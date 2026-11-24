from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


REQUEST_SCHEMA_VERSION = "finance_operation_execute_request_v0"
ORDER_SCHEMA_VERSION = "finance_order_intent_v0"
OUTCOME_SCHEMA_VERSION = "loopx_operation_outcome_v0"
PROTOCOL = "finance_operation_executor_v0"
PERMISSION = "finance.operation.simulate"
OPERATION_KIND = "finance.order.simulate"
_OPAQUE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _token(value: object, *, field: str) -> str:
    result = str(value or "").strip()
    if not _OPAQUE.fullmatch(result):
        raise ValueError(f"{field} must be a compact opaque id")
    return result


def _decimal(value: object, *, field: str, positive: bool = True) -> Decimal:
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{field} must be a positive finite decimal")
    return result


def _normalize_order(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("finance operation payload must be an object")
    allowed = {
        "schema_version",
        "asset",
        "side",
        "quantity",
        "quantity_unit",
        "order_type",
        "limit_price",
        "price_unit",
        "time_in_force",
        "reduce_only",
        "maximum_fee",
        "fee_unit",
    }
    if set(value) - allowed:
        raise ValueError("finance order intent contains unsupported fields")
    if value.get("schema_version") != ORDER_SCHEMA_VERSION:
        raise ValueError(f"finance order intent must use {ORDER_SCHEMA_VERSION}")
    side = str(value.get("side") or "").lower()
    order_type = str(value.get("order_type") or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError("finance order side must be buy or sell")
    if order_type != "limit":
        raise ValueError("the M1 simulator accepts limit orders only")
    if value.get("time_in_force") not in {"GTC", "IOC"}:
        raise ValueError("finance order time_in_force must be GTC or IOC")
    if not isinstance(value.get("reduce_only"), bool):
        raise ValueError("finance order reduce_only must be true or false")
    quantity = _decimal(value.get("quantity"), field="quantity")
    limit_price = _decimal(value.get("limit_price"), field="limit_price")
    maximum_fee = _decimal(value.get("maximum_fee"), field="maximum_fee")
    return {
        "schema_version": ORDER_SCHEMA_VERSION,
        "asset": _token(value.get("asset"), field="asset"),
        "side": side,
        "quantity": str(quantity),
        "quantity_unit": _token(value.get("quantity_unit"), field="quantity_unit"),
        "order_type": order_type,
        "limit_price": str(limit_price),
        "price_unit": _token(value.get("price_unit"), field="price_unit"),
        "time_in_force": value["time_in_force"],
        "reduce_only": value["reduce_only"],
        "maximum_fee": str(maximum_fee),
        "fee_unit": _token(value.get("fee_unit"), field="fee_unit"),
    }


def execute_simulated_finance_operation(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("finance executor request must be an object")
    expected_fields = {
        "schema_version",
        "protocol",
        "permission",
        "operation_id",
        "operation_kind",
        "operation_schema",
        "payload",
        "payload_digest",
        "confirmation_digest",
        "claim_id",
        "executor_revision",
        "destination_account_ref",
    }
    if set(value) != expected_fields:
        raise ValueError("finance executor request has unsupported or missing fields")
    if value.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError(f"finance executor request must use {REQUEST_SCHEMA_VERSION}")
    if value.get("protocol") != PROTOCOL or value.get("permission") != PERMISSION:
        raise ValueError("finance executor protocol or permission is unsupported")
    if value.get("operation_kind") != OPERATION_KIND:
        raise ValueError("finance executor operation kind is unsupported")
    if value.get("operation_schema") != ORDER_SCHEMA_VERSION:
        raise ValueError("finance executor operation schema is unsupported")
    if value.get("destination_account_ref") != "account:simulation":
        raise ValueError("M1 finance execution is restricted to account:simulation")
    operation_id = _token(value.get("operation_id"), field="operation_id")
    claim_id = _token(value.get("claim_id"), field="claim_id")
    confirmation_digest = str(value.get("confirmation_digest") or "")
    payload_digest = str(value.get("payload_digest") or "")
    if not _SHA256.fullmatch(confirmation_digest):
        raise ValueError("confirmation_digest must be lowercase SHA-256")
    if not _SHA256.fullmatch(payload_digest):
        raise ValueError("payload_digest must be lowercase SHA-256")
    order = _normalize_order(value.get("payload"))
    if _digest(value.get("payload")) != payload_digest:
        raise ValueError("payload_digest does not match the finance order intent")
    notional = Decimal(order["quantity"]) * Decimal(order["limit_price"])
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "ok": True,
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "outcome": "simulated_filled",
        "projection_verified": True,
        "operation_id": operation_id,
        "payload_digest": payload_digest,
        "claim_id": claim_id,
        "executor_revision": _token(
            value.get("executor_revision"), field="executor_revision"
        ),
        "summary": (
            f"SIMULATION: {order['side'].upper()} {order['quantity']} "
            f"{order['asset']} at {order['limit_price']} {order['price_unit']}."
        ),
        "details": {
            "asset": order["asset"],
            "side": order["side"],
            "filled_quantity": order["quantity"],
            "average_price": order["limit_price"],
            "notional": str(notional),
            "notional_unit": order["price_unit"],
            "fee": "0",
            "fee_unit": order["fee_unit"],
        },
        "simulation": True,
        "external_write_performed": False,
        "observed_at": observed_at,
    }
