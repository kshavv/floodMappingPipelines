"""Top-level pipeline: download the full-year temporal image for a given
administrative region and year.

[PATH2] Each year produces a SINGLE full-year stack on the Kharif-aligned
27-bi-week grid.  The Kharif (and, later, Rabi / Zaid) sub-stacks are sliced
out of this full-year stack by the EE app at classify time, so no separate
season assets are exported — for the target year or for historical years.

Two call shapes:

  # Whole state
  download_temporal_images_for_year(
      state='Kerala', year=2024,
      training_fc='projects/.../full_dataset_v3',
      asset_root='projects/.../TemporalImages',
      destinations='asset')

  # Subset of districts
  download_temporal_images_for_year(
      state='Kerala', districts=['Ernakulam', 'Kollam', 'Thrissur'],
      year=2024,
      training_fc='projects/.../full_dataset_v3',
      asset_root='projects/.../TemporalImages',
      destinations=['asset', 'drive'],
      drive_folder='flood_temporal_images')

  # Many years (historical + target), full-year stacks for all
  download_temporal_images_for_years(
      state='Assam', years=[2019, 2020, 2021, 2022, 2023, 2024],
      training_fc='projects/.../full_dataset_v3',
      asset_root='projects/.../TemporalImages',
      destinations='asset')
"""
from __future__ import annotations
from typing import Iterable, List, Optional, Union

import ee

from .config import (
    DEFAULT_S1_WINDOW, DEFAULT_S2_WINDOW,
    SCALE, NATIVE_CRS, MAX_PIXELS,
)
from .classifiers import train_classifiers
from .stacks import build_full_year_stack
from .admin import AdminRoi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_destinations(destinations) -> List[str]:
    """Normalise to a de-duplicated list of {'asset','drive'}."""
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


def _resolve_training_fc(training_fc) -> ee.FeatureCollection:
    if isinstance(training_fc, ee.FeatureCollection):
        return training_fc
    if isinstance(training_fc, str):
        return ee.FeatureCollection(training_fc)
    raise TypeError(
        f'training_fc must be ee.FeatureCollection or asset id string; '
        f'got {type(training_fc).__name__}')


def _asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Rabi / Zaid Temporal Smoothing Helpers
# ---------------------------------------------------------------------------

def _window_correction(bands: list, anchor_prev: ee.Image, anchor_next: ee.Image = None, anchor_zero_mask: ee.Image = None) -> list:
    corrected = []
    n = len(bands)
    for i in range(n):
        prev = anchor_prev if i == 0 else corrected[i - 1]
        cur = bands[i]
        
        if i < n - 1:
            nxt = bands[i + 1]
        else:
            nxt = anchor_next

        if nxt is None:
            out = cur.where(prev.eq(0), 0)
        else:
            out = cur
            # Rule 1 — heal isolated dry gap
            heal = prev.eq(1).And(cur.eq(0)).And(nxt.eq(1))
            out = out.where(heal, 1)
            # Rule 3 — once dry, stay dry
            out = out.where(prev.eq(0), 0)

        if anchor_zero_mask is not None:
            out = out.where(anchor_zero_mask, 0)
            
        corrected.append(out)
    return corrected


def _min_flips_correction(observed_bands: list, names: list) -> tuple:
    n = len(observed_bands)
    observed = ee.Image.cat(observed_bands).rename(names)
    best_cutoff = ee.Image.constant(0)
    best_dist = ee.Image.constant(n + 1)

    for k in range(n + 1):
        pattern = ee.Image.cat([
            ee.Image.constant(1 if j < k else 0) for j in range(n)
        ]).rename(names)
        dist = observed.neq(pattern).reduce(ee.Reducer.sum())
        is_better = dist.lt(best_dist)
        
        best_cutoff = best_cutoff.where(is_better, k)
        best_dist = best_dist.where(is_better, dist)

    result = [best_cutoff.gt(i).rename(names[i]) for i in range(n)]
    return result, best_cutoff


