"""Constants for the Eurostar integration."""

from datetime import timedelta

DOMAIN = "eurostar"

CONF_ORIGIN = "origin"
CONF_DESTINATION = "destination"

GTFS_STATIC_URL = "https://integration-storage.dm.eurostar.com/gtfs-prod/gtfs_static_commercial_v2.zip"
GTFS_RT_URL = "https://integration-storage.dm.eurostar.com/gtfs-prod/gtfs_rt_v2.bin"

STATIC_REFRESH_INTERVAL = timedelta(hours=24)
RT_REFRESH_INTERVAL = timedelta(seconds=60)

NUM_DEPARTURES = 5

ATTRIBUTION = "Data provided by Eurostar"
