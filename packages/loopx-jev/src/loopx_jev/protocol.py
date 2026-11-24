"""Finite response and wire validation; no scheduling authority."""

from __future__ import annotations
import json
import math
from typing import Any


def validate_choice(answer: Any, labels: tuple[str, ...]) -> tuple[str, float]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("invalid_answer_type")
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(labels):
        raise ValueError("invalid_probability_domain")
    if any(
        isinstance(v, bool)
        or not isinstance(v, (float, int))
        or not math.isfinite(v)
        or not 0 <= v <= 1
        for v in probabilities.values()
    ):
        raise ValueError("invalid_probability")
    if abs(sum(probabilities.values()) - 1) > 1e-4:
        raise ValueError("invalid_probability_sum")
    choice = answer.get("choice")
    if choice not in labels or probabilities[choice] + 1e-9 < max(
        probabilities.values()
    ):
        raise ValueError("invalid_selected_choice")
    confidence = answer.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (float, int))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ValueError("invalid_confidence")
    return choice, probabilities[choice]


def request_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_noul(answer: Any) -> float:
    """Return the calibrated probability of one Noul (yes/no) answer."""

    if not isinstance(answer, dict) or answer.get("type") != "noul":
        raise ValueError("invalid_answer_type")
    value = answer.get("noul")
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("invalid_noul_probability")
    return float(value)
