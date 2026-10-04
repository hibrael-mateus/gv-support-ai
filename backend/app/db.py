"""Local SQLite store: cases, investigation memory, chat, sources, chunks (FTS5 + vectors), feedback.

Plain sqlite3 instead of an ORM: the lexical index is an FTS5 virtual table and vectors are BLOBs
in the same file, which keeps the install a single portable database and the bundle small.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from .settings import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  customer TEXT DEFAULT '', product TEXT DEFAULT '', module TEXT DEFAULT '',
  routine TEXT DEFAULT '', menu TEXT DEFAULT '', screen TEXT DEFAULT '',
  error_message TEXT DEFAULT '', description TEXT DEFAULT '',
  environment TEXT DEFAULT '', server TEXT DEFAULT '', database_name TEXT DEFAULT '',
  already_validated TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Em investigação',
  root_cause TEXT DEFAULT '', resolution TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Investigation memory: tests already executed and their outcome ("DNS PV990 = OK").
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  key TEXT NOT NULL, value TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'INFO',
  source TEXT DEFAULT 'analista',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(case_id, key)
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  title TEXT NOT NULL, rationale TEXT DEFAULT '', test TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Não validada', evidence TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,  -- NULL = free chat
  role TEXT NOT NULL, content TEXT NOT NULL,
  agent TEXT DEFAULT '', sources_json TEXT DEFAULT '[]', meta_json TEXT DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
  name TEXT NOT NULL, path TEXT NOT NULL, size INTEGER DEFAULT 0,
  text_excerpt TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
  useful INTEGER NOT NULL, reason TEXT DEFAULT '', comment TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
  drive_file_id TEXT PRIMARY KEY,
  name TEXT NOT NULL, mime_type TEXT, path TEXT DEFAULT '',
  folder_id TEXT, authorized_root TEXT NOT NULL,
  product TEXT DEFAULT '', module TEXT DEFAULT '', doc_type TEXT DEFAULT '',
  modified_time TEXT, hash TEXT, chunks INTEGER DEFAULT 0, web_url TEXT DEFAULT '',
  uses INTEGER DEFAULT 0,
  indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS index_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drive_file_id TEXT, name TEXT, error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drive_file_id TEXT NOT NULL REFERENCES sources(drive_file_id) ON DELETE CASCADE,
  page INTEGER DEFAULT 0, ordinal INTEGER DEFAULT 0,
  content TEXT NOT NULL, embedding BLOB,
  section TEXT DEFAULT '', product TEXT DEFAULT '', doc_type TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_chunks_file ON chunks(drive_file_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  content, source_name, product, module, doc_type,
  tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_init_lock = threading.Lock()
_initialized = False


def init_db() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.executescript(SCHEMA)
        _initialized = True


def reset_for_tests() -> None:
    global _initialized
    _initialized = False


@contextmanager
def connection():
    init_db()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_meta(key: str, default: str = "") -> str:
    with connection() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    with connection() as conn:
        conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
