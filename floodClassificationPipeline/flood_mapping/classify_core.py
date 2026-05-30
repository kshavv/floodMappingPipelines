"""Frequency layers, the 5-class Kharif classifier, the 2-class
Rabi/Zaid classifier, and the temporal-pattern corrections.

Server-side EE port of the corresponding functions in ``ee_app.js``
(``freqFromCollection``, ``classifyFloodMap``, ``applyCorrections``),
adapted to read the already-exported 27-band Kharif-aligned full-year
assets rather than rebuilding stacks from Sentinel imagery.

Mask handling
-------------
Outputs inherit the input band's validity mask wherever possible:
* The 5-class start image is ``target_image.multiply(0)`` (= 0 everywhere
  the source band is valid, masked elsewhere). The subsequent
  ``where(...)`` writes only overwrite valid pixels.
* The 2-class start image is ``target_image.multiply(0).add(CLS_LAND)``
  (= 2 everywhere the source band is valid, masked elsewhere).

build_classification_image additionally applies the polygon ROI as a
hard geometry mask, so every output band shares one consistent state-
shaped extent regardless of per-bi-week scene availability.
"""
from __future__ import annotations

from typing import List

import ee

from .classify_config import (
    N_BIWEEKS_FULL, KHARIF_SLOTS,
    CLS_PERENNIAL, CLS_LAND, CLS_SEASONAL, CLS_REGULAR, CLS_ANOMALOUS,
    GLOBAL_TRANSITION_THRESHOLD, LOCAL_TRANSITION_THRESHOLD,
    LOCAL_WINDOW_RADIUS, SCALE, NATIVE_CRS,
)


# ---------------------------------------------------------------------------
# Frequency helpers (port of freqFromCollection)
# ---------------------------------------------------------------------------

def freq_from_collection(coll: ee.ImageCollection, name: str) -> ee.Image:
    """Fraction-of-valid-observations-that-are-water, per pixel."""
    valid = (coll.map(lambda i: i.unmask(-1).gte(0))
             .reduce(ee.Reducer.sum()).rename('valid'))
    water = (coll.map(lambda i: i.unmask(0))
             .reduce(ee.Reducer.sum()).rename('water'))
    return (water.divide(valid.add(1e-10))
            .updateMask(valid.gt(0))
            .clamp(0, 1)
            .rename(name))


def _band_collection(stack: ee.Image, band_names: List[str]) -> ee.ImageCollection:
    imgs = [stack.select([b]).rename('water') for b in band_names]
    return ee.ImageCollection(imgs)


def perennial_frequency(full_year_stack: ee.Image) -> ee.Image:
    """Perennial frequency = water fraction across ALL 27 full-year bands
    of the target-year stack (season-agnostic)."""
    band_names = [f'BW_{i + 1}' for i in range(N_BIWEEKS_FULL)]
    return freq_from_collection(
        _band_collection(full_year_stack, band_names), 'perennialFreq')


def biweek_frequency_for_slot(historical_stacks: List[ee.Image],
                              slot_zero_based: int,
                              roi: ee.Geometry) -> ee.Image:
    """Cross-year frequency for one specific full-year slot.

    The Kharif-aligned grid is identical across years (Jun 1 always slot 11,
    etc.), so the same slot index is the same calendar window in every
    year. Pull band ``BW_<slot+1>`` from every historical full-year stack.
    """
    band = f'BW_{slot_zero_based + 1}'
    imgs = [
        s.select([band]).rename('water').toFloat().round().clamp(0, 1).clip(roi)
        for s in historical_stacks
    ]
    return freq_from_collection(ee.ImageCollection(imgs), 'biweekFreq')


def kharif_seasonal_frequency(full_year_stack: ee.Image) -> ee.Image:
    """Seasonal ('yearly') frequency over the Kharif bi-weeks of the
    target year (the Kharif slot range of the full-year stack)."""
    band_names = [f'BW_{s + 1}' for s in KHARIF_SLOTS]
    return freq_from_collection(
        _band_collection(full_year_stack, band_names), 'yearlyFreq')


# ---------------------------------------------------------------------------
# 5-class Kharif classifier (port of classifyFloodMap)
# ---------------------------------------------------------------------------

