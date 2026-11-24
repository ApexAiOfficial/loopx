"""Complete accounting across long, growing and partially written rollouts."""

import json
import tracemalloc
from pathlib import Path

import pytest

from loopx.control_plane.quota.codex_session_usage import (
    CodexSessionUsageError,
    read_codex_session_usage,
)


def usage(tokens: int) -> bytes:
    return json.dumps({
        "type": "event_msg", "timestamp": f"2026-09-24T00:00:{tokens:02d}Z",
        "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": tokens, "output_tokens": 2, "cached_input_tokens": 0,
        }}},
    }).encode() + b"\n"


@pytest.fixture
def rollout(tmp_path):
    path = tmp_path / "rollout.jsonl"
    header = [
        {"type": "session_meta", "payload": {"id": "session-stream"}},
        {"type": "turn_context", "payload": {"model": "model-a"}},
    ]
    path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in header) + usage(10))
    return path


def test_accounting_reads_past_large_irrelevant_history_with_bounded_memory(rollout):
    # A sampled prefix would return 10 instead of the newest cumulative 20.
    with rollout.open("ab") as stream:
        event = json.dumps({"type": "response_item", "payload": {"text": "x" * 8192}}).encode() + b"\n"
        for _ in range(512):
            stream.write(event)
        stream.write(usage(20))

    tracemalloc.start()
    try:
        observed = read_codex_session_usage(rollout)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # 4 MiB of transcript with 8 KiB records must not require a whole-file
    # allocation. Leave ample headroom for decoder/interpreter differences.
    assert peak < 1024 * 1024
    assert observed["input_tokens"] == 20
    assert observed["model"] == "model-a"
    assert observed["source_snapshot_id"].endswith("00:00:20Z")
    assert "payload" not in observed


def test_read_does_not_chase_events_appended_after_open_snapshot(rollout, monkeypatch):
    original = Path.open

    class GrowingFile:
        def __init__(self, stream):
            self.stream = stream
            self.grown = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def readline(self, size=-1):
            if not self.grown:
                self.grown = True
                with original(rollout, "ab") as writer:
                    writer.write(usage(20))
            return self.stream.readline(size)

    def growing_open(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return GrowingFile(stream) if path == rollout and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", growing_open)
    assert read_codex_session_usage(rollout)["input_tokens"] == 10
    monkeypatch.setattr(Path, "open", original)
    assert read_codex_session_usage(rollout)["input_tokens"] == 20


def test_partial_utf8_append_preserves_last_complete_usage(rollout):
    with rollout.open("ab") as stream:
        stream.write(b'{"type":"response_item","text":"' + "中".encode()[:2])
    assert read_codex_session_usage(rollout)["input_tokens"] == 10


def test_unicode_text_separators_are_not_jsonl_record_boundaries(rollout):
    with rollout.open("ab") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": {
            "text": "one\u2028two\u0085three",
        }}, ensure_ascii=False).encode() + b"\n" + usage(20))
    assert read_codex_session_usage(rollout)["input_tokens"] == 20


def test_file_truncated_during_scan_does_not_book_a_stale_prefix(rollout, monkeypatch):
    original = Path.open

    class TruncatedFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def readline(self, size=-1):
            # Opening size has already been captured, but no payload was read.
            with original(rollout, "wb"):
                pass
            return self.stream.readline(size)

    def truncated_open(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return TruncatedFile(stream) if path == rollout and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", truncated_open)
    with pytest.raises(CodexSessionUsageError, match="truncated during read"):
        read_codex_session_usage(rollout)


@pytest.mark.parametrize("suffix", [b"\n", b"\n\n", b"\n" + usage(20)])
def test_invalid_utf8_is_not_treated_as_concurrent_append(rollout, suffix):
    with rollout.open("ab") as stream:
        stream.write(b'{"text":"\xff"}' + suffix)
    with pytest.raises(CodexSessionUsageError, match="line 4.*corrupt"):
        read_codex_session_usage(rollout)


@pytest.mark.parametrize("suffix", [b"", b"\n", b"\n \n"])
def test_torn_final_json_keeps_existing_blank_line_semantics(rollout, suffix):
    with rollout.open("ab") as stream:
        stream.write(b'{"type":' + suffix)
    assert read_codex_session_usage(rollout)["input_tokens"] == 10


@pytest.mark.parametrize("following", [usage(20), b"null\n", b"{broken}\n"])
def test_interior_damage_refuses_even_when_later_usage_is_valid(rollout, following):
    with rollout.open("ab") as stream:
        stream.write(b'{"type":\n \n' + following)
    with pytest.raises(CodexSessionUsageError, match="line 4.*corrupt"):
        read_codex_session_usage(rollout)
