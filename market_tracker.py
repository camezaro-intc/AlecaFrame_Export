#!/usr/bin/env python3
"""
Warframe Market Price Tracker for AlecaFrame Exports
Fetches live Warframe.market (v2 API) prices for:
1. Mods & Prime sets you can sell (duplicates, completed sets, high value)
2. Mods you need (unowned mods, wishlist, missing max-ranks)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_BASE = "https://api.warframe.market/v2"
USER_AGENT = "AlecaPriceTracker/1.0 (WarframeInventoryBot; Windows)"
CACHE_DIR = Path(".market_cache")
ITEMS_CACHE_FILE = CACHE_DIR / "items_catalog.json"
PRICES_CACHE_FILE = CACHE_DIR / "prices_cache.json"
CACHE_TTL_PRICES = 1800  # 30 minutes
CACHE_TTL_CATALOG = 86400  # 24 hours


def request_json(url: str, headers: dict[str, str] | None = None) -> Any:
    """Polite HTTP GET request returning parsed JSON."""
    req_headers = {"User-Agent": USER_AGENT, "Platform": "pc"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


class MarketClient:
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.prices_cache: dict[str, dict[str, Any]] = {}
        self.catalog: list[dict[str, Any]] = []
        self.ref_to_item: dict[str, dict[str, Any]] = {}
        self.name_to_item: dict[str, dict[str, Any]] = {}
        self._load_prices_cache()
        self._load_catalog()

    def _load_prices_cache(self) -> None:
        if PRICES_CACHE_FILE.exists():
            try:
                self.prices_cache = json.loads(
                    PRICES_CACHE_FILE.read_text(encoding="utf-8")
                )
            except Exception:
                self.prices_cache = {}

    def _save_prices_cache(self) -> None:
        try:
            PRICES_CACHE_FILE.write_text(
                json.dumps(self.prices_cache, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"Warning: could not save price cache: {e}", file=sys.stderr)

    def _load_catalog(self) -> None:
        now = time.time()
        catalog_fresh = False
        if ITEMS_CACHE_FILE.exists():
            try:
                cached = json.loads(ITEMS_CACHE_FILE.read_text(encoding="utf-8"))
                if now - cached.get("timestamp", 0) < CACHE_TTL_CATALOG:
                    self.catalog = cached.get("data", [])
                    catalog_fresh = True
            except Exception:
                pass

        if not catalog_fresh:
            print("Fetching latest item catalog from Warframe.market v2...", file=sys.stderr)
            try:
                resp = request_json(f"{API_BASE}/items")
                self.catalog = resp.get("data", [])
                ITEMS_CACHE_FILE.write_text(
                    json.dumps({"timestamp": now, "data": self.catalog}),
                    encoding="utf-8",
                )
            except Exception as e:
                print(f"Error fetching catalog: {e}", file=sys.stderr)
                if not self.catalog and ITEMS_CACHE_FILE.exists():
                    self.catalog = json.loads(
                        ITEMS_CACHE_FILE.read_text(encoding="utf-8")
                    ).get("data", [])

        # Build index maps
        for item in self.catalog:
            game_ref = item.get("gameRef")
            if game_ref:
                self.ref_to_item[game_ref] = item
            en_name = (
                item.get("i18n", {}).get("en", {}).get("name")
                or item.get("slug", "").replace("_", " ").title()
            )
            if en_name:
                self.name_to_item[en_name.lower()] = item

    def get_historical_stats(
        self, slug: str, rank: int | None = None
    ) -> dict[str, Any]:
        """Fetch 48-hour and 90-day closed sales statistics from Warframe.market."""
        cache_key = f"stats:{slug}:r{rank if rank is not None else 'any'}"
        now = time.time()
        if cache_key in self.prices_cache:
            entry = self.prices_cache[cache_key]
            if now - entry.get("timestamp", 0) < CACHE_TTL_PRICES:
                return entry["data"]

        time.sleep(0.35)
        url = f"https://api.warframe.market/v1/items/{slug}/statistics"
        headers = {
            "User-Agent": USER_AGENT,
            "Platform": "pc",
            "Language": "en",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8")).get("payload", {})
                stats_closed = payload.get("statistics_closed", {})
                c48 = stats_closed.get("48hours", [])
                c90 = stats_closed.get("90days", [])

                if rank is not None:
                    c48 = [x for x in c48 if x.get("mod_rank") == rank]
                    c90 = [x for x in c90 if x.get("mod_rank") == rank]

                v48 = sum(x.get("volume", 0) for x in c48)
                w48 = sum(
                    x.get("wa_price", x.get("avg_price", 0)) * x.get("volume", 0)
                    for x in c48
                )
                avg48 = round(w48 / v48, 1) if v48 else (c48[-1].get("avg_price") if c48 else None)
                med48 = c48[-1].get("median") if c48 else None

                v90 = sum(x.get("volume", 0) for x in c90)
                w90 = sum(
                    x.get("wa_price", x.get("avg_price", 0)) * x.get("volume", 0)
                    for x in c90
                )
                avg90 = round(w90 / v90, 1) if v90 else (c90[-1].get("avg_price") if c90 else None)
                med90 = c90[-1].get("median") if c90 else None

                result = {
                    "vol_48h": v48,
                    "avg_48h": avg48,
                    "med_48h": med48,
                    "vol_90d": v90,
                    "avg_90d": avg90,
                    "med_90d": med90,
                }
                self.prices_cache[cache_key] = {"timestamp": now, "data": result}
                self._save_prices_cache()
                return result
        except Exception as e:
            return {"error": str(e)}

    def get_market_price(
        self, slug: str, rank: int | None = None, include_stats: bool = False
    ) -> dict[str, Any]:
        """Fetch top orders for an item slug, returning pricing summary."""
        cache_key = f"{slug}:r{rank if rank is not None else 'any'}"
        now = time.time()
        result = None
        if cache_key in self.prices_cache:
            entry = self.prices_cache[cache_key]
            if now - entry.get("timestamp", 0) < CACHE_TTL_PRICES:
                result = dict(entry["data"])

        if result is None:
            # Throttle to avoid rate limiting
            time.sleep(0.35)

            url = f"{API_BASE}/orders/item/{slug}/top"
            if rank is not None:
                url += f"?rank={rank}"

            try:
                resp = request_json(url)
                data = resp.get("data", {})
                sells = data.get("sell", [])
                buys = data.get("buy", [])

                sell_prices = [
                    s["platinum"]
                    for s in sells
                    if s.get("visible", True)
                    and s.get("user", {}).get("status") in ("ingame", "online")
                ]
                buy_prices = [
                    b["platinum"]
                    for b in buys
                    if b.get("visible", True)
                    and b.get("user", {}).get("status") in ("ingame", "online")
                ]

                min_sell = min(sell_prices) if sell_prices else None
                avg_sell = (
                    round(sum(sell_prices[:3]) / len(sell_prices[:3]), 1)
                    if sell_prices
                    else None
                )
                max_buy = max(buy_prices) if buy_prices else None

                # Get best seller for quick whisper
                best_seller = None
                if sells:
                    top_s = sells[0]
                    user = top_s.get("user", {})
                    best_seller = {
                        "username": user.get("ingameName"),
                        "status": user.get("status"),
                        "platinum": top_s.get("platinum"),
                        "quantity": top_s.get("quantity"),
                    }

                result = {
                    "min_sell": min_sell,
                    "avg_sell": avg_sell,
                    "max_buy": max_buy,
                    "top_sellers": sell_prices[:3],
                    "top_buyers": buy_prices[:3],
                    "best_seller": best_seller,
                }

                self.prices_cache[cache_key] = {"timestamp": now, "data": result}
                self._save_prices_cache()
            except urllib.error.HTTPError as e:
                result = {"error": f"HTTP {e.code}"}
            except Exception as e:
                result = {"error": str(e)}

        if include_stats and result and "error" not in result:
            result["history"] = self.get_historical_stats(slug, rank=rank)

        return result


def load_json(path: Path) -> Any:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8-sig"))


def analyze_sellable_mods(
    mods: list[dict[str, Any]], client: MarketClient, limit: int = 15
) -> list[dict[str, Any]]:
    """Find valuable duplicate mods that can be sold for platinum."""
    candidates = []
    for mod in mods:
        amount_owned = mod.get("amountOwned", 0)
        used_by = mod.get("modUsedBy", "")
        # Look for mods with duplicates (or unequipped mods with estimated value)
        if amount_owned > 1 or (amount_owned >= 1 and not used_by and mod.get("sellPrice", 0) >= 5):
            name = mod.get("name")
            internal_name = mod.get("internalName")
            item = client.ref_to_item.get(internal_name) or client.name_to_item.get(
                (name or "").lower()
            )
            if not item:
                continue

            slug = item["slug"]
            est_price = mod.get("sellPrice", 0)
            candidates.append(
                {
                    "name": name,
                    "slug": slug,
                    "amountOwned": amount_owned,
                    "spare": amount_owned - (1 if used_by else 0),
                    "currentRank": mod.get("currentModRank", 0),
                    "maxRank": mod.get("modRankMax", 0),
                    "estPrice": est_price,
                    "modType": mod.get("modType"),
                }
            )

    # Sort by AlecaFrame's estimated price descending
    candidates.sort(key=lambda x: (x["estPrice"], x["spare"]), reverse=True)
    selected = candidates[:limit]

    # Query live market prices
    results = []
    for c in selected:
        prices = client.get_market_price(c["slug"], rank=c["currentRank"], include_stats=True)
        results.append({**c, "market": prices})
    return results


def analyze_ready_sets(
    sets: list[dict[str, Any]], client: MarketClient, limit: int = 10
) -> list[dict[str, Any]]:
    """Find completed Prime sets that can be sold immediately."""
    ready = [s for s in sets if s.get("isReadyToSell")]
    ready.sort(key=lambda s: s.get("sellPrice", 0), reverse=True)
    selected = ready[:limit]

    results = []
    for s in selected:
        name = s.get("name", "")
        # In WFM, sets have slugs like 'rhino_prime_set'
        lookup_name = name.lower()
        item = client.name_to_item.get(lookup_name)
        if not item:
            slug_guess = lookup_name.replace(" ", "_").replace("-", "_")
            item = client.name_to_item.get(slug_guess)

        market_prices = {}
        if item:
            market_prices = client.get_market_price(item["slug"], include_stats=True)

        results.append(
            {
                "name": name,
                "amountOwned": s.get("amountOwned", 1),
                "alecaSell": s.get("sellPrice", 0),
                "alecaBuy": s.get("buyPrice", 0),
                "ducats": s.get("ducats", 0),
                "market": market_prices,
            }
        )
    return results


def parse_wishlist(wishlist_file: Path | None = None) -> list[str]:
    """Parse mod names from wishlist file, handling markdown formatting, comments, and bullets."""
    w_path = wishlist_file or Path("wishlist.txt")
    if not w_path.exists():
        return []
    targets: list[str] = []
    ignore_keywords = ("example", "add mod", "one per line", "the script", "examples:", "format:")
    for line in w_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        cleaned = raw.lstrip("#-* \t").strip()
        if not cleaned:
            continue
        if any(kw in cleaned.lower() for kw in ignore_keywords):
            continue
        targets.append(cleaned)
    return targets


def analyze_wishlist(
    client: MarketClient, wishlist_file: Path | None = None
) -> list[dict[str, Any]]:
    """Fetch live market prices and whisper commands for wishlist mods."""
    targets = parse_wishlist(wishlist_file)
    results = []
    for target in targets:
        # Match by name or slug
        item = client.name_to_item.get(target.lower())
        if not item:
            slug_guess = target.lower().replace(" ", "_").replace("-", "_")
            item = client.name_to_item.get(slug_guess)
        if not item:
            for it in client.catalog:
                if it.get("slug", "").lower() == target.lower().replace(" ", "_"):
                    item = it
                    break

        if item:
            prices = client.get_market_price(item["slug"], rank=0, include_stats=True)
            results.append(
                {
                    "name": item.get("i18n", {}).get("en", {}).get("name") or target.title(),
                    "slug": item["slug"],
                    "tags": item.get("tags", []),
                    "maxRank": item.get("maxRank", 0),
                    "market": prices,
                }
            )
        else:
            results.append(
                {
                    "name": target.title(),
                    "slug": "",
                    "tags": [],
                    "maxRank": 0,
                    "market": {"error": "Item not found in Warframe Market catalog"},
                }
            )
    return results


def analyze_needed_mods(
    mods: list[dict[str, Any]],
    client: MarketClient,
    limit: int = 15,
    exclude_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Find high-value / important tradable mods missing from inventory."""
    owned_refs = {
        m.get("internalName")
        for m in mods
        if m.get("amountOwned", 0) > 0 and m.get("internalName")
    }
    owned_names = {
        (m.get("name") or "").lower()
        for m in mods
        if m.get("amountOwned", 0) > 0
    }
    excluded = {n.lower() for n in (exclude_names or set())}

    # Filter catalog for tradable mods not owned
    unowned = []
    for item in client.catalog:
        tags = item.get("tags", [])
        if "mod" not in tags or "pvp" in tags:
            continue
        game_ref = item.get("gameRef")
        en_name = item.get("i18n", {}).get("en", {}).get("name", "")
        en_lower = en_name.lower() if en_name else ""
        if (game_ref and game_ref in owned_refs) or (en_lower and en_lower in owned_names):
            continue
        if en_lower and en_lower in excluded:
            continue

        # Tag priority weighting
        priority = 0
        if "primed" in tags:
            priority += 40
        elif "archon" in tags:
            priority += 35
        elif "galvanized" in tags:
            priority += 30
        elif "corrupted" in tags:
            priority += 25
        elif "aura" in tags:
            priority += 20
        elif "rare" in tags:
            priority += 10

        unowned.append({**item, "name": en_name, "priority": priority})

    # Sort unowned by priority
    unowned.sort(key=lambda x: x["priority"], reverse=True)
    selected = unowned[:limit]

    results = []
    for item in selected:
        prices = client.get_market_price(item["slug"], rank=0, include_stats=False)
        results.append(
            {
                "name": item["name"],
                "slug": item["slug"],
                "tags": item.get("tags", []),
                "maxRank": item.get("maxRank", 0),
                "market": prices,
            }
        )
    return results


