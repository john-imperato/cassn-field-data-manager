# CA-SSN Field Data Manager — Utilities

Helper scripts for maintenance and data recovery tasks.

---

## `box_auth_setup.py`

Runs the Box OAuth setup flow and writes reusable Box tokens to
`~/.cassn_credentials/box_tokens.json`.

### When to use

Use this script the first time you connect `cassn_field_data_manager.py` to Box,
or any time your saved Box tokens stop working and need to be refreshed.

### Requirements
```bash
pip install box-sdk-gen
```

You also need `~/.cassn_credentials/config.json` with your Box app
`client_id` and `client_secret`.

To verify `box-sdk-gen` is installed:

```bash
python3 -c "import box_sdk_gen; print('box-sdk-gen ok')"
```

### Setup

1. Confirm your Box credentials file exists:
   ```bash
   ls ~/.cassn_credentials/config.json
   ```
2. If `~/.cassn_credentials/config.json` does not exist, create it from the example file:
   ```bash
   mkdir -p ~/.cassn_credentials
   cp config.json.example ~/.cassn_credentials/config.json
   ```
3. Edit `~/.cassn_credentials/config.json` and add your Box app `client_id` and `client_secret`.

### Run
```bash
python3 utils/box_auth_setup.py
```

During the OAuth flow, `box_auth_setup.py` will:

1. Open your browser to the Box authorization page.
2. Ask you to log in and grant access.
3. Ask you to paste the full redirect URL back into the terminal.
4. Exchange that authorization code for tokens.
5. Save `box_tokens.json` to `~/.cassn_credentials/`.

### Output

On success, the script writes:

```text
~/.cassn_credentials/box_tokens.json
```

That token file is then used by:

- `cassn_field_data_manager.py`
- `recover_file_metadata.py`

### Notes

- If the script finds an existing token file, it tests that connection first
- If the existing token is invalid, it falls back to a fresh OAuth flow
- Refreshed tokens are written back to `~/.cassn_credentials/box_tokens.json` automatically
- The browser may redirect to a page that does not load; that is expected
- Paste the entire redirect URL, not just the authorization code

---

## `recover_file_metadata.py`

Recovers a deployment by downloading the full Box folder to the staging drive,
then regenerating:

- `file_metadata.csv`
- `manifest.json`
- `recovery_report.json`

### When to use

Use this script when a deployment was successfully uploaded to Box but the
local metadata artifacts were missing, incomplete, or need to be rebuilt.

### Requirements
```bash
pip install Pillow box-sdk-gen
```

Pillow is required. The script fails immediately if EXIF support is unavailable.

### Setup

1. Confirm Box credentials exist in `~/.cassn_credentials/`:
   - `config.json`
   - `box_tokens.json`
   ```bash
   ls ~/.cassn_credentials/config.json ~/.cassn_credentials/box_tokens.json
   ```
2. Open [`utils/recover_file_metadata.py`](/Users/johnimperato/GitHub/cassn-field-data-manager/utils/recover_file_metadata.py) and confirm the hard-coded recovery root matches your machine:
   - `RECOVERY_ROOT = Path("/Volumes/G-DRIVE ArmorATD/cassn-field-data-staging")`
   - Change this path if you want recovered deployments written somewhere else
   ```bash
   rg -n 'RECOVERY_ROOT' utils/recover_file_metadata.py
   ```
3. Confirm that recovery path exists and is writable on your machine.
   ```bash
   ls "/Volumes/G-DRIVE ArmorATD/cassn-field-data-staging"
   ```
4. Find the Box deployment folder ID from the Box URL:
   - `https://app.box.com/folder/123456789012`
   - Use the top-level deployment folder ID, not the `raw_data` subfolder ID
5. Confirm local plot metadata exists for label recovery:
   ```bash
   ls local_data/plots.csv
   ```

### Run
```bash
python3 utils/recover_file_metadata.py BOX_FOLDER_ID
```

Replace `BOX_FOLDER_ID` with the numeric deployment folder ID from Box. 

