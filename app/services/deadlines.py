"""Timestamp precision bridge for n8n JavaScript Date (milliseconds)."""

from datetime import datetime


def expiry_timestamp_reaches_deadline(occurred_at: datetime, deadline: datetime) -> bool:
    """Accept JS's exact-millisecond truncation of a backend microsecond deadline.

    Keep transport-receipt and processing clocks compared to the *full* deadline.
    Only the event's original timestamp uses millisecond precision because
    JavaScript Date.toISOString() cannot preserve sub-millisecond digits.
    This allows less than 1ms loss, never a full millisecond or more.
    """
    deadline_at_js_precision = deadline.replace(
        microsecond=(deadline.microsecond // 1000) * 1000
    )
    return occurred_at >= deadline_at_js_precision
