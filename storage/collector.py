"""
Passe-plat entre les modules (modules/*.py) et le journal brut (table
`collections`). Aucune interprétation du contenu ici : on appelle collect(),
on sérialise le dict tel quel en JSON, on l'insère avec un horodatage. Les
modules n'ont donc aucune connaissance du stockage, et ce fichier n'a
aucune connaissance de la forme interne des dicts qu'il transporte au-delà
de `collected_at`/`source`.
"""

import json

from modules import commander, logbook, market
from storage import db


def _record(conn, module_name: str, payload: dict) -> int:
    cursor = conn.execute(
        "INSERT INTO collections (module, collected_at, source, payload) VALUES (?, ?, ?, ?)",
        (
            module_name,
            payload.get("collected_at"),
            payload.get("source"),
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def record_commander(conn=None) -> int:
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        return _record(conn, "commander", commander.collect())
    finally:
        if own_conn:
            conn.close()


def record_market(conn=None, commodity_name: str = "Agronomic Treatment", station_count: int = 15) -> int:
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        return _record(conn, "market", market.collect(commodity_name, station_count))
    finally:
        if own_conn:
            conn.close()


def record_logbook(conn=None, max_entries: int | None = None) -> int:
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        return _record(conn, "logbook", logbook.collect(max_entries))
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    conn = db.connect()
    try:
        if target in ("commander", "all"):
            print("commander ->", record_commander(conn))
        if target in ("market", "all"):
            commodity = sys.argv[2] if len(sys.argv) > 2 else "Agronomic Treatment"
            print("market ->", record_market(conn, commodity))
        if target in ("logbook", "all"):
            print("logbook ->", record_logbook(conn))
    finally:
        conn.close()
