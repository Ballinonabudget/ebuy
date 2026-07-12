from __future__ import annotations

import base64
import gzip
import json
import mimetypes
import re
import time
import uuid
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .market import build_query


APP_SCOPE = "https://api.ebay.com/oauth/api_scope"
SELL_SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
]
SELL_SCOPE = " ".join(SELL_SCOPES)
_TOKEN_CACHE: dict[str, dict] = {}

CATEGORY_HINTS = {
    "tech": "29946",
    "electronics": "29946",
    "sneakers": "15709",
    "shoes": "15709",
    "apparel": "15687",
    "clothing": "15687",
    "bags": "169291",
    "accessories": "4250",
    "games": "139973",
    "toys": "220",
}


class EbayConfigError(RuntimeError):
    pass


class EbayApiError(RuntimeError):
    pass


def api_root(config: dict) -> str:
    return "https://api.sandbox.ebay.com" if config.get("env") == "sandbox" else "https://api.ebay.com"


def auth_root(config: dict) -> str:
    return "https://auth.sandbox.ebay.com" if config.get("env") == "sandbox" else "https://auth.ebay.com"


def media_root(config: dict) -> str:
    return "https://apim.sandbox.ebay.com" if config.get("env") == "sandbox" else "https://apim.ebay.com"


def token_url(config: dict) -> str:
    return f"{api_root(config)}/identity/v1/oauth2/token"


