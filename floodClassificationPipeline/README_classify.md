# Flood Mapping — Classification Pipeline

This package extends the download pipeline. The download side builds and
exports per-year temporal water-mask stacks; this side reads those
exported full-year assets and classifies them into a **single multi-band
classification image** that is exported as one asset (and/or GeoTIFF).

## What it produces

For a target year + state (optionally a district subset), one **27-band**
`ee.Image` (`Classified_<year>_<title>`), bands `BW_1 … BW_27`, on the
**same Kharif-aligned grid** as the input `RF_water_FullYear_<year>_<title>`
assets. The output is masked to the state polygon, so every band has the
state outline — not a bounding-box rectangle.

Each band is classified according to which season its bi-week falls in:

| Season | Bands (Kharif-aligned grid)     | Window (approx)   | Scheme   |
| ------ | ------------------------------- | ----------------- | -------- |
| Kharif | `BW_12 … BW_21`                 | Jun 1 → Oct 4     | 5-class  |
| Zaid   | `BW_8 … BW_11`                  | Apr 6 → May 17    | 2-class  |
| Rabi   | `BW_1 … BW_7` + `BW_22 … BW_27` | late Dec / Nov–Mar| 2-class  |

Rabi absorbs every non-Kharif, non-Zaid slot, so all 27 bands are
classified — there are no masked gaps.

### Class codes (shared by every band)

| Code | 5-class (Kharif)   | 2-class (Rabi / Zaid) |
| ---- | ------------------ | --------------------- |
| 1    | Perennial water    | Water                 |
| 2    | Land / non-water   | Non-water             |
| 3    | Seasonal water     | —                     |
| 4    | Regular flood      | —                     |
| 5    | Anomalous water    | —                     |

Codes 3/4/5 only ever appear in Kharif bands. Water=1 / non-water=2 was
chosen for Rabi/Zaid so a single 5-class palette renders every band.

## How the Kharif 5-class step works

It mirrors `ee_app.js` exactly, but reads the exported stacks instead of
rebuilding from Sentinel:

- **Perennial frequency** — water fraction across all 27 bands of the
  target-year full-year stack.
- **Bi-week frequency** — for each Kharif slot, the water fraction at
  the *same slot index* across all historical full-year stacks (the
  Kharif-aligned grid is identical across years, so a slot is the same
  calendar window in every year).
- **Seasonal ("yearly") frequency** — water fraction across the Kharif
  bands (slots 11–20) of the target-year stack.
- **Classification** — `classifyFloodMap` logic: perennial / land /
  seasonal / regular / anomalous from those three frequencies + the
  thresholds.
- **Temporal corrections** (optional, on by default) — `applyCorrections`
  logic: demote isolated / high-transition water back to land using the
  Kharif sub-stack.

## Polygon mask (state-shaped output)

`build_classification_image` masks the final 27-band stack by the polygon
ROI before export. This is necessary because:

1. The `where()` operations build code values everywhere the *condition*
   is valid, so without an explicit mask the Rabi/Zaid bands fill the
   bounding-box rectangle with code 2.
2. The Kharif bands look state-shaped in the JS app only because their
   "outside" value is 0, which falls outside the `{min:1,max:5}` vis
   stretch and renders transparent — the asset still contains 0s in the
   rectangle.

Both pathologies disappear once the polygon mask is applied. Set
`apply_geometry_mask=False` to keep the rectangle if you want it.

## Install

```bash
pip install earthengine-api
earthengine authenticate
```

## Usage

```python
import ee
ee.Initialize(project='gentle-operator-308420')

from flood_mapping import classify_year

result = classify_year(
    state='Kerala',
    year=2024,
    asset_root='projects/gentle-operator-308420/assets/TemporalImages',
    destinations='asset',
    output_root='projects/gentle-operator-308420/assets/Classified',
)
print(result['output_asset_id'])    # Classified_2024_kerala
```

Then open the **Tasks** tab in the Code Editor (or `ee.batch.Task.list()`)
and run the queued export.

For a district subset:

```python
classify_year(
    state='Kerala',
    districts=['Ernakulam', 'Kollam', 'Thrissur'],
    year=2024,
    asset_root=ASSET_ROOT,
    destinations='asset',
    output_root=OUTPUT_ROOT,
)
# Title auto-derives to 'kerala_3,7,12' — same rule as the download pipeline.
```

For batching:

```python
from flood_mapping import classify_years
classify_years(
    state='Kerala', years=[2019, 2020, 2021, 2022, 2023, 2024],
    asset_root=ASSET_ROOT,
    destinations='asset', output_root=OUTPUT_ROOT,
)
```

See `example_classify.py` for more.

## Key parameters

- `historical_years` — years supplying the Kharif cross-year frequency
  (default `[2019…2024]`). Missing assets are dropped with a warning;
  the target year is always included.
- `thresholds` — override `{'perennial','biweek','biweekAn','yearlyAn'}`.
- `apply_temporal_corrections` — default `True`.
- `apply_geometry_mask` — default `True` (polygon-shaped output).
- `roi` / `title` — explicit overrides when you skipped the admin path.
- `skip_existing` — skip the asset export if the output already exists.

## Module layout

| Module               | Role                                                   |
| -------------------- | ------------------------------------------------------ |
| `classify_config.py` | Season slot ranges, class codes, thresholds, asset ids |
| `classify_core.py`   | Frequencies, 5-class + 2-class classifiers, corrections|
| `classify_build.py`  | Assemble the 27-band classification image + polygon mask |
| `classify_year.py`   | Public entry point: AdminRoi, load assets, classify, export |

The original download modules (`download_year.py`, `stacks.py`,
`classifiers.py`, `admin.py`, `config.py`) are unchanged.
