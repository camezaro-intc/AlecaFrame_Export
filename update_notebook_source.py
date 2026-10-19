#!/usr/bin/env python3
"""Build Gemini Notebook Markdown sources from AlecaFrame JSON exports."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_MARKER = re.compile(r"^<!-- SOURCE_JSON: (.+) -->$")
FENCE_START = re.compile(r"^(`{3,})json$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
IDENTITY_FIELDS = ("randomID", "internalName")
MAX_CHANGE_DETAILS = 250
MAX_VALUE_LENGTH = 120
RIVEN_RECORDS_PER_SOURCE = 150
RECORDS_PER_SECTION = 40

NOISE_KEYS = {
    "picture",
    "weaponPicture",
    "shouldDisplayPlusInPrice",
    "vualtedMakesSense",
    "ordersPlaced",
    "amountNow",
    "isMod",
    "isRelic",
    "goalItemOwned",
    "randomID",
    "minimumMasteryText",
    "editlistType",
    "editlistVisibility",
    "debugInfo",
}


def strip_html(text: Any) -> str:
    if not isinstance(text, str):
        return str(text)
    return re.sub(r"\s+", " ", HTML_TAG_RE.sub("", text)).strip()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_label(record: Any, fallback: str) -> str:
    if isinstance(record, dict):
        # If it's a Riven with statsPerWeapon, include the primary weapon name first
        stats_per_wep = record.get("statsPerWeapon")
        if isinstance(stats_per_wep, list) and stats_per_wep and isinstance(stats_per_wep[0], dict):
            wep_name = stats_per_wep[0].get("weaponName", "")
            riven_name = record.get("name", "")
            if wep_name and riven_name:
                return f"{wep_name} ({riven_name})"
            if wep_name:
                return f"{wep_name} Riven"

        for field in ("name", "weaponName", "internalName", "randomID"):
            value = record.get(field)
            if value is not None and value != "":
                return strip_html(str(value))
    return fallback


def parse_previous_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    lines = path.read_text(encoding="utf-8").splitlines()
    snapshots: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        marker = SOURCE_MARKER.fullmatch(lines[index])
        if marker is None:
            index += 1
            continue

        filename = marker.group(1)
        index += 1
        while index < len(lines) and not FENCE_START.fullmatch(lines[index]):
            index += 1
        if index == len(lines):
            raise ValueError(f"Missing JSON block for {filename} in {path.name}")

        fence = FENCE_START.fullmatch(lines[index]).group(1)
        index += 1
        content: list[str] = []
        while index < len(lines) and lines[index] != fence:
            content.append(lines[index])
            index += 1
        if index == len(lines):
            raise ValueError(f"Unclosed JSON block for {filename} in {path.name}")

        try:
            snapshots[filename] = json.loads("\n".join(content))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid stored JSON for {filename} in {path.name}: {error}"
            ) from error
        index += 1

    return snapshots


def unique_identity_field(old: list[Any], new: list[Any]) -> str | None:
    for field in IDENTITY_FIELDS:
        old_values = [item.get(field) for item in old if isinstance(item, dict)]
        new_values = [item.get(field) for item in new if isinstance(item, dict)]
        if (
            len(old_values) == len(old)
            and len(new_values) == len(new)
            and all(value is not None and value != "" for value in old_values + new_values)
            and len(set(map(canonical, old_values))) == len(old_values)
            and len(set(map(canonical, new_values))) == len(new_values)
        ):
            return field
    return None


def short_value(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(rendered) > MAX_VALUE_LENGTH:
        return rendered[: MAX_VALUE_LENGTH - 3] + "..."
    return rendered


def nested_changes(old: Any, new: Any, path: str) -> list[str]:
    if type(old) is not type(new):
        return [f"`{path}` changed from `{short_value(old)}` to `{short_value(new)}`"]
    if isinstance(old, dict):
        changes: list[str] = []
        for key in sorted(old.keys() | new.keys()):
            child_path = f"{path}.{key}"
            if key not in old:
                changes.append(f"`{child_path}` added: `{short_value(new[key])}`")
            elif key not in new:
                changes.append(f"`{child_path}` removed (was `{short_value(old[key])}`)")
            else:
                changes.extend(nested_changes(old[key], new[key], child_path))
            if len(changes) >= MAX_CHANGE_DETAILS:
                return changes[:MAX_CHANGE_DETAILS]
        return changes
    if isinstance(old, list):
        if old == new:
            return []
        changes = []
        for index in range(min(len(old), len(new))):
            changes.extend(nested_changes(old[index], new[index], f"{path}[{index}]"))
            if len(changes) >= MAX_CHANGE_DETAILS:
                return changes[:MAX_CHANGE_DETAILS]
        for index in range(len(new) - len(old)):
            changes.append(
                f"`{path}[{len(old) + index}]` added: "
                f"`{short_value(new[len(old) + index])}`"
            )
        for index in range(len(old) - len(new)):
            changes.append(
                f"`{path}[{len(new) + index}]` removed "
                f"(was `{short_value(old[len(new) + index])}`)"
            )
        return changes[:MAX_CHANGE_DETAILS]
    if old != new:
        return [f"`{path}` changed from `{short_value(old)}` to `{short_value(new)}`"]
    return []


def compare_records(old: Any, new: Any) -> tuple[list[str], list[str], list[tuple[str, list[str]]]]:
    if not isinstance(old, list) or not isinstance(new, list):
        changes = nested_changes(old, new, "$")
        return ([], [], [("$", changes)] if changes else [])

    identity = unique_identity_field(old, new)
    if identity is None:
        old_counts = Counter(map(canonical, old))
        new_counts = Counter(map(canonical, new))
        old_remaining = old_counts - new_counts
        new_remaining = new_counts - old_counts
        removed = [
            record_label(json.loads(value), f"record {number}")
            for number, value in enumerate(
                (value for value, count in old_remaining.items() for _ in range(count)),
                start=1,
            )
        ]
        added = [
            record_label(json.loads(value), f"record {number}")
            for number, value in enumerate(
                (value for value, count in new_remaining.items() for _ in range(count)),
                start=1,
            )
        ]
        return added, removed, []

    old_by_id = {canonical(item[identity]): item for item in old}
    new_by_id = {canonical(item[identity]): item for item in new}
    added = [
        record_label(new_by_id[key], str(new_by_id[key][identity]))
        for key in sorted(new_by_id.keys() - old_by_id.keys())
    ]
    removed = [
        record_label(old_by_id[key], str(old_by_id[key][identity]))
        for key in sorted(old_by_id.keys() - new_by_id.keys())
    ]
    changed: list[tuple[str, list[str]]] = []
    for key in sorted(old_by_id.keys() & new_by_id.keys()):
        details = nested_changes(old_by_id[key], new_by_id[key], "$")
        if details:
            label = record_label(new_by_id[key], str(new_by_id[key][identity]))
            changed.append((label, details))
    return added, removed, changed


def render_change_summary(previous: dict[str, Any], current: dict[str, Any]) -> str:
    if not previous:
        return (
            "No previous generated snapshot was found; this is the initial export. "
            "Future runs will compare against this one.\n"
        )

    lines: list[str] = []
    detail_count = 0
    for filename in sorted(current.keys() - previous.keys()):
        lines.append(
            f"- **{filename}:** new JSON export "
            f"({len(current[filename]) if isinstance(current[filename], list) else 1} records)."
        )
    for filename in sorted(previous.keys() - current.keys()):
        lines.append(f"- **{filename}:** JSON export was removed from the folder.")

    for filename in sorted(current.keys() & previous.keys()):
        old_data = previous[filename]
        new_data = current[filename]
        added, removed, changed = compare_records(old_data, new_data)
        if not added and not removed and not changed:
            lines.append(f"- **{filename}:** no data changes.")
            continue
        lines.append(
            f"- **{filename}:** {len(added)} record(s) added, "
            f"{len(removed)} removed, {len(changed)} updated."
        )
        for label in added[:MAX_CHANGE_DETAILS]:
            lines.append(f"  - Added: `{label}`")
            detail_count += 1
        for label in removed[:MAX_CHANGE_DETAILS]:
            lines.append(f"  - Removed: `{label}`")
            detail_count += 1
        for label, changes in changed:
            if detail_count >= MAX_CHANGE_DETAILS:
                break
            lines.append(f"  - Updated `{label}`:")
            for change in changes:
                if detail_count >= MAX_CHANGE_DETAILS:
                    break
                lines.append(f"    - {change}")
                detail_count += 1
        if detail_count >= MAX_CHANGE_DETAILS:
            lines.append(
                f"- Change details were limited to the first {MAX_CHANGE_DETAILS} entries; "
                "the complete latest data is included below."
            )
            break

    if not lines:
        lines.append("No JSON exports were found in the folder.")
    return "\n".join(lines) + "\n"


def markdown_fence(content: str) -> str:
    longest_run = max((len(match.group()) for match in re.finditer(r"`+", content)), default=0)
    return "`" * max(3, longest_run + 1)


def extract_internal_hint(internal_name: Any) -> str:
    if not isinstance(internal_name, str) or not internal_name.startswith("/"):
        return ""
    parts = [p for p in internal_name.split("/") if p and p not in ("Lotus", "Upgrades", "Types", "Items")]
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")


def format_riven_stats(stats_per_weapon: Any) -> str:
    """Extract only the Max Rank (level 8) traits per weapon variant and strip HTML tags."""
    if not isinstance(stats_per_weapon, list) or not stats_per_weapon:
        return ""
    weapon_summaries: list[str] = []
    for wep in stats_per_weapon:
        if not isinstance(wep, dict):
            continue
        wep_name = wep.get("weaponName", "Unknown Weapon")
        by_level = wep.get("byLevel", [])
        if not isinstance(by_level, list) or not by_level:
            continue
        # Pick highest level (typically level 8)
        max_entry = max(
            (entry for entry in by_level if isinstance(entry, dict)),
            key=lambda x: x.get("level", 0),
            default=None,
        )
        if not max_entry:
            continue

        pos_list = []
        for trait in max_entry.get("positiveTraits", []):
            if isinstance(trait, dict) and trait.get("description"):
                desc = strip_html(trait["description"])
                grade = trait.get("grade", "")
                pos_list.append(f"{desc} [{grade}]" if grade else desc)

        neg_list = []
        for trait in max_entry.get("negativeTraits", []):
            if isinstance(trait, dict) and trait.get("description"):
                desc = strip_html(trait["description"])
                grade = trait.get("grade", "")
                neg_list.append(f"{desc} [{grade}]" if grade else desc)

        traits_str = ", ".join(pos_list)
        if neg_list:
            traits_str += f" | Curse: {', '.join(neg_list)}"
        weapon_summaries.append(f"{wep_name} (Max Rank): {traits_str}")

    return " ; ".join(weapon_summaries)


def format_nested_value(val: Any) -> str:
    if isinstance(val, list):
        if not val:
            return ""
        items = []
        for entry in val:
            if isinstance(entry, dict):
                sub_parts = [
                    f"{k}: {strip_html(v)}"
                    for k, v in entry.items()
                    if k not in NOISE_KEYS and v not in (None, "", False, [], {})
                ]
                if sub_parts:
                    items.append("(" + ", ".join(sub_parts) + ")")
            else:
                items.append(strip_html(entry))
        return "; ".join(items)
    if isinstance(val, dict):
        sub_parts = [
            f"{k}: {strip_html(v)}"
            for k, v in val.items()
            if k not in NOISE_KEYS and v not in (None, "", False, [], {})
        ]
        return "(" + ", ".join(sub_parts) + ")"
    return strip_html(val)


def format_record_line(record: Any, index: int) -> str:
    if not isinstance(record, dict):
        return f"- Record {index}: {json.dumps(record, ensure_ascii=False)}"

    name = record_label(record, f"Item #{index}")
    details: list[str] = []

    # 1. Type & Rarity
    item_type = record.get("type") or record.get("weaponType") or ""
    mod_type = record.get("modType", "")
    if mod_type and item_type:
        details.append(f"Type: {mod_type} {item_type}")
    elif item_type:
        details.append(f"Type: {item_type}")
    elif mod_type:
        details.append(f"Rarity: {mod_type}")

    # 2. Rank (Mods / Arcanes / Rivens)
    if "currentModRank" in record or "modRankMax" in record:
        cur_r = record.get("currentModRank", 0)
        max_r = record.get("modRankMax", "?")
        status = "MAXED" if cur_r == max_r and max_r != "?" else "Unmaxed"
        details.append(f"Rank: {cur_r}/{max_r} ({status})")
    elif "currentImprovementLevel" in record or "maxImprovementLevel" in record:
        cur_r = record.get("currentImprovementLevel", 0)
        max_r = record.get("maxImprovementLevel", 8)
        details.append(f"Riven Rank: {cur_r}/{max_r}")

    # 3. Quantity Owned
    if "amountOwned" in record:
        details.append(f"Owned: {record['amountOwned']}")
    elif "count" in record:
        details.append(f"Owned: {record['count']}")

    # 4. Polarity, Mastery, Disposition & Roll Grade
    if record.get("polarity"):
        details.append(f"Polarity: {record['polarity']}")
    if record.get("minimumMastery") is not None and record.get("minimumMastery") != -1:
        details.append(f"MR: {record['minimumMastery']}")
    if record.get("disposition"):
        details.append(f"Disposition: {round(float(record['disposition']), 2)}")
    if record.get("grade"):
        details.append(f"Overall Grade: {record['grade']}")
    if record.get("rerollCount") is not None:
        details.append(f"Rerolls: {record['rerollCount']}")
    if record.get("modUsedBy"):
        details.append(f"Compatibility: {strip_html(record['modUsedBy'])}")

    # 5. Riven Stats (Max Rank Only)
    if "statsPerWeapon" in record:
        riven_summary = format_riven_stats(record["statsPerWeapon"])
        if riven_summary:
            details.append(f"Stats -> {riven_summary}")

    # 6. Important Flags
    flags: list[str] = []
    if record.get("isFav"):
        flags.append("FAVORITED")
    if record.get("isReadyToSell"):
        flags.append("COMPLETE SET / READY TO BUILD OR SELL")
    if record.get("owned"):
        flags.append("OWNED IN ARSENAL")
    if record.get("mastered") or record.get("isMastered"):
        flags.append("Mastered")
    if record.get("vaulted"):
        flags.append("Vaulted")
    if flags:
        details.append("Flags: " + ", ".join(flags))

    # 7. Economy (Platinum & Ducats)
    econ: list[str] = []
    if record.get("sellPrice"):
        econ.append(f"Sell: {record['sellPrice']}p")
    if record.get("buyPrice"):
        econ.append(f"Buy: {record['buyPrice']}p")
    if record.get("ducats"):
        econ.append(f"Ducats: {record['ducats']}")
    if econ:
        details.append(" | ".join(econ))

    # 8. Internal Effect Hint
    hint = extract_internal_hint(record.get("internalName"))
    if hint and hint.lower() != str(name).lower():
        details.append(f"Effect ID: {hint}")

    # 9. Remaining fields
    handled_keys = NOISE_KEYS | {
        "name",
        "weaponName",
        "internalName",
        "type",
        "weaponType",
        "modType",
        "currentModRank",
        "modRankMax",
        "currentImprovementLevel",
        "maxImprovementLevel",
        "amountOwned",
        "count",
        "polarity",
        "minimumMastery",
        "disposition",
        "grade",
        "rerollCount",
        "modUsedBy",
        "statsPerWeapon",
        "isFav",
        "isReadyToSell",
        "owned",
        "mastered",
        "isMastered",
        "vaulted",
        "sellPrice",
        "buyPrice",
        "ducats",
    }

    for key, val in record.items():
        if key in handled_keys or val in (None, "", False, [], {}):
            continue
        rendered_val = format_nested_value(val)
        if rendered_val:
            details.append(f"{key}: {rendered_val}")

    return f"- **{name}** — " + " | ".join(details)


def build_split_markdown(filename: str, data: Any, title: str) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# {title}",
        "",
        f"Searchable Warframe inventory data exported from `{filename}` (Updated: {generated_at}).",
        "",
    ]

    if isinstance(data, list):
        if not data:
            lines.append("_No records in this export._")
            return "\n".join(lines) + "\n"

        sorted_data = sorted(
            data,
            key=lambda item: record_label(item, "").casefold() if isinstance(item, dict) else "",
        )
        total = len(sorted_data)
        lines.append(f"Total entries in `{filename}`: **{total}**.")
        lines.append("")

        for start in range(0, total, RECORDS_PER_SECTION):
            chunk = sorted_data[start : start + RECORDS_PER_SECTION]
            first_label = record_label(chunk[0], f"#{start + 1}")
            last_label = record_label(chunk[-1], f"#{start + len(chunk)}")
            lines.append(
                f"## {title}: Entries {start + 1} to {start + len(chunk)} ({first_label} — {last_label})"
            )
            lines.append("")
            for offset, record in enumerate(chunk, start=start + 1):
                lines.append(format_record_line(record, offset))
            lines.append("")

    elif isinstance(data, dict):
        for key, value in data.items():
            if key in NOISE_KEYS:
                continue
            lines.append(f"## {title} — {key}")
            lines.append("")
            if isinstance(value, list):
                for idx, item in enumerate(value, start=1):
                    lines.append(format_record_line(item, idx))
            else:
                lines.append(f"- **{key}**: {format_nested_value(value)}")
            lines.append("")
    else:
        lines.append(str(data))

    return "\n".join(lines) + "\n"


def build_markdown(current: dict[str, Any], previous: dict[str, Any]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    sections = [
        "# AlecaFrame Export",
        "",
        f"_Generated by `update_notebook_source.py` on {generated_at}._",
        "",
        "This document contains the complete contents of each JSON export. "
        "The change summary compares this run with the previous generated copy.",
        "",
        "## Changes since previous generation",
        "",
        render_change_summary(previous, current).rstrip(),
        "",
        "## Complete JSON exports",
        "",
    ]
    for filename, data in current.items():
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        fence = markdown_fence(serialized)
        sections.extend(
            [
                f"<!-- SOURCE_JSON: {filename} -->",
                f"### {filename}",
                "",
                f"{fence}json",
                serialized,
                fence,
                "",
            ]
        )
    return "\n".join(sections)


def write_atomically(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temp_path = Path(temporary.name)
    try:
        os.replace(temp_path, output)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combine JSON exports into a Markdown source and report changes."
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Folder containing the JSON exports (default: script folder).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown output path (default: <directory>/combined.md).",
    )
    parser.add_argument(
        "--split-output-dir",
        type=Path,
        default=None,
        help=(
            "Also write one Markdown source per JSON file "
            "(default: <directory>/notebook_sources)."
        ),
    )
    parser.add_argument(
        "--skip-market",
        action="store_true",
        help="Skip fetching live Warframe Market prices and wishlist.",
    )
    parser.add_argument(
        "--wishlist",
        type=Path,
        default=None,
        help="Path to custom wishlist text file (default: <directory>/wishlist.txt).",
    )
    args = parser.parse_args()

    directory = args.directory.resolve()
    output = (args.output or directory / "combined.md").resolve()
    split_output_dir = (
        args.split_output_dir or directory / "notebook_sources"
    ).resolve()
    json_files = sorted(directory.glob("*.json"), key=lambda path: path.name.casefold())
    if not json_files:
        parser.error(f"No .json exports found in {directory}")

    current: dict[str, Any] = {}
    generated_split_files: set[Path] = set()
    try:
        for path in json_files:
            current[path.name] = json.loads(path.read_text(encoding="utf-8-sig"))
        previous = parse_previous_snapshot(output)
        markdown = build_markdown(current, previous)
        write_atomically(output, markdown)
        for filename, data in current.items():
            if filename == "rivens.json" and isinstance(data, list):
                chunks = [
                    data[index : index + RIVEN_RECORDS_PER_SOURCE]
                    for index in range(0, len(data), RIVEN_RECORDS_PER_SOURCE)
                ] or [[]]
                for index, chunk in enumerate(chunks, start=1):
                    split_name = f"rivens-{index:03}.md"
                    split_path = split_output_dir / split_name
                    title = f"Rivens ({index}/{len(chunks)})"
                    write_atomically(
                        split_path,
                        build_split_markdown(filename, chunk, title),
                    )
                    generated_split_files.add(split_path)
                continue

            if filename == "alecaframeStatsExport.json" and isinstance(data, dict):
                try:
                    from stats_analyzer import (
                        build_account_stats_markdown,
                        build_trade_history_markdown,
                        build_mastery_roadmap_markdown,
                        classify_mastery_roadmap,
                        build_html_dashboard,
                        parse_trades,
                    )
                    parsed_trades = parse_trades(data.get("trades", []))

                    # 1. account_stats.md
                    stats_path = split_output_dir / "account_stats.md"
                    write_atomically(stats_path, build_account_stats_markdown(data))
                    generated_split_files.add(stats_path)

                    # 2. trade_history.md
                    trade_path = split_output_dir / "trade_history.md"
                    write_atomically(trade_path, build_trade_history_markdown(parsed_trades))
                    generated_split_files.add(trade_path)

                    # 3. mastery_roadmap.md
                    foundry_file = directory / "foundry.json"
                    roadmap_data = None
                    if foundry_file.exists():
                        try:
                            foundry_raw = json.loads(foundry_file.read_text(encoding="utf-8-sig"))
                            pts = data.get("generalDataPoints", [])
                            current_mr = pts[-1].get("mr", 34) if pts else 34
                            roadmap_data = classify_mastery_roadmap(foundry_raw, current_mr=current_mr)
                            mastery_path = split_output_dir / "mastery_roadmap.md"
                            write_atomically(mastery_path, build_mastery_roadmap_markdown(roadmap_data))
                            generated_split_files.add(mastery_path)
                        except Exception as m_err:
                            print(f"Warning: could not process mastery roadmap: {m_err}", file=sys.stderr)

                    # 4. stats_dashboard.html in workspace root
                    dashboard_path = directory / "stats_dashboard.html"
                    write_atomically(dashboard_path, build_html_dashboard(data, parsed_trades, roadmap_data=roadmap_data))
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated stats dashboard at {dashboard_path}", file=sys.stderr)
                except Exception as stats_err:
                    print(f"Warning: could not process stats export: {stats_err}", file=sys.stderr)
                continue

            split_name = f"{Path(filename).stem}.md"
            split_path = split_output_dir / split_name
            write_atomically(
                split_path,
                build_split_markdown(filename, data, Path(filename).stem),
            )
            generated_split_files.add(split_path)

        # Generate Warframe.market pricing intelligence & wishlist report
        if not args.skip_market:
            try:
                from market_tracker import (
                    MarketClient,
                    analyze_wishlist,
                    analyze_sellable_mods,
                    analyze_ready_sets,
                    analyze_needed_mods,
                    generate_markdown_report,
                )
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching live Warframe.market prices & wishlist intelligence...", file=sys.stderr)
                client = MarketClient()
                mods_data = current.get("inventoryMods.json", [])
                sets_data = current.get("inventorySets.json", [])
                w_path = args.wishlist or (directory / "wishlist.txt")

                wishlist_mods = analyze_wishlist(client, wishlist_file=w_path)
                exclude_names = {m["name"] for m in wishlist_mods}
                sell_mods = analyze_sellable_mods(mods_data, client, limit=10)
                ready_sets = analyze_ready_sets(sets_data, client, limit=8)
                needed_mods = analyze_needed_mods(
                    mods_data, client, limit=10, exclude_names=exclude_names
                )

                market_report = generate_markdown_report(
                    sell_mods, ready_sets, needed_mods, wishlist_mods=wishlist_mods
                )

                market_split_file = split_output_dir / "market_opportunities.md"
                write_atomically(market_split_file, market_report)
                generated_split_files.add(market_split_file)

                # Also write root market_opportunities.md
                write_atomically(directory / "market_opportunities.md", market_report)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated market intelligence in {market_split_file}", file=sys.stderr)
            except Exception as market_err:
                print(f"Warning: could not update market intelligence: {market_err}", file=sys.stderr)

        stale_riven_sources = list(split_output_dir.glob("rivens-*.md"))
        legacy_riven_source = split_output_dir / "rivens.md"
        legacy_stats_source = split_output_dir / "alecaframeStatsExport.md"
        if legacy_riven_source.exists():
            stale_riven_sources.append(legacy_riven_source)
        if legacy_stats_source.exists():
            stale_riven_sources.append(legacy_stats_source)
        for stale_path in stale_riven_sources:
            if stale_path not in generated_split_files:
                stale_path.unlink()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Export failed: {error}", file=sys.stderr)
        return 1

    print(f"Updated {output}")
    print(
        f"Updated {len(generated_split_files)} per-file Markdown source(s) "
        f"in {split_output_dir}"
    )
    print(
        f"Included {len(current)} JSON file(s), "
        f"{sum(len(data) if isinstance(data, list) else 1 for data in current.values())} top-level record(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())