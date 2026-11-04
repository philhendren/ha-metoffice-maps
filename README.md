# Met Office Maps

A Home Assistant custom integration that turns a Met Office DataHub
**Map Images** order into a looping rain forecast for the next few hours
around your home.

Home Assistant fetches the frames itself, server-side and within the free
plan's daily request budget. It crops them around home, smooths the rain, adds
a coastline and a home marker, and serves finished PNGs. Dashboards only load those images.
**The API key never leaves Home Assistant.**

> Status: v1, under review. The dashboard player is a separate piece of work.

## What you need

1. A Met Office DataHub account with the **Map Images** plan (the free plan
   allows 1,000 requests a day, reset at 00:00 UTC).
2. A Map Images **order** with:
   - region: UK
   - parameters: total precipitation rate (land cover is not needed: the coastline is
     bundled)
   - steps: hourly, covering at least the next 6 hours
   - model runs: all
3. The order ID. The portal shows it as `O123456789012`; the API wants
   `o123456789012`. Either works here: it is converted to lower case.

## Install

1. In HACS, add this repository as a custom repository (category:
   Integration) and install **Met Office Maps**.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Met Office Maps**
   and enter the API key and order ID. Checking them uses one request.

## What you get

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.<name>_rain_forecast` | Model run on show (timestamp) | `frames`: step, valid time and a signed URL for each frame; `last_checked`; `last_error` |
| `sensor.<name>_requests_today` | Requests made today (UTC) | `cap`, `plan_limit`, `remaining`, `budget_exhausted` |

Frames are also served by two authenticated endpoints:

- `GET /api/metoffice_maps/<entry_id>/frames.json` lists the frames on show,
  each with a signed URL for an `<img>` tag.
- `GET /api/metoffice_maps/<entry_id>/frame/<step>.png` returns one frame
  (480 × 480 transparent PNG, with an `ETag` for cheap revalidation).

Valid times come from the Met Office file IDs (run time plus step), never from
the browser's clock.

The `metoffice_maps.refresh` service checks for new frames now, using the
budget like any other check.

## Options

| Option | Default | Notes |
| --- | --- | --- |
| Centre latitude / longitude | Home | |
| Radius | 150 km | The frame shows this distance in every direction |
| Forecast frames | 6 | The next N whole hours |
| Daily request cap | 800 | Up to 950. At the cap, polling stops until 00:00 UTC and the last frames stay on show |
| Check every | 15 min | Each check is one request |

## How frames are drawn

- **Rain** keeps the Met Office colours. Each source pixel covers about 3 km, so
  a 150 km frame is about five times larger than the area it crops. The rain is
  scaled with a bicubic filter and softened by 0.8 of a source pixel, so the
  pixel steps don't show (`SOFTEN` in `render.py`).
- **Land and coastline** come from Natural Earth 1:10m land polygons (public
  domain), bundled in `custom_components/metoffice_maps/data/land.json`. They
  are drawn at four times the frame size and scaled down, so the coast is smooth
  and anti-aliased at any radius. `scripts/build_coastline.py` rebuilds the file.
- After an update that changes how frames look, the frames on disk are redrawn
  from the downloads, with no extra requests.

## Request budget

| What | When | Requests a day |
| --- | --- | --- |
| Check the order's latest listing | Every 15 minutes | 96 |
| Download frames for a new run | When a new run is published (twice a day in Phase 0) | up to 6 each |
| Download the next hour's frame | Once an hour, as the window moves | about 24 |
| Metadata (map bounds) | Once, then cached | about 0 |
| **Typical total** | | **about 130** |

The rules the code enforces:

- Every call counts, including failures, and the count is kept in `.storage`
  under the UTC date, so a restart cannot reset it.
- A download that would cross the cap is not started; the old frames stay.
- After a 429 or 5xx the check interval doubles, up to 2 hours, and returns to
  normal after a success. After a 401 or 403 polling stops and Home Assistant
  asks for a new key. If the order disappears, a repair issue is raised.
- Frames already on disk are never downloaded again. After a restart, frames
  on disk are served straight away and the first check comes after a random
  0–60 s delay.

## How the maps were worked out (Phase 0)

`scripts/discover.py` makes at most 20 requests with your key (read from
`METOFFICE_KEY`, never printed) and writes a report to `discovery/`, which is
git-ignored. Run on 4 November 2026, it settled:

- **Bounds**: from each file's metadata, `fileDetails.file.region.extent`
  (longitude −25 to 15, latitude 45 to 63, "UK model extent").
- **Projection**: equirectangular. Checked against the land cover image at 12
  known land and sea points.
- **Images**: 800 × 800, palette PNGs already coloured with the Met Office rain
  scale; no rain is fully transparent. The integration keeps those colours.
  The land cover image at this size gave a blocky coast (3 km steps), so since
  0.2.0 the coast comes from bundled vector data instead.
- **Runs**: 00Z and 12Z, each listed with dated file IDs
  (`total_precipitation_rate_ts3_2026110400`) and aliases (`…_ts3_+00`).

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Tests run offline against a fake DataHub and require 100% branch coverage.
Plain-English behaviour specs live in `tests/bdd/features/`.

## Licence

MIT. Not affiliated with or endorsed by the Met Office. Coastline data: Natural
Earth (public domain), https://www.naturalearthdata.com.
