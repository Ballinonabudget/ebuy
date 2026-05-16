# eBay Engine MVP

Local-first desktop app for turning item photos + a `gist.txt` into a resale decision card, profit estimate, and draft listing package.

## Machine Choice

Build it here first unless the new Mac mini is already set up and will be the machine you use this weekend. This MVP is portable: copy this folder to the new Mac, keep `data/ebay_engine.db`, and update `.env` paths if needed.

Use the new Mac mini now only if:

- it is already on your desk,
- you will photograph/import items there,
- Python 3 is available,
- and you want it to be the always-on command center.

Otherwise, do not wait. Build and test here, then move it.

## Quick Start

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:8787
```

## Folder Intake

Create one folder per item inside the drop zone:

```text
~/eBay_Drop/
  Jordan_1_Chicago_01/
    photo_1.jpg
    photo_2.jpg
    photo_3.jpg
    gist.txt
```

Minimum `gist.txt`:

```text
Condition: Used - Excellent
COGS: 85
Notes: Small scuff on right toe cap, visible in photo 3
```

Useful optional fields:

```text
Brand: Nike
Model: Air Jordan 1 Retro High OG
Size: 10.5
Box: OG box included
Accessories: Extra laces
Ship time: 2 days
Category: sneakers
```

## MVP Flow

1. Drop item folder into `~/eBay_Drop/`
2. Click `Scan Drop Zone`
3. Open the item
4. Add sold comp average, active count, sold count, and expected sale price
5. Review recommendation, fees, profit, and draft listing text
6. List manually on eBay for now
7. Mark item status as listed/sold later

## Files

```text
app.py                 local web server
ebay_engine/           app modules
settings.yaml          editable business defaults
data/ebay_engine.db    SQLite database, created automatically
static/                CSS and JS
templates/             HTML views
```

## What This Version Does Not Do Yet

- No automatic eBay publishing
- No eBay OAuth dependency
- No retailer scraping
- No SMS approval loop
- No phone scanner yet

Those come after the manual resale workflow is proven.
