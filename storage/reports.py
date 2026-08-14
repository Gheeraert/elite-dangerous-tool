"""
Rapports en lecture seule sur le pont SQLite (storage/db.py). Ce module ne
fait jamais d'écriture — uniquement des SELECT — et n'a aucune connaissance
de comment les données ont été collectées, seulement du schéma dérivé
(market_transactions, price_checks).
"""

import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from storage import db

# Au-delà de cette fenêtre avant une transaction, un price_check est jugé
# trop ancien pour servir de référence de comparaison.
_COMPARISON_WINDOW_DAYS = 7

_REQUIRED_TABLES = ("collections", "market_transactions", "price_checks")


class ReportUnavailable(Exception):
    """Levée quand la base ou les tables attendues n'existent pas encore."""


def _normalize_commodity(name: str) -> str:
    """market_transactions stocke le nom lisible du journal ("Agronomic
    Treatment"), price_checks le slug Ardent ("agronomictreatment") : sans
    cette normalisation (minuscule, alphanumérique uniquement), aucune
    correspondance n'est jamais trouvée entre les deux tables."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _ensure_ready(conn: sqlite3.Connection) -> None:
    missing = [t for t in _REQUIRED_TABLES if not _table_exists(conn, t)]
    if missing:
        raise ReportUnavailable(
            f"Table(s) absente(s) : {', '.join(missing)}. "
            "Lancez d'abord une collecte (python -m storage.collector) "
            "puis une matérialisation (python -m storage.materializer)."
        )


def _best_price_before(
    price_checks: list[tuple[datetime, int]], at: datetime
) -> tuple[datetime, int] | None:
    """Parmi les (checked_at, price) d'une commodité/direction donnée, renvoie
    l'instantané le plus proche mais antérieur ou égal à `at`, en prenant le
    prix maximum parmi les stations de cet instantané. None si rien dans la
    fenêtre de comparaison (_COMPARISON_WINDOW_DAYS)."""
    window_start = at - timedelta(days=_COMPARISON_WINDOW_DAYS)
    candidates = [(checked_at, price) for checked_at, price in price_checks if window_start <= checked_at <= at]
    if not candidates:
        return None
    best_checked_at = max(checked_at for checked_at, _ in candidates)
    best_price = max(price for checked_at, price in candidates if checked_at == best_checked_at)
    return best_checked_at, best_price


def profit_by_commodity(conn: sqlite3.Connection, days: int = 30) -> list[dict]:
    """Pour chaque commodité ayant au moins une transaction réelle dans les
    `days` derniers jours : volumes achetés/vendus, crédits dépensés/reçus,
    profit réel brut, et pour les ventes comparables (un price_check existe
    dans les _COMPARISON_WINDOW_DAYS jours précédant la transaction),
    l'écart entre le revenu réel et celui au meilleur prix communautaire
    connu au moment de la vente.

    Requêtes en lecture seule uniquement. Lève ReportUnavailable si la base
    n'a pas encore été initialisée (aucune collecte lancée)."""
    _ensure_ready(conn)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    tx_rows = conn.execute(
        "SELECT commodity, direction, quantity, total_value, timestamp FROM market_transactions"
    ).fetchall()
    price_rows = conn.execute(
        "SELECT commodity, direction, checked_at, price FROM price_checks"
    ).fetchall()

    price_checks_by_key: dict[tuple[str, str], list[tuple[datetime, int]]] = defaultdict(list)
    for commodity, direction, checked_at, price in price_rows:
        try:
            key = (_normalize_commodity(commodity), direction)
            price_checks_by_key[key].append((_parse_ts(checked_at), price))
        except (TypeError, ValueError):
            continue  # horodatage illisible : instantané ignoré proprement

    per_commodity: dict[str, dict] = defaultdict(lambda: {
        "achats_count": 0, "ventes_count": 0,
        "quantite_achetee": 0, "quantite_vendue": 0,
        "credits_depenses": 0, "credits_recus": 0,
        "ventes_comparables": 0, "ventes_non_comparables": 0,
        "revenu_potentiel_meilleur_prix": 0, "ecart_credits": 0,
    })

    for commodity, direction, quantity, total_value, timestamp in tx_rows:
        try:
            ts = _parse_ts(timestamp)
        except (TypeError, ValueError):
            continue  # transaction à l'horodatage illisible : ignorée proprement, pas bloquante
        if ts < cutoff:
            continue

        row = per_commodity[commodity]
        if direction == "achat":
            row["achats_count"] += 1
            row["quantite_achetee"] += quantity
            row["credits_depenses"] += total_value
        elif direction == "vente":
            row["ventes_count"] += 1
            row["quantite_vendue"] += quantity
            row["credits_recus"] += total_value

            key = (_normalize_commodity(commodity), "vente")
            best = _best_price_before(price_checks_by_key.get(key, []), ts)
            if best is None:
                row["ventes_non_comparables"] += 1
            else:
                _, best_price = best
                revenu_potentiel = best_price * quantity
                row["ventes_comparables"] += 1
                row["revenu_potentiel_meilleur_prix"] += revenu_potentiel
                row["ecart_credits"] += total_value - revenu_potentiel

    results = []
    for commodity, row in per_commodity.items():
        comparable = row["ventes_comparables"] > 0
        ecart_pct = (
            row["ecart_credits"] / row["revenu_potentiel_meilleur_prix"] * 100
            if comparable and row["revenu_potentiel_meilleur_prix"]
            else None
        )
        results.append({
            "commodity": commodity,
            "achats": {
                "count": row["achats_count"],
                "quantite": row["quantite_achetee"],
                "credits_depenses": row["credits_depenses"],
            },
            "ventes": {
                "count": row["ventes_count"],
                "quantite": row["quantite_vendue"],
                "credits_recus": row["credits_recus"],
            },
            "profit_reel": row["credits_recus"] - row["credits_depenses"],
            "comparaison_marche": {
                "comparable": comparable,
                "ventes_comparables": row["ventes_comparables"],
                "ventes_non_comparables": row["ventes_non_comparables"],
                "revenu_potentiel_meilleur_prix": row["revenu_potentiel_meilleur_prix"] if comparable else None,
                "ecart_credits": row["ecart_credits"] if comparable else None,
                "ecart_pct": ecart_pct,
            },
        })

    results.sort(key=lambda r: r["profit_reel"], reverse=True)
    return results


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.1f}".replace(",", " ")
    return f"{value:,}".replace(",", " ")


