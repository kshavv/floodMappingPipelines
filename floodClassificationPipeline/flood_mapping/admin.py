"""Resolve (state, districts) into an ROI geometry + a deterministic title.

The title scheme is byte-identical to `ee_app.js` so assets produced
by this Python pipeline can be reused by the EE app's "Use existing
temporal images" mode without rename gymnastics:

  - Whole state                 → title = slugified state name
                                    e.g. 'kerala'
  - Subset of districts         → title = '<state>_<i1,i2,…>'
                                    where i_k are 1-based indices into
                                    the alphabetised district list,
                                    sorted ascending
                                    e.g. 'kerala_3,7,12'

The district indices are derived from the alphabetical order of
ADM2_NAME values within the chosen state in FAO/GAUL/2015/level2,
filtered to India.  Same order, same indices, every time.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

import ee


GAUL_LEVEL1 = 'FAO/GAUL/2015/level1'   # states
GAUL_LEVEL2 = 'FAO/GAUL/2015/level2'   # districts
INDIA = 'India'


def slugify(s: str) -> str:
    """Lowercase, ASCII-only word chars, '_' between, no leading/trailing."""
    s = (s or '').lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def _india_state_geom(state_name: str) -> ee.Geometry:
    fc = (ee.FeatureCollection(GAUL_LEVEL1)
          .filter(ee.Filter.And(
              ee.Filter.eq('ADM0_NAME', INDIA),
              ee.Filter.eq('ADM1_NAME', state_name))))
    # simplify(100) keeps the request payload small without affecting
    # 30 m raster output.
    return fc.geometry().simplify(100)


def _india_district_names(state_name: str) -> list[str]:
    """Alphabetised district names within the state."""
    fc = (ee.FeatureCollection(GAUL_LEVEL2)
          .filter(ee.Filter.And(
              ee.Filter.eq('ADM0_NAME', INDIA),
              ee.Filter.eq('ADM1_NAME', state_name))))
    # Pulls a Python list directly via getInfo (small payload).
    return sorted(fc.aggregate_array('ADM2_NAME').distinct().getInfo())


def _india_district_geom(state_name: str,
                         district_names: Iterable[str]) -> ee.Geometry:
    fc = (ee.FeatureCollection(GAUL_LEVEL2)
          .filter(ee.Filter.And(
              ee.Filter.eq('ADM0_NAME', INDIA),
              ee.Filter.eq('ADM1_NAME', state_name),
              ee.Filter.inList('ADM2_NAME', list(district_names)))))
    return fc.geometry().simplify(100)


def _districts_to_indices(state_name: str,
                          districts: Iterable[str]) -> tuple[list[int], list[str]]:
    """Given user-supplied district names, return (1-based indices,
    canonical district names) in the alphabetised state list.

    Raises ValueError if any district is unknown for the given state,
    listing the close matches.
    """
    all_districts = _india_district_names(state_name)
    # Case-insensitive lookup so callers don't have to mirror GAUL casing.
    lower_map = {d.lower(): d for d in all_districts}

    indices: list[int] = []
    canonical: list[str] = []
    unknown: list[str] = []

    for raw in districts:
        key = raw.strip().lower()
        if key in lower_map:
            d = lower_map[key]
            canonical.append(d)
            indices.append(all_districts.index(d) + 1)   # 1-based
        else:
            unknown.append(raw)

    if unknown:
        # Try to suggest near matches so typos are quick to fix.
        from difflib import get_close_matches
        suggestions = {
            u: get_close_matches(u, all_districts, n=3) for u in unknown
        }
        suggestion_lines = '\n'.join(
            f'  "{u}" — did you mean: {", ".join(s) if s else "(no close match)"}'
            for u, s in suggestions.items())
        raise ValueError(
            f'Unknown district(s) for state "{state_name}":\n{suggestion_lines}\n'
            f'Full list of {len(all_districts)} districts: {all_districts}')

    return indices, canonical


def _derive_title(state_name: str,
                  indices: Optional[list[int]],
                  total_districts: int) -> str:
    """Same rule as `ee_app.js#deriveAdminTitle`."""
    state_slug = slugify(state_name)
    if not indices or len(indices) == total_districts:
        return state_slug
    sorted_idx = sorted(indices)
    return f'{state_slug}_{",".join(str(i) for i in sorted_idx)}'


# ---------------------------------------------------------------------------

class AdminRoi:
    """Resolved admin region: geometry + title + legend metadata.

    Construct via `AdminRoi.from_state(...)` or
    `AdminRoi.from_districts(...)`.
    """

    def __init__(self, *, state_name: str, geometry: ee.Geometry,
                 title: str, is_whole_state: bool,
                 districts: list[str], indices: list[int],
                 total_districts: int):
        self.state_name      = state_name
        self.geometry        = geometry
        self.title           = title
        self.is_whole_state  = is_whole_state
        self.districts       = districts
        self.indices         = indices
        self.total_districts = total_districts

    @property
    def district_numbering(self) -> str:
        """Human-readable legend, e.g. '3=Ernakulam, 7=Kollam'.

        Empty string when the region is the whole state.  Attached to
        exported assets as the `district_numbering` image property.
        """
        if self.is_whole_state:
            return ''
        return ', '.join(
            f'{i}={d}' for i, d in sorted(zip(self.indices, self.districts)))

    @classmethod
    def from_state(cls, state_name: str) -> 'AdminRoi':
        """Whole state — geometry is the union of all districts.

        Title: just the slugified state name (e.g. 'kerala').
        """
        districts = _india_district_names(state_name)
        if not districts:
            raise ValueError(
                f'State "{state_name}" not found in FAO/GAUL/2015 level2 '
                f'(India).  Check spelling — GAUL uses names like '
                f'"Kerala", "Tamil Nadu", "Uttar Pradesh".')

        return cls(
            state_name=state_name,
            geometry=_india_state_geom(state_name),
            title=slugify(state_name),
            is_whole_state=True,
            districts=[],
            indices=[],
            total_districts=len(districts),
        )

    @classmethod
    def from_districts(cls,
                       state_name: str,
                       districts: Iterable[str]) -> 'AdminRoi':
        """Subset of districts within a state.

        ROI is the union of the selected district polygons.

        Title: '<state>_<i,j,k>' with 1-based indices into the
        alphabetised district list (matches `ee_app.js`).  If every
        district in the state is listed, the title collapses to just
        the state name (same as `from_state`).
        """
        all_districts = _india_district_names(state_name)
        if not all_districts:
            raise ValueError(
                f'State "{state_name}" not found in FAO/GAUL/2015 level2 '
                f'(India).')

        district_list = [d for d in districts if d and d.strip()]
        if not district_list:
            # Empty list = same as whole state.  Defer to from_state.
            return cls.from_state(state_name)

        indices, canonical = _districts_to_indices(state_name, district_list)
        is_whole = (len(indices) == len(all_districts))

        if is_whole:
            geom = _india_state_geom(state_name)
        else:
            geom = _india_district_geom(state_name, canonical)

        return cls(
            state_name=state_name,
            geometry=geom,
            title=_derive_title(state_name, indices, len(all_districts)),
            is_whole_state=is_whole,
            districts=canonical,
            indices=sorted(indices),
            total_districts=len(all_districts),
        )

    def __repr__(self) -> str:
        if self.is_whole_state:
            return (f'AdminRoi(state="{self.state_name}", '
                    f'whole_state, title="{self.title}")')
        return (f'AdminRoi(state="{self.state_name}", '
                f'districts={self.districts}, '
                f'indices={self.indices}, title="{self.title}")')
