"""Tests for the Eurostar sensor module."""

from datetime import UTC, datetime

from custom_components.eurostar.coordinator import DepartureInfo
from custom_components.eurostar.sensor import _format_status


def _make_departure(delay_seconds: int | None = None) -> DepartureInfo:
    return DepartureInfo(
        trip_id="T1",
        route_name="ES",
        headsign="Paris",
        scheduled_departure=datetime(2026, 3, 25, 8, 0, tzinfo=UTC),
        scheduled_arrival=datetime(2026, 3, 25, 10, 30, tzinfo=UTC),
        realtime_departure=None,
        delay_seconds=delay_seconds,
    )


def test_format_status_no_realtime() -> None:
    assert _format_status(_make_departure(None)) == "Scheduled"


def test_format_status_on_time() -> None:
    assert _format_status(_make_departure(0)) == "On time"


def test_format_status_small_delay() -> None:
    # Less than 1 minute counts as on time
    assert _format_status(_make_departure(30)) == "On time"


def test_format_status_delayed() -> None:
    assert _format_status(_make_departure(300)) == "Delayed 5 min"
    assert _format_status(_make_departure(900)) == "Delayed 15 min"


def test_format_status_negative_delay() -> None:
    # Ahead of schedule
    assert _format_status(_make_departure(-60)) == "On time"
