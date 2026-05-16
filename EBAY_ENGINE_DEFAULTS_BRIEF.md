# eBay Engine Defaults Brief

Source: Google Drive doc `ePay Automated Project Spec`, plus current eBay seller help references checked May 8, 2026.

## Objective

Build the first version as a local desktop-assisted listing engine that helps you start selling this weekend. The system should not try to fully automate buying, listing, or publishing yet. The weekend MVP should help you photograph items, write a simple `gist.txt`, calculate resale viability, draft a listing package, and track expected profit in SQLite.

The operating rule stays: nothing goes live without manual approval.

## Recommended Weekend MVP Scope

Version 1 should be a local command-center workflow:

1. Item folder intake in `~/eBay_Drop/`
2. `gist.txt` parser with required `COGS`
3. SQLite item ledger
4. Manual or semi-manual market comp capture
5. Profit calculator
6. Draft listing recommendation card
7. Local dashboard or generated HTML review page
8. macOS notification when an item is ready

Do not make the first build dependent on eBay OAuth, eBay Inventory API, Twilio, retailer scraping, StockX/GOAT scraping, or mobile scanning. Those are valuable, but they are not needed to start selling within three days.

## Default Listing Strategy

Default format: `BUY_IT_NOW`

Default duration: `GTC` for fixed price listings when API-ready; use `30_DAY_BIN` as the internal recommendation label for now.

Default pricing mode: `MARKET`

Pricing defaults:

- Aggressive: 12% below 30-day sold average
- Market: 5% below 30-day sold average
- Premium: at 30-day sold average, only when sell-through is strong and competition is low

Initial buy/no-buy gates:

- Minimum gross profit: `$25`
- Minimum ROI for weekend flips: `35%`
- Target ROI for sourced arbitrage: `50%`
- Target sell-through window: `30 days`
- High-velocity flag: projected sell-through within `7 days`
- Race-to-bottom warning: active listings exceed sold listings over the last 30 days

Use the 50/100 rule as a sourcing target, not as a blocker for listing items you already own. For current inventory, list anything with clean photos, clear condition, and positive expected profit unless there is account-risk or defect risk.

## Shipping Defaults

Recommended default: buyer-paid calculated shipping for most items.

Why: for the MVP, this protects margin while item weights and box sizes are still inconsistent. Free shipping can be a later optimization once you know your actual average cost.

Default settings:

- Handling time: `2 business days`
- Domestic shipping: calculated buyer-paid shipping
- Carrier/service: USPS Ground Advantage or eBay-recommended comparable economy service for small items
- Expedited option: optional, buyer-paid
- Local pickup: off by default
- International shipping: off by default until the workflow is stable
- Signature confirmation: required when total order value is `$750+`
- Shipping cost estimate reserve: `$9.50` default internal estimate when real dimensions are missing
- Packing material reserve: `$1.50`
- Insurance reserve: `0` by default, configurable per item

Category overrides:

- Sneakers: default shoe box mailer or 16x10x6 box, buyer-paid calculated shipping
- Small electronics: buyer-paid calculated shipping, add insurance/signature when risk or value is high
- Clothing: buyer-paid calculated shipping unless lightweight enough to offer a tested flat rate

Data storage:

- `.env`: no shipping policy values except API credentials
- SQLite: actual package weight, dimensions, chosen service, label cost, tracking number, shipped date
- Settings file: default handling time, default shipping method, default shipping estimate, packaging reserve, international enabled flag

## Returns Defaults

Recommended default for weekend MVP: `30-day buyer-paid returns` for normal resale items where condition can be documented well.

Use `no returns` only for:

- Parts/not working electronics
- As-is items
- Items with uncertain authenticity, function, sizing, or defect risk
- Final-sale categories where returns would create obvious abuse risk

Default return settings:

- Return window: `30 days`
- Return shipping payer: buyer
- Restocking fee: none
- Condition disclosure: required in generated description
- Defects: must be explicitly called out in title/description when material

Reasoning: 30-day returns generally improves buyer trust, but the engine needs category-level override because electronics and as-is items can create avoidable loss.

