#!/usr/bin/env python3
"""
Automated Google Drive Sync for AlecaFrame Markdown Sources & Scripts
Before copying new files:
1. Moves previous files in G:\\Mi unidad\\WF_DATA\\ to timestamped archive folders in OLD/.
2. Copies new generated .md files directly into G:\\Mi unidad\\WF_DATA\\ (flat, no subfolders).
3. Synchronizes Python scripts into G:\\Mi unidad\\WF_DATA\\SCRIPTS\\ (archiving previous versions to SCRIPTS\\OLD\\).
4. Explicitly omits local-only files (riven_intelligence.md and riven_tracker.py) from uploading.
Supports --dry-run to preview archiving and copying without touching any files.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DRIVE_DIR = Path(r"G:\Mi unidad\WF_DATA")
SYNC_TOKENS_FILE = Path("sync_tokens.json")

# ==============================================================================
# SYNC CONFIGURATION TOKENS
# Token = true  -> Synchronize/Upload to Google Drive.
# Token = false -> Omit from Drive upload (retained locally only).
# Supports overriding or editing via sync_tokens.json in the workspace root.
# ==============================================================================
DEFAULT_SYNC_TOKENS: dict[str, bool] = {
    # Markdown Sources (generated from AlecaFrame exports)
    "account_stats.md": True,
    "combined.md": True,
    "foundry.md": True,
    "inventoryArcanes.md": True,
    "inventoryMisc.md": True,
    "inventoryParts.md": True,
    "inventoryRelics.md": True,
    "inventorySets.md": True,
    "market_opportunities.md": True,
    "mastery_roadmap.md": True,
    "trade_history.md": True,

    # Riven Inventory Split & Overview
    "rivens-overview.md": True,
    "rivens-rifles.md": True,
    "rivens-shotguns.md": True,
    "rivens-pistols.md": True,
    "rivens-melee.md": True,
    "rivens-modular.md": True,
    "rivens-*.md": True,
    "riven_intelligence.md": False,

    # Mod Inventory Split & Overview
    "mods-overview.md": True,
    "mods-warframe.md": True,
    "mods-shotguns.md": True,
    "mods-rifles.md": True,
    "mods-pistols.md": True,
    "mods-melee.md": True,
    "mods-companions.md": True,
    "mods-archwing.md": True,
    "mods-specialized.md": True,
    "mods-*.md": True,

    # Reconstructed Arsenal Loadouts & Builds
    "builds-overview.md": True,
    "builds-warframes.md": True,
    "builds-shotguns.md": True,
    "builds-rifles.md": True,
    "builds-pistols.md": True,
    "builds-melee.md": True,
    "builds-companions.md": True,
    "builds-archwing.md": True,
    "builds-*.md": True,

    # HTML Dashboards & Visualizers
    "stats_dashboard.html": False,

    # Python Scripts (synced to G:\Mi unidad\WF_DATA\SCRIPTS\)
    "market_tracker.py": True,
    "push_to_github.py": True,
    "stats_analyzer.py": True,
    "sync_to_drive.py": True,
    "update_notebook_source.py": True,
    "riven_tracker.py": False,
}


def load_sync_tokens(config_path: Path | None = None) -> dict[str, bool]:
    """
    Load sync configuration tokens.
    Merges local sync_tokens.json (if present) over DEFAULT_SYNC_TOKENS.
    """
    tokens = dict(DEFAULT_SYNC_TOKENS)
    cfg = config_path or SYNC_TOKENS_FILE
    if cfg.exists():
        try:
            custom = json.loads(cfg.read_text(encoding="utf-8"))
            if isinstance(custom, dict):
                for k, v in custom.items():
                    tokens[k] = bool(v)
        except Exception as e:
            print(f"[!] Warning reading '{cfg}': {e}", file=sys.stderr)
    return tokens


def save_sync_tokens(tokens: dict[str, bool], config_path: Path | None = None) -> Path:
    """Save the sync tokens dictionary into sync_tokens.json with clean formatting."""
    cfg = config_path or SYNC_TOKENS_FILE
    cfg.write_text(json.dumps(tokens, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cfg


def is_sync_enabled(filename: str, tokens: dict[str, bool] | None = None) -> bool:
    """
    Check if a file has sync enabled (Token == True).
    Supports exact matching and wildcard patterns (e.g., 'rivens-*.md').
    Defaults to True if unlisted.
    """
    if tokens is None:
        tokens = load_sync_tokens()
    fname_lower = filename.casefold()

    # 1. Exact match check
    for pattern, enabled in tokens.items():
        if pattern.casefold() == fname_lower:
            return bool(enabled)

    # 2. Pattern match check (e.g. rivens-*.md)
    for pattern, enabled in tokens.items():
        if fnmatch.fnmatch(fname_lower, pattern.casefold()):
            return bool(enabled)

    # Default to True if unlisted
    return True


def print_sync_tokens(tokens: dict[str, bool] | None = None) -> None:
    """Display the current sync tokens formatted cleanly."""
    if tokens is None:
        tokens = load_sync_tokens()

    print("=" * 76)
    print("GOOGLE DRIVE SYNC CONFIGURATION TOKENS (sync_tokens.json)")
    print("=" * 76)
    print("Rule: Token = true  -> Synchronize/Upload to Google Drive")
    print("      Token = false -> Omit from upload (Retain locally only)")
    print("-" * 76)

    md_tokens = {k: v for k, v in tokens.items() if k.endswith(".md") or k.endswith(".html")}
    py_tokens = {k: v for k, v in tokens.items() if k.endswith(".py")}

    print("[MARKDOWN SOURCES & DASHBOARDS]")
    for name, enabled in md_tokens.items():
        status_tag = "[SYNC ENABLED]" if enabled else "[LOCAL ONLY] "
        print(f"  {status_tag}  {name:<28} = {'true' if enabled else 'false'};")

    print("\n[PYTHON SCRIPTS (G:\\Mi unidad\\WF_DATA\\SCRIPTS\\)]")
    for name, enabled in py_tokens.items():
        status_tag = "[SYNC ENABLED]" if enabled else "[LOCAL ONLY] "
        print(f"  {status_tag}  {name:<28} = {'true' if enabled else 'false'};")

    print("=" * 76)


def get_drive_directory(custom_path: Path | str | None = None) -> Path:
    """Resolve the target Google Drive directory."""
    if custom_path:
        return Path(custom_path).resolve()
    return DEFAULT_DRIVE_DIR


def get_markdown_sources(source_dir: Path, tokens: dict[str, bool] | None = None) -> list[Path]:
    """Find all Markdown sources in source_dir, plus combined.md if present, respecting sync tokens."""
    if not source_dir.exists():
        return []
    if tokens is None:
        tokens = load_sync_tokens()
    sources: dict[str, Path] = {}
    for p in source_dir.glob("*.md"):
        if not is_sync_enabled(p.name, tokens):
            continue
        sources[p.name.lower()] = p
    root_combined = source_dir.parent / "combined.md"
    if "combined.md" not in sources and root_combined.exists() and root_combined.is_file():
        if is_sync_enabled("combined.md", tokens):
            sources["combined.md"] = root_combined
    return sorted(list(sources.values()), key=lambda p: p.name.casefold())


def sync_to_drive(
    source_dir: Path,
    drive_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = True,
    tokens: dict[str, bool] | None = None,
) -> tuple[list[Path], list[Path]]:
    """
    Archive previous files to OLD/ and copy new generated Markdown files directly to Google Drive.

    Args:
        source_dir: Directory containing generated .md files (e.g. notebook_sources/)
        drive_dir: Target Google Drive folder (default: G:\\Mi unidad\\WF_DATA)
        dry_run: If True, preview what would be archived and copied without writing
        verbose: If True, print status and summary to sys.stderr
        tokens: Optional dictionary of sync configuration tokens

    Returns:
        tuple of (moved_to_old_files, copied_new_files)
    """
    if tokens is None:
        tokens = load_sync_tokens()

    target_drive = get_drive_directory(drive_dir)
    old_dir = target_drive / "OLD"

    if not source_dir.exists():
        if verbose:
            print(f"[!] Warning: Source directory '{source_dir}' does not exist.", file=sys.stderr)
        return [], []

    sources = get_markdown_sources(source_dir, tokens)
    if not sources:
        if verbose:
            print(f"[!] Warning: No sync-enabled .md files found in '{source_dir}'.", file=sys.stderr)
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

    # 1. Identify previous files in target_drive to move to OLD/, and detect omitted files to remove
    incoming_names = {s.name.lower() for s in sources}
    previous_files_to_move: list[Path] = []
    omitted_files_in_drive: list[Path] = []

    for f in target_drive.iterdir():
        # Do not move directories (like OLD or SCRIPTS itself)
        if not f.is_file():
            continue
        if not is_sync_enabled(f.name, tokens):
            omitted_files_in_drive.append(f)
            continue
        if f.suffix.lower() == ".md" or f.name.lower() in incoming_names:
            previous_files_to_move.append(f)

    previous_files_to_move.sort(key=lambda p: p.name.casefold())
    omitted_files_in_drive.sort(key=lambda p: p.name.casefold())

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

            if omitted_files_in_drive:
                print(f"\n[DRY RUN] Step 0: Would remove {len(omitted_files_in_drive)} disabled/omitted file(s) from active Drive folder:", file=sys.stderr)
                for om in omitted_files_in_drive:
                    print(f"  * {om.name} (Token = false, local only)", file=sys.stderr)

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

        workspace_root = source_dir.parent if source_dir.name == "notebook_sources" else source_dir
        sync_scripts_to_drive(
            workspace_dir=workspace_root,
            drive_dir=target_drive,
            dry_run=True,
            verbose=verbose,
            tokens=tokens,
        )

        return previous_files_to_move, sources

    # Remove any omitted files lingering in target_drive
    for om in omitted_files_in_drive:
        try:
            om.unlink()
            if verbose:
                print(f"[{timestamp}] Removed omitted file '{om.name}' from active Drive folder (Token = false).", file=sys.stderr)
        except Exception as om_err:
            if verbose:
                print(f"[!] Warning removing omitted file {om.name}: {om_err}", file=sys.stderr)

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
        tokens=tokens,
    )

    return moved_files, copied_files


def sync_scripts_to_drive(
    workspace_dir: Path,
    drive_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = True,
    tokens: dict[str, bool] | None = None,
) -> tuple[list[Path], list[Path]]:
    """
    Sync Python scripts (.py) from workspace_dir to G:\\Mi unidad\\WF_DATA\\SCRIPTS\\,
    respecting sync configuration tokens (Token == True).
    Before copying an updated script:
    1. If a previous version exists in SCRIPTS/, moves it to SCRIPTS\\OLD\\ (replacing any existing old file).
    2. Copies the new version into SCRIPTS\\.
    """
    if tokens is None:
        tokens = load_sync_tokens()

    target_drive = get_drive_directory(drive_dir)
    scripts_dir = target_drive / "SCRIPTS"
    scripts_old_dir = scripts_dir / "OLD"

    py_scripts = [
        s for s in workspace_dir.glob("*.py")
        if is_sync_enabled(s.name, tokens)
    ]
    py_scripts.sort(key=lambda p: p.name.casefold())
    if not py_scripts:
        return [], []

    if not target_drive.exists():
        if dry_run and verbose:
            print(f"[DRY RUN] Target drive folder '{target_drive}' does not exist.", file=sys.stderr)
        return [], []

    # Check for any omitted scripts currently sitting in scripts_dir or scripts_old_dir
    omitted_scripts_in_drive: list[Path] = []
    if scripts_dir.exists():
        for f in scripts_dir.iterdir():
            if f.is_file() and not is_sync_enabled(f.name, tokens):
                omitted_scripts_in_drive.append(f)
    if scripts_old_dir.exists():
        for f in scripts_old_dir.iterdir():
            if f.is_file() and not is_sync_enabled(f.name, tokens):
                omitted_scripts_in_drive.append(f)

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
        if verbose and (scripts_to_archive or scripts_to_copy or omitted_scripts_in_drive):
            print(f"\n[DRY RUN] Script Sync & Archive Simulation ({timestamp}):", file=sys.stderr)
            print(f"Target Scripts Folder: {scripts_dir}", file=sys.stderr)
            print(f"Archive Scripts Folder: {scripts_old_dir}", file=sys.stderr)
            for om in omitted_scripts_in_drive:
                print(f"  * Would remove disabled script: {om.name} from {om.parent.name}/ (Token = false)", file=sys.stderr)
            for a in scripts_to_archive:
                print(f"  * Move to OLD: {a.name} -> SCRIPTS/OLD/{a.name}", file=sys.stderr)
            for c in scripts_to_copy:
                print(f"  * Copy: {c.name} -> SCRIPTS/{c.name}", file=sys.stderr)
        return scripts_to_archive, scripts_to_copy

    # Remove any omitted scripts lingering in active or old scripts folders
    for om in omitted_scripts_in_drive:
        try:
            om.unlink()
            if verbose:
                print(f"[{timestamp}] Removed disabled script '{om.name}' from '{om.parent.name}/' (Token = false).", file=sys.stderr)
        except Exception as om_err:
            if verbose:
                print(f"[!] Warning removing omitted script {om.name}: {om_err}", file=sys.stderr)

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
        "--tokens",
        "--list-tokens",
        action="store_true",
        help="List all files and their sync token status (true = sync, false = omit)",
    )
    parser.add_argument(
        "--set-token",
        nargs=2,
        metavar=("FILENAME", "VALUE"),
        help="Set sync token for a file (e.g. --set-token riven_intelligence.md false)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output",
    )

    args = parser.parse_args()

    if args.tokens:
        print_sync_tokens()
        return 0

    if args.set_token:
        filename, val_str = args.set_token
        val_bool = val_str.lower() in ("true", "1", "yes", "y", "enable")
        tokens = load_sync_tokens()
        tokens[filename] = val_bool
        save_sync_tokens(tokens)
        status_str = "true" if val_bool else "false"
        print(f"[OK] Updated token: {filename} = {status_str}; (saved to {SYNC_TOKENS_FILE})")
        return 0

    sync_to_drive(
        source_dir=args.source_dir,
        drive_dir=args.drive_dir,
        dry_run=args.dry_run,
        verbose=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