def print_report(results: list[dict], days: int) -> None:
    if not results:
        print(f"Aucune transaction dans les {days} derniers jours.")
        return

    columns = [
        ("Commodité", 24, "<"),
        ("Achats", 7, ">"),
        ("Ventes", 7, ">"),
        ("Qté ach.", 9, ">"),
        ("Qté vendue", 10, ">"),
        ("Dépensé", 13, ">"),
        ("Reçu", 13, ">"),
        ("Profit réel", 13, ">"),
        ("Écart marché", 13, ">"),
        ("Écart %", 8, ">"),
    ]
    header = " ".join(f"{name:{align}{width}}" for name, width, align in columns)
    print(header)
    print("-" * len(header))

    for r in results:
        cm = r["comparaison_marche"]
        ecart_pct = f"{cm['ecart_pct']:.1f}%" if cm["ecart_pct"] is not None else "n/a"
        values = [
            r["commodity"],
            _fmt(r["achats"]["count"]),
            _fmt(r["ventes"]["count"]),
            _fmt(r["achats"]["quantite"]),
            _fmt(r["ventes"]["quantite"]),
            _fmt(r["achats"]["credits_depenses"]),
            _fmt(r["ventes"]["credits_recus"]),
            _fmt(r["profit_reel"]),
            _fmt(cm["ecart_credits"]),
            ecart_pct,
        ]
        print(" ".join(f"{v:{align}{width}}" for v, (_, width, align) in zip(values, columns)))

    non_comparables = sum(r["comparaison_marche"]["ventes_non_comparables"] for r in results)
    if non_comparables:
        print(
            f"\n({non_comparables} vente(s) sans price_check dans les {_COMPARISON_WINDOW_DAYS} "
            "jours précédents : exclues du calcul d'écart marché.)"
        )


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # évite le mojibake sur les consoles Windows non-UTF8

    parser = argparse.ArgumentParser(description="Profit réel par commodité, comparé au marché.")
    parser.add_argument("--days", type=int, default=30, help="Fenêtre en jours (défaut : 30)")
    args = parser.parse_args()

    conn = db.connect()
    try:
        try:
            report = profit_by_commodity(conn, days=args.days)
        except ReportUnavailable as e:
            raise SystemExit(str(e))
        print_report(report, args.days)
    finally:
        conn.close()