def _basic_auth(config: dict) -> str:
    client_id = config.get("client_id") or ""
    client_secret = config.get("client_secret") or ""
    if not client_id or not client_secret:
        raise EbayConfigError("Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET.")
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _request_json(request: Request, timeout: int = 20) -> dict:
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise EbayApiError(f"eBay API HTTP {exc.code}: {detail[:500]}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EbayApiError(f"eBay API request failed: {exc}") from exc
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise EbayApiError(f"eBay API returned non-JSON response: {body[:200]}") from exc


def _mint_token(config: dict, grant_type: str, scope: str, refresh_token: str = "") -> str:
    payload = {"grant_type": grant_type, "scope": scope}
    if refresh_token:
        payload["refresh_token"] = refresh_token
    request = Request(
        token_url(config),
        data=urlencode(payload).encode(),
        headers={
            "Authorization": _basic_auth(config),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    data = _request_json(request)
    access_token = data.get("access_token")
    if not access_token:
        raise EbayApiError("eBay token response did not include access_token.")
    expires_in = int(data.get("expires_in") or 7200)
    cache_key = f"{config.get('env')}:{grant_type}:{scope}"
    _TOKEN_CACHE[cache_key] = {"token": access_token, "expires_at": time.time() + expires_in - 120}
    return access_token


def application_token(config: dict) -> str:
    cache_key = f"{config.get('env')}:client_credentials:{APP_SCOPE}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached["expires_at"] > time.time():
        return cached["token"]
    return _mint_token(config, "client_credentials", APP_SCOPE)


def user_token(config: dict) -> str:
    if config.get("user_access_token"):
        return config["user_access_token"]
    refresh_token = config.get("refresh_token") or ""
    if not refresh_token:
        raise EbayConfigError("Missing EBAY_USER_ACCESS_TOKEN or EBAY_REFRESH_TOKEN.")
    cache_key = f"{config.get('env')}:refresh_token:{SELL_SCOPE}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached["expires_at"] > time.time():
        return cached["token"]
    return _mint_token(config, "refresh_token", SELL_SCOPE, refresh_token=refresh_token)


def readiness(config: dict) -> dict:
    has_app_credentials = bool(config.get("client_id") and config.get("client_secret"))
    has_user_token = bool(config.get("user_access_token") or config.get("refresh_token"))
    policy_fields = {
        "paymentPolicyId": bool(config.get("payment_policy_id")),
        "returnPolicyId": bool(config.get("return_policy_id")),
        "fulfillmentPolicyId": bool(config.get("fulfillment_policy_id")),
        "merchantLocationKey": bool(config.get("merchant_location_key")),
    }
    missing_publish = [name for name, present in policy_fields.items() if not present]
    if not has_user_token:
        missing_publish.append("userOAuthToken")
    if not config.get("default_category_id"):
        missing_publish.append("categoryId")
    env = config.get("env", "production")
    profiles = config.get("profiles", {})
    production = profiles.get("production", {})
    allow_production_publish = bool(config.get("allow_production_publish"))
    production_ready = bool(production.get("ready"))
    return {
        "env": env,
        "marketplaceId": config.get("marketplace_id", "EBAY_US"),
        "browseReady": has_app_credentials,
        "listingReady": has_app_credentials and has_user_token and not missing_publish,
        "hasAppCredentials": has_app_credentials,
        "hasUserToken": has_user_token,
        "policies": policy_fields,
        "missingPublishFields": missing_publish,
        "tokenEndpoint": token_url(config),
        "browseEndpoint": f"{api_root(config)}/buy/browse/v1/item_summary/search",
        "inventoryEndpoint": f"{api_root(config)}/sell/inventory/v1",
        "mediaEndpoint": f"{media_root(config)}/commerce/media/v1_beta/image/create_image_from_file",
        "consentUrl": consent_url(config),
        "profiles": profiles,
        "productionReady": production_ready,
        "productionPublishLocked": not allow_production_publish,
        "allowProductionPublish": allow_production_publish,
        "productionDryRunReady": production_ready and env == "production" and not allow_production_publish,
        "productionLaunchReady": production_ready and allow_production_publish,
        "productionSafety": [
            {
                "label": "Production profile complete",
                "pass": production_ready,
                "detail": "Production credentials, seller authorization, policy IDs, merchant location, and category ID must be present.",
            },
            {
                "label": "Live publish lock",
                "pass": not allow_production_publish,
                "detail": "Keep EBAY_ALLOW_PRODUCTION_PUBLISH=false while running production dry runs.",
            },
            {
                "label": "Active mode",
                "pass": env == "production",
                "detail": "Switch to Production mode only when validating production credentials and payloads.",
            },
        ],
    }


def consent_url(config: dict) -> str:
    redirect_uri = config.get("redirect_uri") or ""
    client_id = config.get("client_id") or ""
    if not redirect_uri or not client_id:
        return ""
    return (
        f"{auth_root(config)}/oauth2/authorize?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": SELL_SCOPE,
            }
        )
    )


def browse_active_listings(item: dict, config: dict, limit: int = 20) -> dict:
    if not readiness(config)["browseReady"]:
        raise EbayConfigError("Browse API needs EBAY_CLIENT_ID and EBAY_CLIENT_SECRET.")
    query = build_query(item)
    data = browse_search(query, config, limit=limit)
    return {
        "query": query,
        "searchUrl": data["searchUrl"],
        "activeCount": data["activeCount"],
        "listings": data["listings"],
    }


def browse_search(query: str, config: dict, limit: int = 20, filter_value: str = "") -> dict:
    if not readiness(config)["browseReady"]:
        raise EbayConfigError("Browse API needs eBay app credentials.")
    params = {"q": query, "limit": max(1, min(limit, 50)), "fieldgroups": "EXTENDED"}
    if filter_value:
        params["filter"] = filter_value
    encoded = urlencode(params)
    url = f"{api_root(config)}/buy/browse/v1/item_summary/search?{encoded}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {application_token(config)}",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": config.get("marketplace_id") or "EBAY_US",
        },
        method="GET",
    )
    data = _request_json(request)
    listings = []
    for summary in data.get("itemSummaries") or []:
        price = summary.get("price") or summary.get("currentBidPrice") or {}
        image = summary.get("image") or {}
        seller = summary.get("seller") or {}
        listings.append(
            {
                "title": summary.get("title") or "",
                "condition": summary.get("condition") or "",
                "price": _float(price.get("value")),
                "currency": price.get("currency") or "USD",
                "shipping": _float(((summary.get("shippingOptions") or [{}])[0].get("shippingCost") or {}).get("value")),
                "watchers": int(summary.get("watchCount") or summary.get("bidCount") or 0),
                "url": summary.get("itemWebUrl") or "",
                "imageUrl": image.get("imageUrl") or "",
                "seller": seller.get("username") or "",
                "itemId": summary.get("itemId") or "",
                "source": "ebay_browse",
            }
        )
    return {
        "query": query,
        "searchUrl": url,
        "activeCount": int(data.get("total") or len(listings)),
        "listings": listings,
    }


