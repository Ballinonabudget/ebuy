from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebay_engine.config import BASE_DIR, app_config
from ebay_engine.ebay_api import api_root, user_token


LOCATION_KEY = "EBUY_ORLANDO_32837"
MARKETPLACE_ID = "EBAY_US"
CATEGORY_TYPE = [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}]


def ebay_request(config: dict, path: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(
        f"{api_root(config)}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {user_token(config)}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Content-Language": "en-US",
            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 409 and method in {"POST", "PUT"}:
            return {"status": "exists", "detail": detail}
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc
    if not body:
        return {}
    return json.loads(body)


def first_policy_id(data: dict, collection_name: str, id_name: str, fallback_name: str) -> str:
    for policy in data.get(collection_name) or []:
        if policy.get("name") == fallback_name:
            return str(policy.get(id_name) or "")
    for policy in data.get(collection_name) or []:
        if policy.get(id_name):
            return str(policy[id_name])
    return ""


def create_or_find_payment_policy(config: dict) -> str:
    name = "Ebuy Sandbox Immediate Payment"
    existing = ebay_request(config, f"/sell/account/v1/payment_policy?{urlencode({'marketplace_id': MARKETPLACE_ID})}")
    policy_id = first_policy_id(existing, "paymentPolicies", "paymentPolicyId", name)
    if policy_id:
        return policy_id
    created = ebay_request(
        config,
        "/sell/account/v1/payment_policy",
        "POST",
        {
            "name": name,
            "marketplaceId": MARKETPLACE_ID,
            "categoryTypes": CATEGORY_TYPE,
            "immediatePay": True,
        },
    )
    return str(created.get("paymentPolicyId") or "")


def create_or_find_return_policy(config: dict) -> str:
    name = "Ebuy Sandbox No Returns"
    existing = ebay_request(config, f"/sell/account/v1/return_policy?{urlencode({'marketplace_id': MARKETPLACE_ID})}")
    policy_id = first_policy_id(existing, "returnPolicies", "returnPolicyId", name)
    if policy_id:
        return policy_id
    created = ebay_request(
        config,
        "/sell/account/v1/return_policy",
        "POST",
        {
            "name": name,
            "marketplaceId": MARKETPLACE_ID,
            "categoryTypes": CATEGORY_TYPE,
            "returnsAccepted": False,
        },
    )
    return str(created.get("returnPolicyId") or "")


def calculated_fulfillment_payload(name: str) -> dict:
    return {
        "name": name,
        "marketplaceId": MARKETPLACE_ID,
        "categoryTypes": CATEGORY_TYPE,
        "handlingTime": {"value": 2, "unit": "DAY"},
        "shipToLocations": {"regionIncluded": [{"regionName": "US"}], "regionExcluded": []},
        "shippingOptions": [
            {
                "optionType": "DOMESTIC",
                "costType": "CALCULATED",
                "shippingServices": [
                    {
                        "sortOrder": 1,
                        "shippingCarrierCode": "USPS",
                        "shippingServiceCode": "USPSPriority",
                        "freeShipping": False,
                        "buyerResponsibleForShipping": True,
                        "buyerResponsibleForPickup": False,
                    }
                ],
                "insuranceOffered": False,
            }
        ],
        "globalShipping": False,
        "pickupDropOff": False,
        "freightShipping": False,
    }


def flat_rate_fulfillment_payload(name: str) -> dict:
    payload = calculated_fulfillment_payload(name)
    payload["shippingOptions"][0]["costType"] = "FLAT_RATE"
    payload["shippingOptions"][0]["shippingServices"][0]["shippingCost"] = {
        "value": "8.99",
        "currency": "USD",
    }
    return payload


def create_or_find_fulfillment_policy(config: dict) -> str:
    name = "Ebuy Sandbox Calculated USPS"
    existing = ebay_request(
        config,
        f"/sell/account/v1/fulfillment_policy?{urlencode({'marketplace_id': MARKETPLACE_ID})}",
    )
    policy_id = first_policy_id(existing, "fulfillmentPolicies", "fulfillmentPolicyId", name)
    if policy_id:
        return policy_id
    try:
        created = ebay_request(config, "/sell/account/v1/fulfillment_policy", "POST", calculated_fulfillment_payload(name))
    except RuntimeError as exc:
        print(f"Calculated shipping policy was rejected, falling back to flat-rate sandbox policy: {exc}")
        created = ebay_request(
            config,
            "/sell/account/v1/fulfillment_policy",
            "POST",
            flat_rate_fulfillment_payload("Ebuy Sandbox Flat Rate USPS"),
        )
    return str(created.get("fulfillmentPolicyId") or "")


def create_location(config: dict) -> str:
    ebay_request(
        config,
        f"/sell/inventory/v1/location/{quote(LOCATION_KEY)}",
        "POST",
        {
            "name": "Ebuy Orlando Warehouse",
            "merchantLocationStatus": "ENABLED",
            "locationTypes": ["WAREHOUSE"],
            "location": {
                "address": {
                    "addressLine1": "11310 S Orange Blossom Trail",
                    "addressLine2": "Suite 351",
                    "city": "Orlando",
                    "stateOrProvince": "FL",
                    "postalCode": "32837",
                    "country": "US",
                }
            },
        },
    )
    return LOCATION_KEY


def upsert_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    output = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n")


def main() -> None:
    config = app_config()["ebay"]
    if config.get("env") != "sandbox":
        raise SystemExit("Refusing to create sandbox defaults because EBAY_ENV is not sandbox.")

    location_key = create_location(config)
    payment_policy_id = create_or_find_payment_policy(config)
    return_policy_id = create_or_find_return_policy(config)
    fulfillment_policy_id = create_or_find_fulfillment_policy(config)

    updates = {
        "EBAY_MERCHANT_LOCATION_KEY": location_key,
        "EBAY_PAYMENT_POLICY_ID": payment_policy_id,
        "EBAY_RETURN_POLICY_ID": return_policy_id,
        "EBAY_FULFILLMENT_POLICY_ID": fulfillment_policy_id,
        "EBAY_DEFAULT_CATEGORY_ID": "29946",
    }
    upsert_env(BASE_DIR / ".env", updates)

    print(
        json.dumps(
            {
                "locationKey": location_key,
                "paymentPolicyId": bool(payment_policy_id),
                "returnPolicyId": bool(return_policy_id),
                "fulfillmentPolicyId": bool(fulfillment_policy_id),
                "defaultCategoryId": updates["EBAY_DEFAULT_CATEGORY_ID"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
