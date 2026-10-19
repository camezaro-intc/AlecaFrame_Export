#!/usr/bin/env python3
"""
Automated GitHub Sync for AlecaFrame Markdown Sources & Dashboard
Stages modified .md and .html files, generates an informative update summary,
commits, and pushes to GitHub so Gemini NotebookLM always has the latest versions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo(repo_dir: Path) -> bool:
    res = run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_dir)
    return res.returncode == 0 and res.stdout.strip() == "true"


def get_current_branch(repo_dir: Path) -> str:
    res = run_git(["branch", "--show-current"], cwd=repo_dir)
    branch = res.stdout.strip()
    return branch if branch else "main"


def get_remote_name(repo_dir: Path) -> str:
    res = run_git(["remote"], cwd=repo_dir)
    remotes = [r.strip() for r in res.stdout.splitlines() if r.strip()]
    if "origin" in remotes:
        return "origin"
    return remotes[0] if remotes else "origin"


def get_modified_target_files(repo_dir: Path, include_all: bool = False) -> list[str]:
    """Identify modified or untracked .md and .html files (or all if include_all is set)."""
    res = run_git(["status", "--porcelain"], cwd=repo_dir)
    if res.returncode != 0:
        return []

    targets = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        raw_path = line[3:].strip().strip('"')
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ")[1].strip().strip('"')

        if include_all:
            targets.append(raw_path)
        elif raw_path.endswith(".md") or raw_path.endswith(".html"):
            targets.append(raw_path)

    return sorted(list(set(targets)))


def extract_telemetry_summary(repo_dir: Path) -> list[str]:
    """Extract quick bullet points from the latest export data for the commit message."""
    bullets = []

    # 1. Account Stats
    stats_file = repo_dir / "alecaframeStatsExport.json"
    if stats_file.exists():
        try:
            raw = json.loads(stats_file.read_text(encoding="utf-8-sig"))
            pts = raw.get("generalDataPoints", [])
            if pts:
                latest = pts[-1]
                plat = latest.get("plat", 0)
                mr = latest.get("mr", "?")
                credits_m = round(latest.get("credits", 0) / 1_000_000, 2)
                endo_k = round(latest.get("endo", 0) / 1_000, 1)
                bullets.append(f"Account Snapshot: MR {mr} | {plat:,}p Plat | {credits_m}M Credits | {endo_k}k Endo")
        except Exception:
            pass

    # 2. Mastery Rank Progression
    mastery_file = repo_dir / "notebook_sources" / "mastery_roadmap.md"
    if mastery_file.exists():
        try:
            txt = mastery_file.read_text(encoding="utf-8")
            m_xp = re.search(r"Mastery XP Currently Owned in Inventory.*?:\*\*\s*\*\*([0-9,]+)\s*XP\*\*", txt)
            if m_xp:
                bullets.append(f"Mastery Progress: {m_xp.group(1)} XP ready in inventory for next MR")
        except Exception:
            pass

    # 3. Market Intelligence
    market_file = repo_dir / "market_opportunities.md"
    if market_file.exists():
        bullets.append("Market Intel: Warframe.market order prices & wishlist updated")

    return bullets


def build_commit_message(repo_dir: Path, staged_files: list[str]) -> tuple[str, str]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"Sync Notebook sources & Dashboard [{now_str}]"

    body_lines = [
        "Automated sync of NotebookLM Markdown sources and interactive dashboard.",
        "",
        "Updated Files:",
    ]

    # Categorize files
    dashboards = [f for f in staged_files if f.endswith(".html")]
    root_md = [f for f in staged_files if "/" not in f and "\\" not in f and f.endswith(".md")]
    sources_md = [f for f in staged_files if "notebook_sources" in f]

    if dashboards:
        body_lines.append(f"- Dashboard: {', '.join(dashboards)}")
    if root_md:
        body_lines.append(f"- Core Markdown: {', '.join(root_md)}")
    if sources_md:
        base_names = [Path(f).name for f in sources_md]
        body_lines.append(f"- Notebook Sources ({len(sources_md)}): {', '.join(base_names)}")

    # Add telemetry bullets if available
    telemetry_bullets = extract_telemetry_summary(repo_dir)
    if telemetry_bullets:
        body_lines.append("")
        body_lines.append("Telemetry Highlights:")
        for b in telemetry_bullets:
            body_lines.append(f"- {b}")

    body = "\n".join(body_lines)
    return title, body


def push_changes(
    repo_dir: Path | None = None,
    dry_run: bool = False,
    include_all: bool = False,
    verbose: bool = True,
) -> bool:
    """Stage modified .md and .html files, commit with summary, and push to GitHub."""
    if repo_dir is None:
        repo_dir = Path.cwd()
    repo_dir = repo_dir.resolve()

    if not is_git_repo(repo_dir):
        if verbose:
            print(f"[!] Warning: {repo_dir} is not a git repository. Skipping git push.", file=sys.stderr)
        return False

    branch = get_current_branch(repo_dir)
    remote = get_remote_name(repo_dir)

    target_files = get_modified_target_files(repo_dir, include_all=include_all)
    if not target_files:
        if verbose:
            print("[OK] GitHub Sync: All Markdown and HTML files are already up-to-date.", file=sys.stderr)
        return True

    if verbose:
        print(f"[*] Found {len(target_files)} modified Markdown/HTML file(s) to push:", file=sys.stderr)
        for tf in target_files:
            print(f"    - {tf}", file=sys.stderr)

    if dry_run:
        title, body = build_commit_message(repo_dir, target_files)
        print("\n[DRY RUN] Would stage the above files and commit with:", file=sys.stderr)
        print(f"Commit Title: {title}", file=sys.stderr)
        print(f"Commit Body:\n{body}", file=sys.stderr)
        print(f"[DRY RUN] Would push to {remote}/{branch}", file=sys.stderr)
        return True

    # Stage target files
    add_res = run_git(["add", "--"] + target_files, cwd=repo_dir)
    if add_res.returncode != 0:
        print(f"[!] Error staging files: {add_res.stderr}", file=sys.stderr)
        return False

    # Check if there are staged changes
    diff_res = run_git(["diff", "--cached", "--quiet"], cwd=repo_dir)
    if diff_res.returncode == 0:
        if verbose:
            print("[OK] GitHub Sync: No staged changes to commit.", file=sys.stderr)
        return True

    # Generate commit message
    title, body = build_commit_message(repo_dir, target_files)

    # Commit
    commit_res = run_git(["commit", "-m", title, "-m", body], cwd=repo_dir)
    if commit_res.returncode != 0:
        print(f"[!] Error committing changes: {commit_res.stderr}", file=sys.stderr)
        return False

    if verbose:
        print(f"[OK] Committed: {title}", file=sys.stderr)

    # Push
    push_res = run_git(["push", remote, branch], cwd=repo_dir)
    if push_res.returncode != 0:
        print(f"[!] Warning: git push failed: {push_res.stderr.strip()}", file=sys.stderr)
        print("    Tip: Check network connectivity or git credentials.", file=sys.stderr)
        return False

    if verbose:
        print(f"[OK] Successfully pushed latest sources to GitHub ({remote}/{branch})!", file=sys.stderr)

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Push modified Warframe Markdown sources and HTML dashboard to GitHub"
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("."),
        help="Repository root directory (defaults to current dir)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the sync without committing or pushing",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="include_all",
        help="Stage and push all modified files, not just .md and .html",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational console output",
    )

    args = parser.parse_args()
    success = push_changes(
        repo_dir=args.dir,
        dry_run=args.dry_run,
        include_all=args.include_all,
        verbose=not args.quiet,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

