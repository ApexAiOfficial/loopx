"""Offline coverage assessment of normalized, read-only source receipts.

Transport adapters own source decoding, market identity and snapshot assertions.
A complete result covers only the supplied query and asserted snapshot. It does
not establish source truth, publication time, new economic events or alpha.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .boundary import reject_forbidden_material
from .presentation_validation import (
    boolean,
    bounded_list,
    enum,
    evidence_reference,
    identifier,
    iso_value,
    number,
    plain_text,
    record,
)

MAX_PAGES = 128
MAX_ROWS_PER_PAGE = 500
MAX_ROWS = 5000
MAX_PERIOD_METRICS = 24
MAX_METRIC_COMPONENTS = 32
MAX_SPOT_MARKETS = 64
MAX_SPOT_TOKENS = 128
PAGE_FIELDS = {
    "request_identity",
    "page_number",
    "source_status",
    "started_at",
    "observed_at",
    "rows",
    "total_count",
    "has_more",
    "snapshot_id",
    "snapshot_evidence_ref",
}
ROW_FIELDS = {"id", "market", "content_sha256", "publication_at"}
SOURCE_PERIOD_METRIC_FIELDS = {
    "metric_id",
    "label",
    "event_namespace",
    "event_id",
    "event_at",
    "instrument_id",
    "scope_id",
    "period_start",
    "period_end",
    "source_state",
    "value",
    "unit",
    "metric_basis",
    "metric_semantics",
    "value_origin",
    "value_precision",
    "observation_authority",
    "sign_basis",
    "fee_inclusion",
    "account_scope",
    "account_value_role",
    "includes_isolated_margin",
    "expected_components",
    "observed_components",
    "double_counted_components",
    "numerator_scope",
    "denominator_scope",
    "lineage_id",
    "source_ref",
    "methodology_state",
    "anomaly_state",
}
SOURCE_PERIOD_METRIC_DERIVED_FIELDS = {
    "event_identity",
    "coverage_state",
    "missing_components",
    "lineage_state",
    "duplicate_of",
    "independent_evidence",
    "gap_reasons",
    "account_nav_treatment",
    "ready_eligible",
    "admission_reason",
}

_OBSERVATION_AUTHORITY_RANK = {
    "fill_vwap": 0,
    "source_reported_exact": 1,
    "derived_exact": 2,
    "source_reported_rounded": 3,
    "rounded_position_entry": 4,
    "derived_rounded": 5,
}

SPOT_MARKET_IDENTITY_FIELDS = {"pairs", "tokens", "contexts", "markets"}
SPOT_PAIR_FIELDS = {"name", "asset_indexes", "is_canonical", "source_ref"}
SPOT_TOKEN_FIELDS = {"index", "symbol", "source_ref"}
SPOT_CONTEXT_FIELDS = {"coin", "observed_at", "mark_price", "source_ref"}


class CoverageState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNSTABLE = "unstable"
    SOURCE_ERROR = "source_error"


def _period_date(value: object, *, context: str) -> str:
    result = iso_value(value, context=context)
    if "T" in result:
        raise ValueError(f"{context} must be an ISO-8601 calendar date")
    return result


def _identifier_list(
    value: object,
    *,
    context: str,
    minimum: int = 0,
) -> list[str]:
    items = [
        identifier(item, context=f"{context}[{index}]")
        for index, item in enumerate(
            bounded_list(
                value,
                context=context,
                minimum=minimum,
                maximum=MAX_METRIC_COMPONENTS,
            )
        )
    ]
    if len(items) != len(set(items)):
        raise ValueError(f"{context} must not contain duplicate identifiers")
    return items


def _source_period_metric(value: object, *, index: int) -> dict[str, Any]:
    context = f"source_period_metrics[{index}]"
    item = record(
        value,
        context=context,
        allowed=SOURCE_PERIOD_METRIC_FIELDS | SOURCE_PERIOD_METRIC_DERIVED_FIELDS,
    )
    period_start = _period_date(
        item.get("period_start"), context=f"{context}.period_start"
    )
    period_end = _period_date(item.get("period_end"), context=f"{context}.period_end")
    if period_start > period_end:
        raise ValueError(f"{context} period_start must not be after period_end")
    expected = _identifier_list(
        item.get("expected_components"),
        context=f"{context}.expected_components",
        minimum=1,
    )
    observed = _identifier_list(
        item.get("observed_components"),
        context=f"{context}.observed_components",
    )
    double_counted = _identifier_list(
        item.get("double_counted_components"),
        context=f"{context}.double_counted_components",
    )
    numerator_scope = _identifier_list(
        item.get("numerator_scope"),
        context=f"{context}.numerator_scope",
    )
    denominator_scope = _identifier_list(
        item.get("denominator_scope"),
        context=f"{context}.denominator_scope",
    )
    expected_set, observed_set = set(expected), set(observed)
    if not observed_set <= expected_set:
        raise ValueError(f"{context}.observed_components must be expected")
    if not set(double_counted) <= observed_set:
        raise ValueError(f"{context}.double_counted_components must be observed")
    if set(double_counted) & set(numerator_scope):
        raise ValueError(
            f"{context}.numerator_scope must exclude double-counted components"
        )
    source_state = enum(
        item.get("source_state"),
        {"ok", "error"},
        context=f"{context}.source_state",
    )
    metric_value = (
        None
        if item.get("value") is None
        else number(item.get("value"), context=f"{context}.value")
    )
    if metric_value is not None and not numerator_scope:
        raise ValueError(f"{context}.numerator_scope is required with a value")
    if source_state == "ok" and not set(numerator_scope) <= observed_set:
        raise ValueError(f"{context}.numerator_scope must be observed")
    if source_state == "error" and (metric_value is not None or observed):
        raise ValueError(
            f"{context} source_error cannot carry a value or observed components"
        )
    metric_semantics = enum(
        item.get("metric_semantics"),
        {
            "generic",
            "entry_price",
            "cash_delta",
            "cumulative_funding_cost",
            "fill_fee",
            "account_nav",
            "account_component",
            "withdrawable",
            "external_asset_coverage",
        },
        context=f"{context}.metric_semantics",
    )
    value_origin = enum(
        item.get("value_origin"),
        {"source_reported", "derived"},
        context=f"{context}.value_origin",
    )
    value_precision = enum(
        item.get("value_precision"),
        {"exact", "rounded"},
        context=f"{context}.value_precision",
    )
    observation_authority = enum(
        item.get("observation_authority"),
        set(_OBSERVATION_AUTHORITY_RANK),
        context=f"{context}.observation_authority",
    )
    authority_shape = {
        "source_reported_exact": ("source_reported", "exact"),
        "source_reported_rounded": ("source_reported", "rounded"),
        "derived_exact": ("derived", "exact"),
        "derived_rounded": ("derived", "rounded"),
        "fill_vwap": ("derived", "exact"),
        "rounded_position_entry": ("source_reported", "rounded"),
    }[observation_authority]
    if (value_origin, value_precision) != authority_shape:
        raise ValueError(
            f"{context}.observation_authority conflicts with value origin/precision"
        )
    if observation_authority in {"fill_vwap", "rounded_position_entry"} and (
        metric_semantics != "entry_price"
    ):
        raise ValueError(
            f"{context}.{observation_authority} requires entry_price semantics"
        )

    sign_basis = enum(
        item.get("sign_basis"),
        {"not_signed", "account_cash_change", "funding_cost", "fee_cost"},
        context=f"{context}.sign_basis",
    )
    required_sign_basis = {
        "cash_delta": "account_cash_change",
        "cumulative_funding_cost": "funding_cost",
        "fill_fee": "fee_cost",
    }.get(metric_semantics, "not_signed")
    if sign_basis != required_sign_basis:
        raise ValueError(
            f"{context}.sign_basis must be {required_sign_basis} for {metric_semantics}"
        )

    fee_inclusion = enum(
        item.get("fee_inclusion"),
        {"not_applicable", "builder_included"},
        context=f"{context}.fee_inclusion",
    )
    required_fee_inclusion = (
        "builder_included" if metric_semantics == "fill_fee" else "not_applicable"
    )
    if fee_inclusion != required_fee_inclusion:
        raise ValueError(
            f"{context}.fee_inclusion must be {required_fee_inclusion} for "
            f"{metric_semantics}"
        )

    account_scope = enum(
        item.get("account_scope"),
        {"not_applicable", "product", "venue", "unified_account", "external_asset"},
        context=f"{context}.account_scope",
    )
    account_value_role = enum(
        item.get("account_value_role"),
        {
            "not_applicable",
            "nav_owner",
            "composition",
            "reconciliation",
            "withdrawable",
            "coverage",
        },
        context=f"{context}.account_value_role",
    )
    includes_isolated_margin = boolean(
        item.get("includes_isolated_margin"),
        context=f"{context}.includes_isolated_margin",
    )
    account_shape = {
        "account_nav": ({"unified_account"}, {"nav_owner"}),
        "account_component": (
            {"product", "venue"},
            {"composition", "reconciliation"},
        ),
        "withdrawable": ({"venue"}, {"withdrawable"}),
        "external_asset_coverage": ({"external_asset"}, {"coverage"}),
    }.get(metric_semantics, ({"not_applicable"}, {"not_applicable"}))
    if (
        account_scope not in account_shape[0]
        or account_value_role not in account_shape[1]
    ):
        raise ValueError(
            f"{context} account scope/role conflicts with {metric_semantics} semantics"
        )
    if metric_semantics == "account_nav" and not includes_isolated_margin:
        raise ValueError(
            f"{context}.account_nav must declare that isolated margin is included"
        )
    if metric_semantics not in {"account_nav", "account_component"} and (
        includes_isolated_margin
    ):
        raise ValueError(
            f"{context}.includes_isolated_margin is invalid for {metric_semantics}"
        )

    event_at = iso_value(
        item.get("event_at"),
        context=f"{context}.event_at",
        date_only_allowed=False,
    )
    return {
        "metric_id": identifier(item.get("metric_id"), context=f"{context}.metric_id"),
        "label": plain_text(
            item.get("label"), context=f"{context}.label", max_length=120
        ),
        "event_namespace": identifier(
            item.get("event_namespace"), context=f"{context}.event_namespace"
        ),
        "event_id": identifier(item.get("event_id"), context=f"{context}.event_id"),
        "event_at": event_at,
        "instrument_id": identifier(
            item.get("instrument_id"), context=f"{context}.instrument_id"
        ),
        "scope_id": identifier(item.get("scope_id"), context=f"{context}.scope_id"),
        "period_start": period_start,
        "period_end": period_end,
        "source_state": source_state,
        "value": metric_value,
        "unit": plain_text(item.get("unit"), context=f"{context}.unit", max_length=40),
        "metric_basis": enum(
            item.get("metric_basis"),
            {"realized_cash", "period_estimate", "annualized_estimate"},
            context=f"{context}.metric_basis",
        ),
        "metric_semantics": metric_semantics,
        "value_origin": value_origin,
        "value_precision": value_precision,
        "observation_authority": observation_authority,
        "sign_basis": sign_basis,
        "fee_inclusion": fee_inclusion,
        "account_scope": account_scope,
        "account_value_role": account_value_role,
        "includes_isolated_margin": includes_isolated_margin,
        "expected_components": expected,
        "observed_components": observed,
        "double_counted_components": double_counted,
        "numerator_scope": numerator_scope,
        "denominator_scope": denominator_scope,
        "lineage_id": identifier(
            item.get("lineage_id"), context=f"{context}.lineage_id"
        ),
        "source_ref": evidence_reference(
            item.get("source_ref"), context=f"{context}.source_ref"
        ),
        "methodology_state": enum(
            item.get("methodology_state"),
            {"verified", "declared_only", "unverified", "conflicting"},
            context=f"{context}.methodology_state",
        ),
        "anomaly_state": enum(
            item.get("anomaly_state"),
            {"clear", "unverified", "confirmed"},
            context=f"{context}.anomaly_state",
        ),
    }


def validate_source_period_metrics(value: object) -> list[dict[str, Any]]:
    """Normalize period metrics without turning source observations into readiness."""

    metrics = [
        _source_period_metric(item, index=index)
        for index, item in enumerate(
            bounded_list(
                value,
                context="source_period_metrics",
                maximum=MAX_PERIOD_METRICS,
            )
        )
    ]
    metric_ids = [str(item["metric_id"]) for item in metrics]
    if len(metric_ids) != len(set(metric_ids)):
        raise ValueError("source_period_metrics metric_id values must be unique")
    primary_by_lineage: dict[tuple[str, ...], str] = {}
    exact_values_by_lineage: dict[tuple[str, ...], set[float]] = {}

    def primary_rank(row: Mapping[str, Any]) -> tuple[int, int, int, int, str]:
        missing_count = len(
            set(row["expected_components"]) - set(row["observed_components"])
        )
        coverage_rank = (
            3
            if row["source_state"] == "error"
            else 2
            if row["value"] is None
            else 1
            if missing_count
            else 0
        )
        return (
            coverage_rank,
            0 if row["methodology_state"] == "verified" else 1,
            0 if row["anomaly_state"] == "clear" else 1,
            _OBSERVATION_AUTHORITY_RANK[str(row["observation_authority"])],
            str(row["metric_id"]),
        )

    for item in sorted(metrics, key=primary_rank):
        key = (
            str(item["lineage_id"]),
            str(item["event_namespace"]),
            str(item["event_id"]),
            str(item["event_at"]),
            str(item["instrument_id"]),
            str(item["scope_id"]),
            str(item["period_start"]),
            str(item["period_end"]),
            str(item["metric_semantics"]),
            str(item["unit"]),
        )
        primary_by_lineage.setdefault(key, str(item["metric_id"]))
        if item["value"] is not None and item["value_precision"] == "exact":
            exact_values_by_lineage.setdefault(key, set()).add(float(item["value"]))

    normalized: list[dict[str, Any]] = []
    for item in metrics:
        missing = sorted(
            set(item["expected_components"]) - set(item["observed_components"])
        )
        coverage_state = (
            "source_error"
            if item["source_state"] == "error"
            else "missing"
            if item["value"] is None
            else "partial"
            if missing
            else "complete"
        )
        lineage_key = (
            str(item["lineage_id"]),
            str(item["event_namespace"]),
            str(item["event_id"]),
            str(item["event_at"]),
            str(item["instrument_id"]),
            str(item["scope_id"]),
            str(item["period_start"]),
            str(item["period_end"]),
            str(item["metric_semantics"]),
            str(item["unit"]),
        )
        primary_id = primary_by_lineage[lineage_key]
        duplicate_of = None if primary_id == item["metric_id"] else primary_id
        gaps: list[str] = []
        if coverage_state != "complete":
            gaps.append(coverage_state)
        gaps.extend(f"missing_component:{component}" for component in missing)
        if item["methodology_state"] != "verified":
            gaps.append(f"methodology:{item['methodology_state']}")
        if item["anomaly_state"] != "clear":
            gaps.append(f"anomaly:{item['anomaly_state']}")
        if item["value_precision"] == "rounded":
            gaps.append("rounded_value")
        if duplicate_of is not None:
            gaps.append("duplicate_upstream")
        if len(exact_values_by_lineage.get(lineage_key, set())) > 1:
            gaps.append("lineage_value_conflict")
        account_nav_treatment = {
            "nav_owner": "authoritative_total",
            "composition": "composition_only",
            "reconciliation": "reconciliation_only",
            "withdrawable": "venue_liquidity_only",
            "coverage": "external_asset_coverage_only",
            "not_applicable": "not_account_value",
        }[str(item["account_value_role"])]
        normalized.append(
            {
                **item,
                "event_identity": {
                    "namespace": item["event_namespace"],
                    "source_event_id": item["event_id"],
                    "event_at": item["event_at"],
                    "instrument_id": item["instrument_id"],
                    "scope_id": item["scope_id"],
                },
                "coverage_state": coverage_state,
                "missing_components": missing,
                "lineage_state": (
                    "primary" if duplicate_of is None else "duplicate_upstream"
                ),
                "duplicate_of": duplicate_of,
                "independent_evidence": duplicate_of is None,
                "gap_reasons": gaps,
                "account_nav_treatment": account_nav_treatment,
                "ready_eligible": False,
                "admission_reason": "source_period_metric_is_evidence_only",
            }
        )
    return normalized


def _nonnegative_integer(value: object, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def validate_spot_market_identity(value: object) -> dict[str, Any]:
    """Join spot contexts by pair identity and tokens by explicit indexes."""

    item = record(
        value,
        context="spot_market_identity",
        allowed=SPOT_MARKET_IDENTITY_FIELDS,
    )
    tokens: list[dict[str, Any]] = []
    for index, raw_token in enumerate(
        bounded_list(
            item.get("tokens"),
            context="spot_market_identity.tokens",
            maximum=MAX_SPOT_TOKENS,
        )
    ):
        context = f"spot_market_identity.tokens[{index}]"
        token = record(raw_token, context=context, allowed=SPOT_TOKEN_FIELDS)
        tokens.append(
            {
                "index": _nonnegative_integer(
                    token.get("index"), context=f"{context}.index"
                ),
                "symbol": plain_text(
                    token.get("symbol"), context=f"{context}.symbol", max_length=40
                ),
                "source_ref": evidence_reference(
                    token.get("source_ref"), context=f"{context}.source_ref"
                ),
            }
        )
    token_indexes = [token["index"] for token in tokens]
    if len(token_indexes) != len(set(token_indexes)):
        raise ValueError("spot_market_identity.tokens index values must be unique")
    token_by_index = {token["index"]: token for token in tokens}

    contexts: list[dict[str, Any]] = []
    for index, raw_context in enumerate(
        bounded_list(
            item.get("contexts"),
            context="spot_market_identity.contexts",
            maximum=MAX_SPOT_MARKETS,
        )
    ):
        context = f"spot_market_identity.contexts[{index}]"
        context_item = record(
            raw_context,
            context=context,
            allowed=SPOT_CONTEXT_FIELDS,
        )
        mark_price = (
            None
            if context_item.get("mark_price") is None
            else number(
                context_item.get("mark_price"),
                context=f"{context}.mark_price",
            )
        )
        if mark_price is not None and mark_price <= 0:
            raise ValueError(f"{context}.mark_price must be positive or null")
        contexts.append(
            {
                "coin": plain_text(
                    context_item.get("coin"),
                    context=f"{context}.coin",
                    max_length=80,
                ),
                "observed_at": iso_value(
                    context_item.get("observed_at"),
                    context=f"{context}.observed_at",
                    date_only_allowed=False,
                ),
                "mark_price": mark_price,
                "source_ref": evidence_reference(
                    context_item.get("source_ref"),
                    context=f"{context}.source_ref",
                ),
            }
        )
    context_names = [context["coin"] for context in contexts]
    if len(context_names) != len(set(context_names)):
        raise ValueError("spot_market_identity.contexts coin values must be unique")
    context_by_coin = {context["coin"]: context for context in contexts}

    pairs: list[dict[str, Any]] = []
    for index, raw_pair in enumerate(
        bounded_list(
            item.get("pairs"),
            context="spot_market_identity.pairs",
            maximum=MAX_SPOT_MARKETS,
        )
    ):
        context = f"spot_market_identity.pairs[{index}]"
        pair = record(raw_pair, context=context, allowed=SPOT_PAIR_FIELDS)
        asset_indexes = [
            _nonnegative_integer(
                asset_index,
                context=f"{context}.asset_indexes[{asset_position}]",
            )
            for asset_position, asset_index in enumerate(
                bounded_list(
                    pair.get("asset_indexes"),
                    context=f"{context}.asset_indexes",
                    minimum=2,
                    maximum=2,
                )
            )
        ]
        if asset_indexes[0] == asset_indexes[1]:
            raise ValueError(f"{context}.asset_indexes must identify two assets")
        pairs.append(
            {
                "name": plain_text(
                    pair.get("name"), context=f"{context}.name", max_length=80
                ),
                "asset_indexes": asset_indexes,
                "is_canonical": boolean(
                    pair.get("is_canonical"), context=f"{context}.is_canonical"
                ),
                "source_ref": evidence_reference(
                    pair.get("source_ref"), context=f"{context}.source_ref"
                ),
            }
        )
    pair_names = [pair["name"] for pair in pairs]
    if len(pair_names) != len(set(pair_names)):
        raise ValueError("spot_market_identity.pairs name values must be unique")
    missing_contexts = sorted(set(pair_names) - set(context_names))
    extra_contexts = sorted(set(context_names) - set(pair_names))
    if missing_contexts or extra_contexts:
        raise ValueError(
            "spot_market_identity requires exact pair.name/context.coin identity; "
            f"missing={missing_contexts}, unmatched={extra_contexts}"
        )

    markets: list[dict[str, Any]] = []
    for pair in pairs:
        missing_indexes = [
            asset_index
            for asset_index in pair["asset_indexes"]
            if asset_index not in token_by_index
        ]
        if missing_indexes:
            raise ValueError(
                "spot_market_identity pair asset indexes are missing from tokens: "
                f"{missing_indexes}"
            )
        base = token_by_index[pair["asset_indexes"][0]]
        quote = token_by_index[pair["asset_indexes"][1]]
        market_context = context_by_coin[pair["name"]]
        markets.append(
            {
                "pair_name": pair["name"],
                "context_coin": market_context["coin"],
                "base_asset": {"index": base["index"], "symbol": base["symbol"]},
                "quote_asset": {
                    "index": quote["index"],
                    "symbol": quote["symbol"],
                },
                "observed_at": market_context["observed_at"],
                "mark_price": market_context["mark_price"],
                "canonicality": (
                    "canonical_name" if pair["is_canonical"] else "noncanonical_name"
                ),
                "backing_inference": "not_inferred",
                "source_refs": [
                    pair["source_ref"],
                    base["source_ref"],
                    quote["source_ref"],
                    market_context["source_ref"],
                ],
                "ready_eligible": False,
            }
        )
    return {
        "pairs": pairs,
        "tokens": tokens,
        "contexts": contexts,
        "markets": markets,
    }


def timestamp(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or "T" not in value:
        raise ValueError("coverage timestamps require ISO datetime with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "coverage timestamps require ISO datetime with timezone"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError("coverage timestamps require ISO datetime with timezone")
    return parsed.astimezone(UTC)


def _label(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(
            f"{field} requires a nonempty string of at most 120 characters"
        )
    reject_forbidden_material(value, path=field)
    return value


def validate_coverage_requirement(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "request_identity",
        "collection_started_at",
    }:
        raise ValueError(
            "source_coverage requires request_identity and collection_started_at"
        )
    identity = value["request_identity"]
    if not isinstance(identity, Mapping) or set(identity) != {
        "market",
        "universe_id",
        "query_id",
    }:
        raise ValueError("coverage identity requires market, universe_id, query_id")
    return {
        "request_identity": {
            key: _label(identity[key], key) for key in sorted(identity)
        },
        "collection_started_at": timestamp(value["collection_started_at"]).isoformat(),
    }


def assess_pages(
    pages: object,
    *,
    request_identity: Mapping[str, Any],
    frozen_at: str,
    evaluated_at: str,
) -> dict[str, Any]:
    """Assess normalized pages while preserving observed IDs and versions.

    Each page has request_identity (excluding page number), page_number,
    source_status, started_at, observed_at, rows, total_count and has_more.
    Rows have id, market and content_sha256, with optional publication_at.
    Completeness additionally requires a common nonempty snapshot_id and
    snapshot_evidence_ref asserted by the adapter. No such evidence
    means partial even when counts match. Missing/error payloads are not empty
    successes. Caller contract violations raise ValueError.
    """
    requirement = validate_coverage_requirement(
        {
            "request_identity": request_identity,
            "collection_started_at": frozen_at,
        }
    )
    request_identity = requirement["request_identity"]
    if not isinstance(pages, list) or len(pages) > MAX_PAGES:
        raise ValueError(f"source_pages requires at most {MAX_PAGES} receipts")
    reject_forbidden_material(pages, path="source_pages")
    for page in pages:
        if not isinstance(page, dict) or set(page) - PAGE_FIELDS:
            raise ValueError("coverage pages accept only normalized receipt metadata")
        rows = page.get("rows")
        if isinstance(rows, list):
            if len(rows) > MAX_ROWS_PER_PAGE:
                raise ValueError("source_pages exceeds normalized row budget")
            for row in rows:
                if not isinstance(row, dict) or set(row) - ROW_FIELDS:
                    raise ValueError(
                        "coverage rows accept only identity and version metadata"
                    )
    if sum(len(p["rows"]) for p in pages if isinstance(p.get("rows"), list)) > MAX_ROWS:
        raise ValueError("source_pages exceeds normalized row budget")
    frozen, evaluated = timestamp(frozen_at), timestamp(evaluated_at)
    if frozen > evaluated:
        raise ValueError("invalid_evaluation_clock")
    errors, instability, gaps = set(), set(), set()
    observations, page_versions, page_ids = {}, {}, {}
    totals, terminals, snapshots, snapshot_refs = set(), set(), set(), set()
    raw_count = 0
    for page in pages:
        start, observed = (
            timestamp(page.get("started_at")),
            timestamp(page.get("observed_at")),
        )
        if not frozen <= start <= observed <= evaluated:
            raise ValueError("invalid_observation_clock")
        number = page.get("page_number")
        if type(number) is not int or number < 1:
            raise ValueError("positive_page_number_required")
        if page.get("request_identity") != request_identity:
            errors.add("request_identity_mismatch")
        if page.get("source_status") != "ok":
            errors.add("source_error_or_unknown")
            continue
        rows = page.get("rows")
        if not isinstance(rows, list):
            errors.add("missing_rows")
            continue
        total = page.get("total_count")
        if total is None:
            gaps.add("total_unknown")
        elif type(total) is not int or total < 0:
            errors.add("invalid_total")
        else:
            totals.add(total)
        more = page.get("has_more")
        if more is False:
            terminals.add(number)
        elif more is not True:
            gaps.add("terminal_unknown")
        snapshot, snapshot_ref = (
            page.get("snapshot_id"),
            page.get("snapshot_evidence_ref"),
        )
        if (
            snapshot is None
            or snapshot == ""
            or snapshot_ref is None
            or snapshot_ref == ""
        ):
            gaps.add("snapshot_unattested")
        else:
            snapshots.add(_label(snapshot, "snapshot_id"))
            snapshot_refs.add(_label(snapshot_ref, "snapshot_evidence_ref"))
        raw_count += len(rows)
        signature, ids = [], set()
        for row in rows:
            key, digest = row.get("id"), row.get("content_sha256")
            if (
                not isinstance(key, str)
                or not key.strip()
                or len(key) > 120
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                errors.add("row_identity_or_digest_missing")
                continue
            if row.get("market") != request_identity["market"]:
                errors.add("row_market_mismatch")
            pub = row.get("publication_at")
            if pub is not None:
                try:
                    if timestamp(pub) > observed:
                        errors.add("publication_after_observation")
                except (ValueError, AttributeError, TypeError):
                    errors.add("invalid_publication_time")
                    pub = None
            if key in ids:
                instability.add("duplicate_within_page")
            ids.add(key)
            signature.append((key, digest, pub))
            seen = observed.isoformat()
            item = observations.setdefault(
                key, {"id": key, "versions": {}, "first_observed_at": seen}
            )
            if observed < timestamp(item["first_observed_at"]):
                item["first_observed_at"] = seen
            version = item["versions"].setdefault(
                digest,
                {
                    "content_sha256": digest,
                    "first_observed_at": seen,
                    "publication_at_values": [],
                },
            )
            if observed < timestamp(version["first_observed_at"]):
                version["first_observed_at"] = seen
            if pub not in version["publication_at_values"]:
                version["publication_at_values"].append(pub)
                version["publication_at_values"].sort(
                    key=lambda p: (p is not None, p or "")
                )
            if len(item["versions"]) > 1 or len(version["publication_at_values"]) > 1:
                instability.add("record_version_conflict")
        encoded = json.dumps(
            {
                "rows": signature,
                "has_more": more,
                "total_count": total,
                "snapshot_id": snapshot,
                "snapshot_evidence_ref": snapshot_ref,
            },
            ensure_ascii=False,
        )
        if number in page_versions and encoded != page_versions[number]:
            instability.add("repeated_page_changed")
        page_versions.setdefault(number, encoded)
        page_ids.setdefault(number, set()).update(ids)
    seen_ids = set()
    for number in sorted(page_ids):
        if seen_ids & page_ids[number]:
            instability.add("cross_page_overlap")
        seen_ids.update(page_ids[number])
    if len(totals) > 1:
        instability.add("reported_total_changed")
    if len(snapshots) > 1 or len(snapshot_refs) > 1:
        instability.add("snapshot_changed")
    if len(terminals) > 1:
        instability.add("inconsistent_terminal")
    if len(terminals) != 1:
        gaps.add("terminal_not_established")
    elif next(iter(terminals)) != len(page_ids) or any(
        number != index for index, number in enumerate(sorted(page_ids), 1)
    ):
        gaps.add("noncontiguous_pages_or_pages_after_terminal")
    if len(totals) != 1 or len(observations) != next(iter(totals), None):
        gaps.add("reported_count_not_covered")
    if not pages:
        gaps.add("no_observations")
    state = (
        CoverageState.SOURCE_ERROR
        if errors
        else CoverageState.UNSTABLE
        if instability
        else CoverageState.PARTIAL
        if gaps
        else CoverageState.COMPLETE
    )
    return {
        "schema_version": "finance_source_coverage_v1",
        "state": state.value,
        "requirement": requirement,
        "evaluated_at": evaluated.isoformat(),
        "row_count_including_replays": raw_count,
        "receipt_count": len(pages),
        "unique_ids": len(observations),
        "reported_totals": sorted(totals),
        "observed_page_numbers": sorted(page_ids),
        "errors": sorted(errors),
        "instability": sorted(instability),
        "gaps": sorted(gaps),
        "records": [observations[k] for k in sorted(observations)],
        "snapshot_evidence_state": "adapter_asserted" if snapshots else "missing",
        "publication_time_verified": False,
        "event_novelty_verified": False,
        "limitation": "Conditional on adapter identities and snapshot assertions; query coverage does not prove source truth, historical availability, or an investment edge.",
    }


def coverage_observation(
    value: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
    evaluation_as_of: str,
) -> dict[str, Any]:
    if set(value) != {"gate_id", "source_pages"} or value["gate_id"] != rule["gate_id"]:
        raise ValueError(
            "a source-coverage observation requires only the bound gate_id and source_pages"
        )
    # Case dates mean midnight UTC. Datetimes in coverage-enabled cases must
    # carry an offset; do not infer the host timezone for receipt verification.
    if "T" not in evaluation_as_of:
        evaluation_as_of += "T00:00:00+00:00"
    requirement = rule["source_coverage"]
    report = assess_pages(
        value["source_pages"],
        request_identity=requirement["request_identity"],
        frozen_at=requirement["collection_started_at"],
        evaluated_at=evaluation_as_of,
    )
    complete = report["state"] == CoverageState.COMPLETE
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {
        "gate_id": rule["gate_id"],
        "observation_state": "observed" if complete else "missing",
        "value": True if complete else None,
        "evidence_refs": [f"coverage:{digest}"],
        "reason": f"Source query coverage is {report['state']}; snapshot evidence remains adapter-asserted.",
        "source_coverage": report,
    }
