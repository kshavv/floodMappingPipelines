"""Build the temporal water-mask stacks for a given year.

Each output is a multi-band `ee.Image` where each band is a
`BW_<N>` byte mask. Date metadata for each bi-week is attached as
image properties (`BW_<N>_startDate`, `BW_<N>_endDate`) so downstream
loaders can reconstruct which date range each band covers without
re-running the pipeline.

[PATH2] The full-year grid is anchored on the SAME 14-day phase as the
Kharif season (it starts in late December of the prior year, not Jan 1),
so the Kharif window — and, later, Rabi / Zaid — can be sliced out of a
single full-year stack with no date drift. This mirrors the EE app, which
no longer stores separate season stacks. `build_kharif_stack` is retained
for reference / ad-hoc use but is not part of the download path anymore.
"""
from __future__ import annotations

import datetime

import ee

from .config import (
    MONSOON_START, N_BIWEEKS, N_BIWEEKS_FULL,
    BIWEEK_DAYS, HALF_BIWEEK_DAYS,
)
from .classifiers import rf_water_for_biweek


def full_year_anchor(year: int) -> datetime.date:
    """Phase-aligned start date (<= Jan 1) for `year`'s full-year grid.

    Steps backwards from ``MONSOON_START``/1 in 14-day increments until on
    or before Jan 1, so the resulting grid's bi-week boundaries coincide
    with the Kharif boundaries.  Identical logic to ``fullYearAnchor`` in
    the EE app; returns a plain ``datetime.date`` (client-side).
    """
    d = datetime.date(year, MONSOON_START, 1)
    jan1 = datetime.date(year, 1, 1)
    step = datetime.timedelta(days=BIWEEK_DAYS)
    while d > jan1:
        d -= step
    return d


def season_start_slot(year: int,
                       season_start_month: int,
                       season_start_day: int) -> int:
    """0-based slot in the full-year stack where a season starts.

    For Kharif (``MONSOON_START``/1) this is the slot whose start == June 1.
    Used by loaders/classifiers to slice a season out of the full-year
    stack; kept here so the grid math lives in one place.
    """
    anchor = full_year_anchor(year)
    season_start = datetime.date(year, season_start_month, season_start_day)
    return round((season_start - anchor).days / BIWEEK_DAYS)


def _build_stack(start_date: ee.Date,
                 n_biweeks: int,
                 roi: ee.Geometry,
                 rfs: dict,
                 s1_window_days: int,
                 s2_window_days: int) -> ee.Image:
    band_imgs = []
    band_names = []
    meta = {}
    for b in range(n_biweeks):
        bw_start = start_date.advance(b * BIWEEK_DAYS,                'day')
        bw_end   = start_date.advance(b * BIWEEK_DAYS + (BIWEEK_DAYS - 1), 'day')
        bw_mid   = bw_start.advance(HALF_BIWEEK_DAYS,                 'day')
        name     = f'BW_{b + 1}'

        meta[f'{name}_startDate'] = bw_start.format('dd-MM-yyyy')
        meta[f'{name}_endDate']   = bw_end.format('dd-MM-yyyy')

        band_imgs.append(
            rf_water_for_biweek(bw_mid, roi, rfs,
                                s1_window_days=s1_window_days,
                                s2_window_days=s2_window_days)
            .rename(name).toByte())
        band_names.append(name)

    return (ee.ImageCollection(band_imgs).toBands()
            .rename(band_names).set(meta))


def build_kharif_stack(year: int,
                       roi: ee.Geometry,
                       rfs: dict,
                       s1_window_days: int,
                       s2_window_days: int) -> ee.Image:
    """10-band Kharif stack starting June 1 of `year`.

    Retained for reference / ad-hoc use.  The download pipeline no longer
    exports this — the Kharif window is sliced from the full-year stack by
    the EE app at classify time.
    """
    start = ee.Date.fromYMD(year, MONSOON_START, 1)
    return _build_stack(start, N_BIWEEKS, roi, rfs,
                        s1_window_days, s2_window_days).set('year', year)


def build_full_year_stack(year: int,
                          roi: ee.Geometry,
                          rfs: dict,
                          s1_window_days: int,
                          s2_window_days: int) -> ee.Image:
    """27-band full-year stack on the Kharif-aligned grid for `year`.

    [PATH2] The grid is anchored on the Kharif 14-day phase (≈ late Dec of
    the prior year), so slicing slots 11–20 reproduces the Kharif windows
    exactly.  ``grid_anchor`` is stored as a property for traceability.
    """
    anchor = full_year_anchor(year)
    start = ee.Date.fromYMD(anchor.year, anchor.month, anchor.day)
    return (_build_stack(start, N_BIWEEKS_FULL, roi, rfs,
                         s1_window_days, s2_window_days)
            .set('year', year)
            .set('grid_anchor', anchor.strftime('%d-%m-%Y')))
