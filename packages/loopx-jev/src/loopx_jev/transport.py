"""One isolated stdlib HTTP request. No SDK, retries, redirected keys or body logs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from .config import Config, strict_json
from .protocol import request_bytes


@dataclass
class TransportFailure(Exception):
    code: str
    dispatch: str = "may_have_been_sent"


def send(request: dict[str, Any], config: Config, key: str) -> dict[str, Any]:
    started_ns = time.perf_counter_ns()
    body = request_bytes(request)
    if len(body) > config.max_request_bytes:
        raise TransportFailure("request_too_large", "not_sent")
    if not key or "\n" in key or "\r" in key:
        raise TransportFailure("invalid_credential", "not_sent")
    worker = Path(__file__).with_name("http_worker.py")
    # The key travels over a private pipe, never argv, logs or a repository file.
    envelope = request_bytes(
        {
            "request": request,
            "key": key,
            "limit": config.max_response_bytes,
            "timeout": config.deadline_ms / 1000,
        }
    )
    started = time.monotonic()
    prepared_ns = time.perf_counter_ns()
    child = subprocess.Popen(
        [sys.executable, "-I", str(worker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}
        },
    )
    spawned_ns = time.perf_counter_ns()
    try:
        remaining = (
            config.deadline_ms / 1000 - (time.perf_counter_ns() - started_ns) / 1e9
        )
        if remaining <= 0:
            raise subprocess.TimeoutExpired("worker", config.deadline_ms / 1000)
        output, _ = child.communicate(envelope, timeout=remaining)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise TransportFailure("deadline_exceeded") from None
    received_ns = time.perf_counter_ns()
    if len(output) > config.max_response_bytes + 4096:
        raise TransportFailure("response_too_large", "response_received")
    try:
        result = strict_json(output)
    except (ValueError, UnicodeError):
        raise TransportFailure("invalid_transport_response") from None
    if child.returncode != 0 or not isinstance(result, dict):
        raise TransportFailure("transport_worker_failed")
    if "error" in result:
        raise TransportFailure(
            str(result["error"]), str(result.get("dispatch", "may_have_been_sent"))
        )
    decoded_ns = time.perf_counter_ns()
    result["transport_timing_ns"] = {
        "prepare": prepared_ns - started_ns,
        "spawn": spawned_ns - prepared_ns,
        "wait_inclusive": received_ns - spawned_ns,
        "decode": decoded_ns - received_ns,
        "total": decoded_ns - started_ns,
    }
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result
