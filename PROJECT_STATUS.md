# eBuy — Project State & Handoff Document

Last updated: 2026-07-13 (by Claude Code)
Previous revision: 2026-07-12

> **Handoff rule:** This file is the single source of truth for project state.
> Any agent (OpenAI Codex, Claude Code, or human) MUST read this file before
> working, and MUST update Section 9 (Session Log) and any changed sections
> before ending a work session. Commit and push after every meaningful change.

---

## 1. Identity & Locations

| What | Where |
|---|---|
| Project name | eBuy (a.k.a. "ebuy", historically "Ebay Engine" / "epay") |
| GitHub | https://github.com/Ballinonabudget/ebuy (public — never commit secrets) |
| Local working copy | `/Users/miniman/Documents/Codex/2026-05-07/use-the-google-drive-doc-epay` |
| Run | `python3 app.py` → http://127.0.0.1:8787/ui |
| Drop zone (item photos + gists) | `/Users/miniman/eBay_Drop/` |
| Database | `data/ebay_engine.db` (SQLite, git-ignored) |
| Secrets | `.env` (git-ignored; template in `.env.example`) |
| Backup plan | `~/Documents/Codex/2026-05-15/to-ensure-this-directive-is-perfectly/Ebuy Backup and Restore Plan - 2026-05-16.txt` |

**Purpose:** local-first resale command center — drop item photos + a gist
note into `eBay_Drop/`, import them, research comps, get a price/format/
profit recommendation and a draft listing package, then (sandbox today,
production later) create the eBay listing. Nothing publishes to production
without an explicit unlock (see §6).

**Related-but-separate:** `/Users/miniman/Epay/` was an older abandoned
scaffold for the same idea; deleted 2026-07-12 (in Trash as
`Epay-removed-2026-07-12`). Do not resurrect it.

---

## 2. Architecture

Standard-library-only Python web app (no framework, no pip installs needed
to run the core app).

```
app.py                      → entry point, starts server
ebay_engine/
  server.py                 → HTTP routes + HTML rendering (largest module)
  config.py                 → .env + settings.yaml loading, eBay profile
                              system (sandbox/production prefixed keys with
                              legacy fallback), readiness checklist
  db.py                     → SQLite schema + access
  intake.py                 → drop-zone scanner, gist.txt / Gist-template.txt parsing
  market.py                 → pre-API market research (best-effort webpage parsing)
  kicksdb.py                → KicksDB sneaker catalog enrichment: cache-first
                              SKU lookup (kicksdb_cache), fill-blanks-only
                              merge onto items, SKU mismatch guard, stock
                              image reference-only. Inspector:
                              python3 -m ebay_engine.kicksdb <SKU>
  recommend.py              → profit math + recommendation labels
  ebay_api.py               → official eBay REST integration: OAuth tokens
                              (app + user), consent URL, Browse search,
                              media/EPS image upload, inventory item + offer
                              creation, validate, publish plan (dry-run),
                              publish_live, readiness checks
static/modern.js|.css       → single-page UI shell ("FlipBench-style")
templates/                  → legacy server-rendered pages (item, layout)
settings.yaml               → business defaults: shipping, returns, photo
                              minimums/angles per category, fee model, pricing
                              strategy (see file — it is the policy source)
tools/create_ebay_sandbox_defaults.py → one-shot: creates sandbox policies/
                              location and prints the IDs for .env
```

**Key API routes:** `/api/items` (+ `/api/items/{id}/research|draft|publish|enrich`),
`/api/scan`, `/api/audit`, `/api/ebay/status`, `/api/ebay/mode`,
`/api/enrich/backfill`.

**DB tables:** `items`, `photos`, `market_snapshots`, `recommendations`,
`listing_drafts`, `sales`, `ebay_listing_publications`, `photo_publications`,
`market_competition`, `deal_scout_reviews`, `kicksdb_cache`.

**eBay credential profiles:** `.env` keys are prefixed `EBAY_SANDBOX_*` /
`EBAY_PRODUCTION_*` (legacy unprefixed `EBAY_*` still read as sandbox
fallback). Active mode is switched in the UI (`/api/ebay/mode`).

---

## 3. Change history (all commits)

