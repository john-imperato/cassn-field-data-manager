#!/usr/bin/env python3
"""
Recover `file_metadata.csv` and `deployment_event_record.json` for a single Box deployment.

Workflow:
1. Authenticate with Box using the same local credentials as the app.
2. Download the entire deployment folder to the configured staging drive.
3. Recompute file hashes and EXIF metadata from the downloaded files.
4. Rebuild `file_metadata.csv`, `deployment_event_record.json`, and `recovery_report.json`.

Usage:
    python3 utils/recover_file_metadata.py <box_folder_id>
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from box_sdk_gen import BoxClient, BoxOAuth, OAuthConfig

try:
    from PIL import Image
    from PIL.ExifTags import GPSTAGS, TAGS
except ImportError as exc:
    raise SystemExit(
        "Pillow is required for recovery because EXIF extraction is mandatory. "
        "Install it with: pip install Pillow"
    ) from exc

APP_VERSION = "2.1"
TOKEN_FILE = Path.home() / ".cassn_credentials" / "box_tokens.json"
CONFIG_FILE = Path.home() / ".cassn_credentials" / "config.json"
RECOVERY_ROOT = Path("/Volumes/G-DRIVE ArmorATD/cassn-field-data-staging")
LOCAL_DATA_DIR = Path(__file__).resolve().parent.parent / "local_data"

DEVICE_TYPES = {
    "ML": "Medium-Large Animal Camera",
    "SA": "Small Animal Camera",
    "BD": "Acoustic Recorder Birds",
    "BT": "Acoustic Recorder Bats",
}

DEVICE_ORDER = {code: index for index, code in enumerate(DEVICE_TYPES.keys())}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".cr2",
    ".nef",
    ".arw",
    ".dng",
}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".wma", ".ogg"}
CONFIG_EXTENSIONS = {".txt"}

METADATA_FILENAMES = {"file_metadata.csv", "deployment_event_record.json"}

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

MEDIA_RE = re.compile(
    r"^(?P<organization>[^_]+)_(?P<site>[^_]+)_plot(?P<plot_number>\d+)_(?P<device_type>[A-Z]+)_(?P<deployment>\d{6})_(?P<sequence>\d{5})$"
)
CONFIG_RE = re.compile(
    r"^(?P<organization>[^_]+)_(?P<site>[^_]+)_(?P<device_type>[A-Z]+)_(?P<deployment_start>\d{8})_CONFIG_(?P<sequence>\d+)$"
)
DEVICE_FOLDER_RE = re.compile(r"^p(?P<plot_number>\d+)_(?P<device_type>[A-Z]+)$")
DEPLOYMENT_FOLDER_RE = re.compile(
    r"^(?P<organization>[^_]+)_(?P<site>[^_]+)_(?P<deployment_end>\d{8})$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download one Box deployment and regenerate metadata artifacts."
    )
    parser.add_argument("box_folder_id", help="Box deployment folder ID to recover")
    return parser.parse_args()


def required_local_csv_path(filename: str) -> Path:
    return LOCAL_DATA_DIR / filename


def load_plot_names() -> dict[str, list[str | None]]:
    plot_names: dict[str, list[str | None]] = {}
    csv_path = required_local_csv_path("plots.csv")
    if not csv_path.exists():
        return plot_names

    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(csv_path, "r", encoding=encoding) as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    site_code = row["site_code"].strip()
                    plot_number = int(row["plot_number"])
                    plot_name = row["plot_name"].strip()

                    if site_code not in plot_names:
                        plot_names[site_code] = [None, None, None, None]

                    if 1 <= plot_number <= 4 and plot_name:
                        plot_names[site_code][plot_number - 1] = plot_name
            return plot_names
        except UnicodeDecodeError:
            plot_names = {}

    return plot_names


PLOT_NAMES = load_plot_names()


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def load_box_client() -> BoxClient:
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"Token file not found: {TOKEN_FILE}")
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")

    with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
        config_data = json.load(handle)

    box_config = config_data.get("box", config_data)

    class SimpleTokenStorage:
        def __init__(self, token_file_path: Path):
            self.token_file = token_file_path

        def store(self, token) -> None:
            with open(self.token_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "access_token": token.access_token,
                        "refresh_token": token.refresh_token,
                    },
                    handle,
                    indent=2,
                )

        def get(self):
            try:
                from box_sdk_gen import AccessToken

                with open(self.token_file, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                return AccessToken(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                )
            except Exception:
                return None

        def clear(self) -> None:
            if self.token_file.exists():
                self.token_file.unlink()

    oauth_config = OAuthConfig(
        client_id=box_config["client_id"],
        client_secret=box_config["client_secret"],
        token_storage=SimpleTokenStorage(TOKEN_FILE),
    )
    return BoxClient(BoxOAuth(oauth_config))


def classify_file(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in CONFIG_EXTENSIONS:
        return "config"
    return "other"


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ratio_to_float(value) -> float:
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        if value.denominator == 0:
            return 0.0
        return float(value.numerator) / float(value.denominator)
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        if denominator == 0:
            return 0.0
        return float(numerator) / float(denominator)
    return float(value)


def _dms_to_decimal(dms, ref) -> str:
    if not dms or not ref:
        return "NA"
    try:
        degrees = _ratio_to_float(dms[0])
        minutes = _ratio_to_float(dms[1])
        seconds = _ratio_to_float(dms[2])
        decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
        if ref in ("S", "W"):
            decimal = -decimal
        return f"{decimal:.6f}"
    except Exception:
        return "NA"


def extract_exif(path: Path) -> tuple[dict[str, str], str | None]:
    result = {
        "exif_datetime": "NA",
        "exif_make": "NA",
        "exif_model": "NA",
        "latitude": "NA",
        "longitude": "NA",
    }

    try:
        with Image.open(path) as image:
            if not hasattr(image, "_getexif"):
                return result, None

            raw_exif = image._getexif()
            if not raw_exif:
                return result, None

            tag_map = {TAGS.get(tag_id, tag_id): value for tag_id, value in raw_exif.items()}

            for field_name, tag_name in (
                ("exif_make", "Make"),
                ("exif_model", "Model"),
            ):
                value = tag_map.get(tag_name)
                if value not in (None, ""):
                    result[field_name] = str(value).strip()

            datetime_value = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
            if datetime_value not in (None, ""):
                result["exif_datetime"] = str(datetime_value).strip()

            gps_info = tag_map.get("GPSInfo")
            if gps_info:
                gps_tags = {GPSTAGS.get(tag_id, tag_id): value for tag_id, value in gps_info.items()}
                result["latitude"] = _dms_to_decimal(
                    gps_tags.get("GPSLatitude"), gps_tags.get("GPSLatitudeRef")
                )
                result["longitude"] = _dms_to_decimal(
                    gps_tags.get("GPSLongitude"), gps_tags.get("GPSLongitudeRef")
                )

            return result, None
    except Exception as exc:
        return result, str(exc)


def list_folder_items(client: BoxClient, folder_id: str) -> list:
    items = []
    marker = None
    while True:
        response = client.folders.get_folder_items(
            folder_id,
            fields=["id", "name", "type", "size", "modified_at"],
            usemarker=True,
            marker=marker,
            limit=1000,
        )
        items.extend(response.entries)
        marker = getattr(response, "next_marker", None)
        if not marker:
            break
    return items


def get_folder_info(client: BoxClient, folder_id: str):
    return client.folders.get_folder_by_id(folder_id, fields=["id", "name", "path_collection"])


def iso_or_na(value: str | None) -> str:
    if not value:
        return "NA"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value


def load_json_file(path: Path) -> tuple[dict | None, str | None]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, None
    except Exception as exc:
        return None, str(exc)


def infer_reserve_name(folder_info) -> str:
    path_collection = getattr(folder_info, "path_collection", None)
    if not path_collection:
        return "NA"

    entries = getattr(path_collection, "entries", None) or []
    if len(entries) >= 1:
        return getattr(entries[-1], "name", None) or "NA"
    return "NA"


def infer_deployment_info(
    deployment_folder_name: str, deployment_metadata: dict | None, folder_info
) -> dict:
    if isinstance(deployment_metadata, dict):
        return {
            "organization": deployment_metadata.get("organization", "NA"),
            "reserve_name": deployment_metadata.get("reserve_name", "NA"),
            "site": deployment_metadata.get("site", "NA"),
            "deployment_start": deployment_metadata.get("deployment_start", "NA"),
            "deployment_end": deployment_metadata.get("deployment_end", "NA"),
            "observer": deployment_metadata.get("observer", "NA"),
        }

    match = DEPLOYMENT_FOLDER_RE.match(deployment_folder_name)
    deployment_end = "NA"
    organization = "NA"
    site = "NA"
    if match:
        organization = match.group("organization")
        site = match.group("site")
        raw_end = match.group("deployment_end")
        deployment_end = f"{raw_end[0:4]}-{raw_end[4:6]}-{raw_end[6:8]}"

    return {
        "organization": organization,
        "reserve_name": infer_reserve_name(folder_info),
        "site": site,
        "deployment_start": "NA",
        "deployment_end": deployment_end,
        "observer": "NA",
    }


def build_device_context(
    manifest_data: dict | None, deployment_info: dict
) -> dict[tuple[str, str], dict[str, str]]:
    context: dict[tuple[str, str], dict[str, str]] = {}

    if isinstance(manifest_data, dict):
        for device in manifest_data.get("devices", []):
            plot_number = str(device.get("plot_number", "NA"))
            device_type = device.get("device_type", "NA")
            context[(plot_number, device_type)] = {
                "plot_number": plot_number,
                "plot_label": str(device.get("plot_label", "NA")),
                "device_type": device_type,
                "device_label": str(device.get("device_label", "NA")),
            }

    site_code = deployment_info.get("site", "NA")
    plot_names = PLOT_NAMES.get(site_code)
    for plot_number in range(1, 5):
        for device_type in DEVICE_TYPES:
            key = (str(plot_number), device_type)
            if key in context:
                continue
            plot_label = str(plot_number)
            if plot_names and len(plot_names) >= plot_number and plot_names[plot_number - 1]:
                plot_label = plot_names[plot_number - 1]
            context[key] = {
                "plot_number": str(plot_number),
                "plot_label": plot_label,
                "device_type": device_type,
                "device_label": f"p{plot_number}_{device_type}",
            }

    return context


def context_from_device_folder(relative_path: Path) -> tuple[str | None, str | None]:
    if len(relative_path.parts) < 3 or relative_path.parts[0] != "raw_data":
        return None, None
    match = DEVICE_FOLDER_RE.match(relative_path.parts[1])
    if not match:
        return None, None
    return match.group("plot_number"), match.group("device_type")


def parse_filename(filename: str) -> dict[str, str]:
    stem = Path(filename).stem
    media_match = MEDIA_RE.match(stem)
    if media_match:
        return {
            "organization": media_match.group("organization"),
            "site": media_match.group("site"),
            "plot_number": media_match.group("plot_number"),
            "device_type": media_match.group("device_type"),
        }

    config_match = CONFIG_RE.match(stem)
    if config_match:
        return {
            "organization": config_match.group("organization"),
            "site": config_match.group("site"),
            "plot_number": "NA",
            "device_type": config_match.group("device_type"),
        }

    return {}


def download_box_tree(
    client: BoxClient,
    folder_id: str,
    local_root: Path,
    report: dict,
    relative_dir: Path = Path(),
) -> list[dict]:
    downloaded_files: list[dict] = []
    items = list_folder_items(client, folder_id)

    for item in items:
        item_type = getattr(item, "type", None)
        item_name = getattr(item, "name", None)
        item_id = getattr(item, "id", None)
        item_relative_path = relative_dir / item_name

        if item_type == "folder":
            (local_root / item_relative_path).mkdir(parents=True, exist_ok=True)
            downloaded_files.extend(
                download_box_tree(client, item_id, local_root, report, item_relative_path)
            )
            continue

        if item_type != "file":
            continue

        local_path = local_root / item_relative_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        log(f"Downloading {item_relative_path.as_posix()}")

        try:
            with open(local_path, "wb") as handle:
                client.downloads.download_file_to_output_stream(item_id, handle)
            downloaded_files.append(
                {
                    "id": item_id,
                    "name": item_name,
                    "relative_path": item_relative_path,
                    "local_path": local_path,
                    "size": getattr(item, "size", None),
                    "modified_at": getattr(item, "modified_at", None),
                }
            )
        except Exception as exc:
            report["problems"].append(
                {
                    "path": item_relative_path.as_posix(),
                    "reason": "download_failed",
                    "detail": str(exc),
                }
            )
            report["status"] = "failed"

    return downloaded_files


def build_row(
    file_info: dict,
    device_context: dict[tuple[str, str], dict[str, str]],
    deployment_info: dict,
    report: dict,
) -> dict[str, str] | None:
    relative_path: Path = file_info["relative_path"]
    local_path: Path = file_info["local_path"]
    filename = file_info["name"]

    log(f"Processing {relative_path.as_posix()}")

    row = {field: "NA" for field in FIELDNAMES}
    row["new_filename"] = filename
    row["file_type"] = classify_file(filename)
    row["file_size_bytes"] = str(local_path.stat().st_size)
    row["timestamp"] = iso_or_na(file_info.get("modified_at"))

    try:
        row["file_hash_sha256"] = sha256_of_file(local_path)
    except Exception as exc:
        report["problems"].append(
            {
                "path": relative_path.as_posix(),
                "reason": "hash_failed",
                "detail": str(exc),
            }
        )
        report["status"] = "failed"
        return None

    if row["file_type"] == "image":
        exif_fields, exif_error = extract_exif(local_path)
        row.update(exif_fields)
        if exif_error:
            report["problems"].append(
                {
                    "path": relative_path.as_posix(),
                    "reason": "exif_failed",
                    "detail": exif_error,
                }
            )
            report["status"] = "failed"

    parsed = parse_filename(filename)
    folder_plot_number, folder_device_type = context_from_device_folder(relative_path)

    plot_number = folder_plot_number or parsed.get("plot_number")
    device_type = folder_device_type or parsed.get("device_type")

    if plot_number and plot_number != "NA":
        row["plot_number"] = str(plot_number)
    if device_type:
        row["device_type"] = device_type

    if plot_number and plot_number != "NA" and device_type:
        context = device_context.get((str(plot_number), device_type))
        if context:
            row["plot_label"] = context["plot_label"]
            row["device_label"] = context["device_label"]

    if row["plot_number"] == "NA" and row["file_type"] != "config":
        report["problems"].append(
            {
                "path": relative_path.as_posix(),
                "reason": "filename_parse_failed",
                "detail": "Could not determine plot number from filename or folder path.",
            }
        )
        report["status"] = "failed"

    if row["device_type"] == "NA":
        report["problems"].append(
            {
                "path": relative_path.as_posix(),
                "reason": "filename_parse_failed",
                "detail": "Could not determine device type from filename or folder path.",
            }
        )
        report["status"] = "failed"

    if row["plot_label"] == "NA" and row["plot_number"] != "NA":
        report["problems"].append(
            {
                "path": relative_path.as_posix(),
                "reason": "field_set_to_NA",
                "detail": "plot_label could not be recovered.",
            }
        )
        report["status"] = "failed"

    if row["device_label"] == "NA" and row["device_type"] != "NA":
        report["problems"].append(
            {
                "path": relative_path.as_posix(),
                "reason": "field_set_to_NA",
                "detail": "device_label could not be recovered.",
            }
        )
        report["status"] = "failed"

    if parsed:
        if deployment_info.get("organization") == "NA" and parsed.get("organization"):
            deployment_info["organization"] = parsed["organization"]
        if deployment_info.get("site") == "NA" and parsed.get("site"):
            deployment_info["site"] = parsed["site"]

    return row


def sort_devices(devices: list[dict]) -> list[dict]:
    def key_fn(device: dict):
        plot_number = device.get("plot_number", "999")
        try:
            plot_sort = int(plot_number)
        except ValueError:
            plot_sort = 999
        return (
            plot_sort,
            DEVICE_ORDER.get(device.get("device_type"), 999),
            device.get("device_label", ""),
        )

    return sorted(devices, key=key_fn)


def build_manifest(
    deployment_info: dict, rows: list[dict[str, str]], manifest_data: dict | None
) -> dict:
    if isinstance(manifest_data, dict) and isinstance(manifest_data.get("devices"), list):
        devices = manifest_data["devices"]
    else:
        seen = set()
        devices = []
        for row in rows:
            if row["plot_number"] == "NA" or row["device_type"] == "NA" or row["device_label"] == "NA":
                continue
            key = (row["plot_number"], row["device_type"], row["device_label"])
            if key in seen:
                continue
            seen.add(key)
            devices.append(
                {
                    "plot_number": row["plot_number"],
                    "plot_label": row["plot_label"],
                    "device_type": row["device_type"],
                    "device_label": row["device_label"],
                }
            )

    return {
        "deployment_info": deployment_info,
        "devices": sort_devices(devices),
        "file_count": len(rows),
        "generated": datetime.now().astimezone().isoformat(),
        "version": APP_VERSION,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def summarize_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = {"image": 0, "audio": 0, "config": 0, "other": 0}
    for row in rows:
        counts[row["file_type"]] = counts.get(row["file_type"], 0) + 1
    return counts


def main() -> int:
    args = parse_args()

    if RECOVERY_ROOT.exists() is False:
        raise FileNotFoundError(f"Recovery root does not exist: {RECOVERY_ROOT}")

    report = {
        "status": "success",
        "box_folder_id": args.box_folder_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "recovery_root": str(RECOVERY_ROOT),
        "outputs": {},
        "counts": {},
        "problems": [],
        "notes": {
            "always_na_fields": ["original_filename", "source_path"],
            "timestamp_source": "box_modified_time",
        },
    }

    try:
        log("Authenticating with Box")
        client = load_box_client()
        user = client.users.get_user_me()
        log(f"Connected as {user.name} ({user.login})")

        folder_info = get_folder_info(client, args.box_folder_id)
        deployment_folder_name = folder_info.name
        local_deployment_root = RECOVERY_ROOT / deployment_folder_name
        report["outputs"]["deployment_root"] = str(local_deployment_root)

        if local_deployment_root.exists():
            raise FileExistsError(
                f"Recovery folder already exists: {local_deployment_root}. "
                "Delete it manually before rerunning."
            )

        log(f"Creating recovery folder {local_deployment_root}")
        local_deployment_root.mkdir(parents=True, exist_ok=False)

        log(f"Downloading deployment folder {deployment_folder_name}")
        downloaded_files = download_box_tree(client, args.box_folder_id, local_deployment_root, report)

        attempted_download_count = len(downloaded_files) + sum(
            1 for problem in report["problems"] if problem["reason"] == "download_failed"
        )
        actual_download_count = sum(1 for path in local_deployment_root.rglob("*") if path.is_file())

        if actual_download_count != len(downloaded_files):
            report["problems"].append(
                {
                    "path": local_deployment_root.as_posix(),
                    "reason": "download_count_mismatch",
                    "detail": (
                        f"Expected {len(downloaded_files)} downloaded files on disk, "
                        f"found {actual_download_count}."
                    ),
                }
            )
            report["status"] = "failed"

        record_path = local_deployment_root / "deployment_event_record.json"
        existing_record, record_error = load_json_file(record_path)

        if record_error:
            report["problems"].append(
                {
                    "path": record_path.as_posix(),
                    "reason": "metadata_load_failed",
                    "detail": record_error,
                }
            )
            report["status"] = "failed"

        deployment_metadata = (existing_record or {}).get("deployment_info")
        deployment_info = infer_deployment_info(
            deployment_folder_name, deployment_metadata, folder_info
        )
        device_context = build_device_context(existing_record, deployment_info)

        rows = []
        non_metadata_files = [f for f in downloaded_files if f["name"] not in METADATA_FILENAMES]
        for file_info in non_metadata_files:
            row = build_row(file_info, device_context, deployment_info, report)
            if row is not None:
                rows.append(row)

        if len(rows) != len(non_metadata_files):
            report["problems"].append(
                {
                    "path": local_deployment_root.as_posix(),
                    "reason": "row_count_mismatch",
                    "detail": (
                        f"Recovered {len(rows)} rows from {len(non_metadata_files)} non-metadata files."
                    ),
                }
            )
            report["status"] = "failed"

        recovered_manifest = build_manifest(deployment_info, rows, existing_manifest)

        output_csv = local_deployment_root / "file_metadata.csv"
        output_manifest = local_deployment_root / "deployment_event_record.json"
        output_report = local_deployment_root / "recovery_report.json"

        log(f"Writing {output_csv.name}")
        write_csv(output_csv, rows)

        log(f"Writing {output_manifest.name}")
        with open(output_manifest, "w", encoding="utf-8") as handle:
            json.dump(recovered_manifest, handle, indent=2)

        report["completed_at"] = datetime.now().astimezone().isoformat()
        report["outputs"] = {
            "deployment_root": str(local_deployment_root),
            "file_metadata_csv": str(output_csv),
            "manifest_json": str(output_manifest),
            "recovery_report_json": str(output_report),
        }
        report["counts"] = {
            "box_files_downloaded": len(downloaded_files),
            "box_files_attempted": attempted_download_count,
            "non_metadata_files": len(non_metadata_files),
            "csv_rows_written": len(rows),
            "file_types": summarize_counts(rows),
        }

        log(f"Writing {output_report.name}")
        with open(output_report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)

        if report["status"] == "failed":
            log("Recovery completed with failures. Review recovery_report.json.")
            return 1

        log("Recovery completed successfully.")
        return 0

    except Exception as exc:
        report["status"] = "failed"
        report["completed_at"] = datetime.now().astimezone().isoformat()
        report["problems"].append(
            {
                "path": args.box_folder_id,
                "reason": "fatal_error",
                "detail": str(exc),
            }
        )

        deployment_root = report["outputs"].get("deployment_root")
        if deployment_root:
            report_path = Path(deployment_root) / "recovery_report.json"
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)

        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
