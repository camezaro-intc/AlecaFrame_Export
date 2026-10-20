#!/usr/bin/env python3
"""
Automated Google Drive Sync for AlecaFrame Markdown Sources
Copies all generated .md files from notebook_sources/ directly into
Google Drive (G:\\Mi unidad\\WF_DATA\\) with a flat structure (no subfolders)
so Google Gemini NotebookLM can ingest the latest information directly from Google Drive.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
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
    sources = set(source_dir.glob("*.md"))
    root_combined = source_dir.parent / "combined.md"
    if root_combined.exists() and root_combined.is_file():
        sources.add(root_combined)
    return sorted(list(sources), key=lambda p: p.name.casefold())


def sync_to_drive(
    source_dir: Path,
    drive_dir: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = True,
) -> list[Path]:
    """
    Copy Markdown files directly (flat, no subfolders) into Google Drive directory.
    
    Args:
        source_dir: Directory containing generated .md files (e.g. notebook_sources/)
        drive_dir: Target Google Drive folder (default: G:\\Mi unidad\\WF_DATA)
        dry_run: If True, preview what would be copied without writing to disk
        force: If True, copy all files even if size and modification time match
        verbose: If True, print status and summary to sys.stderr
        
    Returns:
        List of Path objects for copied (or would-be copied) files.
    """
    target_drive = get_drive_directory(drive_dir)

    if not source_dir.exists():
        if verbose:
            print(f"[!] Warning: Source directory '{source_dir}' does not exist.", file=sys.stderr)
        return []

    sources = get_markdown_sources(source_dir)
    if not sources:
        if verbose:
            print(f"[!] Warning: No .md files found in '{source_dir}'.", file=sys.stderr)
        return []

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
                return []

    copied: list[Path] = []
    skipped: list[Path] = []

    for src in sources:
        dst = target_drive / src.name
        needs_copy = False

        if not dst.exists() or force:
            needs_copy = True
        else:
            try:
                src_stat = src.stat()
                dst_stat = dst.stat()
                if src_stat.st_size != dst_stat.st_size:
                    needs_copy = True
                elif src_stat.st_mtime > dst_stat.st_mtime + 1.0:
                    needs_copy = True
                elif src.read_bytes() != dst.read_bytes():
                    needs_copy = True
            except Exception:
                needs_copy = True

        if needs_copy:
            copied.append(src)
        else:
            skipped.append(src)

    if verbose:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if dry_run:
            print(f"\n[DRY RUN] Google Drive Auto-Copy Simulation ({timestamp}):", file=sys.stderr)
            print(f"Target Folder: {target_drive} (Flat structure, no subfolders)", file=sys.stderr)
            if copied:
                print(f"Found {len(copied)} file(s) that would be copied/updated:", file=sys.stderr)
                for f in copied:
                    dst = target_drive / f.name
                    status = "NEW" if not dst.exists() else "UPDATED"
                    size_kb = round(f.stat().st_size / 1024, 1)
                    print(f"  * {f.name} ({size_kb} KB) -> [{status}]", file=sys.stderr)
            else:
                print("All files in Google Drive are already up to date.", file=sys.stderr)
            if skipped:
                print(f"({len(skipped)} file(s) are identical and would be skipped)", file=sys.stderr)
        else:
            if copied:
                print(f"[{timestamp}] Auto-copying {len(copied)} Markdown source(s) to Google Drive...", file=sys.stderr)
                for src in copied:
                    dst = target_drive / src.name
                    try:
                        shutil.copy2(src, dst)
                    except Exception as err:
                        print(f"[!] Error copying {src.name} to {dst}: {err}", file=sys.stderr)
                print(f"[OK] Successfully copied {len(copied)} Markdown source(s) directly into '{target_drive}'.", file=sys.stderr)
                print(f"     Gemini NotebookLM can now ingest/refresh these sources directly from Google Drive.", file=sys.stderr)
            else:
                print(f"[OK] Google Drive: All {len(sources)} Markdown sources in '{target_drive}' are already up to date.", file=sys.stderr)

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy generated Markdown notebook sources directly to Google Drive (flat, no subfolders)"
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
        help="Simulate the copy and show what would be updated without writing to Google Drive",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force copy all files even if sizes and timestamps match",
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
        force=args.force,
        verbose=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
