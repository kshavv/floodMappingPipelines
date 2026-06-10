# Bhuvan Flood Pipeline

Download Bhuvan's daily flood layers via WMS, stitch them into masks,
and write them as georeferenced GeoTIFFs. Two endpoints, four AOI
modes, three levels of logging.

## Two endpoints

| Endpoint                          | Input            | Output                            |
| --------------------------------- | ---------------- | --------------------------------- |
| `download_bhuvan_kharif_stack`    | `state, year`    | Multi-band GeoTIFF, 140 bands     |
| `download_bhuvan_flood_day`       | `state, date`    | Single-band GeoTIFF, one date     |

The day endpoint is useful for quickly inspecting a known flood date,
or for testing whether a layer-name pattern is right before committing
to a 140-day run.

## Four AOI modes

Both endpoints accept the same AOI options:

| Spec                                                       | Tiles per day (Kerala) | Setup needed              |
| ---------------------------------------------------------- | ---------------------- | ------------------------- |
| `state='Kerala'`                                           | ~500                   | none                      |
| `state='Kerala', district='Ernakulam'`                     | ~10-30                 | `ee.Initialize(...)`      |
| `state='Kerala', district_geometry=<shapely Polygon>`      | depends on polygon     | none                      |
| (advanced) custom `BhuvanClient`                           | —                      | —                         |

District mode is ~50x fewer requests because tile-grid covers a much
smaller bbox AND we drop tiles that don't intersect the district
polygon (no HTTP request for them).

## Output

| Property            | Year endpoint                | Day endpoint               |
| ------------------- | ---------------------------- | -------------------------- |
| Format              | GeoTIFF (BigTIFF if needed)  | GeoTIFF                    |
| Bands               | 140 (one per Kharif day)     | 1                          |
| Pixel type          | `uint8` (0/1 mask)           | `uint8` (0/1 mask)         |
| CRS                 | EPSG:4326                    | EPSG:4326                  |
| Resolution          | ~76 m at the equator         | ~76 m at the equator       |
| Band descriptions   | ISO dates                    | ISO date                   |
| Per-band tags       | `date`, `bhuvan_layer`       | `date`, `bhuvan_layer`     |
| File tags           | `state`, `district`, `year`  | `state`, `district`, `date`|

Days/dates without Bhuvan data become all-zero bands. District-mode
output is masked to the district polygon shape; state-mode output is
bbox-shaped.

## Class encoding

Every band: `uint8`, **0 = land / no data**, **1 = flood**.

## Logging flags

Both endpoints accept:

| Flag                 | What it does                                                       |
| -------------------- | ------------------------------------------------------------------ |
| `log=True`           | (year endpoint) One status line per day during the run             |
| `debug=True`         | Upfront diagnostic block before any tile is fetched (steps 1-6).   |
|                      | Includes state config, AOI bbox, tile-grid math, polygon stats,    |
|                      | sample tiles, run plan, latency estimate.                          |
| `verbose=True`       | One line per tile during stitching — URL, status, bytes, elapsed.  |
| `tile_cache_dir=...` | Save every raw PNG tile to disk for QGIS inspection.               |

## Fast-fail probe (NEW)

`BhuvanClient` now uses a short-timeout, no-retry probe to detect
whether Bhuvan has a flood layer for a given date. Previously the
probe inherited the full `(timeout=30, max_retries=3,
backoff=exponential)` settings used for real tile fetches, so a date
without data could spend a minute or more grinding through retries on
each of the 4 suffix variants. The probe now uses
`probe_timeout=5.0s` with no retries: Bhuvan either responds in 5s or
we treat the date as "no data" and move on.

This makes no-data days near-instant; days with data are unchanged.

## Install

```bash
pip install rasterio pillow requests numpy shapely
# Only if you want district-name resolution:
pip install earthengine-api
earthengine authenticate
```

## Usage

### Day endpoint

```python
from bhuvan_flood import download_bhuvan_flood_day

# Whole state, one date
download_bhuvan_flood_day(
    state='Kerala', date='2018-08-16',
    debug=True,
)
# -> ./bhuvan_flood_kerala_2018-08-16.tif
```

```python
# Single district, one date (needs ee.Initialize)
import ee
ee.Initialize(project='your-project')

download_bhuvan_flood_day(
    state='Kerala', district='Ernakulam', date='2018-08-16',
    debug=True,
)
# -> ./bhuvan_flood_kerala_ernakulam_2018-08-16.tif
```

### Year endpoint

```python
from bhuvan_flood import download_bhuvan_kharif_stack

download_bhuvan_kharif_stack(
    state='Kerala', year=2018,
    debug=True,            # upfront diagnostic block
    log=True,              # per-day status during the run
)
# -> ./bhuvan_kharif_kerala_2018.tif  (140 bands)
```

```python
# Single district, whole year
download_bhuvan_kharif_stack(
    state='Kerala', district='Ernakulam', year=2018,
    debug=True,
)
# -> ./bhuvan_kharif_kerala_ernakulam_2018.tif
```

## Module layout

| Module               | Role                                                |
| -------------------- | --------------------------------------------------- |
| `config.py`          | State -> (code, bbox) mapping, grid constants       |
| `wms_client.py`      | URL building, layer probe (fast-fail), tile fetch   |
| `stitch.py`          | Tile stitching + cyan-pixel test + polygon filter   |
| `districts.py`       | GAUL level-2 district polygon resolution            |
| `pipeline.py`        | Both endpoints + shared AOI/debug helpers           |
