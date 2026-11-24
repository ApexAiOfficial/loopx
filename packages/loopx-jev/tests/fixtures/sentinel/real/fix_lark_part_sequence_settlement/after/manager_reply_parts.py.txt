"""Bounded multi-message delivery for a manager answer that does not fit once.

A persisted manager answer that the provider rejects for length used to be left
on the channel as nothing at all. This module owns the alternative: split the
already-validated body into ordered parts, send the parts the provider has not
accepted yet, and record that progress in the same durable delivery state the
single-message path uses, so a retry resumes instead of re-sending.

The counter is not the whole record. A part is counted only after the transport
accepted it, so a state that already shows every part accepted means the reader
has the whole answer even when the caller never got to write its own receipt
(a failed settle write, or a process that stopped right after the last part).
That case settles from the record instead of re-sending nothing forever.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .inbox_reply import reply_lark_event_inbox
from .outbound import DEFAULT_LARK_TEXT_LIMIT, split_lark_outbound_text

# An oversized answer is delivered as a bounded sequence rather than a flood:
# past this many parts the answer keeps its leading parts and ends with a note
# naming where the full text is already saved.
MANAGER_REPLY_MAX_PARTS = 8
MANAGER_REPLY_OVERFLOW_NOTE = (
    "本条答复超过可投递长度，上面已按顺序发送前面的部分；"
    "完整答复保存在 LoopX 管家会话中。"
)
PART_DELIVERY_COMPLETE_KEY = "delivery_parts_complete"
PART_DELIVERY_VERIFIED_KEY = "delivery_parts_verified"
PART_DELIVERY_INCOMPLETE = "reply_part_delivery_incomplete"
PART_DELIVERY_COMPLETION_UNVERIFIED = "reply_part_delivery_completion_unverified"


def plan_manager_reply_parts(reply_text: str) -> tuple[list[str], bool]:
    """Return the parts to deliver and whether the remainder was replaced."""

    parts = split_lark_outbound_text(
        reply_text,
        limit=DEFAULT_LARK_TEXT_LIMIT,
        max_parts=MANAGER_REPLY_MAX_PARTS,
        overflow_note=MANAGER_REPLY_OVERFLOW_NOTE,
    )
    truncated = len(parts) == MANAGER_REPLY_MAX_PARTS and (
        MANAGER_REPLY_OVERFLOW_NOTE in parts[-1]
    )
    return parts, truncated


def _part_verified(reply: Mapping[str, Any]) -> bool:
    """Whether the provider readback confirmed this part on the channel."""

    return bool(
        reply.get("external_write_performed") is True
        and reply.get("verification_performed") is True
        and reply.get("reply_verified") is True
    )


def _part_accepted(reply: Mapping[str, Any]) -> bool:
    """Whether this part may be counted as delivered.

    ``ok`` also requires the source reaction cleanup to have finished, so a part
    the provider already verified can come back not-ok with a cleanup still
    pending. Its text is on the channel either way: counting it is what keeps a
    retry from sending the reader the same part twice, and the pending cleanup
    stays the transport's own business.
    """

    return reply.get("ok") is True or _part_verified(reply)


def _accepted_reply_facts(reply: Mapping[str, Any]) -> dict[str, Any]:
    """The durable facts of one part the provider confirmed."""

    return {
        "reply_idempotency_key": reply.get("idempotency_key"),
        PART_DELIVERY_VERIFIED_KEY: _part_verified(reply),
    }


def completed_part_delivery_receipt(
    delivery_state: Mapping[str, Any],
) -> dict[str, Any] | None:
    """The verified receipt for a sequence whose every part was accepted.

    Returns ``None`` unless the durable record proves both that the sequence
    finished and that the provider verified the last part, so a caller never
    marks a delivery verified on the strength of an unfinished or unverified
    record.
    """

    if delivery_state.get(PART_DELIVERY_COMPLETE_KEY) is not True:
        return None
    if delivery_state.get(PART_DELIVERY_VERIFIED_KEY) is not True:
        return None
    key = delivery_state.get("reply_idempotency_key")
    if not isinstance(key, str) or not key.startswith("sha256:"):
        return None
    return {
        "ok": True,
        "status": "sent_verified",
        "idempotency_key": key,
        "content_format": "text",
        "external_write_performed": True,
        "verification_performed": True,
        "reply_verified": True,
        "part_delivery_reused": True,
    }


def part_delivery_incomplete_reason(delivery_state: Mapping[str, Any]) -> str:
    """Name why a sequence stopped, when the record already says all parts went.

    A recorded counter that reached the part count without a verified
    completion cannot be re-sent (the parts are already on the channel) and
    cannot be settled either, so it gets its own reason instead of the generic
    incomplete one.
    """

    recorded = delivery_state.get("delivery_part_count")
    sent = delivery_state.get("delivery_parts_sent")
    if (
        isinstance(recorded, int)
        and not isinstance(recorded, bool)
        and isinstance(sent, int)
        and not isinstance(sent, bool)
        and recorded > 0
        and sent == recorded
    ):
        return PART_DELIVERY_COMPLETION_UNVERIFIED
    return PART_DELIVERY_INCOMPLETE


def deliver_manager_reply_parts(
    *,
    parts: list[str],
    delivery_state: dict[str, Any],
    delivery_path: Path,
    write_delivery,
    reply_runner: Any,
    root: Path,
    config_path: Path,
    message_id: str,
    content_format: str,
) -> Mapping[str, Any] | None:
    """Send the remaining parts in order, resuming from the recorded count.

    The durable state, not the return value, is the record of what the provider
    accepted: each accepted part advances `delivery_parts_sent` before the next
    send, and a rejected part stops the sequence there.
    """

    recorded_count = delivery_state.get("delivery_part_count")
    sent = delivery_state.get("delivery_parts_sent")
    if (
        not isinstance(recorded_count, int)
        or isinstance(recorded_count, bool)
        or recorded_count != len(parts)
        or not isinstance(sent, int)
        or isinstance(sent, bool)
        or not 0 <= sent <= len(parts)
    ):
        # A different split than the one on record cannot be resumed safely.
        sent = 0
    elif sent == len(parts):
        # Every part is already on the channel. Settle from the recorded
        # acceptance instead of reporting an incomplete sequence that no retry
        # could ever finish (re-sending would duplicate the whole answer).
        return completed_part_delivery_receipt(delivery_state)
    delivery_state.update(
        delivery_part_count=len(parts),
        delivery_parts_sent=sent,
        format_degraded=True,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    # A sequence that is still being sent is not a complete one, even when a
    # previous attempt recorded a verified completion for a different split.
    delivery_state[PART_DELIVERY_COMPLETE_KEY] = False
    write_delivery(delivery_path, delivery_state)
    last: Mapping[str, Any] | None = None
    for index in range(sent, len(parts)):
        last = reply_lark_event_inbox(
            project=root,
            config_path=config_path,
            message_id=message_id,
            text=parts[index],
            content_format=content_format,
            execute=True,
            runner=reply_runner,
        )
        if not _part_accepted(last):
            delivery_state.update(
                delivery_parts_sent=index,
                last_delivery_status=str(last.get("status") or "reply_failed"),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            write_delivery(delivery_path, delivery_state)
            return None
        delivery_state.update(
            delivery_parts_sent=index + 1,
            **(
                {PART_DELIVERY_COMPLETE_KEY: True, **_accepted_reply_facts(last)}
                if index + 1 == len(parts)
                else _accepted_reply_facts(last)
            ),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        write_delivery(delivery_path, delivery_state)
    return last


def deliver_manager_reply_after_length_failure(
    *,
    reply_text: str,
    delivery_state: dict[str, Any],
    delivery_path: Path,
    write_delivery,
    reply_runner: Any,
    root: Path,
    config_path: Path,
    message_id: str,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Deliver one over-limit manager answer as bounded parts.

    Returns the last accepted reply, or ``None`` plus the reason to report when
    a part was rejected. Plain text is the only format a split can promise, so
    the caller has already degraded presentation before calling this.
    """

    parts, truncated = plan_manager_reply_parts(reply_text)
    if truncated:
        delivery_state.update(
            delivery_truncated=True,
            delivery_source_char_count=len(reply_text),
        )
    reply = deliver_manager_reply_parts(
        parts=parts,
        delivery_state=delivery_state,
        delivery_path=delivery_path,
        write_delivery=write_delivery,
        reply_runner=reply_runner,
        root=root,
        config_path=config_path,
        message_id=message_id,
        content_format="text",
    )
    return reply, (
        None if reply is not None else part_delivery_incomplete_reason(delivery_state)
    )


def manager_part_delivery_pending_result(
    *,
    reason: str,
    delivery_state: Mapping[str, Any],
    goal_id: str,
    inbox_config_ref: str,
) -> dict[str, Any]:
    """The typed pending result for a part sequence the provider interrupted."""

    return {
        "ok": False,
        "status": "reply_delivery_pending",
        "reason": reason,
        "delivery_part_count": delivery_state.get("delivery_part_count"),
        "delivery_parts_sent": delivery_state.get("delivery_parts_sent"),
        "format_degraded": True,
        "goal_id": goal_id,
        "inbox_config_ref": inbox_config_ref,
        "source_acknowledged": False,
    }


def manager_part_delivery_readback(delivery_state: Mapping[str, Any]) -> dict[str, Any]:
    """Part accounting for a delivered answer, empty when it was one message."""

    if not (
        isinstance(delivery_state.get("delivery_part_count"), int)
        and isinstance(delivery_state.get("delivery_parts_sent"), int)
    ):
        return {}
    return {
        "delivery_part_count": delivery_state["delivery_part_count"],
        "delivery_parts_sent": delivery_state["delivery_parts_sent"],
        "delivery_truncated": bool(delivery_state.get("delivery_truncated")),
    }
