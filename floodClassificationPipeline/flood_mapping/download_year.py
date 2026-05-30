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
                image=fullyear_stack.toByte(),
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
            image=fullyear_stack.toByte(),
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
