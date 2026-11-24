"""Build public-safe, simulation-only Finance operation requests.

This module is the Finance-owned producer for LoopX Core's canonical
``operation.execute`` envelope.  It validates domain semantics and emits one
immutable request; Core remains the owner of persistence, human confirmation,
delivery, claim consumption, and outcome readback.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from ipaddress import ip_address
import json
import re
from typing import Any
from urllib.parse import urlparse

from .presentation_validation import evidence_reference


FINANCE_TRANSACTION_APPROVAL_INPUT_SCHEMA_VERSION = (
    "finance_transaction_approval_input_v0"
)
FINANCE_TRANSACTION_APPROVAL_PACKET_SCHEMA_VERSION = (
    "finance_transaction_approval_packet_v0"
)
LOOPX_OPERATION_REQUEST_SCHEMA_VERSION = "loopx_operation_request_v0"
LOOPX_OPERATION_PROJECTION_SCHEMA_VERSION = "loopx_operation_projection_v0"
FINANCE_ORDER_INTENT_SCHEMA_VERSION = "finance_order_intent_v0"
FINANCE_EXECUTOR_EXTENSION_ID = "loopx-finance-execution"
FINANCE_EXECUTOR_PROTOCOL = "finance_operation_executor_v0"
FINANCE_EXECUTOR_PERMISSION = "finance.operation.simulate"
FINANCE_OPERATION_KIND = "finance.order.simulate"

_OPAQUE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_PRINCIPAL = re.compile(r"^[a-z][a-z0-9._-]{0,30}:[A-Za-z0-9._:-]{1,200}$")
_PRIVATE_TEXT = (
    re.compile(r"\bBearer\s+", re.IGNORECASE),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _text(value: object, *, field: str, limit: int) -> str:
    result = " ".join(str(value or "").split())
    if not result:
        raise ValueError(f"{field} is required")
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    if any(pattern.search(result) for pattern in _PRIVATE_TEXT):
        raise ValueError(f"{field} contains private or credential-like text")
    return result


def _token(value: object, *, field: str) -> str:
    result = str(value or "").strip()
    if not _OPAQUE.fullmatch(result):
        raise ValueError(f"{field} must be a compact opaque id")
    return result


def _decimal(value: object, *, field: str, minimum: Decimal | None = None) -> Decimal:
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not result.is_finite() or (minimum is not None and result < minimum):
        raise ValueError(f"{field} must be a finite decimal >= {minimum}")
    return result


def _future_expiry(value: object, *, now: datetime) -> str:
    text = _text(value, field="expires_at", limit=80)
    try:
        expires_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if expires_at.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    expires_at = expires_at.astimezone(UTC)
    if not now < expires_at <= now + timedelta(days=7):
        raise ValueError("expires_at must be within the next seven days")
    return expires_at.isoformat().replace("+00:00", "Z")


def _evidence_observed_at(value: object, *, now: datetime) -> str:
    text = _text(value, field="evidence_observed_at", limit=80)
    try:
        observed_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "evidence_observed_at must be an ISO-8601 timestamp"
        ) from exc
    if observed_at.tzinfo is None:
        raise ValueError("evidence_observed_at must include a timezone")
    observed_at = observed_at.astimezone(UTC)
    if observed_at > now:
        raise ValueError("evidence_observed_at must not be in the future")
    return observed_at.isoformat().replace("+00:00", "Z")


def _public_evidence_ref(value: object, *, index: int) -> dict[str, str]:
    field = f"evidence_refs[{index}]"
    if not isinstance(value, Mapping) or set(value) != {"label", "ref"}:
        raise ValueError(f"{field} must contain exactly label and ref")
    label = _text(value.get("label"), field=f"{field}.label", limit=36)
    ref = evidence_reference(value.get("ref"), context=f"{field}.ref")
    parsed = urlparse(ref)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{field}.ref must be a public HTTPS URL")
    hostname = (parsed.hostname or "").lower()
    local_hostname = (
        hostname == "localhost"
        or hostname.endswith((".local", ".internal", ".corp", ".lan"))
        or hostname.startswith(("private.", "internal."))
    )
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    local_address = bool(
        address
        and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        )
    )
    if local_hostname or local_address:
        raise ValueError(f"{field}.ref must not target a local address")
    return {"label": label, "ref": ref}


def _text_list(
    value: object,
    *,
    field: str,
    minimum: int,
    maximum: int,
    item_limit: int,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field} must be a list")
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} must contain {minimum}-{maximum} items")
    result = [
        _text(item, field=f"{field}[{index}]", limit=item_limit)
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def build_finance_transaction_approval_packet(
    value: object,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate one transaction request and emit Core's canonical request.

    The output can be passed directly to ``loopx goal-channel
    prepare-operation`` after selecting ``operation_request``.  It is always a
    simulation and never carries venue, signer, wallet, transfer, or credential
    authority.
    """

    if not isinstance(value, Mapping):
        raise ValueError("finance transaction approval input must be an object")
    allowed = {
        "schema_version",
        "request_id",
        "candidate_ref",
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
        "expected_edge_bps",
        "maximum_cost_bps",
        "evidence_observed_at",
        "evidence_refs",
        "no_trade_conditions",
        "expires_at",
        "authorized_principals",
        "executor_revision",
        "simulation",
    }
    if set(value) - allowed:
        raise ValueError("finance transaction approval input has unsupported fields")
    if value.get("schema_version") != FINANCE_TRANSACTION_APPROVAL_INPUT_SCHEMA_VERSION:
        raise ValueError(
            "schema_version must be "
            f"{FINANCE_TRANSACTION_APPROVAL_INPUT_SCHEMA_VERSION}"
        )
    if value.get("simulation") is not True:
        raise ValueError("simulation must be true")

    request_id = _token(value.get("request_id"), field="request_id")
    candidate_ref = _token(value.get("candidate_ref"), field="candidate_ref")
    asset = _token(value.get("asset"), field="asset")
    side = str(value.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    order_type = str(value.get("order_type") or "").lower()
    if order_type != "limit":
        raise ValueError("the simulation request accepts limit orders only")
    time_in_force = value.get("time_in_force")
    if time_in_force not in {"GTC", "IOC"}:
        raise ValueError("time_in_force must be GTC or IOC")
    if not isinstance(value.get("reduce_only"), bool):
        raise ValueError("reduce_only must be true or false")

    quantity = _decimal(value.get("quantity"), field="quantity", minimum=Decimal("0"))
    limit_price = _decimal(
        value.get("limit_price"), field="limit_price", minimum=Decimal("0")
    )
    maximum_fee = _decimal(
        value.get("maximum_fee"), field="maximum_fee", minimum=Decimal("0")
    )
    if quantity == 0 or limit_price == 0 or maximum_fee == 0:
        raise ValueError(
            "quantity, limit_price, and maximum_fee must be greater than zero"
        )
    expected_edge_bps = _decimal(
        value.get("expected_edge_bps"),
        field="expected_edge_bps",
        minimum=Decimal("0"),
    )
    maximum_cost_bps = _decimal(
        value.get("maximum_cost_bps"),
        field="maximum_cost_bps",
        minimum=Decimal("0"),
    )
    if expected_edge_bps <= maximum_cost_bps:
        raise ValueError("expected_edge_bps must exceed maximum_cost_bps")

    quantity_unit = _token(value.get("quantity_unit"), field="quantity_unit")
    price_unit = _token(value.get("price_unit"), field="price_unit")
    fee_unit = _token(value.get("fee_unit"), field="fee_unit")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    evidence_observed_at = _evidence_observed_at(
        value.get("evidence_observed_at"), now=current
    )
    evidence_value = value.get("evidence_refs")
    if (
        not isinstance(evidence_value, Sequence)
        or isinstance(evidence_value, (str, bytes, bytearray))
        or not 1 <= len(evidence_value) <= 3
    ):
        raise ValueError("evidence_refs must contain 1-3 items")
    evidence_refs = [
        _public_evidence_ref(item, index=index)
        for index, item in enumerate(evidence_value)
    ]
    if len({item["ref"] for item in evidence_refs}) != len(evidence_refs):
        raise ValueError("evidence_refs must use unique refs")
    no_trade_conditions = _text_list(
        value.get("no_trade_conditions"),
        field="no_trade_conditions",
        minimum=1,
        maximum=3,
        item_limit=120,
    )
    principals_value = value.get("authorized_principals")
    if (
        not isinstance(principals_value, Sequence)
        or isinstance(principals_value, (str, bytes, bytearray))
        or not 1 <= len(principals_value) <= 20
    ):
        raise ValueError("authorized_principals must contain 1-20 identities")
    principals: list[str] = []
    for raw_principal in principals_value:
        principal = str(raw_principal or "").strip()
        if not _PRINCIPAL.fullmatch(principal):
            raise ValueError(
                "authorized_principals must use provider:subject identities"
            )
        if principal not in principals:
            principals.append(principal)
    executor_revision = _token(
        value.get("executor_revision"), field="executor_revision"
    )
    expires_at = _future_expiry(value.get("expires_at"), now=current)

    payload = {
        "schema_version": FINANCE_ORDER_INTENT_SCHEMA_VERSION,
        "asset": asset,
        "side": side,
        "quantity": str(quantity),
        "quantity_unit": quantity_unit,
        "order_type": order_type,
        "limit_price": str(limit_price),
        "price_unit": price_unit,
        "time_in_force": time_in_force,
        "reduce_only": value["reduce_only"],
        "maximum_fee": str(maximum_fee),
        "fee_unit": fee_unit,
    }
    maximum_notional = quantity * limit_price
    fields = [
        {"label": "Candidate", "value": candidate_ref},
        {
            "label": "Action",
            "value": (
                f"{side.upper()} {quantity} {quantity_unit} · LIMIT "
                f"{limit_price} {price_unit} · {time_in_force}"
            ),
        },
        {
            "label": "Maximum notional",
            "value": f"{maximum_notional} {price_unit}",
        },
        {
            "label": "Economics",
            "value": (
                f"edge {expected_edge_bps} bps · max cost {maximum_cost_bps} bps · "
                f"max fee {maximum_fee} {fee_unit}"
            ),
        },
        {"label": "Expires", "value": expires_at},
        {"label": "Evidence observed", "value": evidence_observed_at},
        *[
            {"label": f"Evidence {index + 1}: {item['label']}", "value": item["ref"]}
            for index, item in enumerate(evidence_refs)
        ],
        *[
            {"label": f"No-trade {index + 1}", "value": condition}
            for index, condition in enumerate(no_trade_conditions)
        ],
    ]
    for index, field in enumerate(fields):
        if len(field["label"]) > 40 or len(field["value"]) > 120:
            raise ValueError(
                f"operation projection field {index + 1} exceeds Core limits"
            )
    projection = {
        "schema_version": LOOPX_OPERATION_PROJECTION_SCHEMA_VERSION,
        "title": "Simulated finance transaction request",
        "subtitle": f"{candidate_ref} · human confirmation required",
        "focus": (f"{side.upper()} {quantity} {asset} @ {limit_price} {price_unit}"),
        "fields": fields,
        "warning": (
            "Simulation only. Approval cannot submit an order, sign, move funds, "
            "or grant real-trading authority. Reject if any no-trade condition is met."
        ),
        "simulated": True,
    }
    operation_request = {
        "schema_version": LOOPX_OPERATION_REQUEST_SCHEMA_VERSION,
        "domain": "finance",
        "operation_kind": FINANCE_OPERATION_KIND,
        "operation_schema": FINANCE_ORDER_INTENT_SCHEMA_VERSION,
        "payload_ref": f"finance-order:{request_id}",
        "payload": payload,
        "payload_digest": _digest(payload),
        "projection": projection,
        "destination_account_ref": "account:simulation",
        "expires_at": expires_at,
        "authorized_principals": principals,
        "executor": {
            "extension_id": FINANCE_EXECUTOR_EXTENSION_ID,
            "protocol": FINANCE_EXECUTOR_PROTOCOL,
            "permission": FINANCE_EXECUTOR_PERMISSION,
            "revision": executor_revision,
        },
    }
    request_digest = _digest(operation_request)
    return {
        "ok": True,
        "schema_version": FINANCE_TRANSACTION_APPROVAL_PACKET_SCHEMA_VERSION,
        "mode": "finance-transaction-approval",
        "summary": (
            f"Prepared simulation-only approval request {request_id} for {asset}."
        ),
        "idempotency_key": f"finance-operation-{request_digest[:32]}",
        "operation_request_digest": request_digest,
        "operation_request": operation_request,
        "boundary": {
            "simulation": True,
            "human_confirmation_required": True,
            "real_order_allowed": False,
            "signature_allowed": False,
            "transfer_allowed": False,
            "external_write_performed": False,
        },
    }
