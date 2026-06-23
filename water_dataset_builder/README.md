# Water dataset — all-GEE pipeline

Everything runs server-side on Earth Engine. The script is triggered from
your machine but no feature data is ever pulled local — the only traffic
back is task status. Output is a single GEE FeatureCollection asset.

This exists because the hybrid pipeline's `getInfo()` pull hit "User memory
limit exceeded": forcing the whole sample→Sentinel-search→stack graph to
resolve in one interactive call exceeds EE's interactive budget. Running
end-to-end as a batch `Export.table.toAsset` uses the larger batch budget
and sidesteps the problem — the same mechanism your original JS scripts
used.

## Prep: upload inputs as assets
Upload each category's KML/shapefile as its own GEE **table asset** (Code
Editor → Assets → New → Table upload, or `earthengine upload table`). Each
polygon must keep its `Name` property (e.g. `19W19102022`). Then set the
asset IDs in `config.py` under `CATEGORIES`.

NW-ring sampling is on for `large` and `small`, off for the two `_cnnw`
categories and `negatives` — same rule as before.

## Configure
`config.py`:
- `EE_PROJECT` — your EE-enabled Cloud project.
- `ASSET_BASE` / `CATEGORIES` — where your 5 input assets live.
- `OUTPUT_ASSET_ID` — destination FeatureCollection asset.
- `SAMPLE_TILE_SCALE` — leave at 1 (fastest). Raise to 4/8 only if a batch
  run reports a memory error.

## Run
```bash
python main.py
```
First run prompts `ee.Authenticate()`. The script builds the merged,
engineered collection, starts one export task, and polls until the asset
is written. You can also watch it in the Code Editor Tasks tab.

## What runs server-side
1. Parse `Name` → id / waterType / day / month / year (+ polygon area).
2. Sample up to 20 interior water pixels per polygon; for `large`/`small`
   also sample up to 15 non-water pixels in an outer ring.
3. Attach closest Sentinel-1 (±7 d) and Sentinel-2 (±3 d, cloud ≤ 60).
4. Engineer features: VV_VH_ratio, NDWI, MNDWI, BGR, soilIndex, B2_log,
   B3_log, month, sizeClass, and the binary `waterType` label. Filter to
   s1_day_diff ≤ 5.5 and s2_day_diff ≤ 4.5.
5. Merge all categories, keep `OUTPUT_PROPERTIES`, export one asset.

## Differences vs the pandas version
- Feature engineering is now EE-side; formulas are identical (same 1e-6
  guards, same thresholds). Verified numerically against the pandas math.
- The day-diff filter and `sample_missing == 0` drop are EE `.filter()`
  calls now.
- Geometry is retained on the output asset (the pandas CSV dropped it).
  Drop it in `clean_for_export` if you'd rather not keep it.

## Files
- `config.py` — assets, params, output property list
- `ee_logic.py` — parse / sample / enrich / engineer (all server-side)
- `main.py` — merge categories, export one asset, poll
