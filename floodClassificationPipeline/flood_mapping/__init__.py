"""flood_mapping — temporal-image download + classification pipeline."""
from .download_year import (
    download_temporal_images_for_year,
    download_temporal_images_for_years,
)
from .admin import AdminRoi, slugify
from .config import (
    FEATURES_FUSED, FEATURES_S1, SEED, MONSOON_START, N_BIWEEKS,
    N_BIWEEKS_FULL, SCALE, NATIVE_CRS, HISTORICAL_YEARS,
)

# Classification pipeline (uses the exported full-year assets).
from .classify_year import classify_year, classify_years
from .classify_build import build_classification_image
from .classify_config import (
    KHARIF_SLOTS, ZAID_SLOTS, RABI_SLOTS, season_for_slot,
    CLASS_PALETTE, CLASS_LABELS, DEFAULT_THRESHOLDS,
    fullyear_asset_id,
)

__all__ = [
    # download
    'download_temporal_images_for_year',
    'download_temporal_images_for_years',
    'AdminRoi', 'slugify',
    'FEATURES_FUSED', 'FEATURES_S1', 'SEED', 'MONSOON_START',
    'N_BIWEEKS', 'N_BIWEEKS_FULL', 'SCALE', 'NATIVE_CRS',
    'HISTORICAL_YEARS',
    # classify
    'classify_year', 'classify_years',
    'build_classification_image',
    'KHARIF_SLOTS', 'ZAID_SLOTS', 'RABI_SLOTS', 'season_for_slot',
    'CLASS_PALETTE', 'CLASS_LABELS', 'DEFAULT_THRESHOLDS',
    'fullyear_asset_id',
]