def build_publish_plan(item: dict, draft: dict, photos: list[dict], config: dict) -> dict:
    sku = sku_for(item)
    title = (draft.get("title") or item.get("title") or item.get("model") or item.get("folder_name") or "")[:80]
    description = draft.get("description") or ""
    price = _float(draft.get("start_price"))
    category_id = _category_id(item, draft, config)
    image_urls = public_image_urls(photos, config)
    condition = condition_enum(item.get("condition") or "")
    marketplace_id = config.get("marketplace_id") or "EBAY_US"
    inventory_payload = {
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "condition": condition,
        "conditionDescription": (item.get("condition") or "See photos")[:1000],
        "packageWeightAndSize": package_weight_and_size(item),
        "product": {
            "title": title,
            "description": text_from_html(description),
            "aspects": product_aspects(item),
            "imageUrls": image_urls,
        },
    }
    if item.get("upc"):
        inventory_payload["product"]["upc"] = [str(item["upc"])]
    offer_payload = {
        "sku": sku,
        "marketplaceId": marketplace_id,
        "format": "FIXED_PRICE",
        "availableQuantity": 1,
        "categoryId": category_id,
        "merchantLocationKey": config.get("merchant_location_key") or "",
        "listingDescription": description,
        "listingPolicies": {
            "fulfillmentPolicyId": config.get("fulfillment_policy_id") or "",
            "paymentPolicyId": config.get("payment_policy_id") or "",
            "returnPolicyId": config.get("return_policy_id") or "",
        },
        "pricingSummary": {"price": {"currency": "USD", "value": f"{price:.2f}"}},
    }
    validation = validate_listing(item, draft, photos, config, inventory_payload, offer_payload)
    missing = []
    if not readiness(config)["hasUserToken"]:
        missing.append("seller OAuth token or refresh token")
    if not title:
        missing.append("listing title")
    if not description:
        missing.append("HTML description")
    if price <= 0:
        missing.append("start price")
    if not category_id:
        missing.append("numeric eBay category ID")
    if not image_urls:
        missing.append("public HTTPS image URL")
    if not config.get("merchant_location_key"):
        missing.append("merchant location key")
    for label, value in offer_payload["listingPolicies"].items():
        if not value:
            missing.append(label)
    missing.extend(check["field"] for check in validation if check["level"] == "blocker" and check["field"] not in missing)
    return {
        "mode": "dry_run",
        "environment": config.get("env", "production"),
        "allowProductionPublish": bool(config.get("allow_production_publish")),
        "productionPublishLocked": config.get("env") == "production" and not bool(config.get("allow_production_publish")),
        "sku": sku,
        "canPublish": not missing,
        "missing": missing,
        "validation": validation,
        "endpoints": {
            "inventoryItem": f"PUT {api_root(config)}/sell/inventory/v1/inventory_item/{quote(sku)}",
            "createOffer": f"POST {api_root(config)}/sell/inventory/v1/offer",
            "publishOffer": f"POST {api_root(config)}/sell/inventory/v1/offer/{{offerId}}/publish",
        },
        "inventoryItemPayload": inventory_payload,
        "offerPayload": offer_payload,
        "notes": [
            "Dry run only. No live eBay listing is created from this preview.",
            "eBay requires public HTTPS image URLs; local /photo?id=... URLs are not publishable.",
            "Production mode remains dry-run-only unless EBAY_ALLOW_PRODUCTION_PUBLISH=true.",
        ],
    }


