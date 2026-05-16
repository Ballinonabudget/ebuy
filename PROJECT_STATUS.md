# eBay Engine Project Status

Last updated: 2026-05-13

## Current Stage

Stage 4: Pre-API local listing workflow MVP.

The app is no longer just a folder importer. It can now ingest item folders, read `Gist-template.txt`, store inventory in SQLite, run best-effort eBay market research, calculate resale math, and produce a recommendation plus draft listing text.

## Working App

Local URL:

```text
http://127.0.0.1:8787
```

Project folder:

```text
/Users/miniman/Documents/Codex/2026-05-07/use-the-google-drive-doc-epay
```

Drop zone:

```text
/Users/miniman/eBay_Drop
```

Run command from the project folder:

```bash
python3 app.py
```

## What Is Built

- Local Python web app using standard library only.
- SQLite database at `data/ebay_engine.db`.
- Configurable defaults in `settings.yaml`.
- Drop-zone scanner for item folders.
- Accepts `gist.txt` and `Gist-template.txt`.
- Parses item metadata:
  - brand
  - model
  - category
  - item type
  - size
  - condition
  - box/package
  - accessories
  - tested
  - defects
  - COGS
  - notes
- Imports photo file records.
- Category-specific minimum photo counts:
  - clothing/socks: 3
  - accessories: 3
  - electronics: 5
  - sneakers: 6
- Best-effort eBay auto research button.
- Auto research estimates:
  - 30-day average sold
  - median sold price
  - outlier-filtered sold range
  - expected sale price
  - active listing count
  - sold count
  - sell-through rate
  - confidence score
- Profit math:
  - eBay fee estimate
  - order fee
  - packaging reserve
  - risk reserve
  - net profit
  - ROI
- Basic recommendations:
  - `NEEDS_COMPS`
  - `LIST`
  - `PASS_OR_REPRICE`
  - `LIST_ONLY_IF_CASHFLOW`
  - `WATCH_SATURATION`
- Draft title generation.
- Draft eBay HTML description generation.
- Editable item metadata screen.
- Clean listing package section with:
  - recommended title
  - recommended price
  - readable listing preview
  - copy-ready eBay HTML
  - shipping defaults
  - returns defaults
  - profit summary
  - warning checklist
- Clearer recommendation labels:
  - `SELL_NOW`
  - `SELL_FAST`
  - `LIST_MARKET`
  - `HOLD`
  - `DO_NOT_BUY`
  - `NEEDS_MORE_INFO`
  - `BAD_COMP_MATCH`
- Market confidence, sampled sold count, sampled active count, active/sold pressure, and review links.
- Better pre-API research:
  - median sold price
  - outlier filtering
  - low/high filtered sold range
  - confidence score
  - query builder prefers UPC/style code when available
  - condition-aware search terms
- Photo workflow:
  - photo thumbnails from imported folders
  - cover photo selection
  - category angle checklist
- Local sale tracking:
  - sale price
  - actual eBay fees
  - actual shipping cost
  - sold date
  - actual profit
  - mark item sold
- Status tracking:
  - pending
  - needs_info
  - ready
  - approved
  - listed
  - sold
  - archived

## Current Test Items

Imported from `/Users/miniman/eBay_Drop`:

- Adidas Socks
- Nike Socks
- Rode Mic
- JOBY Action Grip
- JOBY Wavo AIR 2-Person

Example result:

Rode Mic auto research found an expected sale price around `$29-$30` against `$50` COGS, so the app recommended `PASS_OR_REPRICE`.

## Current Limitations

- Product identification still depends mostly on `Gist-template.txt`.
- Auto research uses best-effort eBay webpage parsing, not official eBay API.
- Comp notes are internal research notes, not listing text.
- Auto research confidence is still heuristic and based on best-effort page parsing.
- Manual market snapshot saves do not preserve prior auto-research review links unless auto research is run again.
- Photo preview and cover selection exist, but drag reorder is not built yet.
- No official eBay draft creation yet.
- No eBay OAuth flow yet.
- No sale/order sync.
- No mobile scanning/capture workflow.
- No AI image/product recognition yet.

## Completed Step: Step 3

Step 3 is complete when:

- You can edit item metadata without touching `Gist-template.txt`.
- You can click one item and see a clean copy-paste listing package.
- The app shows warnings before listing, such as:
  - missing COGS
  - missing condition
  - missing photos
  - low/negative profit
  - possible bad comp match
- The draft description has both:
  - readable preview
  - copy-ready eBay HTML
- The app gives a clearer action recommendation than `PASS_OR_REPRICE`.

## Completed Step: Step 4

Better market research:

- Median sold price
- Outlier removal
- New vs used matching through condition-aware query terms
- Price range
- Confidence score
- Better query builder
- UPC/style-code-aware search

## Completed Pre-API Local Workflow Additions

- Photo thumbnails
- Cover photo selection
- Category angle checklist
- Local sold/profit tracking

## Next Step: Step 5

eBay API Integration:

- eBay OAuth
- category suggestions
- official active listing search
- draft inventory item creation
- offer creation
- draft listing creation
- manual approval before publishing

## Later Roadmap

Step 5: eBay API Integration

- eBay OAuth
- category suggestions
- official active listing search
- draft inventory item creation
- offer creation
- draft listing creation
- manual approval before publishing

Step 6: Photo Workflow Enhancements

- reorder photos
- missing angle checklist
- future AI image quality review

Step 7: Sales and Profit Tracking Enhancements

- monthly profit goal dashboard

Step 8: Mobile Companion

- phone capture flow
- barcode/UPC scan
- in-store buy/pass screen
- shelf price input
- market analysis on phone

Step 9: Full Automation

- AI identifies products from photos
- app researches market automatically
- app drafts title/description/item specifics
- app creates eBay draft
- user approves
- app publishes/schedules
- app tracks sale/profit

## Prompt For New Thread

Use this prompt to continue:

```text
We are building the local eBay Engine app in:
/Users/miniman/Documents/Codex/2026-05-07/use-the-google-drive-doc-epay

Read PROJECT_STATUS.md first. Continue with Step 3: build the Listing Package + Editable Item Fields screen. Keep the app local-first, lightweight, and usable for weekend resale listing. Do not start eBay API integration yet.
```
