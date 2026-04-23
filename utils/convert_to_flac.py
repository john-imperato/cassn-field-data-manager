#!/usr/bin/env python3
"""
Convert WAV files in _BD folders to FLAC for SoundHub upload.

Usage:
    python utils/convert_to_flac.py \
        --source "/Volumes/G-DRIVE ArmorATD/2026" \
        --output "/Volumes/G-DRIVE ArmorATD/soundhub_staging/UCNature_CASSN"

Derives deployment_id from folder names:
  UC_QuailRidge_20260108/raw_data/p1_BD → QuailRidge_plot1_BD_20260108

Only processes _BD folders containing at least one .wav file.
Source WAVs are never modified. Skips files already converted (idempotent).
"""

import argparse
import subprocess
import sys
from pathlib import Path


def deployment_id_from_path(bd_folder: Path) -> str:
    """
    Derive SoundHub deployment_id from folder path.

    Expects structure: <anything>/<UC_Site_YYYYMMDD>/.../<pN_BD>
    Returns: Site_plotN_BD_YYYYMMDD
    """
    # Find the deployment folder (UC_Site_YYYYMMDD) by walking up until we find
    # a folder whose name matches the UC_<site>_<date> pattern
    parts = bd_folder.parts
    deployment_folder = None
    for part in parts:
        tokens = part.split("_")
        if len(tokens) >= 3 and tokens[0] == "UC" and tokens[-1].isdigit() and len(tokens[-1]) == 8:
            deployment_folder = part
            date = tokens[-1]
            site = "_".join(tokens[1:-1])

    if deployment_folder is None:
        raise ValueError(f"Could not find UC_<Site>_<YYYYMMDD> folder in path: {bd_folder}")

    # Parse plot folder: p1_BD → plot1, BD
    plot_part, device = bd_folder.name.split("_", 1)
    plot = "plot" + plot_part[1:]  # p1 → plot1

    return f"{site}_{plot}_{device}_{date}"


def find_bd_folders(source_root: Path) -> list[Path]:
    candidates = [source_root] + [p for p in source_root.rglob("*") if p.is_dir()]
    return [
        p for p in candidates
        if p.name.endswith("_BD") and any(p.glob("*.wav"))
    ]


def convert_folder(bd_folder: Path, output_root: Path) -> tuple[int, int]:
    deployment_id = deployment_id_from_path(bd_folder)
    out_folder = output_root / deployment_id
    out_folder.mkdir(parents=True, exist_ok=True)

    converted = 0
    skipped = 0

    for wav in sorted(bd_folder.glob("*.wav")):
        flac_out = out_folder / (wav.stem + ".flac")
        if flac_out.exists():
            print(f"  SKIP (exists): {flac_out.name}")
            skipped += 1
            continue
        print(f"  Converting: {wav.name} → {flac_out.name}")
        result = subprocess.run(
            ["flac", "--silent", "--output-name", str(flac_out), str(wav)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr.strip()}", file=sys.stderr)
        else:
            converted += 1

    return converted, skipped


def main():
    parser = argparse.ArgumentParser(description="Convert WAVs in _BD folders to FLAC for SoundHub.")
    parser.add_argument("--source", required=True, help="Root directory to scan for _BD folders")
    parser.add_argument("--output", required=True, help="SoundHub project staging directory (e.g. .../UCNature_CASSN)")
    args = parser.parse_args()

    source_root = Path(args.source)
    output_root = Path(args.output)

    if not source_root.exists():
        print(f"ERROR: Source path does not exist: {source_root}", file=sys.stderr)
        sys.exit(1)

    bd_folders = find_bd_folders(source_root)
    if not bd_folders:
        print(f"No _BD folders with WAV files found under: {source_root}")
        sys.exit(0)

    print(f"Found {len(bd_folders)} _BD folder(s) with WAV files under: {source_root}")
    print(f"Output staging: {output_root}\n")

    total_converted = total_skipped = 0
    for folder in bd_folders:
        deployment_id = deployment_id_from_path(folder)
        print(f"[{folder.name}] → [{deployment_id}]")
        c, s = convert_folder(folder, output_root)
        total_converted += c
        total_skipped += s

    print(f"\nDone. Converted: {total_converted}  Skipped (already exist): {total_skipped}")


if __name__ == "__main__":
    main()
