"""
Source communautaire EDSM : coordonnées galactiques d'un système, par nom.
Aucune clé requise, mais Cloudflare (devant edsm.net) renvoie 403 sans
User-Agent explicite — le User-Agent par défaut de `requests` est traité
comme un bot.

  https://www.edsm.net/en/api-v1
"""

import requests

SYSTEM_URL = "https://www.edsm.net/api-v1/system"
_HEADERS = {"User-Agent": "elite-dangerous-tool/1.0 (personal project)"}


def get_system_coordinates(system_name: str) -> dict | None:
    """Coordonnées `[x, y, z]` (années-lumière) d'un système par son nom
    exact. None si le système est introuvable (EDSM renvoie `[]` dans ce
    cas plutôt qu'une erreur HTTP)."""
    r = requests.get(
        SYSTEM_URL,
        params={"systemName": system_name, "showCoordinates": 1},
        headers=_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if not data or "coords" not in data:
        return None
    coords = data["coords"]
    return {
        "system": data.get("name", system_name),
        "coords": [coords["x"], coords["y"], coords["z"]],
    }