Data storage:

- SQLite: item-level return policy selected and reason for override
- Settings file: default return window, return payer, no-return categories
- `.env`: none

## Notification Defaults

Recommended default: macOS notification first, SMS later.

Weekend MVP:

- Use macOS local notification or terminal alert when a draft recommendation is ready
- Dashboard remains the approval surface
- No SMS dependency for v1

Version 1.1:

- Add email fallback if needed

Version 2:

- Add Twilio SMS for approve/edit/hold links after listing workflow is reliable

Data storage:

- `.env`: Twilio credentials only when SMS is enabled
- SQLite: notification events, notification status, approval decision, approval timestamp
- Settings file: notification method, enabled/disabled flags, phone number reference key but not secrets

## Photo Standards

Minimum standard per item:

- Minimum photos: `6`
- Recommended photos: `8-12`
- Minimum resolution: `1600px` on the longest edge
- Format: JPG or HEIC converted to JPG for upload workflow
- Background: clean neutral background
- Lighting: bright, no harsh shadows
- Required angles: front, back, left, right, top, bottom/sole, tag/label, defect closeups
- Defect proof: every scuff, stain, scratch, missing accessory, box damage, or screen issue gets a closeup
- File naming: allow flexible names, but normalize internally by sequence

Category additions:

- Sneakers: size tag, outsole, insole/liner, box label, box condition, accessories/laces
- Electronics: front, back, sides/ports, powered-on screen, serial/IMEI status note without exposing sensitive numbers publicly, accessories
- Clothing: front, back, tag, material/care label, measurements, flaws

Validation behavior:

- If fewer than 6 photos, mark item `needs_photos`
- If no defect photo is present but gist mentions defects, mark `needs_defect_photo`
- If no size/spec photo for sneakers/electronics, mark `needs_identifier_photo`

Data storage:

- SQLite: photo records, validation status, inferred angle labels, uploaded URLs later
- Settings file: minimum photo count, required angles by category, min resolution
- `.env`: none

## Fee Assumptions

Default fee model for MVP:

- Final value fee reserve: `13.6%`
- Per-order fee reserve: `$0.40` for orders over `$10`
- Per-order fee reserve: `$0.30` for orders `$10` or less
- Insertion fee reserve: `$0.00` until monthly free listing allowance is exceeded
- Optional promoted listing fee: `0%` by default
- Defect/risk reserve: `3%` for used electronics, `1%` for sneakers/clothing
- Refund/return reserve: `0%` initially, configurable later once real return rate exists

Formula:

```text
estimated_net_profit =
  expected_sale_price
  - COGS
  - estimated_ebay_final_value_fee
  - per_order_fee
  - estimated_shipping_cost_if_seller_paid
  - packaging_reserve
  - risk_reserve
```

Important: eBay fee rates vary by category, Store subscription, seller status, listing upgrades, and policy penalties. The MVP should use conservative defaults, then store item-level actuals once sales happen.

Data storage:

- `.env`: eBay API credentials only, never fee percentages
- SQLite: category fee rate used, estimated fees, actual fees, sale price, payout, label cost, net profit
- Settings file: default fee rates, category overrides, risk reserves, promoted listing default

## Configuration Placement

Use `.env` only for secrets and machine-specific paths. Do not bury business rules in `.env`.

| Setting | Recommended Home | Reason |
|---|---|---|
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, OAuth tokens | `.env` | Secret credentials |
| Claude/OpenAI API key | `.env` | Secret credentials |
| Twilio SID/token | `.env` | Secret credentials |
| Drop zone path | `.env` or settings file | Machine-specific, but not secret |
| Database path | `.env` or settings file | Machine-specific |
| Default shipping policy | settings file | Business rule, editable without DB migration |
| Default return policy | settings file | Business rule |
| Default fee assumptions | settings file | Business rule that changes over time |
| Category-specific rules | settings file | Easy to revise |
| Monthly profit target | SQLite | User/business data that changes often |
| Item COGS | SQLite | Per-item financial record |
| Photo metadata | SQLite | Per-item operational record |
| Market comps | SQLite | Historical item research |
| Approval decisions | SQLite | Audit trail |
| Actual sale/fee/shipping cost | SQLite | Financial truth |