The script recovers exactly one deployment folder per run.

Progress is printed to the terminal as files are downloaded and processed.

Example terminal output during a live recovery run:

![Recovery progress](../screenshots/04-recover-file-metadata-progress.png)

### Output

The script creates a local recovery folder under:

```text
/Volumes/G-DRIVE ArmorATD/cassn-field-data-staging/<deployment-folder-name>/
```

That recovery folder contains:

- the downloaded Box deployment contents
- `file_metadata.csv`
- `manifest.json`
- `recovery_report.json`

If the deployment folder already exists locally, the script fails and does not overwrite it.

### Notes

- Authenticates using `~/.cassn_credentials/box_tokens.json` — no
  separate authentication step needed
- Downloads the entire deployment and preserves the Box folder structure
- Uses Box modified time for the recovered `timestamp` field
- Sets unrecoverable fields such as `original_filename` and `source_path` to `NA`
- Writes recovered outputs locally only; it does not upload `file_metadata.csv`
  or `manifest.json` back to Box
- Writes `recovery_report.json` even when the run completes with failures
- Uses `local_data/plots.csv` for plot-label lookup; `example_data/` files are templates only

---

## `generate_wi_deployments.py`

Generates Wildlife Insights (WI) bulk-upload deployment CSVs for all deployments in Box,
then uploads them back to Box. Can also process a single local deployment folder for testing.

Each deployment event produces two CSVs — one per camera type — written into a
`WI_metadata/` subfolder inside the deployment folder:

- `wildlife_insights_ML_deployments.csv` — one row per ML (parallel) camera plot
- `wildlife_insights_SA_deployments.csv` — one row per SA (downward) camera plot

These files are formatted for direct import into the Wildlife Insights bulk upload interface.

### Terminology

| CASSN term | WI term |
|---|---|
| Deployment event (4 cameras, ~10 weeks) | Event / subproject |
| Individual camera out for a period | Deployment |

### When to use

- **Backfill:** Run once after a field event to generate WI CSVs for all deployments in Box.
- **New deployments:** Run after each new deployment folder is uploaded to Box.
- **Main app (future):** This logic will be wired into Tab 3 of `cassn_field_data_manager.py`
  so WI CSVs are generated automatically at finalize time.

### Requirements

```bash
pip install box-sdk-gen
```

No additional packages needed beyond the main app requirements.

### Setup

Two local data files must exist before running. Both are gitignored — they contain
project IDs and camera serial numbers that are specific to your machine and should
not be committed.

#### 1. `local_data/cameras.csv`

Maps each site + plot + camera type to a physical camera serial number and WI-required
field attributes. Copy the template and fill in your values:

```bash
cp example_data/cameras.csv local_data/cameras.csv
```

Columns:

| Column | Description | WI accepted values |
|---|---|---|
| `site_code` | Matches `sites.csv` | — |
| `plot_number` | Integer 1–4 | — |
| `device_type` | `ML` or `SA` | — |
| `camera_id` | Physical camera serial number | Any string |
| `feature_type` | Habitat feature at the camera location | `None`, `Road paved`, `Road dirt`, `Trail hiking`, `Trail game`, `Road underpass`, `Road overpass`, `Road bridge`, `Culvert`, `Burrow`, `Nest site`, `Carcass`, `Water source`, `Fruiting tree`, `Other` |
| `sensor_height` | Height of sensor above ground | `Chest height`, `Knee height`, `Canopy`, `Unknown`, `Other` |
| `sensor_orientation` | Camera angle | `Parallel`, `Pointed Downward`, `Pointed Upward`, `Other` |

Default values pre-populated in the skeleton:
- `sensor_height` → `Knee height`
- `sensor_orientation` → `Parallel` (ML), `Pointed Downward` (SA)
- `feature_type` for SA rows → `None`

If `camera_id` is blank for a row, the script logs a warning but still generates the CSV row.
Fill in serial numbers before uploading to WI — WI requires camera records to exist before
deployment records can reference them.

#### 2. `local_data/wi_config.json`

