from __future__ import annotations

import html


def money(value: float) -> str:
    return f"${value:,.2f}"


def clean(value) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def build_title(item: dict) -> str:
    size = str(item.get("size") or "").strip()
    include_size = size and size.upper() not in {"N/A", "NA", "NONE"}
    parts = [
        item.get("brand"),
        item.get("model"),
        item.get("color"),
        include_size and f"Size {size}",
        item.get("condition"),
    ]
    title = " ".join(str(part).strip() for part in parts if part)
    return title[:80] or item["folder_name"].replace("_", " ")[:80]


def build_plain_description(item: dict, title: str) -> str:
    condition = item.get("condition") or "See photos"
    notes = item.get("notes") or "No additional notes provided."
    box = item.get("box") or "See photos"
    accessories = item.get("accessories") or "Only what is pictured is included."
    tested = item.get("tested") or "N/A"
    defects = item.get("defects") or "None noted"
    return f"""{clean(title)}

Condition: {clean(condition)}
Box/Packaging: {clean(box)}
Accessories: {clean(accessories)}
Tested: {clean(tested)}
Defects: {clean(defects)}

Notes:
{clean(notes)}

Photos show the exact item you will receive. Please review all photos before buying.
Ships within 2 business days. Buyer-paid calculated shipping unless otherwise shown at checkout."""


def build_description(item: dict, rec: dict) -> str:
    condition = item.get("condition") or "See photos"
    notes = item.get("notes") or "No additional notes provided."
    box = item.get("box") or "See photos"
    accessories = item.get("accessories") or "Only what is pictured is included."
    tested = item.get("tested") or "N/A"
    defects = item.get("defects") or "None noted"
    return f"""<h2>{clean(rec['title'])}</h2>
<p><strong>Condition:</strong> {clean(condition)}</p>
<p><strong>Box/Packaging:</strong> {clean(box)}</p>
<p><strong>Accessories:</strong> {clean(accessories)}</p>
<p><strong>Tested:</strong> {clean(tested)}</p>
<p><strong>Defects:</strong> {clean(defects)}</p>
<p><strong>Notes:</strong> {clean(notes)}</p>
<p>Photos show the exact item you will receive. Please review all photos before buying.</p>
<p>Ships within 2 business days. Buyer-paid calculated shipping unless otherwise shown at checkout.</p>"""


def latest_recommendation(item: dict, market: dict | None, settings: dict) -> dict:
    strategy = settings["strategy"]
    fees = settings["fees"]
    shipping = settings["shipping"]

    avg_sold = float((market or {}).get("avg_sold_price") or 0)
    median_sold = float((market or {}).get("median_sold_price") or 0)
    expected_sale = float((market or {}).get("expected_sale_price") or 0)
    active_count = int((market or {}).get("active_count") or 0)
    sold_count = int((market or {}).get("sold_count_30d") or 0)
    shipping_cost = float((market or {}).get("shipping_cost") or 0)
    confidence = (market or {}).get("confidence") or "unknown"

    price_anchor = median_sold or avg_sold
    if not expected_sale and price_anchor:
        expected_sale = price_anchor * (1 - float(strategy["market_discount_from_avg_sold"]))
    suggested_price = expected_sale or price_anchor or 0

    final_value_fee = suggested_price * float(fees["default_final_value_rate"])
    order_fee = float(
        fees["per_order_fee_over_10"] if suggested_price > 10 else fees["per_order_fee_10_or_less"]
    )
    packaging = float(shipping["packaging_reserve"])

    category = (item.get("category") or "default").lower()
    reserve_rates = fees.get("risk_reserve", {})
    reserve_rate = float(reserve_rates.get(category, reserve_rates.get("default", 0.02)))
    risk_reserve = suggested_price * reserve_rate

    cogs = float(item.get("cogs") or 0)
    estimated_profit = (
        suggested_price - cogs - final_value_fee - order_fee - shipping_cost - packaging - risk_reserve
    )
    roi = estimated_profit / cogs if cogs else 0
    sell_through_rate = sold_count / active_count if active_count else (1.0 if sold_count else 0.0)

    if suggested_price <= 0:
        decision = "NEEDS_MORE_INFO"
        rationale = "Add sold comp data or expected sale price before buying/listing."
    elif confidence in {"needs_review", "low"} and avg_sold > suggested_price * 1.8:
        decision = "BAD_COMP_MATCH"
        rationale = "Comp data may include mismatched items. Review eBay links before pricing."
    elif estimated_profit < float(strategy["minimum_profit_dollars"]):
        decision = "DO_NOT_BUY"
        rationale = f"Estimated profit is below {money(float(strategy['minimum_profit_dollars']))}."
    elif roi < float(strategy["minimum_roi_for_owned_inventory"]):
        decision = "HOLD"
        rationale = "ROI is below the owned-inventory target, but it may still be worth listing for cash flow."
    elif sell_through_rate >= 1.0 and roi >= float(strategy["target_roi_for_sourcing"]):
        decision = "SELL_NOW"
        rationale = "Profit, ROI, and sell-through all look strong for a quick listing."
    elif sell_through_rate >= 0.5:
        decision = "SELL_FAST"
        rationale = "Market demand looks healthy. Price slightly below market for faster cash flow."
    elif active_count and sold_count and active_count > sold_count:
        decision = "LIST_MARKET"
        rationale = "Active listings exceed recent sold count. Use market pricing and watch saturation."
    else:
        decision = "LIST_MARKET"
        rationale = "Profit and ROI clear the MVP thresholds."

    title = build_title(item)
    rec = {
        "listing_format": strategy["default_listing_format"],
        "pricing_mode": strategy["default_pricing_mode"],
        "suggested_price": round(suggested_price, 2),
        "ebay_fee": round(final_value_fee, 2),
        "order_fee": round(order_fee, 2),
        "packaging_reserve": round(packaging, 2),
        "risk_reserve": round(risk_reserve, 2),
        "estimated_profit": round(estimated_profit, 2),
        "roi": round(roi, 4),
        "sell_through_rate": round(sell_through_rate, 4),
        "market_confidence": confidence,
        "decision": decision,
        "rationale": rationale,
        "title": title,
    }
    rec["description"] = build_description(item, rec)
    rec["plain_description"] = build_plain_description(item, title)
    return rec
