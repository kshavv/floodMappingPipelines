#!/usr/bin/env python3
"""Command-line driver for the Bhuvan flood-tile download pipeline.

Wraps the same functions exposed by ``bhuvan_flood`` so you can run the
pipeline from the command line instead of editing a script:

    download_bhuvan_flood_day          -> --mode day   (single date, 1 band)
    download_bhuvan_kharif_stack       -> --mode kharif (Kharif window, 140 bands)
    download_bhuvan_kharif_biweek_stack-> --mode biweek (bi-week aggregated)

Examples
--------
# Single date, whole state:
python run_bhuvan.py --mode day --state Kerala --date 2023-07-06 \
    --output-path ./final_raster/kerala_2023-07-06.tif

# Single date, one district:
python run_bhuvan.py --mode day --state Kerala --district Ernakulam \
    --date 2023-07-06

# Full Kharif stack, whole state, one year:
python run_bhuvan.py --mode kharif --state Kerala --years 2023

# Full Kharif stack, one district, several years:
python run_bhuvan.py --mode kharif --state Kerala --district Ernakulam \
    --years 2022 2023 2024 --output-dir ./final_raster

# Bi-week aggregated stack:
python run_bhuvan.py --mode biweek --state Kerala --years 2023
"""
from __future__ import annotations

import argparse
import sys


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='Download Bhuvan flood layers from the command line.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument('--mode', choices=['day', 'kharif', 'biweek'], default='kharif',
                   help='day = single date (1 band); kharif = full Kharif stack '
                        '(140 bands); biweek = bi-week aggregated stack.')
    p.add_argument('--state', required=True,
                   help='State name registered in bhuvan_flood/config.py STATES.')
    p.add_argument('--district', default=None,
                   help='Optional single district name within the state.')

    # day mode
    p.add_argument('--date', default=None,
                   help='ISO date YYYY-MM-DD. Required for --mode day.')

    # kharif / biweek mode
    p.add_argument('--years', nargs='+', type=int, default=None,
                   help='One or more years. Required for --mode kharif/biweek.')

    # output
    p.add_argument('--output-path', default=None,
                   help='Exact output GeoTIFF path. For day mode, or for a '
                        'single year in kharif/biweek mode.')
    p.add_argument('--output-dir', default=None,
                   help='Directory for outputs when processing multiple years; '
                        'filenames are auto-generated. Ignored if --output-path is set.')

    # AOI / behaviour
    p.add_argument('--bbox-buffer-deg', type=float, default=0.05,
                   help='Buffer (degrees) added around the AOI bbox.')
    p.add_argument('--no-clip', action='store_true',
                   help='Keep the bbox rectangle instead of clipping to the '
                        'state/district polygon.')
    p.add_argument('--tile-cache-dir', default=None,
                   help='Optional directory to cache downloaded tiles.')
    p.add_argument('--debug', action='store_true', help='Verbose debug header.')
    p.add_argument('--verbose', action='store_true', help='Verbose logging.')
    return p.parse_args(argv)


def _auto_path(output_dir, state, district, tag):
    from pathlib import Path
    slug = state.lower().replace(' ', '_')
    dpart = f'_{district.lower().replace(" ", "_")}' if district else ''
    return str(Path(output_dir) / f'bhuvan_{slug}{dpart}_{tag}.tif')


def main(argv=None) -> int:
    args = parse_args(argv)

    from bhuvan_flood import (
        download_bhuvan_flood_day,
        download_bhuvan_kharif_stack,
        download_bhuvan_kharif_biweek_stack,
    )

    common = dict(
        state=args.state,
        district=args.district,
        bbox_buffer_deg=args.bbox_buffer_deg,
        clip_to_state=not args.no_clip,
        debug=args.debug,
        verbose=args.verbose,
        tile_cache_dir=args.tile_cache_dir,
    )

    if args.mode == 'day':
        if not args.date:
            raise SystemExit('--mode day requires --date YYYY-MM-DD.')
        print(f'\n=== {args.state}'
              f'{"/" + args.district if args.district else ""} {args.date} (day) ===')
        result = download_bhuvan_flood_day(
            date=args.date, output_path=args.output_path, **common)
        out = result.get('output_path') if isinstance(result, dict) else result
        print(f'  -> {out}')
    else:
        if not args.years:
            raise SystemExit(f'--mode {args.mode} requires --years.')
        download = (download_bhuvan_kharif_biweek_stack
                    if args.mode == 'biweek'
                    else download_bhuvan_kharif_stack)
        for year in args.years:
            print(f'\n=== {args.state}'
                  f'{"/" + args.district if args.district else ""} {year} '
                  f'({args.mode}) ===')
            if args.output_path and len(args.years) == 1:
                output_path = args.output_path
            elif args.output_dir:
                output_path = _auto_path(args.output_dir, args.state,
                                         args.district, f'{year}_{args.mode}')
            else:
                output_path = None  # let the pipeline pick its default path
            result = download(year=year, output_path=output_path, **common)
            out = result.get('output_path') if isinstance(result, dict) else result
            print(f'  -> {out}')

    print('\n--- DONE ---')
    return 0


if __name__ == '__main__':
    sys.exit(main())