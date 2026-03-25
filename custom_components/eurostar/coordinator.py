"""Data coordinator for Eurostar integration."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DESTINATION,
    CONF_ORIGIN,
    DOMAIN,
    GTFS_RT_URL,
    GTFS_STATIC_URL,
    NUM_DEPARTURES,
    RT_REFRESH_INTERVAL,
    STATIC_REFRESH_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class StopInfo:
    """Information about a stop/station."""

    stop_id: str
    stop_name: str


@dataclass
class ScheduledDeparture:
    """A scheduled departure from the static timetable."""

    trip_id: str
    route_name: str
    headsign: str
    departure_time: datetime
    arrival_time: datetime
    origin_stop_sequence: int


@dataclass
class DepartureInfo:
    """A departure with optional real-time information."""

    trip_id: str
    route_name: str
    headsign: str
    scheduled_departure: datetime
    scheduled_arrival: datetime
    realtime_departure: datetime | None
    delay_seconds: int | None


@dataclass
class StaticSchedule:
    """Parsed static schedule data for one origin-destination pair."""

    departures: list[ScheduledDeparture]
    stops: dict[str, StopInfo]
    service_date: date
    fetched_at: datetime


def _parse_gtfs_time(time_str: str, service_date: date, tz: tzinfo) -> datetime:
    """Parse a GTFS time string (which can exceed 24:00:00) into a datetime."""
    parts = time_str.strip().split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2]) if len(parts) > 2 else 0

    extra_days = hours // 24
    hours = hours % 24

    dt = datetime(
        service_date.year,
        service_date.month,
        service_date.day,
        hours,
        minutes,
        seconds,
        tzinfo=tz,
    )
    if extra_days:
        dt += timedelta(days=extra_days)
    return dt


def _is_service_active(
    service_id: str,
    check_date: date,
    calendars: dict[str, dict[str, Any]],
    calendar_dates: dict[str, list[tuple[date, int]]],
) -> bool:
    """Check if a service_id is active on the given date."""
    # Check calendar_dates exceptions first
    for exc_date, exc_type in calendar_dates.get(service_id, []):
        if exc_date == check_date:
            # exception_type 1 = added, 2 = removed
            return exc_type == 1

    # Check regular calendar
    cal = calendars.get(service_id)
    if cal is None:
        return False

    start = cal["start_date"]
    end = cal["end_date"]
    if check_date < start or check_date > end:
        return False

    day_name = check_date.strftime("%A").lower()
    return cal.get(day_name, False)


def _parse_date(date_str: str) -> date:
    """Parse a GTFS date string (YYYYMMDD) into a date."""
    return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))


def _parse_static_data(
    zip_data: bytes,
    origin_id: str,
    destination_id: str,
    service_date: date,
) -> StaticSchedule:
    """Parse the GTFS static ZIP and extract relevant schedule data."""
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        # Parse stops
        stops: dict[str, StopInfo] = {}
        with zf.open("stops.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                stop_id = row["stop_id"]
                stops[stop_id] = StopInfo(
                    stop_id=stop_id,
                    stop_name=row["stop_name"],
                )

        # Parse agency for timezone
        tz = UTC
        try:
            with zf.open("agency.txt") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    tz_name = row.get("agency_timezone", "")
                    if tz_name:
                        try:
                            import zoneinfo

                            tz = zoneinfo.ZoneInfo(tz_name)  # type: ignore[assignment]
                        except (KeyError, ImportError):
                            _LOGGER.warning("Unknown timezone %s, using UTC", tz_name)
                    break
        except KeyError:
            _LOGGER.warning("No agency.txt found in GTFS, using UTC")

        # Parse routes
        routes: dict[str, str] = {}
        with zf.open("routes.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                routes[row["route_id"]] = row.get("route_short_name") or row.get(
                    "route_long_name", ""
                )

        # Parse calendar
        calendars: dict[str, dict[str, Any]] = {}
        try:
            with zf.open("calendar.txt") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    calendars[row["service_id"]] = {
                        "monday": row.get("monday") == "1",
                        "tuesday": row.get("tuesday") == "1",
                        "wednesday": row.get("wednesday") == "1",
                        "thursday": row.get("thursday") == "1",
                        "friday": row.get("friday") == "1",
                        "saturday": row.get("saturday") == "1",
                        "sunday": row.get("sunday") == "1",
                        "start_date": _parse_date(row["start_date"]),
                        "end_date": _parse_date(row["end_date"]),
                    }
        except KeyError:
            pass

        # Parse calendar_dates
        calendar_dates: dict[str, list[tuple[date, int]]] = {}
        try:
            with zf.open("calendar_dates.txt") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    sid = row["service_id"]
                    calendar_dates.setdefault(sid, []).append(
                        (_parse_date(row["date"]), int(row["exception_type"]))
                    )
        except KeyError:
            pass

        # Parse trips
        trips: dict[
            str, tuple[str, str, str]
        ] = {}  # trip_id -> (route_id, service_id, headsign)
        with zf.open("trips.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                service_id = row["service_id"]
                if _is_service_active(
                    service_id, service_date, calendars, calendar_dates
                ):
                    trips[row["trip_id"]] = (
                        row["route_id"],
                        service_id,
                        row.get("trip_headsign", ""),
                    )

        # Parse stop_times - only keep rows for origin/destination
        # on active trips. Keyed by trip_id -> {stop_id: (dep, arr, seq)}
        trip_stops: dict[str, dict[str, tuple[str, str, int]]] = {}
        with zf.open("stop_times.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                trip_id = row["trip_id"]
                stop_id = row["stop_id"]
                if trip_id in trips and stop_id in (origin_id, destination_id):
                    trip_stops.setdefault(trip_id, {})[stop_id] = (
                        row["departure_time"],
                        row["arrival_time"],
                        int(row["stop_sequence"]),
                    )

    # Build departures list
    departures: list[ScheduledDeparture] = []
    for trip_id, stop_data in trip_stops.items():
        if origin_id not in stop_data or destination_id not in stop_data:
            continue
        origin_data = stop_data[origin_id]
        dest_data = stop_data[destination_id]
        # Ensure origin comes before destination in the trip
        if origin_data[2] >= dest_data[2]:
            continue

        route_id, _, headsign = trips[trip_id]
        departures.append(
            ScheduledDeparture(
                trip_id=trip_id,
                route_name=routes.get(route_id, "Eurostar"),
                headsign=headsign,
                departure_time=_parse_gtfs_time(origin_data[0], service_date, tz),
                arrival_time=_parse_gtfs_time(dest_data[1], service_date, tz),
                origin_stop_sequence=origin_data[2],
            )
        )

    departures.sort(key=lambda d: d.departure_time)

    return StaticSchedule(
        departures=departures,
        stops=stops,
        service_date=service_date,
        fetched_at=datetime.now(UTC),
    )


def parse_stops_from_gtfs(zip_data: bytes) -> dict[str, str]:
    """Parse stops.txt from a GTFS ZIP and return {stop_id: stop_name}.

    Only returns stops that appear in stop_times.txt, deduplicated by name
    (keeping the shortest stop_id per name to prefer base station IDs over
    platform-specific ones like ``paris_nord_5``).
    """
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        # Collect all stop_ids used in stop_times
        used_stop_ids: set[str] = set()
        with zf.open("stop_times.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                used_stop_ids.add(row["stop_id"])

        # Read all used stops, then deduplicate by name
        used_stops: dict[str, str] = {}
        with zf.open("stops.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                stop_id = row["stop_id"]
                if stop_id not in used_stop_ids:
                    continue
                name = row["stop_name"]
                # Keep shortest stop_id per name (base station over platform)
                if name not in used_stops or len(stop_id) < len(used_stops[name]):
                    used_stops[name] = stop_id

        # Invert to {stop_id: stop_name}
        return {stop_id: name for name, stop_id in used_stops.items()}


class EurostarCoordinator(DataUpdateCoordinator[list[DepartureInfo]]):
    """Coordinator to fetch Eurostar schedule and real-time data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=RT_REFRESH_INTERVAL,
        )
        self._origin_id: str = entry.data[CONF_ORIGIN]
        self._destination_id: str = entry.data[CONF_DESTINATION]
        self._static_data: StaticSchedule | None = None
        self._last_zip_data: bytes | None = None
        self._session = async_get_clientsession(hass)

    def _needs_static_refresh(self) -> bool:
        """Check if static data needs to be refreshed."""
        if self._static_data is None:
            return True
        now = datetime.now(UTC)
        if now - self._static_data.fetched_at > STATIC_REFRESH_INTERVAL:
            return True
        # Also refresh if the service date has changed
        today = date.today()
        return self._static_data.service_date != today

    async def _fetch_static_data(self) -> None:
        """Download and parse the GTFS static feed."""
        try:
            async with self._session.get(GTFS_STATIC_URL) as resp:
                resp.raise_for_status()
                zip_data = await resp.read()
        except Exception as err:
            raise UpdateFailed(f"Failed to download GTFS static data: {err}") from err

        self._last_zip_data = zip_data
        today = date.today()
        self._static_data = await self.hass.async_add_executor_job(
            _parse_static_data,
            zip_data,
            self._origin_id,
            self._destination_id,
            today,
        )

    async def _fetch_realtime_data(self) -> dict[str, int]:
        """Download and parse the GTFS-RT feed. Returns {trip_id: delay_seconds}."""
        from google.transit import gtfs_realtime_pb2

        try:
            async with self._session.get(GTFS_RT_URL) as resp:
                resp.raise_for_status()
                rt_data = await resp.read()
        except Exception:
            _LOGGER.warning("Failed to fetch GTFS-RT data, continuing with static only")
            return {}

        # Build lookup of trip_id -> origin stop_sequence from static data
        assert self._static_data is not None
        origin_sequences: dict[str, int] = {
            dep.trip_id: dep.origin_stop_sequence
            for dep in self._static_data.departures
        }

        def _parse_rt(data: bytes) -> dict[str, int]:
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(data)
            delays: dict[str, int] = {}
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                trip_id = entity.trip_update.trip.trip_id
                if trip_id not in origin_sequences:
                    continue
                origin_seq = origin_sequences[trip_id]
                for stu in entity.trip_update.stop_time_update:
                    # Match by stop_id or stop_sequence
                    matched = (
                        stu.stop_id and stu.stop_id == self._origin_id
                    ) or stu.stop_sequence == origin_seq
                    if matched:
                        if stu.departure.HasField("delay"):
                            delays[trip_id] = stu.departure.delay
                        elif stu.arrival.HasField("delay"):
                            delays[trip_id] = stu.arrival.delay
                        break
            return delays

        return await self.hass.async_add_executor_job(_parse_rt, rt_data)

    async def _async_update_data(self) -> list[DepartureInfo]:
        """Fetch data from GTFS feeds.

        Returns upcoming departures, including tomorrow's if today's are
        exhausted.
        """
        if self._needs_static_refresh():
            await self._fetch_static_data()

        assert self._static_data is not None

        rt_delays = await self._fetch_realtime_data()

        results = self._build_departure_list(self._static_data.departures, rt_delays)

        # If we don't have enough departures for today, fetch tomorrow's
        if len(results) < NUM_DEPARTURES:
            tomorrow = self._static_data.service_date + timedelta(days=1)
            if self._last_zip_data is not None:
                tomorrow_schedule = await self.hass.async_add_executor_job(
                    _parse_static_data,
                    self._last_zip_data,
                    self._origin_id,
                    self._destination_id,
                    tomorrow,
                )
                results.extend(
                    self._build_departure_list(tomorrow_schedule.departures, rt_delays)
                )

        return results[:NUM_DEPARTURES]

    def _build_departure_list(
        self,
        departures: list[ScheduledDeparture],
        rt_delays: dict[str, int],
    ) -> list[DepartureInfo]:
        """Build a list of upcoming departures with real-time data merged in."""
        if departures:
            now = datetime.now(departures[0].departure_time.tzinfo)
        else:
            now = datetime.now(UTC)

        results: list[DepartureInfo] = []
        for dep in departures:
            effective_departure = dep.departure_time
            delay = rt_delays.get(dep.trip_id)
            realtime_departure = None
            if delay is not None:
                realtime_departure = dep.departure_time + timedelta(seconds=delay)
                effective_departure = realtime_departure

            if effective_departure < now:
                continue

            results.append(
                DepartureInfo(
                    trip_id=dep.trip_id,
                    route_name=dep.route_name,
                    headsign=dep.headsign,
                    scheduled_departure=dep.departure_time,
                    scheduled_arrival=dep.arrival_time,
                    realtime_departure=realtime_departure,
                    delay_seconds=delay,
                )
            )

        return results

    @property
    def origin_name(self) -> str:
        """Get the origin station name."""
        if self._static_data and self._origin_id in self._static_data.stops:
            return self._static_data.stops[self._origin_id].stop_name
        return self._origin_id

    @property
    def destination_name(self) -> str:
        """Get the destination station name."""
        if self._static_data and self._destination_id in self._static_data.stops:
            return self._static_data.stops[self._destination_id].stop_name
        return self._destination_id
