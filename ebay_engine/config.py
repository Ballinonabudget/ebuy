from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


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
    return {
        "base_dir": BASE_DIR,
        "drop_zone": drop_zone,
        "database_path": db_path,
        "host": env.get("HOST", "127.0.0.1"),
        "port": int(env.get("PORT", "8787")),
        "settings": load_settings(),
    }
