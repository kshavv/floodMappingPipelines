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