WI project IDs and deployment-level defaults. Copy the template and fill in your values:

```bash
cp example_data/wi_config.json local_data/wi_config.json
```

Fields:

| Key | Description |
|---|---|
| `project_id_ML` | Numeric WI project ID for mammal cameras — from the WI project URL |
| `project_id_SA` | Numeric WI project ID for small animal cameras |
| `bait_type_ML` | WI bait type for ML cameras (e.g. `Scent`) |
| `bait_type_SA` | WI bait type for SA cameras (e.g. `Scent`) |
| `bait_description_ML` | Free-text bait description for ML cameras |
| `bait_description_SA` | Free-text bait description for SA cameras |
| `event_type` | WI event type — default `Temporal` |
| `quiet_period` | Camera quiet period in seconds — default `0` |
| `camera_functioning_default` | Default camera status — default `Camera Functioning` |

To find your WI project ID: log in to [app.wildlifeinsights.org](https://app.wildlifeinsights.org),
open the project, and copy the number from the URL:
`wildlifeinsights.org/manage/projects/XXXXX`

### Run — Box mode (all deployments)

```bash
python3 utils/generate_wi_deployments.py
```

Traverses the full Box hierarchy (root → year → reserve → deployment), downloads
`deployment_metadata.json` and `manifest.json` from each deployment folder (small JSON
files only — images are not downloaded), generates the WI CSVs, and uploads them to a
`WI_metadata/` subfolder within each deployment folder in Box.

Skips any deployment folder that already has WI CSVs in `WI_metadata/` unless `--force`
is passed.

### Run — local mode (single deployment)

```bash
python3 utils/generate_wi_deployments.py --local PATH
```

Processes one local deployment folder. Writes WI CSVs to a `WI_metadata/` subfolder
inside that folder. Useful for testing before running against Box.

Example:

```bash
python3 utils/generate_wi_deployments.py --local '/Volumes/G-DRIVE ArmorATD/2026/UC_QuailRidge_20260108'
```

### Options

| Flag | Description |
|---|---|
| `--local PATH` | Process a single local deployment folder instead of Box |
| `--force` | Regenerate and overwrite WI CSVs even if they already exist |

### Output

For each deployment event, the script creates or updates:

```text
<deployment-folder>/
└── WI_metadata/
    ├── wildlife_insights_ML_deployments.csv
    └── wildlife_insights_SA_deployments.csv
```

Each CSV has exactly 27 columns in the order required by Wildlife Insights bulk upload.
One row per camera plot. Example row values:

| Field | Example |
|---|---|
| `project_id` | `123456` |
| `deployment_id` | `UC_QuailRidge_plot1_ML_20260108` |
| `subproject_name` | `UC_QuailRidge_20260108` |
| `placename` | `QuailRidge_plot1` |
| `event_name` | `2025NOV-2026JAN` |
| `sensor_orientation` | `Parallel` (ML) or `Pointed Downward` (SA) |

### WI camera records (prerequisite for WI upload)

WI requires camera records to exist in your project before deployment records can
reference them. Camera serial numbers in `cameras.csv` must be uploaded to WI via a
separate Cameras bulk upload CSV before importing deployment CSVs. This is a manual
step in the WI interface and is outside the scope of this script.

### Notes

- Authenticates using `~/.cassn_credentials/box_tokens.json` — no separate authentication step needed
- Only downloads `deployment_metadata.json` and `manifest.json` from Box (a few KB each); images are never downloaded
- Audio device types (BD, BT) are ignored — WI image upload only; audio will be handled separately
- `feature_type` for SA cameras defaults to `None` (required by WI but not applicable)
- `sensor_orientation` is pre-populated from `cameras.csv` and falls back to `Parallel` (ML) or `Pointed Downward` (SA) if the row is missing
- Missing `wi_config.json` causes the script to exit with an error before any files are written
- Missing `cameras.csv` causes the script to continue with blank per-camera fields and a warning
- The `WI_metadata/` subfolder is created automatically in Box if it does not exist