def generate_markdown_report(
    sell_mods: list[dict[str, Any]],
    ready_sets: list[dict[str, Any]],
    needed_mods: list[dict[str, Any]],
    wishlist_mods: list[dict[str, Any]] | None = None,
) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Warframe Market Price Intelligence & Opportunities",
        f"**Generated:** {now_str} | **Source:** Warframe.market v2 + v1 Closed Statistics + AlecaFrame Exports\n",
    ]

    # Prominent Wishlist Section
    if wishlist_mods:
        lines.extend([
            "---",
            "## 🌟 Your Custom Wishlist (Target Mods to Buy)",
            "Live market prices, historical 48h & 90d sales stats, and trade whispers:\n",
            "| Wishlist Mod | Live Best Buy | 48h Avg (Median) | 90d Baseline | 48h Traded Vol | Active Seller IGN | Status | Trade Whisper (Click to Copy) |",
            "|:---|:---:|:---:|:---:|:---:|:---|:---:|:---|",
        ])
        for item in wishlist_mods:
            m = item.get("market", {})
            h = m.get("history", {})
            min_s = f"{m.get('min_sell')}p" if m.get("min_sell") is not None else "-"
            
            avg_48 = f"{h.get('avg_48h')}p" if h.get("avg_48h") is not None else "-"
            if h.get("med_48h") is not None:
                avg_48 += f" ({h.get('med_48h')}p)"
            avg_90 = f"{h.get('avg_90d')}p" if h.get("avg_90d") is not None else "-"
            vol_48 = f"{h.get('vol_48h')} sold" if h.get("vol_48h") is not None else "-"

            best = m.get("best_seller") or {}
            ign = best.get("username", "N/A")
            status = best.get("status", "offline")
            whisper = (
                f"`/w {ign} Hi! I want to buy: {item['name']} for {m.get('min_sell')} platinum. (warframe.market)`"
                if m.get("min_sell") and ign != "N/A"
                else "-"
            )
            lines.append(
                f"| **{item['name']}** | **{min_s}** | {avg_48} | {avg_90} | {vol_48} | {ign} | {status} | {whisper} |"
            )

    lines.extend([
        "\n---",
        "## 💎 Top Prime Sets Ready to Sell",
        "Complete sets in your inventory with live orders and 48h/90d historical trade volume:\n",
        "| Set Name | Owned | Live Best Sell | 48h Avg Sold | 90d Baseline | Instant Buy | 48h Vol | Aleca Est. |",
        "|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])
    for s in ready_sets:
        m = s.get("market", {})
        h = m.get("history", {})
        min_s = f"{m.get('min_sell')}p" if m.get("min_sell") is not None else "-"
        avg_48 = f"{h.get('avg_48h')}p" if h.get("avg_48h") is not None else "-"
        avg_90 = f"{h.get('avg_90d')}p" if h.get("avg_90d") is not None else "-"
        vol_48 = f"{h.get('vol_48h')} sold" if h.get("vol_48h") is not None else "-"
        max_b = f"{m.get('max_buy')}p" if m.get("max_buy") is not None else "-"
        lines.append(
            f"| **{s['name']}** | {s['amountOwned']} | **{min_s}** | {avg_48} | {avg_90} | {max_b} | {vol_48} | {s['alecaSell']}p |"
        )

    lines.extend([
        "\n---",
        "## 📦 Top Duplicate Mods to Sell (Spare Copies)",
        "Spare copies in your inventory you can liquidate for Platinum:\n",
        "| Mod Name | Total / Spare | Rank | Live Best Sell | 48h Avg Sold | 90d Baseline | Instant Buy | 48h Vol | Est. Total Plat |",
        "|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])
    for m in sell_mods:
        p = m.get("market", {})
        h = p.get("history", {})
        min_s = f"{p.get('min_sell')}p" if p.get("min_sell") is not None else "-"
        avg_48 = f"{h.get('avg_48h')}p" if h.get("avg_48h") is not None else "-"
        avg_90 = f"{h.get('avg_90d')}p" if h.get("avg_90d") is not None else "-"
        vol_48 = f"{h.get('vol_48h')} sold" if h.get("vol_48h") is not None else "-"
        max_b = f"{p.get('max_buy')}p" if p.get("max_buy") is not None else "-"
        spare = m["spare"]
        best_p = p.get("min_sell") or m["estPrice"]
        tot_plat = f"~{spare * best_p}p" if best_p else "-"
        lines.append(
            f"| **{m['name']}** | {m['amountOwned']} ({spare} spare) | R{m['currentRank']}/{m['maxRank']} | **{min_s}** | {avg_48} | {avg_90} | {max_b} | {vol_48} | **{tot_plat}** |"
        )

    lines.extend([
        "\n---",
        "## 🎯 Priority Mods Missing From Inventory (To Buy)",
        "Key tradable mods (Primed, Corrupted, Archon, Aura) not in your collection:\n",
        "| Missing Mod | Tags / Tier | Best Buy Price | Seller In-Game Name | Status | Trade Whisper |",
        "|:---|:---|:---:|:---|:---:|:---|",
    ])
    for item in needed_mods:
        m = item.get("market", {})
        min_s = f"{m.get('min_sell')}p" if m.get("min_sell") is not None else "-"
        best = m.get("best_seller") or {}
        ign = best.get("username", "N/A")
        status = best.get("status", "offline")
        whisper = (
            f"`/w {ign} Hi! I want to buy: {item['name']} for {m.get('min_sell')} platinum. (warframe.market)`"
            if m.get("min_sell") and ign != "N/A"
            else "-"
        )
        tag_str = ", ".join([t for t in item["tags"] if t != "mod"][:3])
        lines.append(
            f"| **{item['name']}** | {tag_str} | **{min_s}** | {ign} | {status} | {whisper} |"
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Track live Warframe.market prices for your AlecaFrame inventory."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("market_opportunities.md"),
        help="Path for markdown summary report",
    )
    parser.add_argument(
        "--top-sell",
        type=int,
        default=10,
        help="Number of duplicate mods to check",
    )
    parser.add_argument(
        "--top-sets",
        type=int,
        default=8,
        help="Number of ready sets to check",
    )
    parser.add_argument(
        "--top-needed",
        type=int,
        default=10,
        help="Number of unowned priority mods to check",
    )
    parser.add_argument(
        "--wishlist",
        type=Path,
        default=Path("wishlist.txt"),
        help="Path to custom wishlist text file (one mod name per line)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch inventory files for changes and re-run",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Continuous polling interval in seconds (0 = run once)",
    )

    args = parser.parse_args()

    mods_path = Path("inventoryMods.json")
    sets_path = Path("inventorySets.json")

    if not mods_path.exists():
        print(f"Error: {mods_path} not found in current directory.", file=sys.stderr)
        return 1

    client = MarketClient()

    def run_check() -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Analyzing inventory & wishlist...", file=sys.stderr)
        mods_data = load_json(mods_path)
        sets_data = load_json(sets_path)

        wishlist_mods = analyze_wishlist(client, wishlist_file=args.wishlist)
        exclude_from_needed = {m["name"] for m in wishlist_mods}

        sell_mods = analyze_sellable_mods(mods_data, client, limit=args.top_sell)
        ready_sets = analyze_ready_sets(sets_data, client, limit=args.top_sets)
        needed_mods = analyze_needed_mods(
            mods_data, client, limit=args.top_needed, exclude_names=exclude_from_needed
        )

        md = generate_markdown_report(
            sell_mods, ready_sets, needed_mods, wishlist_mods=wishlist_mods
        )
        args.output.write_text(md, encoding="utf-8")
        nb_file = Path("notebook_sources") / "market_opportunities.md"
        if nb_file.parent.exists():
            nb_file.write_text(md, encoding="utf-8")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Report updated at {args.output} and {nb_file}!", file=sys.stderr)

        # Print quick summary to console
        if wishlist_mods:
            print("\n=== YOUR WISHLIST MODS (LIVE) ===")
            for item in wishlist_mods:
                p = item.get("market", {})
                best = p.get("best_seller") or {}
                ign = best.get("username", "N/A")
                print(f"- {item['name']}: Best price {p.get('min_sell', '?')}p (Seller: {ign})")

        print("\n=== TOP READY SETS TO SELL ===")
        for s in ready_sets[:5]:
            m = s.get("market", {})
            print(f"- {s['name']}: {m.get('min_sell', '?')}p (Instant buy: {m.get('max_buy', '?')}p)")

        print("\n=== TOP SPARE MODS TO SELL ===")
        for m in sell_mods[:5]:
            p = m.get("market", {})
            print(f"- {m['name']} ({m['spare']} spare): {p.get('min_sell', '?')}p each")

        print("\n=== OTHER PRIORITY MODS TO BUY ===")
        for item in needed_mods[:5]:
            p = item.get("market", {})
            print(f"- {item['name']}: Best price {p.get('min_sell', '?')}p")
        print()

    run_check()

    if args.interval > 0:
        print(f"Running in periodic mode every {args.interval} seconds. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(args.interval)
                run_check()
        except KeyboardInterrupt:
            print("\nStopped.")

    elif args.watch:
        def get_latest_mtime() -> float:
            mtimes = [
                mods_path.stat().st_mtime,
                sets_path.stat().st_mtime if sets_path.exists() else 0,
            ]
            if args.wishlist.exists():
                mtimes.append(args.wishlist.stat().st_mtime)
            return max(mtimes)

        last_mtime = get_latest_mtime()
        print(f"Watching inventory files & {args.wishlist} for updates. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3)
                cur_mtime = get_latest_mtime()
                if cur_mtime > last_mtime:
                    last_mtime = cur_mtime
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] File change detected (inventory or wishlist)! Re-checking...")
                    run_check()
        except KeyboardInterrupt:
            print("\nStopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
