from __future__ import annotations

from enum import Enum
from typing import Any


class DeliveryBatchScale(str, Enum):
    """Structured machine signal for the scale of a delivery run."""

    TEST_ONLY = "test_only"
    SINGLE_SURFACE = "single_surface"
    MULTI_SURFACE = "multi_surface"
    IMPLEMENTATION = "implementation"


DELIVERY_BATCH_SCALE_CHOICES = tuple(scale.value for scale in DeliveryBatchScale)
DELIVERY_BATCH_SCALE_ALIASES: dict[str, DeliveryBatchScale] = {
    "single_segment": DeliveryBatchScale.SINGLE_SURFACE,
    "bounded_segment": DeliveryBatchScale.SINGLE_SURFACE,
}
# Historical runs used segment-shaped names before scale became a typed write
# contract.  Readers retain those aliases, but accepting them for new writes
# silently invents a surface count: in particular, a bounded segment can span
# one or many surfaces.  New writers must choose the canonical scale explicitly.
DELIVERY_BATCH_SCALE_INPUT_CHOICES = DELIVERY_BATCH_SCALE_CHOICES
SMALL_DELIVERY_BATCH_SCALES = frozenset(
    {
        DeliveryBatchScale.TEST_ONLY,
        DeliveryBatchScale.SINGLE_SURFACE,
    }
)
UNKNOWN_DELIVERY_BATCH_SCALE = "unknown"


def normalize_delivery_batch_scale(value: Any) -> DeliveryBatchScale | None:
    if isinstance(value, DeliveryBatchScale):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    alias = DELIVERY_BATCH_SCALE_ALIASES.get(text)
    if alias:
        return alias
    try:
        return DeliveryBatchScale(text)
    except ValueError:
        return None


def require_delivery_batch_scale(value: Any) -> DeliveryBatchScale:
    text = str(value or "").strip()
    if not isinstance(value, DeliveryBatchScale) and text in DELIVERY_BATCH_SCALE_ALIASES:
        raise ValueError(
            f"delivery_batch_scale legacy alias {text!r} is read-only and ambiguous for new "
            "writes; choose one of: " + ", ".join(DELIVERY_BATCH_SCALE_CHOICES)
        )
    scale = normalize_delivery_batch_scale(value)
    if scale is None:
        raise ValueError(
            "delivery_batch_scale must be one of: "
            + ", ".join(DELIVERY_BATCH_SCALE_CHOICES)
        )
    return scale


def delivery_batch_scale_value(value: Any) -> str | None:
    scale = normalize_delivery_batch_scale(value)
    return scale.value if scale else None
