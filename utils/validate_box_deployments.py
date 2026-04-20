#!/usr/bin/env python3
"""
Validate CASSN deployment metadata on Box.

Checks for each deployment under a given root directory:
  1. Required files/folders present, no stale old-format files
  2. file_metadata.csv has the correct schema (no source_path, etc.)
  3. deployment_event_record.json is valid and has required keys
  4. JSON file_count matches CSV row count
  5. CSV new_filename values match actual files in raw_data/
"""

import sys
import csv
import json
from pathlib import Path

BOX_ROOT = Path(
    "/Users/johnimperato/Library/CloudStorage/Box-Box/CASSN/field_data/2026"
)

REQUIRED_FILES = {"deployment_event_record.json", "file_metadata.csv"}
REQUIRED_DIRS = {"raw_data", "WI_metadata"}
STALE_FILES = {"manifest.json", "deployment_metadata.json"}

EXPECTED_CSV_COLUMNS = {
    "new_filename", "original_filename", "plot_number", "plot_label",
    "device_type", "device_id", "file_type", "file_size_bytes",
    "file_hash_sha256", "recorded_datetime", "latitude", "longitude",
    "camera_make", "camera_model", "sequence_trigger_type",
    "sequence_event_num", "sequence_position", "sequence_total",
}

REQUIRED_JSON_KEYS = {"deployment_info", "devices", "file_count", "generated", "version"}

SKIP_NAMES = {"_migration_backup", "WI_metadata", "session.json"}


def is_media_file(path: Path) -> bool:
    """True for files that should appear as rows in file_metadata.csv."""
    name = path.name
    if name.startswith(".") or name.startswith("._"):
        return False
    return True


def collect_raw_data_files(raw_data_dir: Path) -> set[str]:
    """Return set of filenames (not paths) of all uploadable files under raw_data/."""
    result = set()
    for f in raw_data_dir.rglob("*"):
        if f.is_file() and is_media_file(f):
            result.add(f.name)
    return result


def validate_deployment(deploy_dir: Path) -> list[str]:
    """Run all checks on a single deployment folder. Returns list of issue strings."""
    issues = []
    name = deploy_dir.name

    # Check 1: required files and directories
    for fname in REQUIRED_FILES:
        if not (deploy_dir / fname).exists():
            issues.append(f"MISSING FILE: {fname}")
    for dname in REQUIRED_DIRS:
        if not (deploy_dir / dname).is_dir():
            issues.append(f"MISSING DIR: {dname}/")

    # Check 1b: stale old-format files
    for fname in STALE_FILES:
        if (deploy_dir / fname).exists():
            issues.append(f"STALE FILE PRESENT: {fname} (should have been renamed/removed)")

    # Check 1c: migration backup folder present (informational)
    if (deploy_dir / "_migration_backup").exists():
        issues.append("INFO: _migration_backup/ folder present (can be removed after verification)")

    # Check 2: CSV schema
    csv_path = deploy_dir / "file_metadata.csv"
    csv_rows = []
    if csv_path.exists():
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                actual_cols = set(reader.fieldnames or [])
                csv_rows = list(reader)

            missing_cols = EXPECTED_CSV_COLUMNS - actual_cols
            extra_cols = actual_cols - EXPECTED_CSV_COLUMNS
            if missing_cols:
                issues.append(f"CSV MISSING COLUMNS: {sorted(missing_cols)}")
            if extra_cols:
                issues.append(f"CSV EXTRA/UNEXPECTED COLUMNS: {sorted(extra_cols)}")

        except Exception as e:
            issues.append(f"CSV READ ERROR: {e}")

    # Check 3 + 4: JSON schema and file_count
    json_path = deploy_dir / "deployment_event_record.json"
    json_file_count = None
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                record = json.load(f)

            missing_keys = REQUIRED_JSON_KEYS - set(record.keys())
            if missing_keys:
                issues.append(f"JSON MISSING KEYS: {sorted(missing_keys)}")

            json_file_count = record.get("file_count")
            csv_row_count = len(csv_rows)
            if json_file_count is not None and json_file_count != csv_row_count:
                issues.append(
                    f"FILE COUNT MISMATCH: JSON says {json_file_count}, "
                    f"CSV has {csv_row_count} rows"
                )

        except json.JSONDecodeError as e:
            issues.append(f"JSON PARSE ERROR: {e}")
        except Exception as e:
            issues.append(f"JSON READ ERROR: {e}")

    # Check 5: CSV ↔ raw_data cross-reference
    raw_data_dir = deploy_dir / "raw_data"
    if raw_data_dir.is_dir() and csv_rows:
        csv_filenames = {row["new_filename"] for row in csv_rows if row.get("new_filename")}
        disk_filenames = collect_raw_data_files(raw_data_dir)

        in_csv_not_on_disk = csv_filenames - disk_filenames
        on_disk_not_in_csv = disk_filenames - csv_filenames

        if in_csv_not_on_disk:
            issues.append(
                f"IN CSV BUT MISSING ON DISK ({len(in_csv_not_on_disk)} files): "
                + ", ".join(sorted(in_csv_not_on_disk)[:10])
                + (" ..." if len(in_csv_not_on_disk) > 10 else "")
            )
        if on_disk_not_in_csv:
            issues.append(
                f"ON DISK BUT MISSING FROM CSV ({len(on_disk_not_in_csv)} files): "
                + ", ".join(sorted(on_disk_not_in_csv)[:10])
                + (" ..." if len(on_disk_not_in_csv) > 10 else "")
            )

    return issues


def main():
    if not BOX_ROOT.exists():
        print(f"ERROR: Box root not found: {BOX_ROOT}")
        sys.exit(1)

    # Find all deployment folders (depth 2: reserve/deployment)
    deployments = sorted(
        d for reserve in BOX_ROOT.iterdir() if reserve.is_dir()
        for d in reserve.iterdir() if d.is_dir()
    )

    if not deployments:
        print("No deployment folders found.")
        sys.exit(1)

    print(f"Found {len(deployments)} deployment(s) under {BOX_ROOT}\n")
    print("=" * 70)

    total_issues = 0
    for deploy_dir in deployments:
        reserve = deploy_dir.parent.name
        print(f"\n[{reserve}]  {deploy_dir.name}")
        print("-" * 70)
        issues = validate_deployment(deploy_dir)
        if not issues:
            print("  OK — all checks passed")
        else:
            for issue in issues:
                tag = "  INFO" if issue.startswith("INFO") else "  FAIL"
                print(f"{tag}: {issue}")
            total_issues += sum(1 for i in issues if not i.startswith("INFO"))

    print("\n" + "=" * 70)
    if total_issues == 0:
        print("RESULT: All deployments passed validation.")
    else:
        print(f"RESULT: {total_issues} issue(s) found across {len(deployments)} deployment(s).")
    print("=" * 70)


if __name__ == "__main__":
    main()
