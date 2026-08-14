"""
Module 1 — Données du commander.

Priorité à la CAPI (/profile, /shipyard, /fleetcarrier) si un token valide
est disponible ; sinon repli sur les fichiers locaux d'état (Status.json,
Cargo.json, ShipLocker.json), qui ne couvrent qu'une partie des catégories
(pas de fleet carrier, identité limitée : ces fichiers ne contiennent pas le
nom du commander ni ses rangs).
"""

from datetime import datetime, timezone

from sources import capi, journal

_EMPTY_RESULT = {
    "identite": {"nom": None, "rangs": None},
    "finances": {"credits": None, "dette": None},
    "vaisseau_actuel": {
        "nom": None, "type": None, "valeur": None, "sante": None, "modules": None,
    },
    "flotte": [],
    "cargaison": [],
    "materiaux_inventaire": {"items": [], "components": [], "consumables": [], "data": []},
    "fleet_carrier": None,
}


def _from_capi(access_token: str, host: str) -> dict:
    profile = capi.get_profile(access_token, host)
    commander = profile.get("commander", {})
    ship = profile.get("ship", {})
    ships = profile.get("ships", {})

    result = {
        "identite": {
            "nom": commander.get("name"),
            "rangs": commander.get("rank"),
        },
        "finances": {
            "credits": commander.get("credits"),
            "dette": commander.get("debt"),
        },
        "vaisseau_actuel": {
            "nom": ship.get("shipName") or ship.get("name"),
            "type": ship.get("shipType") or ship.get("name"),
            "valeur": ship.get("value"),
            "sante": ship.get("health"),
            "modules": sorted(ship.get("modules", {}).keys()) if isinstance(ship.get("modules"), dict) else None,
        },
        "flotte": [
            {"shipId": ship_id, "type": info.get("name"), "nom": info.get("shipName")}
            for ship_id, info in (ships.items() if isinstance(ships, dict) else [])
        ],
        "cargaison": ship.get("cargo", []),
        "materiaux_inventaire": _EMPTY_RESULT["materiaux_inventaire"],
        "fleet_carrier": None,
    }

    try:
        carrier = capi.get_fleetcarrier(access_token, host)
        result["fleet_carrier"] = {
            "nom": carrier.get("name", {}).get("vanityName") if isinstance(carrier.get("name"), dict) else None,
            "callsign": carrier.get("name", {}).get("callsign") if isinstance(carrier.get("name"), dict) else None,
            "position": carrier.get("currentStarSystem"),
            "solde": carrier.get("finance", {}).get("cash"),
            "carburant": carrier.get("fuel"),
            "capacite": carrier.get("capacity"),
            "commandes": carrier.get("orders"),
            "taxation": carrier.get("finance", {}).get("taxRate"),
            "equipage": carrier.get("crew"),
        }
    except Exception:
        pass  # fleet carrier optionnel : absence de carrier possédé, ou endpoint indisponible

    return result


def _group_shiplocker_items(shiplocker: dict) -> dict:
    def summarize(items: list) -> list:
        return [
            {"nom": i.get("Name_Localised", i.get("Name")), "quantite": i.get("Count")}
            for i in items
        ]

    return {
        "items": summarize(shiplocker.get("Items", [])),
        "components": summarize(shiplocker.get("Components", [])),
        "consumables": summarize(shiplocker.get("Consumables", [])),
        "data": summarize(shiplocker.get("Data", [])),
    }


def _from_local() -> dict:
    journal_dir = journal.default_journal_dir()
    status = journal.read_status(journal_dir)
    cargo = journal.read_cargo(journal_dir)
    shiplocker = journal.read_shiplocker(journal_dir)

    result = {k: v for k, v in _EMPTY_RESULT.items()}
    result["identite"] = dict(_EMPTY_RESULT["identite"])
    result["finances"] = dict(_EMPTY_RESULT["finances"])
    result["vaisseau_actuel"] = dict(_EMPTY_RESULT["vaisseau_actuel"])

    if status:
        result["vaisseau_actuel"]["sante"] = status.get("Flags")
        if "Balance" in status:
            result["finances"]["credits"] = status.get("Balance")

    if cargo:
        result["cargaison"] = [
            {"nom": i.get("Name_Localised", i.get("Name")), "quantite": i.get("Count")}
            for i in cargo.get("Inventory", [])
        ]

    if shiplocker:
        result["materiaux_inventaire"] = _group_shiplocker_items(shiplocker)

    return result


def collect() -> dict:
    result: dict = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": None,
        "errors": [],
    }

    try:
        config = capi.load_config()
        token = capi.load_token()
        if token is None:
            raise capi.CapiNotConfigured("Aucun token CAPI enregistré (.capi_token.json absent)")
        host = capi.host_for_environment(config.get("environment", "live"))
        result.update(_from_capi(token["access_token"], host))
        result["source"] = "capi"
        return result
    except Exception as e:
        result["errors"].append(f"capi indisponible, repli local : {e}")

    try:
        result.update(_from_local())
        result["source"] = "local"
    except Exception as e:
        result["errors"].append(f"lecture locale indisponible : {e}")
        result.update(_EMPTY_RESULT)
        result["source"] = "none"

    return result


if __name__ == "__main__":
    import json

    print(json.dumps(collect(), indent=2, ensure_ascii=False))
