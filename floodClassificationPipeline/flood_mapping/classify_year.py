"""Top-level entry point for the classification pipeline.

Resolves the polygon ROI via :class:`AdminRoi` (same logic the download
pipeline uses, so titles line up byte-for-byte), loads the exported
full-year assets (target year + historical years), builds a single
27-band classification image, and queues an export.

Usage
-----
    import ee
    ee.Initialize(project='gentle-operator-308420')

    from flood_mapping import classify_year

    result = classify_year(
        state='Kerala',                 # GAUL level-1 name; resolves polygon ROI
        year=2024,
        asset_root='projects/gentle-operator-308420/assets/TemporalImages',
        destinations='asset',
        output_root='projects/gentle-operator-308420/assets/Classified',
    )
    print(result['output_asset_id'])

District subset:
    classify_year(state='Kerala', districts=['Ernakulam','Kollam','Thrissur'],
                  year=2024, ...)
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Union

import ee

from .classify_config import (
    HISTORICAL_YEARS, SCALE, NATIVE_CRS, MAX_PIXELS,
    fullyear_asset_id,
)
from .classify_build import build_classification_image
from .admin import AdminRoi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_destinations(destinations) -> List[str]:
    if isinstance(destinations, str):
        destinations = [destinations]
    out = [d.strip().lower() for d in destinations if d and d.strip()]
    invalid = [d for d in out if d not in ('asset', 'drive')]
    if invalid:
        raise ValueError(
            f'Invalid destination(s): {invalid}. '
            f'Must be one or more of: "asset", "drive".')
    if not out:
        raise ValueError(
            'At least one destination is required (asset, drive, or both).')
    return list(dict.fromkeys(out))


def _asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_year(
    state: Optional[str] = None,
    year: Optional[int] = None,
    asset_root: Optional[str] = None,
    *,
    districts: Optional[Iterable[str]] = None,
    title: Optional[str] = None,
    roi: Optional[ee.Geometry] = None,
    historical_years: Optional[Iterable[int]] = None,
    destinations: Union[str, Iterable[str]] = 'asset',
    output_root: Optional[str] = None,
    drive_folder: Optional[str] = None,
    output_name: Optional[str] = None,
    thresholds: Optional[dict] = None,
    apply_temporal_corrections: bool = True,
    apply_geometry_mask: bool = True,
    start_tasks: bool = True,
    skip_existing: bool = True,
) -> dict:
    """Classify the full-year asset for ``year`` / ``state`` (optionally
    ``districts``) into a single 27-band classification image and queue
    the export.

    Two call shapes are supported:

    1. **Admin-driven (recommended):**
       Pass ``state`` (and optional ``districts``). The polygon ROI and
       the asset title are derived via :class:`AdminRoi` — same logic
       as the download pipeline, so titles match byte-for-byte. The
       polygon is also used as the output mask so the exported asset is
       state-shaped instead of a bounding-box rectangle.

    2. **Explicit:**
       Pass ``title`` and ``roi`` directly (advanced; you must ensure
       ``title`` matches the full-year asset's title, and ``roi`` is the
       polygon you want as the output mask).

    Parameters
    ----------
    state
        Indian state name as in FAO GAUL level-1 (e.g. ``"Kerala"``).
    year
        Target year to classify.
    asset_root
        Root path where the input ``RF_water_FullYear_*`` assets live.
    districts
        Optional list of district names within the state. Same rules as
        ``download_temporal_images_for_year``.
    title
        Override the auto-derived title. Required if ``state`` is not
        given.
    roi
        Override the polygon ROI used for cross-year bi-week clipping
        and the output mask. If omitted, derived from
        ``AdminRoi.from_state(state, districts)``.
    historical_years
        Years whose full-year assets supply the cross-year Kharif
        bi-week frequency. Defaults to ``HISTORICAL_YEARS``. Missing
        ones are dropped (warning); the target year is always included.
    destinations
        ``'asset'``, ``'drive'``, or both.
    output_root
        Required for ``'asset'``.
    drive_folder
        Required for ``'drive'``.
    output_name
        Override the output base name. Defaults to
        ``Classified_<year>_<title>``.
    thresholds
        Override the 5-class thresholds.
    apply_temporal_corrections
        Apply Kharif temporal-pattern corrections (default True).
    apply_geometry_mask
        Mask the output by the polygon ROI (default True). Set False
        only if you specifically want a rectangle.
    start_tasks
        Call ``.start()`` on each task immediately (default True).
    skip_existing
        Skip the asset export if the output asset already exists.
    """
    dests = _resolve_destinations(destinations)
    if 'asset' in dests and not output_root:
        raise ValueError(
            '`output_root` is required when "asset" is in destinations.')
    if 'drive' in dests and not drive_folder:
        raise ValueError(
            '`drive_folder` is required when "drive" is in destinations.')
    if year is None:
        raise ValueError('`year` is required.')
    if asset_root is None:
        raise ValueError('`asset_root` is required.')

    # ── Resolve title + ROI ──────────────────────────────────
    if state is not None:
        districts_list = list(districts) if districts else []
        admin: AdminRoi = (
            AdminRoi.from_districts(state, districts_list)
            if districts_list
            else AdminRoi.from_state(state)
        )
        resolved_title = title or admin.title
        resolved_roi = roi or admin.geometry
        print(f'Resolved admin region: {admin}')
    else:
        if not title:
            raise ValueError(
                'Pass either `state` (recommended) or both `title` and '
                '`roi`.')
        if roi is None:
            print('  ⚠ No `roi` given — using target asset footprint as '
                  'ROI. The geometry mask will be the asset bounding '
                  'box, not the state polygon. Pass `state=...` or an '
                  'explicit `roi=...` for a polygon-shaped output.')
        resolved_title = title
        resolved_roi = roi

    hist_years = (list(historical_years)
                  if historical_years is not None
                  else list(HISTORICAL_YEARS))

    # ── Resolve + verify input assets ────────────────────────
    target_id = fullyear_asset_id(asset_root, year, resolved_title)
    if not _asset_exists(target_id):
        raise FileNotFoundError(
            f'Target full-year asset not found: {target_id}\n'
            f'Run the download pipeline for year={year}, '
            f'title="{resolved_title}" first.')
    target_stack = ee.Image(target_id)

    if resolved_roi is None:
        resolved_roi = target_stack.geometry()

    historical_stacks: List[ee.Image] = []
    used_hist: List[int] = []
    missing_hist: List[int] = []
    for hy in hist_years:
        hid = fullyear_asset_id(asset_root, hy, resolved_title)
        if _asset_exists(hid):
            historical_stacks.append(ee.Image(hid))
            used_hist.append(hy)
        else:
            missing_hist.append(hy)

    if year not in used_hist:
        historical_stacks.append(target_stack)
        used_hist.append(year)

    if missing_hist:
        print(f'  ⚠ Missing historical full-year asset(s) for years '
              f'{missing_hist} (title="{resolved_title}") — dropped from '
              f'bi-week frequency. Using {used_hist}.')
    if not historical_stacks:
        raise FileNotFoundError(
            'No historical full-year assets available for bi-week '
            'frequency. Need at least the target year.')

    # ── Build the 27-band classification image ───────────────
    classified = build_classification_image(
        target_stack, historical_stacks, resolved_roi,
        thresholds=thresholds,
        apply_temporal_corrections=apply_temporal_corrections,
        apply_geometry_mask=apply_geometry_mask,
    ).toByte()

    base_name = output_name or f'Classified_{year}_{resolved_title}'

    out: dict = {
        'state':              state,
        'title':              resolved_title,
        'year':               year,
        'classification':     classified,
        'target_asset_id':    target_id,
        'historical_years':   used_hist,
        'missing_historical': missing_hist,
        'output_asset_id':    None,
        'asset_task':         None,
        'drive_task':         None,
        'drive_filename':     None,
        'skipped':            [],
    }

    # ── Asset export ─────────────────────────────────────────
    if 'asset' in dests:
        out_id = f"{output_root.rstrip('/')}/{base_name}"
        out['output_asset_id'] = out_id
        if skip_existing and _asset_exists(out_id):
            out['skipped'].append(out_id)
            print(f'  ♻ Classification asset already exists, '
                  f'skipping: {out_id}')
        else:
            t = ee.batch.Export.image.toAsset(
                image=classified,
                description=base_name,
                assetId=out_id,
                region=resolved_roi, scale=SCALE, crs=NATIVE_CRS,
                maxPixels=MAX_PIXELS,
            )
            if start_tasks:
                t.start()
            out['asset_task'] = t
            print(f'  ✓ Queued classification → asset: {out_id}')

    # ── Drive export ─────────────────────────────────────────
    if 'drive' in dests:
        out['drive_filename'] = base_name
        t = ee.batch.Export.image.toDrive(
            image=classified,
            description=base_name,
            folder=drive_folder,
            fileNamePrefix=base_name,
            region=resolved_roi, scale=SCALE, crs=NATIVE_CRS,
            maxPixels=MAX_PIXELS,
            fileFormat='GeoTIFF',
        )
        if start_tasks:
            t.start()
        out['drive_task'] = t
        print(f'  ✓ Queued classification → Drive: '
              f'{drive_folder}/{base_name}.tif')

    return out


# ---------------------------------------------------------------------------
# Multi-year convenience wrapper (mirrors download_temporal_images_for_years)
# ---------------------------------------------------------------------------

def classify_years(
    state: str,
    years: Iterable[int],
    asset_root: str,
    **kwargs,
) -> List[dict]:
    """Classify several years into individual 27-band classification
    images. Thin loop over :func:`classify_year`.

    Idempotent when ``skip_existing=True`` (default).
    """
    results = []
    for yr in years:
        print(f'━━ Year {yr} ━━')
        results.append(classify_year(
            state=state, year=yr, asset_root=asset_root, **kwargs))
    return results
