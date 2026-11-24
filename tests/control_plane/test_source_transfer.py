"""Witnessed readback and cleanup protect full source transport, not authority."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from loopx.control_plane import effect_runtime
from loopx.control_plane.coordination.local_authority_shadow_projection import (
    MAX_TRANSFER_BYTES, TRANSFER_RESULT_SCHEMA, source_effect_runtime_result,
)


@pytest.mark.parametrize("fault", [None, "digest", "request", "method", "size", "bool_size", "symlink", "runtime"])
def test_readback_is_bound_and_temporary_files_are_removed(monkeypatch, fault):
    if fault == "symlink" and os.name == "nt":
        pytest.skip("creating symlinks requires Windows developer privileges")
    directories = []

    def invoke(method, envelope, **kwargs):
        directory = Path(envelope["directory"])
        directories.append(directory)
        assert json.loads((directory / "request.json").read_text()) == {"todos": ["完整🙂"]}
        assert len(json.dumps(envelope).encode()) < 1024
        if fault == "runtime":
            raise RuntimeError("original operation may have committed")
        data = b'{"complete":true}'
        target = directory / "result.json"
        if fault == "symlink":
            (directory / "other.json").write_bytes(data)
            target.symlink_to(directory / "other.json")
        else:
            target.write_bytes(data)
        result = {"schema_version": TRANSFER_RESULT_SCHEMA, "method": method,
                  "request_sha256": envelope["request_sha256"], "result_sha256": hashlib.sha256(data).hexdigest(),
                  "result_bytes": len(data)}
        if fault == "digest":
            result["result_sha256"] = "0" * 64
        elif fault == "request":
            result["request_sha256"] = "0" * 64
        elif fault == "method":
            result["method"] = "another.operation"
        elif fault == "size":
            result["result_bytes"] = len(data) + 1
        elif fault == "bool_size":
            result["result_bytes"] = True
        return result

    monkeypatch.setattr(effect_runtime, "effect_runtime_result", invoke)
    if fault is None:
        assert source_effect_runtime_result("coordination.source.project", {"todos": ["完整🙂"]}) == {"complete": True}
    else:
        with pytest.raises((effect_runtime.EffectRuntimeRejected, RuntimeError)):
            source_effect_runtime_result("coordination.source.project", {"todos": ["完整🙂"]})
    assert directories and all(not path.exists() for path in directories)


def test_oversized_source_rejects_before_runtime(monkeypatch):
    monkeypatch.setattr(effect_runtime, "effect_runtime_result", lambda *args, **kwargs: pytest.fail("must not dispatch"))
    with pytest.raises(effect_runtime.EffectRuntimeRejected, match="16 MiB"):
        source_effect_runtime_result("coordination.source.project", {"note": "x" * MAX_TRANSFER_BYTES})
