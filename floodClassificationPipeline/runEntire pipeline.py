import time
import ee

# Initialise with your Cloud project
ee.Initialize(project='gentle-operator-308420')

from flood_mapping import (
    download_temporal_images_for_years,
    classify_years,
)
from flood_mapping.admin import _india_district_names

# ── Config ────────────────────────────────────────────────────
STATE       = 'Assam'
YEARS       = [2019, 2020, 2021, 2022, 2023, 2024]
ASSET_ROOT  = 'projects/gentle-operator-308420/assets/TemporalImagesNew'
OUTPUT_ROOT = 'projects/gentle-operator-308420/assets/Classified'
TRAINING_FC = 'projects/gentle-operator-308420/assets/finalDataset/full_dataset_v3'

# ── Automatically find the 13th district ──────────────────────
# admin.py alphabetises the GAUL level 2 names automatically
all_assam_districts = _india_district_names(STATE)
target_district = all_assam_districts[12]  # 0-based index, so 12 is the 13th district
DISTRICTS = [target_district]

print(f"Targeting 13th district of {STATE}: {target_district}")


# ── Step 1: Download Temporal Images ──────────────────────────
print("\n--- STARTING STEP 1: TEMPORAL DOWNLOADS ---")
download_results = download_temporal_images_for_years(
    state=STATE,
    districts=DISTRICTS,
    years=YEARS,
    training_fc=TRAINING_FC,
    asset_root=ASSET_ROOT,
    destinations='asset',
)

# Extract the queued tasks from the results (ignoring years that were skipped)
active_tasks = [
    res['fullyear_asset_task'] 
    for res in download_results 
    if res.get('fullyear_asset_task') is not None
]


# ── Step 1.5: Wait for Tasks to Complete ──────────────────────
if active_tasks:
    print(f"\n--- WAITING FOR {len(active_tasks)} EXPORT TASK(S) TO FINISH ---")
    
    for task in active_tasks:
        task_id = task.id
        print(f"Monitoring Task: {task_id}")
        
        while True:
            status = task.status()
            state = status['state']
            
            if state in ['READY', 'RUNNING']:
                print(f"  [{state}] Waiting 60 seconds...")
                time.sleep(60)  # Check every 1 minute
            elif state == 'COMPLETED':
                print(f"  [COMPLETED] Task {task_id} finished successfully.")
                break
            else:
                # FAILED, CANCELLED, etc.
                error_msg = status.get('error_message', 'Unknown error')
                raise Exception(f"Task {task_id} failed with state {state}: {error_msg}")
else:
    print("\n--- NO NEW TASKS QUEUED (Assets likely already exist) ---")


# ── Step 2: Run Classification ────────────────────────────────
print("\n--- STARTING STEP 2: CLASSIFICATION ---")
# This will now safely run because we guaranteed Step 1 finished
classify_years(
    state=STATE,
    districts=DISTRICTS,
    years=YEARS,
    asset_root=ASSET_ROOT,
    destinations='asset',
    output_root=OUTPUT_ROOT,
)

print("\n--- PIPELINE COMPLETE ---")