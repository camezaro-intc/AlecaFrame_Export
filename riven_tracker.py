#!/usr/bin/env python3
"""
Warframe Riven Intelligence & Market Valuation Tracker
Analyzes AlecaFrame rivens.json exports and live Warframe.market auctions.
Supports:
1. Instant offline grading, trait analysis & categorization of all Rivens.
2. Targeted live Warframe.market auction pricing (unrolled floor, trash floor, top buyouts).
3. Independent CLI execution with filtering by weapon type, grade, or weapon name.
4. Auto-export to notebook_sources/riven_intelligence.md and Google Drive sync.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API_V2_BASE = "https://api.warframe.market/v2"
API_V1_BASE = "https://api.warframe.market/v1"
USER_AGENT = "AlecaPriceTracker/1.0 (WarframeInventoryBot; Windows)"
CACHE_DIR = Path(".market_cache")
RIVEN_WEAPONS_CACHE = CACHE_DIR / "riven_weapons_catalog.json"
RIVEN_AUCTIONS_CACHE = CACHE_DIR / "riven_auctions_cache.json"
CACHE_TTL_AUCTIONS = 7200  # 2 hours
CACHE_TTL_WEAPONS = 86400  # 24 hours
DEFAULT_DRIVE_DIR = Path(r"G:\Mi unidad\WF_DATA")

# Popular / High-meta weapons where rivens command strong demand
HIGH_META_WEAPONS = {
    # Shotguns
    "arca plasmor", "bubonico", "cedo", "corinth", "strun", "kohm", "felarx", "boar", "exergis",
    # Rifles
    "torid", "burston", "latron", "phenmor", "soma", "amprex", "braton", "miter", "dread",
    "paris", "ignis", "tenora", "nagantaka", "stradavar", "opticor", "synapse", "acceltra",
    # Secondaries
    "dual toxocyst", "furis", "lex", "epitaph", "laetum", "sporelacer", "atomos", "ocucor",
    "akmagnus", "akvasto", "brakk", "detron", "pyrana",
    # Melee
    "magistar", "glaive", "ceramic dagger", "hate", "kronen", "nikana", "reaper prime",
    "dual ichor", "sibear", "innodem", "praedos", "orthos", "guandao", "scindo", "gram",
}


def strip_html(text: Any) -> str:
    if not isinstance(text, str):
        return str(text)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def request_json(url: str, timeout: int = 15) -> Any:
    headers = {
        "User-Agent": USER_AGENT,
        "Platform": "pc",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class RivenMarketClient:
    """Handles Warframe.market riven catalog and live auction queries with caching."""

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.weapons_catalog: dict[str, str] = {}  # weapon_name_lower -> slug
        self.auctions_cache: dict[str, dict[str, Any]] = {}
        self._load_weapons_catalog()
        self._load_auctions_cache()

    def _load_weapons_catalog(self) -> None:
        now = time.time()
        loaded = False
        if RIVEN_WEAPONS_CACHE.exists():
            try:
                cached = json.loads(RIVEN_WEAPONS_CACHE.read_text(encoding="utf-8"))
                if now - cached.get("timestamp", 0) < CACHE_TTL_WEAPONS:
                    self.weapons_catalog = cached.get("data", {})
                    loaded = True
            except Exception:
                pass

        if not loaded:
            try:
                data = request_json(f"{API_V2_BASE}/riven/weapons")
                weapons = data.get("data", [])
                catalog = {}
                for w in weapons:
                    en_name = w.get("i18n", {}).get("en", {}).get("name", "")
                    slug = w.get("slug", "")
                    if en_name and slug:
                        catalog[en_name.casefold()] = slug
                self.weapons_catalog = catalog
                RIVEN_WEAPONS_CACHE.write_text(
                    json.dumps({"timestamp": now, "data": catalog}, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                print(f"Warning: could not fetch riven weapons catalog: {e}", file=sys.stderr)

    def _load_auctions_cache(self) -> None:
        if RIVEN_AUCTIONS_CACHE.exists():
            try:
                self.auctions_cache = json.loads(
                    RIVEN_AUCTIONS_CACHE.read_text(encoding="utf-8")
                )
            except Exception:
                self.auctions_cache = {}

    def _save_auctions_cache(self) -> None:
        try:
            RIVEN_AUCTIONS_CACHE.write_text(
                json.dumps(self.auctions_cache, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"Warning: could not save riven auctions cache: {e}", file=sys.stderr)

    def get_weapon_slug(self, weapon_name: str) -> str | None:
        clean = weapon_name.casefold().strip()
        if clean in self.weapons_catalog:
            return self.weapons_catalog[clean]
        # Fallback slugification
        return re.sub(r"[^a-z0-9]+", "_", clean).strip("_")

    def get_live_auction_stats(self, weapon_name: str) -> dict[str, Any] | None:
        slug = self.get_weapon_slug(weapon_name)
        if not slug:
            return None

        now = time.time()
        cached = self.auctions_cache.get(slug)
        if cached and now - cached.get("timestamp", 0) < CACHE_TTL_AUCTIONS:
            return cached.get("stats")

        url = f"{API_V1_BASE}/auctions/search?type=riven&weapon_url_name={slug}&sort_by=price_asc"
        auctions = None
        for attempt in range(2):
            try:
                time.sleep(0.7)  # Polite throttle
                data = request_json(url)
                auctions = data.get("payload", {}).get("auctions", [])
                break
            except urllib.error.HTTPError as he:
                if he.code == 429 and attempt == 0:
                    time.sleep(2.0)
                    continue
                if cached:
                    return cached.get("stats")
                print(f"Warning: market query for {weapon_name} ({slug}): {he}", file=sys.stderr)
                return None
            except Exception as e:
                if cached:
                    return cached.get("stats")
                print(f"Warning: could not fetch auctions for {weapon_name} ({slug}): {e}", file=sys.stderr)
                return None

        if auctions is None:
            return cached.get("stats") if cached else None

        # Filter for online / ingame sellers with active buyout prices
        active = [
            a for a in auctions
            if a.get("owner", {}).get("status") in ("ingame", "online")
            and a.get("buyout_price")
            and a.get("buyout_price") > 0
            and not a.get("closed")
        ]

        if not active:
            # Fallback to any active listings with buyout
            active = [
                a for a in auctions
                if a.get("buyout_price") and a.get("buyout_price") > 0 and not a.get("closed")
            ]

        if not active:
            stats = {
                "slug": slug,
                "total_auctions": len(auctions),
                "online_auctions": 0,
                "trash_floor": None,
                "unrolled_floor": None,
                "median_buyout": None,
                "sample_auctions": [],
            }
        else:
            buyouts = sorted([a["buyout_price"] for a in active])
            unrolled = sorted([
                a["buyout_price"] for a in active
                if a.get("item", {}).get("re_rolls", 0) == 0
            ])

            trash_floor = buyouts[0] if buyouts else None
            unrolled_floor = unrolled[0] if unrolled else None
            median_buyout = buyouts[len(buyouts) // 2] if buyouts else None

            sample_list = []
            for a in active[:3]:
                mod_name = a.get("item", {}).get("name", "")
                price = a.get("buyout_price", 0)
                rolls = a.get("item", {}).get("re_rolls", 0)
                sample_list.append(f"{mod_name} ({price}p, {rolls} rolls)")

            stats = {
                "slug": slug,
                "total_auctions": len(auctions),
                "online_auctions": len(active),
                "trash_floor": trash_floor,
                "unrolled_floor": unrolled_floor,
                "median_buyout": median_buyout,
                "sample_auctions": sample_list,
            }

        self.auctions_cache[slug] = {"timestamp": now, "stats": stats}
        self._save_auctions_cache()
        return stats


@dataclass
class ParsedRiven:
    weapon_name: str
    riven_name: str
    weapon_type: str
    grade: str
    rerolls: int
    disposition: float
    mr: int
    polarity: str
    positive_traits: list[str]
    negative_traits: list[str]
    action_bucket: str
    raw_record: dict[str, Any]

    @property
    def is_unrolled(self) -> bool:
        return self.rerolls == 0

    @property
    def full_name(self) -> str:
        return f"{self.weapon_name} ({self.riven_name})"

    @property
    def is_meta_weapon(self) -> bool:
        return self.weapon_name.casefold() in HIGH_META_WEAPONS


def parse_riven_record(record: dict[str, Any]) -> ParsedRiven:
    wep_name = record.get("weaponName", "Unknown")
    r_name = record.get("name", "Riven")
    w_type = record.get("weaponType", "Rifle")
    grade = record.get("grade", "Bad")
    rerolls = record.get("rerollCount", 0)
    disp = float(record.get("disposition", 1.0))
    mr = int(record.get("minimumMastery", 8))
    pol = record.get("polarity", "madurai")

    pos_traits: list[str] = []
    neg_traits: list[str] = []

    stats_per_wep = record.get("statsPerWeapon", [])
    if stats_per_wep and isinstance(stats_per_wep, list) and isinstance(stats_per_wep[0], dict):
        by_level = stats_per_wep[0].get("byLevel", [])
        if by_level and isinstance(by_level, list):
            max_level = max(by_level, key=lambda x: x.get("level", 0), default={})
            for t in max_level.get("positiveTraits", []):
                if isinstance(t, dict) and t.get("description"):
                    pos_traits.append(strip_html(t["description"]))
            for t in max_level.get("negativeTraits", []):
                if isinstance(t, dict) and t.get("description"):
                    neg_traits.append(strip_html(t["description"]))

    # Determine Action Bucket
    is_meta = wep_name.casefold() in HIGH_META_WEAPONS
    if grade == "Perfect":
        bucket = "💎 High-Value Sell"
    elif grade == "Good":
        if is_meta or rerolls == 0:
            bucket = "💎 High-Value Sell"
        else:
            bucket = "💎 Ready to Sell / Usable"
    elif is_meta and disp >= 1.05 and rerolls <= 5:
        bucket = "🎯 Kuva Reroll Target"
    elif is_meta and rerolls == 0:
        bucket = "💎 Unrolled Meta Sell"
    elif grade == "HasPotential" and disp >= 1.15:
        bucket = "🎯 Kuva Reroll Target"
    elif rerolls > 0 and not is_meta and disp < 1.0:
        bucket = "♻️ Transmute / Dissolve"
    elif rerolls > 0:
        bucket = "🪙 Quick Trash Sale"
    else:
        bucket = "🪙 Unrolled Trash Sale"

    return ParsedRiven(
        weapon_name=wep_name,
        riven_name=r_name,
        weapon_type=w_type,
        grade=grade,
        rerolls=rerolls,
        disposition=disp,
        mr=mr,
        polarity=pol,
        positive_traits=pos_traits,
        negative_traits=neg_traits,
        action_bucket=bucket,
        raw_record=record,
    )


def load_rivens(file_path: Path) -> list[ParsedRiven]:
    if not file_path.exists():
        return []
    try:
        data = json.loads(file_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            return []
        return [parse_riven_record(r) for r in data if isinstance(r, dict)]
    except Exception as e:
        print(f"Error loading rivens from {file_path}: {e}", file=sys.stderr)
        return []


def format_traits(riven: ParsedRiven) -> str:
    parts = []
    if riven.positive_traits:
        parts.append(", ".join(riven.positive_traits))
    if riven.negative_traits:
        parts.append(f"Curse: {', '.join(riven.negative_traits)}")
    return " | ".join(parts) if parts else "No stat projection available"


def generate_riven_intelligence_markdown(
    rivens: list[ParsedRiven],
    market_client: RivenMarketClient | None = None,
    price_check_weapons: set[str] | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Groupings
    by_type: dict[str, list[ParsedRiven]] = {}
    for r in rivens:
        by_type.setdefault(r.weapon_type, []).append(r)

    by_grade: dict[str, list[ParsedRiven]] = {}
    for r in rivens:
        by_grade.setdefault(r.grade, []).append(r)

    high_value_sell = [r for r in rivens if "High-Value" in r.action_bucket or "Ready to Sell" in r.action_bucket or "Unrolled Meta" in r.action_bucket]
    kuva_targets = [r for r in rivens if "Kuva Reroll" in r.action_bucket]
    transmute_candidates = [r for r in rivens if "Transmute" in r.action_bucket or ("Trash" in r.action_bucket and not r.is_meta_weapon)]

    lines = [
        "# Warframe Riven Intelligence & Market Valuation",
        "",
        f"_Generated on {generated_at} from `rivens.json` exports._",
        "",
        "This document provides strategic pricing intelligence, inventory grading, and sales recommendations for all owned Riven mods.",
        "",
        "## 📊 Executive Inventory Summary",
        "",
        f"- **Total Owned Rivens:** {len(rivens)}",
        f"- **Roll Quality Breakdown:**",
        f"  - 🌟 **Perfect (God Rolls):** {len(by_grade.get('Perfect', []))}",
        f"  - 💎 **Good (Strong Stat Synergies):** {len(by_grade.get('Good', []))}",
        f"  - 🎯 **Has Potential (High Disposition / Solid Base):** {len(by_grade.get('HasPotential', []))}",
        f"  - ♻️ **Bad / Fodder:** {len(by_grade.get('Bad', []))}",
        f"- **Unrolled Rivens (0 Rerolls — High Buyer Premium):** {sum(1 for r in rivens if r.is_unrolled)}",
        f"- **Breakdown by Weapon Class:** " + ", ".join(f"**{k}:** {len(v)}" for k, v in sorted(by_type.items())),
        "",
        "---",
        "",
        "## 💎 Top Value Rivens to Sell",
        "",
        "These Rivens have achieved top-tier grades (`Perfect` or `Good`), meta weapon pairing, or unrolled buyer appeal. Recommended to list on Warframe.market or Trade Chat.",
        "",
    ]

    # Sort high value rivens: Perfect first, then Good on meta weapons, then by weapon name
    def high_value_sort_key(r: ParsedRiven) -> tuple[int, int, str]:
        grade_prio = 0 if r.grade == "Perfect" else (1 if r.is_meta_weapon else 2)
        roll_prio = 0 if r.is_unrolled else 1
        return (grade_prio, roll_prio, r.weapon_name)

    sorted_high_value = sorted(high_value_sell, key=high_value_sort_key)

    if not sorted_high_value:
        lines.append("_No High-Value sellable Rivens found._")
    else:
        for r in sorted_high_value:
            unrolled_badge = " **[UNROLLED — 0 ROLLS]**" if r.is_unrolled else f" (Rolls: {r.rerolls})"
            lines.append(f"### {r.full_name}")
            lines.append(f"- **Class:** {r.weapon_type} | **Grade:** `{r.grade}`{unrolled_badge} | **MR:** {r.mr} | **Disposition:** {r.disposition}x")
            lines.append(f"- **Stats (Max Rank):** {format_traits(r)}")
            lines.append(f"- **Category:** {r.action_bucket}")

            # Fetch live market data if client available
            if market_client and (price_check_weapons is None or r.weapon_name.casefold() in price_check_weapons):
                stats = market_client.get_live_auction_stats(r.weapon_name)
                if stats and stats.get("trash_floor") is not None:
                    t_floor = stats["trash_floor"]
                    u_floor = stats.get("unrolled_floor")
                    med = stats.get("median_buyout")
                    active_count = stats.get("online_auctions", 0)
                    lines.append(f"- **Live Warframe.market Auctions ({active_count} online sellers):**")
                    lines.append(f"  - Trash Floor Buyout: **~{t_floor}p**")
                    if u_floor is not None:
                        lines.append(f"  - Unrolled Buyout Floor: **~{u_floor}p**")
                    if med is not None:
                        lines.append(f"  - Median Active Buyout: **~{med}p**")
                    if r.grade == "Perfect":
                        lines.append(f"  - **God-Roll Valuation:** Estimated **500p–1,500p+** (Custom collector pricing; do not undersell).")
                    elif r.is_unrolled:
                        lines.append(f"  - **Recommended Listing Price:** **{max(u_floor or 0, t_floor) + 15}p–{max(u_floor or 0, t_floor) + 40}p** (Unrolled premium).")
                    else:
                        lines.append(f"  - **Recommended Listing Price:** **{t_floor + 25}p–{med or (t_floor + 50)}p**.")

            # Trade chat copy-paste
            lines.append(f"- **Trade Chat Copy:** `WTS [{r.weapon_name} {r.riven_name}] PM offer`")
            lines.append("")

    lines.extend([
        "---",
        "",
        "## 🎯 Top Kuva Re-roll Candidates",
        "",
        "These Rivens belong to popular meta weapons or high-disposition armaments with mediocre rolls. Investing Kuva here offers the highest probability of rolling high-plat God Rolls.",
        "",
    ])

    sorted_kuva = sorted(kuva_targets, key=lambda x: (not x.is_meta_weapon, -x.disposition, x.rerolls))
    if not sorted_kuva:
        lines.append("_No designated Kuva re-roll targets._")
    else:
        for r in sorted_kuva:
            lines.append(f"- **{r.full_name}** ({r.weapon_type}) — Grade: `{r.grade}` | Rolls: {r.rerolls} | Disp: **{r.disposition}x**")
            lines.append(f"  - Current Stats: {format_traits(r)}")
            if r.is_meta_weapon:
                lines.append("  - _Meta Weapon Alert: High market buyer demand; excellent candidate for Kuva rolls._")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## ♻️ Transmutation & Quick Liquidation Candidates",
        "",
        "Fodder rivens on obscure or low-disposition weapons. Recommend transmuting 4 at a time with a **Riven Transmuter** (obtained from Eidolon Captures) to yield a fresh veiled riven, or selling at trash floor (~10–20p).",
        "",
    ])

    for r in transmute_candidates[:20]:
        lines.append(f"- `{r.full_name}` ({r.weapon_type}) — Rolls: {r.rerolls} | Disp: {r.disposition}x")
    if len(transmute_candidates) > 20:
        lines.append(f"- _...and {len(transmute_candidates) - 20} more fodder rivens._")
    lines.append("")

    lines.extend([
        "---",
        "",
        "## 📋 Complete Inventory by Weapon Type",
        "",
    ])

    for w_type in sorted(by_type.keys()):
        group = by_type[w_type]
        lines.append(f"### {w_type} Rivens ({len(group)})")
        lines.append("")
        sorted_group = sorted(group, key=lambda x: (x.grade != "Perfect", x.grade != "Good", x.weapon_name))
        for r in sorted_group:
            status_badge = f"**{r.grade}**"
            if r.is_unrolled:
                status_badge += " (UNROLLED)"
            lines.append(f"- **{r.full_name}** | Grade: {status_badge} | Rolls: {r.rerolls} | Disp: {r.disposition}x")
            lines.append(f"  - Stats: {format_traits(r)}")
            lines.append(f"  - Action: {r.action_bucket}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Warframe Riven Intelligence & Live Market Valuation Tracker"
    )
    parser.add_argument(
        "--rivens-file",
        type=Path,
        default=Path("rivens.json"),
        help="Path to rivens.json export (default: rivens.json)",
    )
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="Filter by weapon type (e.g. shotgun, rifle, pistol, melee, archgun)",
    )
    parser.add_argument(
        "--grade",
        type=str,
        default=None,
        help="Filter by roll grade (e.g. Perfect, Good, HasPotential, Bad)",
    )
    parser.add_argument(
        "--weapon",
        type=str,
        default=None,
        help="Filter by specific weapon name(s), comma-separated (e.g. 'Corinth, Arca Plasmor')",
    )
    parser.add_argument(
        "--top-valuable",
        action="store_true",
        help="Show only high-value sellable rivens (Good/Perfect, unrolled, or meta)",
    )
    parser.add_argument(
        "--skip-market",
        action="store_true",
        help="Skip fetching live Warframe.market auction prices (offline mode)",
    )
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=Path("riven_watchlist.txt"),
        help="Path to riven watchlist file (default: riven_watchlist.txt)",
    )
    parser.add_argument(
        "--all-market",
        action="store_true",
        help="Fetch live market prices for all weapons in the filtered list (slower)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("notebook_sources") / "riven_intelligence.md",
        help="Output markdown file path (default: notebook_sources/riven_intelligence.md)",
    )
    parser.add_argument(
        "--drive-dir",
        type=Path,
        default=DEFAULT_DRIVE_DIR,
        help=f"Target Google Drive destination folder (default: {DEFAULT_DRIVE_DIR})",
    )
    parser.add_argument(
        "--update-drive",
        action="store_true",
        help="Automatically copy generated report to Google Drive and archive previous to OLD/",
    )

    args = parser.parse_args()

    rivens = load_rivens(args.rivens_file)
    if not rivens:
        print(f"No rivens found in {args.rivens_file}.", file=sys.stderr)
        return 1

    # Filter by weapon type
    if args.type:
        target_type = args.type.casefold().strip()
        rivens = [r for r in rivens if target_type in r.weapon_type.casefold()]

    # Filter by grade
    if args.grade:
        target_grades = {g.strip().casefold() for g in args.grade.split(",")}
        rivens = [r for r in rivens if r.grade.casefold() in target_grades]

    # Filter by weapon names
    if args.weapon:
        target_weapons = {w.strip().casefold() for w in args.weapon.split(",")}
        rivens = [r for r in rivens if any(tw in r.weapon_name.casefold() for tw in target_weapons)]

    # Filter top valuable
    if args.top_valuable:
        rivens = [
            r for r in rivens
            if r.grade in ("Perfect", "Good") or (r.is_unrolled and r.is_meta_weapon)
        ]

    market_client = None if args.skip_market else RivenMarketClient()

    # Determine which weapons to price-check live
    price_check_weapons: set[str] = set()

    # 1. From watchlist file if present
    if args.watchlist and args.watchlist.exists():
        try:
            for line in args.watchlist.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    price_check_weapons.add(line.casefold())
        except Exception:
            pass

    # 2. Explicit weapon CLI argument
    if args.weapon:
        for w in args.weapon.split(","):
            if w.strip():
                price_check_weapons.add(w.strip().casefold())

    # 3. Always check Perfect rivens
    for r in rivens:
        if r.grade == "Perfect":
            price_check_weapons.add(r.weapon_name.casefold())

    # 4. If --type or --top-valuable was passed, check weapons in that filtered subset (up to 12)
    if args.type or args.top_valuable:
        for r in rivens:
            if len(price_check_weapons) >= 12 and not args.all_market:
                break
            if r.grade in ("Perfect", "Good") or r.is_meta_weapon:
                price_check_weapons.add(r.weapon_name.casefold())
    elif args.all_market:
        for r in rivens:
            price_check_weapons.add(r.weapon_name.casefold())
    else:
        # Default full inventory run: include top meta weapons with Good rolls (max 6)
        for r in rivens:
            if len(price_check_weapons) >= 6:
                break
            if r.grade == "Good" and r.is_meta_weapon:
                price_check_weapons.add(r.weapon_name.casefold())

    markdown_report = generate_riven_intelligence_markdown(
        rivens=rivens,
        market_client=market_client,
        price_check_weapons=price_check_weapons,
    )

    # Save locally
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown_report, encoding="utf-8")
    print(f"[OK] Wrote Riven Intelligence report ({len(rivens)} rivens) to {args.output}")

    # Terminal output of matching rivens
    print("\n" + "=" * 70)
    print(f"RIVEN INTELLIGENCE SUMMARY ({len(rivens)} Rivens Matching Filter)")
    print("=" * 70)
    for r in rivens:
        unrolled_tag = "[UNROLLED]" if r.is_unrolled else f"[{r.rerolls} rolls]"
        print(f"* {r.weapon_name:<16} | {r.riven_name:<16} | {r.weapon_type:<8} | Grade: {r.grade:<12} | {unrolled_tag:<10} | {r.action_bucket}")
        if market_client and r.weapon_name.casefold() in price_check_weapons:
            stats = market_client.get_live_auction_stats(r.weapon_name)
            if stats and stats.get("trash_floor") is not None:
                t_fl = stats["trash_floor"]
                u_fl = stats.get("unrolled_floor")
                u_str = f" | Unrolled: ~{u_fl}p" if u_fl is not None else ""
                print(f"    --> Market Floor: ~{t_fl}p{u_str} ({stats.get('online_auctions', 0)} online sellers)")
    print("=" * 70)

    # Auto-copy to Google Drive if requested
    if args.update_drive:
        try:
            from sync_to_drive import sync_to_drive
            sync_to_drive(
                source_dir=args.output.parent,
                drive_dir=args.drive_dir,
                verbose=True,
            )
        except Exception as drive_err:
            print(f"Warning: could not sync to Google Drive: {drive_err}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
