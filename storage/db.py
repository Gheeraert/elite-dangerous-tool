"""
Connexion et schéma SQLite.

Deux niveaux de tables :
  - `collections` : journal brut, append-only, une ligne par appel collect().
    Source de vérité, jamais modifiée après écriture — elle ne casse jamais
    quand le format renvoyé par un module évolue.
  - `stations` / `market_transactions` / `price_checks` : tables dérivées,
    reconstruites à partir du journal brut par storage/materializer.py.

Ce module ne connaît rien à la façon dont les données ont été collectées
(CAPI, journal local, Ardent) : c'est storage/materializer.py qui fait le
pont entre la forme des dicts collect() et ce schéma.
"""

import sqlite3
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.toml"
DEFAULT_DB_PATH = REPO_ROOT / "elite.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    source TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collections_module_date ON collections(module, collected_at);

CREATE TABLE IF NOT EXISTS stations (
    market_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    system TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('achat','vente')),
    commodity TEXT NOT NULL,
    market_id INTEGER REFERENCES stations(market_id),
    unit_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    total_value INTEGER NOT NULL,
    collection_id INTEGER REFERENCES collections(id)
);
CREATE INDEX IF NOT EXISTS idx_transactions_commodity ON market_transactions(commodity, timestamp);

CREATE TABLE IF NOT EXISTS price_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    commodity TEXT NOT NULL,
    market_id INTEGER REFERENCES stations(market_id),
    direction TEXT NOT NULL CHECK(direction IN ('achat','vente')),
    price INTEGER NOT NULL,
    collection_id INTEGER REFERENCES collections(id)
);

-- Marque de progression du matérialiseur : id de la dernière ligne de
-- `collections` déjà traitée. Une seule ligne (id=1), pas de mécanisme
-- distribué : cohérent avec un usage local mono-utilisateur.
CREATE TABLE IF NOT EXISTS materialization_progress (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_collection_id INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO materialization_progress (id, last_collection_id) VALUES (1, 0);
"""


def resolve_db_path() -> Path:
    """Chemin de la base : `[storage].path` dans config.toml si présent et non
    vide, sinon un défaut sensé (elite.db à la racine du dépôt)."""
    if CONFIG_PATH.is_file():
        with CONFIG_PATH.open("rb") as f:
            config = tomllib.load(f)
        configured = config.get("storage", {}).get("path")
        if configured:
            path = Path(configured)
            return path if path.is_absolute() else REPO_ROOT / path
    return DEFAULT_DB_PATH


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Ouvre une connexion SQLite et applique le schéma s'il est absent
    (idempotent : CREATE TABLE/INDEX IF NOT EXISTS, aucun script de
    migration séparé à lancer manuellement)."""
    path = Path(db_path) if db_path else resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL : plusieurs connexions (une par thread de storage/loop.py) peuvent
    # écrire sans se heurter à "database is locked" au premier chevauchement ;
    # busy_timeout absorbe le cas résiduel d'une écriture concurrente exacte
    # en attendant plutôt qu'en échouant immédiatement.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
