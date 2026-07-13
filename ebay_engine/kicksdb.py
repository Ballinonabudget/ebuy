"""KicksDB SKU lookup + item enrichment.

Ported from outlet-plug-blog `pipeline/kicksdb.py` (requests → urllib, stdlib
only). KicksDB's field names vary across endpoint/version (releaseDate vs
releasedAt, retailPrice vs initialPrice, v3 wraps in data.title). We map all
known variants into one internal schema and never invent missing fields —
they come back blank (or None for retail_price).

Enrichment rules:
- Cache-first: one API call per unique SKU ever (`kicksdb_cache` table).
- Fill-blanks-only merge: never overwrites a value the user typed in a gist.
- Mismatch guard: if the returned product's SKU doesn't confirm the queried
  style code, nothing is merged and the item is flagged for review.
- The stock image is reference-only (visual sanity check in the UI) — eBay
  listings must use the user's own photos.

Inspector: python3 -m ebay_engine.kicksdb <SKU> prints normalized + raw.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import load_env

KICKSDB_DEFAULT_BASE_URL = "https://api.kicks.dev/v3/stockx/products"
DEFAULT_TIMEOUT = 15

SNEAKER_CATEGORIES = {"sneakers", "shoes"}


class KicksDBError(RuntimeError):
    """Raised when the KicksDB call fails or returns no usable result."""


def _trait_value(traits: Any, name: str) -> str:
    if not isinstance(traits, list):
        return ""
    name_lower = name.lower()
    for t in traits:
        if isinstance(t, dict) and str(t.get("trait", "")).lower() == name_lower:
            v = t.get("value")
            return str(v) if v is not None else ""
    return ""


_DATE_PATTERNS = [
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})"),         # 2026-04-15...
    re.compile(r"^(\d{2})/(\d{2})/(\d{4})"),         # MM/DD/YYYY
]

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}
# "Released on May 30, 2025"
_DESC_DATE_MDY = re.compile(r"[Rr]eleased on (\w+)\s+(\d{1,2}),?\s+(\d{4})")
# "released on the 29th of October, 2022"
_DESC_DATE_ORDINAL = re.compile(r"[Rr]eleased on the (\d{1,2})\w* of (\w+),?\s+(\d{4})")
_DESC_PRICE_RE = re.compile(r"retail price of \$([0-9,]+(?:\.\d+)?)")


def _normalize_date(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    for pat in _DATE_PATTERNS:
        m = pat.match(s)
        if m:
            if len(m.group(1)) == 4:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return s


def _to_number(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    digits = re.sub(r"[^\d.]", "", str(raw))
    return float(digits) if digits else None


def _extract_from_description(desc: str) -> tuple[str, float | None]:
    """Fallback: pull release_date and retail_price from KicksDB prose description."""
    release_date = ""
    retail_price = None

    m = _DESC_DATE_MDY.search(desc)
    if m:
        month = _MONTHS.get(m.group(1).lower(), "")
        if month:
            release_date = f"{m.group(3)}-{month}-{int(m.group(2)):02d}"

    if not release_date:
        m = _DESC_DATE_ORDINAL.search(desc)
        if m:
            month = _MONTHS.get(m.group(2).lower(), "")
            if month:
                release_date = f"{m.group(3)}-{month}-{int(m.group(1)):02d}"

    m = _DESC_PRICE_RE.search(desc)
    if m:
        retail_price = _to_number(m.group(1))

    return release_date, retail_price


def _pick_product(payload: Any, sku: str) -> dict[str, Any] | None:
    """Choose the best-matching product from a KicksDB response, handling shape variants."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    candidates: list[dict[str, Any]] = []
    if isinstance(data, list):
        candidates = [c for c in data if isinstance(c, dict)]
    elif isinstance(data, dict):
        candidates = [data]
    elif isinstance(payload.get("product"), dict):
        candidates = [payload["product"]]
    elif "title" in payload or "name" in payload:
        candidates = [payload]
    if not candidates:
        return None
    sku_norm = sku.strip().lower()
    for c in candidates:
        for key in ("sku", "styleId", "style_id", "style_code"):
            if str(c.get(key, "")).strip().lower() == sku_norm:
                return c
    return candidates[0]


