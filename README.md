# Eurostar for Home Assistant

A Home Assistant custom integration that provides real-time Eurostar train departure information using Eurostar's official GTFS and GTFS-RT open data feeds.

## Features

- Configure origin and destination from 23 Eurostar stations across the UK, France, Belgium, Netherlands, and Germany
- Shows the next 5 upcoming departures as sensor entities
- Real-time delay information updated every 60 seconds
- Each sensor displays a countdown to departure with extra attributes for scheduled/real-time times, delay, route name, and headsign

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Eurostar" and install
3. Restart Home Assistant

### Manual

1. Copy the `custom_components/eurostar` directory to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **Eurostar**
3. Select your origin and destination stations from the dropdowns

## Sensors

For each configured route, the integration creates 5 sensor entities (Departure 1 through 5) representing the next upcoming departures.

Each sensor has:

- **State**: The effective departure time (real-time if available, otherwise scheduled), displayed as a countdown
- **Attributes**:
  - `scheduled_departure` — Scheduled departure time
  - `scheduled_arrival` — Scheduled arrival time
  - `realtime_departure` — Real-time departure time (if available)
  - `delay_minutes` — Delay in minutes (if available)
  - `route_name` — Route identifier
  - `headsign` — Destination displayed on the train
  - `trip_id` — GTFS trip identifier

## Data sources

This integration uses Eurostar's official open data feeds published on [transport.data.gouv.fr](https://transport.data.gouv.fr/datasets/eurostar-gtfs-plan-de-transport-et-temps-reel):

- **Static timetable (GTFS)** — Updated daily, provides scheduled departure and arrival times
- **Real-time updates (GTFS-RT)** — Updated every 30 seconds, provides delay information

Data is provided under the [Licence Ouverte v2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).

## License

Apache 2.0 — see [LICENSE](LICENSE).