Recommended config files:

```text
/Users/miniman/SACC/.env
/Users/miniman/SACC/ebay/settings.yaml
/Users/miniman/SACC/ebay/ebay_engine.db
```

## Suggested `settings.yaml`

```yaml
shipping:
  default_handling_days: 2
  default_model: calculated_buyer_paid
  domestic_enabled: true
  international_enabled: false
  default_estimated_shipping_cost: 9.50
  packaging_reserve: 1.50
  signature_required_order_total: 750

returns:
  default_policy: 30_day_buyer_paid
  no_return_categories:
    - parts_not_working
    - as_is_electronics
    - uncertain_authenticity

photos:
  min_count: 6
  recommended_count: 10
  min_long_edge_px: 1600
  required_angles:
    sneakers: [front, back, left, right, outsole, size_tag, box_label, defects]
    electronics: [front, back, ports, powered_on, accessories, defects]
    clothing: [front, back, tag, measurements, defects]

fees:
  default_final_value_rate: 0.136
  per_order_fee_over_10: 0.40
  per_order_fee_10_or_less: 0.30
  insertion_fee_default: 0.00
  promoted_listing_rate_default: 0.00
  risk_reserve:
    sneakers: 0.01
    clothing: 0.01
    electronics_used: 0.03

strategy:
  default_listing_format: BUY_IT_NOW
  default_pricing_mode: MARKET
  aggressive_discount_from_avg_sold: 0.12
  market_discount_from_avg_sold: 0.05
  minimum_profit_dollars: 25
  minimum_roi_for_owned_inventory: 0.20
  target_roi_for_sourcing: 0.50
  target_sell_through_days: 30
  high_velocity_days: 7
```

## Three-Day Build Plan

Assuming today is Friday, May 8, 2026, the realistic MVP target is a local decision-and-drafting app by Sunday night, May 10, 2026. Full eBay API draft creation depends on the eBay developer account and OAuth approval, so it should not be the critical path.

Day 1: Friday

- Create project folder and SQLite schema
- Implement drop zone watcher
- Parse `gist.txt`
- Import photos and validate minimum photo standards
- Store item records in SQLite
- Generate a local item review page

Day 2: Saturday

- Add manual comp entry form or CSV input for sold comps
- Build profit calculator and recommendation card
- Add fee/shipping/return defaults from `settings.yaml`
- Add listing title and description generator
- Add macOS notification when recommendation is ready

Day 3: Sunday

- Polish dashboard flow: pending, ready, needs info, approved, listed, sold
- Add exportable listing package: title, description, price, photo checklist, item specifics
- Add manual sale update fields for payout, label cost, actual profit
- Test with 5 real items before listing

## Version 2 App Direction

The app should evolve into a local-first desktop app with a mobile capture companion.

Recommended architecture:

- Desktop core: Python + SQLite + local web UI
- Mobile v1: phone camera plus upload/share into Google Drive or local drop zone
- Mobile v2: lightweight PWA for scan/capture/review
- Market data: API-first where available, scraper-backed only where allowed and stable
- Approval: dashboard first, SMS/app push later

Build sequence:

1. Local inventory and listing workflow
2. Market comp workflow
3. eBay OAuth and draft creation
4. Dashboard and approval queue
5. Phone capture workflow
6. Sourcing scanner and QR/barcode lookup
7. Retail arbitrage agents
8. Goal-based buying/listing prioritization
9. White-label supplier research layer
10. Inventory mirroring across eBay, web shop, and future channels

## Do Not Build Yet

Do not build automated retailer purchasing, full white-label sourcing, TikTok trend scraping, automatic eBay publishing, or inventory mirroring before the basic item ledger, profit math, and draft workflow are reliable.

Those features are the long-term product, but for this weekend they add risk without helping you sell immediately.
