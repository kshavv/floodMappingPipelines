"""Bi-week grid + reduction strategies for the Kharif biweek endpoint.

Bi-week definition
------------------
Matches the GEE flood-classification pipeline's Kharif phase grid:

    BW_12 starts Jun 4
    BW_13 starts Jun 18
    ...
    BW_21 starts Sep 24
    BW_21 ends   Oct 7 (inclusive)

Each bi-week is exactly 14 days, and the 10 Kharif bi-weeks cover the
140-day window Jun 4 → Oct 7 (Oct 8 starts BW_22, which is Rabi).

Combiner functions
------------------
Two ways to reduce ~14 days of Bhuvan flood data into a single
band-per-bi-week:

* ``combine_union(masks)``   — logical OR. A pixel is flooded if
  ANY day in the bi-week had cyan at that pixel.
* ``combine_mid_snapshot(masks_by_date, biweek_start)`` — pick the
  single data-day nearest the midpoint of the bi-week (Day 7);
  ties broken to the earlier date.

Both return a ``uint8`` array of the same shape as the input. Outside
pixels (255) are preserved through both combiners.
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np


# --- Bi-week grid constants -----------------------------------------------
# Matches the classification pipeline: BW_12 starts Jun 4, 14-day stride.
KHARIF_BW_NUMBERS = list(range(12, 22))           # [12, 13, ..., 21]
KHARIF_N_BIWEEKS = len(KHARIF_BW_NUMBERS)         # 10
KHARIF_BW_LENGTH_DAYS = 14
KHARIF_BW12_START_MONTH = 6
KHARIF_BW12_START_DAY = 4


def kharif_biweek_starts(year: int) -> List[_dt.date]:
    """Start date of each of the 10 Kharif bi-weeks for ``year``.

    Returns 10 ``datetime.date`` values: BW_12 first (Jun 4), then each
    subsequent bi-week 14 days later.
    """
    bw12_start = _dt.date(year, KHARIF_BW12_START_MONTH,
                          KHARIF_BW12_START_DAY)
    return [bw12_start + _dt.timedelta(days=14 * i)
            for i in range(KHARIF_N_BIWEEKS)]


def kharif_biweek_dates(year: int) -> List[List[_dt.date]]:
    """14 daily dates inside each Kharif bi-week.

    Returns 10 lists of 14 dates each, in bi-week order (BW_12 first).
    """
    return [[start + _dt.timedelta(days=d)
             for d in range(KHARIF_BW_LENGTH_DAYS)]
            for start in kharif_biweek_starts(year)]


def biweek_label(year: int, bw_index_0based: int) -> str:
    """Pretty label like 'BW_12 (2025-06-04 → 2025-06-17)'."""
    bw_num = KHARIF_BW_NUMBERS[bw_index_0based]
    starts = kharif_biweek_starts(year)
    start = starts[bw_index_0based]
    end = start + _dt.timedelta(days=KHARIF_BW_LENGTH_DAYS - 1)
    return f'BW_{bw_num} ({start.isoformat()} → {end.isoformat()})'


# --- Combiners ------------------------------------------------------------
#
# Both combiners assume the masks are uint8 with the convention
# 0=land/no-flood, 1=flood, 255=nodata (outside polygon).
#
# 'nodata' propagation rule: a pixel is nodata in the output only if it
# was nodata in EVERY input mask. Otherwise the combiner ignores nodata
# pixels and reduces only the 0/1 values.
# ---------------------------------------------------------------------------

NODATA_VALUE = 255


def combine_union(masks: List[np.ndarray]) -> np.ndarray:
    """Logical OR across all input masks.

    Output pixel is 1 if ANY input had 1 at that pixel; 0 if all valid
    inputs had 0; 255 (nodata) only if every input was 255 at that
    pixel (i.e. the pixel is outside the polygon in every mask, which
    they all share so it's just outside the polygon).
    """
    if not masks:
        raise ValueError('combine_union needs at least one mask')
    stack = np.stack(masks, axis=0)              # (N, H, W) uint8
    valid = (stack != NODATA_VALUE)
    flood = (stack == 1) & valid                 # (N, H, W) bool
    any_flood = flood.any(axis=0)
    any_valid = valid.any(axis=0)
    out = np.full(stack.shape[1:], NODATA_VALUE, dtype=np.uint8)
    out[any_valid & any_flood] = 1
    out[any_valid & ~any_flood] = 0
    return out


def combine_mid_snapshot(masks_by_date: Dict[_dt.date, np.ndarray],
                         biweek_start: _dt.date,
                         empty_template: np.ndarray
                         ) -> Tuple[np.ndarray, Optional[_dt.date]]:
    """Pick the single data-day nearest the bi-week midpoint.

    ``masks_by_date`` maps each data-day's date to its mask (only days
    Bhuvan actually had data for should be present here — empty days
    must be omitted).

    The bi-week midpoint is Day 7 (start + 7 days). Days inside the
    bi-week are scored by ``|day - midpoint|``, lowest score wins.
    Ties go to the earlier date.

    If ``masks_by_date`` is empty (no data days in this bi-week),
    returns ``(empty_template, None)`` so the caller can write a
    no-data band.

    Returns ``(chosen_mask, chosen_date)`` so the caller can record
    which exact day was picked.
    """
    biweek_end = biweek_start + _dt.timedelta(days=KHARIF_BW_LENGTH_DAYS)
    in_bw = {d: m for d, m in masks_by_date.items()
             if biweek_start <= d < biweek_end}
    if not in_bw:
        return empty_template, None
    midpoint = biweek_start + _dt.timedelta(days=7)
    chosen = min(in_bw.keys(),
                 key=lambda d: (abs((d - midpoint).days), d))
    return in_bw[chosen], chosen


# --- Registry of combiner strategies --------------------------------------
# Lets the orchestrator switch reduction strategy by name. Add new
# combiners here and they're immediately selectable from the public
# endpoint.

CombinerFn = Callable[..., np.ndarray]


def _wrap_union(masks_by_date, biweek_start, empty_template):
    """Adapter so combine_union has the same signature as mid_snapshot."""
    biweek_end = biweek_start + _dt.timedelta(days=KHARIF_BW_LENGTH_DAYS)
    in_bw = [m for d, m in masks_by_date.items()
             if biweek_start <= d < biweek_end]
    if not in_bw:
        return empty_template, None
    return combine_union(in_bw), None             # 2nd value unused for union


COMBINERS: Dict[str, CombinerFn] = {
    'union':         _wrap_union,
    'mid_snapshot':  combine_mid_snapshot,
}
