# ⚔️ Warframe AlecaFrame Telemetry, Market Engine & Mastery Optimizer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-none%20(stdlib%20only)-green.svg)](https://docs.python.org/3/library/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](https://github.com/camezaro-intc/AlecaFrame_Export)
[![NotebookLM Ready](https://img.shields.io/badge/NotebookLM-Optimized%20Sources-purple.svg)](https://notebooklm.google.com/)

A comprehensive, zero-dependency toolkit designed to transform **AlecaFrame** data exports into:
1. **Interactive HTML Visualizer Dashboard** featuring historical Platinum & resource charts, trade transaction ledgers, and a **Mastery Rank (MR) Helper** with live Warframe wiki artwork.
2. **Live Market Pricing & Trading Engine** integrating the **Warframe.market** v2 & v1 APIs to monitor wishlist mod prices, sellable duplicate mods, prime sets, and auto-generated in-game trade whisper commands (`/w <user>...`).
3. **Structured Markdown Knowledge Bases** in [`notebook_sources/`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/notebook_sources) and [`combined.md`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/combined.md) specifically formatted for instant ingestion into **Google Gemini** and **Google NotebookLM**.
4. **Automated GitHub Sync Pipeline** keeping remote GitHub repositories and linked NotebookLM notebooks perpetually updated with zero manual copy-pasting.

---

## 🌟 Key Capabilities

### 1. 🎖️ Mastery Rank (MR) Helper & Progression Optimizer
* **Inventory Analysis**: Automatically inspects [`foundry.json`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/foundry.json) and classifies all unmastered items into prioritized tiers:
  * **⚡ Priority 1 (In Inventory):** Items already owned and crafted in your arsenal (immediate 0-plat / 0-crafting XP wins).
  * **🎯 Priority 2 (Missing 1 Part):** Prime sets and weapons needing only a single component from relics or trading.
  * **🐾 Priority 3 (Companions & Modulars):** Kavat/Kubrow breeding and open-world modular items (Amps, Zaws, K-Drives).
  * **⚔️ Priority 4 (Nemesis Hunter):** Kuva, Tenet, and Infested Coda weapons capable of reaching Rank 40 (with 5 Formas).
  * **🏛️ Priority 5 (Clan / Market / Drops):** Dojo research, Simaris/Baro offerings, and multi-part prime sets.
* **Speed-Leveling Meta Guide**: Integrated power-leveling cheat sheet covering Normal Sanctuary Onslaught (Frames/Archwings), the ESO 1-Weapon Affinity Trick, and Adaro Savage Silence 500% stealth multiplier runs.
* **Live Visual Artwork**: High-resolution transparent item renders sourced directly from the AlecaFrame CDN with graceful fallback placeholders.

### 2. 📊 Financial & Progression Dashboard ([`stats_dashboard.html`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/stats_dashboard.html))
* **Historical Timeline**: Chart.js timeline tracking daily Platinum balances, peak wealth milestones, and resource accumulation (Credits & Endo) across 330+ days.
* **Trade Transaction Ledger**: Filterable and searchable ledger tracking sales, purchases, partner names, itemized trades, and net Platinum exchange.
* **Data Provenance**: Clear baseline comparatives measured against your first recorded AlecaFrame tracking session.

### 3. 💰 Live Warframe.market Pricing Engine ([`market_tracker.py`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/market_tracker.py))
* **Wishlist Monitoring**: Automatically fetches real-time lowest buy/sell orders, 48-hour volume-weighted averages, 90-day baseline prices, and 48-hour sales volume for items listed in [`wishlist.txt`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/wishlist.txt).
* **Inventory Sell Opportunities**: Identifies completed prime sets and duplicate mods with high market demand.
* **Ready-to-Use In-Game Whispers**: Generates click-and-copy whisper commands:
  ```text
  /w PlayerName Hi! I want to buy: "Primed Continuity (Rank 0)" for 45 platinum. (warframe.market)
  ```

### 4. 🤖 Google NotebookLM & Gemini Knowledge Sources
* Splits raw JSON telemetry into clean, token-efficient Markdown sources in [`notebook_sources/`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/notebook_sources):
  * `account_stats.md` — Wallet & account telemetry
  * `mastery_roadmap.md` — Prioritized MR leveling roadmap
  * `trade_history.md` — Itemized trade transaction receipts
  * `market_opportunities.md` — Current live market pricing & buy/sell targets
  * `inventoryMods.md`, `inventorySets.md`, `inventoryParts.md`, `inventoryRelics.md`, `inventoryArcanes.md`, `inventoryMisc.md`, `foundry.md`, `rivens-001.md`
* Generates [`combined.md`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/combined.md) for single-document ingestion.

### 5. 🚀 Automated GitHub Sync ([`push_to_github.py`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/push_to_github.py))
* Automatically detects modified `.md` sources and `.html` dashboards.
* Generates an informative commit summary with current account statistics, mastery progress, and updated file counts.
* Commits and pushes to `origin/main` so linked NotebookLM notebooks always have the latest data without manual file re-uploads.

---

## 📁 Repository Structure

```text
AlecaFrame_Export/
├── README.md                      # Repository documentation & guide
├── .gitignore                     # Ignores __pycache__ and .market_cache
├── stats_dashboard.html           # Interactive multi-tab visualizer dashboard
├── combined.md                    # Monolithic markdown export
├── market_opportunities.md        # Current market pricing & whisper report
├── wishlist.txt                   # User-defined mod & item wishlist
│
├── update_notebook_source.py      # Master pipeline runner (JSON -> MD -> HTML -> Git)
├── stats_analyzer.py              # Telemetry & Mastery Rank optimizer
├── market_tracker.py              # Warframe.market v2/v1 API client
├── push_to_github.py              # Automated Git staging, commit & push engine
│
├── notebook_sources/              # Modular Markdown sources for NotebookLM
│   ├── account_stats.md           # Progression milestones & financial summary
│   ├── mastery_roadmap.md         # Prioritized MR ranking roadmap & leveling guide
│   ├── trade_history.md           # Trade receipts & ledger
│   ├── market_opportunities.md    # Wishlist pricing & in-game trade whispers
│   ├── foundry.md                 # Foundry blueprints & crafting readiness
│   ├── inventoryMods.md           # Mod collection & duplicate tracking
│   ├── inventorySets.md           # Prime sets & trade readiness
│   ├── inventoryParts.md          # Prime parts & components
│   ├── inventoryRelics.md         # Void relics & refinement tiers
│   ├── inventoryArcanes.md        # Arcanes inventory & ranks
│   ├── inventoryMisc.md           # Resources, keys, and miscellaneous items
│   └── rivens-001.md              # Riven mods & weapon stats
│
└── *.json                         # Raw AlecaFrame JSON exports (foundry, inventory, stats)
```

---

## ⚡ Quick Start Guide

### Prerequisites
* **Python 3.10+**
* **Zero external dependencies** (uses only standard library modules: `urllib`, `json`, `sqlite3`, `subprocess`, etc.).
* **Git** configured with access to your repository.

---

### Step 1: Export Data from AlecaFrame
1. Open **AlecaFrame** on your PC.
2. Navigate to **Settings ➔ Export Data**.
3. Export your files into this repository directory:
   * `alecaframeStatsExport.json`
   * `foundry.json`
   * `inventoryMods.json`
   * `inventorySets.json`
   * `inventoryParts.json`
   * `inventoryRelics.json`
   * `inventoryArcanes.json`
   * `inventoryMisc.json`
   * `rivens.json`

---

### Step 2: Run the Master Pipeline
To process all exports, generate markdown sources, build the interactive dashboard, fetch live market prices, and push changes to GitHub automatically, run:

```powershell
python update_notebook_source.py
```

#### Pipeline Execution Flow:
```text
[AlecaFrame JSONs]
        │
        ├──▶ update_notebook_source.py (Generates combined.md & notebook_sources/*.md)
        │            │
        │            ├──▶ stats_analyzer.py (Generates stats_dashboard.html & mastery_roadmap.md)
        │            │
        │            ├──▶ market_tracker.py (Fetches live Warframe.market prices & whispers)
        │            │
        │            └──▶ push_to_github.py (Stages, commits & pushes to GitHub)
        ▼
[GitHub Repository & Gemini NotebookLM Updated]
```

---

## 🛠️ Standalone Tool Usage

Each script can also be executed independently for specific tasks:

### 1. View or Rebuild the Dashboard & Mastery Rank Helper
```powershell
python stats_analyzer.py
```
* Generates [`stats_dashboard.html`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/stats_dashboard.html), [`notebook_sources/account_stats.md`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/notebook_sources/account_stats.md), and [`notebook_sources/mastery_roadmap.md`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/notebook_sources/mastery_roadmap.md).
* Double-click `stats_dashboard.html` to open the interactive dashboard in any browser.

---

### 2. Live Market Intelligence & Wishlist Whispers
```powershell
# Analyze wishlist and top inventory sell opportunities:
python market_tracker.py --wishlist wishlist.txt

# Continuously monitor prices every 15 minutes:
python market_tracker.py --watch --interval 15
```

---

### 3. Push Updates to GitHub On-Demand
```powershell
# Commit and push modified Markdown sources & HTML dashboard:
python push_to_github.py

# Preview changes without committing or pushing (Dry Run):
python push_to_github.py --dry-run
```

---

### 4. Run Pipeline Without Pushing to GitHub
```powershell
python update_notebook_source.py --skip-push
```

---

## 🤖 Google Gemini / NotebookLM Integration

To query your inventory using Google Gemini or NotebookLM:
1. Open **[Google NotebookLM](https://notebooklm.google.com/)**.
2. Create a new Notebook (e.g., *"Warframe Codex & Inventory"*).
3. Add sources by selecting **Import from GitHub** (or upload files from [`notebook_sources/`](file:///c:/Users/ALEJANDRO%20MEZA/Desktop/AlecaFrame_Export/notebook_sources)):
   * Add `mastery_roadmap.md` for leveling advice and unmastered gear queries.
   * Add `market_opportunities.md` for trading and pricing queries.
   * Add `account_stats.md` for historical wallet statistics and trade receipts.
   * Add `foundry.md` and `inventorySets.md` for crafting and relic planning.
4. **Example Queries you can ask NotebookLM:**
   * *"Which unmastered warframes or weapons do I already own in my inventory?"*
   * *"What parts am I missing to complete the Daikyu Prime or Trumna Prime?"*
   * *"What duplicate mods do I own that sell for the highest platinum?"*
   * *"What is the fastest way for me to level up my Caliban Prime and Kuva Sobek?"*

---

## 📄 License
This project is open-source and intended for personal Warframe account intelligence and NotebookLM source ingestion. Warframe and all associated assets are trademarks of Digital Extremes Ltd. Warframe.market is an independent trading platform.

