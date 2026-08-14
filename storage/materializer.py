"""
Matérialiseur : seul composant à connaître à la fois la forme des dicts
collect() (via les lignes brutes de `collections`) et le schéma SQL dérivé
(stations / market_transactions / price_checks). Les modules n'en savent
rien, et storage/db.py n'en sait rien non plus.

Rejoue les lignes de `collections` non encore traitées (voir
`materialization_progress`), dans l'ordre. Une ligne dont le payload est
mal formé ou incomplet (y compris un payload contenant déjà un champ
`errors` renseigné par le collect() d'origine) est ignorée proprement :
elle ne doit jamais empêcher le traitement des lignes suivantes.
"""

import json

from storage import db


def _get_progress(conn) -> int:
    row = conn.execute(
        "SELECT last_collection_id FROM materialization_progress WHERE id = 1"
    ).fetchone()
    return row[0] if row else 0


def _set_progress(conn, collection_id: int) -> None:
    conn.execute(
        "UPDATE materialization_progress SET last_collection_id = ? WHERE id = 1",
        (collection_id,),
    )


def _upsert_station(conn, market_id, name, system, seen_at) -> None:
    if not isinstance(market_id, int) or not name or not system:
        return  # pas de clé fiable : on ne peut pas peupler `stations` pour cette ligne
    conn.execute(
        """
        INSERT INTO stations (market_id, name, system, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(market_id) DO UPDATE SET
            name = excluded.name,
            system = excluded.system,
            last_seen = MAX(stations.last_seen, excluded.last_seen)
        """,
        (market_id, name, system, seen_at, seen_at),
    )


def _materialize_logbook(conn, collection_id: int, payload: dict) -> None:
    for step in payload.get("etapes", []) or []:
        resume = step.get("resume_depuis_etape_precedente")
        if not resume:
            continue
        commerce = resume.get("commerce", {})
        for tx in commerce.get("achats", []) or []:
            _record_transaction(conn, collection_id, tx, "achat")
        for tx in commerce.get("ventes", []) or []:
            _record_transaction(conn, collection_id, tx, "vente")


def _record_transaction(conn, collection_id: int, tx: dict, direction: str) -> None:
    try:
        commodity = tx["commodity"]
        unit_price = int(tx["prix_unitaire"])
        quantity = int(tx["quantite"])
        total_value = int(tx["valeur_totale"])
        timestamp = tx["horodatage"]
    except (KeyError, TypeError, ValueError):
        return  # transaction mal formée : ignorée proprement, ne bloque pas les suivantes

    market_id = tx.get("market_id")
    _upsert_station(conn, market_id, tx.get("station"), tx.get("systeme"), timestamp)

    conn.execute(
        """
        INSERT INTO market_transactions
            (timestamp, direction, commodity, market_id, unit_price, quantity, total_value, collection_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (timestamp, direction, commodity, market_id if isinstance(market_id, int) else None,
         unit_price, quantity, total_value, collection_id),
    )


def _materialize_market(conn, collection_id: int, payload: dict) -> None:
    checked_at = payload.get("collected_at")
    commodity_info = payload.get("commodity", {})
    commodity = commodity_info.get("resolved_name") or commodity_info.get("requested")
    if not commodity or not checked_at:
        return

    for entry in payload.get("best_sell_stations", []) or []:
        _record_price_check(conn, collection_id, checked_at, commodity, entry, "vente")
    for entry in payload.get("best_buy_stations", []) or []:
        _record_price_check(conn, collection_id, checked_at, commodity, entry, "achat")


def _record_price_check(conn, collection_id: int, checked_at: str, commodity: str, entry: dict, direction: str) -> None:
    price = entry.get("price")
    if not isinstance(price, (int, float)):
        return  # champ absent/illisible (ex. "?" faute de donnée fraîche) : ligne ignorée

    market_id = entry.get("market_id")
    _upsert_station(conn, market_id, entry.get("station"), entry.get("system"), checked_at)

    conn.execute(
        """
        INSERT INTO price_checks (checked_at, commodity, market_id, direction, price, collection_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (checked_at, commodity, market_id if isinstance(market_id, int) else None,
         direction, int(price), collection_id),
    )


def _materialize_commander(conn, collection_id: int, payload: dict) -> None:
    """Point d'extension : aucune table dérivée pour `commander` dans ce schéma
    (phase 2). À implémenter dans une phase future si un historique
    (crédits, flotte, fleet carrier...) devient nécessaire."""
    return


_HANDLERS = {
    "logbook": _materialize_logbook,
    "market": _materialize_market,
    "commander": _materialize_commander,
}


def materialize(conn=None) -> dict:
    """Traite toutes les lignes de `collections` postérieures à la marque de
    progression. Renvoie {"processed": n, "errors": [...]}. Une exception sur
    une ligne (JSON invalide, payload inattendu) est consignée dans `errors`
    et n'empêche jamais le traitement des lignes suivantes."""
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        last_id = _get_progress(conn)
        rows = conn.execute(
            "SELECT id, module, payload FROM collections WHERE id > ? ORDER BY id",
            (last_id,),
        ).fetchall()

        processed = 0
        errors: list[str] = []

        for collection_id, module_name, payload_json in rows:
            try:
                payload = json.loads(payload_json)
                handler = _HANDLERS.get(module_name)
                if handler is not None:
                    handler(conn, collection_id, payload)
                # module inconnu : ignoré proprement, aucune table dérivée définie pour lui
            except Exception as e:
                errors.append(f"collection {collection_id} ({module_name}) : {e}")

            _set_progress(conn, collection_id)
            processed += 1

        conn.commit()
        return {"processed": processed, "errors": errors}
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import json as _json

    print(_json.dumps(materialize(), indent=2, ensure_ascii=False))
