from __future__ import annotations

import html
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import app_config
from .db import connect, row, rows
from .ebay_api import (
    EbayApiError,
    EbayConfigError,
    browse_active_listings,
    build_publish_plan,
    publish_live,
    readiness as ebay_readiness,
    upload_media_image_from_file,
)
from .intake import scan_drop_zone
from .market import research_item
from .recommend import latest_recommendation


CONFIG = app_config()


def render_template(name: str, context: dict) -> str:
    template = (CONFIG["base_dir"] / "templates" / name).read_text()
    for key, value in context.items():
        template = template.replace("{{ " + key + " }}", str(value))
    return template


def escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def first(data: dict, name: str, default: str = "") -> str:
    return data.get(name, [default])[0].strip()


def status_options(current: str) -> str:
    statuses = ["pending", "needs_info", "ready", "approved", "listed", "sold", "archived"]
    return "".join(
        f"<option value='{escape(status)}'{' selected' if status == current else ''}>{escape(status)}</option>"
        for status in statuses
    )


def warning_list(item: dict, photos: list[dict], rec: dict, settings: dict) -> str:
    warnings: list[str] = []
    category = (item.get("category") or "general").lower()
    by_category = settings["photos"].get("min_count_by_category", {})
    min_count = int(by_category.get(category, settings["photos"]["min_count"]))
    if not float(item.get("cogs") or 0):
        warnings.append("Missing COGS. Profit and ROI are not reliable.")
    if not (item.get("condition") or "").strip():
        warnings.append("Missing condition. Add condition before copy/paste listing.")
    if len(photos) < min_count:
        warnings.append(f"Missing photos: {len(photos)}/{min_count} minimum for {category}.")
    if rec["estimated_profit"] <= 0:
        warnings.append("Low or negative estimated profit.")
    if rec["decision"] in {"BAD_COMP_MATCH", "NEEDS_MORE_INFO"}:
        warnings.append("Review market comps before listing.")
    if not warnings:
        warnings.append("No blocking warnings from the local checklist.")
    return "".join(f"<li>{escape(warning)}</li>" for warning in warnings)


def link_or_dash(url: str | None, label: str) -> str:
    if not url:
        return "<span>-</span>"
    return f"<a href='{escape(url)}' target='_blank' rel='noreferrer'>{escape(label)}</a>"


