"""Timeout comparison never advances server-side expiry by a full millisecond."""

from datetime import UTC, datetime, timedelta

from app.services.deadlines import expiry_timestamp_reaches_deadline


def test_exact_js_millisecond_loss_is_accepted_for_timeout_event():
    deadline = datetime(2026, 11, 8, 10, 11, 42, 980327, tzinfo=UTC)
    sent = datetime(2026, 11, 8, 10, 11, 42, 980000, tzinfo=UTC)
    assert sent < deadline
    assert expiry_timestamp_reaches_deadline(sent, deadline)


def test_full_millisecond_early_timestamp_remains_rejected():
    deadline = datetime(2026, 11, 8, 10, 11, 42, 980327, tzinfo=UTC)
    early = datetime(2026, 11, 8, 10, 11, 42, 979000, tzinfo=UTC)
    assert not expiry_timestamp_reaches_deadline(early, deadline)


def test_exact_and_later_timestamps_accepted():
    deadline = datetime(2026, 11, 8, 10, 11, 42, 980327, tzinfo=UTC)
    assert expiry_timestamp_reaches_deadline(deadline, deadline)
    assert expiry_timestamp_reaches_deadline(deadline + timedelta(seconds=1), deadline)
