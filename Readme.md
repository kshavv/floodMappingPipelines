# Project Documentation

## Contents

1. [Project Overview](#project-overview) — how the four parts connect
2. [Part 1 — Data Collection & Dataset Building](#part-1--data-collection--dataset-building)
3. [Part 2 — Flood Classification Pipeline](#part-2--flood-classification-pipeline)
4. [Part 3 — Bhuvan Flood Pipeline](#part-3--bhuvan-flood-pipeline)
5. [Part 4 — GloFAS / GFM Flood Pipeline](#part-4--glofas--gfm-flood-pipeline)

---

## Project Overview

### What each part produces

| Part | Section | What it produces |
|------|---------|------------------|
| 1. Data Collection | [Part 1](#part-1--data-collection--dataset-building) | The labelled pixel dataset that trains the water model (`full_dataset_v3.csv`) |
| 2. Flood Classification | [Part 2](#part-2--flood-classification-pipeline) | Our own per-state/district classified flood maps from Sentinel-1/2 |
| 3. Bhuvan Pipeline | [Part 3](#part-3--bhuvan-flood-pipeline) | Daily / Kharif flood-extent rasters from Bhuvan/NRSC |
| 4. GloFAS / GFM Pipeline | [Part 4](#part-4--glofas--gfm-flood-pipeline) | Biweekly flood-extent rasters from the GFM service|

### How the parts connect (data flow)

```
        ┌────────────────────────────────────────────────────────────┐
        │  PART 1 — DATA COLLECTION  (waterDatasetBuilder/)          │
        │                                                            │
        │  hand-drawn water/non-water polygons (Google Earth Pro)    │
        │            │                                               │
        │            ▼  sample pixels + attach Sentinel-1/2          │
        │     full_dataset_v3.csv   ← the LABELLED TRAINING SET      │
        │     (also exported to GEE as a FeatureCollection asset)    │
        └───────────────────────────┬────────────────────────────────┘
                                    │  training_fc  (full_dataset_v3.csv)
                                    ▼
        ┌───────────────────────────────────────────────────────────┐
        │  PART 2 — FLOOD CLASSIFICATION (floodClassificationPipe)  │ 
        │  package: flood_mapping/                                  │
        │                                                           │
        │  Step 1  download_temporal_images_for_years(...)          │
        │     • trains a Random Forest on training_fc  ⟵ TRAINING  │
        │       HAPPENS HERE, at runtime (classifiers.py)           │
        │     • applies it to every bi-week of the year             │
        │     • exports a 27-band temporal WATER-MASK stack (asset) │
        │            │                                              │
        │  Step 2  classify_years(...)                              │
        │     • reads the temporal stack                            │
        │     • labels each pixel into flood CLASSES                │
        │       (Kharif: 5 classes; Rabi/Zaid: 2 classes)           │
        │            │                                              │
        │            ▼                                              │
        │     classified flood maps                                 │
        │             |                                             │                   
        │             ▼                                             │
        │  Step 3 Applying temporal corrections                     │
        │             |                                             │
        │             ▼                                             │
        │     Final corrected flood maps                            │
        └───────────────────────────────────────────────────────────┘
```


## Part 1 — Data Collection & Dataset Building

### Water Dataset Builder — Data Collection & Preparation

This document describes the following points:-
- How the water-classification training dataset is collected and prepared.  
- How to run the pipeline that builds it. 


The output is a single csv tables which contains pixel level data for doing water classification.
---

#### The Entire Flow of Data Collection / Preparation

##### 1. Collecting Water Polygons

Polygons are marked manually  in **Google Earth Pro**. There are four kinds
of polygons in total:

- **Large waterbodies** — large water polygons.
- **Small waterbodies (farm ponds)** — small water polygons.
- **Large polygons – cannot sample non-water** — large waterbodies whose
  surroundings are unsuitable for non-water sampling (e.g. nearby
  waterbodies), so no non-water points are drawn around them.
- **Small polygons – cannot sample non-water** — the small-waterbody
  equivalent of the above.

In addition, some polygons are marked later for **hard negative mining** —
after running the flood classification, regions the Random Forest model
mispredicts are added as negatives to correct the model.

The latest polygon data live in the repo under `waterDatasetBuilder/Data` which contains all 5 categories in seperate folder. More
polygons can be added, or existing ones updated, simply by opening the
files in Google Earth Pro and editing them.

##### 2. Upload the Polygons to GEE

Export the polygon files as **KML** and upload them to GEE as table assets
under the folder `waterPolygons`. This is a **required** step — these
uploaded assets are the input to the data-builder pipeline.

Each kind of polygon is uploaded as its own asset so the pipeline can
treat them differently (only the plain large/small categories get
non-water sampling).

##### 3. Convert Polygons to Pixels + Attach Sentinel Data

The pipeline converts each polygon into individual pixels and attaches
Sentinel-1 (radar) and Sentinel-2 (optical) information to every pixel. To
keep the dataset balanced, it also samples some **non-water** points
around the two plain polygon categories (large and small).

##### 4. Final Data Processing / Engineering

A final processing/engineering pass:

- cleans up pixels with empty / missing information;
- filters out pixels where the Sentinel-1 and Sentinel-2 acquisition dates
  are too far apart from the target date;
- computes the derived features used by the model.

After this, the final dataset is created and used to train the Random
Forest model. 

**Note:** To continue with further pipeline the final dataset need to be saved under folder `finalDataset` as gee an gee asset.

> **Note:** the  dataset is also present in the repo at
> `waterDatasetBuilder/Data/full_dataset_v3.csv`.

##### Data-flow diagram

```
  GEE Polygons assets (5 categories)
            │
            ▼
   parse Name → id / type / day / month / year / area
            │
            ├── sample interior water pixels (≤20/polygon)
            └── [if enabled] sample outer NW ring (≤15/polygon)
            │
            ▼
   merge water + NW points
            │
            ▼
   enrich: closest S1 (±7d) + S2 (±3d, cloud≤60) → stack → sample
            │
            ▼
   engineer: indices, logs, sizeClass, label; filter by day-diff
            │
            ▼
   merge all categories → select output properties
            │
            ▼
   Export.table.toAsset  →  single FeatureCollection asset(Final Dataset)
```

---

#### How to Run the Pipeline for Data Collection

##### Prerequisites

- A Google Cloud project with the **Earth Engine API enabled**.
- Python 3.9+ with the Earth Engine client installed:
  ```bash
  pip install -r requirements.txt   # earthengine-api
  ```
- One-time authentication (a browser prompt appears on first run, or run
  it manually):
  ```bash
  earthengine authenticate
  ```


##### Input preparation

1. Mark / edit polygons in Google Earth Pro (see step 1 above).
2. Export each category as a **KML** file.
3. Upload each KML to GEE as a table asset under the `waterPolygons`
   folder (Code Editor → Assets → New → Table upload, or
   `earthengine upload table`).
4. Make sure each polygon keeps its `Name` property (see below) and that
   the asset IDs in `config.py` match the uploaded names exactly.

##### Naming convention of polygons

Every polygon must carry a `Name` property in the form:

```
<id><type><DDMMYYYY>
```

| Name           | id  | type | date        |
|----------------|-----|------|-------------|
| `19W19102022`  | 19  | W    | 2022-10-19  |
| `305W06032025` | 305 | W    | 2025-03-06  |
| `12NW01012020` | 12  | NW   | 2020-01-01  |

- **id** — leading digits identifying the polygon.
- **type** — `W` for water or `NW` for non-water. (The parser checks for
  `NW` before `W`, so `12NW...` is correctly read as non-water.)
- **DDMMYYYY** — the imagery target date used to find matching Sentinel
  scenes.

##### Configuration

All settings live in `config.py`. The variables you need to adjust:

**Project and assets**

| Variable          | What to set it to                                                                 |
|-------------------|-----------------------------------------------------------------------------------|
| `EE_PROJECT`      | Your Earth-Engine-enabled Cloud project id, e.g. `gentle-operator-308420`.        |
| `ASSET_BASE`      | The GEE folder holding your uploaded polygon assets, e.g. `projects/<project>/assets/waterPolygons`. |
| `CATEGORIES`      | Maps each category to its asset path and whether it gets non-water sampling.      |
| `OUTPUT_ASSET_ID` | Destination asset for the final dataset, e.g. `projects/<project>/assets/finalDataset/water_rf_dataset`. |

`CATEGORIES` is the key one. Each entry has an `asset` path and a
`do_nw_sampling` flag — `True` only for the plain large/small categories,
`False` for the two "cannot sample NW" categories and the negatives:

```python
CATEGORIES = {
    "large":      {"asset": ASSET_BASE + "/LargePolygons",     "do_nw_sampling": True},
    "large_cnnw": {"asset": ASSET_BASE + "/LargePolygonsCNNW", "do_nw_sampling": False},
    "small":      {"asset": ASSET_BASE + "/SmallPolygons",     "do_nw_sampling": True},
    "small_cnnw": {"asset": ASSET_BASE + "/SmallPolygonsCNNW", "do_nw_sampling": False},
    "negatives":  {"asset": ASSET_BASE + "/negativeSampling",  "do_nw_sampling": False},
}
```

The asset IDs must match the uploaded names **exactly, including
capitalization** — `negativeSampling` and `negativesampling` are different
assets to GEE.

**Sampling parameters**

| Variable                | Default | Meaning                                                |
|-------------------------|---------|--------------------------------------------------------|
| `SCALE`                 | 10      | Sampling scale in metres.                              |
| `WATER_INTERIOR_BUFFER` | −5      | Inward buffer (m) before sampling water pixels, to avoid mixed edge pixels. |
| `WATER_PTS_PER_POLY`    | 20      | Max water pixels sampled per polygon.                 |
| `NW_INNER_BUFFER`       | 15      | Outward buffer (m) before the non-water ring starts.  |
| `NW_RING_WIDTH`         | 30      | Thickness (m) of the non-water ring.                  |
| `NW_PTS_PER_POLY`       | 15      | Max non-water pixels sampled per polygon.             |
| `SAMPLE_TILE_SCALE`     | 1       | EE tiling for the heavy sample; raise to 4 or 8 only if a run reports a memory error. |

**Sentinel search windows / filters**

| Variable          | Default | Meaning                                              |
|-------------------|---------|------------------------------------------------------|
| `S1_WINDOW_DAYS`  | 7       | ± day window to search for the closest Sentinel-1.   |
| `S2_WINDOW_DAYS`  | 3       | ± day window to search for the closest Sentinel-2.   |
| `S2_MAX_CLOUD`    | 60      | Max `CLOUDY_PIXEL_PERCENTAGE` allowed for Sentinel-2.|
| `S1_BANDS`        | VV, VH  | Sentinel-1 bands kept.                               |
| `S2_BANDS`        | B2,B3,B4,B8,B5,B6,B7,B8A,B11 | Sentinel-2 bands kept.                  |

**Feature-engineering filters**

| Variable               | Default | Meaning                                                       |
|------------------------|---------|---------------------------------------------------------------|
| `S1_DAY_DIFF_MAX`      | 5.5     | Drop pixels whose Sentinel-1 image is further than this (days) from the target date. |
| `S2_DAY_DIFF_MAX`      | 4.5     | Drop pixels whose Sentinel-2 image is further than this (days) from the target date. |
| `SIZECLASS_SMALL_MAX`  | 5,000   | `sizeClass` 0 upper bound (m²).                               |
| `SIZECLASS_MEDIUM_MAX` | 50,000  | `sizeClass` 1 upper bound (m²); larger polygons are class 2.  |

##### Running the pipeline

```bash
python main.py
```

What happens:

1. **Init + auth** — connects to your project (browser login on first run).
2. **Preflight** — checks that all input assets exist and lists any that
   are missing before doing any work.
3. **Build** — constructs the server-side graph for each category.
4. **Export** — starts one batch `Export.table.toAsset` task and polls it,
   printing progress every 20 seconds.
5. **Done** — prints the final asset path when the task completes.

Progress can also be watched in the Code Editor **Tasks** tab. Because the
export is a batch job, runtime scales with the number of polygons; expect
minutes rather than seconds.

---

#### Output Schema

Each feature (row) in the output asset carries these properties:

**Identity & metadata**
`id`, `Name`, `month`, `poly_area_m2`, `sizeClass`,
`s1_datetime_utc`, `s1_day_diff`, `s2_datetime_utc`, `s2_day_diff`

**Sentinel-1 (radar, dB)**
`VV`, `VH`

**Sentinel-2 (optical surface reflectance)**
`B2`, `B3`, `B4`, `B5`, `B6`, `B7`, `B8`, `B8A`, `B11`

**Engineered features**
`VV_VH_ratio`, `NDWI`, `MNDWI`, `BGR`, `soilIndex`, `B2_log`, `B3_log`

**Label**
`waterType` — `1` = water, `0` = non-water

##### Feature definitions

| Feature       | Formula                                   | Purpose                       |
|---------------|-------------------------------------------|-------------------------------|
| `VV_VH_ratio` | `VV - VH`                                 | Radar polarisation contrast   |
| `NDWI`        | `(B3 - B8) / (B3 + B8 + 1e-6)`            | Water vs. vegetation          |
| `MNDWI`       | `(B3 - B11) / (B3 + B11 + 1e-6)`          | Water vs. built-up / soil     |
| `BGR`         | `(B2 - B3) / (B2 + B3 + 1e-6)`            | Blue–green contrast           |
| `soilIndex`   | `B11 / (B4 + 1e-6)`                       | Soil / sand discrimination    |
| `B2_log`      | `ln(B2 + 1e-6)`                           | Expand dark-band differences  |
| `B3_log`      | `ln(B3 + 1e-6)`                           | Expand dark-band differences  |
| `sizeClass`   | 0 if ≤ 5,000 m²; 1 if ≤ 50,000 m²; else 2 | Waterbody size bucket         |

The `1e-6` term guards against division by zero and `ln(0)`.


---

## Part 2 — Flood Classification Pipeline

### Flood Mapping Pipeline Documentation
---

### Environment Setup

#### 1. Prerequisites

- Python 3.7+
- An active Google Earth Engine account.
- A Google Cloud Project with the Earth Engine API enabled.

#### 2. Creating a virtual environment(Optional)
```bash
# 1. Create a virtual environment 
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows
```

#### 3. Installation & Requirements

Install the required dependencies using pip(These are required by bhuvan pipeline or the flood Pipeline):

```bash
pip install -r requirements.txt
```



#### 4. Authentication & Initialization

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

### Pipeline Endpoints & Usage

The pipeline consists of two major stages:

1. **Temporal Image Download** – Generates temporal water-mask image stacks and exports them as Earth Engine assets.
2. **Classification** – Reads the exported temporal stacks and generates classified flood/water maps.

There are two ways to drive these stages:

- **Python API** – import the functions and call them yourself (described in Steps 1 and 2 below). Useful inside notebooks or your own scripts.
- **Command line** – run the bundled `run_pipeline.py` script and pass the state, districts, years, etc. as arguments. This runs the exact same functions with no code edits. See [Command-Line Usage](#command-line-usage).

---

### Step 1: Temporal Image Download
This step builds full-year temporal water-mask stacks (27 bi-weekly intervals) on a strict Kharif-aligned temporal grid and exports them as Earth Engine assets.

#### A. Full State-Level Processing

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

> **Command-line equivalent:**
> ```bash
> python run_pipeline.py --state Kerala --step download
> ```

---

#### B. District-Level Processing

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

> **Command-line equivalent:**
> ```bash
> python run_pipeline.py --state Assam --districts Kamrup Cachar --years 2024 --step download
> ```

> **Important:** Ensure that all export tasks generated during Step 1 have completed successfully in the Earth Engine **Tasks** tab before proceeding to classification.

> **Note** To get the district name for a state. Run this

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

### Step 2: Classification Endpoint

Once the temporal image stacks have been exported as assets, the classification endpoint reads them and generates a final classified image containing 27 temporal bands.

The classification strategy differs by season:

#### Kharif Season

Pixels are classified into **5 classes**:

1. Perennial Water
2. Land
3. Seasonal Water
4. Regular Flood
5. Anomalous Flood

#### Rabi & Zaid Seasons

Pixels are classified into **2 classes**:

1. Water
2. Non-Water

The classification step automatically inherits the spatial boundary (state or district) used during the temporal image generation stage.

##### Example Usage

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

> **Command-line equivalent:**
> ```bash
> python run_pipeline.py --state Kerala --years 2024 --step classify
> ```

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

> **Command-line equivalent:**
> ```bash
> python run_pipeline.py --state Assam --districts Kamrup Cachar --years 2024 --step classify
> ```

---

### Command-Line Usage

Instead of editing a script or notebook, you can run the whole pipeline from the
command line with `run_pipeline.py`. It calls the same `download_temporal_images_for_years`
and `classify_years` functions, so the behaviour is identical to the Python examples above —
you just pass the state, districts, years, and so on as arguments.

Place `run_pipeline.py` in the `floodClassificationPipeline/` directory (next to the
`flood_mapping/` package) and run it from there.

#### Quick start

```bash
# Whole state, default years (2019–2024), download + classify
python run_pipeline.py --state Bihar

# Specific districts and years, download + classify
python run_pipeline.py --state Assam --districts Kamrup Cachar --years 2019 2020 2021 2022 2023 2024
```

#### Running a single stage

Use `--step` to run only one stage. This mirrors the two-step manual workflow.

```bash
# Step 1 only — queue the temporal-image export tasks
python run_pipeline.py --state Assam --districts Kamrup --step download

# Step 2 only — classify (the Step 1 assets must already exist)
python run_pipeline.py --state Assam --districts Kamrup --step classify

# Both stages (this is the default if --step is omitted)
python run_pipeline.py --state Assam --districts Kamrup --step both
```

#### Waiting for export tasks automatically

Classification can only run after the Step 1 export tasks finish. Normally you watch
the Earth Engine **Tasks** tab and start Step 2 manually. Passing `--wait` makes the
script block after download until every export task reaches `COMPLETED`, then runs
classification automatically — so a single command does the entire end-to-end run.

```bash
python run_pipeline.py --state Assam --districts Kamrup --wait
```

`--poll-seconds` controls how often the task status is checked (default 60).

#### Selecting a district by position

If you don't want to type the district name, `--district-index` picks a single district
by its 1-based position in the alphabetised district list for that state.

```bash
# Process the 13th district of Assam
python run_pipeline.py --state Assam --district-index 13
```

Use either `--districts` or `--district-index`, not both. To see the district list and
its ordering, use the `get_district_names` snippet shown in Step 1.

#### All arguments

| Argument            | Required | Default                                                                 | Description                                                                                  |
|---------------------|----------|-------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `--state`           | Yes      | —                                                                       | State name as in FAO GAUL level-1 (e.g. `Kerala`, `Assam`).                                  |
| `--districts`       | No       | (whole state)                                                           | One or more district names, space-separated. Omit to process the whole state.               |
| `--district-index`  | No       | —                                                                       | Pick one district by its 1-based position in the alphabetised list. Alternative to `--districts`. |
| `--years`           | No       | `2019 2020 2021 2022 2023 2024`                                         | One or more years, space-separated.                                                          |
| `--step`            | No       | `both`                                                                  | `download`, `classify`, or `both`.                                                           |
| `--wait`            | No       | off                                                                     | After download, block until export tasks finish, then classify.                             |
| `--poll-seconds`    | No       | `60`                                                                    | How often to poll EE task status when `--wait` is set.                                       |
| `--project`         | No       | `gentle-operator-308420`                                                | Google Cloud project passed to `ee.Initialize()`.                                            |
| `--asset-root`      | No       | `projects/gentle-operator-308420/assets/TemporalImagesNew`              | Root EE asset folder for the temporal stacks.                                                |
| `--output-root`     | No       | `projects/gentle-operator-308420/assets/Classified`                     | Root EE asset folder for classified outputs.                                                 |
| `--training-fc`     | No       | `projects/gentle-operator-308420/assets/finalDataset/full_dataset_v3`   | Training FeatureCollection asset id.                                                         |
| `--destinations`    | No       | `asset`                                                                 | Comma-separated export destinations, e.g. `asset` or `asset,drive`.                          |
| `--drive-folder`    | No       | —                                                                       | Drive folder name (required if `drive` is in `--destinations`).                              |

To print this list at any time:

```bash
python run_pipeline.py --help
```

---

### Notes

- Earth Engine authentication must be completed before running the pipeline.
- Classification should only be run after all temporal image export tasks have completed successfully. (Use `--wait` to enforce this automatically from the command line.)


---

## Part 3 — Bhuvan Flood Pipeline

### Bhuvan Flood Pipeline

Downloads daily flood maps from Bhuvan (NRSC) over WMS, stitches them
into georeferenced GeoTIFFs, and supports both single-date and full-
year (Kharif window) batch runs.
---
#### 1. Creating a virtual environment(Optional)
```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows
```

### 2. Install dependencies
```
pip install -r requirements.txt
```
### 3. Authenticate Earth Engine 
on terminal
```
earthengine authenticate
```

python
```python
import ee
ee.Initialize(project='<your-gcp-project-id>')
```

#### Endpoints

The package exposes two public functions. Both are imported from
`bhuvan_flood`.

There are two ways to run them:

- **Python API** – import the functions and call them yourself (shown below).
- **Command line** – run the bundled `run_bhuvan.py` script and pass the state,
  district, date/year, etc. as arguments. It calls the same functions, so the
  behaviour is identical. See [Command-Line Usage](#command-line-usage).

##### `download_bhuvan_flood_day` — single date

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

##### `download_bhuvan_kharif_stack` — full Kharif window

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

### Command-Line Usage

Instead of editing a script, you can run the pipeline from the command line with
`run_bhuvan.py`. It calls the same `bhuvan_flood` functions shown above — you just
pass the state, district, date/year, and output location as arguments.

Place `run_bhuvan.py` in the `bhuvanFloodPipeline/` directory (next to the
`bhuvan_flood/` package) and run it from there.

#### Choosing what to download

The `--mode` flag selects which endpoint runs:

| `--mode`  | Endpoint called                       | Output                         |
|-----------|---------------------------------------|--------------------------------|
| `day`     | `download_bhuvan_flood_day`           | Single-band GeoTIFF for one date |
| `kharif`  | `download_bhuvan_kharif_stack`        | 140-band Kharif-window stack   |
| `biweek`  | `download_bhuvan_kharif_biweek_stack` | Bi-week aggregated stack       |

#### Examples

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

#### Output paths

- `--output-path` sets the exact `.tif` filename. Use it for `day` mode, or for a
  single year in `kharif`/`biweek` mode.
- `--output-dir` is for processing **multiple years** at once: filenames are
  auto-generated inside that directory (one per year).
- If you give neither, the pipeline falls back to its own built-in default path
  scheme.

#### All arguments

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


---

## Part 4 — GloFAS / GFM Flood Pipeline

### GFM Flood Data Pipeline — Documentation

#### Overview

This pipeline downloads, processes, and stacks Global Flood Monitoring (GFM) satellite-derived flood extent data for a given Indian district and year. The output is a **26-band biweekly GeoTIFF** where each band represents one ~2-week period of the year, clipped to the district boundary.

**Data source:** [EODC GFM STAC API](https://stac.eodc.eu/api/v1)  
**Satellite:** Sentinel-1 SAR-derived flood extent  
**Output CRS:** EPSG:4326  
**Output classes (final clipped TIF):**

| Value | Class |
|-------|-------|
| 1 | Flood extent |
| 2 | Land |
| 3 | Seasonal water |
| 4 | Permanent water |

> Intermediate outputs may contain `0` (unassigned pixels where neither flood nor reference water covered a pixel) and `255` (pixels outside the district boundary set during clipping). Both are removed in the final clipped TIF — within the district boundary, the reference water layer provides complete land/water coverage, so every pixel resolves to a class 1–4.

---

#### Pipeline Architecture

```
District Name
     │
     ▼
[GADM Boundary Lookup]  ──►  AOI bbox + district geometry
     │
     ▼
[STAC Search]  ──►  ENSEMBLE_FLOOD items intersecting AOI
     │
     ├──► [Download]  ──►  ensemble_flood_extent tiles  (per date)
     │                     reference_water_mask tiles   (all dates, merged once)
     │
     ▼
[Merge Tiles per Date]
     │
     ├──► ENSEMBLE_FLOOD_{date}_merged.tif
     └──► REFERENCE_WATER_merged.tif  (shared across all dates)
     │
     ▼
[Combine Flood + Ref Water]  ──►  combined_native_{date}.tif  (classified, native CRS)
     │
     ▼
[Reproject to EPSG:4326]  ──►  combined_4326_{date}.tif
     │
     ▼
[Biweekly Stack]  ──►  gfm_biweekly_{year}.tif  (26-band, full AOI extent)
     │
     ▼
[Clip to District]  ──►  gfm_biweekly_{year}_clipped.tif  (nodata=255 outside boundary)
```

---

#### Prerequisites

##### Python Packages

```bash
pip install -r requirements.txt
```

##### GADM District Boundaries

The pipeline uses GADM Level 2 (district) boundaries for India. Download and cache locally before running:

```python
import geopandas as gpd

gadm_url = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_IND_2.json"
india_districts = gpd.read_file(gadm_url)
india_districts.to_file("india_districts.gpkg", driver="GPKG")
```

This only needs to be done **once** — the file `india_districts.gpkg` is reused on subsequent runs.

---

#### GFM Account Registration

Before running the pipeline, you need a registered account on the GFM portal. The `EMAIL` and `PASSWORD` in the config are the credentials from this account.

1. Go to [https://portal.gfm.eodc.eu/](https://portal.gfm.eodc.eu/)
2. Click **Register** and fill in your details
3. Verify your email address
4. Once verified, your credentials can be used directly in the pipeline config below

The pipeline authenticates via `POST /v2/auth/login` and receives a bearer token used for all subsequent STAC searches and tile downloads. The token is fetched fresh on every run — no manual login is needed after the one-time registration.

---

#### Configuration

Edit these variables at the top of the script before running:

```python
EMAIL         = "your@email.com"     # GFM portal registered email
PASSWORD      = "yourpassword"       # GFM portal password

DISTRICT_NAME = "Barpeta"            # Must match GADM NAME_2 field (case-insensitive)
START_DATE    = "2023-01-01"
END_DATE      = "2023-12-31"
```

**Finding the correct district name:** GADM uses transliterated English spellings. If the exact name is not found, the script will print similar matches to help you correct it.

---

#### Step-by-Step Walkthrough

##### Step 1 — District Boundary Lookup (`get_district_info`)

Reads `india_districts.gpkg`, matches the district name against the `NAME_2` column (case-insensitive), and returns:

- `aoi_bbox` — padded bounding box `[west, south, east, north]` used for STAC search
- `district_geom` — GeoJSON-like geometry dict used for final clipping

A 0.1° padding is added around the district boundary so that STAC tile search captures edge tiles fully.

##### Step 2 — STAC Search (`search_products`)

Queries the EODC STAC API for all `GFM` collection items:

- Spatially filtered to `aoi_bbox`
- Temporally filtered to `START_DATE` / `END_DATE`
- Further filtered to items whose ID contains `ENSEMBLE_FLOOD` and whose footprint actually intersects the AOI

The date is extracted from the item ID (format: `ENSEMBLE_FLOOD_YYYYMMDDTHHMMSS_...`).

##### Step 3 — Coverage Check (`check_spatial_coverage`)

Computes the union of all item footprints and reports what percentage of the AOI is covered. Useful for identifying gaps in the Sentinel-1 acquisition schedule.

##### Step 4 — Download (`download_products`, `search_reference_water`)

Downloads two asset types per STAC item:

- `ensemble_flood_extent` — binary flood mask (0 = no flood, 1 = flood)
- `reference_water_mask` — reference water classes (0 = land, 1 = permanent water, 2 = seasonal water)

Files are saved to `gfm_downloads/`. Already-downloaded files are skipped.

Reference water tiles are also searched independently across the full AOI to ensure complete spatial coverage even on dates where no flood items exist.

##### Step 5 — Merge Tiles (`merge_per_date`)

Tiles are mosaicked using `rasterio.merge`:

- **Flood:** one merged file per acquisition date → `gfm_merged/ENSEMBLE_FLOOD_{date}_merged.tif`
- **Reference water:** all tiles merged once → `gfm_merged/REFERENCE_WATER_merged.tif` (reused for every date)

##### Step 6 — Classification (`combine_tifs`)

For each date, combines the flood and reference water layers into a single classified raster:

```
Priority order (flood takes precedence over water classes):

  flood == 1                          → class 1 (flood)
  flood != 1 AND ref_water == 0       → class 2 (land)
  flood != 1 AND ref_water == 2       → class 3 (seasonal water)
  flood != 1 AND ref_water == 1       → class 4 (permanent water)
  everything else                     → class 0 (unclassified)
```

Both layers are reprojected to the flood tile's native CRS and grid during compositing.

##### Step 7 — Reproject to EPSG:4326 (`reproject_to_4326`)

Reprojects each classified TIF to geographic coordinates (EPSG:4326) using nearest-neighbour resampling to preserve discrete class values. A colormap is embedded:

| Class | Color |
|-------|-------|
| 1 — Flood | Violet `(148, 0, 211)` |
| 2 — Land | White `(255, 255, 255)` |
| 3 — Seasonal water | Cyan `(0, 255, 255)` |
| 4 — Permanent water | Blue `(0, 0, 255)` |

Intermediate `combined_native_{date}.tif` files are deleted after reprojection to save disk space.

##### Step 8 — Biweekly Stack (`create_biweekly_stack`)

Groups the daily classified TIFs into 26 biweekly periods (each ~14 days). The output is a 26-band GeoTIFF where Band N corresponds to biweek N of the year.

**Grid computation:** The output grid extent is computed as the **union of all input file extents** — i.e. the bounding box that covers every daily TIF. Each file is then reprojected onto this common grid before compositing. This ensures no data is lost when different acquisition dates have slightly different spatial coverages. Pixels in the union extent that fall outside all input files remain `0` at this stage, but are removed in the subsequent district clipping step.

**Priority compositing** within each biweek (highest priority wins per pixel):

```
Flood (1) > Seasonal water (3) > Permanent water (4) > Land (2)
```

This means if any single day in a biweek shows flooding at a pixel, the biweek band records it as flood.

Band descriptions are written as `Biweek_1` through `Biweek_26`.

##### Step 9 — Clip to District (`clip_to_district`)

Clips the 26-band stack to the exact district polygon using `rasterio.mask`. Pixels outside the district boundary are set to `nodata=255` (chosen to avoid conflict with valid class values 1–4). Within the district, the reference water layer provides complete coverage, so no `0` pixels remain — every pixel in the final output is one of classes 1–4.

Output: `gfm_biweekly_{year}_clipped.tif`

---

#### Output Files

| File | Location | Description |
|------|----------|-------------|
| `gfm_downloads/*.tif` | `gfm_downloads/` | Raw downloaded tiles |
| `ENSEMBLE_FLOOD_{date}_merged.tif` | `gfm_merged/` | Merged flood tiles per date |
| `REFERENCE_WATER_merged.tif` | `gfm_merged/` | Single merged reference water mosaic |
| `combined_4326_{date}.tif` | `gfm_final/` | Classified + reprojected TIF per date |
| `gfm_biweekly_{year}.tif` | `gfm_final/` | 26-band biweekly stack (full AOI) |
| `gfm_biweekly_{year}_clipped.tif` | `gfm_final/` | 26-band stack clipped to district boundary |

The clipped file is the primary deliverable for downstream analysis and validation.

---

#### Resumability

The pipeline is designed to be re-run safely:

- Downloaded tiles are skipped if the file already exists
- Merged TIFs are skipped if already present
- Per-date combined TIFs are skipped if `combined_4326_{date}.tif` already exists

To reprocess a specific date, delete the corresponding `combined_4326_{date}.tif` from `gfm_final/`.

---

#### Common Issues

**District not found**
The script prints similar GADM `NAME_2` values when no exact match is found. Use the suggested spelling exactly.

**No STAC items returned**
Check that `START_DATE` / `END_DATE` and `DISTRICT_NAME` are correct. Sentinel-1 has a ~6–12 day revisit cycle, so some short date ranges may return no items for small districts.

**Partial AOI coverage**
If `check_spatial_coverage` reports < 100%, the district likely straddles a fixed GFM tile boundary. This is expected — the stack compositing will still capture all available data.

**API 502/503/504 errors**
The EODC API occasionally returns transient errors. Adding a retry loop around `requests.get` calls (with exponential backoff) is recommended for large downloads.

---