def dollars(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def integer(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def ui_status(status: str | None, rec: dict | None = None) -> str:
    normalized = (status or "pending").lower()
    if normalized in {"listed", "sold"}:
        return "listed"
    if normalized in {"archived", "pass"}:
        return "pass"
    if normalized in {"needs_info", "photos"}:
        return "photos"
    if normalized in {"ready", "approved"}:
        return "ready"
    decision = (rec or {}).get("decision", "")
    if decision in {"SELL_NOW", "SELL_FAST"}:
        return "ready"
    if decision in {"DO_NOT_BUY", "PASS_OR_REPRICE"}:
        return "pass"
    return "review"


def verdict_from_decision(decision: str) -> str:
    if decision in {"SELL_NOW", "SELL_FAST"}:
        return "approve"
    if decision in {"HOLD", "LIST_MARKET"}:
        return "reprice"
    if decision in {"DO_NOT_BUY", "PASS_OR_REPRICE"}:
        return "pass"
    return "review"


def age_label(timestamp: str | None) -> str:
    if not timestamp:
        return "-"
    try:
        from datetime import datetime

        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(value.tzinfo)
        seconds = max(0, int((now - value).total_seconds()))
    except ValueError:
        return str(timestamp).split(" ")[0]
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def category_label(value: str | None) -> str:
    raw = (value or "general").strip().lower()
    return {
        "sneakers": "Sneakers",
        "clothing": "Apparel",
        "electronics": "Tech",
        "accessories": "Bags",
        "general": "General",
    }.get(raw, raw[:1].upper() + raw[1:])


def latest_row(conn, table: str, item_id: int) -> dict | None:
    return row(conn, f"SELECT * FROM {table} WHERE item_id = ? ORDER BY id DESC LIMIT 1", (item_id,))


def market_series(market: dict | None) -> list[dict]:
    if not market:
        return []
    values = [
        dollars(market.get("sold_price_low")),
        dollars(market.get("median_sold_price")),
        dollars(market.get("avg_sold_price")),
        dollars(market.get("expected_sale_price")),
        dollars(market.get("sold_price_high")),
    ]
    values = [value for value in values if value > 0]
    labels = ["-30d", "-21d", "-14d", "-7d", "now"]
    return [{"date": labels[index], "price": round(value, 2)} for index, value in enumerate(values)]


def audit_capabilities() -> list[dict]:
    return [
        {
            "surface": "Queue/sidebar counts",
            "status": "wired",
            "source": "GET /api/items",
            "notes": "Counts are derived from current SQLite items and UI status mapping.",
        },
        {
            "surface": "Inventory table rows",
            "status": "wired",
            "source": "GET /api/items",
            "notes": "Identity, photos, pricing, status, confidence, comps, ROI, and sell-through are live where source records exist.",
        },
        {
            "surface": "Status filters and sort selector",
            "status": "wired-client",
            "source": "client state over /api/items",
            "notes": "Filtering/sorting is immediate and uses loaded API values.",
        },
        {
            "surface": "+ Add photos / watcher card",
            "status": "wired",
            "source": "POST /api/scan",
            "notes": "Scans the drop zone and refreshes the dashboard without leaving the new UI.",
        },
        {
            "surface": "Command search",
            "status": "wired-client",
            "source": "client state over /api/items",
            "notes": "Filters rows by brand, model, category, status, folder, and condition.",
        },
        {
            "surface": "Review overlay navigation",
            "status": "wired-client",
            "source": "GET /api/items/{id}",
            "notes": "Previous/next and J/K hydrate each item from the API.",
        },
        {
            "surface": "Photo carousel",
            "status": "wired",
            "source": "photos table + /photo?id=...",
            "notes": "Thumbnails switch the hero image; missing files show existing placeholder behavior.",
        },
        {
            "surface": "More research",
            "status": "wired",
            "source": "POST /api/items/{id}/research",
            "notes": "Runs the existing eBay research pipeline, saves a market snapshot, and refreshes the overlay.",
        },
        {
            "surface": "Save draft",
            "status": "wired",
            "source": "POST /api/items/{id}/draft",
            "notes": "Persists edits in listing_drafts and refreshes the open overlay.",
        },
        {
            "surface": "Reject / Need pix / Approve & list",
            "status": "wired",
            "source": "POST /api/items/{id}/status",
            "notes": "Updates item status in SQLite and refreshes queues.",
        },
        {
            "surface": "Approve ready bulk action",
            "status": "wired",
            "source": "POST /api/items/bulk-status",
            "notes": "Marks all UI-ready items as listed.",
        },
        {
            "surface": "Active competition table",
            "status": "wired-api-ready",
            "source": "market_competition table + eBay Browse API",
            "notes": "Stores per-listing active comps when EBAY_CLIENT_ID and EBAY_CLIENT_SECRET are configured. Manual POST rows still work.",
        },
        {
            "surface": "Sold-comp chart",
            "status": "partially-wired",
            "source": "market_snapshots aggregate fields",
            "notes": "Uses stored aggregate low/median/average/ask/high. Exact comp points need a future sold_comps table or scraper output.",
        },
        {
            "surface": "Publish to eBay",
            "status": "dry-run-ready",
            "source": "POST /api/items/{id}/publish",
            "notes": "Builds Inventory API payloads and missing-field checks. Live publish is gated behind seller OAuth, policy IDs, public images, and confirm_live=true.",
        },
        {
            "surface": "Listing preview",
            "status": "wired-client",
            "source": "draft form + local photo URLs",
            "notes": "Renders the current draft as an eBay-style preview before saving or publishing.",
        },
    ]


def photo_rows(conn, item_id: int) -> list[dict]:
    return rows(
        conn,
        """
        SELECT
          photos.*,
          photo_publications.public_url AS ebay_public_url,
          photo_publications.use_by_date AS ebay_use_by_date,
          photo_publications.uploaded_at AS ebay_uploaded_at,
          photo_publications.error AS ebay_upload_error
        FROM photos
        LEFT JOIN photo_publications
          ON photo_publications.photo_id = photos.id
          AND photo_publications.provider = 'ebay_media'
          AND photo_publications.ebay_env = ?
        WHERE photos.item_id = ?
        ORDER BY photos.role = 'cover' DESC, photos.sort_order, photos.filename
        """,
        (CONFIG["ebay"].get("env") or "sandbox", item_id),
    )


def confidence_ratio(market: dict | None, item: dict) -> float:
    score = integer((market or {}).get("confidence_score"))
    if score:
        return min(score, 100) / 100
    filled = sum(1 for key in ["brand", "model", "condition", "cogs"] if item.get(key))
    return min(0.85, 0.35 + filled * 0.12)


def money_input(data: dict, name: str) -> float:
    raw = first(data, name, "0").replace("$", "").replace(",", "")
    return float(raw) if raw else 0.0


def photo_cards(photos: list[dict], cover_id: int | None) -> str:
    if not photos:
        return "<p>No photos imported yet.</p>"
    cards = []
    for photo in photos:
        checked = " checked" if photo["id"] == cover_id or photo.get("role") == "cover" else ""
        role = escape(photo.get("role") or "")
        exists = Path(photo["path"]).exists()
        missing = "" if exists else " missing"
        note = role or ("Imported photo" if exists else "File missing from drop zone")
        cards.append(
            f"""
            <label class="photo-card{missing}">
              <img src="/photo?id={photo['id']}" alt="{escape(photo['filename'])}" loading="lazy">
              <span>{escape(photo['filename'])}</span>
              <input type="radio" name="cover_photo_id" value="{photo['id']}"{checked}>
              <small>{escape(note)}</small>
            </label>
            """
        )
    return "".join(cards)


def required_angle_list(category: str, settings: dict) -> str:
    angles = settings["photos"].get("required_angles", {}).get(category.lower(), [])
    if not angles:
        return "<li>No angle checklist configured for this category.</li>"
    return "".join(f"<li>{escape(angle.replace('_', ' '))}</li>" for angle in angles)


def layout(content: str, title: str = "eBay Engine") -> bytes:
    css = (CONFIG["base_dir"] / "static" / "app.css").read_text()
    body = render_template("layout.html", {"title": escape(title), "content": content, "css": css})
    return body.encode()


def item_card(item: dict) -> str:
    status = escape(item["status"])
    name = escape(item["folder_name"].replace("_", " "))
    title = escape(item.get("title") or item.get("model") or "Needs draft")
    return f"""
    <a class="item-card" href="/item?id={item['id']}">
      <div>
        <span class="status">{status}</span>
        <h3>{name}</h3>
        <p>{title}</p>
      </div>
      <strong>${float(item.get('cogs') or 0):,.2f}</strong>
    </a>
    """


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/ui":
            return self.modern_ui()
        if parsed.path == "/api/items":
            return self.api_items()
        if parsed.path == "/api/audit":
            return self.api_audit()
        if parsed.path == "/api/ebay/status":
            return self.api_ebay_status()
        if parsed.path.startswith("/api/items/"):
            return self.api_item(parsed.path)
        if parsed.path == "/":
            return self.home()
        if parsed.path == "/scan":
            return self.scan()
        if parsed.path == "/item":
            params = parse_qs(parsed.query)
            return self.item(int(params.get("id", ["0"])[0]))
        if parsed.path == "/research":
            params = parse_qs(parsed.query)
            return self.research(int(params.get("id", ["0"])[0]))
        if parsed.path == "/photo":
            params = parse_qs(parsed.query)
            return self.photo(int(params.get("id", ["0"])[0]))
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode()
        if parsed.path == "/api/scan":
            return self.api_scan()
        if parsed.path == "/api/items/bulk-status":
            return self.api_bulk_status(raw)
        if parsed.path.startswith("/api/items/"):
            return self.api_item_post(parsed.path, raw)
        data = parse_qs(raw)
        if parsed.path == "/market":
            return self.save_market(data)
        if parsed.path == "/status":
            return self.save_status(data)
        if parsed.path == "/item":
            return self.save_item(data)
        if parsed.path == "/photos":
            return self.save_photos(data)
        if parsed.path == "/sale":
            return self.save_sale(data)
        self.send_error(404)

    def respond(self, body: bytes, status: int = 200, content_type: str = "text/html"):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_json(self, data: dict | list, status: int = 200):
        self.respond(json.dumps(data, default=str).encode(), status, "application/json")

    def read_json(self, raw: str) -> dict:
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {key: value[0] for key, value in parse_qs(raw).items()}

    def redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def modern_ui(self):
        css = (CONFIG["base_dir"] / "static" / "modern.css").read_text()
        js = (CONFIG["base_dir"] / "static" / "modern.js").read_text()
        body = render_template(
            "modern.html",
            {
                "css": css,
                "js": js,
                "drop_zone": escape(CONFIG["drop_zone"]),
            },
        )
        self.respond(body.encode(), content_type="text/html")

    def item_payload(self, conn, item: dict, full: bool = False) -> dict:
        item_id = int(item["id"])
        photos = photo_rows(conn, item_id)
        market = latest_row(conn, "market_snapshots", item_id)
        draft = row(conn, "SELECT * FROM listing_drafts WHERE item_id = ?", (item_id,))
        sale = latest_row(conn, "sales", item_id)
        rec = latest_recommendation(item, market, CONFIG["settings"])
        status = ui_status(item.get("status"), rec)
        ask = dollars((draft or {}).get("start_price")) or dollars(rec.get("suggested_price"))
        net = dollars(rec.get("estimated_profit"))
        roi = dollars(rec.get("roi")) * 100
        sell_through = dollars(rec.get("sell_through_rate")) * 100
        conf = confidence_ratio(market, item)
        photo_urls = [f"/photo?id={photo['id']}" for photo in photos]
        existing_photo_count = sum(1 for photo in photos if Path(photo["path"]).exists())
        missing_photo_count = max(0, len(photos) - existing_photo_count)
        ebay_photo_count = sum(1 for photo in photos if str(photo.get("ebay_public_url") or "").startswith("https://"))
        defects = [part.strip() for part in str(item.get("defects") or "").split(",") if part.strip()]
        payload = {
            "id": str(item_id),
            "engineStatus": item.get("status"),
            "status": status,
            "queue": status,
            "folderName": item.get("folder_name"),
            "sourcePath": item.get("folder_path"),
            "ingestedAt": item.get("created_at"),
            "updatedAt": item.get("updated_at"),
            "age": age_label(item.get("updated_at") or item.get("created_at")),
            "brand": item.get("brand") or "Unknown",
            "model": item.get("model") or item.get("folder_name", "Needs draft").replace("_", " "),
            "styleCode": item.get("style_code") or "",
            "cat": category_label(item.get("category")),
            "condition": item.get("condition") or "Needs condition",
            "size": item.get("size") or "",
            "color": item.get("color") or "",
            "conf": conf,
            "photos": len(photos),
            "existingPhotos": existing_photo_count,
            "missingPhotos": missing_photo_count,
            "ebayPhotos": ebay_photo_count,
            "photoUrls": photo_urls,
            "defects": defects,
            "cogs": dollars(item.get("cogs")),
            "ask": ask or None,
            "net": net,
            "roiPct": roi,
            "sellThru": sell_through if market else None,
            "comps": integer((market or {}).get("sold_count_30d")) if market else None,
            "decision": rec.get("decision"),
            "rationale": rec.get("rationale"),
        }
        if not full:
            return payload

        competition = rows(
            conn,
            """
            SELECT title, condition, price, watchers, url, source, created_at
            FROM market_competition
            WHERE item_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (item_id,),
        )
        checks = [
            {
                "label": f"ROI {roi:.1f}%",
                "pass": roi >= float(CONFIG["settings"]["strategy"]["minimum_roi_for_owned_inventory"]) * 100,
                "rule": f"min {float(CONFIG['settings']['strategy']['minimum_roi_for_owned_inventory']) * 100:.0f}%",
            },
            {
                "label": f"Profit ${net:,.2f}",
                "pass": net >= float(CONFIG["settings"]["strategy"]["minimum_profit_dollars"]),
                "rule": f"min ${float(CONFIG['settings']['strategy']['minimum_profit_dollars']):,.0f}",
            },
            {
                "label": f"Comps {integer((market or {}).get('sold_count_30d'))}",
                "pass": integer((market or {}).get("sold_count_30d")) >= 3,
                "rule": "min 3 sold",
            },
            {
                "label": f"Confidence {conf * 100:.0f}%",
                "pass": conf >= 0.6,
                "rule": "min 60%",
            },
        ]
        market_payload = {
            "fetchedAt": (market or {}).get("created_at"),
            "activeUrl": (market or {}).get("active_url") or "",
            "soldUrl": (market or {}).get("sold_url") or "",
            "query": (market or {}).get("query") or "",
            "confidence": (market or {}).get("confidence") or "unknown",
            "confidenceScore": integer((market or {}).get("confidence_score")),
            "notes": (market or {}).get("notes") or "",
            "sold": {
                "median": dollars((market or {}).get("median_sold_price")),
                "average": dollars((market or {}).get("avg_sold_price")),
                "rangeLow": dollars((market or {}).get("sold_price_low")),
                "rangeHigh": dollars((market or {}).get("sold_price_high")),
                "series": market_series(market),
                "count": integer((market or {}).get("sold_count_30d")),
            },
            "sellThrough": sell_through,
            "competition": {
                "activeCount": integer((market or {}).get("active_count")),
                "listings": [
                    {
                        "title": comp.get("title") or "",
                        "condition": comp.get("condition") or "",
                        "price": dollars(comp.get("price")),
                        "watchers": integer(comp.get("watchers")),
                        "url": comp.get("url") or "",
                        "source": comp.get("source") or "manual",
                    }
                    for comp in competition
                ],
            },
        }
        payload.update(
            {
                "ai": {
                    "conf": conf,
                    "agentLog": [
                        {"line": f"Imported {len(photos)} photo records from drop zone", "severity": "info"},
                        {"line": f"{ebay_photo_count} photo(s) uploaded to eBay Media API for {CONFIG['ebay'].get('env')}", "severity": "info" if ebay_photo_count else "warn"},
                        *(
                            [{"line": f"{missing_photo_count} photo file(s) are missing from saved paths", "severity": "warn"}]
                            if missing_photo_count
                            else []
                        ),
                        {"line": f"Mapped gist fields to {payload['brand']} {payload['model']}", "severity": "info"},
                        {"line": f"Market confidence: {market_payload['confidence']} ({market_payload['confidenceScore']}/100)", "severity": "warn" if conf < 0.6 else "info"},
                    ],
                    "attributes": [
                        {"key": "Brand", "value": payload["brand"], "confidence": conf},
                        {"key": "Model", "value": payload["model"], "confidence": conf},
                        {"key": "Condition", "value": payload["condition"], "confidence": 0.7 if item.get("condition") else 0.25},
                        {"key": "COGS", "value": f"${payload['cogs']:,.2f}", "confidence": 0.95 if payload["cogs"] else 0.2},
                    ],
                    "photos": photo_urls,
                    "defects": defects,
                },
                "market": market_payload,
                "financial": {
                    "cogs": payload["cogs"],
                    "expectedAsk": ask,
                    "feesPct": float(CONFIG["settings"]["fees"]["default_final_value_rate"]),
                    "estimatedNet": net,
                    "roiPct": roi,
                    "verdict": verdict_from_decision(rec.get("decision", "")),
                    "checks": checks,
                    "headline": f"Net ${net:,.2f} · {roi:.1f}% ROI",
                    "reason": rec.get("rationale"),
                },
                "draft": {
                    "seoTitle": (draft or {}).get("title") or rec.get("title") or "",
                    "htmlDescription": (draft or {}).get("description") or rec.get("description") or "",
                    "category": (draft or {}).get("category") or item.get("category") or "general",
                    "shipping": {
                        "service": (draft or {}).get("shipping_service") or CONFIG["settings"]["shipping"]["default_model"],
                    },
                    "format": {
                        "kind": (draft or {}).get("format_kind") or "fixed",
                        "startPrice": ask,
                    },
                    "status": (draft or {}).get("status") or "generated",
                },
                "sale": {
                    "salePrice": dollars((sale or {}).get("sale_price")),
                    "actualEbayFees": dollars((sale or {}).get("actual_ebay_fees")),
                    "actualShippingCost": dollars((sale or {}).get("actual_shipping_cost")),
                    "soldAt": (sale or {}).get("sold_at") or "",
                    "notes": (sale or {}).get("notes") or "",
                    "actualProfit": self.actual_profit(item, sale),
                },
            }
        )
        return payload

    def api_audit(self):
        self.respond_json({"capabilities": audit_capabilities()})

    def api_ebay_status(self):
        self.respond_json({"ebay": ebay_readiness(CONFIG["ebay"])})

    def api_items(self):
        with connect(CONFIG["database_path"]) as conn:
            db_items = rows(conn, "SELECT * FROM items ORDER BY updated_at DESC, id DESC")
            items = [self.item_payload(conn, item, full=False) for item in db_items]
        counts = {
            "inbox": len(items),
            "ready": sum(1 for item in items if item["status"] == "ready"),
            "draft": sum(1 for item in items if item["status"] == "draft"),
            "photos": sum(1 for item in items if item["status"] == "photos"),
            "review": sum(1 for item in items if item["status"] == "review"),
            "pass": sum(1 for item in items if item["status"] == "pass"),
            "listed": sum(1 for item in items if item["status"] == "listed"),
            "potNet": round(sum(dollars(item.get("net")) for item in items if item.get("net") and item["status"] != "pass"), 2),
        }
        self.respond_json({"items": items, "counts": counts, "dropZone": str(CONFIG["drop_zone"])})

    def api_scan(self):
        with connect(CONFIG["database_path"]) as conn:
            result = scan_drop_zone(conn, CONFIG["drop_zone"])
            db_items = rows(conn, "SELECT * FROM items ORDER BY updated_at DESC, id DESC")
            items = [self.item_payload(conn, item, full=False) for item in db_items]
        counts = {
            "inbox": len(items),
            "ready": sum(1 for item in items if item["status"] == "ready"),
            "draft": sum(1 for item in items if item["status"] == "draft"),
            "photos": sum(1 for item in items if item["status"] == "photos"),
            "review": sum(1 for item in items if item["status"] == "review"),
            "pass": sum(1 for item in items if item["status"] == "pass"),
            "listed": sum(1 for item in items if item["status"] == "listed"),
            "potNet": round(sum(dollars(item.get("net")) for item in items if item.get("net") and item["status"] != "pass"), 2),
        }
        self.respond_json({"scan": result, "items": items, "counts": counts, "dropZone": str(CONFIG["drop_zone"])})

    def api_bulk_status(self, raw: str):
        data = self.read_json(raw)
        ids = [int(value) for value in data.get("ids", []) if str(value).isdigit()]
        status = data.get("status") or "listed"
        updated = 0
        with connect(CONFIG["database_path"]) as conn:
            for item_id in ids:
                cursor = conn.execute(
                    "UPDATE items SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, item_id),
                )
                updated += cursor.rowcount
            conn.commit()
            db_items = rows(conn, "SELECT * FROM items ORDER BY updated_at DESC, id DESC")
            items = [self.item_payload(conn, item, full=False) for item in db_items]
        self.respond_json({"updated": updated, "items": items})

    def api_item(self, path: str):
        parts = path.strip("/").split("/")
        if len(parts) != 3 or not parts[2].isdigit():
            self.respond_json({"error": "Not found"}, 404)
            return
        item_id = int(parts[2])
        with connect(CONFIG["database_path"]) as conn:
            item = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
            if not item:
                self.respond_json({"error": "Item not found"}, 404)
                return
            self.respond_json({"item": self.item_payload(conn, item, full=True)})

    def api_item_post(self, path: str, raw: str):
        parts = path.strip("/").split("/")
        if len(parts) != 4 or not parts[2].isdigit():
            self.respond_json({"error": "Not found"}, 404)
            return
        item_id = int(parts[2])
        action = parts[3]
        data = self.read_json(raw)
        with connect(CONFIG["database_path"]) as conn:
            item = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
            if not item:
                self.respond_json({"error": "Item not found"}, 404)
                return
            if action == "status":
                status = data.get("status") or "pending"
                conn.execute("UPDATE items SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, item_id))
            elif action == "research":
                result = research_item(item, CONFIG["settings"])
                competition = []
                try:
                    browse = browse_active_listings(item, CONFIG["ebay"])
                    competition = browse["listings"]
                    result["active_count"] = browse["activeCount"] or result.get("active_count")
                    result["sampled_active_count"] = len(competition)
                    result["active_url"] = browse["searchUrl"]
                    result["query"] = browse["query"] or result.get("query")
                    result["notes"] = "\n".join(
                        [
                            result.get("notes") or "",
                            f"eBay Browse API returned {len(competition)} active listing rows for competition review.",
                        ]
                    ).strip()
                except EbayConfigError as exc:
                    result["notes"] = "\n".join([result.get("notes") or "", f"Browse API not configured: {exc}"]).strip()
                except EbayApiError as exc:
                    result["notes"] = "\n".join([result.get("notes") or "", f"Browse API failed: {exc}"]).strip()
                snapshot_id = self.save_market_snapshot(conn, item_id, result)
                if competition:
                    self.replace_api_competition(conn, item_id, snapshot_id, competition)
            elif action == "cover":
                photo_id = integer(data.get("photo_id"))
                conn.execute("UPDATE photos SET role = NULL WHERE item_id = ?", (item_id,))
                if photo_id:
                    conn.execute(
                        "UPDATE photos SET role = 'cover' WHERE id = ? AND item_id = ?",
                        (photo_id, item_id),
                    )
                conn.execute("UPDATE items SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
            elif action == "price":
                latest = latest_row(conn, "market_snapshots", item_id) or {}
                values = {
                    "avg_sold_price": dollars(data.get("avg_sold_price", latest.get("avg_sold_price"))),
                    "median_sold_price": dollars(data.get("median_sold_price", latest.get("median_sold_price"))),
                    "sold_price_low": dollars(data.get("sold_price_low", latest.get("sold_price_low"))),
                    "sold_price_high": dollars(data.get("sold_price_high", latest.get("sold_price_high"))),
                    "expected_sale_price": dollars(data.get("expected_sale_price", latest.get("expected_sale_price"))),
                    "active_count": integer(data.get("active_count", latest.get("active_count"))),
                    "sold_count_30d": integer(data.get("sold_count_30d", latest.get("sold_count_30d"))),
                    "shipping_cost": dollars(data.get("shipping_cost", latest.get("shipping_cost"))),
                    "confidence": data.get("confidence", latest.get("confidence") or "manual"),
                    "notes": data.get("notes", latest.get("notes") or "Edited in scrollytelling UI."),
                }
                self.save_market_snapshot(conn, item_id, values)
            elif action == "draft":
                title = str(data.get("title") or "")
                description = str(data.get("description") or "")
                category = str(data.get("category") or item.get("category") or "general")
                shipping = str(data.get("shipping_service") or CONFIG["settings"]["shipping"]["default_model"])
                format_kind = str(data.get("format_kind") or "fixed")
                start_price = dollars(data.get("start_price"))
                conn.execute(
                    """
                    INSERT INTO listing_drafts (
                      item_id, title, description, category, shipping_service,
                      format_kind, start_price, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', CURRENT_TIMESTAMP)
                    ON CONFLICT(item_id) DO UPDATE SET
                      title = excluded.title,
                      description = excluded.description,
                      category = excluded.category,
                      shipping_service = excluded.shipping_service,
                      format_kind = excluded.format_kind,
                      start_price = excluded.start_price,
                      status = 'draft',
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (item_id, title, description, category, shipping, format_kind, start_price),
                )
                conn.execute("UPDATE items SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
            elif action == "competition":
                listings = data.get("listings") or []
                if isinstance(listings, dict):
                    listings = [listings]
                inserted = 0
                for listing in listings:
                    if not (listing.get("title") or listing.get("price")):
                        continue
                    conn.execute(
                        """
                        INSERT INTO market_competition (
                          item_id, title, condition, price, watchers, url, source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            str(listing.get("title") or ""),
                            str(listing.get("condition") or ""),
                            dollars(listing.get("price")),
                            integer(listing.get("watchers")),
                            str(listing.get("url") or ""),
                            str(listing.get("source") or "manual"),
                        ),
                    )
                    inserted += 1
                if inserted:
                    conn.execute("UPDATE items SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
            elif action == "publish":
                photos = photo_rows(conn, item_id)
                draft = self.effective_draft(conn, item, data)
                if data.get("confirm_live") is True:
                    try:
                        result = publish_live(item, draft, photos, CONFIG["ebay"])
                    except (EbayConfigError, EbayApiError) as exc:
                        self.respond_json({"error": str(exc), "publish": build_publish_plan(item, draft, photos, CONFIG["ebay"])}, 400)
                        return
                    conn.execute("UPDATE items SET status = 'listed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
                    conn.commit()
                    updated = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
                    self.respond_json({"item": self.item_payload(conn, updated, full=True), "publish": result})
                    return
                self.respond_json({"item": self.item_payload(conn, item, full=True), "publish": build_publish_plan(item, draft, photos, CONFIG["ebay"])})
                return
            elif action == "upload-photos":
                result = self.upload_item_photos(conn, item_id)
                conn.commit()
                updated = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
                photos = photo_rows(conn, item_id)
                draft = self.effective_draft(conn, updated, data)
                self.respond_json(
                    {
                        "item": self.item_payload(conn, updated, full=True),
                        "upload": result,
                        "publish": build_publish_plan(updated, draft, photos, CONFIG["ebay"]),
                    }
                )
                return
            else:
                self.respond_json({"error": "Unsupported action"}, 400)
                return
            conn.commit()
            updated = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
            self.respond_json({"item": self.item_payload(conn, updated, full=True)})

    def home(self):
        with connect(CONFIG["database_path"]) as conn:
            items = rows(conn, "SELECT * FROM items ORDER BY updated_at DESC, id DESC")
        content = f"""
        <section class="hero">
          <div>
            <p class="eyebrow">Weekend MVP</p>
            <h1>eBay Engine</h1>
            <p>Scan your drop zone, review resale math, and turn inventory into listing packages.</p>
          </div>
          <a class="button" href="/scan">Scan Drop Zone</a>
        </section>
        <section class="panel">
          <div class="section-head">
            <h2>Inventory Queue</h2>
            <p>Drop zone: {escape(CONFIG['drop_zone'])}</p>
          </div>
          <div class="grid">{''.join(item_card(item) for item in items) or '<p>No items imported yet.</p>'}</div>
        </section>
        """
        self.respond(layout(content))

    def scan(self):
        with connect(CONFIG["database_path"]) as conn:
            result = scan_drop_zone(conn, CONFIG["drop_zone"])
        detail_rows = "".join(
            f"<li><strong>{escape(detail['folder'])}</strong>: {escape(detail['status'])} - {escape(detail['reason'])}</li>"
            for detail in result.get("details", [])
        )
        content = f"""
        <section class="panel narrow">
          <h1>Scan Complete</h1>
          <p>Imported {result['imported']} new item(s). Skipped {result['skipped']} existing or incomplete folder(s).</p>
          <ul class="scan-details">{detail_rows}</ul>
          <a class="button" href="/">Back to Dashboard</a>
        </section>
        """
        self.respond(layout(content, "Scan Complete"))

    def item(self, item_id: int):
        with connect(CONFIG["database_path"]) as conn:
            item = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
            if not item:
                self.send_error(404)
                return
            photos = photo_rows(conn, item_id)
            market = row(
                conn,
                "SELECT * FROM market_snapshots WHERE item_id = ? ORDER BY id DESC LIMIT 1",
                (item_id,),
            )
            sale = row(conn, "SELECT * FROM sales WHERE item_id = ? ORDER BY id DESC LIMIT 1", (item_id,))
            rec = latest_recommendation(item, market, CONFIG["settings"])
        existing_photos = [photo for photo in photos if Path(photo["path"]).exists()]
        cover = next((photo for photo in photos if photo.get("role") == "cover"), None)
        cover_id = int(cover["id"]) if cover else (int(photos[0]["id"]) if photos else None)
        needs = ""
        category = (item.get("category") or "general").lower()
        by_category = CONFIG["settings"]["photos"].get("min_count_by_category", {})
        min_count = int(by_category.get(category, CONFIG["settings"]["photos"]["min_count"]))
        if len(existing_photos) < min_count:
            needs = f"<p class='warning'>Needs more photos: {len(existing_photos)}/{min_count} available.</p>"
        content = render_template(
            "item.html",
            {
                "id": item["id"],
                "folder_name": escape(item["folder_name"]),
                "status": escape(item["status"]),
                "status_options": status_options(item["status"]),
                "brand": escape(item.get("brand")),
                "model": escape(item.get("model")),
                "style_code": escape(item.get("style_code")),
                "upc": escape(item.get("upc")),
                "category": escape(item.get("category")),
                "item_type": escape(item.get("item_type")),
                "color": escape(item.get("color")),
                "condition": escape(item.get("condition")),
                "size": escape(item.get("size")),
                "box": escape(item.get("box")),
                "accessories": escape(item.get("accessories")),
                "tested": escape(item.get("tested")),
                "defects": escape(item.get("defects")),
                "cogs": f"{float(item.get('cogs') or 0):.2f}",
                "notes": escape(item.get("notes")),
                "photo_count": f"{len(existing_photos)} available / {len(photos)} records",
                "photo_cards": photo_cards(photos, cover_id),
                "required_angle_list": required_angle_list(category, CONFIG["settings"]),
                "photo_warning": needs,
                "avg_sold_price": escape((market or {}).get("avg_sold_price") or ""),
                "median_sold_price": escape((market or {}).get("median_sold_price") or ""),
                "sold_price_low": escape((market or {}).get("sold_price_low") or ""),
                "sold_price_high": escape((market or {}).get("sold_price_high") or ""),
                "expected_sale_price": escape((market or {}).get("expected_sale_price") or ""),
                "active_count": escape((market or {}).get("active_count") or ""),
                "sold_count_30d": escape((market or {}).get("sold_count_30d") or ""),
                "shipping_cost": escape((market or {}).get("shipping_cost") or ""),
                "market_confidence": escape((market or {}).get("confidence") or rec["market_confidence"]),
                "confidence_score": escape((market or {}).get("confidence_score") or 0),
                "sampled_sold_count": escape((market or {}).get("sampled_sold_count") or 0),
                "filtered_sold_count": escape((market or {}).get("filtered_sold_count") or 0),
                "sampled_active_count": escape((market or {}).get("sampled_active_count") or 0),
                "active_vs_sold_pressure": escape(
                    f"{int((market or {}).get('active_count') or 0)} active / {int((market or {}).get('sold_count_30d') or 0)} sold"
                ),
                "active_review_link": link_or_dash((market or {}).get("active_url"), "Review active listings"),
                "sold_review_link": link_or_dash((market or {}).get("sold_url"), "Review sold listings"),
                "market_notes": escape((market or {}).get("notes") or ""),
                "decision": escape(rec["decision"]),
                "rationale": escape(rec["rationale"]),
                "suggested_price": f"${rec['suggested_price']:,.2f}",
                "estimated_profit": f"${rec['estimated_profit']:,.2f}",
                "roi": f"{rec['roi'] * 100:.1f}%",
                "sell_through": f"{rec['sell_through_rate'] * 100:.1f}%",
                "fees": f"${rec['ebay_fee'] + rec['order_fee']:,.2f}",
                "risk_reserve": f"${rec['risk_reserve']:,.2f}",
                "packaging_reserve": f"${rec['packaging_reserve']:,.2f}",
                "shipping_defaults": escape(
                    f"{CONFIG['settings']['shipping']['default_model']}, ships in {CONFIG['settings']['shipping']['default_handling_days']} business days"
                ),
                "returns_defaults": escape(CONFIG["settings"]["returns"]["default_policy"]),
                "warning_list": warning_list(item, existing_photos, rec, CONFIG["settings"]),
                "draft_title": escape(rec["title"]),
                "plain_description": escape(rec["plain_description"]),
                "draft_description": escape(rec["description"]),
                "sale_price": escape((sale or {}).get("sale_price") or ""),
                "actual_ebay_fees": escape((sale or {}).get("actual_ebay_fees") or ""),
                "actual_shipping_cost": escape((sale or {}).get("actual_shipping_cost") or ""),
                "sold_at": escape((sale or {}).get("sold_at") or ""),
                "sale_notes": escape((sale or {}).get("notes") or ""),
                "actual_profit": self.actual_profit(item, sale),
            },
        )
        self.respond(layout(content, item["folder_name"]))

    def persist_recommendation(self, conn, item_id: int):
        item = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
        market = row(
            conn,
            "SELECT * FROM market_snapshots WHERE item_id = ? ORDER BY id DESC LIMIT 1",
            (item_id,),
        )
        if not item or not market:
            return
        rec = latest_recommendation(item, market, CONFIG["settings"])
        conn.execute(
            """
            INSERT INTO recommendations (
              item_id, listing_format, pricing_mode, suggested_price,
              ebay_fee, order_fee, packaging_reserve, risk_reserve,
              estimated_profit, roi, sell_through_rate, decision,
              rationale, title, description
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                item_id,
                rec["listing_format"],
                rec["pricing_mode"],
                rec["suggested_price"],
                rec["ebay_fee"],
                rec["order_fee"],
                rec["packaging_reserve"],
                rec["risk_reserve"],
                rec["estimated_profit"],
                rec["roi"],
                rec["sell_through_rate"],
                rec["decision"],
                rec["rationale"],
                rec["title"],
                rec["description"],
            ),
        )

    def effective_draft(self, conn, item: dict, overrides: dict | None = None) -> dict:
        draft = row(conn, "SELECT * FROM listing_drafts WHERE item_id = ?", (item["id"],)) or {}
        rec = latest_recommendation(item, latest_row(conn, "market_snapshots", item["id"]), CONFIG["settings"])
        result = {
            "title": draft.get("title") or rec.get("title") or "",
            "description": draft.get("description") or rec.get("description") or "",
            "category": draft.get("category") or item.get("category") or "general",
            "shipping_service": draft.get("shipping_service") or CONFIG["settings"]["shipping"]["default_model"],
            "format_kind": draft.get("format_kind") or "fixed",
            "start_price": dollars(draft.get("start_price")) or dollars(rec.get("suggested_price")),
        }
        overrides = overrides or {}
        for key in ["title", "description", "category", "shipping_service", "format_kind", "start_price"]:
            if key in overrides and overrides[key] not in {None, ""}:
                result[key] = overrides[key]
        return result

    def replace_api_competition(self, conn, item_id: int, snapshot_id: int | None, listings: list[dict]):
        conn.execute("DELETE FROM market_competition WHERE item_id = ? AND source = 'ebay_browse'", (item_id,))
        for listing in listings[:20]:
            conn.execute(
                """
                INSERT INTO market_competition (
                  item_id, snapshot_id, title, condition, price, watchers, url, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    snapshot_id,
                    str(listing.get("title") or ""),
                    str(listing.get("condition") or ""),
                    dollars(listing.get("price")),
                    integer(listing.get("watchers")),
                    str(listing.get("url") or ""),
                    str(listing.get("source") or "ebay_browse"),
                ),
            )

    def save_market_snapshot(self, conn, item_id: int, values: dict) -> int:
        cursor = conn.execute(
            """
            INSERT INTO market_snapshots (
              item_id, avg_sold_price, median_sold_price, sold_price_low,
              sold_price_high, expected_sale_price, active_count,
              sold_count_30d, shipping_cost, query, sampled_sold_count,
              filtered_sold_count, sampled_active_count, confidence,
              confidence_score, active_url, sold_url, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                float(values.get("avg_sold_price") or 0),
                float(values.get("median_sold_price") or 0),
                float(values.get("sold_price_low") or 0),
                float(values.get("sold_price_high") or 0),
                float(values.get("expected_sale_price") or 0),
                int(values.get("active_count") or 0),
                int(values.get("sold_count_30d") or 0),
                float(values.get("shipping_cost") or 0),
                values.get("query") or "",
                int(values.get("sampled_sold_count") or 0),
                int(values.get("filtered_sold_count") or 0),
                int(values.get("sampled_active_count") or 0),
                values.get("confidence") or "manual",
                int(values.get("confidence_score") or 0),
                values.get("active_url") or "",
                values.get("sold_url") or "",
                values.get("notes") or "",
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        self.persist_recommendation(conn, item_id)
        conn.execute("UPDATE items SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
        return snapshot_id

    def upload_item_photos(self, conn, item_id: int) -> dict:
        env = CONFIG["ebay"].get("env") or "sandbox"
        photos = photo_rows(conn, item_id)
        result = {"provider": "ebay_media", "env": env, "uploaded": 0, "skipped": 0, "failed": 0, "photos": []}
        for photo in photos[:24]:
            existing_url = str(photo.get("ebay_public_url") or "")
            if existing_url.startswith("https://"):
                result["skipped"] += 1
                result["photos"].append({"id": photo["id"], "filename": photo.get("filename"), "status": "skipped", "url": existing_url})
                continue
            if not Path(photo["path"]).exists():
                error = "Source photo file is missing from the drop zone path."
                result["failed"] += 1
                self.save_photo_publication_error(conn, photo, env, error)
                result["photos"].append({"id": photo["id"], "filename": photo.get("filename"), "status": "failed", "error": error})
                continue
            try:
                upload = upload_media_image_from_file(photo, CONFIG["ebay"])
            except (EbayConfigError, EbayApiError) as exc:
                error = str(exc)
                result["failed"] += 1
                self.save_photo_publication_error(conn, photo, env, error)
                result["photos"].append({"id": photo["id"], "filename": photo.get("filename"), "status": "failed", "error": error})
                continue
            public_url = upload["publicUrl"]
            conn.execute(
                """
                INSERT INTO photo_publications (
                  photo_id, provider, ebay_env, public_url, use_by_date, uploaded_at, error
                ) VALUES (?, 'ebay_media', ?, ?, ?, CURRENT_TIMESTAMP, NULL)
                ON CONFLICT(photo_id, provider, ebay_env) DO UPDATE SET
                  public_url = excluded.public_url,
                  use_by_date = excluded.use_by_date,
                  uploaded_at = CURRENT_TIMESTAMP,
                  error = NULL
                """,
                (photo["id"], env, public_url, upload.get("useByDate") or ""),
            )
            result["uploaded"] += 1
            result["photos"].append(
                {
                    "id": photo["id"],
                    "filename": photo.get("filename"),
                    "status": "uploaded",
                    "url": public_url,
                    "useByDate": upload.get("useByDate") or "",
                }
            )
        if result["uploaded"]:
            conn.execute("UPDATE items SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
        return result

    def save_photo_publication_error(self, conn, photo: dict, env: str, error: str) -> None:
        conn.execute(
            """
            INSERT INTO photo_publications (
              photo_id, provider, ebay_env, public_url, use_by_date, uploaded_at, error
            ) VALUES (?, 'ebay_media', ?, '', NULL, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(photo_id, provider, ebay_env) DO UPDATE SET
              error = excluded.error,
              uploaded_at = CURRENT_TIMESTAMP
            """,
            (photo["id"], env, error[:1000]),
        )

    def research(self, item_id: int):
        with connect(CONFIG["database_path"]) as conn:
            item = row(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
            if not item:
                self.send_error(404)
                return
            result = research_item(item, CONFIG["settings"])
            self.save_market_snapshot(conn, item_id, result)
            conn.commit()
        self.redirect(f"/item?id={item_id}")

    def save_market(self, data: dict):
        item_id = int(data.get("id", ["0"])[0])
        def num(name: str) -> float:
            raw = data.get(name, ["0"])[0].strip()
            return float(raw) if raw else 0.0
        def integer(name: str) -> int:
            raw = data.get(name, ["0"])[0].strip()
            return int(raw) if raw else 0
        with connect(CONFIG["database_path"]) as conn:
            self.save_market_snapshot(
                conn,
                item_id,
                {
                    "avg_sold_price": num("avg_sold_price"),
                    "median_sold_price": num("median_sold_price"),
                    "sold_price_low": num("sold_price_low"),
                    "sold_price_high": num("sold_price_high"),
                    "expected_sale_price": num("expected_sale_price"),
                    "active_count": integer("active_count"),
                    "sold_count_30d": integer("sold_count_30d"),
                    "shipping_cost": num("shipping_cost"),
                    "confidence": data.get("confidence", ["manual"])[0],
                    "notes": data.get("notes", [""])[0],
                },
            )
            conn.commit()
        self.redirect(f"/item?id={item_id}")

    def save_item(self, data: dict):
        item_id = int(first(data, "id", "0") or 0)
        with connect(CONFIG["database_path"]) as conn:
            conn.execute(
                """
                UPDATE items
                SET brand = ?, model = ?, style_code = ?, upc = ?,
                    category = ?, item_type = ?, size = ?,
                    color = ?, condition = ?, box = ?, accessories = ?, tested = ?,
                    defects = ?, cogs = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    first(data, "brand"),
                    first(data, "model"),
                    first(data, "style_code"),
                    first(data, "upc"),
                    first(data, "category") or "general",
                    first(data, "item_type"),
                    first(data, "size"),
                    first(data, "color"),
                    first(data, "condition"),
                    first(data, "box"),
                    first(data, "accessories"),
                    first(data, "tested"),
                    first(data, "defects"),
                    float(first(data, "cogs", "0") or 0),
                    first(data, "notes"),
                    item_id,
                ),
            )
            self.persist_recommendation(conn, item_id)
            conn.commit()
        self.redirect(f"/item?id={item_id}")

    def save_photos(self, data: dict):
        item_id = int(first(data, "id", "0") or 0)
        cover_photo_id = int(first(data, "cover_photo_id", "0") or 0)
        with connect(CONFIG["database_path"]) as conn:
            conn.execute("UPDATE photos SET role = NULL WHERE item_id = ?", (item_id,))
            if cover_photo_id:
                conn.execute(
                    "UPDATE photos SET role = 'cover' WHERE id = ? AND item_id = ?",
                    (cover_photo_id, item_id),
                )
            conn.execute("UPDATE items SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
            conn.commit()
        self.redirect(f"/item?id={item_id}")

    def save_sale(self, data: dict):
        item_id = int(first(data, "id", "0") or 0)
        with connect(CONFIG["database_path"]) as conn:
            conn.execute(
                """
                INSERT INTO sales (
                  item_id, sale_price, actual_ebay_fees, actual_shipping_cost,
                  sold_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    money_input(data, "sale_price"),
                    money_input(data, "actual_ebay_fees"),
                    money_input(data, "actual_shipping_cost"),
                    first(data, "sold_at"),
                    first(data, "sale_notes"),
                ),
            )
            conn.execute(
                "UPDATE items SET status = 'sold', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,),
            )
            conn.commit()
        self.redirect(f"/item?id={item_id}")

    def actual_profit(self, item: dict, sale: dict | None) -> str:
        if not sale:
            return "Not sold yet"
        profit = (
            float(sale.get("sale_price") or 0)
            - float(item.get("cogs") or 0)
            - float(sale.get("actual_ebay_fees") or 0)
            - float(sale.get("actual_shipping_cost") or 0)
        )
        return f"${profit:,.2f}"

    def photo(self, photo_id: int):
        with connect(CONFIG["database_path"]) as conn:
            photo = row(conn, "SELECT * FROM photos WHERE id = ?", (photo_id,))
        if not photo:
            self.send_error(404)
            return
        path = Path(photo["path"])
        if not path.exists() or not path.is_file():
            label = escape(photo.get("filename") or "Missing photo")
            body = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="640" viewBox="0 0 640 640">
<rect width="640" height="640" fill="#f5f5f7"/>
<rect x="40" y="40" width="560" height="560" rx="20" fill="#ffffff" stroke="#d7d7dc" stroke-width="4"/>
<text x="320" y="300" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, sans-serif" font-size="28" fill="#6e6e73">Missing photo file</text>
<text x="320" y="342" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, sans-serif" font-size="20" fill="#6e6e73">{label}</text>
</svg>"""
            self.respond(body.encode(), content_type="image/svg+xml")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.respond(path.read_bytes(), content_type=content_type)

    def save_status(self, data: dict):
        item_id = int(data.get("id", ["0"])[0])
        status = data.get("status", ["pending"])[0]
        with connect(CONFIG["database_path"]) as conn:
            conn.execute(
                "UPDATE items SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, item_id),
            )
            conn.commit()
        self.redirect(f"/item?id={item_id}")


def run():
    CONFIG["database_path"].parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((CONFIG["host"], CONFIG["port"]), Handler)
    print(f"eBay Engine running at http://{CONFIG['host']}:{CONFIG['port']}")
    print(f"Drop zone: {CONFIG['drop_zone']}")
    server.serve_forever()
