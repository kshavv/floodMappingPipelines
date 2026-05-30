"""Assemble the 27-band classification image for one target year.

For each of the 27 full-year bi-weeks on the Kharif-aligned grid:
  * Kharif slots → full 5-class classification (perennial / land /
    seasonal / regular flood / anomalous), with optional temporal
    corrections, exactly like ``ee_app.js``.
  * Rabi & Zaid slots → 2-class water(1) / non-water(2).

All 27 resulting single-band images are stacked into one multi-band
``ee.Image`` (BW_1..BW_27). A polygon ROI mask is applied to every band
so the exported asset is state-shaped, not rectangular.
"""
from __future__ import annotations

from typing import List, Optional

import ee

from .classify_config import (
    N_BIWEEKS_FULL, KHARIF_SLOTS, ZAID_SLOTS, RABI_SLOTS,
    season_for_slot, DEFAULT_THRESHOLDS,
)
from .classify_core import (
    perennial_frequency, biweek_frequency_for_slot, kharif_seasonal_frequency,
    classify_flood_map, classify_two_class, apply_corrections,
)


def _kharif_substack(full_year_stack: ee.Image) -> ee.Image:
    """Slice the Kharif slots and rename them BW_1..BW_n so
    apply_corrections sees a clean 1-based Kharif stack."""
    src = [f'BW_{s + 1}' for s in KHARIF_SLOTS]
    dst = [f'BW_{i + 1}' for i in range(len(KHARIF_SLOTS))]
    return full_year_stack.select(src).rename(dst)


def build_classification_image(
    target_full_year_stack: ee.Image,
    historical_full_year_stacks: List[ee.Image],
    roi: ee.Geometry,
    *,
    thresholds: Optional[dict] = None,
    apply_temporal_corrections: bool = True,
    apply_geometry_mask: bool = True,
) -> ee.Image:
    """Return a single 27-band classification ``ee.Image``.

    Parameters
    ----------
    target_full_year_stack
        The ``RF_water_FullYear_<year>_<title>`` asset (27 bands).
    historical_full_year_stacks
        Full-year stacks (27 bands each) for the historical years used
        to compute cross-year bi-week frequency for Kharif.
    roi
        Region of interest. Used both for the historical bi-week clip
        and (when ``apply_geometry_mask=True``) as the validity mask of
        the output image.
    thresholds
        Override the default 5-class thresholds.
    apply_temporal_corrections
        Apply Kharif temporal-pattern corrections (default True).
    apply_geometry_mask
        Mask every output band by ``roi`` so the exported asset has the
        state's polygon outline, not the bounding-box rectangle
        (default True).
    """
    thr = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        thr.update(thresholds)

    # --- Frequencies needed for the Kharif 5-class step ---------------
    perennial = perennial_frequency(target_full_year_stack)
    kharif_seasonal = kharif_seasonal_frequency(target_full_year_stack)
    kharif_stack = _kharif_substack(target_full_year_stack)

    out_bands: List[ee.Image] = []
    out_names: List[str] = []

    for slot in range(N_BIWEEKS_FULL):
        band_in = f'BW_{slot + 1}'
        band_out = f'BW_{slot + 1}'
        target_water = (target_full_year_stack.select([band_in])
                        .rename('water'))
        season = season_for_slot(slot)

        if season == 'kharif':
            biweek_freq = biweek_frequency_for_slot(
                historical_full_year_stacks, slot, roi)
            cls = classify_flood_map(
                target_water, perennial, biweek_freq, kharif_seasonal, thr)
            if apply_temporal_corrections:
                kharif_idx = KHARIF_SLOTS.index(slot)        # 0-based
                kharif_band = f'BW_{kharif_idx + 1}'
                cls = apply_corrections(
                    cls, kharif_stack, kharif_band, kharif_idx,
                    n_biweeks=len(KHARIF_SLOTS))
        else:
            cls = classify_two_class(target_water)

        out_bands.append(cls.rename(band_out).toByte())
        out_names.append(band_out)

    classified = (ee.ImageCollection(out_bands).toBands()
                  .rename(out_names))

    # --- Polygon ROI mask --------------------------------------------
    # The download pipeline writes assets clipped to the polygon ROI but
    # the asset's storage extent is still rectangular. Apply the polygon
    # mask explicitly here so the EXPORTED classification image is
    # state-shaped on every band (Kharif and Rabi/Zaid alike), instead
    # of having Rabi/Zaid bands fill the bounding-box rectangle with 2s.
    if apply_geometry_mask:
        geom_mask = ee.Image.constant(1).clip(roi).mask()
        classified = classified.updateMask(geom_mask)

    # --- Metadata -----------------------------------------------------
    classified = classified.set({
        'year': target_full_year_stack.get('year'),
        'admin_state': target_full_year_stack.get('admin_state'),
        'district_numbering': target_full_year_stack.get('district_numbering'),
        'grid_anchor': target_full_year_stack.get('grid_anchor'),
        'kharif_bands': ','.join(f'BW_{s + 1}' for s in KHARIF_SLOTS),
        'zaid_bands':   ','.join(f'BW_{s + 1}' for s in ZAID_SLOTS),
        'rabi_bands':   ','.join(f'BW_{s + 1}' for s in RABI_SLOTS),
        'classification_scheme':
            'kharif=5class(1..5); rabi,zaid=2class(water=1,nonwater=2)',
    })
    return classified
