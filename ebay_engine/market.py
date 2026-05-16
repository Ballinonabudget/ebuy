from __future__ import annotations

import re
import statistics
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


PRICE_RE = re.compile(r"\$([0-9][0-9,]*(?:\.[0-9]{2})?)")
COUNT_RE = re.compile(r"([0-9][0-9,]*)\s+(?:results?|sold)", re.IGNORECASE)


def build_query(item: dict) -> str:
    identifier = str(item.get("upc") or item.get("style_code") or "").strip()
    if identifier:
        return identifier
    parts = [
        item.get("brand"),
        item.get("model"),
        item.get("item_type"),
        item.get("color"),
    ]
    category = (item.get("category") or "").lower()
    if category in {"clothing", "sneakers"} and item.get("size"):
        parts.append(str(item.get("size")))
    condition = str(item.get("condition") or "").lower()
    if "new" in condition:
        parts.append("new")
    elif "used" in condition or "pre-owned" in condition:
        parts.append("used")
    return " ".join(str(part).strip() for part in parts if part).strip() or item["folder_name"].replace("_", " ")


def ebay_urls(query: str) -> tuple[str, str]:
    encoded = quote_plus(query)
    active = f"https://www.ebay.com/sch/i.html?_nkw={encoded}&_sop=12"
    sold = f"https://www.ebay.com/sch/i.html?_nkw={encoded}&LH_Sold=1&LH_Complete=1&_sop=13"
    return active, sold


def fetch(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=12) as response:
        return response.read().decode("utf-8", errors="ignore")


def clean_price(value: str) -> float:
    return float(value.replace(",", ""))


def extract_prices(html: str) -> list[float]:
    text = unescape(html)
    prices: list[float] = []
    for match in PRICE_RE.finditer(text):
        price = clean_price(match.group(1))
        if 1 <= price <= 10000:
            prices.append(price)
    return prices


def extract_count(html: str) -> int:
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    matches = [int(match.group(1).replace(",", "")) for match in COUNT_RE.finditer(text)]
    return max(matches) if matches else 0


def trimmed_average(prices: list[float]) -> float:
    uniqueish = prices[:80]
    if not uniqueish:
        return 0.0
    if len(uniqueish) >= 8:
        ordered = sorted(uniqueish)
        trim = max(1, len(ordered) // 10)
        ordered = ordered[trim:-trim]
        return statistics.mean(ordered)
    return statistics.mean(uniqueish)


def remove_outliers(prices: list[float]) -> list[float]:
    uniqueish = prices[:80]
    if len(uniqueish) < 6:
        return uniqueish
    median = statistics.median(uniqueish)
    if median <= 0:
        return uniqueish
    return [price for price in uniqueish if median * 0.45 <= price <= median * 1.9]


def confidence_score(filtered_count: int, active_count: int, sold_count: int, spread: float) -> int:
    score = 0
    if filtered_count >= 12:
        score += 40
    elif filtered_count >= 6:
        score += 28
    elif filtered_count >= 3:
        score += 16
    elif filtered_count:
        score += 8
    if sold_count >= 10:
        score += 25
    elif sold_count >= 4:
        score += 15
    elif sold_count:
        score += 8
    if active_count and sold_count:
        score += 15
    if spread <= 0.35 and filtered_count >= 3:
        score += 20
    elif spread <= 0.7 and filtered_count >= 3:
        score += 10
    return min(score, 100)


def confidence_label(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    if score >= 25:
        return "low"
    return "needs_review"


def research_item(item: dict, settings: dict) -> dict:
    query = build_query(item)
    active_url, sold_url = ebay_urls(query)
    errors: list[str] = []
    active_html = ""
    sold_html = ""

    try:
        active_html = fetch(active_url)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        errors.append(f"Active search failed: {exc}")

    try:
        sold_html = fetch(sold_url)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        errors.append(f"Sold search failed: {exc}")

    sold_prices = extract_prices(sold_html)
    active_prices = extract_prices(active_html)
    filtered_sold_prices = remove_outliers(sold_prices)
    avg_sold = trimmed_average(filtered_sold_prices)
    median_sold = statistics.median(filtered_sold_prices) if filtered_sold_prices else 0.0
    sold_low = min(filtered_sold_prices) if filtered_sold_prices else 0.0
    sold_high = max(filtered_sold_prices) if filtered_sold_prices else 0.0
    active_count = extract_count(active_html) or len(active_prices)
    sold_count = extract_count(sold_html) or min(len(sold_prices), 90)

    discount = float(settings["strategy"]["market_discount_from_avg_sold"])
    price_anchor = median_sold or avg_sold
    expected_sale = price_anchor * (1 - discount) if price_anchor else 0.0
    spread = ((sold_high - sold_low) / median_sold) if median_sold else 1.0
    score = confidence_score(len(filtered_sold_prices), active_count, sold_count, spread)
    confidence = confidence_label(score)

    notes = [
        f"Auto research used eBay search: {query}",
        f"Outlier-filtered average sold: ${avg_sold:,.2f}",
        f"Median sold: ${median_sold:,.2f}",
        f"Filtered sold range: ${sold_low:,.2f}-${sold_high:,.2f}",
        f"Suggested quick-sale price: ${expected_sale:,.2f}",
        f"Sampled {len(sold_prices)} sold-price signals; kept {len(filtered_sold_prices)} after outlier filtering.",
        f"Sampled {len(active_prices)} active-price signals. Confidence score: {score}/100.",
        f"Review before listing: active={active_url} sold={sold_url}",
    ]
    if errors:
        notes.extend(errors)

    return {
        "query": query,
        "avg_sold_price": round(avg_sold, 2),
        "median_sold_price": round(median_sold, 2),
        "sold_price_low": round(sold_low, 2),
        "sold_price_high": round(sold_high, 2),
        "expected_sale_price": round(expected_sale, 2),
        "active_count": int(active_count),
        "sold_count_30d": int(sold_count),
        "shipping_cost": 0.0,
        "sampled_sold_count": len(sold_prices),
        "filtered_sold_count": len(filtered_sold_prices),
        "sampled_active_count": len(active_prices),
        "confidence": confidence,
        "confidence_score": score,
        "notes": "\n".join(notes),
        "active_url": active_url,
        "sold_url": sold_url,
        "errors": errors,
    }
