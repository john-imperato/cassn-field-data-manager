# CA-SSN Field Data Manager — Utilities

Helper scripts for maintenance and data recovery tasks.

---

## `recover_file_metadata.py`

Recovers a missing `file_metadata.csv` for a deployment by re-downloading
files from Box, recomputing SHA-256 hashes, and extracting EXIF metadata.

### When to use

If the app completed SD card processing and Box upload successfully but
`file_metadata.csv` was not written to the local staging folder.

### Requirements
```bash
pip install Pillow box-sdk-gen
```

`box-sdk-gen` is already installed if you've used the main app.

### Setup

1. Open the script and set `BOX_DEPLOYMENT_FOLDER_ID` in the CONFIG section
   to the numeric folder ID from the Box URL for your deployment:
```
   https://app.box.com/folder/123456789012  ←  that number
```

2. `TOKEN_FILE` and `CONFIG_FILE` default to `~/.cassn_credentials/` —
   no changes needed if credentials are in the standard location.

### Run
```bash
python3 utils/recover_file_metadata.py
```

Progress is printed to the terminal as each file is processed.

### Output

`file_metadata_recovered.csv` is written to the current directory.
Review it, rename it to `file_metadata.csv`, and place it in the
deployment staging folder or upload it to the Box deployment folder
alongside the raw files.

### Notes

- Authenticates using `~/.cassn_credentials/box_tokens.json` — no
  separate authentication step needed
- Files are downloaded one at a time and deleted immediately after
  processing to minimize local disk usage
- `original_filename` will be blank — pre-rename filenames are not
  stored in Box and cannot be recovered
```