| Date | Commit | What it added |
|---|---|---|
| 2026-05-16 | `c39fe11` Initial Ebuy automation app | Everything in the 2026-05-13 status doc: intake, gist parsing, SQLite inventory, best-effort market research (median, outlier filter, confidence), profit math, recommendation labels, draft title/HTML description, listing package screen, photo thumbnails + cover selection, sold/profit tracking, `settings.yaml` defaults, `EBAY_ENGINE_DEFAULTS_BRIEF.md` |
| 2026-06-12 | `ba81d91` Add eBay sandbox listing workflow | First official eBay API integration (`ebay_api.py`, 483 lines): OAuth app/user tokens, EPS image upload, inventory item + offer creation, validation, dry-run publish plan, live publish; `tools/create_ebay_sandbox_defaults.py`; publish UI |
| 2026-06-12 | `6efb825` Add eBay mode profiles and deal scout | Sandbox vs production credential profiles with UI mode toggle; Deal Scout feature; `/api/ebay/status` readiness reporting |
| 2026-07-12 | `81526e3` Add production readiness checklist and publish safety gates | Production Setup modal: grouped credential checklist (shows presence only, never secrets), safety checks, consent URL, copy-missing-keys; production stays dry-run-only unless `EBAY_ALLOW_PRODUCTION_PUBLISH=true`. (Written 2026-06-12, sat uncommitted for a month, committed during 2026-07-12 audit.) |
| 2026-07-13 | `5d92c51` Add KicksDB catalog enrichment stage | `ebay_engine/kicksdb.py` ported from outlet-plug-blog (urllib, stdlib-only); `kicksdb_cache` table (one API call per SKU ever); fill-blanks-only merge of brand/model/color/retail_price/release_date; SKU mismatch guard; triggers = auto-on-scan (sneakers w/ style code) + overlay button + `/api/enrich/backfill`; `items` gains `retail_price`, `release_date`, `kicksdb_verified` |

---

## 4. Current state (verified 2026-07-13)

