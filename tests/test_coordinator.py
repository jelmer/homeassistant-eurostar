"""Tests for the Eurostar coordinator GTFS parsing."""

import io
import zipfile
from datetime import UTC, date, datetime

from custom_components.eurostar.coordinator import (
    _is_service_active,
    _parse_date,
    _parse_gtfs_time,
    _parse_static_data,
    parse_stops_from_gtfs,
)


def _make_gtfs_zip(files: dict[str, str]) -> bytes:
    """Create a GTFS ZIP file in memory from a dict of {filename: csv_content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


SAMPLE_AGENCY = "agency_id,agency_name,agency_url,agency_timezone\n1,Eurostar,https://www.eurostar.com,Europe/London\n"

SAMPLE_STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon\n"
    "LON,London St Pancras,51.5317,-0.1262\n"
    "PAR,Paris Gare du Nord,48.8809,2.3553\n"
    "BRU,Brussels Midi,50.8357,4.3366\n"
)

SAMPLE_ROUTES = (
    "route_id,route_short_name,route_long_name,route_type\nR1,ES,Eurostar,2\n"
)

SAMPLE_CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
    "WEEKDAY,1,1,1,1,1,0,0,20260101,20261231\n"
    "WEEKEND,0,0,0,0,0,1,1,20260101,20261231\n"
)

SAMPLE_CALENDAR_DATES = (
    "service_id,date,exception_type\n"
    "WEEKDAY,20260325,2\n"  # removed for March 25 (Wednesday)
    "WEEKEND,20260325,1\n"  # added for March 25
)

SAMPLE_TRIPS = (
    "trip_id,route_id,service_id,trip_headsign\n"
    "T1,R1,WEEKDAY,Paris Gare du Nord\n"
    "T2,R1,WEEKDAY,Paris Gare du Nord\n"
    "T3,R1,WEEKEND,Paris Gare du Nord\n"
)

SAMPLE_STOP_TIMES = (
    "trip_id,stop_id,arrival_time,departure_time,stop_sequence\n"
    "T1,LON,06:00:00,06:15:00,1\n"
    "T1,PAR,08:30:00,08:30:00,2\n"
    "T2,LON,10:00:00,10:15:00,1\n"
    "T2,PAR,12:30:00,12:30:00,2\n"
    "T3,LON,09:00:00,09:15:00,1\n"
    "T3,PAR,11:30:00,11:30:00,2\n"
)


def _make_sample_zip() -> bytes:
    return _make_gtfs_zip(
        {
            "agency.txt": SAMPLE_AGENCY,
            "stops.txt": SAMPLE_STOPS,
            "routes.txt": SAMPLE_ROUTES,
            "calendar.txt": SAMPLE_CALENDAR,
            "calendar_dates.txt": SAMPLE_CALENDAR_DATES,
            "trips.txt": SAMPLE_TRIPS,
            "stop_times.txt": SAMPLE_STOP_TIMES,
        }
    )


def test_parse_date() -> None:
    assert _parse_date("20260325") == date(2026, 3, 25)
    assert _parse_date("20261231") == date(2026, 12, 31)


def test_parse_gtfs_time_normal() -> None:
    service_date = date(2026, 3, 25)
    result = _parse_gtfs_time("10:30:00", service_date, UTC)
    assert result == datetime(2026, 3, 25, 10, 30, 0, tzinfo=UTC)


def test_parse_gtfs_time_over_24() -> None:
    service_date = date(2026, 3, 25)
    result = _parse_gtfs_time("25:30:00", service_date, UTC)
    assert result == datetime(2026, 3, 26, 1, 30, 0, tzinfo=UTC)


def test_is_service_active_regular_weekday() -> None:
    calendars = {
        "WEEKDAY": {
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": False,
            "sunday": False,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        }
    }
    # March 24, 2026 is a Tuesday
    assert _is_service_active("WEEKDAY", date(2026, 3, 24), calendars, {})
    # March 28, 2026 is a Saturday
    assert not _is_service_active("WEEKDAY", date(2026, 3, 28), calendars, {})


def test_is_service_active_with_exception() -> None:
    calendars = {
        "WEEKDAY": {
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": False,
            "sunday": False,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        }
    }
    calendar_dates = {
        "WEEKDAY": [(date(2026, 3, 25), 2)],  # removed
    }
    assert not _is_service_active(
        "WEEKDAY", date(2026, 3, 25), calendars, calendar_dates
    )


def test_is_service_active_added_exception() -> None:
    calendars = {}
    calendar_dates = {
        "WEEKEND": [(date(2026, 3, 25), 1)],  # added
    }
    assert _is_service_active("WEEKEND", date(2026, 3, 25), calendars, calendar_dates)


def test_parse_stops_from_gtfs() -> None:
    zip_data = _make_sample_zip()
    stops = parse_stops_from_gtfs(zip_data)
    # BRU is not in stop_times.txt, so it should be excluded.
    # LON and PAR appear in stop_times and are deduplicated by name.
    assert stops == {
        "LON": "London St Pancras",
        "PAR": "Paris Gare du Nord",
    }


def test_parse_stops_deduplicates_platforms() -> None:
    """Platform-level stops should be deduplicated, keeping shortest ID."""
    files = {
        "agency.txt": SAMPLE_AGENCY,
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
            "LON,London St Pancras,51.53,-0.12,0,LON_area\n"
            "LON_5,London St Pancras,51.53,-0.12,0,LON_area\n"
            "LON_area,London St Pancras,51.53,-0.12,1,\n"
        ),
        "routes.txt": SAMPLE_ROUTES,
        "calendar.txt": SAMPLE_CALENDAR,
        "calendar_dates.txt": "service_id,date,exception_type\n",
        "trips.txt": "trip_id,route_id,service_id,trip_headsign\n",
        "stop_times.txt": (
            "trip_id,stop_id,arrival_time,departure_time,stop_sequence\n"
            "T1,LON,06:00:00,06:15:00,1\n"
            "T1,LON_5,06:00:00,06:15:00,1\n"
        ),
    }
    zip_data = _make_gtfs_zip(files)
    stops = parse_stops_from_gtfs(zip_data)
    # Should keep "LON" (shorter) over "LON_5"
    assert stops == {"LON": "London St Pancras"}


def test_parse_static_data_weekday() -> None:
    """Test parsing on a regular Tuesday (March 24, 2026)."""
    zip_data = _make_sample_zip()
    result = _parse_static_data(zip_data, "LON", "PAR", date(2026, 3, 24))

    assert len(result.departures) == 2
    assert result.departures[0].trip_id == "T1"
    assert result.departures[1].trip_id == "T2"
    assert result.departures[0].route_name == "ES"
    assert result.departures[0].headsign == "Paris Gare du Nord"
    assert result.service_date == date(2026, 3, 24)


def test_parse_static_data_with_exceptions() -> None:
    """Test March 25, 2026 where WEEKDAY is removed and WEEKEND is added."""
    zip_data = _make_sample_zip()
    result = _parse_static_data(zip_data, "LON", "PAR", date(2026, 3, 25))

    # Only T3 (WEEKEND) should be active
    assert len(result.departures) == 1
    assert result.departures[0].trip_id == "T3"


def test_parse_static_data_reverse_direction_excluded() -> None:
    """Trips going PAR->LON should not appear when querying LON->PAR."""
    files = {
        "agency.txt": SAMPLE_AGENCY,
        "stops.txt": SAMPLE_STOPS,
        "routes.txt": SAMPLE_ROUTES,
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "DAILY,1,1,1,1,1,1,1,20260101,20261231\n"
        ),
        "calendar_dates.txt": "service_id,date,exception_type\n",
        "trips.txt": (
            "trip_id,route_id,service_id,trip_headsign\n"
            "T_REVERSE,R1,DAILY,London St Pancras\n"
        ),
        "stop_times.txt": (
            "trip_id,stop_id,arrival_time,departure_time,stop_sequence\n"
            "T_REVERSE,PAR,08:00:00,08:15:00,1\n"
            "T_REVERSE,LON,10:30:00,10:30:00,2\n"
        ),
    }
    zip_data = _make_gtfs_zip(files)
    result = _parse_static_data(zip_data, "LON", "PAR", date(2026, 3, 24))
    assert len(result.departures) == 0


def test_parse_static_data_sorted_by_departure() -> None:
    """Departures should be sorted by departure time."""
    zip_data = _make_sample_zip()
    result = _parse_static_data(zip_data, "LON", "PAR", date(2026, 3, 24))
    times = [d.departure_time for d in result.departures]
    assert times == sorted(times)