def publish_live(item: dict, draft: dict, photos: list[dict], config: dict) -> dict:
    plan = build_publish_plan(item, draft, photos, config)
    if plan["missing"]:
        raise EbayConfigError("Cannot publish until missing fields are fixed: " + ", ".join(plan["missing"]))
    token = user_token(config)
    sku = plan["sku"]
    common_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Content-Language": "en-US",
        "Accept": "application/json",
    }
    inventory_request = Request(
        f"{api_root(config)}/sell/inventory/v1/inventory_item/{quote(sku)}",
        data=json.dumps(plan["inventoryItemPayload"]).encode(),
        headers=common_headers,
        method="PUT",
    )
    inventory_response = _request_json(inventory_request)
    offer_request = Request(
        f"{api_root(config)}/sell/inventory/v1/offer",
        data=json.dumps(plan["offerPayload"]).encode(),
        headers=common_headers,
        method="POST",
    )
    try:
        offer_response = _request_json(offer_request)
    except EbayApiError as exc:
        offer_id = _offer_id_from_error(str(exc))
        if not offer_id:
            raise
        offer_response = {"offerId": offer_id, "reusedExistingOffer": True}
    offer_id = offer_response.get("offerId")
    if not offer_id:
        raise EbayApiError("createOffer did not return offerId.")
    if offer_response.get("reusedExistingOffer"):
        update_offer_request = Request(
            f"{api_root(config)}/sell/inventory/v1/offer/{quote(str(offer_id))}",
            data=json.dumps(plan["offerPayload"]).encode(),
            headers=common_headers,
            method="PUT",
        )
        offer_response["updateResponse"] = _request_json(update_offer_request)
    publish_request = Request(
        f"{api_root(config)}/sell/inventory/v1/offer/{quote(str(offer_id))}/publish",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="POST",
    )
    publish_response = _request_json(publish_request)
    return {
        "mode": "live",
        "environment": config.get("env", "production"),
        "sku": sku,
        "inventoryResponse": inventory_response,
        "offerResponse": offer_response,
        "publishResponse": publish_response,
    }


