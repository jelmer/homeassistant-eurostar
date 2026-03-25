"""Sensor platform for Eurostar integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, NUM_DEPARTURES
from .coordinator import DepartureInfo, EurostarCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eurostar sensor entities."""
    coordinator: EurostarCoordinator = entry.runtime_data

    async_add_entities(
        EurostarDepartureSensor(coordinator, entry, i) for i in range(NUM_DEPARTURES)
    )


def _format_status(dep: DepartureInfo) -> str:
    """Format a human-readable status string for a departure."""
    if dep.delay_seconds is None:
        return "Scheduled"
    if dep.delay_seconds == 0:
        return "On time"
    if dep.delay_seconds > 0:
        minutes = dep.delay_seconds // 60
        if minutes < 1:
            return "On time"
        return f"Delayed {minutes} min"
    # Negative delay = ahead of schedule
    return "On time"


class EurostarDepartureSensor(CoordinatorEntity[EurostarCoordinator], SensorEntity):
    """Sensor for an upcoming Eurostar departure."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:train"
    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EurostarCoordinator,
        entry: ConfigEntry,
        index: int,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_departure_{index}"
        self._attr_translation_key = f"departure_{index}"
        self._attr_name = f"Departure {index + 1}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=(
                f"Eurostar {coordinator.origin_name} to {coordinator.destination_name}"
            ),
            manufacturer="Eurostar",
            model="Train Schedule",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _departure(self) -> DepartureInfo | None:
        """Get the departure for this sensor's index."""
        if not self.coordinator.data or self._index >= len(self.coordinator.data):
            return None
        return self.coordinator.data[self._index]

    @property
    def native_value(self) -> datetime | None:
        """Return the effective departure time."""
        dep = self._departure
        if dep is None:
            return None
        return dep.realtime_departure or dep.scheduled_departure

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Return additional departure attributes."""
        dep = self._departure
        if dep is None:
            return {}

        delay_minutes = None
        if dep.delay_seconds is not None:
            delay_minutes = round(dep.delay_seconds / 60, 1)

        duration = dep.scheduled_arrival - dep.scheduled_departure
        duration_minutes = round(duration.total_seconds() / 60)

        return {
            "status": _format_status(dep),
            "scheduled_departure": dep.scheduled_departure.isoformat(),
            "scheduled_arrival": dep.scheduled_arrival.isoformat(),
            "realtime_departure": (
                dep.realtime_departure.isoformat() if dep.realtime_departure else None
            ),
            "delay_minutes": delay_minutes,
            "duration_minutes": duration_minutes,
            "route_name": dep.route_name,
            "headsign": dep.headsign,
            "trip_id": dep.trip_id,
        }
