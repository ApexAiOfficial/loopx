from __future__ import annotations

import threading

from loopx.chat_runtime import _TurnEventBuffer


class _TransientFlushStore:
    def __init__(self) -> None:
        self.flush_calls = 0
        self.first_attempt = threading.Event()
        self.retry_attempt = threading.Event()

    def load_turn(self, _session_id: str, _turn_id: str) -> dict[str, object]:
        return {}

    def flush_events(self, _session_id: str, _turn_id: str) -> None:
        self.flush_calls += 1
        if self.flush_calls == 1:
            self.first_attempt.set()
            raise OSError("transient flush failure")
        self.retry_attempt.set()


def test_turn_event_buffer_retries_after_transient_flush_failure() -> None:
    store = _TransientFlushStore()
    buffer = _TurnEventBuffer(
        store=store,  # type: ignore[arg-type]
        session_id="session",
        turn_id="turn",
        event_flush_interval_sec=0.01,
    )
    try:
        assert store.first_attempt.wait(timeout=1)
        assert store.retry_attempt.wait(timeout=1)
    finally:
        buffer.stop_event.set()
        buffer.flush_thread.join(timeout=1)