def _normalize(raw: dict[str, Any], queried_sku: str) -> dict[str, Any]:
    """Map a KicksDB product dict to our internal schema. Missing fields stay blank."""
    title = raw.get("title") or raw.get("name") or raw.get("shoeName") or ""
    brand = raw.get("brand") or raw.get("brandName") or ""
    image = (
        raw.get("image")
        or raw.get("product_image")
        or raw.get("imageUrl")
        or raw.get("thumbnail")
        or ""
    )
    # Do NOT fall back to queried_sku here — an absent SKU field means we
    # cannot confirm this product matches the query, and the empty string
    # will trigger the mismatch guard in enrich_item.
    sku = (
        raw.get("sku")
        or raw.get("styleId")
        or raw.get("style_id")
        or raw.get("style_code")
        or ""
    )
    traits = raw.get("traits") or []
    colorway = (
        raw.get("colorway")
        or _trait_value(traits, "Colorway")
        or raw.get("color")
        or ""
    )
    release_raw = (
        raw.get("releaseDate")
        or raw.get("releasedAt")
        or raw.get("release_date")
        or _trait_value(traits, "Release Date")
        or ""
    )
    retail_raw = (
        raw.get("retailPrice")
        if raw.get("retailPrice") is not None
        else raw.get("initialPrice")
        if raw.get("initialPrice") is not None
        else raw.get("retail_price")
        if raw.get("retail_price") is not None
        else _trait_value(traits, "Retail Price")
    )
    release_date = _normalize_date(str(release_raw))
    retail_price = _to_number(retail_raw)

    description = raw.get("description") or ""
    if description and (not release_date or retail_price is None):
        desc_date, desc_price = _extract_from_description(description)
        if not release_date:
            release_date = desc_date
        if retail_price is None:
            retail_price = desc_price

    return {
        "sku": str(sku).strip(),
        "name": str(title).strip(),
        "brand": str(brand).strip(),
        "colorway": str(colorway).strip(),
        "release_date": release_date,
        "retail_price": retail_price,
        "product_image": str(image).strip(),
    }


def missing_fields(record: dict[str, Any]) -> list[str]:
    """List normalized fields that came back empty — surfaced for honesty."""
    missing = []
    for field in ("name", "brand", "colorway", "release_date", "product_image"):
        if not record.get(field):
            missing.append(field)
    if record.get("retail_price") is None:
        missing.append("retail_price")
    return missing


def sku_matches(returned: str, queried: str) -> bool:
    """Compare SKUs ignoring case and separator style (DH6927-140 == dh6927 140)."""
    normalize = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    return bool(returned) and normalize(returned) == normalize(queried)