def upload_media_image_from_file(photo: dict, config: dict) -> dict:
    path = Path(photo.get("path") or "")
    if not path.exists():
        raise EbayConfigError(f"Photo file does not exist: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    supported = {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/avif",
        "image/heic",
        "image/webp",
    }
    if mime_type not in supported:
        raise EbayConfigError(f"Unsupported eBay Media API image file type: {mime_type}")

    boundary = f"EbuyBoundary{uuid.uuid4().hex}"
    file_bytes = path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="image"; filename="{_multipart_escape(path.name)}"\r\n'.encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = Request(
        f"{media_root(config)}/commerce/media/v1_beta/image/create_image_from_file",
        data=body,
        headers={
            "Authorization": f"Bearer {user_token(config)}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            response_body = _decode_body(response.read(), response.headers.get("Content-Encoding", ""))
            location = response.headers.get("Location", "")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise EbayApiError(f"eBay Media API HTTP {exc.code}: {detail[:800]}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EbayApiError(f"eBay Media API request failed: {exc}") from exc
    try:
        data = json.loads(response_body or "{}")
    except json.JSONDecodeError as exc:
        raise EbayApiError(f"eBay Media API returned non-JSON response: {response_body[:500]}") from exc
    public_url = data.get("imageUrl") or data.get("maxDimensionImageUrl") or ""
    if not public_url:
        raise EbayApiError(f"eBay Media API did not return imageUrl: {response_body[:500]}")
    return {
        "provider": "ebay_media",
        "publicUrl": public_url,
        "maxDimensionImageUrl": data.get("maxDimensionImageUrl") or "",
        "useByDate": data.get("expirationDate") or "",
        "imageLocation": location,
    }


def validate_listing(item: dict, draft: dict, photos: list[dict], config: dict, inventory_payload: dict, offer_payload: dict) -> list[dict]:
    checks = []

    def add(field: str, label: str, passed: bool, level: str, detail: str) -> None:
        checks.append({"field": field, "label": label, "pass": bool(passed), "level": "ok" if passed else level, "detail": detail})

    title = inventory_payload["product"].get("title") or ""
    description = offer_payload.get("listingDescription") or ""
    image_urls = inventory_payload["product"].get("imageUrls") or []
    aspects = inventory_payload["product"].get("aspects") or {}
    raw_category = str(draft.get("category") or "").strip()
    category = str(offer_payload.get("categoryId") or "").strip()
    item_category = str(item.get("category") or "").strip().lower()

    add("listing title", "Title", bool(title), "blocker", "eBay requires a listing title.")
    add("title length", "Title length", len(title) <= 80, "blocker", "Inventory API titles must be 80 characters or fewer.")
    add("HTML description", "Description", bool(description), "blocker", "A buyer-facing listing description is required.")
    add("start price", "Price", _float((offer_payload.get("pricingSummary") or {}).get("price", {}).get("value")) > 0, "blocker", "Price must be greater than zero.")
    add("numeric eBay category ID", "Numeric category", category.isdigit(), "blocker", "Use a numeric eBay category ID, not a label like Tech or Apparel.")
    add("category mapping", "Category source", raw_category.isdigit(), "warning", "Current category came from a fallback map/default. Confirm it before production.")
    add("public HTTPS image URL", "eBay image URLs", bool(image_urls), "blocker", "Upload item photos through eBay Media API before publishing.")
    add("brand aspect", "Brand aspect", bool(aspects.get("Brand")), "warning", "Brand improves search and may be required in some categories.")
    add("model aspect", "Model aspect", bool(aspects.get("Model")), "warning", "Model improves matching and buyer confidence.")
    if item_category in {"sneakers", "apparel", "clothing"}:
        add("size aspect", "Size aspect", bool(aspects.get("Size")), "warning", "Size is important for apparel and footwear listings.")
    haystack = " ".join(str(item.get(key) or "") for key in ["title", "brand", "model", "folder_name", "category"]).lower()
    if any(token in haystack for token in ["mic", "microphone", "videomic"]):
        add("form factor aspect", "Form Factor aspect", bool(aspects.get("Form Factor")), "blocker", "Microphone categories require Form Factor.")
        add("type aspect", "Type aspect", bool(aspects.get("Type")), "warning", "Microphone listings should include Type.")
    add("condition", "Condition", bool(item.get("condition")), "blocker", "Condition must be set before publishing.")
    add("merchant location key", "Merchant location", bool(config.get("merchant_location_key")), "blocker", "Seller inventory location is required.")
    package = inventory_payload.get("packageWeightAndSize") or {}
    add("package weight", "Package weight", bool((package.get("weight") or {}).get("value")), "blocker", "Calculated shipping requires package weight.")
    add("package dimensions", "Package dimensions", bool(package.get("dimensions")), "warning", "Package dimensions improve calculated shipping accuracy.")
    for field, label in [
        ("fulfillmentPolicyId", "Fulfillment policy"),
        ("paymentPolicyId", "Payment policy"),
        ("returnPolicyId", "Return policy"),
    ]:
        add(field, label, bool((offer_payload.get("listingPolicies") or {}).get(field)), "blocker", f"{label} is required for Inventory API offers.")
    return checks


def public_image_urls(photos: list[dict], config: dict) -> list[str]:
    ebay_urls = [
        str(photo.get("ebay_public_url") or "")
        for photo in photos[:24]
        if str(photo.get("ebay_public_url") or "").startswith("https://")
    ]
    if ebay_urls:
        return ebay_urls
    base = (config.get("public_image_base_url") or "").rstrip("/")
    if not base or not base.startswith("https://"):
        return []
    urls = []
    for photo in photos[:24]:
        photo_id = photo.get("id")
        if photo_id:
            urls.append(f"{base}/photo?id={photo_id}")
    return urls


def product_aspects(item: dict) -> dict:
    aspects = {}
    haystack = " ".join(str(item.get(key) or "") for key in ["title", "brand", "model", "folder_name", "category"]).lower()
    if item.get("brand"):
        aspects["Brand"] = [str(item["brand"])]
    if item.get("model"):
        aspects["Model"] = [str(item["model"])]
    if item.get("style_code"):
        aspects["MPN"] = [str(item["style_code"])]
    if item.get("color"):
        aspects["Color"] = [str(item["color"])]
    if item.get("size") and str(item.get("size")).strip().lower() not in {"n/a", "na", "none"}:
        aspects["Size"] = [str(item["size"])]
    if any(token in haystack for token in ["mic", "microphone", "videomic"]):
        aspects.setdefault("Type", ["Microphone"])
        aspects.setdefault("Form Factor", ["Shotgun Microphone"])
        aspects.setdefault("Connectivity", ["3.5 mm (1/8 in) TRS"])
    return aspects


def package_weight_and_size(item: dict) -> dict:
    haystack = " ".join(str(item.get(key) or "") for key in ["title", "model", "folder_name", "category"]).lower()
    if any(token in haystack for token in ["mic", "microphone", "videomic"]):
        return {
            "dimensions": {"height": 4, "length": 8, "width": 6, "unit": "INCH"},
            "weight": {"value": 1, "unit": "POUND"},
        }
    return {
        "dimensions": {"height": 6, "length": 12, "width": 9, "unit": "INCH"},
        "weight": {"value": 2, "unit": "POUND"},
    }


def sku_for(item: dict) -> str:
    name = item.get("style_code") or item.get("model") or item.get("folder_name") or "item"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(name)).strip("-").upper()[:34]
    return f"EBUY-{item.get('id')}-{slug or 'ITEM'}"[:50]


def condition_enum(condition: str) -> str:
    normalized = condition.lower()
    if "parts" in normalized or "not working" in normalized:
        return "FOR_PARTS_OR_NOT_WORKING"
    if "open box" in normalized or "new other" in normalized:
        return "NEW_OTHER"
    if "like new" in normalized:
        return "LIKE_NEW"
    if "new" in normalized and "used" not in normalized and "pre" not in normalized:
        return "NEW"
    if "very good" in normalized:
        return "USED_VERY_GOOD"
    if "acceptable" in normalized:
        return "USED_ACCEPTABLE"
    return "USED_GOOD"


def text_from_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()[:4000]


def _category_id(item: dict, draft: dict, config: dict) -> str:
    raw = str(draft.get("category") or "").strip()
    if raw.isdigit():
        return raw
    category_hint = CATEGORY_HINTS.get(raw.lower()) or CATEGORY_HINTS.get(str(item.get("category") or "").lower())
    if category_hint:
        return category_hint
    fallback = str(config.get("default_category_id") or "").strip()
    return fallback if fallback.isdigit() else ""


def _float(value) -> float:
    try:
        return float(str(value or "0").replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _offer_id_from_error(message: str) -> str:
    if "Offer entity already exists" not in message:
        return ""
    match = re.search(r'"offerId"\s*,\s*"value"\s*:\s*"([^"]+)"', message)
    if match:
        return match.group(1)
    match = re.search(r"offerId[^0-9]+([0-9]+)", message)
    return match.group(1) if match else ""


def _multipart_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def _decode_body(body: bytes, encoding: str = "") -> str:
    if encoding.lower() == "gzip" or body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    return body.decode("utf-8", errors="ignore")
