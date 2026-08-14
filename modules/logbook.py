"""
Module 3 — Journal de bord.

Transforme les fichiers Journal.*.log en une liste chronologique d'étapes
significatives (arrivée en système, amarrage, départ), chacune accompagnée
d'un résumé catégorisé (commerce / combat / minage / exploration) des
actions survenues depuis l'étape précédente. Ce n'est pas un export brut
transaction par transaction : les événements non couverts sont ignorés
proprement, sans faire planter le parsing.

Événements couverts a minima : FSDJump, Docked, Undocked, MarketBuy,
MarketSell, Bounty, MiningRefined, FSSSignalDiscovered, CarrierJump.
"""

from datetime import datetime, timezone

from sources import journal

_STEP_EVENTS = {
    "FSDJump": "arrivee_systeme",
    "CarrierJump": "arrivee_systeme_carrier",
    "Docked": "amarrage",
    "Undocked": "depart",
}


def _empty_activity() -> dict:
    return {
        # Une entrée par transaction (pas un simple compteur) : c'est ce qui permet
        # au matérialiseur de stockage de peupler market_transactions ligne par ligne.
        "commerce": {"achats": [], "ventes": []},
        "combat": {"primes": 0, "recompenses": 0},
        "minage": {"materiaux": {}},
        "exploration": {"signaux_detectes": 0},
    }


def _activity_has_content(activity: dict) -> bool:
    return (
        bool(activity["commerce"]["achats"])
        or bool(activity["commerce"]["ventes"])
        or any(activity["combat"].values())
        or bool(activity["minage"]["materiaux"])
        or activity["exploration"]["signaux_detectes"] > 0
    )


def _apply_activity_event(activity: dict, event: dict, current_station: dict) -> None:
    etype = event.get("event")
    if etype == "MarketBuy":
        activity["commerce"]["achats"].append({
            "horodatage": event.get("timestamp"),
            "commodity": event.get("Type_Localised", event.get("Type", "?")),
            "market_id": current_station.get("market_id"),
            "station": current_station.get("station"),
            "systeme": current_station.get("systeme"),
            "quantite": event.get("Count", 0),
            "prix_unitaire": event.get("BuyPrice", 0),
            "valeur_totale": event.get("TotalCost", 0),
        })
    elif etype == "MarketSell":
        activity["commerce"]["ventes"].append({
            "horodatage": event.get("timestamp"),
            "commodity": event.get("Type_Localised", event.get("Type", "?")),
            "market_id": current_station.get("market_id"),
            "station": current_station.get("station"),
            "systeme": current_station.get("systeme"),
            "quantite": event.get("Count", 0),
            "prix_unitaire": event.get("SellPrice", 0),
            "valeur_totale": event.get("TotalSale", 0),
        })
    elif etype == "Bounty":
        activity["combat"]["primes"] += 1
        activity["combat"]["recompenses"] += event.get("TotalReward", event.get("Reward", 0)) or 0
    elif etype == "MiningRefined":
        name = event.get("Type_Localised", event.get("Type", "?"))
        activity["minage"]["materiaux"][name] = activity["minage"]["materiaux"].get(name, 0) + 1
    elif etype == "FSSSignalDiscovered":
        activity["exploration"]["signaux_detectes"] += 1
    # tout autre événement (y compris inconnu) est ignoré proprement : non couvert par cette phase


def _make_step_entry(event: dict, preceding_activity: dict, current_system: str | None) -> dict:
    etype = event.get("event")
    return {
        "horodatage": event.get("timestamp"),
        "type": _STEP_EVENTS.get(etype, etype),
        # Undocked ne porte pas StarSystem dans le journal : on reporte le dernier système connu.
        "systeme": event.get("StarSystem") or event.get("System") or current_system,
        "station": event.get("StationName") if etype in ("Docked", "Undocked") else None,
        "resume_depuis_etape_precedente": (
            preceding_activity if _activity_has_content(preceding_activity) else None
        ),
    }


def collect(max_entries: int | None = None) -> dict:
    """Construit le journal de bord chronologique. `max_entries` limite le
    nombre d'étapes renvoyées (les plus récentes) ; None = tout l'historique
    disponible dans les fichiers journal présents sur le disque."""
    journal_dir = journal.default_journal_dir()
    files = journal.list_journal_files(journal_dir)

    entries: list[dict] = []
    activity = _empty_activity()
    current_system: str | None = None
    # Rempli sur Docked, conservé tel quel après Undocked (les transactions ne
    # peuvent survenir qu'amarré, donc rester "collé" à la dernière station ne
    # produit jamais de fausse association).
    current_station: dict = {"market_id": None, "station": None, "systeme": None}

    for event in journal.iter_journal_events(files):
        etype = event.get("event")
        if etype in ("FSDJump", "CarrierJump"):
            current_system = event.get("StarSystem") or current_system
        if etype == "Docked":
            current_station = {
                "market_id": event.get("MarketID"),
                "station": event.get("StationName"),
                "systeme": event.get("StarSystem") or current_system,
            }
        if etype in _STEP_EVENTS:
            entries.append(_make_step_entry(event, activity, current_system))
            activity = _empty_activity()
        else:
            _apply_activity_event(activity, event, current_station)

    if max_entries is not None:
        entries = entries[-max_entries:]

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "journal_dir": str(journal_dir),
        "fichiers_lus": [f.name for f in files],
        "etapes": entries,
    }


if __name__ == "__main__":
    import json
    import sys

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    print(json.dumps(collect(max_entries=limit), indent=2, ensure_ascii=False))
