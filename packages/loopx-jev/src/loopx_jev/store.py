"""Finite local study ledger: atomic reservations, explicit initialization, no implicit retry."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid
from typing import Any

from loopx.file_lock import exclusive_file_lock
from .config import read_json

ID = re.compile(r"^[a-f0-9]{64}$")


def atomic_json(path: Path, value: Any) -> None:
    if path.is_symlink():
        raise ValueError("refusing symlink output")
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2
    ).encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=".jev-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.chmod(name, 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def initialize_run(root: Path, max_requests: int = 20) -> None:
    if (
        isinstance(max_requests, bool)
        or not isinstance(max_requests, int)
        or not 1 <= max_requests <= 100
    ):
        raise ValueError("invalid run budget")
    if root.exists():
        raise ValueError(
            "run directory already exists; inspect it instead of resetting its budget"
        )
    root.mkdir(mode=0o700, parents=True)
    atomic_json(
        root / "manifest.json",
        {
            "schema": "jev_private_run_v0",
            "run_id": uuid.uuid4().hex,
            "created_at": time.time(),
            "max_requests": max_requests,
            "attempts": {},
        },
    )


class RunStore:
    def __init__(self, root: Path):
        if root.is_symlink() or not root.is_dir():
            raise ValueError("initialize a new private run directory explicitly")
        self.root = root
        self.manifest = root / "manifest.json"
        self._read()

    def _read(self) -> dict[str, Any]:
        value, _ = read_json(self.manifest, 1024 * 1024)
        if (
            not isinstance(value, dict)
            or value.get("schema") != "jev_private_run_v0"
            or not isinstance(value.get("attempts"), dict)
            or isinstance(value.get("max_requests"), bool)
            or not isinstance(value.get("max_requests"), int)
            or not 1 <= value["max_requests"] <= 100
        ):
            raise ValueError("invalid private run manifest")
        return value

    def reserve(self, request_id: str, max_requests: int) -> dict[str, Any] | None:
        if not ID.fullmatch(request_id):
            raise ValueError("invalid request identity")
        with exclusive_file_lock(self.manifest):
            value = self._read()
            if request_id in value["attempts"]:
                path = self.root / f"{request_id}.json"
                if path.is_file():
                    previous, _ = read_json(path)
                    if not isinstance(previous, dict):
                        raise ValueError("invalid_stored_attempt")
                    return previous
                # An attempt tombstone outlives its detail; never silently re-send.
                return {
                    "status": "prior_attempt_unresolved",
                    "dispatch": "may_have_been_sent",
                }
            if len(value["attempts"]) >= min(max_requests, value["max_requests"]):
                return {"status": "budget_exhausted", "dispatch": "not_sent"}
            value["attempts"][request_id] = {"reserved_at": time.time()}
            atomic_json(self.manifest, value)
            return None

    def finish(self, request_id: str, record: dict[str, Any]) -> None:
        if not ID.fullmatch(request_id):
            raise ValueError("invalid request identity")
        with exclusive_file_lock(self.manifest):
            value = self._read()
            if request_id not in value["attempts"]:
                raise ValueError("request has no durable reservation")
            path = self.root / f"{request_id}.json"
            if path.exists():
                raise ValueError("attempt result already recorded")
            atomic_json(path, {**record, "request_id": request_id})
