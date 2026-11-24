"""Connector-registry state files stay UTF-8 on a non-UTF-8 host locale.

``Path.read_text()``/``Path.write_text()`` without an explicit ``encoding``
resolve through ``io.text_encoding(None)`` to the host locale, which is cp936 on
a zh-CN Windows host. JSON is UTF-8 by specification, so on such a host the
writer and the reader disagree: the registry silently reverts to its builtin
catalog and every locally registered connector is lost with exit status 0.

Faking the decoder selection keeps this regression portable -- it needs no cp936
machine, which no CI runner provides. An explicit ``encoding=`` still wins, so
only call sites that omit it change. This is the file-I/O analogue of the
``subprocess._text_encoding`` fake in ``tests/test_doctor_git_encoding.py``.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from loopx.capabilities.connector_registry.core import (
    load_connector_registry,
    register_connector,
    save_connector_registry,
)


@pytest.fixture
def non_utf8_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(io, "text_encoding", lambda encoding=None: encoding or "gbk")


def test_registry_round_trips_on_a_non_utf8_host(
    tmp_path: Path, non_utf8_host: None
) -> None:
    # The fake must be in effect, or this test would pass vacuously on a UTF-8
    # host and prove nothing. GBK decodes these bytes into mojibake rather than
    # raising, so assert on the value instead of on an exception.
    probe = tmp_path / "probe.txt"
    probe.write_bytes("用户任务".encode("utf-8"))
    assert probe.read_text() != "用户任务", "the non_utf8_host fake is not in effect"

    path = tmp_path / "connector-registry.json"
    state = load_connector_registry(path)
    result = register_connector(
        state, "probe-connector", name="中文连接器", status="supported"
    )
    save_connector_registry(
        {**state, "connectors": result["connectors"], "usage": result["usage_map"]},
        path,
    )

    # A writer must not produce bytes its own reader cannot decode.
    path.read_bytes().decode("utf-8")

    reloaded = load_connector_registry(path)
    entry = next(c for c in reloaded["connectors"] if c["id"] == "probe-connector")
    assert entry["name"] == "中文连接器"
    assert entry["status"] == "supported"
