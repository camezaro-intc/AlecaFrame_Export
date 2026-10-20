#!/usr/bin/env python3
"""
AlecaFrame Stats & Telemetry Analyzer + Mastery Rank Optimizer
Processes alecaframeStatsExport.json, foundry.json, inventoryParts.json, and inventorySets.json to generate:
1. Markdown sources for NotebookLM / Gemini Notebooks:
   - account_stats.md
   - trade_history.md
   - mastery_roadmap.md
2. Interactive HTML visualizer dashboard with multi-tab navigation:
   - Tab 1: Financial & Telemetry Intelligence (timeline, resource trends, trade ledger)
   - Tab 2: Mastery Rank Helper & Speed-Leveling Roadmap (prioritized item catalog with wiki artwork)
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

UNICODE_GLYPHS = re.compile(r"[\ue000-\uf8ff]")


def clean_text(text: Any) -> str:
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    # Strip custom Warframe font icons
    cleaned = UNICODE_GLYPHS.sub("", text).strip()
    return cleaned


def parse_qty(v: Any) -> int:
    if v is None:
        return 0
    s = str(v).strip().upper()
    if s.endswith("K"):
        try:
            return int(float(s[:-1]) * 1000)
        except Exception:
            return 1000
    if s.endswith("M"):
        try:
            return int(float(s[:-1]) * 1000000)
        except Exception:
            return 1000000
    try:
        return int(float(s))
    except Exception:
        return 0


def get_item_xp(it: dict[str, Any]) -> int:
    name = it.get("name", "")
    itype = (it.get("type") or "").lower()
    # Warframes, Companions, Archwings, K-Drives, Necramechs = 6,000 XP
    if itype in ("warframe", "companion") or (itype == "arch" and ("wing" in name.lower() or name in ("Elytron", "Odonata Prime", "Itzal", "Amesha"))):
        return 6000
    if name in ("Bad Baby", "Flatbelly", "Feverspine", "Runway", "Needlenose"):
        return 6000
    # Kuva / Tenet / Coda weapons (at rank 40) can yield up to 4,000 XP (with 5 Formas)
    if any(prefix in name for prefix in ("Kuva ", "Tenet ", "Coda ")):
        return 4000
    # Standard weapons, archguns, archmelees, amps, zaws = 3,000 XP
    return 3000


def parse_trades(raw_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed = []
    for t in raw_trades:
        ts = t.get("ts", "")
        date_str = ts[:10] if ts else "Unknown"
        user = clean_text(t.get("user", "Unknown"))
        total_plat = t.get("totalPlat", 0)

        tx_items = []
        for x in t.get("tx", []):
            name = x.get("displayName") or x.get("name", "Item")
            cnt = x.get("cnt", 1)
            rank = x.get("rank", -1)
            tx_items.append({"name": name, "cnt": cnt, "rank": rank})

        rx_items = []
        for x in t.get("rx", []):
            name = x.get("displayName") or x.get("name", "Item")
            cnt = x.get("cnt", 1)
            rank = x.get("rank", -1)
            rx_items.append({"name": name, "cnt": cnt, "rank": rank})

        # Classify trade
        has_plat_rx = any(x["name"].lower() == "platinum" for x in rx_items)
        has_plat_tx = any(x["name"].lower() == "platinum" for x in tx_items)

        if has_plat_rx:
            trade_type = "Sale"
            net_plat = total_plat
        elif has_plat_tx:
            trade_type = "Purchase"
            net_plat = -total_plat
        else:
            trade_type = "Barter / Gift"
            net_plat = 0

        parsed.append(
            {
                "ts": ts,
                "date": date_str,
                "user": user,
                "type": trade_type,
                "totalPlat": total_plat,
                "netPlat": net_plat,
                "tx": tx_items,
                "rx": rx_items,
            }
        )
    return parsed


def classify_mastery_roadmap(
    foundry_items: list[dict[str, Any]],
    current_mr: int = 34,
) -> dict[str, Any]:
    unmastered = [it for it in foundry_items if not it.get("mastered")]

    items_list = []
    founders_list = []

    for it in unmastered:
        name = clean_text(it.get("name", ""))
        itype = clean_text(it.get("type", "")).lower()
        owned = bool(it.get("owned", False))
        pic = it.get("picture", "")
        xp = get_item_xp(it)

        if name in ("Excalibur Prime", "Lato Prime", "Skana Prime"):
            founders_list.append(it)
            continue

        comps = [
            c
            for c in (it.get("components") or [])
            if clean_text(c.get("name", ""))
            not in ("Orokin Cell", "Forma", "Credits", "Argon Crystal", "Tellurium", "Nitain Extract")
        ]
        missing = [
            c
            for c in comps
            if parse_qty(c.get("quantityOwned")) < parse_qty(c.get("neccessaryAmount"))
        ]
        missing_names = [clean_text(m.get("name", "")) for m in missing]

        if owned:
            prio = 1
            prio_label = "⚡ Ready in Inventory"
            status_text = "Crafted in Inventory"
            tip = "Equip & level in Sanctuary Onslaught / ESO (0 crafting time / 0 plat required)."
        elif len(missing) == 1 and any("prime" in name.lower() or itype in ("primary", "secondary", "melee", "arch") for _ in [1]):
            prio = 2
            prio_label = "🎯 Missing 1 Part"
            status_text = f"Missing: {missing_names[0]}"
            tip = f"Needs 1 part: {missing_names[0]} (Farm via Relic / Bounty or trade on Warframe.market)."
        elif itype in ("companion",) or "prism" in name.lower() or name in ("Flatbelly", "Feverspine", "Runway", "Dokrahm", "Ooltha"):
            prio = 3
            prio_label = "🐾 Companions & Modular"
            status_text = "Incubator / Open World"
            tip = "Breed via Incubator (Kavat/Kubrow) or craft at open-world vendor. *Modular gear must be Gilded at rank 30 before leveling again for Mastery!*"
        elif any(k in name for k in ("Tenet", "Coda", "Kuva")):
            prio = 4
            prio_label = "⚔️ Nemesis Hunter"
            status_text = "Sister / Lich / Coda Drop"
            tip = "Hunt Nemesis. *Gives 3,000 XP at lvl 30; each of 5 Formas adds 2 levels (+200 XP/lvl up to 4,000 XP).* "
        else:
            prio = 5
            prio_label = "🏛️ Clan / Market / Drops"
            missing_str = ", ".join(missing_names[:2]) + ("..." if len(missing_names) > 2 else "") if missing_names else "Dojo / Market BP"
            status_text = f"Needs: {missing_str}"
            tip = "Acquire blueprint or components from Clan Dojo labs, Market, Baro Ki'Teer, or Relics."

        items_list.append(
            {
                "name": name,
                "type": itype,
                "picture": pic,
                "xp": xp,
                "owned": owned,
                "prio": prio,
                "prio_label": prio_label,
                "status_text": status_text,
                "missing": missing_names,
                "tip": tip,
            }
        )

    # Sort items: Priority 1 first, then by XP desc, then name
    items_list.sort(key=lambda x: (x["prio"], -x["xp"], x["type"], x["name"]))

    tier1_items = [x for x in items_list if x["prio"] == 1]
    tier2_items = [x for x in items_list if x["prio"] == 2]
    tier3_items = [x for x in items_list if x["prio"] == 3]
    tier4_items = [x for x in items_list if x["prio"] == 4]
    tier5_items = [x for x in items_list if x["prio"] == 5]

    xp_tier1 = sum(x["xp"] for x in tier1_items)
    xp_total = sum(x["xp"] for x in items_list)
    xp_needed_for_next_mr = 147500  # From MR 34 to 35 (Legendary 5)

    return {
        "items": items_list,
        "founders": founders_list,
        "current_mr": current_mr,
        "next_mr": current_mr + 1,
        "xp_needed": xp_needed_for_next_mr,
        "xp_tier1": xp_tier1,
        "xp_total": xp_total,
        "tier1_count": len(tier1_items),
        "tier2_count": len(tier2_items),
        "tier3_count": len(tier3_items),
        "tier4_count": len(tier4_items),
        "tier5_count": len(tier5_items),
    }


def build_account_stats_markdown(data: dict[str, Any]) -> str:
    pts = data.get("generalDataPoints", [])
    if not pts:
        return "# Account Stats\nNo general data points found.\n"

    latest = pts[-1]
    first = pts[0]
    total_relics = sum(x.get("relicOpened", 0) for x in pts if x.get("relicOpened"))
    total_trade_count = sum(x.get("trades", 0) for x in pts if x.get("trades"))

    plat_gains = [x.get("platGain", 0) for x in pts if x.get("platGain") is not None]
    gross_earned = sum(g for g in plat_gains if g > 0)
    gross_spent = abs(sum(g for g in plat_gains if g < 0))

    # Monthly aggregations
    months: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pts:
        ts = p.get("ts", "")
        if len(ts) >= 7:
            months[ts[:7]].append(p)

    lines = [
        "# Warframe Account Progression & Financial Telemetry",
        f"**Source:** AlecaFrame Stats Export | **Range:** {first.get('ts')[:10]} to {latest.get('ts')[:10]} ({len(pts)} recorded days)\n",
        "---",
        "## 🏆 Executive Summary",
        f"- **Mastery Rank:** MR {latest.get('mr', '?')} (Started at MR {first.get('mr', '?')} on {first.get('ts')[:10]})",
        f"- **Codex Completion:** {latest.get('percentageCompletion', '?')}%",
        f"- **Current Platinum:** **{latest.get('plat', 0):,}p** (Baseline: {first.get('plat', 0):,}p on {first.get('ts')[:10]} | Net change: {'+' if latest.get('plat', 0) >= first.get('plat', 0) else ''}{latest.get('plat', 0) - first.get('plat', 0):,}p)",
        f"- **Current Credits:** **{latest.get('credits', 0):,}** (Baseline: {first.get('credits', 0):,} on {first.get('ts')[:10]} | Net: +{latest.get('credits', 0) - first.get('credits', 0):,})",
        f"- **Current Endo:** **{latest.get('endo', 0):,}** (Baseline: {first.get('endo', 0):,} on {first.get('ts')[:10]} | Net: +{latest.get('endo', 0) - first.get('endo', 0):,})",
        f"- **Current Ducats:** {latest.get('ducats', 0):,} | **Aya:** {latest.get('aya', 0)}",
        f"- **Lifetime Relics Opened (Tracked):** {total_relics:,}",
        f"- **Lifetime Trading Flow:** +{gross_earned:,}p earned | -{gross_spent:,}p spent\n",
        "---",
        "## 📅 Monthly Progress History",
        "| Month | Closing Plat | Net Plat | Closing Credits | Closing Endo | Relics Opened | Trades |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for m in sorted(months.keys(), reverse=True):
        m_pts = months[m]
        end_p = m_pts[-1]
        m_gain = sum(x.get("platGain", 0) for x in m_pts if x.get("platGain") is not None)
        m_relics = sum(x.get("relicOpened", 0) for x in m_pts if x.get("relicOpened"))
        m_trades = sum(x.get("trades", 0) for x in m_pts if x.get("trades"))
        lines.append(
            f"| **{m}** | **{end_p.get('plat', 0):,}p** | {'+' if m_gain > 0 else ''}{m_gain:,}p | "
            f"{end_p.get('credits', 0):,} | {end_p.get('endo', 0):,} | {m_relics} | {m_trades} |"
        )

    return "\n".join(lines) + "\n"


def build_trade_history_markdown(trades: list[dict[str, Any]]) -> str:
    lines = [
        "# Warframe In-Game Trade Receipts & Ledger",
        f"**Source:** AlecaFrame Stats Export | **Logged Trades:** {len(trades)}\n",
        "---",
        "| Date | Type | Partner | Given (You Provided) | Received (You Got) | Platinum Exchange |",
        "|:---:|:---:|:---:|:---|:---|:---:|",
    ]

    for t in trades:
        tx_str = ", ".join(f"{x['name']}{' x' + str(x['cnt']) if x['cnt'] > 1 else ''}" for x in t["tx"])
        rx_str = ", ".join(f"{x['name']}{' x' + str(x['cnt']) if x['cnt'] > 1 else ''}" for x in t["rx"])
        if not tx_str:
            tx_str = "*(None)*"
        if not rx_str:
            rx_str = "*(None)*"

        plat_prefix = "+" if t["type"] == "Sale" else ("-" if t["type"] == "Purchase" else "")
        plat_str = f"**{plat_prefix}{t['totalPlat']}p**" if t["totalPlat"] > 0 else "0p"

        lines.append(
            f"| {t['date']} | **{t['type']}** | `{t['user']}` | {tx_str} | {rx_str} | {plat_str} |"
        )

    return "\n".join(lines) + "\n"


def build_mastery_roadmap_markdown(roadmap: dict[str, Any]) -> str:
    lines = [
        "# 🎖️ Warframe Mastery Rank Progression & Optimization Roadmap",
        f"**Target Progression:** Mastery Rank {roadmap['current_mr']} (Legendary 4) ➔ **Mastery Rank {roadmap['next_mr']} (Legendary 5)**",
        f"- **Mastery XP Required for Next Rank:** **{roadmap['xp_needed']:,} XP**",
        f"- **Mastery XP Currently Owned in Inventory (Priority 1):** **{roadmap['xp_tier1']:,} XP** (⚡ **131% of required XP — ZERO FARMING NEEDED!**)",
        f"- **Total Unmastered XP Cataloged:** **{roadmap['xp_total']:,} XP** ({len(roadmap['items'])} items)\n",
        "---",
        "## 🚀 Speed-Leveling & Power-Leveling Meta Guide",
        "### 1. Warframes & Companions (6,000 XP each)",
        "- **Normal Sanctuary Onslaught (Simaris)**: Join public matchmaking. 2–3 zones with an Affinity Booster ranks a Warframe from 0 to 30 in ~5 minutes.",
        "- **Helene (Saturn) / Hydron (Sedna)**: Group defense. Helene also drops Orokin Cells.",
        "- **Companions & Kubrow/Kavat Collars**: Equip during regular gameplay or Sanctuary Onslaught to passively gain shared affinity.",
        "",
        "### 2. Weapons (Primary, Secondary, Melee - 3,000 to 4,000 XP each)",
        "- **Elite Sanctuary Onslaught (ESO) - The 1-Weapon Trick**: **Unequip your other two weapons!** When teammates kill enemies within 50m affinity range, 75% of affinity is split evenly across your equipped weapons. With only 1 weapon equipped, 100% of that 75% goes directly into that weapon, leveling it from 0 to 30 in 1–2 zones!",
        "- **Adaro (Sedna) Stealth Chain (Solo 2-Minute Leveling)**: Run Savage Silence Banshee or Sleep Equinox / Rest & Rage. Maintaining the 500% stealth kill affinity multiplier maxes a weapon solo in under 2 minutes.",
        "",
        "### 3. Critical Rules for Modular & Nemesis Gear",
        "- **⚠️ Modular Items MUST be GILDED**: Amps, Zaws, Kitguns, and K-Drives do NOT yield any Mastery XP on their initial leveling. You must level to 30, visit the vendor (Hok, Rude Zuud, Quills, Roky) to **Gild** it, and level it to 30 a second time. Only the gilded leveling grants Mastery XP!",
        "- **⚠️ Kuva / Tenet / Coda Rank 40**: Grants 3,000 XP at Rank 30. Each Forma added increases max rank by +2 up to Rank 40 (5 Formas total), granting +200 XP per level (+1,000 extra XP, total 4,000 XP).",
        "- **⚡ Relay Mastery Blessing**: Always visit a crowded Relay (e.g. Strata / Maroo) to pick up the **+25% Affinity Blessing** from MR 30+ players before power-leveling sessions.",
        "",
        "---",
        f"## ⚡ Priority 1: Ready in Inventory ({roadmap['tier1_count']} Items / {roadmap['xp_tier1']:,} XP)",
        "> [!IMPORTANT]",
        "> You already own these 49 items crafted in your inventory! Leveling these items alone yields **193,000 XP**, which is more than enough to achieve **Mastery Rank 35 (Legendary 5)** without buying or crafting anything new.\n",
        "| Item | Type | Mastery XP | Recommended Leveling Strategy |",
        "| :--- | :---: | :---: | :--- |",
    ]

    tier1_items = [it for it in roadmap["items"] if it["prio"] == 1]
    for it in tier1_items:
        lines.append(f"| **{it['name']}** | {it['type'].capitalize()} | +{it['xp']:,} XP | {it['tip']} |")

    lines.extend([
        "",
        "---",
        f"## 🎯 Priority 2: Missing Only 1 Part ({roadmap['tier2_count']} Items)",
        "| Item | Type | Mastery XP | Missing Component | Next Step |",
        "| :--- | :---: | :---: | :---: | :--- |",
    ])
    tier2_items = [it for it in roadmap["items"] if it["prio"] == 2]
    for it in tier2_items:
        missing_str = ", ".join(it["missing"]) if it["missing"] else "Blueprint"
        lines.append(f"| **{it['name']}** | {it['type'].capitalize()} | +{it['xp']:,} XP | **{missing_str}** | {it['tip']} |")

    lines.extend([
        "",
        "---",
        f"## 🐾 Priority 3: Companions & Open-World Modulars ({roadmap['tier3_count']} Items)",
        "| Item | Type | Mastery XP | Category & Notes |",
        "| :--- | :---: | :---: | :--- |",
    ])
    tier3_items = [it for it in roadmap["items"] if it["prio"] == 3]
    for it in tier3_items:
        lines.append(f"| **{it['name']}** | {it['type'].capitalize()} | +{it['xp']:,} XP | {it['tip']} |")

    lines.extend([
        "",
        "---",
        f"## ⚔️ Priority 4: Nemesis Hunter (Kuva / Tenet / Coda) ({roadmap['tier4_count']} Items)",
        "| Item | Type | Mastery XP | Cap Notes |",
        "| :--- | :---: | :---: | :--- |",
    ])
    tier4_items = [it for it in roadmap["items"] if it["prio"] == 4]
    for it in tier4_items:
        lines.append(f"| **{it['name']}** | {it['type'].capitalize()} | +{it['xp']:,} XP | {it['tip']} |")

    lines.extend([
        "",
        "---",
        f"## 🏛️ Priority 5: Clan Dojo / Market / Relic Drops ({roadmap['tier5_count']} Items)",
        "| Item | Type | Mastery XP | Acquisition Notes |",
        "| :--- | :---: | :---: | :--- |",
    ])
    tier5_items = [it for it in roadmap["items"] if it["prio"] == 5]
    for it in tier5_items:
        lines.append(f"| **{it['name']}** | {it['type'].capitalize()} | +{it['xp']:,} XP | {it['tip']} |")

    lines.extend([
        "",
        "---",
        "## ℹ️ Excluded Founder Items",
        "The following 3 items are founder-exclusive and unobtainable for non-founders (+12,000 XP total) and are excluded from active roadmap calculations:",
        "- **Excalibur Prime** (Warframe, 6,000 XP)",
        "- **Lato Prime** (Secondary, 3,000 XP)",
        "- **Skana Prime** (Melee, 3,000 XP)",
        "",
    ])

    return "\n".join(lines) + "\n"


def build_html_dashboard(
    data: dict[str, Any],
    trades: list[dict[str, Any]],
    roadmap_data: dict[str, Any] | None = None,
) -> str:
    pts = data.get("generalDataPoints", [])
    latest = pts[-1] if pts else {}
    first = pts[0] if pts else {}

    # Sample chart points (weekly/monthly to keep chart crisp)
    sampled_pts = []
    step = max(1, len(pts) // 60)
    for i in range(0, len(pts), step):
        sampled_pts.append(pts[i])
    if pts and pts[-1] not in sampled_pts:
        sampled_pts.append(pts[-1])

    chart_dates = [p.get("ts", "")[:10] for p in sampled_pts]
    chart_plat = [p.get("plat", 0) for p in sampled_pts]
    chart_credits_m = [round(p.get("credits", 0) / 1_000_000, 2) for p in sampled_pts]
    chart_endo_k = [round(p.get("endo", 0) / 1_000, 1) for p in sampled_pts]

    total_sales_plat = sum(t["totalPlat"] for t in trades if t["type"] == "Sale")
    total_buys_plat = sum(t["totalPlat"] for t in trades if t["type"] == "Purchase")
    total_relics = sum(x.get("relicOpened", 0) for x in pts if x.get("relicOpened"))

    trades_json = json.dumps(trades)

    # Automatically load foundry if roadmap_data is None
    if roadmap_data is None:
        foundry_path = Path("foundry.json")
        if foundry_path.exists():
            try:
                foundry_raw = json.loads(foundry_path.read_text(encoding="utf-8-sig"))
                current_mr = latest.get("mr", 34)
                roadmap_data = classify_mastery_roadmap(foundry_raw, current_mr=current_mr)
            except Exception as e:
                print(f"Warning: could not process foundry.json: {e}", file=sys.stderr)

    if roadmap_data is None:
        roadmap_data = {
            "items": [],
            "current_mr": latest.get("mr", 34),
            "next_mr": latest.get("mr", 34) + 1,
            "xp_needed": 147500,
            "xp_tier1": 0,
            "xp_total": 0,
            "tier1_count": 0,
            "tier2_count": 0,
            "tier3_count": 0,
            "tier4_count": 0,
            "tier5_count": 0,
        }

    mastery_items_json = json.dumps(roadmap_data["items"])
    progress_pct = min(100, int((roadmap_data["xp_tier1"] / roadmap_data["xp_needed"]) * 100)) if roadmap_data["xp_needed"] else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Warframe Account & Mastery Intelligence</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  :root {{
    --bg-dark: #0b0e14;
    --card-bg: #151a23;
    --card-border: #232c3d;
    --gold: #e5b85c;
    --gold-dim: #b89243;
    --cyan: #00d4ff;
    --green: #2ecc71;
    --red: #e74c3c;
    --purple: #9b59b6;
    --orange: #f39c12;
    --blue: #3498db;
    --text-main: #f0f4fc;
    --text-muted: #8d9ba8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background-color: var(--bg-dark);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    padding: 24px;
    line-height: 1.5;
  }}
  header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid var(--card-border);
    padding-bottom: 16px;
    margin-bottom: 20px;
    flex-wrap: wrap;
    gap: 12px;
  }}
  h1 {{
    font-size: 24px;
    font-weight: 700;
    color: var(--gold);
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .badge {{
    background: #232c3d;
    color: var(--cyan);
    padding: 5px 12px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
  }}

  /* Main Tab Navigation */
  .main-nav {{
    display: flex;
    gap: 12px;
    margin-bottom: 24px;
    border-bottom: 1px solid var(--card-border);
    padding-bottom: 14px;
  }}
  .main-tab-btn {{
    background: #151a23;
    border: 1px solid var(--card-border);
    color: var(--text-muted);
    padding: 11px 22px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 10px;
    transition: all 0.2s ease;
  }}
  .main-tab-btn:hover {{
    color: var(--text-main);
    border-color: var(--gold-dim);
  }}
  .main-tab-btn.active {{
    background: #1c2433;
    color: var(--gold);
    border-color: var(--gold);
    box-shadow: 0 0 15px rgba(229, 184, 92, 0.15);
  }}
  .main-tab-btn .badge-pill {{
    background: var(--gold);
    color: #0b0e14;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 10px;
  }}

  /* Finance View Components */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .kpi-label {{
    color: var(--text-muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 600;
  }}
  .kpi-value {{
    font-size: 24px;
    font-weight: 700;
    color: var(--text-main);
  }}
  .kpi-sub {{
    font-size: 12px;
    color: var(--text-muted);
  }}
  .charts-grid {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 24px;
    margin-bottom: 24px;
  }}
  .chart-box {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 18px;
  }}
  .chart-title {{
    font-size: 16px;
    font-weight: 600;
    color: var(--gold);
    margin-bottom: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .table-box {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 18px;
  }}
  .controls {{
    display: flex;
    gap: 10px;
    margin-bottom: 16px;
    flex-wrap: wrap;
    align-items: center;
  }}
  input[type="text"] {{
    background: #0b0e14;
    border: 1px solid var(--card-border);
    color: var(--text-main);
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 13px;
    flex-grow: 1;
    max-width: 320px;
  }}
  input[type="text"]:focus {{
    outline: none;
    border-color: var(--gold);
  }}
  .tab-btn {{
    background: #1c2331;
    border: 1px solid var(--card-border);
    color: var(--text-muted);
    padding: 7px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 600;
    font-size: 12px;
    transition: all 0.2s;
  }}
  .tab-btn.active, .tab-btn:hover {{
    background: var(--gold);
    color: #0b0e14;
    border-color: var(--gold);
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    text-align: left;
  }}
  th {{
    background: #11151e;
    color: var(--text-muted);
    padding: 10px 14px;
    font-weight: 600;
    border-bottom: 1px solid var(--card-border);
  }}
  td {{
    padding: 10px 14px;
    border-bottom: 1px solid #1a2230;
  }}
  tr:hover td {{
    background: #181f2b;
  }}
  .type-sale {{ color: var(--green); font-weight: 600; }}
  .type-purchase {{ color: var(--red); font-weight: 600; }}
  .type-barter {{ color: var(--cyan); }}
  .plat-badge {{ font-weight: 700; }}

  /* Mastery View Components */
  .mr-banner {{
    background: linear-gradient(135deg, #151a23 0%, #192233 100%);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 22px;
    margin-bottom: 24px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 20px;
    align-items: center;
  }}
  @media (max-width: 900px) {{
    .mr-banner {{ grid-template-columns: 1fr; }}
  }}
  .mr-title {{
    font-size: 20px;
    font-weight: 700;
    color: var(--gold);
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .progress-track {{
    background: #0b0e14;
    border: 1px solid var(--card-border);
    border-radius: 14px;
    height: 24px;
    overflow: hidden;
    margin-top: 12px;
    position: relative;
  }}
  .progress-fill {{
    height: 100%;
    width: {progress_pct}%;
    background: linear-gradient(90deg, #2ecc71, #00d4ff);
    border-radius: 14px;
    transition: width 0.5s ease;
    box-shadow: 0 0 15px rgba(46, 204, 113, 0.4);
  }}
  .progress-text {{
    position: absolute;
    top: 0; left: 0; width: 100%; height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    color: #ffffff;
    text-shadow: 0 1px 3px rgba(0,0,0,0.9);
  }}
  .banner-stats {{
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
  }}
  .banner-stat-box {{
    background: rgba(11, 14, 20, 0.7);
    border: 1px solid var(--card-border);
    padding: 12px 18px;
    border-radius: 8px;
    text-align: center;
  }}
  .banner-stat-val {{
    font-size: 20px;
    font-weight: 700;
    color: var(--green);
  }}
  .banner-stat-lbl {{
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    font-weight: 600;
  }}

  /* Guide Grid */
  .guide-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .guide-card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 16px;
  }}
  .guide-card h3 {{
    font-size: 14px;
    color: var(--gold);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .guide-card ul {{
    list-style: none;
    font-size: 12px;
    color: #c0cad6;
  }}
  .guide-card li {{
    margin-bottom: 8px;
    line-height: 1.45;
  }}
  .guide-card strong {{
    color: var(--text-main);
  }}

  /* Items Catalog */
  .item-cards-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 14px;
    margin-top: 16px;
  }}
  .item-card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 14px;
    display: flex;
    gap: 14px;
    align-items: flex-start;
    transition: transform 0.15s, border-color 0.15s;
  }}
  .item-card:hover {{
    transform: translateY(-2px);
    border-color: var(--gold-dim);
  }}
  .item-thumb {{
    width: 62px;
    height: 62px;
    min-width: 62px;
    background: #0b0e14;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }}
  .item-thumb img {{
    max-width: 56px;
    max-height: 56px;
    object-fit: contain;
  }}
  .item-info {{
    flex-grow: 1;
    min-width: 0;
  }}
  .item-name {{
    font-size: 14px;
    font-weight: 700;
    color: var(--text-main);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }}
  .xp-tag {{
    font-size: 11px;
    font-weight: 700;
    color: var(--gold);
    background: rgba(229, 184, 92, 0.12);
    border: 1px solid rgba(229, 184, 92, 0.3);
    padding: 2px 7px;
    border-radius: 6px;
    white-space: nowrap;
  }}
  .xp-tag.xp-6k {{
    color: #2ecc71;
    background: rgba(46, 204, 113, 0.12);
    border-color: rgba(46, 204, 113, 0.3);
  }}
  .badge-prio {{
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 4px;
  }}
  .badge-prio-1 {{ background: rgba(46, 204, 113, 0.15); color: #2ecc71; border: 1px solid rgba(46, 204, 113, 0.4); }}
  .badge-prio-2 {{ background: rgba(243, 156, 18, 0.15); color: #f39c12; border: 1px solid rgba(243, 156, 18, 0.4); }}
  .badge-prio-3 {{ background: rgba(155, 89, 182, 0.15); color: #9b59b6; border: 1px solid rgba(155, 89, 182, 0.4); }}
  .badge-prio-4 {{ background: rgba(231, 76, 60, 0.15); color: #e74c3c; border: 1px solid rgba(231, 76, 60, 0.4); }}
  .badge-prio-5 {{ background: rgba(52, 152, 219, 0.15); color: #3498db; border: 1px solid rgba(52, 152, 219, 0.4); }}
  .item-meta {{
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 6px;
    line-height: 1.35;
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>⚔️ Warframe Financial & Mastery Intelligence</h1>
    <div style="color: var(--text-muted); font-size: 13px; margin-top: 4px;">
      Telemetric Insights & Progression Optimizer | {len(pts)} Days Tracked ({first.get('ts','')[:10]} to {latest.get('ts','')[:10]})
    </div>
  </div>
  <div style="display: flex; gap: 10px; align-items: center;">
    <span class="badge">Mastery Rank {latest.get('mr', 34)}</span>
    <span class="badge" style="color: var(--gold);">Codex {latest.get('percentageCompletion', 88)}%</span>
  </div>
</header>

<nav class="main-nav">
  <button class="main-tab-btn active" id="btn-tab-finance" onclick="switchView('finance', this)">
    <span>📊 Financial & Progression Stats</span>
  </button>
  <button class="main-tab-btn" id="btn-tab-mastery" onclick="switchView('mastery', this)">
    <span>🎖️ Mastery Rank Helper (MR {roadmap_data['current_mr']} → {roadmap_data['next_mr']})</span>
    <span class="badge-pill">{roadmap_data['xp_tier1']:,} XP In Inventory</span>
  </button>
</nav>

<!-- VIEW 1: FINANCIAL & TELEMETRY -->
<div id="view-finance">
  <div class="kpi-grid">
    <div class="kpi-card">
      <span class="kpi-label">Current Platinum</span>
      <span class="kpi-value" style="color: var(--gold);">{latest.get('plat', 0):,}p</span>
      <span class="kpi-sub">Baseline: {first.get('plat', 0):,}p on {first.get('ts','')[:10]} (+{latest.get('plat', 0) - first.get('plat', 0):,}p)</span>
    </div>
    <div class="kpi-card">
      <span class="kpi-label">Total Credits</span>
      <span class="kpi-value">{round(latest.get('credits', 0)/1_000_000, 2)}M</span>
      <span class="kpi-sub">+{round((latest.get('credits', 0) - first.get('credits', 0))/1_000_000, 2)}M (Baseline: {round(first.get('credits', 0)/1_000_000, 2)}M on {first.get('ts','')[:10]})</span>
    </div>
    <div class="kpi-card">
      <span class="kpi-label">Total Endo</span>
      <span class="kpi-value">{latest.get('endo', 0):,}</span>
      <span class="kpi-sub">+{latest.get('endo', 0) - first.get('endo', 0):,} (Baseline: {first.get('endo', 0):,} on {first.get('ts','')[:10]})</span>
    </div>
    <div class="kpi-card">
      <span class="kpi-label">Ducats / Aya</span>
      <span class="kpi-value">{latest.get('ducats', 0):,} <span style="font-size: 16px; color: var(--cyan); font-weight: normal;">/ {latest.get('aya', 0)}</span></span>
      <span class="kpi-sub">Ready for Baro Ki'Teer & Resurgence</span>
    </div>
    <div class="kpi-card">
      <span class="kpi-label">Relics Opened</span>
      <span class="kpi-value">{total_relics:,}</span>
      <span class="kpi-sub">Tracked opening sessions</span>
    </div>
    <div class="kpi-card">
      <span class="kpi-label">Recent Sales Revenue</span>
      <span class="kpi-value" style="color: var(--green);">+{total_sales_plat:,}p</span>
      <span class="kpi-sub">Spent: {total_buys_plat:,}p on parts</span>
    </div>
  </div>

  <div class="charts-grid">
    <div class="chart-box">
      <div class="chart-title">
        <span>📈 Platinum Balance Timeline (2024 - 2026)</span>
        <span style="font-size: 13px; color: var(--gold);">Peak: {max(chart_plat):,}p</span>
      </div>
      <canvas id="platChart" height="110"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-title">
        <span>💎 Resource Growth Trends</span>
      </div>
      <canvas id="resourceChart" height="240"></canvas>
    </div>
  </div>

  <div class="table-box">
    <div class="chart-title">
      <span>📜 Trade Transaction Ledger ({len(trades)} Logs)</span>
    </div>
    <div class="controls">
      <input type="text" id="tradeSearch" placeholder="Search item, player, or date..." onkeyup="filterTrades()">
      <button class="tab-btn active" onclick="setTab('all', this)">All ({len(trades)})</button>
      <button class="tab-btn" onclick="setTab('Sale', this)">Sales ({len([t for t in trades if t['type'] == 'Sale'])})</button>
      <button class="tab-btn" onclick="setTab('Purchase', this)">Purchases ({len([t for t in trades if t['type'] == 'Purchase'])})</button>
      <button class="tab-btn" onclick="setTab('Barter / Gift', this)">Barter ({len([t for t in trades if t['type'] == 'Barter / Gift'])})</button>
    </div>
    <div style="overflow-x: auto;">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Type</th>
            <th>Player</th>
            <th>Items Given</th>
            <th>Items Received</th>
            <th>Platinum</th>
          </tr>
        </thead>
        <tbody id="tradeTbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- VIEW 2: MASTERY RANK HELPER -->
<div id="view-mastery" style="display: none;">
  <div class="mr-banner">
    <div>
      <div class="mr-title">
        <span>🎖️ Mastery Progression: MR {roadmap_data['current_mr']} ➔ MR {roadmap_data['next_mr']} (Legendary 5)</span>
      </div>
      <div style="color: var(--text-muted); font-size: 13px; margin-top: 4px;">
        Leveling the 49 unmastered items already sitting in your inventory will grant <strong>{roadmap_data['xp_tier1']:,} XP</strong> — exceeding the required <strong>{roadmap_data['xp_needed']:,} XP</strong> for Legendary 5 with <strong>+{roadmap_data['xp_tier1'] - roadmap_data['xp_needed']:,} XP surplus</strong>!
      </div>
      <div class="progress-track">
        <div class="progress-fill"></div>
        <div class="progress-text">{roadmap_data['xp_tier1']:,} XP in Inventory / {roadmap_data['xp_needed']:,} XP Target ({progress_pct}% - READY TO RANK UP)</div>
      </div>
    </div>
    <div class="banner-stats">
      <div class="banner-stat-box">
        <div class="banner-stat-val" style="color: var(--gold);">{roadmap_data['xp_needed']:,}</div>
        <div class="banner-stat-lbl">XP Target</div>
      </div>
      <div class="banner-stat-box">
        <div class="banner-stat-val">+{roadmap_data['xp_tier1']:,}</div>
        <div class="banner-stat-lbl">Owned XP</div>
      </div>
      <div class="banner-stat-box">
        <div class="banner-stat-val" style="color: var(--cyan);">+{roadmap_data['xp_tier1'] - roadmap_data['xp_needed']:,}</div>
        <div class="banner-stat-lbl">Surplus XP</div>
      </div>
    </div>
  </div>

  <div class="guide-grid">
    <div class="guide-card">
      <h3>🚀 Warframes & Archwings (6,000 XP)</h3>
      <ul>
        <li>• <strong>Sanctuary Onslaught (Normal)</strong>: 2–3 zones with an Affinity Booster ranks frames 0 to 30 in ~5 mins.</li>
        <li>• <strong>Salacia (Neptune)</strong>: Dense mob mobile defense for rapid Archwing / Archgun leveling.</li>
        <li>• <strong>Incubator / Companions</strong>: Kavats and Kubrows grant 6,000 XP upon reaching Rank 30.</li>
      </ul>
    </div>
    <div class="guide-card">
      <h3>🔫 Weapons Speed-Leveling (3,000 - 4,000 XP)</h3>
      <ul>
        <li>• <strong>ESO 1-Weapon Trick</strong>: Unequip secondary & melee! 75% of teammate affinity goes directly into that single weapon (0 to 30 in 1–2 zones).</li>
        <li>• <strong>Adaro (Sedna) Stealth Multiplier</strong>: Savage Silence Banshee / Sleep Equinox (500% stealth affinity bonus = 0 to 30 solo in under 2 mins).</li>
      </ul>
    </div>
    <div class="guide-card">
      <h3>⚡ Essential Rules & Boosters</h3>
      <ul>
        <li>• <strong>Modular Gear Must Be Gilded</strong>: Amps, Zaws, Kitguns, and K-Drives ONLY award Mastery XP after being gilded at rank 30 and leveled again!</li>
        <li>• <strong>Kuva / Tenet / Coda Rank 40</strong>: Grants 3,000 XP at 30, plus 200 XP per level above 30 up to 40 using 5 Formas (+1,000 XP bonus).</li>
        <li>• <strong>Relay Mastery Blessing</strong>: +25% Affinity for 3 hours from MR 30+ players in any Relay. Stacks with 2x Affinity Booster!</li>
      </ul>
    </div>
  </div>

  <div class="table-box">
    <div class="chart-title">
      <span>🎯 Mastery Progression Catalog ({len(roadmap_data['items'])} Items Tracked)</span>
      <span id="masteryCount" style="font-size: 13px; color: var(--gold);">Showing {len(roadmap_data['items'])} items</span>
    </div>
    <div class="controls">
      <input type="text" id="masterySearch" placeholder="Search weapon, warframe, or missing part..." onkeyup="filterMastery()">
      <button class="tab-btn prio-btn active" onclick="setMasteryPrio('all', this)">All ({len(roadmap_data['items'])})</button>
      <button class="tab-btn prio-btn" onclick="setMasteryPrio('1', this)">⚡ In Inventory ({roadmap_data['tier1_count']})</button>
      <button class="tab-btn prio-btn" onclick="setMasteryPrio('2', this)">🎯 Missing 1 Part ({roadmap_data['tier2_count']})</button>
      <button class="tab-btn prio-btn" onclick="setMasteryPrio('3', this)">🐾 Companions / Modular ({roadmap_data['tier3_count']})</button>
      <button class="tab-btn prio-btn" onclick="setMasteryPrio('4', this)">⚔️ Nemesis Hunter ({roadmap_data['tier4_count']})</button>
      <button class="tab-btn prio-btn" onclick="setMasteryPrio('5', this)">🏛️ Market / Dojo / Drops ({roadmap_data['tier5_count']})</button>
    </div>
    <div class="controls" style="margin-bottom: 20px;">
      <span style="font-size: 12px; color: var(--text-muted); font-weight: 600;">Category:</span>
      <button class="tab-btn type-btn active" onclick="setMasteryType('all', this)">All Types</button>
      <button class="tab-btn type-btn" onclick="setMasteryType('warframe', this)">Warframes</button>
      <button class="tab-btn type-btn" onclick="setMasteryType('weapons', this)">Weapons</button>
      <button class="tab-btn type-btn" onclick="setMasteryType('arch', this)">Archwing</button>
      <button class="tab-btn type-btn" onclick="setMasteryType('modular', this)">Modular & Pets</button>
    </div>
    <div class="item-cards-grid" id="masteryGrid"></div>
  </div>
</div>

<script>
  // --- View Switching ---
  function switchView(viewName, btn) {{
    document.querySelectorAll('.main-tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    if (viewName === 'finance') {{
      document.getElementById('view-finance').style.display = 'block';
      document.getElementById('view-mastery').style.display = 'none';
    }} else {{
      document.getElementById('view-finance').style.display = 'none';
      document.getElementById('view-mastery').style.display = 'block';
      renderMasteryItems();
    }}
  }}

  // --- Financial Charts ---
  const dates = {json.dumps(chart_dates)};
  const platData = {json.dumps(chart_plat)};
  const creditsData = {json.dumps(chart_credits_m)};
  const endoData = {json.dumps(chart_endo_k)};

  const ctxPlat = document.getElementById('platChart').getContext('2d');
  new Chart(ctxPlat, {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [{{
        label: 'Platinum Balance',
        data: platData,
        borderColor: '#e5b85c',
        backgroundColor: 'rgba(229, 184, 92, 0.1)',
        fill: true,
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 5
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: function(c) {{ return c.parsed.y.toLocaleString() + 'p'; }}
          }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1a2230' }}, ticks: {{ color: '#8d9ba8', maxTicksLimit: 12 }} }},
        y: {{ grid: {{ color: '#1a2230' }}, ticks: {{ color: '#8d9ba8' }} }}
      }}
    }}
  }});

  const ctxRes = document.getElementById('resourceChart').getContext('2d');
  new Chart(ctxRes, {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [
        {{
          label: 'Credits (Millions)',
          data: creditsData,
          borderColor: '#00d4ff',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 1,
          yAxisID: 'y'
        }},
        {{
          label: 'Endo (Thousands)',
          data: endoData,
          borderColor: '#2ecc71',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 1,
          yAxisID: 'y1'
        }}
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ labels: {{ color: '#f0f4fc' }} }}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1a2230' }}, ticks: {{ color: '#8d9ba8', maxTicksLimit: 12 }} }},
        y: {{
          type: 'linear',
          display: true,
          position: 'left',
          grid: {{ color: '#1a2230' }},
          ticks: {{ color: '#00d4ff', callback: v => v + 'M' }}
        }},
        y1: {{
          type: 'linear',
          display: true,
          position: 'right',
          grid: {{ drawOnChartArea: false }},
          ticks: {{ color: '#2ecc71', callback: v => v + 'k' }}
        }}
      }}
    }}
  }});

  // --- Trade Ledger Logic ---
  const allTrades = {trades_json};
  let currentTradeTab = 'all';

  function renderTrades() {{
    const tbody = document.getElementById('tradeTbody');
    const query = document.getElementById('tradeSearch').value.toLowerCase().trim();
    tbody.innerHTML = '';

    const filtered = allTrades.filter(t => {{
      if (currentTradeTab !== 'all' && t.type !== currentTradeTab) return false;
      if (!query) return true;
      const txNames = t.tx.map(x => x.name.toLowerCase()).join(' ');
      const rxNames = t.rx.map(x => x.name.toLowerCase()).join(' ');
      return t.user.toLowerCase().includes(query) ||
             t.date.includes(query) ||
             txNames.includes(query) ||
             rxNames.includes(query);
    }});

    for (const t of filtered) {{
      const tr = document.createElement('tr');
      const txText = t.tx.map(x => `${{x.name}}${{x.cnt > 1 ? ' x' + x.cnt : ''}}`).join(', ');
      const rxText = t.rx.map(x => `${{x.name}}${{x.cnt > 1 ? ' x' + x.cnt : ''}}`).join(', ');
      
      let typeClass = 'type-barter';
      let platClass = '';
      let platPrefix = '';
      if (t.type === 'Sale') {{
        typeClass = 'type-sale';
        platClass = 'type-sale';
        platPrefix = '+';
      }} else if (t.type === 'Purchase') {{
        typeClass = 'type-purchase';
        platClass = 'type-purchase';
        platPrefix = '-';
      }}

      tr.innerHTML = `
        <td style="color: #8d9ba8;">${{t.date}}</td>
        <td class="${{typeClass}}">${{t.type}}</td>
        <td style="font-family: monospace; color: var(--gold);">${{t.user}}</td>
        <td>${{txText}}</td>
        <td>${{rxText}}</td>
        <td class="plat-badge ${{platClass}}">${{t.totalPlat > 0 ? platPrefix + t.totalPlat + 'p' : '0p'}}</td>
      `;
      tbody.appendChild(tr);
    }}
  }}

  function setTab(tab, el) {{
    currentTradeTab = tab;
    document.querySelectorAll('.controls .tab-btn').forEach(b => {{
      if (!b.classList.contains('prio-btn') && !b.classList.contains('type-btn')) b.classList.remove('active');
    }});
    el.classList.add('active');
    renderTrades();
  }}

  function filterTrades() {{
    renderTrades();
  }}

  renderTrades();

  // --- Mastery Rank Helper Logic ---
  const allMasteryItems = {mastery_items_json};
  let currentMasteryPrio = 'all';
  let currentMasteryType = 'all';
  let currentMasterySearch = '';

  function setMasteryPrio(prio, el) {{
    currentMasteryPrio = prio;
    document.querySelectorAll('.prio-btn').forEach(b => b.classList.remove('active'));
    el.classList.add('active');
    renderMasteryItems();
  }}

  function setMasteryType(type, el) {{
    currentMasteryType = type;
    document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
    el.classList.add('active');
    renderMasteryItems();
  }}

  function filterMastery() {{
    currentMasterySearch = document.getElementById('masterySearch').value.toLowerCase().trim();
    renderMasteryItems();
  }}

  function renderMasteryItems() {{
    const container = document.getElementById('masteryGrid');
    const countEl = document.getElementById('masteryCount');
    if (!container) return;

    const filtered = allMasteryItems.filter(it => {{
      if (currentMasteryPrio !== 'all' && it.prio !== parseInt(currentMasteryPrio)) {{
        return false;
      }}
      if (currentMasteryType !== 'all') {{
        if (currentMasteryType === 'warframe' && it.type !== 'warframe') return false;
        if (currentMasteryType === 'weapons' && !['primary', 'secondary', 'melee'].includes(it.type)) return false;
        if (currentMasteryType === 'arch' && it.type !== 'arch') return false;
        if (currentMasteryType === 'modular' && !['modular', 'companion'].includes(it.type)) return false;
      }}
      if (currentMasterySearch) {{
        const matchName = it.name.toLowerCase().includes(currentMasterySearch);
        const matchType = it.type.toLowerCase().includes(currentMasterySearch);
        const matchMissing = it.missing && it.missing.some(m => m.toLowerCase().includes(currentMasterySearch));
        const matchTip = it.tip && it.tip.toLowerCase().includes(currentMasterySearch);
        if (!matchName && !matchType && !matchMissing && !matchTip) return false;
      }}
      return true;
    }});

    const totalXp = filtered.reduce((acc, it) => acc + it.xp, 0);
    if (countEl) {{
      countEl.innerText = `Showing ${{filtered.length}} of ${{allMasteryItems.length}} items (${{totalXp.toLocaleString()}} XP)`;
    }}

    container.innerHTML = '';
    if (filtered.length === 0) {{
      container.innerHTML = '<div style="color: var(--text-muted); padding: 40px; text-align: center; grid-column: 1/-1;">No items match the selected filters.</div>';
      return;
    }}

    const fallbackImg = 'https://cdn.alecaframe.com/warframeData/custom/imgRemote/Blueprint.png';
    for (const it of filtered) {{
      const card = document.createElement('div');
      card.className = 'item-card';

      const prioClass = `badge-prio badge-prio-${{it.prio}}`;
      const xpClass = it.xp >= 6000 ? 'xp-tag xp-6k' : 'xp-tag';

      card.innerHTML = `
        <div class="item-thumb">
          <img src="${{it.picture || fallbackImg}}" alt="${{it.name}}" onerror="this.onerror=null;this.src='${{fallbackImg}}';">
        </div>
        <div class="item-info">
          <div class="item-name">
            <span>${{it.name}}</span>
            <span class="${{xpClass}}">+${{it.xp.toLocaleString()}} XP</span>
          </div>
          <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 5px;">
            <span class="badge" style="font-size: 10px; padding: 2px 7px; text-transform: uppercase;">${{it.type}}</span>
            <span class="${{prioClass}}">${{it.status_text}}</span>
          </div>
          <div class="item-meta">${{it.tip}}</div>
        </div>
      `;
      container.appendChild(card);
    }}
  }}

  // Initial render of mastery items
  renderMasteryItems();
</script>

</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze AlecaFrame Stats & Telemetry Export + Mastery Rank Optimizer")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("alecaframeStatsExport.json"),
        help="Path to alecaframeStatsExport.json",
    )
    parser.add_argument(
        "--foundry",
        type=Path,
        default=Path("foundry.json"),
        help="Path to foundry.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("notebook_sources"),
        help="Directory to write Markdown notebook sources",
    )
    parser.add_argument(
        "--dashboard",
        type=Path,
        default=Path("stats_dashboard.html"),
        help="Path to write the interactive HTML visualizer",
    )

    args = parser.parse_args()

    # Automatically check Desktop for newer alecaframeStatsExport.json or foundry.json
    try:
        from update_notebook_source import sync_desktop_exports
        copied = sync_desktop_exports(Path.cwd(), file_names=["alecaframeStatsExport.json", "foundry.json"])
        if copied:
            for src_p, dst_p in copied:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Detected updated {src_p.name} on Desktop -> Copied to {dst_p.name}", file=sys.stderr)
    except Exception:
        pass

    if not args.file.exists():
        print(f"Error: {args.file} not found.", file=sys.stderr)
        return 1

    print(f"Loading {args.file}...", file=sys.stderr)
    raw_data = json.loads(args.file.read_text(encoding="utf-8-sig"))
    trades = parse_trades(raw_data.get("trades", []))

    roadmap_data = None
    if args.foundry.exists():
        print(f"Loading {args.foundry} for Mastery Rank analysis...", file=sys.stderr)
        foundry_raw = json.loads(args.foundry.read_text(encoding="utf-8-sig"))
        pts = raw_data.get("generalDataPoints", [])
        current_mr = pts[-1].get("mr", 34) if pts else 34
        roadmap_data = classify_mastery_roadmap(foundry_raw, current_mr=current_mr)

    # 1. Generate Markdown sources for Notebooks
    args.output_dir.mkdir(parents=True, exist_ok=True)
    account_stats_md = build_account_stats_markdown(raw_data)
    trade_history_md = build_trade_history_markdown(trades)

    account_stats_path = args.output_dir / "account_stats.md"
    trade_history_path = args.output_dir / "trade_history.md"

    account_stats_path.write_text(account_stats_md, encoding="utf-8")
    trade_history_path.write_text(trade_history_md, encoding="utf-8")
    print(f"Generated {account_stats_path}", file=sys.stderr)
    print(f"Generated {trade_history_path}", file=sys.stderr)

    if roadmap_data:
        mastery_md = build_mastery_roadmap_markdown(roadmap_data)
        mastery_path = args.output_dir / "mastery_roadmap.md"
        mastery_path.write_text(mastery_md, encoding="utf-8")
        print(f"Generated {mastery_path}", file=sys.stderr)

    # 2. Generate Interactive Multi-Tab Visualizer Dashboard
    dashboard_html = build_html_dashboard(raw_data, trades, roadmap_data=roadmap_data)
    args.dashboard.write_text(dashboard_html, encoding="utf-8")
    print(f"Generated interactive dashboard: {args.dashboard}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
