#!/usr/bin/env python3
"""
Automated Google Drive Sync for AlecaFrame Markdown Sources
Before copying new files:
1. Moves previous files in G:\\Mi unidad\\WF_DATA\\ directly to G:\\Mi unidad\\WF_DATA\\OLD\\ (replacing existing backups).
2. Copies the new generated .md files directly into G:\\Mi unidad\\WF_DATA\\ (flat, no subfolders)
so Google Gemini NotebookLM can ingest the latest information directly from Google Drive.
Supports --dry-run to preview archiving and copying without touching any files.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DRIVE_DIR = Path(r"G:\Mi unidad\WF_DATA")


def get_drive_directory(custom_path: Path | str | None = None) -> Path:
    """Resolve the target Google Drive directory."""
    if custom_path:
        return Path(custom_path).resolve()
    return DEFAULT_DRIVE_DIR


def get_markdown_sources(source_dir: Path) -> list[Path]:
    """Find all Markdown sources in source_dir, plus combined.md if present."""
    if not source_dir.exists():
        return []
    sources: dict[str, Path] = {}
    for p in source_dir.glob("*.md"):
        sources[p.name.lower()] = p
    root_combined = source_dir.parent / "combined.md"
    if "combined.md" not in sources and root_combined.exists() and root_combined.is_file():
        sources["combined.md"] = root_combined
    return sorted(list(sources.values()), key=lambda p: p.name.casefold())


def sync_to_drive(
    source_dir: Path,
    drive_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> tuple[list[Path], list[Path]]:
    """
    Archive previous files to OLD/ and copy new generated Markdown files directly to Google Drive.

    Args:
        source_dir: Directory containing generated .md files (e.g. notebook_sources/)
        drive_dir: Target Google Drive folder (default: G:\\Mi unidad\\WF_DATA)
        dry_run: If True, preview what would be archived and copied without writing
        verbose: If True, print status and summary to sys.stderr

    Returns:
        tuple of (moved_to_old_files, copied_new_files)
    """
    target_drive = get_drive_directory(drive_dir)
    old_dir = target_drive / "OLD"

    if not source_dir.exists():
        if verbose:
            print(f"[!] Warning: Source directory '{source_dir}' does not exist.", file=sys.stderr)
        return [], []

    sources = get_markdown_sources(source_dir)
    if not sources:
        if verbose:
            print(f"[!] Warning: No .md files found in '{source_dir}'.", file=sys.stderr)
        return [], []

    # Check if Google Drive directory is accessible
    if not target_drive.exists():
        if dry_run:
            if verbose:
                print(f"[DRY RUN] Target drive folder '{target_drive}' does not exist yet (would be created).", file=sys.stderr)
        else:
            try:
                target_drive.mkdir(parents=True, exist_ok=True)
                if verbose:
                    print(f"[*] Created target Google Drive directory: {target_drive}", file=sys.stderr)
            except Exception as e:
                if verbose:
                    print(
                        f"[!] Error: Could not access or create Google Drive directory '{target_drive}'. "
                        f"Make sure Google Drive is running and drive G: is mounted. Error: {e}",
                        file=sys.stderr,
                    )
                return [], []

    # 1. Identify previous files in target_drive to move to OLD/
    incoming_names = {s.name.lower() for s in sources}
    previous_files_to_move: list[Path] = []

    for f in target_drive.iterdir():
        # Do not move directories (like OLD itself)
        if f.is_file() and (f.suffix.lower() == ".md" or f.name.lower() in incoming_names):
            previous_files_to_move.append(f)

    previous_files_to_move.sort(key=lambda p: p.name.casefold())

    timestamp = datetime.now().strftime("%H:%M:%S")
    utc_timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_UTC")
    subfolder_name = f"OLD_DATA_{utc_timestamp_str}"
    target_archive_subfolder = old_dir / subfolder_name

    # 2. Dry run simulation
    if dry_run:
        if verbose:
            print(f"\n[DRY RUN] Google Drive Archive & Copy Simulation ({timestamp}):", file=sys.stderr)
            print(f"Target Active Folder: {target_drive} (Flat structure)", file=sys.stderr)
            print(f"Archive Folder:       {target_archive_subfolder} (Timestamped subfolder)", file=sys.stderr)

            if previous_files_to_move:
                print(f"\n[DRY RUN] Step 1: Would move {len(previous_files_to_move)} previous file(s) to OLD/{subfolder_name}/:", file=sys.stderr)
                for f in previous_files_to_move:
                    print(f"  * {f.name} -> OLD/{subfolder_name}/{f.name}", file=sys.stderr)
            else:
                print(f"\n[DRY RUN] Step 1: No previous files in active folder to move to OLD/{subfolder_name}/.", file=sys.stderr)

            print(f"\n[DRY RUN] Step 2: Would copy {len(sources)} new generated Markdown source(s) to WF_DATA/:", file=sys.stderr)
            for s in sources:
                size_kb = round(s.stat().st_size / 1024, 1)
                print(f"  * {s.name} ({size_kb} KB)", file=sys.stderr)

        return previous_files_to_move, sources

    # 3. Execution: Step 1 - Move previous files to OLD/OLD_DATA_{TIME_STAMP_UTC}/
    moved_files: list[Path] = []
    if previous_files_to_move:
        try:
            target_archive_subfolder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            if verbose:
                print(f"[!] Warning: Could not create archive folder '{target_archive_subfolder}': {e}", file=sys.stderr)

        for prev_f in previous_files_to_move:
            dest_in_old = target_archive_subfolder / prev_f.name
            try:
                if dest_in_old.exists():
                    dest_in_old.unlink()
                shutil.move(str(prev_f), str(dest_in_old))
                moved_files.append(prev_f)
            except Exception as move_err:
                if verbose:
                    print(f"[!] Warning moving {prev_f.name} to OLD/{subfolder_name}/: {move_err}", file=sys.stderr)

        if verbose and moved_files:
            print(f"[{timestamp}] Moved {len(moved_files)} previous file(s) to 'OLD/{subfolder_name}/'.", file=sys.stderr)

    # 4. Execution: Step 2 - Copy newly generated files to target_drive
    copied_files: list[Path] = []
    for src in sources:
        dst = target_drive / src.name
        try:
            shutil.copy2(src, dst)
            copied_files.append(dst)
        except Exception as copy_err:
            if verbose:
                print(f"[!] Error copying {src.name} to {dst}: {copy_err}", file=sys.stderr)

    if verbose:
        print(f"[OK] Successfully copied {len(copied_files)} new generated Markdown source(s) directly into '{target_drive}'.", file=sys.stderr)
        print("     Gemini NotebookLM can now ingest/refresh the latest information from your Drive account.", file=sys.stderr)

    # Sync scripts into SCRIPTS/ (and archive previous to SCRIPTS/OLD/)
    workspace_root = source_dir.parent if source_dir.name == "notebook_sources" else source_dir
    sync_scripts_to_drive(
        workspace_dir=workspace_root,
        drive_dir=target_drive,
        dry_run=dry_run,
        verbose=verbose,
    )

    return moved_files, copied_files


def sync_scripts_to_drive(
    workspace_dir: Path,
    drive_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> tuple[list[Path], list[Path]]:
    """
    Sync Python scripts (.py) from workspace_dir to G:\\Mi unidad\\WF_DATA\\SCRIPTS\\.
    Before copying an updated script:
    1. If a previous version exists in SCRIPTS/, moves it to SCRIPTS\\OLD\\ (replacing any existing old file).
    2. Copies the new version into SCRIPTS\\.
    """
    target_drive = get_drive_directory(drive_dir)
    scripts_dir = target_drive / "SCRIPTS"
    scripts_old_dir = scripts_dir / "OLD"

    py_scripts = sorted(list(workspace_dir.glob("*.py")), key=lambda p: p.name.casefold())
    if not py_scripts:
        return [], []

    if not target_drive.exists():
        if dry_run and verbose:
            print(f"[DRY RUN] Target drive folder '{target_drive}' does not exist.", file=sys.stderr)
        return [], []

    scripts_to_archive: list[Path] = []
    scripts_to_copy: list[Path] = []

    for s in py_scripts:
        dst = scripts_dir / s.name
        needs_update = False
        if not dst.exists():
            needs_update = True
        else:
            try:
                # Compare content
                if s.read_bytes() != dst.read_bytes():
                    needs_update = True
                    scripts_to_archive.append(dst)
            except Exception:
                needs_update = True
                scripts_to_archive.append(dst)
        if needs_update:
            scripts_to_copy.append(s)

    timestamp = datetime.now().strftime("%H:%M:%S")

    if dry_run:
        if verbose and (scripts_to_archive or scripts_to_copy):
            print(f"\n[DRY RUN] Script Sync & Archive Simulation ({timestamp}):", file=sys.stderr)
            print(f"Target Scripts Folder: {scripts_dir}", file=sys.stderr)
            print(f"Archive Scripts Folder: {scripts_old_dir}", file=sys.stderr)
            for a in scripts_to_archive:
                print(f"  * Move to OLD: {a.name} -> SCRIPTS/OLD/{a.name}", file=sys.stderr)
            for c in scripts_to_copy:
                print(f"  * Copy: {c.name} -> SCRIPTS/{c.name}", file=sys.stderr)
        return scripts_to_archive, scripts_to_copy

    if not scripts_to_copy:
        return [], []

    try:
        scripts_dir.mkdir(parents=True, exist_ok=True)
        scripts_old_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        if verbose:
            print(f"[!] Warning creating scripts folders: {e}", file=sys.stderr)

    moved: list[Path] = []
    for a in scripts_to_archive:
        dest_old = scripts_old_dir / a.name
        try:
            if dest_old.exists():
                dest_old.unlink()
            shutil.move(str(a), str(dest_old))
            moved.append(a)
        except Exception as err:
            if verbose:
                print(f"[!] Warning moving script {a.name} to SCRIPTS/OLD/: {err}", file=sys.stderr)

    copied: list[Path] = []
    for c in scripts_to_copy:
        dest_new = scripts_dir / c.name
        try:
            shutil.copy2(c, dest_new)
            copied.append(dest_new)
        except Exception as err:
            if verbose:
                print(f"[!] Warning copying script {c.name} to SCRIPTS/: {err}", file=sys.stderr)

    if verbose and copied:
        print(f"[{timestamp}] Updated {len(copied)} script(s) in '{scripts_dir}' (archived {len(moved)} to 'SCRIPTS/OLD/').", file=sys.stderr)

    return moved, copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive previous files to OLD/ and copy new Markdown sources directly to Google Drive"
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("notebook_sources"),
        help="Folder containing generated Markdown files (default: notebook_sources/)",
    )
    parser.add_argument(
        "--drive-dir",
        type=Path,
        default=DEFAULT_DRIVE_DIR,
        help=f"Target Google Drive destination folder (default: {DEFAULT_DRIVE_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate archiving to OLD/ and copying without writing or moving any files",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output",
    )

    args = parser.parse_args()
    sync_to_drive(
        source_dir=args.source_dir,
        drive_dir=args.drive_dir,
        dry_run=args.dry_run,
        verbose=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
