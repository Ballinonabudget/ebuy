from __future__ import annotations

import re
import sqlite3
from pathlib import Path


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


FIELD_MAP = {
    "brand": "brand",
    "model": "model",
    "style_code": "style_code",
    "style": "style_code",
    "upc": "upc",
    "category": "category",
    "item_type": "item_type",
    "size": "size",
    "color": "color",
    "condition": "condition",
    "box": "box",
    "package/box": "box",
    "package_box": "box",
    "accessories": "accessories",
    "tested": "tested",
    "defects": "defects",
    "notes": "notes",
    "cogs": "cogs",
}


def parse_gist(path: Path) -> dict:
    data: dict[str, str | float] = {}
    notes: list[str] = []
    for line in path.read_text(errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            notes.append(stripped)
            continue
        key, value = stripped.split(":", 1)
        normalized = key.strip().lower().replace(" ", "_")
        mapped = FIELD_MAP.get(normalized)
        if not mapped:
            notes.append(stripped)
            continue
        clean = value.strip()
        if mapped == "cogs":
            match = re.search(r"\d+(?:\.\d+)?", clean)
            data[mapped] = float(match.group(0)) if match else 0.0
        else:
            data[mapped] = clean
    if notes and "notes" not in data:
        data["notes"] = "\n".join(notes)
    return data


def find_gist(folder: Path) -> Path | None:
    exact = folder / "gist.txt"
    if exact.exists():
        return exact
    candidates = sorted(
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".txt"
        and "gist" in path.stem.lower()
    )
    return candidates[0] if candidates else None


def scan_drop_zone(conn: sqlite3.Connection, drop_zone: Path) -> dict:
    drop_zone.mkdir(parents=True, exist_ok=True)
    imported = 0
    skipped = 0
    details: list[dict] = []

    for folder in sorted(path for path in drop_zone.iterdir() if path.is_dir()):
        gist = find_gist(folder)
        if not gist:
            skipped += 1
            details.append({"folder": folder.name, "status": "skipped", "reason": "missing gist text file"})
            continue
        exists = conn.execute(
            "SELECT id FROM items WHERE folder_name = ?", (folder.name,)
        ).fetchone()
        if exists:
            skipped += 1
            details.append({"folder": folder.name, "status": "skipped", "reason": "already imported"})
            continue

        parsed = parse_gist(gist)
        if parsed.get("defects") and parsed.get("defects") != "None":
            parsed["notes"] = "\n".join(
                part
                for part in [str(parsed.get("notes") or ""), f"Defects: {parsed['defects']}"]
                if part
            )
        if parsed.get("tested") and parsed.get("tested") != "N/A":
            parsed["notes"] = "\n".join(
                part
                for part in [str(parsed.get("notes") or ""), f"Tested: {parsed['tested']}"]
                if part
            )
        cogs = float(parsed.get("cogs", 0) or 0)
        fields = {
            "folder_name": folder.name,
            "folder_path": str(folder),
            "brand": parsed.get("brand"),
            "model": parsed.get("model") or parsed.get("item_type"),
            "style_code": parsed.get("style_code"),
            "upc": parsed.get("upc"),
            "category": parsed.get("category") or "general",
            "item_type": parsed.get("item_type"),
            "size": parsed.get("size"),
            "color": parsed.get("color"),
            "condition": parsed.get("condition"),
            "box": parsed.get("box"),
            "accessories": parsed.get("accessories"),
            "tested": parsed.get("tested"),
            "defects": parsed.get("defects"),
            "notes": parsed.get("notes"),
            "cogs": cogs,
        }
        cursor = conn.execute(
            """
            INSERT INTO items (
              folder_name, folder_path, brand, model, style_code, upc,
              category, item_type, size, color, condition, box, accessories, tested, defects,
              notes, cogs
            ) VALUES (
              :folder_name, :folder_path, :brand, :model, :style_code, :upc,
              :category, :item_type, :size, :color, :condition, :box, :accessories, :tested, :defects,
              :notes, :cogs
            )
            """,
            fields,
        )
        item_id = cursor.lastrowid
        for index, photo in enumerate(sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_EXTENSIONS)):
            conn.execute(
                "INSERT INTO photos (item_id, path, filename, sort_order) VALUES (?, ?, ?, ?)",
                (item_id, str(photo), photo.name, index),
            )
        imported += 1
        details.append({"folder": folder.name, "status": "imported", "reason": f"used {gist.name}"})

    conn.commit()
    return {"imported": imported, "skipped": skipped, "details": details}
