from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  folder_name TEXT NOT NULL UNIQUE,
  folder_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  title TEXT,
  brand TEXT,
  model TEXT,
  style_code TEXT,
  upc TEXT,
  category TEXT DEFAULT 'general',
  item_type TEXT,
  size TEXT,
  color TEXT,
  condition TEXT,
  box TEXT,
  accessories TEXT,
  tested TEXT,
  defects TEXT,
  notes TEXT,
  cogs REAL NOT NULL DEFAULT 0,
  retail_price REAL,
  release_date TEXT,
  kicksdb_verified INTEGER DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kicksdb_cache (
  sku TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL,
  path TEXT NOT NULL,
  filename TEXT NOT NULL,
  role TEXT,
  sort_order INTEGER DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS photo_publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  photo_id INTEGER NOT NULL,
  provider TEXT NOT NULL DEFAULT 'ebay_media',
  ebay_env TEXT NOT NULL DEFAULT 'sandbox',
  public_url TEXT NOT NULL DEFAULT '',
  use_by_date TEXT,
  uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  error TEXT,
  UNIQUE(photo_id, provider, ebay_env),
  FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ebay_listing_publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL,
  ebay_env TEXT NOT NULL,
  sku TEXT NOT NULL,
  offer_id TEXT,
  listing_id TEXT,
  status TEXT NOT NULL DEFAULT 'published',
  response_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(item_id, ebay_env),
  FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS deal_scout_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_key TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL,
  avg_sold_price REAL DEFAULT 0,
  median_sold_price REAL DEFAULT 0,
  sold_price_low REAL DEFAULT 0,
  sold_price_high REAL DEFAULT 0,
  expected_sale_price REAL DEFAULT 0,
  active_count INTEGER DEFAULT 0,
  sold_count_30d INTEGER DEFAULT 0,
  shipping_cost REAL DEFAULT 0,
  query TEXT,
  sampled_sold_count INTEGER DEFAULT 0,
  filtered_sold_count INTEGER DEFAULT 0,
  sampled_active_count INTEGER DEFAULT 0,
  confidence TEXT DEFAULT 'unknown',
  confidence_score INTEGER DEFAULT 0,
  active_url TEXT,
  sold_url TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS market_competition (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL,
  snapshot_id INTEGER,
  title TEXT NOT NULL DEFAULT '',
  condition TEXT NOT NULL DEFAULT '',
  price REAL NOT NULL DEFAULT 0,
  watchers INTEGER NOT NULL DEFAULT 0,
  url TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE,
  FOREIGN KEY(snapshot_id) REFERENCES market_snapshots(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL,
  listing_format TEXT NOT NULL,
  pricing_mode TEXT NOT NULL,
  suggested_price REAL NOT NULL,
  ebay_fee REAL NOT NULL,
  order_fee REAL NOT NULL,
  packaging_reserve REAL NOT NULL,
  risk_reserve REAL NOT NULL,
  estimated_profit REAL NOT NULL,
  roi REAL NOT NULL,
  sell_through_rate REAL NOT NULL,
  decision TEXT NOT NULL,
  rationale TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS listing_drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  shipping_service TEXT NOT NULL DEFAULT 'calculated_buyer_paid',
  format_kind TEXT NOT NULL DEFAULT 'fixed',
  start_price REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL,
  sale_price REAL NOT NULL DEFAULT 0,
  actual_ebay_fees REAL NOT NULL DEFAULT 0,
  actual_shipping_cost REAL NOT NULL DEFAULT 0,
  sold_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);
"""


MIGRATIONS = {
    "items": {
        "style_code": "TEXT",
        "upc": "TEXT",
        "item_type": "TEXT",
        "color": "TEXT",
        "tested": "TEXT",
        "defects": "TEXT",
        "retail_price": "REAL",
        "release_date": "TEXT",
        "kicksdb_verified": "INTEGER DEFAULT 0",
    },
    "photos": {
        "sort_order": "INTEGER DEFAULT 0",
    },
    "photo_publications": {
        "provider": "TEXT NOT NULL DEFAULT 'ebay_media'",
        "ebay_env": "TEXT NOT NULL DEFAULT 'sandbox'",
        "public_url": "TEXT NOT NULL DEFAULT ''",
        "use_by_date": "TEXT",
        "uploaded_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "error": "TEXT",
    },
    "ebay_listing_publications": {
        "offer_id": "TEXT",
        "listing_id": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'published'",
        "response_json": "TEXT",
        "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "deal_scout_reviews": {
        "notes": "TEXT",
        "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "market_snapshots": {
        "median_sold_price": "REAL DEFAULT 0",
        "sold_price_low": "REAL DEFAULT 0",
        "sold_price_high": "REAL DEFAULT 0",
        "query": "TEXT",
        "sampled_sold_count": "INTEGER DEFAULT 0",
        "filtered_sold_count": "INTEGER DEFAULT 0",
        "sampled_active_count": "INTEGER DEFAULT 0",
        "confidence": "TEXT DEFAULT 'unknown'",
        "confidence_score": "INTEGER DEFAULT 0",
        "active_url": "TEXT",
        "sold_url": "TEXT",
    },
}


def migrate(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def row(conn: sqlite3.Connection, query: str, params: tuple = ()) -> dict | None:
    result = conn.execute(query, params).fetchone()
    return dict(result) if result else None
