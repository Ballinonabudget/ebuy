from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


EBAY_PROFILE_FIELDS = {
    "CLIENT_ID": "client_id",
    "CLIENT_SECRET": "client_secret",
    "REDIRECT_URI": "redirect_uri",
    "USER_ACCESS_TOKEN": "user_access_token",
    "REFRESH_TOKEN": "refresh_token",
    "PAYMENT_POLICY_ID": "payment_policy_id",
    "RETURN_POLICY_ID": "return_policy_id",
    "FULFILLMENT_POLICY_ID": "fulfillment_policy_id",
    "MERCHANT_LOCATION_KEY": "merchant_location_key",
    "DEFAULT_CATEGORY_ID": "default_category_id",
    "PUBLIC_IMAGE_BASE_URL": "public_image_base_url",
}


EBAY_PROFILE_CHECKLIST = [
    {
        "group": "App credentials",
        "fields": [
            ("CLIENT_ID", "Client ID / App ID"),
            ("CLIENT_SECRET", "Client Secret / Cert ID"),
            ("REDIRECT_URI", "RuName / Redirect URI"),
        ],
        "required": True,
    },
    {
        "group": "Seller authorization",
        "fields": [
            ("REFRESH_TOKEN", "Refresh token"),
            ("USER_ACCESS_TOKEN", "User access token"),
        ],
        "required": True,
        "any": True,
        "note": "Use a refresh token for normal operation. A short-lived user access token is acceptable only for temporary testing.",
    },
    {
        "group": "Listing policies",
        "fields": [
            ("PAYMENT_POLICY_ID", "Payment policy ID"),
            ("RETURN_POLICY_ID", "Return policy ID"),
            ("FULFILLMENT_POLICY_ID", "Fulfillment policy ID"),
        ],
        "required": True,
    },
    {
        "group": "Inventory setup",
        "fields": [
            ("MERCHANT_LOCATION_KEY", "Merchant location key"),
            ("DEFAULT_CATEGORY_ID", "Default numeric category ID"),
        ],
        "required": True,
    },
]


def _coerce(value: str):
    raw = value.strip()
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _parse_scalar(value: str):
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip("\"'") for part in inner.split(",")]
    return _coerce(value)


def load_env(path: Path | None = None) -> dict[str, str]:
    env_path = path or BASE_DIR / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def save_env_values(updates: dict[str, str], path: Path | None = None) -> None:
    env_path = path or BASE_DIR / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
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
    env_path.write_text("\n".join(output) + "\n")


def load_settings(path: Path | None = None) -> dict:
    settings_path = path or BASE_DIR / "settings.yaml"
    data: dict = {}
    stack: list[tuple[int, dict | list]] = [(-1, data)]

    for raw_line in settings_path.read_text().splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if line.startswith("- "):
            if isinstance(parent, list):
                parent.append(_parse_scalar(line[2:]))
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value:
            if isinstance(parent, dict):
                parent[key] = _parse_scalar(value)
            continue

        child: dict | list = {}
        if isinstance(parent, dict):
            parent[key] = child
        stack.append((indent, child))

        next_lines = settings_path.read_text().splitlines()
        current_index = next_lines.index(raw_line)
        for future in next_lines[current_index + 1 :]:
            if not future.strip():
                continue
            future_indent = len(future) - len(future.lstrip(" "))
            if future_indent <= indent:
                break
            if future.strip().startswith("- "):
                child_list: list = []
                if isinstance(parent, dict):
                    parent[key] = child_list
                stack[-1] = (indent, child_list)
                break
            break

    return data


def app_config() -> dict:
    env = load_env()
    drop_zone = Path(os.path.expanduser(env.get("DROP_ZONE", "~/eBay_Drop")))
    db_path = Path(env.get("DATABASE_PATH", "data/ebay_engine.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    ebay_env = (env.get("EBAY_ENV") or "production").strip().lower()
    ebay_env = "sandbox" if ebay_env == "sandbox" else "production"
    ebay = ebay_profile_config(env, ebay_env)
    return {
        "base_dir": BASE_DIR,
        "drop_zone": drop_zone,
        "database_path": db_path,
        "host": env.get("HOST", "127.0.0.1"),
        "port": int(env.get("PORT", "8787")),
        "settings": load_settings(),
        "ebay": ebay,
    }


def ebay_profile_config(env: dict[str, str], active_env: str) -> dict:
    prefix = "EBAY_SANDBOX" if active_env == "sandbox" else "EBAY_PRODUCTION"
    profile = {
        "env": active_env,
        "marketplace_id": env.get(f"{prefix}_MARKETPLACE_ID") or env.get("EBAY_MARKETPLACE_ID", "EBAY_US"),
        "allow_production_publish": (env.get("EBAY_ALLOW_PRODUCTION_PUBLISH") or "").strip().lower() == "true",
    }
    for suffix, key in EBAY_PROFILE_FIELDS.items():
        value = env.get(f"{prefix}_{suffix}", "")
        if active_env == "sandbox" and not value:
            value = env.get(f"EBAY_{suffix}", "")
        profile[key] = value
    profile["profiles"] = {
        "sandbox": ebay_profile_summary(env, "EBAY_SANDBOX", allow_legacy=True),
        "production": ebay_profile_summary(env, "EBAY_PRODUCTION", allow_legacy=False),
    }
    return profile


def ebay_profile_summary(env: dict[str, str], prefix: str, allow_legacy: bool = False) -> dict:
    def value(suffix: str) -> str:
        direct = env.get(f"{prefix}_{suffix}", "")
        if allow_legacy and not direct:
            return env.get(f"EBAY_{suffix}", "")
        return direct

    has_app = bool(value("CLIENT_ID") and value("CLIENT_SECRET"))
    has_seller = bool(value("USER_ACCESS_TOKEN") or value("REFRESH_TOKEN"))
    has_policies = all(
        bool(value(suffix))
        for suffix in [
            "PAYMENT_POLICY_ID",
            "RETURN_POLICY_ID",
            "FULFILLMENT_POLICY_ID",
            "MERCHANT_LOCATION_KEY",
            "DEFAULT_CATEGORY_ID",
        ]
    )
    checklist = []
    for group in EBAY_PROFILE_CHECKLIST:
        fields = []
        present_count = 0
        for suffix, label in group["fields"]:
            present = bool(value(suffix))
            present_count += 1 if present else 0
            fields.append(
                {
                    "key": f"{prefix}_{suffix}",
                    "legacyKey": f"EBAY_{suffix}" if allow_legacy else "",
                    "label": label,
                    "present": present,
                }
            )
        complete = present_count > 0 if group.get("any") else present_count == len(fields)
        checklist.append(
            {
                "group": group["group"],
                "required": bool(group.get("required")),
                "complete": complete,
                "any": bool(group.get("any")),
                "note": group.get("note", ""),
                "fields": fields,
            }
        )
    missing = [
        field["key"]
        for group in checklist
        if group["required"] and not group["complete"]
        for field in group["fields"]
        if not field["present"]
    ]
    ready = all(group["complete"] for group in checklist if group["required"])
    return {
        "hasAppCredentials": has_app,
        "hasSellerToken": has_seller,
        "hasListingSetup": has_policies,
        "ready": ready,
        "missing": missing,
        "checklist": checklist,
    }
