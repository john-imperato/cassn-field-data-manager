#!/usr/bin/env python3
"""
Verify FLAC conversion completeness by comparing WAV counts in source _BD folders
against FLAC counts in staging deployment_id folders.

Read-only — never modifies any files.

Usage:
    python utils/verify_flac_conversion.py \
        --staging "/Volumes/G-DRIVE ArmorATD/soundhub_staging/UCNature_CASSN" \
        --sources "/Volumes/G-DRIVE ArmorATD/2026" \
                  "/Users/johnimperato/Library/CloudStorage/Box-Box/CASSN/field_data/2026"
"""

import argparse
from pathlib import Path


def find_source_bd_folder(deployment_id: str, source_roots: list[Path]) -> Path | None:
    """
    Locate the source _BD folder for a deployment_id across multiple source roots.
    Tries both with and without a raw_data/ intermediate directory to handle
    sites where the folder structure varies (e.g. Angelo has no raw_data/).
    """
    tokens = deployment_id.split("_")
    date = tokens[-1]
    device = tokens[-2]
    plot_short = "p" + tokens[-3].replace("plot", "")
    site = "_".join(tokens[:-3])
    deployment_folder = f"UC_{site}_{date}"
    bd_folder_name = f"{plot_short}_{device}"
    for root in source_roots:
        for uc_dir in root.rglob(deployment_folder):
            if not uc_dir.is_dir():
                continue
            for subpath in [uc_dir / "raw_data" / bd_folder_name, uc_dir / bd_folder_name]:
                if subpath.exists():
                    return subpath
    return None


def main():
    parser = argparse.ArgumentParser(description="Verify WAV→FLAC conversion completeness (read-only).")
    parser.add_argument("--staging", required=True, help="SoundHub staging directory (UCNature_CASSN/)")
    parser.add_argument("--sources", nargs="+", required=True, help="Source root directories to search for _BD folders")
    args = parser.parse_args()

    staging_root = Path(args.staging)
    source_roots = [Path(s) for s in args.sources]

    if not staging_root.exists():
        print(f"ERROR: Staging directory not found: {staging_root}")
        return

    deployment_folders = sorted([d for d in staging_root.iterdir() if d.is_dir()])
    if not deployment_folders:
        print("No deployment folders found in staging directory.")
        return

    print(f"{'Deployment ID':<40} {'Source WAVs':>11} {'Staged FLACs':>12} {'Status':>10}")
    print("-" * 78)

    all_ok = True
    for dep_folder in deployment_folders:
        flac_count = len(list(dep_folder.glob("*.flac")))
        source_bd = find_source_bd_folder(dep_folder.name, source_roots)

        if source_bd is None:
            print(f"{dep_folder.name:<40} {'N/A':>11} {flac_count:>12}  ⚠️  source not found")
            all_ok = False
        else:
            wav_count = len(list(source_bd.glob("*.wav")))
            status = "✅ OK" if flac_count == wav_count else f"❌ MISMATCH"
            if flac_count != wav_count:
                all_ok = False
            print(f"{dep_folder.name:<40} {wav_count:>11} {flac_count:>12}  {status}")

    print("-" * 78)
    if all_ok:
        print("All staged deployments match their sources.")
    else:
        print("Some deployments have mismatches — review above.")


if __name__ == "__main__":
    main()
