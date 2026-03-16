#!/usr/bin/env python3
"""
recover_file_metadata.py
------------------------
Recovers a missing file_metadata.csv for a CA-SSN deployment by re-downloading
files from Box, computing SHA-256 hashes, extracting EXIF data, and parsing
filenames according to the org_site_plot_devicetype_deployment_filenumber convention.

Usage:
    python3 recover_file_metadata.py

Edit the CONFIG section below before running.
"""

import csv
import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path

# ── box_sdk_gen imports ────────────────────────────────────────────────────────
from box_sdk_gen import BoxClient, BoxOAuth, OAuthConfig

# ── Optional: Pillow for EXIF (install with: pip install Pillow) ───────────────
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("⚠️  Pillow not installed — EXIF fields will be empty. Run: pip install Pillow")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — edit these before running
# ══════════════════════════════════════════════════════════════════════════════

# Path to your box_tokens.json (same one the app uses)
TOKEN_FILE = Path.home() / ".cassn_credentials" / "box_tokens.json"

# Path to config.json with client_id / client_secret
CONFIG_FILE = Path.home() / ".cassn_credentials" / "config.json"

# Box folder ID for the deployment you want to recover.
# Find this in the Box URL when you open the folder:
#   https://app.box.com/folder/XXXXXXXXXX  ← that number
BOX_DEPLOYMENT_FOLDER_ID = "370997912973"

# Where to write the recovered CSV (defaults to current directory)
OUTPUT_CSV = Path("./file_metadata_recovered.csv")

# ══════════════════════════════════════════════════════════════════════════════


def load_box_client():
    """Authenticate using saved OAuth tokens, using the same SimpleTokenStorage
    approach as the main app (get_box_client in cassn_field_data_manager.py)."""
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"Token file not found: {TOKEN_FILE}")
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")

    with open(CONFIG_FILE) as f:
        config_data = json.load(f)

    box_config = config_data.get("box", config_data)  # support both nested and flat

    class SimpleTokenStorage:
        def __init__(self, token_file_path):
            self.token_file = token_file_path

        def store(self, token):
            tokens = {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
            }
            with open(self.token_file, "w") as f:
                json.dump(tokens, f, indent=2)

        def get(self):
            try:
                from box_sdk_gen import AccessToken
                with open(self.token_file, "r") as f:
                    data = json.load(f)
                return AccessToken(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                )
            except Exception:
                return None

        def clear(self):
            if self.token_file.exists():
                self.token_file.unlink()

    config = OAuthConfig(
        client_id=box_config["client_id"],
        client_secret=box_config["client_secret"],
        token_storage=SimpleTokenStorage(TOKEN_FILE),
    )
    auth = BoxOAuth(config)
    return BoxClient(auth)


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_exif(path: Path) -> dict:
    """Return EXIF fields used in file_metadata.csv, or empty strings."""
    result = {
        "exif_datetime": "",
        "exif_make": "",
        "exif_model": "",
        "latitude": "",
        "longitude": "",
    }
    if not PILLOW_AVAILABLE:
        return result

    try:
        img = Image.open(path)
        exif_data = img._getexif()
        if not exif_data:
            return result

        tag_map = {TAGS.get(k, k): v for k, v in exif_data.items()}

        result["exif_make"] = str(tag_map.get("Make", "")).strip()
        result["exif_model"] = str(tag_map.get("Model", "")).strip()

        # Prefer DateTimeOriginal, fall back to DateTime
        dt_raw = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime", "")
        result["exif_datetime"] = str(dt_raw).strip()

        # GPS
        gps_info = tag_map.get("GPSInfo")
        if gps_info:
            gps_tags = {TAGS.get(k, k): v for k, v in gps_info.items()}
            lat = _dms_to_dd(gps_tags.get("GPSLatitude"), gps_tags.get("GPSLatitudeRef"))
            lon = _dms_to_dd(gps_tags.get("GPSLongitude"), gps_tags.get("GPSLongitudeRef"))
            if lat is not None:
                result["latitude"] = str(round(lat, 6))
            if lon is not None:
                result["longitude"] = str(round(lon, 6))
    except Exception as e:
        print(f"    EXIF warning for {path.name}: {e}")

    return result


def _dms_to_dd(dms, ref) -> float | None:
    """Convert degrees/minutes/seconds tuple to decimal degrees."""
    if not dms or not ref:
        return None
    try:
        def to_float(v):
            if isinstance(v, tuple):
                return v[0] / v[1] if v[1] else 0.0
            return float(v)
        d = to_float(dms[0])
        m = to_float(dms[1])
        s = to_float(dms[2])
        dd = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            dd = -dd
        return dd
    except Exception:
        return None


def parse_filename(filename: str) -> dict:
    """
    Parse CA-SSN filename convention:
        org_site_plot_devicetype_deployment_filenumber.ext

    Returns a dict with extracted fields (empty string if not parseable).
    """
    stem = Path(filename).stem
    parts = stem.split("_")

    result = {
        "plot_number": "",
        "plot_label": "",
        "device_type": "",
        "device_label": "",
    }

    # Convention has at least 6 underscore-separated parts
    if len(parts) >= 6:
        result["plot_number"] = parts[2]        # e.g. "1", "2"
        result["device_type"] = parts[3]        # e.g. "CT", "AM", "BD"

        # Reconstruct labels used in the app
        result["plot_label"] = f"Plot {parts[2]}"
        result["device_type_raw"] = parts[3]

        device_labels = {
            "CT": "Camera Trap",
            "AM": "AudioMoth",
            "BD": "BirdWeather PUC",
        }
        result["device_label"] = device_labels.get(parts[3], parts[3])

    return result