def _hybrid_correction(bands: list, names: list, anchor_prev: ee.Image, anchor_next: ee.Image = None, anchor_zero_mask: ee.Image = None) -> ee.Image:
    observed = ee.Image.cat(bands).rename(names)

    win_list = _window_correction(bands, anchor_prev, anchor_next, anchor_zero_mask)
    win_image = ee.Image.cat(win_list).rename(names)

    mf_list, _ = _min_flips_correction(bands, names)
    mf_image = ee.Image.cat(mf_list).rename(names)

    win_flips = observed.neq(win_image).reduce(ee.Reducer.sum())
    mf_flips = observed.neq(mf_image).reduce(ee.Reducer.sum())
    use_mf = mf_flips.lt(win_flips)

    final_bands = [
        win_image.select(name).where(use_mf, mf_image.select(name))
        for name in names
    ]
    return ee.Image.cat(final_bands).rename(names)


def _apply_rabi_zaid_smoothing(image: ee.Image, year: int, title: str, asset_root: Optional[str]) -> ee.Image:
    """Apply hybrid temporal smoothing to BOY (Rabi+Zaid) and EOY (Rabi) bands."""
    # 27-band Kharif-aligned grid mapping: Kharif sits exactly at BW_12 to BW_21
    boy_names = [f'BW_{i}' for i in range(1, 12)]     # BW_1 to BW_11
    kharif_names = [f'BW_{i}' for i in range(12, 22)] # BW_12 to BW_21
    eoy_names = [f'BW_{i}' for i in range(22, 28)]    # BW_22 to BW_27

    boy_bands = [image.select(n) for n in boy_names]
    eoy_bands = [image.select(n) for n in eoy_names]

    if asset_root:
        root = asset_root.rstrip('/')
        prev_asset = f"{root}/RF_water_FullYear_{year-1}_{title}"
        next_asset = f"{root}/RF_water_FullYear_{year+1}_{title}"
    else:
        prev_asset = next_asset = ""

    # PREV anchor for BOY
    if _asset_exists(prev_asset):
        prev_year_bw27 = ee.Image(prev_asset).select('BW_27')
        print(f'  Smoothing: Using {year-1} BW_27 as BOY anchor')
    else:
        prev_year_bw27 = image.select('BW_1')
        print('  Smoothing: Previous year asset not found, using current BW_1 as BOY anchor')

    # NEXT anchor for EOY
    if _asset_exists(next_asset):
        next_year_bw1 = ee.Image(next_asset).select('BW_1')
        print(f'  Smoothing: Using {year+1} BW_1 as EOY anchor')
    else:
        next_year_bw1 = image.select('BW_27')
        print('  Smoothing: Next year asset not found, using current BW_27 as EOY anchor')

    # --- Process Block 1 (BOY) ---
    bw12_current = image.select('BW_12')
    corrected_boy = _hybrid_correction(boy_bands, boy_names, prev_year_bw27, bw12_current, None)

    # --- Process Block 2 (EOY) ---
    last_kharif = image.select('BW_21')
    kharif_zero = last_kharif.eq(0)
    corrected_eoy = _hybrid_correction(eoy_bands, eoy_names, last_kharif, next_year_bw1, kharif_zero)

    # Assemble Final Image
    kharif_unchanged = image.select(kharif_names)
    smoothed = corrected_boy.addBands(kharif_unchanged).addBands(corrected_eoy)

    # Retain the original no-data masks and metadata properties
    smoothed = smoothed.updateMask(image.mask()).toByte()
    return ee.Image(smoothed.copyProperties(image, image.propertyNames()))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def download_temporal_images_for_year(
    state:           str,
    year:            int,
    training_fc:     Union[ee.FeatureCollection, str],
    *,
    districts:       Optional[Iterable[str]] = None,
    destinations:    Union[str, Iterable[str]] = 'asset',
    asset_root:      Optional[str] = None,
    drive_folder:    Optional[str] = None,
    s1_window_days:  int = DEFAULT_S1_WINDOW,
    s2_window_days:  int = DEFAULT_S2_WINDOW,
    extra_properties: Optional[dict] = None,
    start_tasks:     bool = True,
    skip_existing:   bool = True,
) -> dict:
    """Build the year's temporal images and queue export tasks.

    Output (regardless of destination):

      * ``RF_water_FullYear_<year>_<title>``  — 27-band full year on the
        Kharif-aligned grid (anchor ≈ late Dec of the prior year).

    Each band is a uint8 water mask (0 = land, 1 = water, masked = no
    data) with bi-week date ranges attached as image properties
    ``BW_<N>_startDate`` / ``BW_<N>_endDate``, plus ``grid_anchor``.

    The asset/Drive **filenames are byte-identical to what ee_app.js
    produces** so outputs from this Python pipeline are immediately
    reusable by the EE app's "Use existing temporal images" mode.

    Parameters
    ----------
    state
        Indian state name as in FAO GAUL level1 (e.g. ``"Kerala"``,
        ``"Tamil Nadu"``).  Required.
    year
        Target year (e.g. ``2024``).
    training_fc
        Per-pixel training FeatureCollection or asset id string.
        Must include numeric properties for all 12 fused features plus
        the integer ``waterType`` label and a ``Name`` property used
        for the polygon-level train/test split.
    districts
        Optional list of district names within the state.

        * ``None`` (or empty) → ROI is the whole state.
            Title: ``'<state_slug>'``  e.g. ``'kerala'``.
        * Non-empty list → ROI is the union of those districts.
            Title: ``'<state_slug>_<i1,i2,…>'`` using 1-based indices
            into the alphabetised state district list, sorted ascending.
            E.g. ``['Ernakulam','Kollam','Thrissur']`` in Kerala →
            ``'kerala_3,7,12'``.

        District names are matched case-insensitively against FAO
        GAUL level2.  Unknown names raise a ``ValueError`` listing
        near matches.
    destinations
        Where to send the outputs.  Pass any of:

        * ``'asset'``                 — Earth Engine assets only
        * ``'drive'``                 — Google Drive (GeoTIFF) only
        * ``['asset', 'drive']``      — both

        Default: ``'asset'``.

    asset_root
        Required when ``'asset'`` is in ``destinations``.  Root asset
        path under which both outputs are written.
    drive_folder
        Required when ``'drive'`` is in ``destinations``.  Drive
        folder name (just the folder, not a full path).  Earth Engine
        creates it if it doesn't exist.
    s1_window_days, s2_window_days
        ± half-width (days) of the search window when picking the
        nearest scene for each bi-week midpoint.  Default 6.  Widen
        for ROIs with S1 revisit gaps (e.g. 2022+ where only S1A is
        operational).
    extra_properties
        Optional dict of extra image properties.  Attached on top of
        the auto-derived admin legend (``admin_state``,
        ``district_numbering``).
    start_tasks
        If True (default), call ``.start()`` on each task immediately.
        Set False to inspect / modify task objects first.
    skip_existing
        Asset destination only: ``ee.data.getAsset()`` is called
        before queueing and existing matches are skipped.  Drive
        exports always run (Earth Engine doesn't expose Drive
        listing).  Pass False to force re-export.

    Returns
    -------
    dict with keys (some may be ``None`` depending on destinations):

        ``admin``                    : ``AdminRoi`` — resolved region
        ``title``                    : str — derived title
        ``fullyear_asset_id``        : str or None
        ``fullyear_asset_task``      : ee.batch.Task or None
        ``fullyear_drive_task``      : ee.batch.Task or None
        ``fullyear_drive_filename``  : str or None
        ``skipped``                  : list[str] — asset ids skipped
    """
    dests = _resolve_destinations(destinations)
    if 'asset' in dests and not asset_root:
        raise ValueError(
            '`asset_root` is required when "asset" is in destinations.')
    if 'drive' in dests and not drive_folder:
        raise ValueError(
            '`drive_folder` is required when "drive" is in destinations.')

    # ── Resolve admin region (geometry + derived title) ──────
    districts_list = list(districts) if districts else []
    admin: AdminRoi = (
        AdminRoi.from_districts(state, districts_list)
        if districts_list
        else AdminRoi.from_state(state)
    )
    print(f'Resolved admin region: {admin}')

    # ── Train classifiers ────────────────────────────────────
    training = _resolve_training_fc(training_fc)
    rfs = train_classifiers(training)

    title = admin.title

    # ── Build the full-year stack ────────────────────────────
    # [PATH2] Only the full-year stack is produced. The Kharif window is a
    # slice of this stack (the grid is Kharif-phase-aligned), handled by the
    # EE app at classify time.
    fullyear_stack = build_full_year_stack(
        year, admin.geometry, rfs, s1_window_days, s2_window_days)

    # Attach admin metadata + caller-supplied extras.
    base_props = {'admin_state': admin.state_name}
    if admin.district_numbering:
        base_props['district_numbering'] = admin.district_numbering
    if extra_properties:
        base_props.update(extra_properties)
    fullyear_stack = fullyear_stack.set(base_props)

    # --- APPLY RABI/ZAID TEMPORAL SMOOTHING ---
    fullyear_stack = _apply_rabi_zaid_smoothing(fullyear_stack, year, title, asset_root)

    fullyear_name = f'RF_water_FullYear_{year}_{title}'

    out: dict = {
        'admin':                   admin,
        'title':                   title,
        'fullyear_asset_id':       None,
        'fullyear_asset_task':     None,
        'fullyear_drive_task':     None,
        'fullyear_drive_filename': None,
        'skipped':                 [],
    }

    # ── Asset destination ────────────────────────────────────
    if 'asset' in dests:
        root = asset_root.rstrip('/')
        fullyear_id = f'{root}/{fullyear_name}'
        out['fullyear_asset_id'] = fullyear_id

        if skip_existing and _asset_exists(fullyear_id):
            out['skipped'].append(fullyear_id)
            print(f'  ♻ Full-year asset already exists, skipping: {fullyear_id}')
        else:
            t = ee.batch.Export.image.toAsset(
                image=fullyear_stack,
                description=fullyear_name,
                assetId=fullyear_id,
                region=admin.geometry,
                scale=SCALE, crs=NATIVE_CRS, maxPixels=MAX_PIXELS,
            )
            if start_tasks:
                t.start()
            out['fullyear_asset_task'] = t
            print(f'  ✓ Queued Full-year → asset: {fullyear_id}')

    # ── Drive destination ────────────────────────────────────
    if 'drive' in dests:
        out['fullyear_drive_filename'] = fullyear_name

        t = ee.batch.Export.image.toDrive(
            image=fullyear_stack,
            description=fullyear_name,
            folder=drive_folder,
            fileNamePrefix=fullyear_name,
            region=admin.geometry,
            scale=SCALE, crs=NATIVE_CRS, maxPixels=MAX_PIXELS,
            fileFormat='GeoTIFF',
        )
        if start_tasks:
            t.start()
        out['fullyear_drive_task'] = t
        print(f'  ✓ Queued Full-year → Drive: {drive_folder}/{fullyear_name}.tif')

    return out