def lookup(sku: str, env: dict[str, str] | None = None, *, return_raw: bool = False):
    """Look up a sneaker by SKU via the KicksDB API (no cache).

    Returns a normalized record dict. With return_raw=True, returns
    (record, raw_payload) so the inspector can verify field mappings.
    Raises KicksDBError on auth failure, HTTP error, or no match.
    """
    sku = sku.strip()
    if not sku:
        raise KicksDBError("SKU is empty.")
    env = env if env is not None else load_env()
    key = (env.get("KICKSDB_API_KEY") or "").strip()
    if not key:
        raise KicksDBError("KICKSDB_API_KEY is not set. Fill it in .env.")
    base_url = (env.get("KICKSDB_BASE_URL") or "").strip() or KICKSDB_DEFAULT_BASE_URL
    params = urlencode({"query": sku, "display[image]": "true"})
    request = Request(
        f"{base_url}?{params}",
        headers={"Authorization": key, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        if exc.code == 401:
            raise KicksDBError("KicksDB 401 unauthorized — check KICKSDB_API_KEY.") from exc
        detail = exc.read().decode("utf-8", errors="ignore")
        raise KicksDBError(f"KicksDB HTTP {exc.code}: {detail[:200]}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise KicksDBError(f"KicksDB network error: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise KicksDBError(f"KicksDB returned non-JSON: {body[:200]}") from exc
    product = _pick_product(payload, sku)
    if product is None:
        raise KicksDBError(f"No product found for SKU {sku!r}.")
    record = _normalize(product, sku)
    if return_raw:
        return record, payload
    return record


def cache_key(sku: str) -> str:
    return sku.strip().upper()


def lookup_cached(conn: sqlite3.Connection, sku: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Cache-first lookup: one API call per unique SKU ever."""
    cached = conn.execute(
        "SELECT payload_json, fetched_at FROM kicksdb_cache WHERE sku = ?",
        (cache_key(sku),),
    ).fetchone()
    if cached:
        record = json.loads(cached["payload_json"])
        record["cached"] = True
        record["fetched_at"] = cached["fetched_at"]
        return record
    record = lookup(sku, env)
    conn.execute(
        "INSERT OR REPLACE INTO kicksdb_cache (sku, payload_json) VALUES (?, ?)",
        (cache_key(sku), json.dumps(record)),
    )
    record["cached"] = False
    return record


# items column ← normalized record field, merged only when the column is blank
ENRICH_FIELD_MAP = [
    ("brand", "brand"),
    ("model", "name"),
    ("color", "colorway"),
    ("release_date", "release_date"),
]


def enrich_item(conn: sqlite3.Connection, item: dict, env: dict[str, str] | None = None) -> dict:
    """Fill blank catalog fields on an item from KicksDB. Never overwrites.

    Returns {"status": "enriched"|"mismatch"|"skipped", "filled": [...], ...}.
    Raises KicksDBError on API failure (caller decides how loud to be).
    """
    item_id = int(item["id"])
    style_code = str(item.get("style_code") or "").strip()
    if not style_code:
        return {"itemId": item_id, "status": "skipped", "reason": "Item has no style code."}

    record = lookup_cached(conn, style_code, env)
    result = {
        "itemId": item_id,
        "sku": style_code,
        "cached": bool(record.get("cached")),
        "record": record,
        "filled": [],
    }
    if not sku_matches(record.get("sku", ""), style_code):
        result["status"] = "mismatch"
        result["reason"] = (
            f"KicksDB returned SKU {record.get('sku') or '(none)'} for query "
            f"{style_code}; fields were NOT merged. Verify the style code."
        )
        return result

    updates: dict[str, Any] = {}
    for column, source in ENRICH_FIELD_MAP:
        current = item.get(column)
        blank = current is None or not str(current).strip()
        value = record.get(source)
        if blank and value is not None and str(value).strip():
            updates[column] = str(value).strip()
    retail = record.get("retail_price")
    if not float(item.get("retail_price") or 0) and retail is not None:
        updates["retail_price"] = float(retail)

    assignments = ", ".join(f"{column} = ?" for column in updates)
    if assignments:
        assignments += ", "
    conn.execute(
        f"UPDATE items SET {assignments}kicksdb_verified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (*updates.values(), item_id),
    )
    result["status"] = "enriched"
    result["filled"] = sorted(updates)
    return result


def auto_enrich_candidate(item: dict) -> bool:
    """Scan-time trigger: sneaker-category item with a style code, not yet verified."""
    return (
        bool(str(item.get("style_code") or "").strip())
        and (item.get("category") or "").strip().lower() in SNEAKER_CATEGORIES
        and not item.get("kicksdb_verified")
    )


if __name__ == "__main__":
    # Quick inspector: `python3 -m ebay_engine.kicksdb <SKU>` prints normalized +
    # raw so field mappings can be verified against the real account response.
    import sys

    if len(sys.argv) != 2:
        print("usage: python3 -m ebay_engine.kicksdb <SKU>", file=sys.stderr)
        sys.exit(2)
    try:
        rec, raw = lookup(sys.argv[1], return_raw=True)
    except KicksDBError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    print("--- NORMALIZED ---")
    print(json.dumps(rec, indent=2, default=str))
    miss = missing_fields(rec)
    if miss:
        print(f"--- MISSING FIELDS: {', '.join(miss)} ---")
    print("--- RAW (first 2000 chars) ---")
    print(json.dumps(raw, indent=2, default=str)[:2000])
