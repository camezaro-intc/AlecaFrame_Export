#!/usr/bin/env python3
"""Build Gemini Notebook Markdown sources from AlecaFrame JSON exports."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
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


KNOWN_ALECAFRAME_EXPORTS = [
    "alecaframeStatsExport.json",
    "foundry.json",
    "inventoryMods.json",
    "inventorySets.json",
    "inventoryParts.json",
    "inventoryRelics.json",
    "inventoryArcanes.json",
    "inventoryMisc.json",
    "rivens.json",
]


def get_desktop_directories(target_dir: Path | None = None) -> list[Path]:
    """Find valid Desktop folders on the current operating system."""
    candidates = []
    if target_dir:
        candidates.append(target_dir.parent)
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / "Desktop")
        candidates.append(Path(userprofile) / "OneDrive" / "Desktop")
    candidates.append(Path.home() / "Desktop")
    candidates.append(Path.cwd().parent)

    seen = set()
    valid_dirs = []
    for c in candidates:
        try:
            resolved = c.resolve()
            if resolved.exists() and resolved.is_dir() and resolved not in seen:
                if target_dir and resolved == target_dir.resolve():
                    continue
                seen.add(resolved)
                valid_dirs.append(resolved)
        except Exception:
            pass
    return valid_dirs


def sync_desktop_exports(
    target_dir: Path,
    file_names: list[str] | None = None,
    search_dirs: list[Path] | None = None,
) -> list[tuple[Path, Path]]:
    """
    Search Desktop directories for AlecaFrame JSON exports.
    If a file is found that is newer or different from the local one, copy it into target_dir.
    Returns list of (source_path, dest_path) for copied files.
    """
    if file_names is None:
        file_names = KNOWN_ALECAFRAME_EXPORTS

    if search_dirs is None:
        search_dirs = get_desktop_directories(target_dir)

    copied_files: list[tuple[Path, Path]] = []

    for d_dir in search_dirs:
        for fname in file_names:
            src = d_dir / fname
            if not src.exists() or not src.is_file():
                continue

            dst = target_dir / fname
            should_copy = False

            if not dst.exists():
                should_copy = True
            else:
                try:
                    src_stat = src.stat()
                    dst_stat = dst.stat()
                    # Copy if Desktop copy has a newer modification timestamp
                    if src_stat.st_mtime > dst_stat.st_mtime + 1.0:
                        should_copy = True
                    elif src_stat.st_size != dst_stat.st_size:
                        should_copy = True
                    else:
                        if src.read_bytes() != dst.read_bytes():
                            should_copy = True
                except Exception:
                    should_copy = True

            if should_copy:
                try:
                    shutil.copy2(src, dst)
                    copied_files.append((src, dst))
                except Exception as copy_err:
                    print(f"Warning: could not copy {src} to {dst}: {copy_err}", file=sys.stderr)

    return copied_files


def strip_html(text: Any) -> str:
    if not isinstance(text, str):
        return str(text)
    return re.sub(r"\s+", " ", HTML_TAG_RE.sub("", text)).strip()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_label(record: Any, fallback: str, include_rank: bool = True) -> str:
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

        if "user" in record and "totalPlat" in record:
            user = record.get("user")
            ts = record.get("ts", "")
            return f"Trade with {user} ({ts})" if user else f"Trade ({ts})"
        if "ts" in record and "plat" in record:
            return f"DataPoint ({record.get('ts')})"

        for field in ("name", "weaponName", "displayName", "internalName", "randomID"):
            value = record.get(field)
            if value is not None and value != "":
                label = strip_html(str(value))
                if include_rank:
                    cur_r = record.get("currentModRank")
                    if cur_r is None:
                        cur_r = record.get("rank")
                    if cur_r is not None:
                        return f"{label} (Rank {cur_r})"
                return label
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


def get_record_identity_key(item: Any) -> str | None:
    """Extract a stable identity key for a record to support order-independent delta comparisons."""
    if not isinstance(item, dict):
        return None

    # Rivens and explicitly keyed items
    random_id = item.get("randomID")
    if random_id:
        return f"randomID:{random_id}"

    # Warframe items: Mods, Arcanes, Weapons, Warframes, Parts, Sets, Relics, Foundry, Misc
    base_name = item.get("internalName") or item.get("name") or item.get("weaponName") or item.get("displayName")
    if base_name:
        rank = item.get("currentModRank")
        if rank is None:
            rank = item.get("rank")
        if rank is None:
            rank = item.get("modRank")
        if rank is not None:
            return f"item:{base_name}#rank={rank}"
        return f"item:{base_name}"

    # Stats, Trades, Timestamps
    ts = item.get("ts")
    if ts is not None:
        return f"ts:{ts}"

    # Generic IDs
    for id_key in ("id", "uuid", "tradeId", "uniqueId"):
        val = item.get(id_key)
        if val is not None:
            return f"{id_key}:{val}"

    # Traits / levels / shards
    level = item.get("level")
    if level is not None:
        return f"level:{level}"
    desc = item.get("description")
    if desc:
        return f"desc:{desc}"
    text = item.get("text")
    if text:
        return f"text:{text}"

    return None


def index_records_by_identity(records: list[Any]) -> tuple[dict[str, Any], list[str]]:
    """Index an array of records by their unique identity keys while preserving encounter order."""
    indexed: dict[str, Any] = {}
    ordered_keys: list[str] = []
    counts: Counter[str] = Counter()
    for item in records:
        base_key = get_record_identity_key(item)
        if base_key is None:
            base_key = f"__canonical__:{canonical(item)}"
        counts[base_key] += 1
        c = counts[base_key]
        unique_key = f"{base_key}#{c}" if c > 1 else base_key
        indexed[unique_key] = item
        ordered_keys.append(unique_key)
    return indexed, ordered_keys


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
        if old == new:
            return []
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

        # If both are lists of dicts, compare using identity rather than array index
        if all(isinstance(x, dict) for x in old) and all(isinstance(x, dict) for x in new):
            old_indexed, old_keys = index_records_by_identity(old)
            new_indexed, new_keys = index_records_by_identity(new)

            changes: list[str] = []
            # Check for property changes in matching items
            for key in new_keys:
                if key in old_indexed:
                    old_item = old_indexed[key]
                    new_item = new_indexed[key]
                    if old_item == new_item:
                        continue
                    item_label = record_label(new_item, key)
                    changes.extend(nested_changes(old_item, new_item, f"{path}[{item_label}]"))
                    if len(changes) >= MAX_CHANGE_DETAILS:
                        return changes[:MAX_CHANGE_DETAILS]

            # Added items
            for key in new_keys:
                if key not in old_indexed:
                    item_label = record_label(new_indexed[key], key)
                    changes.append(f"`{path}` added item `{item_label}`: `{short_value(new_indexed[key])}`")
                    if len(changes) >= MAX_CHANGE_DETAILS:
                        return changes[:MAX_CHANGE_DETAILS]

            # Removed items
            for key in old_keys:
                if key not in new_indexed:
                    item_label = record_label(old_indexed[key], key)
                    changes.append(f"`{path}` removed item `{item_label}` (was `{short_value(old_indexed[key])}`)")
                    if len(changes) >= MAX_CHANGE_DETAILS:
                        return changes[:MAX_CHANGE_DETAILS]

            return changes[:MAX_CHANGE_DETAILS]

        # For primitive lists, if order changed but elements are identical, treat as no changes
        if Counter(map(canonical, old)) == Counter(map(canonical, new)):
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

    old_indexed, old_keys = index_records_by_identity(old)
    new_indexed, new_keys = index_records_by_identity(new)

    added = [
        record_label(new_indexed[key], key)
        for key in new_keys
        if key not in old_indexed
    ]
    removed = [
        record_label(old_indexed[key], key)
        for key in old_keys
        if key not in new_indexed
    ]

    changed: list[tuple[str, list[str]]] = []
    for key in new_keys:
        if key in old_indexed:
            old_item = old_indexed[key]
            new_item = new_indexed[key]
            if old_item == new_item:
                continue
            details = nested_changes(old_item, new_item, "$")
            if details:
                label = record_label(new_item, key)
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

        update_count = len(changed[0][1]) if len(changed) == 1 and changed[0][0] == "$" else len(changed)
        lines.append(
            f"- **{filename}:** {len(added)} record(s) added, "
            f"{len(removed)} removed, {update_count} updated."
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
            if label == "$":
                for change in changes:
                    if detail_count >= MAX_CHANGE_DETAILS:
                        break
                    lines.append(f"  - {change}")
                    detail_count += 1
            else:
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

    name = record_label(record, f"Item #{index}", include_rank=False)
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


RIVEN_CATEGORY_SPECS = [
    ("rifles", "rivens-rifles.md", "Rifles, Bows & Snipers"),
    ("shotguns", "rivens-shotguns.md", "Shotguns"),
    ("pistols", "rivens-pistols.md", "Pistols & Secondaries"),
    ("melee", "rivens-melee.md", "Melee Weapons"),
    ("modular", "rivens-modular.md", "Modular Weapons (Kitguns & Zaws)"),
]


def classify_riven_category(weapon_type: str) -> str:
    """
    Classify weaponType into one of 5 distinct categories:
    - 'rifles': 'Rifle', 'Bow', 'Sniper', 'Launcher'
    - 'shotguns': 'Shotgun'
    - 'pistols': 'Pistol', 'Secondary'
    - 'melee': 'Melee'
    - 'modular': 'Kitgun', 'Zaw'
    """
    wt = (weapon_type or "").strip().casefold()
    if wt in {"rifle", "bow", "sniper", "launcher"}:
        return "rifles"
    if wt == "shotgun":
        return "shotguns"
    if wt in {"pistol", "secondary"}:
        return "pistols"
    if wt == "melee":
        return "melee"
    if wt in {"kitgun", "zaw"}:
        return "modular"
    return "rifles"


def format_riven_card(r: dict[str, Any]) -> str:
    """
    Format a single Riven entry in clean, natural Markdown bullets:
    - **[WeaponName] ([RivenName])** — Type: [weaponType] | Rank: [curRank]/[maxRank] | Polarity: [polarity] | MR: [MR] | Disposition: [disposition]x | Rerolls: [rerollCount]
      - Stats (Max Rank): [Positive Stats comma-separated]
      - Curse: [Negative Curse description] (omit line if no negative)
    """
    weapon_name = r.get("weaponName") or "Unknown Weapon"
    riven_name = r.get("name") or "Riven"
    weapon_type = r.get("weaponType") or "Unknown"
    cur_rank = r.get("currentImprovementLevel", 0)
    max_rank = r.get("maxImprovementLevel", 8)
    raw_polarity = r.get("polarity", "")
    polarity = raw_polarity.capitalize() if raw_polarity else "None"
    mr = r.get("minimumMastery", 0)

    disp_val = r.get("disposition", 1.0)
    try:
        disp_str = f"{round(float(disp_val), 2):g}"
    except (ValueError, TypeError):
        disp_str = str(disp_val)

    rerolls = r.get("rerollCount", 0)

    # Positive and negative traits at Max Rank
    pos_traits: list[str] = []
    neg_traits: list[str] = []

    stats_per_weapon = r.get("statsPerWeapon", [])
    if stats_per_weapon and isinstance(stats_per_weapon, list):
        by_level = stats_per_weapon[0].get("byLevel", [])
        if by_level and isinstance(by_level, list):
            max_level_data = by_level[-1]
            pos_traits = [
                HTML_TAG_RE.sub("", t.get("description", "")).strip()
                for t in max_level_data.get("positiveTraits", [])
                if t.get("description")
            ]
            neg_traits = [
                HTML_TAG_RE.sub("", t.get("description", "")).strip()
                for t in max_level_data.get("negativeTraits", [])
                if t.get("description")
            ]

    header = (
        f"- **{weapon_name} ({riven_name})** — "
        f"Type: {weapon_type} | "
        f"Rank: {cur_rank}/{max_rank} | "
        f"Polarity: {polarity} | "
        f"MR: {mr} | "
        f"Disposition: {disp_str}x | "
        f"Rerolls: {rerolls}"
    )

    lines = [header]
    if pos_traits:
        lines.append(f"  - Stats (Max Rank): {', '.join(pos_traits)}")
    else:
        lines.append("  - Stats (Max Rank): None")

    if neg_traits:
        lines.append(f"  - Curse: {', '.join(neg_traits)}")

    return "\n".join(lines)


def build_riven_category_markdown(
    category_title: str,
    rivens: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# Rivens — {category_title}",
        "",
        f"_Generated by `update_notebook_source.py` on {generated_at}._",
        "",
        f"Total {category_title} Rivens: **{len(rivens)}**",
        "",
        "## Riven Inventory",
        "",
    ]
    if not rivens:
        lines.append("_No rivens in this category._")
    else:
        for r in rivens:
            lines.append(format_riven_card(r))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_riven_overview_markdown(
    rivens_data: list[dict[str, Any]],
    mods_data: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_unveiled = len(rivens_data)
    unrolled_rivens = [r for r in rivens_data if r.get("rerollCount", 0) == 0]
    unrolled_count = len(unrolled_rivens)
    rolled_count = total_unveiled - unrolled_count
    unrolled_pct = (unrolled_count / total_unveiled * 100) if total_unveiled else 0.0

    # Categorize counts
    category_counts: dict[str, int] = {spec[0]: 0 for spec in RIVEN_CATEGORY_SPECS}
    for r in rivens_data:
        cat = classify_riven_category(r.get("weaponType", ""))
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Duplicate audit
    from collections import defaultdict
    by_weapon = defaultdict(list)
    for r in rivens_data:
        w_name = r.get("weaponName", "Unknown")
        by_weapon[w_name].append(r)

    duplicate_weapons = {w: rivs for w, rivs in by_weapon.items() if len(rivs) >= 2}

    # Veiled & Challenge inventory from mods_data
    pure_veiled: list[dict[str, Any]] = []
    challenge_veiled: list[dict[str, Any]] = []

    if mods_data and isinstance(mods_data, list):
        for m in mods_data:
            if not isinstance(m, dict):
                continue
            name = m.get("name", "")
            if not name:
                continue
            if name.endswith("(Veiled)"):
                pure_veiled.append(m)
            elif (
                name.endswith("Riven Mod")
                and m.get("currentModRank") == 0
                and m.get("modRankMax") == 5
            ):
                challenge_veiled.append(m)

    pure_veiled.sort(key=lambda m: m.get("name", "").casefold())
    challenge_veiled.sort(key=lambda m: m.get("name", "").casefold())

    total_pure_veiled = sum(m.get("amountOwned", 1) for m in pure_veiled)
    total_challenge_veiled = sum(m.get("amountOwned", 1) for m in challenge_veiled)

    lines = [
        "# Riven Inventory Overview",
        "",
        f"_Generated by `update_notebook_source.py` on {generated_at}._",
        "",
        "## 📊 Summary Statistics",
        f"- **Total Unveiled Rivens**: **{total_unveiled}**",
        f"- **Unrolled Rivens (0 Rerolls)**: **{unrolled_count}** ({unrolled_pct:.1f}%)",
        f"- **Rolled Rivens (1+ Rerolls)**: **{rolled_count}** ({100.0 - unrolled_pct:.1f}%)",
        f"- **Pure Veiled Rivens (Stacked)**: **{total_pure_veiled}**",
        f"- **Veiled Rivens with Active Challenge**: **{total_challenge_veiled}**",
        f"- **Total Riven Mod Capacity Tracked**: **{total_unveiled + total_challenge_veiled + total_pure_veiled}**",
        "",
        "## ⚔️ Breakdown by Weapon Class",
        f"- **Rifles, Bows, Snipers & Launchers**: **{category_counts.get('rifles', 0)}** (`rivens-rifles.md`)",
        f"- **Shotguns**: **{category_counts.get('shotguns', 0)}** (`rivens-shotguns.md`)",
        f"- **Pistols & Secondaries**: **{category_counts.get('pistols', 0)}** (`rivens-pistols.md`)",
        f"- **Melee Weapons**: **{category_counts.get('melee', 0)}** (`rivens-melee.md`)",
        f"- **Modular Weapons (Kitguns & Zaws)**: **{category_counts.get('modular', 0)}** (`rivens-modular.md`)",
        "",
        "## 👥 Duplicate Audit (Weapons with 2+ Rivens Owned)",
    ]

    if not duplicate_weapons:
        lines.append("_No duplicate rivens owned._")
    else:
        for w_name in sorted(duplicate_weapons.keys(), key=lambda x: x.casefold()):
            rivs = duplicate_weapons[w_name]
            lines.append(f"- **{w_name}** ({len(rivs)} Rivens owned):")
            for r in rivs:
                r_name = r.get("name", "Unknown")
                rolls = r.get("rerollCount", 0)
                tag = "unrolled" if rolls == 0 else f"{rolls} rolls"
                lines.append(f"  - `{r_name}` — {tag}")

    lines.extend([
        "",
        "## 🔒 Veiled & Challenge Inventory (from inventoryMods.json)",
        "",
        "### Pure Veiled Mods (Stacked)",
    ])

    if not pure_veiled:
        lines.append("_No pure veiled rivens in inventory._")
    else:
        for m in pure_veiled:
            m_name = m.get("name", "Veiled Mod")
            count = m.get("amountOwned", 1)
            lines.append(f"- **{m_name}**: {count} owned")
        lines.append(f"- **Total Pure Veiled**: {total_pure_veiled}")

    lines.extend([
        "",
        "### Veiled Mods with Active Challenge (Rank 0/5)",
    ])

    if not challenge_veiled:
        lines.append("_No veiled rivens with active challenge in inventory._")
    else:
        for m in challenge_veiled:
            m_name = m.get("name", "Riven Mod")
            c_rank = m.get("currentModRank", 0)
            m_rank = m.get("modRankMax", 5)
            equipped = m.get("modUsedBy") or "Unequipped"
            lines.append(f"- **{m_name}** (Rank: {c_rank}/{m_rank}) — Equipped: `{equipped}`")
        lines.append(f"- **Total Active Challenge**: {total_challenge_veiled}")

    lines.append("")
    return "\n".join(lines)


MOD_CATEGORY_SPECS = [
    ("warframe", "mods-warframe.md", "Warframe Mods (Stats, Auras, Exilus & Augments)"),
    ("shotguns", "mods-shotguns.md", "Shotgun Mods"),
    ("rifles", "mods-rifles.md", "Rifle, Bow, Sniper & Launcher Mods"),
    ("pistols", "mods-pistols.md", "Pistol, Secondary & Grimoire/Tome Mods"),
    ("melee", "mods-melee.md", "Melee Mods & Stances"),
    ("companions", "mods-companions.md", "Companion, Sentinel & Beast Mods"),
    ("archwing", "mods-archwing.md", "Archwing, Heavy Archgun & Archmelee Mods"),
    ("specialized", "mods-specialized.md", "Specialized Mods (Necramech, Railjack, Parazon, Requiem & Peculiars)"),
]


def classify_mod_category(m: dict[str, Any]) -> str:
    iname = m.get("internalName", "")

    # 1. Archwing (Must check before generic Rifle/Melee because Archguns have /Archwing/Rifle and Archmelee has /Archwing/Melee)
    if "/Mods/Archwing/" in iname or "Archwing" in iname or "Arch-Gun" in iname or "Arch-Melee" in iname:
        return "archwing"

    # 2. Warframe / Powersuit / Aura / Exilus / Drift
    if (
        "/Powersuits/" in iname
        or "/Mods/Warframe/" in iname
        or "/Mods/Aura/" in iname
        or "/Mods/OrokinChallenge/" in iname
        or "Warframe" in iname
        or "Exilus" in iname
        or "Carapace" in iname
    ):
        return "warframe"

    # 3. Shotgun
    if "/Mods/Shotgun/" in iname or "Shotgun" in iname:
        return "shotguns"

    # 4. Rifle / Bow / Sniper / Launcher / Primary
    if (
        "/Mods/Rifle/" in iname
        or "/Mods/Bows/" in iname
        or "Primary" in iname
        or "Rifle" in iname
        or "Sniper" in iname
    ):
        return "rifles"

    # 5. Pistol / Secondary / Grimoire / Tomes
    if (
        "/Mods/Pistol/" in iname
        or "Secondary" in iname
        or "/Grimoire/" in iname
        or "Pistol" in iname
    ):
        return "pistols"

    # 6. Melee / Stances
    if (
        "/Mods/Melee/" in iname
        or "/Weapons/Tenno/Melee" in iname
        or "HeavyMelee" in iname
        or "Melee" in iname
    ):
        return "melee"

    # 7. Companion / Sentinel / Pets / Beasts
    if (
        "/Mods/Sentinel/" in iname
        or "/Sentinels/" in iname
        or "/Pets/" in iname
        or "Sentinel" in iname
        or "Companion" in iname
        or "Kubrow" in iname
        or "Kavat" in iname
        or "Pet" in iname
        or "Beast" in iname
    ):
        return "companions"

    # 8. Specialized
    return "specialized"


def format_mod_card(m: dict[str, Any]) -> str:
    name = m.get("name") or "Unknown Mod"
    cur_rank = m.get("currentModRank", 0)
    max_rank = m.get("modRankMax", 0)
    owned = m.get("amountOwned", 1)
    mod_type = (m.get("modType") or "").capitalize()
    equipped = m.get("modUsedBy") or ""
    sell_price = m.get("sellPrice", 0)

    rank_str = f"Rank: {cur_rank}/{max_rank}"
    if max_rank > 0 and cur_rank == max_rank:
        rank_str += " [Max]"

    type_str = f" | Type: {mod_type}" if mod_type else ""
    mkt_str = f" | Market: ~{sell_price}p" if sell_price > 0 else ""

    header = f"- **{name}** — {rank_str} | Owned: {owned}{type_str}{mkt_str}"
    lines = [header]
    if equipped:
        lines.append(f"  - `{equipped}`")

    return "\n".join(lines)


def build_mods_category_markdown(
    category_title: str,
    mods: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# Mods — {category_title}",
        "",
        f"_Generated by `update_notebook_source.py` on {generated_at}._",
        "",
        f"Total {category_title} Mod Cards: **{len(mods)}**",
        "",
        "## Mod Inventory",
        "",
    ]
    if not mods:
        lines.append("_No mods found in this category._")
    else:
        for m in mods:
            lines.append(format_mod_card(m))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_mods_overview_markdown(mods_data: list[dict[str, Any]]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_cards = len(mods_data)
    total_quantity = sum(m.get("amountOwned", 1) for m in mods_data)
    unique_names = {m.get("name") for m in mods_data if m.get("name")}

    max_ranked = sum(1 for m in mods_data if m.get("modRankMax", 0) > 0 and m.get("currentModRank") == m.get("modRankMax"))
    unranked = sum(1 for m in mods_data if m.get("currentModRank", 0) == 0)

    cat_counts = {spec[0]: 0 for spec in MOD_CATEGORY_SPECS}
    for m in mods_data:
        cat = classify_mod_category(m)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    equipped_mods = [m for m in mods_data if m.get("modUsedBy")]

    primed_mods = [m for m in mods_data if "primed" in (m.get("modType") or "").lower() or "primed" in (m.get("name") or "").lower()]
    galvanized_mods = [m for m in mods_data if "galvanized" in (m.get("name") or "").lower()]
    archon_mods = [m for m in mods_data if "archon" in (m.get("name") or "").lower()]

    from collections import defaultdict
    name_to_total_owned = defaultdict(int)
    for m in mods_data:
        name_to_total_owned[m.get("name", "Unknown")] += m.get("amountOwned", 1)

    top_duplicates = sorted(
        [(name, qty) for name, qty in name_to_total_owned.items() if qty >= 10],
        key=lambda x: x[1],
        reverse=True,
    )[:15]

    lines = [
        "# Mod Inventory Overview",
        "",
        f"_Generated by `update_notebook_source.py` on {generated_at}._",
        "",
        "## 📊 Summary Statistics",
        f"- **Total Mod Cards Tracked**: **{total_cards}**",
        f"- **Total Quantity Owned (including duplicate stacks)**: **{total_quantity:,}** mods",
        f"- **Unique Mod Names**: **{len(unique_names)}**",
        f"- **Max-Ranked Mods**: **{max_ranked}**",
        f"- **Unranked Mods (Rank 0)**: **{unranked}**",
        f"- **Currently Equipped Mods**: **{len(equipped_mods)}**",
        "",
        "## ⚔️ Breakdown by Category",
    ]
    for cat_key, cat_file, cat_title in MOD_CATEGORY_SPECS:
        lines.append(f"- **{cat_title}**: **{cat_counts.get(cat_key, 0)}** (`{cat_file}`)")

    lines.extend([
        "",
        "## 🌟 High-Tier & Specialized Mod Audit",
        f"- **Primed Mods**: **{len(primed_mods)}** cards owned",
        f"- **Galvanized Mods**: **{len(galvanized_mods)}** cards owned",
        f"- **Archon Mods**: **{len(archon_mods)}** cards owned",
        "",
        "## ♻️ Top Duplicate Stacks (Potential Endo / Credit Dissolution)",
    ])

    if not top_duplicates:
        lines.append("_No large duplicate mod stacks._")
    else:
        for name, qty in top_duplicates:
            lines.append(f"- **{name}**: **{qty}** copies owned")

    lines.append("")
    return "\n".join(lines)


BUILD_CATEGORY_SPECS = [
    ("warframes", "builds-warframes.md", "Warframe Loadouts"),
    ("shotguns", "builds-shotguns.md", "Shotgun Loadouts"),
    ("rifles", "builds-rifles.md", "Rifle, Bow & Sniper Loadouts"),
    ("pistols", "builds-pistols.md", "Secondary & Pistol Loadouts"),
    ("melee", "builds-melee.md", "Melee Weapon Loadouts"),
    ("companions", "builds-companions.md", "Companion & Sentinel Loadouts"),
    ("archwing", "builds-archwing.md", "Archwing, Heavy & Necramech Loadouts"),
]


def match_weapon_variant(base_weapon: str, equipped_item: str) -> bool:
    bw = base_weapon.strip().casefold()
    ei = equipped_item.strip().casefold()
    if bw == ei:
        return True
    prefixes = [
        "kuva ", "tenet ", "prisma ", "vandal ", "wraith ", "coda ",
        "telos ", "synoid ", "secura ", "rakta ", "sancti ", "vaykor ",
        "mara ", "dex ", "mutalist ", "carmine "
    ]
    suffixes = [" prime", " vandal", " wraith", " prisma", " dex", " coda"]
    for p in prefixes:
        if ei.startswith(p):
            ei = ei[len(p):].strip()
    for s in suffixes:
        if ei.endswith(s):
            ei = ei[:-len(s)].strip()
    return bw == ei


def extract_arsenal_builds(
    mods_data: list[dict[str, Any]],
    foundry_data: list[dict[str, Any]],
    rivens_data: list[dict[str, Any]] | None = None,
) -> dict[str, list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]]:
    from collections import defaultdict
    foundry_map = {item.get("name"): item.get("type") for item in foundry_data if isinstance(item, dict)}

    # Reverse-map modUsedBy into item -> mods
    builds_raw = defaultdict(list)
    for m in mods_data:
        if not isinstance(m, dict):
            continue
        used_str = m.get("modUsedBy", "")
        if not used_str.startswith("Equipped in"):
            continue
        raw = used_str[len("Equipped in"):].strip()
        m_other = re.search(r"\s+and\s+(\d+)\s+other item\(s\)", raw)
        if m_other:
            raw = raw[:m_other.start()].strip()
        for x in raw.split(","):
            item_name = x.strip()
            if item_name and not item_name.endswith("other item(s)"):
                builds_raw[item_name].append(m)

    # Pre-index rivens by weaponName
    rivens_by_weapon = defaultdict(list)
    if rivens_data:
        for r in rivens_data:
            if isinstance(r, dict):
                w_name = r.get("weaponName", "")
                if w_name:
                    rivens_by_weapon[w_name].append(r)

    categorized_builds: dict[str, list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]] = {
        spec[0]: [] for spec in BUILD_CATEGORY_SPECS
    }

    for item_name, mod_list in builds_raw.items():
        ftype = foundry_map.get(item_name)
        if item_name in {"Voidrig", "Bonewidow"} or any(
            "/Mods/Necromech/" in m.get("internalName", "") or "Necramech" in m.get("name", "")
            for m in mod_list
        ):
            cat = "archwing"
        elif ftype == "warframe":
            cat = "warframes"
        elif ftype == "melee":
            cat = "melee"
        elif ftype == "secondary":
            cat = "pistols"
        elif ftype == "companion":
            cat = "companions"
        elif ftype == "arch":
            cat = "archwing"
        elif ftype == "primary":
            is_shotgun = any(
                "/Mods/Shotgun/" in m.get("internalName", "") or "Shotgun" in m.get("internalName", "")
                for m in mod_list
            )
            cat = "shotguns" if is_shotgun else "rifles"
        else:
            cat = "rifles"

        # Match owned rivens for this weapon
        matched_rivens = []
        for r_base_name, r_list in rivens_by_weapon.items():
            if match_weapon_variant(r_base_name, item_name):
                matched_rivens.extend(r_list)

        # Sort mods by rank descending, then name
        mod_list_sorted = sorted(
            mod_list,
            key=lambda x: (
                -(x.get("currentModRank") or 0),
                (x.get("name") or "").casefold(),
            ),
        )
        categorized_builds[cat].append((item_name, mod_list_sorted, matched_rivens))

    # Sort items alphabetically in each category
    for cat in categorized_builds:
        categorized_builds[cat].sort(key=lambda t: t[0].casefold())

    return categorized_builds


ARCHON_SHARD_NAMES = {
    "red": "Crimson Archon Shard",
    "red_mythic": "Tauforged Crimson Archon Shard",
    "blue": "Azure Archon Shard",
    "blue_mythic": "Tauforged Azure Archon Shard",
    "yellow": "Amber Archon Shard",
    "yellow_mythic": "Tauforged Amber Archon Shard",
    "purple": "Violet Archon Shard",
    "purple_mythic": "Tauforged Violet Archon Shard",
    "green": "Emerald Archon Shard",
    "green_mythic": "Tauforged Emerald Archon Shard",
    "orange": "Topaz Archon Shard",
    "orange_mythic": "Tauforged Topaz Archon Shard",
}

WARFRAME_AURAS = {
    "brief respite", "corrosive projection", "emp aura", "energy siphon",
    "loot detector", "physique", "ready steel", "rifle amp", "rifle scavenger",
    "shepherd", "sprint boost", "steel charge", "aerodynamic", "combat discipline",
    "growing power", "melee guidance", "power donation", "swift momentum", "holster amp",
    "pistol amp", "shotgun amp", "stand united", "speed holster", "toxin resistance",
    "flame repellent", "rejuvenation", "infestation impedance", "empowered blades",
}

WARFRAME_EXILUS = {
    "primed sure footed", "sure footed", "handspring", "rush", "mobilize", "patagium",
    "controlled slide", "thief's wit", "vigilante pursuit", "preparation", "aviator",
    "aero vantage", "pain threshold", "coaction drift", "cunning drift", "endurance drift",
    "power drift", "speed drift", "stealth drift", "agility drift", "boreal's anguish",
    "amar's anguish", "nira's anguish", "firewalker", "ice spring", "toxic flight",
    "lightning dash", "battering maneuver", "rending turn", "piercing step", "shock absorbers",
    "warm coat", "diamond skin", "insulation", "lightning rod", "antitoxin",
}

BUILD_SLOT_GROUPS: dict[str, list[tuple[str, str]]] = {
    "warframes": [
        ("auras", "🌟 Aura Candidates (1 per Config)"),
        ("exilus", "⚡ Exilus Candidates (1 per Config)"),
        ("augments", "🔮 Ability Augments"),
        ("sets", "🛡️ Umbral & Set Enhancements"),
        ("core", "📊 Core Stat Shapers"),
    ],
    "melee": [
        ("stances", "🥋 Stance Slot"),
        ("exilus", "⚡ Tennokai & Exilus"),
        ("combo", "🩸 Combo & Scaling Engine"),
        ("core", "⚔️ Core Damage, Speed & Elementals"),
    ],
    "shotguns": [
        ("exilus", "⚡ Exilus Slot"),
        ("multishot", "💥 Galvanized & Multishot"),
        ("crit_status", "🎯 Critical & Status Engine"),
        ("core", "📊 Core Damage & Elementals"),
    ],
    "rifles": [
        ("exilus", "⚡ Exilus Slot"),
        ("multishot", "💥 Galvanized & Multishot"),
        ("crit_status", "🎯 Critical & Status Engine"),
        ("core", "📊 Core Damage & Elementals"),
    ],
    "pistols": [
        ("exilus", "⚡ Exilus Slot"),
        ("multishot", "💥 Galvanized & Multishot"),
        ("crit_status", "🎯 Critical & Status Engine"),
        ("core", "📊 Core Damage & Elementals"),
    ],
    "companions": [
        ("precepts", "🐾 Precepts & Unique Abilities"),
        ("survival", "🛡️ Survival & Utility"),
        ("core", "⚔️ Weapon & Offense Mods"),
    ],
    "archwing": [
        ("survival", "🛡️ Suit & Defense"),
        ("mobility", "⚡ Mobility & Efficiency"),
        ("abilities", "🔮 Abilities & Power"),
        ("core", "⚔️ Heavy Weapon Mods"),
    ],
}


def format_archon_shards(raw_shards: Any) -> list[str]:
    """Extract and format installed Archon Shards into grouped bullets."""
    if not raw_shards:
        return []
    flat = []
    if isinstance(raw_shards, list):
        for item in raw_shards:
            if isinstance(item, list):
                flat.extend([s for s in item if isinstance(s, dict)])
            elif isinstance(item, dict):
                flat.append(item)
    if not flat:
        return []
    from collections import Counter, defaultdict
    counts = Counter()
    texts = {}
    for s in flat:
        stype = s.get("type", "unknown")
        stext = s.get("text", "")
        key = (stype, stext)
        counts[key] += 1
        texts[key] = stext
    lines = []
    for (stype, stext), count in counts.items():
        sname = ARCHON_SHARD_NAMES.get(stype, stype.replace("_", " ").title() + " Shard")
        count_prefix = f"{count}x " if count > 1 else ""
        text_desc = f": `{stext}`" if stext else ""
        lines.append(f"  - {count_prefix}**{sname}**{text_desc}")
    return lines


def classify_item_mod(mod: dict[str, Any], category_key: str) -> str:
    """Classify an equipped mod into a functional slot group for its item category."""
    name = (mod.get("name") or "").casefold()
    iname = mod.get("internalName") or ""

    if category_key == "warframes":
        if "/Mods/Aura/" in iname or mod.get("type") == "Aura" or name.endswith(" aura") or name in WARFRAME_AURAS:
            return "auras"
        if (
            "/OrokinChallenge/" in iname
            or "/BorealExilusMod" in iname
            or "/AmarExilusMod" in iname
            or "/NiraExilusMod" in iname
            or name in WARFRAME_EXILUS
        ):
            return "exilus"
        if iname.endswith("AugmentCard") or iname.endswith("AugmentTwoCard") or "/Augment" in iname:
            return "augments"
        if (
            "/Mods/Sets/" in iname
            or name.startswith("umbral ")
            or name.startswith("archon ")
            or name.startswith("sacrificial ")
        ):
            return "sets"
        return "core"

    elif category_key == "melee":
        if "/MeleeTrees/" in iname or iname.endswith("MeleeTree") or "/Stances/" in iname or name.endswith(" stance"):
            return "stances"
        if "tennokai" in iname.casefold() or name in {
            "opportunity's reach", "dreamer's wrath", "discipline's merit",
            "master's edge", "condition's perfection", "whirlwind"
        }:
            return "exilus"
        if (
            name in {
                "blood rush", "weeping wounds", "condition overload",
                "gladiator might", "gladiator rush", "sacrificial steel",
                "sacrificial pressure", "drifting contact", "maiming strike"
            }
            or "/Event/Combo" in iname
            or "WeaponDamageIfVictimProcActive" in iname
        ):
            return "combo"
        return "core"

    elif category_key in {"shotguns", "rifles", "pistols"}:
        if "exilus" in iname.casefold() or name in {
            "vigilante supplies", "terminal velocity", "sinister reach", "hush",
            "stabilizer", "rifle ammo mutation", "primed rifle ammo mutation",
            "arrow mutation", "primed arrow mutation", "cautious shot", "aero agility",
            "shotgun ammo mutation", "primed shotgun ammo mutation", "silent battery",
            "fatal acceleration", "lock and load", "narrow barrel", "lethal momentum",
            "ruinous extension", "spry sights", "eject magazine", "target acquired",
            "pistol ammo mutation", "primed pistol ammo mutation", "suppress", "steady hands"
        }:
            return "exilus"
        if name.startswith("galvanized ") or name in {
            "hell's chamber", "split chamber", "barrel diffusion", "lethal torrent",
            "vigilante armaments", "amalgam barrel diffusion"
        } or "SPMod" in iname:
            return "multishot"
        if "crit" in iname.casefold() or "dualstat" in iname.casefold() or name in {
            "vital sense", "point strike", "critical delay", "blunderbuss",
            "primed ravage", "ravage", "critical deceleration", "hunter munitions",
            "target cracker", "primed target cracker", "pistol gambit",
            "primed pistol gambit", "creeping bullseye", "internal bleeding",
            "hemorrhage", "chilling reload", "seeking fury", "toxic barrage",
            "frigid blast", "scattering virulence", "shell shock", "scattering inferno",
            "malignant force", "rime rounds", "high voltage", "thermite rounds",
            "pistol pestilence", "frostbite", "jolt", "scorch", "carnis stinger"
        }:
            return "crit_status"
        return "core"

    elif category_key == "companions":
        if "Precept" in iname or "bond" in name or name in {
            "vacuum", "fetch", "assault mode", "synth deconstruct", "synth fiber",
            "tenacious bond", "reinforced bond", "duplex bond", "momentous bond",
            "aerial bond", "restorative bond", "bite", "maul", "link health",
            "link shields", "link armor", "medi-ray", "animal instinct",
            "primed animal instinct", "charm", "cat's eye", "ghost", "striker",
            "revenge", "crowd dispersion", "electro pulse", "arc coil", "thumper",
            "warrior", "fatal attraction", "anti-grav array", "vaporize"
        }:
            return "precepts"
        if any(k in iname for k in ("Health", "Shield", "Armour")) or name in {
            "calculated redirection", "enhanced vitality", "metal fiber", "repair kit"
        }:
            return "survival"
        return "core"

    elif category_key == "archwing":
        if any(k in iname for k in ("Health", "Shield", "Armour")) or name in {
            "necramech steel fiber", "necramech vitality", "necramech redirection",
            "enhanced durability", "energy inversion"
        }:
            return "survival"
        if name in {
            "necramech friction", "necramech blitz", "necramech thrusters",
            "necramech drift", "necramech efficiency", "hyperion thrusters", "superior defenses"
        }:
            return "mobility"
        if name in {
            "necramech intensify", "necramech streamline", "necramech continuity",
            "system reroute", "energy amplifier", "morphic transformer"
        }:
            return "abilities"
        return "core"

    return "core"


def build_loadout_category_markdown(
    category_key: str,
    category_title: str,
    item_builds: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]],
    archon_shards_map: dict[str, Any] | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# Arsenal Loadouts — {category_title}",
        "",
        f"_Generated by `update_notebook_source.py` on {generated_at}._",
        "",
        f"Total Configured {category_title}: **{len(item_builds)}**",
        "",
        "> [!NOTE]",
        "> Reconstructed from active `inventoryMods.json` and `rivens.json` exports. Items with >8 mods reflect your complete modding pool across active configurations (Config A, B, and C), organized into functional slot roles (Auras, Exilus, Augments, Sets, and Core).",
        "",
        "## Loadouts",
        "",
    ]
    if not item_builds:
        lines.append("_No loadouts found in this category._")
    else:
        slot_groups = BUILD_SLOT_GROUPS.get(category_key, [("core", "📊 Equipped Mods")])
        for item_name, mod_list, riven_list in item_builds:
            header_text = f"### {item_name} ({len(mod_list)} Mods Equipped"
            if len(mod_list) > 8:
                header_text += " Across Active Configs)"
            else:
                header_text += ")"
            lines.append(header_text)

            # 1. Archon shards if available for this item
            if archon_shards_map and item_name in archon_shards_map:
                shard_lines = format_archon_shards(archon_shards_map[item_name])
                if shard_lines:
                    lines.append("- 💎 **Installed Archon Shards**:")
                    lines.extend(shard_lines)

            # 2. Group mods by functional slot
            grouped_mods = defaultdict(list)
            for m in mod_list:
                grp_key = classify_item_mod(m, category_key)
                grouped_mods[grp_key].append(m)

            for grp_key, grp_title in slot_groups:
                mods_in_grp = grouped_mods.get(grp_key, [])
                if not mods_in_grp:
                    continue
                lines.append(f"- {grp_title}:")
                for m in mods_in_grp:
                    m_name = m.get("name", "Unknown Mod")
                    cur_r = m.get("currentModRank", 0)
                    max_r = m.get("modRankMax", 0)
                    m_type = (m.get("modType") or "").capitalize()
                    rank_str = f"Rank: {cur_r}/{max_r}" + (" [Max]" if max_r and cur_r == max_r else "")
                    type_str = f", Type: {m_type}" if m_type else ""
                    lines.append(f"  - **{m_name}** ({rank_str}{type_str})")

            # 3. Append owned Rivens
            if riven_list:
                if len(riven_list) == 1:
                    r = riven_list[0]
                    r_name = r.get("name", "Riven")
                    rolls = r.get("rerollCount", 0)
                    roll_str = "unrolled" if rolls == 0 else f"{rolls} rolls"
                    lines.append(f"- 🔮 **Owned Riven**: `{item_name} {r_name}` ({roll_str})")
                else:
                    lines.append("- 🔮 **Owned Rivens**:")
                    for r in riven_list:
                        r_name = r.get("name", "Riven")
                        rolls = r.get("rerollCount", 0)
                        roll_str = "unrolled" if rolls == 0 else f"{rolls} rolls"
                        lines.append(f"  - `{item_name} {r_name}` ({roll_str})")

            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_loadouts_overview_markdown(
    categorized_builds: dict[str, list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]],
    archon_shards_map: dict[str, Any] | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_items = sum(len(items) for items in categorized_builds.values())
    total_mod_instances = sum(
        len(mod_list)
        for items in categorized_builds.values()
        for _, mod_list, _ in items
    )
    total_rivens_embedded = sum(
        len(riven_list)
        for items in categorized_builds.values()
        for _, _, riven_list in items
    )
    shards_frame_count = len(archon_shards_map) if archon_shards_map else 0

    all_items = [
        (item_name, len(mod_list), cat_spec[2])
        for cat_spec in BUILD_CATEGORY_SPECS
        for item_name, mod_list, _ in categorized_builds.get(cat_spec[0], [])
    ]
    top_modded = sorted(all_items, key=lambda x: x[1], reverse=True)[:15]

    lines = [
        "# Arsenal Loadouts & Builds Overview",
        "",
        f"_Generated by `update_notebook_source.py` on {generated_at}._",
        "",
        "## 📊 Reconstructed Arsenal Summary",
        f"- **Total Configured Items**: **{total_items}** items with active equipped mods",
        f"- **Total Equipped Mod Slots Tracked**: **{total_mod_instances}** mod instances",
        f"- **Owned Rivens Embedded in Loadouts**: **{total_rivens_embedded}** matching weapon rivens",
        f"- **Warframes with Installed Archon Shards**: **{shards_frame_count}** frames",
        "",
        "## ⚔️ Loadout Breakdown by Category",
    ]
    for cat_key, cat_file, cat_title in BUILD_CATEGORY_SPECS:
        count = len(categorized_builds.get(cat_key, []))
        lines.append(f"- **{cat_title}**: **{count}** loadouts (`{cat_file}`)")

    lines.extend([
        "",
        "## 🏆 Top Modded Items (Most Comprehensive Reconstructed Builds)",
    ])
    for item_name, mod_count, cat_name in top_modded:
        lines.append(f"- **{item_name}** ({cat_name}): **{mod_count}** equipped mods tracked")

    lines.extend([
        "",
        "## 💡 Architecture & Modding Notes",
        "- **Functional Slot Categorization**: Equipped mods are grouped by role (Auras, Exilus, Augments, Sets/Umbral, Galvanized/Multishot, Combo, and Core Stats) to distinguish build components across configs.",
        "- **Multi-Config Aggregation**: Items with >8 mods reflect your total mod pool invested across active configurations (Config A, B, and C).",
        "- **Archon Shards Tracking**: Warframes cross-reference `foundry.json` to report installed Crimson, Azure, Amber, Violet, Emerald, and Topaz Archon Shards (including Tauforged variants).",
        "- **Riven Integration**: Each weapon automatically cross-references and embeds matching owned Rivens from `rivens.json`.",
        "- **Staple Mod Truncation**: High-frequency staple mods (such as base Serration or Vitality) shared across 20+ weapons are exported by AlecaFrame with trailing counts, while weapon-specific, rare, Galvanized, Primed, and Augment mods are captured with full fidelity.",
        "",
    ])
    return "\n".join(lines)


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
    parser.add_argument(
        "--drive-dir",
        type=Path,
        default=Path(r"G:\Mi unidad\WF_DATA"),
        help=r"Google Drive destination folder for flat Markdown copies (default: G:\Mi unidad\WF_DATA).",
    )
    parser.add_argument(
        "--skip-drive-copy",
        action="store_true",
        help="Skip auto-copying Markdown files to Google Drive.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the workflow and Google Drive copy without copying files to Drive.",
    )
    parser.add_argument(
        "--no-desktop-sync",
        action="store_true",
        help="Skip searching the Desktop directory for newly exported JSON files.",
    )
    parser.add_argument(
        "--desktop-dir",
        type=Path,
        default=None,
        help="Custom folder to check for exported AlecaFrame JSON files (defaults to Desktop).",
    )
    args = parser.parse_args()

    directory = args.directory.resolve()
    output = (args.output or directory / "combined.md").resolve()
    split_output_dir = (
        args.split_output_dir or directory / "notebook_sources"
    ).resolve()

    # Automatically check Desktop for new AlecaFrame JSON exports
    if not args.no_desktop_sync:
        custom_dirs = [args.desktop_dir.resolve()] if args.desktop_dir else None
        copied = sync_desktop_exports(directory, search_dirs=custom_dirs)
        if copied:
            for src_p, dst_p in copied:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Detected updated {src_p.name} on Desktop -> Copied to {directory.name}/",
                    file=sys.stderr,
                )
    CONFIG_JSON_NAMES = {"sync_tokens.json", "package.json", "tsconfig.json"}
    json_files = sorted(
        [p for p in directory.glob("*.json") if p.name.casefold() not in CONFIG_JSON_NAMES],
        key=lambda path: path.name.casefold(),
    )
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
        combined_split = split_output_dir / "combined.md"
        write_atomically(combined_split, markdown)
        generated_split_files.add(combined_split)
        for filename, data in current.items():
            if filename == "rivens.json" and isinstance(data, list):
                # 1. Deterministic Category Split Routing (5 files)
                categorized_rivens: dict[str, list[dict[str, Any]]] = {
                    spec[0]: [] for spec in RIVEN_CATEGORY_SPECS
                }
                for r in data:
                    if isinstance(r, dict):
                        cat = classify_riven_category(r.get("weaponType", ""))
                        categorized_rivens[cat].append(r)

                for cat_key, split_filename, cat_title in RIVEN_CATEGORY_SPECS:
                    cat_items = categorized_rivens[cat_key]
                    cat_items.sort(
                        key=lambda x: (
                            (x.get("weaponName") or "").casefold(),
                            (x.get("name") or "").casefold(),
                        )
                    )
                    split_path = split_output_dir / split_filename
                    md_content = build_riven_category_markdown(cat_title, cat_items)
                    write_atomically(split_path, md_content)
                    generated_split_files.add(split_path)
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Generated {split_filename} ({len(cat_items)} rivens)",
                        file=sys.stderr,
                    )

                # 2. Dedicated Overview File (rivens-overview.md)
                mods_data = current.get("inventoryMods.json", [])
                overview_md = build_riven_overview_markdown(data, mods_data)
                overview_path = split_output_dir / "rivens-overview.md"
                write_atomically(overview_path, overview_md)
                generated_split_files.add(overview_path)
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Generated rivens-overview.md",
                    file=sys.stderr,
                )

                # 3. Generate riven_intelligence.md
                try:
                    from riven_tracker import (
                        parse_riven_record,
                        RivenMarketClient,
                        generate_riven_intelligence_markdown,
                    )
                    rivens_objs = [parse_riven_record(r) for r in data if isinstance(r, dict)]
                    r_client = None if args.skip_market else RivenMarketClient()
                    p_weapons: set[str] = {r.weapon_name.casefold() for r in rivens_objs if r.grade == "Perfect"}
                    for r in rivens_objs:
                        if len(p_weapons) >= 6:
                            break
                        if r.grade == "Good" and r.is_meta_weapon:
                            p_weapons.add(r.weapon_name.casefold())

                    riven_intel_md = generate_riven_intelligence_markdown(
                        rivens=rivens_objs,
                        market_client=r_client,
                        price_check_weapons=p_weapons,
                    )
                    intel_path = split_output_dir / "riven_intelligence.md"
                    write_atomically(intel_path, riven_intel_md)
                    generated_split_files.add(intel_path)
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Generated riven intelligence in {intel_path.name}",
                        file=sys.stderr,
                    )
                except Exception as r_err:
                    print(f"Warning: could not generate riven intelligence: {r_err}", file=sys.stderr)
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

            if filename == "inventoryMods.json" and isinstance(data, list):
                # 1. Categorized Mod Inventory Split (8 files)
                categorized_mods: dict[str, list[dict[str, Any]]] = {
                    spec[0]: [] for spec in MOD_CATEGORY_SPECS
                }
                for m in data:
                    if isinstance(m, dict):
                        cat = classify_mod_category(m)
                        categorized_mods[cat].append(m)

                for cat_key, split_filename, cat_title in MOD_CATEGORY_SPECS:
                    cat_items = categorized_mods[cat_key]
                    cat_items.sort(
                        key=lambda x: (
                            (x.get("name") or "").casefold(),
                            -(x.get("currentModRank") or 0),
                        )
                    )
                    split_path = split_output_dir / split_filename
                    md_content = build_mods_category_markdown(cat_title, cat_items)
                    write_atomically(split_path, md_content)
                    generated_split_files.add(split_path)
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Generated {split_filename} ({len(cat_items)} mods)",
                        file=sys.stderr,
                    )

                # 2. Mod Inventory Overview (mods-overview.md)
                mods_overview_md = build_mods_overview_markdown(data)
                mods_overview_path = split_output_dir / "mods-overview.md"
                write_atomically(mods_overview_path, mods_overview_md)
                generated_split_files.add(mods_overview_path)
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Generated mods-overview.md",
                    file=sys.stderr,
                )

                # 3. Reconstruct Arsenal Build Loadouts (builds-*.md)
                foundry_data = current.get("foundry.json", [])
                rivens_data = current.get("rivens.json", [])
                categorized_builds = extract_arsenal_builds(data, foundry_data, rivens_data)

                # Pre-index Archon Shards from foundry_data
                archon_shards_map = {
                    item.get("name"): item.get("archonShards")
                    for item in foundry_data
                    if isinstance(item, dict) and item.get("archonShards")
                }

                for b_key, b_filename, b_title in BUILD_CATEGORY_SPECS:
                    b_items = categorized_builds.get(b_key, [])
                    b_path = split_output_dir / b_filename
                    b_md = build_loadout_category_markdown(
                        category_key=b_key,
                        category_title=b_title,
                        item_builds=b_items,
                        archon_shards_map=archon_shards_map if b_key == "warframes" else None,
                    )
                    write_atomically(b_path, b_md)
                    generated_split_files.add(b_path)
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Generated {b_filename} ({len(b_items)} builds)",
                        file=sys.stderr,
                    )

                # 4. Arsenal Loadouts Overview (builds-overview.md)
                builds_overview_md = build_loadouts_overview_markdown(
                    categorized_builds,
                    archon_shards_map=archon_shards_map,
                )
                builds_overview_path = split_output_dir / "builds-overview.md"
                write_atomically(builds_overview_path, builds_overview_md)
                generated_split_files.add(builds_overview_path)
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Generated builds-overview.md",
                    file=sys.stderr,
                )

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

        stale_split_sources = (
            list(split_output_dir.glob("rivens-*.md"))
            + list(split_output_dir.glob("mods-*.md"))
            + list(split_output_dir.glob("builds-*.md"))
        )
        for legacy_name in ["rivens.md", "inventoryMods.md", "alecaframeStatsExport.md"]:
            legacy_file = split_output_dir / legacy_name
            if legacy_file.exists():
                stale_split_sources.append(legacy_file)

        for stale_path in stale_split_sources:
            if stale_path not in generated_split_files:
                try:
                    stale_path.unlink()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Removed stale source: {stale_path.name}", file=sys.stderr)
                except Exception as err:
                    print(f"Warning removing stale source {stale_path.name}: {err}", file=sys.stderr)

        # Clean up legacy files from active Google Drive sync folders (omit OLD archive)
        if not args.skip_drive_copy and args.drive_dir and args.drive_dir.exists():
            for legacy_pat in ["rivens-00*.md", "rivens.md", "inventoryMods.md"]:
                for stale_drive_file in args.drive_dir.rglob(legacy_pat):
                    if "OLD" in stale_drive_file.parts:
                        continue
                    if stale_drive_file.name not in {p.name for p in generated_split_files}:
                        try:
                            stale_drive_file.unlink()
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Removed legacy file '{stale_drive_file.name}' from active Google Drive.", file=sys.stderr)
                        except Exception as drive_del_err:
                            print(f"Warning deleting legacy file {stale_drive_file.name} from Drive: {drive_del_err}", file=sys.stderr)
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

    # Auto-copy generated Markdown sources directly into Google Drive (structured subfolders)
    if not args.skip_drive_copy:
        try:
            from sync_to_drive import sync_to_drive
            sync_to_drive(
                source_dir=split_output_dir,
                drive_dir=args.drive_dir,
                dry_run=args.dry_run,
                verbose=True,
            )
        except Exception as drive_err:
            print(f"Warning: could not sync to Google Drive: {drive_err}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())