"""
Module 2 — Données commerciales.

Généralise ed_best_sales.py : tick BGS courant, et pour une commodité donnée,
les meilleures stations où la VENDRE (imports Ardent) et où l'ACHETER
(exports Ardent). La sortie garde les champs numériques bruts (prix, distance,
demande/offre) pour qu'un futur module de calcul de route commerciale puisse
les consommer directement, plutôt qu'un simple format d'affichage.
"""

import sys
from datetime import datetime, timezone

from sources import community


def _normalize_station(entry: dict, direction: str) -> dict:
    """`direction` = "sell" (stations qui achètent -> sellPrice/demand pertinents)
    ou "buy" (stations qui vendent -> buyPrice/stock pertinents). Ardent renseigne
    les deux familles de champs sur chaque entrée, souvent à 0 côté non pertinent :
    il faut donc choisir le bon champ selon le sens plutôt qu'un simple premier-non-nul."""
    price_key = "sellPrice" if direction == "sell" else "buyPrice"
    return {
        "market_id": entry.get("marketId"),
        "system": community.first_present(entry, "systemName", "system"),
        "station": community.first_present(entry, "stationName", "station"),
        "price": community.first_present(entry, price_key, "price"),
        "demand": entry.get("demand") if direction == "sell" else None,
        "supply": entry.get("stock") if direction == "buy" else None,
        "max_landing_pad": community.first_present(entry, "maxLandingPadSize", "padSize"),
        "distance_to_arrival": community.first_present(entry, "distanceToArrival", "distance"),
        "updated_at": community.first_present(entry, "updatedAt", "timestamp"),
    }


def collect(commodity_name: str, station_count: int = 15) -> dict:
    """Récupère tick + meilleures stations d'achat/vente pour `commodity_name`
    (nom lisible, ex. "Agronomic Treatment"). `station_count` limite le nombre
    de stations renvoyées par sens (achat / vente), après filtrage de fraîcheur."""
    result: dict = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "commodity": {"requested": commodity_name, "resolved_name": None},
        "tick": {"time": None, "error": None},
        "best_sell_stations": [],
        "best_buy_stations": [],
        "errors": [],
    }

    try:
        tick_dt = community.fetch_tick()
        result["tick"]["time"] = tick_dt.isoformat() if tick_dt else None
    except Exception as e:
        tick_dt = None
        result["tick"]["error"] = str(e)

    try:
        resolved_name = community.resolve_commodity(commodity_name)
        result["commodity"]["resolved_name"] = resolved_name
    except Exception as e:
        result["errors"].append(f"resolve_commodity: {e}")
        return result

    cutoff = community.freshness_cutoff(tick_dt)

    try:
        sales = community.fetch_best_sales(resolved_name)
        sales = community.filter_fresh(sales, cutoff)[:station_count]
        result["best_sell_stations"] = [_normalize_station(e, "sell") for e in sales]
    except Exception as e:
        result["errors"].append(f"fetch_best_sales: {e}")

    try:
        purchases = community.fetch_best_purchases(resolved_name)
        purchases = community.filter_fresh(purchases, cutoff)[:station_count]
        result["best_buy_stations"] = [_normalize_station(e, "buy") for e in purchases]
    except Exception as e:
        result["errors"].append(f"fetch_best_purchases: {e}")

    return result


if __name__ == "__main__":
    import json

    commodity = sys.argv[1] if len(sys.argv) > 1 else "Agronomic Treatment"
    print(json.dumps(collect(commodity), indent=2, ensure_ascii=False))
