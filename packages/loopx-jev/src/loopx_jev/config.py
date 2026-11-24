"""Explicit default-off settings for the standalone shadow command."""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, NoReturn


def strict_json(raw: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def bad_constant(_: str) -> NoReturn:
        raise ValueError("non-finite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def read_json(path: Path, limit: int = 1024 * 1024) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected a regular local file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input exceeds byte limit")
    return strict_json(raw), hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Config:
    mode: str = "off"
    scenarios: tuple[str, ...] = ("progress_review",)
    model: str = ""
    allow_egress: bool = False
    deadline_ms: int = 5000
    max_requests_per_run: int = 20
    max_request_bytes: int = 65536
    max_response_bytes: int = 65536
    minimum_label_probability: float = 0.6
    generation: str = "off"


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    obj, generation = read_json(path, 16384)
    fields = {
        "schema_version",
        "mode",
        "scenarios",
        "model",
        "allow_egress",
        "limits",
        "minimum_label_probability",
    }
    if (
        not isinstance(obj, dict)
        or set(obj) - fields
        or obj.get("schema_version") != "loopx_jev_drift_config_v0"
    ):
        raise ValueError("invalid_drift_configuration_schema")
    mode = obj.get("mode", "off")
    if mode not in {"off", "shadow"}:
        raise ValueError("drift_supports_off_or_shadow_only")
    if obj.get("scenarios", ["progress_review"]) != ["progress_review"]:
        raise ValueError("only_progress_review_supported")
    model = obj.get("model", "")
    if not isinstance(model, str) or len(model) > 120:
        raise ValueError("invalid_model")
    if mode != "off" and (not model.strip() or "latest" in model.lower()):
        raise ValueError("shadow_requires_pinned_model")
    egress = obj.get("allow_egress", False)
    if not isinstance(egress, bool):
        raise ValueError("invalid_egress_setting")
    limits = obj.get("limits", {})
    bounds = {
        "deadline_ms": (100, 30000),
        "max_requests_per_run": (1, 100),
        "max_request_bytes": (1024, 131072),
        "max_response_bytes": (1024, 131072),
    }
    if not isinstance(limits, dict) or set(limits) - bounds.keys():
        raise ValueError("invalid_request_limits")
    for name, value in limits.items():
        low, high = bounds[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not low <= value <= high
        ):
            raise ValueError("invalid_request_limit")
    minimum = obj.get("minimum_label_probability", 0.6)
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, (float, int))
        or not 0.5 <= minimum <= 1
    ):
        raise ValueError("invalid_label_probability_threshold")
    return Config(
        mode=mode,
        model=model,
        allow_egress=egress,
        generation=generation,
        minimum_label_probability=minimum,
        **limits,
    )