- Working tree **clean**, local == `origin/main` @ `5d92c51`.
- `.env` exists and is populated. Sandbox credentials appear configured;
  production profile not filled. `KICKSDB_API_KEY` added 2026-07-13
  (copied from the outlet-plug-blog CLI's `.env`).
- KicksDB enrichment runtime-verified 2026-07-13: real API round trip
  (DH6927-140 → Jordan 4 Retro Midnight Navy, $210 retail, released
  2022-10-29), cache hit on second call, no-overwrite and mismatch guards
  pass, app boots, backfill + enrich endpoints respond, migration applied
  to the live DB (all against a scratch DB; the 2 test API calls are the
  only KicksDB usage so far — `kicksdb_cache` in the live DB is empty).
- No live item has a style code yet, so nothing has been enriched for real.
  Next sneaker gist with a `Style:` line will auto-enrich on scan.
- **Database contents:** 5 items — Rode VideoMic Go (**status: listed** —
  sandbox), Adidas Soccer Metro Sock, Nike Spark, and 2 items with no
  brand/model parsed (ids 3, 4 — likely the JOBY Action Grip and JOBY Wavo
  AIR; their `eBay_Drop` folders have gist templates but **no photos**).
  11 photos imported, 10 photo publications (sandbox EPS uploads), 6 market
  snapshots, 7 recommendations. `listing_drafts`, `sales`,
  `deal_scout_reviews`, `market_competition` are empty.
- `ebay_listing_publications` is **empty** despite the Rode Mic being
  `listed` — the sandbox publish either predated that table or wasn't
  recorded. Worth a look when resuming sandbox work.
- App booted and smoke-tested 2026-07-13 (`/api/items`, enrich endpoints,
  DB migration) — but the core intake→research→publish flows have not been
  re-exercised end-to-end since 2026-06-12.

---

## 5. What works (capability summary)

Intake → research → decide → package → (sandbox) list:

1. **Intake:** scan `eBay_Drop/`, parse `gist.txt`/`Gist-template.txt`
   (brand, model, size, condition, box, accessories, tested, defects, COGS,
   notes), import photos, per-category minimum photo counts + angle checklists.
2. **Research (pre-API, best-effort scraping):** 30-day avg/median sold,
   outlier-filtered range, expected price, active count, sell-through rate,
   confidence score; UPC/style-code-aware, condition-aware queries.
   **Plus** official Browse API search when sandbox/production creds active.
3. **Decide:** fee model from `settings.yaml`, packaging + risk reserves,
   net profit, ROI; labels `SELL_NOW / SELL_FAST / LIST_MARKET / HOLD /
   DO_NOT_BUY / NEEDS_MORE_INFO / BAD_COMP_MATCH`.
4. **Package:** draft title, readable preview + copy-ready eBay HTML,
   shipping/returns defaults, warnings checklist, editable metadata.
5. **List (sandbox):** EPS photo upload, inventory item + offer, validate,
   dry-run publish plan, live publish — exercised against sandbox 2026-06-12
   (Rode Mic). Production is gated (§6).
6. **Track:** item statuses `pending → needs_info → ready → approved →
   listed → sold → archived`; sale price/fees/shipping/profit recording.
7. **Enrich (KicksDB, added 2026-07-13):** style code → catalog data
   (brand, model, colorway, retail price, release date, stock image).
   Cache-first (one API call per unique SKU ever), fill-blanks-only (never
   overwrites gist values), SKU mismatch guard. Triggers: auto on scan for
   sneaker imports with a style code, "KicksDB enrich" button in the review
   overlay, `POST /api/enrich/backfill` one-shot. Net effect: a sneaker
   gist can shrink to ~3 lines (`Style:` / `Size:` + `Condition:` /
   `COGS:`) and research gets precise style-code queries.
8. **Extras:** Deal Scout (built 2026-06-12, unused so far — 0 reviews),
   Production Setup readiness modal, `/api/audit`.

---

## 6. Safety & workflow rules (both agents MUST follow)

1. **Production publish lock:** `EBAY_ALLOW_PRODUCTION_PUBLISH=false` stays
   false until production dry runs pass AND the user explicitly asks for a
   real listing. `server.py` enforces this on the publish route; do not
   bypass or "helpfully" flip it.
2. **Never commit** `.env`, `data/*.db`, or `eBay_Drop` content. Repo is
   public.
3. **Commit + push after every meaningful change** (user's standing backup
   rule). Small, described commits.
4. **User approval before anything outward-facing:** live listings,
   publishing photos to production EPS, any spend.
5. **Backups:** after inventory-import or DB-changing sessions, remind the
   user to back up `.env` + `ebay_engine.db` + `eBay_Drop` per the backup
   plan doc (§1). Automation for this is a wishlist item.

---

## 7. Roadmap

**Step 5 — eBay API integration: IN PROGRESS (sandbox done, production pending)**
- [x] OAuth (app + user tokens, consent URL)
- [x] Official Browse search
- [x] EPS image upload, inventory item + offer creation, validation
- [x] Sandbox end-to-end listing (Rode Mic, 2026-06-12)
- [x] Mode profiles + readiness checklist + publish safety gates
- [ ] Production credentials in `.env` (user task — checklist modal shows gaps)
- [ ] Production dry-run pass
- [ ] First real listing (requires explicit user go + publish unlock)
- [ ] Category suggestion API (still using default category ID)
- [ ] Record publications consistently in `ebay_listing_publications` (§4 gap)

**Step 5.5 — KicksDB enrichment: DONE 2026-07-13** (`5d92c51`). Follow-ons
(not started): feed `retail_price` into recommend.py as a pricing anchor;
prefill eBay item aspects (Brand/Style/Colorway) from enriched fields at
publish time.

**Step 6 — photo workflow:** drag reorder, AI image-quality review.
**Step 7 — sales/profit:** monthly profit goal dashboard; sale/order sync from eBay.
**Step 8 — mobile companion:** phone capture, UPC scan, in-store buy/pass.
**Step 9 — full automation:** AI product ID from photos → auto research →
auto draft → user approves → publish + tracking. (The old `/Users/miniman/Epay`
scaffold attempted this with Claude Vision; deleted, but the idea stands.)

**Immediate next actions (in order):**
1. Boot the app, confirm nothing rotted since 2026-06-12; check the
   `listed`-but-unrecorded Rode Mic publication (§4).
2. Photograph the two JOBY items (their folders have no photos) or archive
   those items.
3. Fill production profile in `.env` via the Production Setup checklist;
   run `tools/create_ebay_sandbox_defaults.py` equivalent for production
   policies if needed.
4. Production dry-run → review plan output → ask user for go/no-go on one
   real listing (candidate: Rode VideoMic Go, but re-check comps — May
   research said PASS_OR_REPRICE at $50 COGS vs ~$29 expected).

---

## 8. Cross-agent handoff protocol (Codex ⇄ Claude Code)

- **Read order for a cold start:** this file → `README.md` →
  `EBAY_ENGINE_DEFAULTS_BRIEF.md` → `settings.yaml` → skim
  `ebay_engine/server.py` route table.
- **State lives in three places only:** this doc (intent/status), git
  history (code truth), SQLite DB (data truth). If they disagree, trust git
  and the DB, then fix this doc.
- **Before ending a session:** update §4 (current state) and §7 (check off
  / reorder), append a §9 log entry, commit, push.
- **Claude Code note:** persistent memory for this project exists in
  Claude's memory dir (`project_epay_engine.md`); it mirrors this doc and
  should be updated when this doc changes materially.
- **Codex note:** historical Codex task folders live under
  `~/Documents/Codex/2026-05-*`; this project folder is the only live one.
- Uncommitted work is considered lost work — the 81526e3 feature sat
  invisible for a month. Don't leave the tree dirty.

---

## 9. Session log

| Date | Agent | Summary |
|---|---|---|
| 2026-05-13 | Codex | Status doc written at Stage 4 (pre-API MVP complete) |
| 2026-05-16 | Codex | Initial commit pushed to GitHub; backup plan doc written |
| 2026-06-12 | Codex | Sandbox listing workflow + mode profiles + deal scout committed; readiness-checklist feature written but left uncommitted; sandbox listing of Rode Mic |
| 2026-07-12 | Claude Code | Full audit; committed + pushed the stranded readiness-checklist feature (`81526e3`); deleted legacy `/Users/miniman/Epay` scaffold (→ Trash); rewrote this doc as the standing handoff schematic |
| 2026-07-13 | Claude Code | Pulled `cb5babb` (Documents access restored); built + runtime-verified KicksDB enrichment stage (`5d92c51`): kicksdb.py port, cache table, fill-blanks merge, mismatch guard, scan/button/backfill triggers, UI reference card; `KICKSDB_API_KEY` copied into `.env` |
