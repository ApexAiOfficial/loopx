"""Scoped progress-review sentinel capability.

Only the light policy surface is re-exported here so that configuration and
catalog modules can import it during interpreter start-up. Receipt I/O lives in
``loopx.capabilities.progress_review.receipt`` and is imported explicitly by its
consumers.
"""

from .policy import (
    PROGRESS_REVIEW_POLICY_SCHEMA_VERSION,
    progress_review_goal_policy,
    progress_review_goal_policy_summary,
)

__all__ = [
    "PROGRESS_REVIEW_POLICY_SCHEMA_VERSION",
    "progress_review_goal_policy",
    "progress_review_goal_policy_summary",
]
