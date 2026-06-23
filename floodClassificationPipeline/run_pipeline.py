from __future__ import annotations
 
import argparse
import sys
import time
 
 
# ── Defaults (override any of these from the command line) ────────────────
DEFAULT_YEARS       = [2019, 2020, 2021, 2022, 2023, 2024]
DEFAULT_PROJECT     = 'gentle-operator-308420'
DEFAULT_ASSET_ROOT  = 'projects/gentle-operator-308420/assets/TemporalImagesNew'
DEFAULT_OUTPUT_ROOT = 'projects/gentle-operator-308420/assets/Classified'
DEFAULT_TRAINING_FC = 'projects/gentle-operator-308420/assets/finalDataset/full_dataset_v3'
 
 
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='Run the flood classification pipeline from the command line.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
 
    # What to process
    p.add_argument('--state', required=True,
                   help='Indian state name as in FAO GAUL level-1 (e.g. "Bihar", "Assam").')
    p.add_argument('--districts', nargs='*', default=None,
                   help='Zero or more district names within the state. '
                        'Omit to process the whole state.')
    p.add_argument('--district-index', type=int, default=None,
                   help='Pick a single district by its 1-based position in the '
                        'alphabetised district list (alternative to --districts).')
    p.add_argument('--years', nargs='+', type=int, default=DEFAULT_YEARS,
                   help='One or more years to process.')
 
    # Which step(s) to run
    p.add_argument('--step', choices=['download', 'classify', 'both'],
                   default='both',
                   help='Run only download, only classify, or both.')
    p.add_argument('--wait', action='store_true',
                   help='After download, block until the Earth Engine export '
                        'tasks finish before classifying (mirrors '
                        '"runEntire pipeline.py").')
    p.add_argument('--poll-seconds', type=int, default=60,
                   help='How often to poll EE task status when --wait is set.')
 
    # Earth Engine / asset configuration
    p.add_argument('--project', default=DEFAULT_PROJECT,
                   help='Google Cloud project for ee.Initialize().')
    p.add_argument('--asset-root', default=DEFAULT_ASSET_ROOT,
                   help='Root EE asset folder for the full-year temporal stacks.')
    p.add_argument('--output-root', default=DEFAULT_OUTPUT_ROOT,
                   help='Root EE asset folder for classified outputs.')
    p.add_argument('--training-fc', default=DEFAULT_TRAINING_FC,
                   help='Training FeatureCollection asset id.')
    p.add_argument('--destinations', default='asset',
                   help="Comma-separated export destinations, e.g. 'asset' or 'asset,drive'.")
    p.add_argument('--drive-folder', default=None,
                   help="Drive folder (required if 'drive' is in --destinations).")
 
    return p.parse_args(argv)
 
 
def resolve_districts(state, districts, district_index):
    """Turn the district-related args into a concrete list (or None)."""
    if district_index is not None:
        if districts:
            raise SystemExit('Use either --districts or --district-index, not both.')
        from flood_mapping.admin import _india_district_names
        all_names = _india_district_names(state)
        if not (1 <= district_index <= len(all_names)):
            raise SystemExit(
                f'--district-index {district_index} out of range; {state} has '
                f'{len(all_names)} districts (valid 1..{len(all_names)}).')
        chosen = all_names[district_index - 1]
        print(f'Targeting district #{district_index} of {state}: {chosen}')
        return [chosen]
    return districts if districts else None
 
 
def wait_for_tasks(download_results, poll_seconds):
    """Block until every queued EE export task reaches COMPLETED."""
    active = [
        res['fullyear_asset_task']
        for res in download_results
        if res.get('fullyear_asset_task') is not None
    ]
    if not active:
        print('\n--- NO NEW TASKS QUEUED (assets likely already exist) ---')
        return
 
    print(f'\n--- WAITING FOR {len(active)} EXPORT TASK(S) TO FINISH ---')
    for task in active:
        task_id = task.id
        print(f'Monitoring task: {task_id}')
        while True:
            status = task.status()
            state = status['state']
            if state in ('READY', 'RUNNING'):
                print(f'  [{state}] waiting {poll_seconds}s...')
                time.sleep(poll_seconds)
            elif state == 'COMPLETED':
                print(f'  [COMPLETED] task {task_id} finished.')
                break
            else:
                err = status.get('error_message', 'Unknown error')
                raise RuntimeError(f'Task {task_id} failed ({state}): {err}')
 
 
def main(argv=None) -> int:
    args = parse_args(argv)
 
    import ee
    ee.Initialize(project=args.project)
 
    from flood_mapping import (
        download_temporal_images_for_years,
        classify_years,
    )
 
    districts = resolve_districts(args.state, args.districts, args.district_index)
    destinations = [d.strip() for d in args.destinations.split(',') if d.strip()]
 
    print(f'State        : {args.state}')
    print(f'Districts    : {districts if districts else "(whole state)"}')
    print(f'Years        : {args.years}')
    print(f'Step         : {args.step}')
 
    download_results = None
 
    if args.step in ('download', 'both'):
        print('\n--- STEP 1: TEMPORAL DOWNLOADS ---')
        dl_kwargs = dict(
            state=args.state,
            years=args.years,
            training_fc=args.training_fc,
            asset_root=args.asset_root,
            destinations=destinations,
        )
        if districts:
            dl_kwargs['districts'] = districts
        if args.drive_folder:
            dl_kwargs['drive_folder'] = args.drive_folder
 
        download_results = download_temporal_images_for_years(**dl_kwargs)
 
        if args.wait:
            wait_for_tasks(download_results, args.poll_seconds)
 
    if args.step in ('classify', 'both'):
        print('\n--- STEP 2: CLASSIFICATION ---')
        cls_kwargs = dict(
            state=args.state,
            years=args.years,
            asset_root=args.asset_root,
            destinations=destinations,
            output_root=args.output_root,
        )
        if districts:
            cls_kwargs['districts'] = districts
        if args.drive_folder:
            cls_kwargs['drive_folder'] = args.drive_folder
 
        classify_years(**cls_kwargs)
 
    print('\n--- PIPELINE COMPLETE ---')
    return 0
 
 
if __name__ == '__main__':
    sys.exit(main())