# ⚔️ Warframe AlecaFrame Telemetry, Market Engine & Mastery Optimizer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-none%20(stdlib%20only)-green.svg)](https://docs.python.org/3/library/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](https://github.com/camezaro-intc/AlecaFrame_Export)
[![NotebookLM Ready](https://img.shields.io/badge/NotebookLM-Optimized%20Sources-purple.svg)](https://notebooklm.google.com/)

A comprehensive, zero-dependency toolkit designed to transform **AlecaFrame** data exports into:
1. **Interactive HTML Visualizer Dashboard** featuring historical Platinum & resource charts, trade transaction ledgers, and a **Mastery Rank (MR) Helper** with live Warframe wiki artwork.
2. **Live Market Pricing & Trading Engine** integrating the **Warframe.market** v2 & v1 APIs to monitor wishlist mod prices, sellable duplicate mods, prime sets, and auto-generated in-game trade whisper commands (`/w <user>...`).
3. **Riven Valuation & Market Intelligence** ([`riven_tracker.py`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/riven_tracker.py)) evaluating roll quality, trait combinations, unrolled buyer premiums, and live Warframe.market auction buyouts across all owned Rivens.
4. **Structured Markdown Knowledge Bases** in [`notebook_sources/`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/notebook_sources) specifically formatted for instant ingestion into **Google Gemini** and **Google NotebookLM** via direct **Google Drive** synchronization.
5. **Two-Way Google Drive Synchronization** keeping both knowledge base markdown sources and active Python scripts continuously synchronized with automatic previous-version archiving (`OLD/`).

---

## 🌟 Key Capabilities

### 1. 🎖️ Mastery Rank (MR) Helper & Progression Optimizer
* **Inventory Analysis**: Automatically inspects `foundry.json` and classifies all unmastered items into prioritized tiers:
  * **⚡ Priority 1 (In Inventory):** Items already owned and crafted in your arsenal (immediate 0-plat / 0-crafting XP wins).
  * **🎯 Priority 2 (Missing 1 Part):** Prime sets and weapons needing only a single component from relics or trading.
  * **🐾 Priority 3 (Companions & Modulars):** Kavat/Kubrow breeding and open-world modular items (Amps, Zaws, K-Drives).
  * **⚔️ Priority 4 (Nemesis Hunter):** Kuva, Tenet, and Infested Coda weapons capable of reaching Rank 40 (with 5 Formas).
  * **🏛️ Priority 5 (Clan / Market / Drops):** Dojo research, Simaris/Baro offerings, and multi-part prime sets.
* **Speed-Leveling Meta Guide**: Integrated power-leveling cheat sheet covering Normal Sanctuary Onslaught (Frames/Archwings), the ESO 1-Weapon Affinity Trick, and Adaro Savage Silence 500% stealth multiplier runs.
* **Live Visual Artwork**: High-resolution transparent item renders sourced directly from the AlecaFrame CDN with graceful fallback placeholders.

### 2. 🔮 Riven Intelligence & Valuation Tracker ([`riven_tracker.py`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/riven_tracker.py))
* **Instant Offline Full-Inventory Audit**: Analyzes all owned Rivens locally in < 0.05 seconds with zero network overhead using AlecaFrame's local traits, roll counts, weapon disposition, and roll grades (`Perfect`, `Good`, `HasPotential`, `Bad`).
* **Live Warframe.market Auction Integration**: Queries live online sellers on Warframe.market to retrieve:
  * **Trash Floor Buyout**: Minimum active price for that weapon's rivens (liquidation floor).
  * **Unrolled Buyout Floor**: Minimum active price for 0-reroll rivens (unrolled buyer premium).
  * **Median Active Buyout**: General market benchmark for usable rolls.
* **Strategic Action Buckets**:
  * 💎 **High-Value / Ready to Sell**: Perfect & Good rolls on meta weapons or unrolled popular weapons.
  * 🎯 **Kuva Reroll Targets**: High-disposition (1.1x+) meta weapons with mediocre rolls (invest Kuva here for max profit).
  * 🪙 **Quick Trash Sale**: Rolled fodder rivens to liquidate at the floor price (15–30p) and free up inventory slots.
  * ♻️ **Transmute / Dissolve**: Obscure weapons with bad rolls to combine 4:1 with a Riven Transmuter or dissolve for Endo.
* **In-Game Trade Chat Strings**: Ready-to-copy chat messages (e.g., `WTS [Corinth Lexi-critacan] unrolled 95p or offer`).

### 3. 📊 Financial & Progression Dashboard ([`stats_dashboard.html`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/stats_dashboard.html))
* **Historical Timeline**: Chart.js timeline tracking daily Platinum balances, peak wealth milestones, and resource accumulation (Credits & Endo) across 330+ days.
* **Trade Transaction Ledger**: Filterable and searchable ledger tracking sales, purchases, partner names, itemized trades, and net Platinum exchange.
* **Data Provenance**: Clear baseline comparatives measured against your first recorded AlecaFrame tracking session.

### 4. 💰 Live Warframe.market Pricing Engine ([`market_tracker.py`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/market_tracker.py))
* **Wishlist Monitoring**: Automatically fetches real-time lowest buy/sell orders, 48-hour volume-weighted averages, 90-day baseline prices, and 48-hour sales volume for items listed in [`wishlist.txt`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/wishlist.txt).
* **Inventory Sell Opportunities**: Identifies completed prime sets and duplicate mods with high market demand.
* **Ready-to-Use In-Game Whispers**: Generates click-and-copy whisper commands:
  ```text
  /w PlayerName Hi! I want to buy: "Primed Continuity (Rank 0)" for 45 platinum. (warframe.market)
  ```

### 5. 🤖 Google Drive & Gemini NotebookLM Integration
* All generated markdown intelligence files are flat-copied directly to **`G:\Mi unidad\WF_DATA\`** for instant ingestion by Google Gemini and NotebookLM:
  * `account_stats.md` — Wallet & account telemetry
  * `mastery_roadmap.md` — Prioritized MR ranking roadmap & leveling guide
  * `trade_history.md` — Itemized trade transaction receipts
  * `market_opportunities.md` — Current live market pricing & buy/sell targets
  * `foundry.md`, `inventorySets.md`, `inventoryParts.md`, `inventoryRelics.md`, `inventoryArcanes.md`, `inventoryMisc.md`, `combined.md`
  * **Mod Categories**: `mods-overview.md`, `mods-warframe.md`, `mods-shotguns.md`, `mods-rifles.md`, `mods-pistols.md`, `mods-melee.md`, `mods-companions.md`, `mods-archwing.md`, `mods-specialized.md`
  * **Arsenal Loadouts**: `builds-overview.md`, `builds-warframes.md`, `builds-shotguns.md`, `builds-rifles.md`, `builds-pistols.md`, `builds-melee.md`, `builds-companions.md`, `builds-archwing.md`
  * **Riven Categories**: `rivens-overview.md`, `rivens-rifles.md`, `rivens-shotguns.md`, `rivens-pistols.md`, `rivens-melee.md`, `rivens-modular.md`
  * *(Note: `riven_intelligence.md` is generated and retained locally in `notebook_sources/`, but is explicitly omitted from Drive uploads)*
* **Automatic Data History Archiving (`OLD/OLD_DATA_{TIMESTAMP}/`)**: Before new files are copied, previous data snapshots are moved into a dedicated timestamped subfolder (`G:\Mi unidad\WF_DATA\OLD\OLD_DATA_{TIME_STAMP_UTC}\`), maintaining a full historical log of previous data refreshes without cluttering the active folder.
* **Active Script Sync (`SCRIPTS/` & `SCRIPTS/OLD/`)**: Active `.py` tools are mirrored to `G:\Mi unidad\WF_DATA\SCRIPTS\` so Gemini has access to the latest code, while previous script revisions are archived in `G:\Mi unidad\WF_DATA\SCRIPTS\OLD\` (keeping the single previous version, no subfolders). *(Note: `riven_tracker.py` is kept strictly local and omitted from Drive syncing).*

---

## 📁 Repository Structure

```text
AlecaFrame_Export/
├── README.md                      # Repository documentation & guide
├── .gitignore                     # Excludes personal data (*.json, *.md, dashboards)
├── wishlist.txt                   # User-defined mod & item wishlist
├── riven_watchlist.txt            # (Optional) User-defined weapon watchlist for Riven pricing
│
├── update_notebook_source.py      # Master pipeline runner (JSON -> MD -> HTML -> Drive)
├── riven_tracker.py               # Riven intelligence engine (Local only, omitted from Drive)
├── market_tracker.py              # Warframe.market standard items v2/v1 client
├── stats_analyzer.py              # Telemetry & Mastery Rank optimizer
├── sync_to_drive.py               # Google Drive flat sync & version archiving engine
│
├── notebook_sources/              # Generated Markdown sources
│   ├── riven_intelligence.md      # Riven valuations & auction floors (Local only, omitted from Drive)
│   ├── mastery_roadmap.md         # Prioritized MR ranking roadmap & leveling guide
│   ├── market_opportunities.md    # Wishlist pricing & in-game trade whispers
│   ├── account_stats.md           # Progression milestones & financial summary
│   ├── trade_history.md           # Trade receipts & ledger
│   └── ...                        # Inventory catalog sources
│
└── *.json                         # Raw AlecaFrame JSON exports (Excluded from Git)
```

---

## ⚡ Quick Start Guide

### Step 1: Export Data from AlecaFrame
1. Open **AlecaFrame** on your PC.
2. Navigate to **Settings ➔ Export Data**.
3. Export your files into this repository directory (or leave them on your **Desktop**).

> [!TIP]
> **Automatic Desktop Detection**: If AlecaFrame exports files directly onto your **Desktop**, `update_notebook_source.py` automatically detects newer exports on your Desktop and copies them in—zero manual moving needed.

---

### Step 2: Run the Master Pipeline
To process all exports, generate markdown sources, evaluate rivens, fetch market prices, and synchronize files to **Google Drive (`G:\Mi unidad\WF_DATA\`)**:

```powershell
python update_notebook_source.py
```

#### Pipeline Execution Flow:
```text
[AlecaFrame JSONs (Desktop / Folder)]
        │
        ├──▶ update_notebook_source.py (Generates combined.md & notebook_sources/*.md)
        │            │
        │            ├──▶ riven_tracker.py (Generates riven_intelligence.md with live auction floors)
        │            │
        │            ├──▶ stats_analyzer.py (Generates stats_dashboard.html & mastery_roadmap.md)
        │            │
        │            ├──▶ market_tracker.py (Fetches live Warframe.market prices & whispers)
        │            │
        │            └──▶ sync_to_drive.py (Syncs to G:\Mi unidad\WF_DATA\ & archives to OLD/)
        ▼
[Google Drive & Gemini NotebookLM Updated]
```

---

## 🛠️ Standalone Tool Usage

Each script can also be executed independently for specific tasks:

### 1. Riven Intelligence & Market Valuation (`riven_tracker.py`)
```powershell
# Analyze all owned rivens and generate report:
python riven_tracker.py

# Filter specifically by weapon category (e.g. Shotguns only):
python riven_tracker.py --type shotgun

# Filter by weapon category and show only the most valuable (Good & Perfect):
python riven_tracker.py --type shotgun --top-valuable

# Check specific weapons on demand:
python riven_tracker.py --weapon "Corinth, Arca Plasmor, Bubonico"

# Filter by roll quality:
python riven_tracker.py --grade Perfect,Good

# Run fast offline audit (no HTTP requests):
python riven_tracker.py --skip-market

# Update Google Drive with the riven intelligence report:
python riven_tracker.py --update-drive
```

---

### 2. Auto-Copy Sources & Scripts to Google Drive (`sync_to_drive.py`)
```powershell
# Copy sync-enabled markdown sources and scripts directly to G:\Mi unidad\WF_DATA\:
python sync_to_drive.py

# Preview what files would be archived to OLD/ and copied (Dry Run):
python sync_to_drive.py --dry-run

# View the sync tokens list for all generated files and scripts:
python sync_to_drive.py --tokens

# Toggle sync token for any file on/off:
python sync_to_drive.py --set-token riven_intelligence.md false
python sync_to_drive.py --set-token riven_intelligence.md true
```

#### 🎛️ Google Drive Sync Tokens (`sync_tokens.json`)
Each file generated in the workspace is associated with a boolean token:
* **`token = true`** ➔ File is synchronized and uploaded to Google Drive.
* **`token = false`** ➔ File is generated and retained locally on your PC, but omitted from Google Drive.

Tokens can be configured directly in `sync_tokens.json` or via `python sync_to_drive.py --set-token <file> <true|false>`:

| Generated File | Sync Token | Description / Purpose |
| :--- | :---: | :--- |
| `account_stats.md` | `true` | Wallet, Credits, Endo, Platinum & account milestones |
| `combined.md` | `true` | Full combined snapshot of all inventory exports |
| `foundry.md` | `true` | Active blueprints, crafting components & foundry items |
| `inventoryArcanes.md` | `true` | Owned arcanes catalog with ranks & quantities |
| `inventoryMisc.md` | `true` | Raw materials, resources, cosmetics & keys |
| `inventoryParts.md` | `true` | Prime weapon and frame components |
| `inventoryRelics.md` | `true` | Void relics categorized by era and refinement |
| `inventorySets.md` | `true` | Prime full set completion status |
| `market_opportunities.md`| `true` | Live market buy/sell targets & in-game whispers |
| `mastery_roadmap.md` | `true` | Prioritized MR ranking roadmap & leveling cheat sheet |
| `trade_history.md` | `true` | Itemized trade transaction receipts |
| `rivens-overview.md` | `true` | Full riven inventory overview, duplicates & veiled summary |
| `rivens-rifles.md` | `true` | Rifles, Bows, Snipers & Launchers riven cards |
| `rivens-shotguns.md` | `true` | Shotgun riven cards |
| `rivens-pistols.md` | `true` | Pistol & Secondary riven cards |
| `rivens-melee.md` | `true` | Melee weapon riven cards |
| `rivens-modular.md` | `true` | Kitgun & Zaw modular riven cards |
| `rivens-*.md` | `true` | Wildcard token matching all riven category files |
| `mods-overview.md` | `true` | High-level mod collection overview, duplicates & Endo summary |
| `mods-warframe.md` | `true` | Core Warframe stats, Auras, Exilus, Drift & Augments |
| `mods-shotguns.md` | `true` | Shotgun damage, multishot, crit & elementals |
| `mods-rifles.md` | `true` | Rifle, Bow, Sniper & Launcher mods |
| `mods-pistols.md` | `true` | Pistol, Secondary & Grimoire/Tome mods |
| `mods-melee.md` | `true` | Melee damage, attack speed, combo & Stance mods |
| `mods-companions.md` | `true` | Sentinel, Beast, Robotic weapon & Precept mods |
| `mods-archwing.md` | `true` | Archwing suit, Heavy Archgun & Archmelee mods |
| `mods-specialized.md` | `true` | Necramech, Railjack, Parazon, Requiem & Peculiars |
| `mods-*.md` | `true` | Wildcard token matching all mod category files |
| `builds-overview.md` | `true` | Summary of all 340+ reconstructed arsenal loadouts |
| `builds-warframes.md` | `true` | Reconstructed Warframe loadouts across active configs |
| `builds-shotguns.md` | `true` | Reconstructed Shotgun loadouts with embedded Rivens |
| `builds-rifles.md` | `true` | Reconstructed Rifle loadouts with embedded Rivens |
| `builds-pistols.md` | `true` | Reconstructed Secondary loadouts with embedded Rivens |
| `builds-melee.md` | `true` | Reconstructed Melee loadouts with embedded Rivens |
| `builds-companions.md`| `true` | Reconstructed Companion & Sentinel loadouts |
| `builds-archwing.md` | `true` | Reconstructed Archwing, Heavy & Necramech loadouts |
| `builds-*.md` | `true` | Wildcard token matching all loadout files |
| `riven_intelligence.md` | **`false`** | Riven appraisals & auction floors (retained locally) |
| `stats_dashboard.html` | **`false`** | Interactive HTML dashboard (local browser viewer) |
| `market_tracker.py` | `true` | Warframe.market pricing engine (mirrored to `SCRIPTS/`) |
| `push_to_github.py` | `true` | Git commit & push automation (mirrored to `SCRIPTS/`) |
| `stats_analyzer.py` | `true` | Telemetry & Mastery rank analyzer (mirrored to `SCRIPTS/`) |
| `sync_to_drive.py` | `true` | Drive sync & version archiving engine (mirrored to `SCRIPTS/`) |
| `update_notebook_source.py` | `true` | Master pipeline runner (mirrored to `SCRIPTS/`) |
| `riven_tracker.py` | **`false`** | Riven valuation engine (retained locally, omitted from Drive) |

---

### 3. View or Rebuild the Dashboard & Mastery Rank Helper
```powershell
python stats_analyzer.py
```
* Generates `stats_dashboard.html`, `notebook_sources/account_stats.md`, and `notebook_sources/mastery_roadmap.md`.
* Double-click `stats_dashboard.html` to open the interactive dashboard in any browser.

---

### 4. Live Market Intelligence & Wishlist Whispers
```powershell
# Analyze wishlist and top inventory sell opportunities:
python market_tracker.py --wishlist wishlist.txt

# Continuously monitor prices every 15 minutes:
python market_tracker.py --watch --interval 15
```

---

### 5. Run Pipeline in Simulation Mode (Dry Run)
```powershell
# Process exports and preview Drive sync without writing files to Google Drive:
python update_notebook_source.py --dry-run
```

---

## 🤖 Google Gemini / NotebookLM Integration

Because markdown files are synchronized directly into your Google Drive (`G:\Mi unidad\WF_DATA\`), you can connect Gemini or Google NotebookLM to that Drive folder.

### Example Queries for Gemini:
* *"Retrieve all my rivens for shotguns and check the prices for the most valuable to sell."*
* *"Which unmastered warframes or weapons do I already own in my inventory?"*
* *"What parts am I missing to complete the Daikyu Prime or Trumna Prime?"*
* *"What duplicate mods do I own that sell for the highest platinum?"*
* *"What is the fastest way for me to level up my Caliban Prime and Kuva Sobek?"*
* *"Which of my rivens are the best candidates to roll with Kuva?"*

---

## 🔒 Privacy & Data Protection

All raw JSON exports (`*.json`), generated markdown reports with personal account information (`combined.md`, `market_opportunities.md`, `stats_dashboard.html`, `notebook_sources/`), and personal watchlists are excluded from Git tracking via `.gitignore`. Your personal inventory telemetry, trade history, and wallet statistics stay strictly on your local PC and your private Google Drive account.

---

## 📄 License
This project is open-source and intended for personal Warframe account intelligence and NotebookLM source ingestion. Warframe and all associated assets are trademarks of Digital Extremes Ltd. Warframe.market is an independent trading platform.
