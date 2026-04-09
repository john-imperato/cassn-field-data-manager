# CA-SSN Field Data Manager

A Python desktop application for downloading, uploading, and managing wildlife image and audio data. Designed for the University of California Natural Reserve System (UCNRS) California Sentinel Sites for Nature (CASSN) team collecting standardized biodiversity data with camera traps and acoustic recorders across California.

![Version](https://img.shields.io/badge/version-2.2-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Guided Workflow**: Step-by-step interface for SD card download and cloud storage upload across multi-plot, multi-device deployments
- **Standardized File Naming**: Files renamed to a consistent convention (`ORG_SITE_plotN_DEVTYPE_YYYYMMDD_SEQNO.ext`) for all devices. Camera images additionally encode trigger event and burst position (`EVENTNO_POS`) so photos from the same trigger are grouped.
- **Reconyx MakerNote Parsing**: Sequence position, trigger type (Motion/Time-lapse), and sequence total extracted directly from Reconyx HYPERFIRE HP4K EXIF MakerNote.
- **Device Identification**: Physical device IDs recorded per file. Camera serial numbers sourced from `cameras.csv`, AudioMoth device IDs parsed from CONFIG.TXT.
- **Timestamps**: `recorded_datetime` stored as ISO 8601 with UTC offset (e.g. `2025-12-04T15:48:05-08:00`), sourced from EXIF for cameras and AudioMoth filename for audio; DST-aware via `zoneinfo`
- **File Metadata CSV**: One row per file with standardized fields covering file, device, location, and timing information. See the Metadata CSV Fields section below for the full schema.
- **Deployment Records**: Deployment configuration and file manifest saved as JSON for each session.
- **Data Integrity**: SHA-256 checksum recorded for each file, enabling corruption detection if needed.
- **Cloud Storage**: Automatic upload to Box with progress tracking and OAuth token refresh
- **Multi-Format File Support**: Images (JPG, PNG, TIF, RAW), audio (WAV, MP3, FLAC)
- **Configurable Lookup Tables**: Site, plot, and camera metadata loaded from local CSV files, making the app adaptable to other CASSN partners.
- **Wildlife Insights Export**: Generates a deployment CSV formatted for upload to Wildlife Insights, using camera and plot metadata from `cameras.csv` and `wi_config.json`.
- **Session Persistence**: Interrupted downloads resume automatically. Previously copied files are skipped and sequence/event numbering continues correctly.

## Installation

### Prerequisites

- Python 3.9 or higher
- pip package manager

### Install Dependencies

```bash
pip install PySide6 pillow piexif box-sdk-gen
```

### Download

Clone this repository or download the latest release:

```bash
git clone https://github.com/john-imperato/cassn-field-data-manager.git
cd cassn-field-data-manager
```

### Configure Box Credentials

Credentials to connect with your Box account are stored in `~/.cassn_credentials/`, a hidden folder in your home directory, outside the repo so they are never accidentally committed to version control.

Create the folder and config file:

```bash
mkdir -p ~/.cassn_credentials
cp config.json.example ~/.cassn_credentials/config.json
```

Edit `~/.cassn_credentials/config.json` and add your Box application credentials:

```json
{
  "box": {
    "client_id": "YOUR_BOX_CLIENT_ID",
    "client_secret": "YOUR_BOX_CLIENT_SECRET",
    "target_folder_id": "YOUR_BOX_FOLDER_ID"
  }
}
```

Lock down the folder permissions so only you can read it:

```bash
chmod 700 ~/.cassn_credentials
chmod 600 ~/.cassn_credentials/config.json
```

**To get Box credentials:**
1. Go to https://app.box.com/developers/console
2. Create a new app (Custom App → OAuth 2.0)
3. Copy the Client ID and Client Secret
4. Navigate to the Box folder where you want data uploaded and copy the ID from the URL (e.g. `https://app.box.com/folder/123456789` → folder ID is `123456789`)

## Usage

### 1. Box Authentication (First Time Setup)

After configuring `~/.cassn_credentials/config.json`, authenticate with Box
using the utility script:

```bash
python3 utils/box_auth_setup.py
```

Follow the prompts to:
- Open the Box authorization URL in your browser
- Grant access to the application
- Paste the full redirect URL back into the terminal

This creates or refreshes `~/.cassn_credentials/box_tokens.json`, which enables automatic cloud uploads. No manual copy step is required. For detailed Box utility documentation, see [`utils/README.md`](utils/README.md). Box tokens expire after ~60 days of inactivity. Re-run the command above to refresh them.

### 2. Run the Application

```bash
python cassn_field_data_manager.py
```

### 3. Workflow

#### Step 1: Deployment Metadata
- Select UC as the organization
- Choose the reserve/site from dropdown (auto-complete enabled)
- Enter deployment start and end dates
- Select who is downloading the data
- Check which devices (ML, SA, BD, BT) for each plot
- Configure local staging location (default: `~/Desktop/CASSN_field_data_staging`)
- Enable/disable automatic Box upload

#### Step 2: Collect SD Card Data
- Insert SD card for each device
- Select the device from the list
- Click "Select SD Card & Copy Files" to copy, rename, and hash all files to local staging
- Repeat for all devices

#### Step 3: Review & Finalize
- Review deployment summary
- View file counts and sizes by device
- Files automatically upload to Box (if enabled)
- Open staging folder to verify
- Start new deployment or exit

### Screenshots

#### Deployment Metadata Entry
Enter deployment information, select devices, and configure storage location.

![Deployment Metadata Entry](screenshots/01-metadata-entry.png)

#### SD Card Data Collection
Copy files from SD cards with automatic renaming and metadata extraction.

![SD Card Data Collection](screenshots/02-data-collection.png)

#### Review & Upload to Box
View deployment summary and upload to Box cloud storage.

![Review & Upload](screenshots/03-review-upload.png)

## Output Structure

The application creates an organized folder structure in your staging location:

```
ORG_SITE_YYYYMMDD/
├── deployment_event_record.json # Deployment event record (devices, file count, dates)
├── file_metadata.csv           # Detailed file metadata
├── WI_metadata/                # Wildlife Insights deployment CSVs
│   ├── wildlife_insights_ML_deployments.csv
│   └── wildlife_insights_SA_deployments.csv
└── raw_data/
    ├── p1_ML/                  # Plot 1, Medium-Large camera
    │   ├── UC_Bodega_plot1_ML_202601_00001_1.jpg   # Trigger event 1, photo 1
    │   ├── UC_Bodega_plot1_ML_202601_00001_2.jpg   # Trigger event 1, photo 2
    │   ├── UC_Bodega_plot1_ML_202601_00001_3.jpg   # Trigger event 1, photo 3
    │   ├── UC_Bodega_plot1_ML_202601_00002_1.jpg   # Trigger event 2, photo 1
    │   └── ...
    ├── p1_BD/                  # Plot 1, Bird recorder
    │   ├── UC_Bodega_plot1_BD_202601_00001.wav
    │   └── ...
    └── ...
```

### Wildlife Insights Deployment CSV

At the end of each session, the app automatically generates deployment CSVs formatted for upload to Wildlife Insights, saved to `WI_metadata/` within the deployment folder. One CSV is produced per device type (ML, SA). Requires `cameras.csv` and `wi_config.json` to be populated in `local_data/`.

### Metadata CSV Fields

The `file_metadata.csv` includes one row per file with the following columns:

| Field | Description | Devices |
|---|---|---|
| `new_filename` | Standardized filename assigned by the app | All |
| `original_filename` | Original filename from SD card | All |
| `plot_number` | Plot number | All |
| `plot_label` | Plot name from plots.csv | All |
| `device_type` | ML, SA, BD, or BT | All |
| `device_id` | Camera serial number (from cameras.csv) or AudioMoth Device ID (from CONFIG.TXT) | All |
| `file_type` | image, audio, or config | All |
| `file_size_bytes` | File size in bytes | All |
| `file_hash_sha256` | SHA-256 checksum for integrity verification | All |
| `recorded_datetime` | ISO 8601 datetime with UTC offset (e.g. `2025-12-04T15:48:05-08:00`); from EXIF for cameras, AudioMoth filename for audio | All |
| `latitude` | Plot latitude from plots.csv | All |
| `longitude` | Plot longitude from plots.csv | All |
| `camera_make` | Camera manufacturer from EXIF | Cameras only |
| `camera_model` | Camera model from EXIF | Cameras only |
| `sequence_trigger_type` | Trigger type from Reconyx MakerNote (`M`=Motion, `T`=Time-lapse) | Cameras only |
| `sequence_event_num` | Trigger event number — groups all photos from the same trigger | Cameras only |
| `sequence_position` | Photo's position within the sequence (1, 2, 3) | Cameras only |
| `sequence_total` | Total photos per trigger sequence | Cameras only |

## Device Types

- **ML**: Medium-Large Animal Camera
- **SA**: Small Animal Camera
- **BD**: Acoustic Recorder (Birds)
- **BT**: Acoustic Recorder (Bats)

## Configuration

### Lookup Tables

The application requires real site and plot CSVs in the repo-local ignored
`local_data/` folder:

- `local_data/sites.csv`
- `local_data/plots.csv`
- `local_data/cameras.csv`
- `local_data/wi_config.json`

These files are not tracked by git and are intended for operational metadata,
including any sensitive plot information you do not want in a public repository.

The repo includes tracked example files in `example_data/` so you can create
your local copies:

- `example_data/sites.csv`
- `example_data/plots.csv`
- `example_data/cameras.csv`
- `example_data/wi_config.json`

To create your private local copies:

```bash
mkdir -p local_data
cp example_data/sites.csv local_data/sites.csv
cp example_data/plots.csv local_data/plots.csv
cp example_data/cameras.csv local_data/cameras.csv
cp example_data/wi_config.json local_data/wi_config.json
```

**`cameras.csv`**: Camera serial numbers and Wildlife Insights metadata per plot. The
`generate_wi_deployments.py` utility will auto-generate a skeleton from `plots.csv` if
this file does not exist. Fill in `camera_id` (physical serial number) and `feature_type`
(e.g. `Road dirt`, `Trail game`) for each camera.

**`wi_config.json`**: Wildlife Insights project IDs and upload defaults. Edit
`project_id_ML` and `project_id_SA` to match your project IDs in Wildlife Insights.

Then edit the files in `local_data/`. Changes take effect on next app launch.

The application does not fall back to `example_data/` during normal operation.
Those files are templates only.

## Building the macOS App

To run as a double-clickable macOS `.app` (no terminal required):

```bash
bash build.sh
```

This will:
1. Install PyInstaller if needed
2. Convert the icon to macOS format
3. Bundle Python, all dependencies, assets, and example data into a self-contained `.app`
4. Output `dist/CASSN Field Data Manager.app`

Then install it:

```bash
sudo rm -rf "/Applications/CASSN Field Data Manager.app"
cp -r "dist/CASSN Field Data Manager.app" /Applications/
```

**Note:** `~/.cassn_credentials/config.json` and `~/.cassn_credentials/box_tokens.json` must be set up before launching the `.app`. The bundle does not include credentials.

To rebuild after code changes, run `bash build.sh` again and reinstall.

## Development

### Project Structure

```
cassn-field-data-manager/
├── cassn_field_data_manager.py       # Main application
├── build.sh                          # Script to build the macOS .app bundle
├── cassn_field_data_manager.spec     # PyInstaller configuration for the .app build
├── config.json.example               # Configuration template
├── assets/                           # Visual assets (logos for app UI)
│   ├── ucnrs_logo.png                # UCNRS logo
│   ├── cassn_icon.png                # CA-SSN logo
│   └── cassn_icon.icns               # macOS icon format (generated by build.sh)
├── example_data/                     # Tracked templates and schema examples
│   ├── sites.csv                     # Site/reserve lookup example
│   ├── plots.csv                     # Plot lookup example
│   ├── cameras.csv                   # Camera metadata example (serial numbers, feature types)
│   └── wi_config.json                # Wildlife Insights config example
├── local_data/                       # Real operational CSVs and config (gitignored)
├── utils/
│   ├── box_auth_setup.py             # Box OAuth authentication utility
│   ├── recover_file_metadata.py      # Metadata recovery utility
│   └── generate_wi_deployments.py    # Wildlife Insights deployment CSV generator
├── screenshots/                      # Application screenshots for README
├── .gitignore                        # Git ignore file
└── README.md                         # This file
```
