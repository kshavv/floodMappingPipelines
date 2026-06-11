# Flood Mapping Pipeline Documentation
---

# Environment Setup

## 1. Prerequisites

- Python 3.7+
- An active Google Earth Engine account.
- A Google Cloud Project with the Earth Engine API enabled.

## 2. Creating a virtual environment(Optional)
```bash
# 1. Create a virtual environment 
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows
```

## 3. Installation & Requirements

Install the required dependencies using pip(These are required by bhuvan pipeline or the flood Pipeline):

```bash
pip install -r requirements.txt
```



## 4. Authentication & Initialization

Before running any scripts, authenticate your machine with Earth Engine:

```bash
earthengine authenticate
```

Follow the browser prompts to complete authentication.

In your Python scripts, initialize the Earth Engine client using your Google Cloud Project ID:

```python
import ee
ee.Initialize(project='your-google-cloud-project-id')
```

---

# Pipeline Endpoints & Usage

The pipeline consists of two major stages:

1. **Temporal Image Download** – Generates temporal water-mask image stacks and exports them as Earth Engine assets.
2. **Classification** – Reads the exported temporal stacks and generates classified flood/water maps.

---

# Step 1: Temporal Image Download
This step builds full-year temporal water-mask stacks (27 bi-weekly intervals) on a strict Kharif-aligned temporal grid and exports them as Earth Engine assets.

## A. Full State-Level Processing

To generate temporal images for an entire state, provide the state name. The pipeline automatically resolves the state boundary and queues the export tasks.

```python

from flood_mapping import download_temporal_images_for_years

# Configuration
STATE = 'Kerala'
YEARS = [2019, 2020, 2021, 2022, 2023, 2024]

ASSET_ROOT = 'projects/gentle-operator-308420/assets/TemporalImages'
TRAINING_FC = 'projects/gentle-operator-308420/assets/finalDataset/full_dataset_v3'

# Queue export tasks for the whole state
download_temporal_images_for_years(
    state=STATE,
    years=YEARS,
    training_fc=TRAINING_FC,
    asset_root=ASSET_ROOT,
    destinations='asset'  # Can also include 'drive'
)
```

---

## B. District-Level Processing

To process only selected districts instead of the entire state, provide a list of district names through the `districts` parameter.

The pipeline automatically:

- Resolves district geometries.
- Clips processing to the selected districts.
- Adjusts export naming conventions accordingly.

```python

from flood_mapping import download_temporal_images_for_year

# Queue export task for specific districts
download_temporal_images_for_year(
    state='Assam',
    districts=['Kamrup', 'Cachar'],
    year=2024,
    training_fc='projects/gentle-operator-308420/assets/finalDataset/full_dataset_v3',
    asset_root='projects/gentle-operator-308420/assets/TemporalImages',
    destinations='asset'
)
```

> **Important:** Ensure that all export tasks generated during Step 1 have completed successfully in the Earth Engine **Tasks** tab before proceeding to classification.

> **Note** To get the district name for a state 
 Run this

 ```python
 import ee
ee.Initialize(project='gentle-operator-308420')
from flood_mapping import get_district_names

# Fetch all districts for Assam
assam_districts = get_district_names('Assam')

print(f"Total districts found: {len(assam_districts)}")
print(assam_districts)
```
---

# Step 2: Classification Endpoint

Once the temporal image stacks have been exported as assets, the classification endpoint reads them and generates a final classified image containing 27 temporal bands.

The classification strategy differs by season:

## Kharif Season

Pixels are classified into **5 classes**:

1. Perennial Water
2. Land
3. Seasonal Water
4. Regular Flood
5. Anomalous Flood

## Rabi & Zaid Seasons

Pixels are classified into **2 classes**:

1. Water
2. Non-Water

The classification step automatically inherits the spatial boundary (state or district) used during the temporal image generation stage.

### Example Usage

```python

from flood_mapping import classify_years

# Configuration
STATE = 'Kerala'

# Optional:
# DISTRICTS = ['Ernakulam']

YEARS = [2024]

ASSET_ROOT = 'projects/gentle-operator-308420/assets/TemporalImages'
OUTPUT_ROOT = 'projects/gentle-operator-308420/assets/Classified'

# Run classification
classify_years(
    state=STATE,
    # districts=DISTRICTS,
    years=YEARS,
    asset_root=ASSET_ROOT,
    destinations='asset',
    output_root=OUTPUT_ROOT
)
```

To run the classification for specific districts rather than the entire state, simply uncomment and pass the `districts` list parameter. The pipeline will automatically mask the output to the shape of the requested district(s) instead of the whole state.

```python
from flood_mapping import classify_years

# Configuration
STATE = 'Assam'
DISTRICTS = ['Kamrup', 'Cachar']  # Provide the exact district names
YEARS = [2024]

ASSET_ROOT = 'projects/gentle-operator-308420/assets/TemporalImages'
OUTPUT_ROOT = 'projects/gentle-operator-308420/assets/Classified'

# Run classification for the specific districts
classify_years(
    state=STATE,
    districts=DISTRICTS,  # <--- Pass the districts list here
    years=YEARS,
    asset_root=ASSET_ROOT,
    destinations='asset',
    output_root=OUTPUT_ROOT
)
```



# Notes

- Earth Engine authentication must be completed before running the pipeline.
- Classification should only be run after all temporal image export tasks have completed successfully.

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