def classify_flood_map(target_image: ee.Image,
                       perennial: ee.Image,
                       biweek: ee.Image,
                       yearly: ee.Image,
                       thresholds: dict) -> ee.Image:
    """Five-class classification of a single bi-week.

    ``target_image`` is the bi-week water mask (1 = water, 0 = land).
    Returns a single-band 'classification' image with codes 1..5 inside
    the source band's validity mask; masked elsewhere.
    """
    zero = ee.Image.constant(0).rename('water')
    y_u = yearly.rename('water').unmask(zero)
    b_u = biweek.rename('water').unmask(zero)
    p_u = perennial.unmask(zero)

    is_w = target_image.eq(1)
    is_perennial = is_w.And(p_u.gt(thresholds['perennial']))
    is_land = target_image.eq(0).And(is_perennial.Not())

    # Start from target_image.multiply(0) so the result inherits its mask
    # (i.e. masked outside the source band's valid extent), not from a
    # global ee.Image.constant which has no mask.
    cls = (target_image.multiply(0).rename('classification')
           .where(is_land, CLS_LAND)
           .where(is_perennial, CLS_PERENNIAL))

    dyn = is_w.And(is_perennial.Not())
    seas = dyn.And(b_u.gte(thresholds['biweek']))
    anom = (dyn.And(b_u.lt(thresholds['biweekAn']))
            .And(y_u.lt(thresholds['yearlyAn'])))
    reg = dyn.And(seas.Not()).And(anom.Not())

    return (cls.where(seas, CLS_SEASONAL)
            .where(reg, CLS_REGULAR)
            .where(anom, CLS_ANOMALOUS)
            .rename('classification'))


# ---------------------------------------------------------------------------
# 2-class Rabi/Zaid classifier
# ---------------------------------------------------------------------------

def classify_two_class(target_image: ee.Image) -> ee.Image:
    """Two-class water / non-water for Rabi & Zaid bi-weeks.

    Built from ``target_image`` (not a global constant) so the result
    inherits the source band's validity mask; masked elsewhere.
    Encoded:  water -> 1 (perennial slot), non-water -> 2 (land slot).
    """
    is_w = target_image.eq(1)
    base = (target_image.multiply(0).add(CLS_LAND)
            .rename('classification'))
    return base.where(is_w, CLS_PERENNIAL).rename('classification')


# ---------------------------------------------------------------------------
# Temporal-pattern corrections (port of applyCorrections)
# ---------------------------------------------------------------------------

def apply_corrections(cls: ee.Image,
                      kharif_stack: ee.Image,
                      target_band_name: str,
                      target_idx_zero_based: int,
                      n_biweeks: int = len(KHARIF_SLOTS)) -> ee.Image:
    """Temporal-pattern corrections for a Kharif bi-week."""
    all_bands = [f'BW_{i + 1}' for i in range(n_biweeks)]
    idx = target_idx_zero_based
    pre = all_bands[:idx]
    post = all_bands[idx + 1:]

    pre_stack = kharif_stack.select(pre).unmask(0) if pre else None
    post_stack = kharif_stack.select(post).unmask(0) if post else None

    pre_all_n = (pre_stack.reduce(ee.Reducer.sum()).eq(0)
                 if pre_stack is not None else ee.Image.constant(1))
    post_all_n = (post_stack.reduce(ee.Reducer.sum()).eq(0)
                  if post_stack is not None else ee.Image.constant(1))

    target_is_w = kharif_stack.select(target_band_name).eq(1)

    r1 = pre_all_n.And(post_all_n).And(target_is_w).And(cls.gte(CLS_SEASONAL))
    cls = cls.where(r1, CLS_LAND)

    band_imgs = [
        kharif_stack.select([b]).rename('water').unmask(0)
        .reproject(crs=NATIVE_CRS, scale=SCALE)
        for b in all_bands
    ]

    global_t = [band_imgs[t].neq(band_imgs[t + 1])
                for t in range(len(band_imgs) - 1)]
    global_trans = (ee.ImageCollection(global_t).reduce(ee.Reducer.sum())
                    .reproject(crs=NATIVE_CRS, scale=SCALE))
    r_global = (global_trans.gte(GLOBAL_TRANSITION_THRESHOLD)
                .And(target_is_w).And(cls.gte(CLS_SEASONAL))
                .reproject(crs=NATIVE_CRS, scale=SCALE))
    cls = cls.where(r_global, CLS_LAND)

    lo = max(0, idx - LOCAL_WINDOW_RADIUS)
    hi = min(len(all_bands) - 1, idx + LOCAL_WINDOW_RADIUS)
    local_t = [band_imgs[u].neq(band_imgs[u + 1]) for u in range(lo, hi)]
    if local_t:
        local_trans = (ee.ImageCollection(local_t).reduce(ee.Reducer.sum())
                       .reproject(crs=NATIVE_CRS, scale=SCALE))
        r_local = (local_trans.gte(LOCAL_TRANSITION_THRESHOLD)
                   .And(target_is_w).And(cls.gte(CLS_SEASONAL))
                   .reproject(crs=NATIVE_CRS, scale=SCALE))
        cls = cls.where(r_local, CLS_LAND)

    return cls
