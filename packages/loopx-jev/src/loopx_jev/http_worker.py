"""Private one-shot transport worker. Never print exception text or response bodies."""

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def main() -> None:
    worker_started = time.perf_counter_ns()
    try:
        envelope = json.loads(sys.stdin.buffer.read(270000))
        limit = int(envelope["limit"])
        if not 1024 <= limit <= 131072:
            raise ValueError("limit")
        raw = json.dumps(
            envelope["request"],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        key = envelope.pop("key")
        if not isinstance(key, str) or not key or any(c in key for c in "\r\n"):
            raise ValueError("key")
        request = urllib.request.Request(
            ENDPOINT,
            raw,
            {
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        http_started = time.perf_counter_ns()
        with opener.open(request, timeout=float(envelope["timeout"])) as response:
            headers_received = time.perf_counter_ns()
            payload = response.read(limit + 1)
            body_received = time.perf_counter_ns()
        if len(payload) > limit:
            result = {"error": "response_too_large", "dispatch": "response_received"}
        else:
            # Check framing without normalizing the provider bytes: converting
            # to a dict here would erase duplicate keys before strict_json in
            # the parent can reject an ambiguous answer. Keep the bounded body
            # inside the private pipe, never in diagnostics or persisted logs.
            json.loads(payload)
            timing = {
                "prepare": http_started - worker_started,
                "request_to_headers": headers_received - http_started,
                "body_read": body_received - headers_received,
                "framing": time.perf_counter_ns() - body_received,
            }
            prefix = json.dumps(
                {"dispatch": "response_received", "worker_timing_ns": timing}
            ).encode()[:-1]
            sys.stdout.buffer.write(prefix + b',"response":' + payload + b"}")
            return
    except urllib.error.HTTPError as exc:
        # Do not log remote error content, which may reflect submitted inputs.
        result = {"error": "http_" + str(exc.code), "dispatch": "response_received"}
    except (urllib.error.URLError, TimeoutError, OSError):
        result = {"error": "network_unavailable", "dispatch": "may_have_been_sent"}
    except (ValueError, KeyError, TypeError, UnicodeError):
        result = {"error": "invalid_transport_data", "dispatch": "may_have_been_sent"}
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