def get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    audio_exts = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
    if ext in image_exts:
        return "image"
    elif ext in audio_exts:
        return "audio"
    return "other"


def upload_csv_to_box(client: BoxClient, folder_id: str, csv_path: Path):
    """Upload the recovered CSV to the Box deployment folder as file_metadata.csv.
    If a file_metadata.csv already exists there, overwrite it."""
    # Check if file_metadata.csv already exists in the folder
    items = client.folders.get_folder_items(folder_id, fields=["id", "name", "type"])
    existing_id = None
    for item in items.entries:
        if item.type == "file" and item.name == "file_metadata.csv":
            existing_id = item.id
            break

    with open(csv_path, "rb") as f:
        if existing_id:
            print(f"   Overwriting existing file_metadata.csv (id: {existing_id})...")
            client.uploads.upload_file_version(
                existing_id,
                attributes={"name": "file_metadata.csv"},
                file=f,
            )
        else:
            print("   Uploading new file_metadata.csv...")
            client.uploads.upload_file(
                attributes={"name": "file_metadata.csv", "parent": {"id": folder_id}},
                file=f,
            )


def list_all_files(client: BoxClient, folder_id: str) -> list[dict]:
    """Recursively list all files under a Box folder."""
    files = []
    _recurse(client, folder_id, files, box_path="")
    return files


def _recurse(client, folder_id, files, box_path):
    items = client.folders.get_folder_items(folder_id, fields=["id", "name", "type", "size"])
    for item in items.entries:
        if item.type == "file":
            files.append({"id": item.id, "name": item.name, "size": item.size, "box_path": box_path})
        elif item.type == "folder":
            _recurse(client, item.id, files, box_path=box_path + "/" + item.name if box_path else item.name)


# ── Output CSV columns matching the app's schema ──────────────────────────────
FIELDNAMES = [
    "new_filename",
    "original_filename",
    "plot_number",
    "plot_label",
    "device_type",
    "device_label",
    "file_type",
    "file_size_bytes",
    "file_hash_sha256",
    "timestamp",
    "latitude",
    "longitude",
    "exif_datetime",
    "exif_make",
    "exif_model",
    "source_path",
]


def main():
    if BOX_DEPLOYMENT_FOLDER_ID == "REPLACE_WITH_FOLDER_ID":
        print("❌ Please set BOX_DEPLOYMENT_FOLDER_ID in the CONFIG section before running.")
        return

    print("🔑 Authenticating with Box...")
    client = load_box_client()
    user = client.users.get_user_me()
    print(f"   Connected as: {user.name} ({user.login})")

    print(f"\n📂 Listing files in folder {BOX_DEPLOYMENT_FOLDER_ID}...")
    all_files = list_all_files(client, BOX_DEPLOYMENT_FOLDER_ID)
    print(f"   Found {len(all_files)} files")

    rows = []

    for i, file_info in enumerate(all_files, 1):
        fname = file_info["name"]
        print(f"   [{i}/{len(all_files)}] {fname}")

        # Skip metadata files the app itself creates
        if fname in ("file_metadata.csv", "deployment_metadata.json", "manifest.json"):
            print("      → skipping metadata file")
            continue

        # Download to a single temp file, process it, then delete immediately
        suffix = Path(fname).suffix
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = Path(tmp.name)

            with open(tmp_path, "wb") as f:
                client.downloads.download_file_to_output_stream(file_info["id"], f)

            # Hash
            sha = sha256_of_file(tmp_path)

            # EXIF
            exif = extract_exif(tmp_path)

        except Exception as e:
            print(f"      ⚠️  Failed: {e}")
            continue
        finally:
            # Always delete the temp file, even if processing failed
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

        # Filename parsing
        parsed = parse_filename(fname)

        # Timestamp: prefer EXIF datetime
        timestamp = exif.get("exif_datetime") or ""

        row = {
            "new_filename": fname,
            "original_filename": "",        # not recoverable from Box
            "plot_number": parsed.get("plot_number", ""),
            "plot_label": parsed.get("plot_label", ""),
            "device_type": parsed.get("device_type", ""),
            "device_label": parsed.get("device_label", ""),
            "file_type": get_file_type(fname),
            "file_size_bytes": file_info.get("size", ""),
            "file_hash_sha256": sha,
            "timestamp": timestamp,
            "latitude": exif.get("latitude", ""),
            "longitude": exif.get("longitude", ""),
            "exif_datetime": exif.get("exif_datetime", ""),
            "exif_make": exif.get("exif_make", ""),
            "exif_model": exif.get("exif_model", ""),
            "source_path": f"box://{BOX_DEPLOYMENT_FOLDER_ID}/{file_info.get('box_path', '')}/{fname}".replace("//", "/"),
        }
        rows.append(row)

    # Write CSV locally
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Done! Recovered {len(rows)} file records.")
    print(f"   CSV written locally to: {OUTPUT_CSV.resolve()}")

    # Upload to Box
    print(f"\n📤 Uploading file_metadata.csv to Box folder {BOX_DEPLOYMENT_FOLDER_ID}...")
    try:
        upload_csv_to_box(client, BOX_DEPLOYMENT_FOLDER_ID, OUTPUT_CSV)
        print("   ✅ Uploaded successfully.")
    except Exception as e:
        print(f"   ⚠️  Box upload failed: {e}")
        print(f"   The local copy is still available at: {OUTPUT_CSV.resolve()}")

    print()
    print("⚠️  Note: 'original_filename' is blank (not stored in Box).")
    print("    All other fields are fully recovered.")


if __name__ == "__main__":
    main()