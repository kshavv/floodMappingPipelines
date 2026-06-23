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

There are two ways to drive these stages:

- **Python API** – import the functions and call them yourself (described in Steps 1 and 2 below). Useful inside notebooks or your own scripts.
- **Command line** – run the bundled `run_pipeline.py` script and pass the state, districts, years, etc. as arguments. This runs the exact same functions with no code edits. See [Command-Line Usage](#command-line-usage).

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

> **Command-line equivalent:**
> ```bash
> python run_pipeline.py --state Kerala --step download
> ```

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

# Command-Line Usage

Instead of editing a script or notebook, you can run the whole pipeline from the
command line with `run_pipeline.py`. It calls the same `download_temporal_images_for_years`
and `classify_years` functions, so the behaviour is identical to the Python examples above —
you just pass the state, districts, years, and so on as arguments.

Place `run_pipeline.py` in the `floodClassificationPipeline/` directory (next to the
`flood_mapping/` package) and run it from there.

## Quick start

```bash
# Whole state, default years (2019–2024), download + classify
python run_pipeline.py --state Bihar

# Specific districts and years, download + classify
python run_pipeline.py --state Assam --districts Kamrup Cachar --years 2019 2020 2021 2022 2023 2024
```

## Running a single stage

Use `--step` to run only one stage. This mirrors the two-step manual workflow.

```bash
# Step 1 only — queue the temporal-image export tasks
python run_pipeline.py --state Assam --districts Kamrup --step download

# Step 2 only — classify (the Step 1 assets must already exist)
python run_pipeline.py --state Assam --districts Kamrup --step classify

# Both stages (this is the default if --step is omitted)
python run_pipeline.py --state Assam --districts Kamrup --step both
```

## Waiting for export tasks automatically

Classification can only run after the Step 1 export tasks finish. Normally you watch
the Earth Engine **Tasks** tab and start Step 2 manually. Passing `--wait` makes the
script block after download until every export task reaches `COMPLETED`, then runs
classification automatically — so a single command does the entire end-to-end run.

```bash
python run_pipeline.py --state Assam --districts Kamrup --wait
```

`--poll-seconds` controls how often the task status is checked (default 60).

## Selecting a district by position

If you don't want to type the district name, `--district-index` picks a single district
by its 1-based position in the alphabetised district list for that state.

```bash
# Process the 13th district of Assam
python run_pipeline.py --state Assam --district-index 13
```

Use either `--districts` or `--district-index`, not both. To see the district list and
its ordering, use the `get_district_names` snippet shown in Step 1.

## All arguments

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

# Notes

- Earth Engine authentication must be completed before running the pipeline.
- Classification should only be run after all temporal image export tasks have completed successfully. (Use `--wait` to enforce this automatically from the command line.)