# ---------------------------------------------------------------------------
# Multi-year convenience wrapper
# ---------------------------------------------------------------------------

def download_temporal_images_for_years(
    state:           str,
    years:           Iterable[int],
    training_fc:     Union[ee.FeatureCollection, str],
    **kwargs,
) -> List[dict]:
    """Download full-year stacks for several years (historical + target).

    Thin loop over :func:`download_temporal_images_for_year`.  Every year —
    historical or target — yields a single ``RF_water_FullYear_<year>_<title>``
    asset on the Kharif-aligned grid, matching the EE app which slices each
    season out of the full-year stack at classify time.

    ``skip_existing`` (default True) makes this idempotent: years whose
    full-year asset already exists are skipped.

    All keyword arguments accepted by
    :func:`download_temporal_images_for_year` are forwarded unchanged
    (``districts``, ``destinations``, ``asset_root``, ``drive_folder``,
    ``s1_window_days``, ``s2_window_days``, ``extra_properties``,
    ``start_tasks``, ``skip_existing``).

    Returns
    -------
    list[dict]
        One result dict per year, in the order given.
    """
    results = []
    for yr in years:
        print(f'━━ Year {yr} ━━')
        results.append(
            download_temporal_images_for_year(
                state=state, year=yr, training_fc=training_fc, **kwargs))
    return results