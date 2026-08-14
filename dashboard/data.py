"""
Accès en lecture seule à la base pour l'interface (dashboard/). Aucun appel
réseau ici, aucune écriture — seulement de la lecture de ce que
storage/collector.py et storage/loop.py ont déjà déposé dans `collections`,
plus storage/reports.py pour l'onglet Rapport (réutilisé tel quel).

Les panneaux (dashboard/panels/*.py) sont les seuls à écrire, et seulement
sur action explicite de l'utilisateur (bouton « Actualiser maintenant »),
via storage.collector — jamais ce module.
"""

import json
import sqlite3
import tomllib
from pathlib import Path

from sources import community

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.toml"

_APP_DEFAULTS = {
    "market_default_commodity": "Agronomic Treatment",
    "market_default_station_count": 15,
}


def load_app_config() -> dict:
    """Quelques valeurs par défaut pour l'interface, tirées de config.toml
    quand présent (section [market], déjà utilisée par storage/loop.py)."""
    values = dict(_APP_DEFAULTS)
    if CONFIG_PATH.is_file():
        with CONFIG_PATH.open("rb") as f:
            config = tomllib.load(f)
        market_config = config.get("market", {})
        if market_config.get("default_commodity"):
            values["market_default_commodity"] = market_config["default_commodity"]
        if market_config.get("default_station_count"):
            values["market_default_station_count"] = market_config["default_station_count"]
    return values


def get_latest_collection(conn: sqlite3.Connection, module: str) -> dict | None:
    """Payload (dict) de la ligne la plus récente de `collections` pour ce
    module, ou None si aucune collecte n'a encore été faite."""
    row = conn.execute(
        "SELECT payload FROM collections WHERE module = ? ORDER BY id DESC LIMIT 1",
        (module,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def get_latest_market_collection(conn: sqlite3.Connection, commodity_name: str) -> dict | None:
    """Dernière collecte marché correspondant à `commodity_name`. Compare de
    façon normalisée (community.normalize) : le payload porte soit le nom
    lisible demandé à l'époque ("requested"), soit le slug Ardent
    ("resolved_name"), et l'utilisateur peut taper l'un ou l'autre."""
    target = community.normalize(commodity_name)
    rows = conn.execute(
        "SELECT payload FROM collections WHERE module = 'market' ORDER BY id DESC"
    ).fetchall()
    for (payload_json,) in rows:
        payload = json.loads(payload_json)
        commodity = payload.get("commodity", {})
        candidates = (commodity.get("requested"), commodity.get("resolved_name"))
        if any(c and community.normalize(c) == target for c in candidates):
            return payload
    return None
