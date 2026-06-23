# Bhuvan Flood Pipeline

Downloads daily flood maps from Bhuvan (NRSC) over WMS, stitches them
into georeferenced GeoTIFFs, and supports both single-date and full-
year (Kharif window) batch runs.
---
## 1. Creating a virtual environment(Optional)
```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows
```

# 2. Install dependencies
```
pip install -r requirements.txt
```
# 3. Authenticate Earth Engine 
on terminal
```
earthengine authenticate
```

python
```python
import ee
ee.Initialize(project='<your-gcp-project-id>')
```

## Endpoints

The package exposes two public functions. Both are imported from
`bhuvan_flood`.

There are two ways to run them:

- **Python API** – import the functions and call them yourself (shown below).
- **Command line** – run the bundled `run_bhuvan.py` script and pass the state,
  district, date/year, etc. as arguments. It calls the same functions, so the
  behaviour is identical. See [Command-Line Usage](#command-line-usage).

### `download_bhuvan_flood_day` — single date

Builds a **single-band** GeoTIFF for one specific calendar date.

**Whole state:**

```python
from bhuvan_flood import download_bhuvan_flood_day

download_bhuvan_flood_day(
    state='Kerala',
    date='2023-07-06',
    output_path='./final_raster/kerala_2023-07-06.tif',
)
```

> **Command-line equivalent:**
> ```bash
> python run_bhuvan.py --mode day --state Kerala --date 2023-07-06 \
>     --output-path ./final_raster/kerala_2023-07-06.tif
> ```

**Single district** (requires Earth Engine; see Environment setup):

```python
import ee
ee.Initialize(project='<your-gcp-project-id>')

from bhuvan_flood import download_bhuvan_flood_day

download_bhuvan_flood_day(
    state='Kerala',
    district='Ernakulam',
    date='2023-07-06',
    output_path='./final_raster/kerala_ernakulam_2023-07-06.tif',
)
```

> **Command-line equivalent:**
> ```bash
> python run_bhuvan.py --mode day --state Kerala --district Ernakulam \
>     --date 2023-07-06 --output-path ./final_raster/kerala_ernakulam_2023-07-06.tif
> ```

Use this endpoint for sanity-checking a single known-flood date
before committing to a full year, or for ad-hoc per-event analysis.

### `download_bhuvan_kharif_stack` — full Kharif window

Builds a **140-band** GeoTIFF covering Jun 1 → Oct 18 of a given year.
Each band is one calendar day; bands for days without Bhuvan data are
all-zero placeholders so band index always equals day-of-Kharif.

**Whole state:**

```python
from bhuvan_flood import download_bhuvan_kharif_stack

download_bhuvan_kharif_stack(
    state='Kerala',
    year=2023,
    output_path='./final_raster/kerala_kharif_2023.tif',
)
```

> **Command-line equivalent:**
> ```bash
> python run_bhuvan.py --mode kharif --state Kerala --years 2023 \
>     --output-path ./final_raster/kerala_kharif_2023.tif
> ```

**Single district** (requires Earth Engine):

```python
import ee
ee.Initialize(project='<your-gcp-project-id>')

from bhuvan_flood import download_bhuvan_kharif_stack

download_bhuvan_kharif_stack(
    state='Kerala',
    district='Ernakulam',
    year=2023,
    output_path='./final_raster/kerala_ernakulam_kharif_2023.tif',
)
```

> **Command-line equivalent:**
> ```bash
> python run_bhuvan.py --mode kharif --state Kerala --district Ernakulam \
>     --years 2023 --output-path ./final_raster/kerala_ernakulam_kharif_2023.tif
> ```

---

# Command-Line Usage

Instead of editing a script, you can run the pipeline from the command line with
`run_bhuvan.py`. It calls the same `bhuvan_flood` functions shown above — you just
pass the state, district, date/year, and output location as arguments.

Place `run_bhuvan.py` in the `bhuvanFloodPipeline/` directory (next to the
`bhuvan_flood/` package) and run it from there.

## Choosing what to download

The `--mode` flag selects which endpoint runs:

| `--mode`  | Endpoint called                       | Output                         |
|-----------|---------------------------------------|--------------------------------|
| `day`     | `download_bhuvan_flood_day`           | Single-band GeoTIFF for one date |
| `kharif`  | `download_bhuvan_kharif_stack`        | 140-band Kharif-window stack   |
| `biweek`  | `download_bhuvan_kharif_biweek_stack` | Bi-week aggregated stack       |

## Examples

```bash
# Single date, whole state
python run_bhuvan.py --mode day --state Kerala --date 2023-07-06

# Single date, one district
python run_bhuvan.py --mode day --state Kerala --district Ernakulam --date 2023-07-06

# Full Kharif stack, whole state, one year
python run_bhuvan.py --mode kharif --state Kerala --years 2023

# Full Kharif stack, one district, several years (auto-named files in a folder)
python run_bhuvan.py --mode kharif --state Kerala --district Ernakulam \
    --years 2022 2023 2024 --output-dir ./final_raster

# Bi-week aggregated stack
python run_bhuvan.py --mode biweek --state Kerala --years 2023
```

## Output paths

- `--output-path` sets the exact `.tif` filename. Use it for `day` mode, or for a
  single year in `kharif`/`biweek` mode.
- `--output-dir` is for processing **multiple years** at once: filenames are
  auto-generated inside that directory (one per year).
- If you give neither, the pipeline falls back to its own built-in default path
  scheme.

## All arguments

| Argument            | Required                     | Default   | Description                                                                 |
|---------------------|------------------------------|-----------|-----------------------------------------------------------------------------|
| `--mode`            | No                           | `kharif`  | `day`, `kharif`, or `biweek` (see table above).                             |
| `--state`           | Yes                          | —         | State name registered in `bhuvan_flood/config.py` `STATES`.                 |
| `--district`        | No                           | (whole state) | Single district name within the state.                                  |
| `--date`            | Yes for `--mode day`         | —         | ISO date `YYYY-MM-DD`.                                                       |
| `--years`           | Yes for `kharif`/`biweek`    | —         | One or more years, space-separated.                                         |
| `--output-path`     | No                           | —         | Exact output `.tif` path (day mode, or single-year stack).                  |
| `--output-dir`      | No                           | —         | Directory for auto-named outputs when processing multiple years.            |
| `--bbox-buffer-deg` | No                           | `0.05`    | Buffer (degrees) added around the AOI bbox.                                 |
| `--no-clip`         | No                           | off       | Keep the bbox rectangle instead of clipping to the state/district polygon.  |
| `--tile-cache-dir`  | No                           | —         | Directory to cache downloaded tiles.                                        |
| `--debug`           | No                           | off       | Print the verbose debug header.                                             |
| `--verbose`         | No                           | off       | Verbose logging.                                                            |

To print this list at any time:

```bash
python run_bhuvan.py --help
```

> **Note:** District mode requires Earth Engine (used to resolve the district
> polygon), so authenticate and initialise first as shown in the setup section.