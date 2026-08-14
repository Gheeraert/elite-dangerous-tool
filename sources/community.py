"""
Source communautaire : tick BGS (EDCD TickDetector) et prix par commodité
(projet Ardent, alimenté par EDDN). Aucune clé API, aucune authentification.

  Tick : https://tick.edcd.io/api/tick
  Prix : https://api.ardent-insight.com/v2/...
"""

import csv
import io
import re
from datetime import datetime, timedelta, timezone

import requests

TICK_URL = "https://tick.edcd.io/api/tick"
COMMODITIES_URL = "https://api.ardent-insight.com/v2/commodities"
IMPORTS_URL_TMPL = "https://api.ardent-insight.com/v2/commodity/name/{name}/imports"
EXPORTS_URL_TMPL = "https://api.ardent-insight.com/v2/commodity/name/{name}/exports"
# Référentiel EDCD : donne les noms lisibles ("Agronomic Treatment") associés
# aux commodités, pour habiller les slugs bruts renvoyés par Ardent.
FDEVIDS_COMMODITY_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv"

_commodity_index: dict[str, str] = {}  # nom normalisé -> commodityName réel (cache module)


def normalize(s: str) -> str:
    """Réduit un nom à ses seuls caractères alphanumériques, en minuscules."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def first_present(entry: dict, *keys: str):
    """Retourne la première valeur non nulle parmi `keys` (0 et 0.0 sont valides,
    contrairement à un simple enchaînement de `or` qui les traiterait comme absentes)."""
    for key in keys:
        value = entry.get(key)
        if value is not None:
            return value
    return "?"


def fetch_tick() -> datetime | None:
    """Renvoie l'horodatage du dernier tick BGS, ou None si indisponible."""
    r = requests.get(TICK_URL, timeout=10)
    r.raise_for_status()
    iso = r.json()  # ex. "2026-08-11T17:04:17+00:00"
    return datetime.fromisoformat(iso)


def _ensure_commodity_index() -> None:
    if _commodity_index:
        return
    r = requests.get(COMMODITIES_URL, timeout=20)
    r.raise_for_status()
    for entry in r.json():
        name = entry.get("commodityName", "")
        _commodity_index[normalize(name)] = name


def load_commodity_names() -> list[str]:
    """Liste triée des noms lisibles des commodités suivies par Ardent (ex. "Agronomic
    Treatment"), en les habillant via le référentiel EDCD quand un nom lisible existe."""
    _ensure_commodity_index()

    pretty_names: dict[str, str] = {}  # nom normalisé -> nom lisible EDCD
    try:
        r = requests.get(FDEVIDS_COMMODITY_URL, timeout=20)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            pretty_names[normalize(row["name"])] = row["name"]
    except Exception:
        pass  # tant pis : on retombe sur les slugs bruts d'Ardent

    display_names = [
        pretty_names.get(norm_name, slug) for norm_name, slug in _commodity_index.items()
    ]
    display_names.sort()
    return display_names


def resolve_commodity(human_name: str) -> str:
    """Convertit un nom lisible ('Agronomic Treatments') vers le nom technique
    utilisé par Ardent ('agronomictreatment'), en tolérant singulier/pluriel."""
    target = normalize(human_name)
    _ensure_commodity_index()
    if target in _commodity_index:
        return _commodity_index[target]
    if target.endswith("s") and target[:-1] in _commodity_index:
        return _commodity_index[target[:-1]]
    if (target + "s") in _commodity_index:
        return _commodity_index[target + "s"]
    raise ValueError(f"Commodité introuvable : « {human_name} »")


def fetch_best_sales(commodity_name: str) -> list[dict]:
    """"imports" Ardent = endroits qui achètent la commodité = endroits où LA VENDRE,
    triés par Ardent du prix le plus élevé au plus bas."""
    url = IMPORTS_URL_TMPL.format(name=commodity_name)
    r = requests.get(url, params={"minVolume": 1, "minPrice": 1}, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_best_purchases(commodity_name: str) -> list[dict]:
    """"exports" Ardent = endroits qui vendent la commodité = endroits où L'ACHETER,
    triés par Ardent du prix le plus bas au plus élevé."""
    url = EXPORTS_URL_TMPL.format(name=commodity_name)
    r = requests.get(url, params={"minVolume": 1, "minPrice": 1}, timeout=20)
    r.raise_for_status()
    return r.json()


def freshness_cutoff(tick_dt: datetime | None) -> datetime:
    """Horodatage en dessous duquel une donnée de marché est jugée trop vieille :
    le dernier tick s'il est connu, sinon un repli de 24h."""
    if tick_dt is not None:
        return tick_dt
    return datetime.now(timezone.utc) - timedelta(hours=24)


def filter_fresh(data: list[dict], cutoff: datetime) -> list[dict]:
    fresh = []
    for entry in data:
        raw = first_present(entry, "updatedAt", "timestamp")
        try:
            updated = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue  # horodatage manquant/illisible -> on ne peut pas garantir la fraîcheur
        if updated >= cutoff:
            fresh.append(entry)
    return fresh
