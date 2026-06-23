# Water Dataset Builder — Data Collection & Preparation

This document describes how the water-classification training dataset is
collected and prepared, and how to run the pipeline that builds it. The
pipeline is triggered from your local machine but runs **entirely on
Google Earth Engine (GEE)**; the output is a single GEE
`FeatureCollection` asset that is used to train the Random Forest model.

---

## The Entire Flow of Data Collection / Preparation

### 1. Collecting Water Polygons

Polygons are marked by hand in **Google Earth Pro**. There are four kinds
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

The polygons live in the repo under `waterDatasetBuilder/Data`. More
polygons can be added, or existing ones updated, simply by opening the
files in Google Earth Pro and editing them.

### 2. Upload the Polygons to GEE

Export the polygon files as **KML** and upload them to GEE as table assets
under the folder `waterPolygons`. This is a **required** step — these
uploaded assets are the input to the data-builder pipeline.

Each kind of polygon is uploaded as its own asset so the pipeline can
treat them differently (only the plain large/small categories get
non-water sampling).

### 3. Convert Polygons to Pixels + Attach Sentinel Data

The pipeline converts each polygon into individual pixels and attaches
Sentinel-1 (radar) and Sentinel-2 (optical) information to every pixel. To
keep the dataset balanced, it also samples some **non-water** points
around the two plain polygon categories (large and small).

### 4. Final Data Processing / Engineering

A final processing/engineering pass:

- cleans up pixels with empty / missing information;
- filters out pixels where the Sentinel-1 and Sentinel-2 acquisition dates
  are too far apart from the target date;
- computes the derived features used by the model.

After this, the final dataset is created and used to train the Random
Forest model. It is saved in GEE under the folder `finalDataset`.

> **Note:** the final dataset is also present in the repo at
> `waterDatasetBuilder/Data/full_dataset_v3.csv`.

### Data-flow diagram

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
   Export.table.toAsset  →  single FeatureCollection asset
```

---

## How to Run the Pipeline for Data Collection

### Prerequisites

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

No other libraries are needed — there is no geopandas, pandas, or Drive
client, because nothing is read from local disk or pulled back from GEE.

### Input preparation

1. Mark / edit polygons in Google Earth Pro (see step 1 above).
2. Export each category as a **KML** file.
3. Upload each KML to GEE as a table asset under the `waterPolygons`
   folder (Code Editor → Assets → New → Table upload, or
   `earthengine upload table`).
4. Make sure each polygon keeps its `Name` property (see below) and that
   the asset IDs in `config.py` match the uploaded names exactly.

### Naming convention of polygons

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

### Configuration

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

### Running the pipeline

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

## Output Schema

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

### Feature definitions

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