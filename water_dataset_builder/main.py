"""
All-GEE pipeline orchestrator.

Builds each category server-side, merges them, and exports a single
FeatureCollection asset. The only thing that touches your machine is task
status polling — no feature data is pulled local.

Run:  python main.py
"""

import time
import ee

import config
import ee_logic


def init_ee():
    try:
        ee.Initialize(project=config.EE_PROJECT)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=config.EE_PROJECT)


def build_merged():
    parts = []
    for label, meta in config.CATEGORIES.items():
        print(f"  building category: {label} (NW sampling={meta['do_nw_sampling']})")
        fc = ee_logic.build_category(meta["asset"], meta["do_nw_sampling"])
        # Tag with category for traceability.
        fc = fc.map(lambda f: f.set("category", label))
        parts.append(fc)

    merged = parts[0]
    for p in parts[1:]:
        merged = merged.merge(p)
    return merged


def clean_for_export(fc):
    """Keep only the output properties (geometry retained on the asset)."""
    props = config.OUTPUT_PROPERTIES

    def keep(f):
        d = ee.Dictionary.fromLists(
            ee.List(props),
            ee.List([f.get(k) for k in props]))
        return ee.Feature(f.geometry()).set(d)

    return fc.map(keep)


def export_asset(fc):
    task = ee.batch.Export.table.toAsset(
        collection=fc,
        description="water_rf_dataset_asset",
        assetId=config.OUTPUT_ASSET_ID,
    )
    task.start()
    print(f"\nExport task started -> {config.OUTPUT_ASSET_ID}")
    print("Polling for completion (this runs entirely on GEE)…")

    while task.active():
        time.sleep(20)
        print("  …still running")
    state = task.status().get("state")
    if state == "COMPLETED":
        print(f"\nDone. Asset written to {config.OUTPUT_ASSET_ID}")
    else:
        print(f"\nExport ended in state {state}: {task.status()}")


def main():
    init_ee()
    print("Building merged, engineered dataset (server-side)…")
    merged = build_merged()
    final = clean_for_export(merged)
    export_asset(final)


if __name__ == "__main__":
    main()
