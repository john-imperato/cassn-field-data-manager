# CA-SSN Field Data Manager — Utilities

Helper scripts for maintenance and data recovery tasks.

---

## `box_auth_setup.py`

Runs the Box OAuth setup flow and writes reusable Box tokens to
`~/.cassn_credentials/box_tokens.json`.

### When to use

Use this script the first time you connect the app to Box, or any time your
saved Box tokens stop working and need to be refreshed.

### Requirements
```bash
pip install box-sdk-gen
```

You also need a valid Box app config at `~/.cassn_credentials/config.json`.

To verify `box-sdk-gen` is installed:

```bash
python3 -c "import box_sdk_gen; print('box-sdk-gen ok')"
```

### Setup

1. Confirm your Box credentials file exists:
   ```bash
   ls ~/.cassn_credentials/config.json
   ```
2. If needed, create it from the example file:
   ```bash
   mkdir -p ~/.cassn_credentials
   cp config.json.example ~/.cassn_credentials/config.json
   ```
3. Edit `~/.cassn_credentials/config.json` and add your Box app `client_id` and `client_secret`.

### Run
```bash
python3 utils/box_auth_setup.py
```

The script will:

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

- the main app
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

If the app completed SD card processing and Box upload successfully but
the deployment metadata artifacts were not written locally or need to be rebuilt.

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
2. Open [`utils/recover_file_metadata.py`](/tmp/cassn-rewrite-main/utils/recover_file_metadata.py) and confirm the hard-coded recovery root matches your machine:
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

### Run
```bash
python3 utils/recover_file_metadata.py BOX_FOLDER_ID
```

Replace `BOX_FOLDER_ID` with the numeric deployment folder ID from Box. Do not include angle brackets.

The script recovers exactly one deployment folder per run.

Progress is printed to the terminal as files are downloaded and processed.

Example terminal output during a live recovery run:

![Recovery progress](../screenshots/04-recover-file-metadata-progress.png)

### Output

The script creates a local recovery folder under:

```text
/Volumes/G-DRIVE ArmorATD/cassn-field-data-staging/<deployment-folder-name>/
```

That folder contains:

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
- Does not upload any recovered files back to Box
- Writes `recovery_report.json` even when the run completes with failures
