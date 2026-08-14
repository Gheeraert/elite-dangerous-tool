"""
Source Frontier Companion API (CAPI) : profil du commander, chantier naval,
fleet carrier. Authentifiée via OAuth2.

État de cette phase
--------------------
Le squelette ci-dessous couvre : constantes des hosts/endpoints, chargement
de config, appel des endpoints une fois un token valide obtenu, et
rafraîchissement de token. CE QUI RESTE À FINALISER :

  - `run_authorization_flow()` : le flux interactif complet (ouvrir le
    navigateur sur AUTH_URL, faire écouter `redirect_uri` en local pour
    récupérer le `code`, gérer PKCE/state) n'est pas implémenté. Aujourd'hui
    `exchange_code_for_token()` suppose que le `code` a déjà été obtenu
    manuellement.
  - Persistance du token (accès + refresh) sur disque : le format attendu est
    documenté dans `save_token`/`load_token`, mais aucun chiffrement n'est
    fait — le fichier token est exclu du dépôt via .gitignore, à l'utilisateur
    de le protéger sur son poste.
  - Rafraîchissement automatique en tâche de fond avant expiration : non fait,
    seule une fonction `refresh_access_token()` ponctuelle est fournie.

Points de vigilance (déjà vérifiés) :
  - Host Live    : https://companion.orerve.net
  - Host Legacy  : https://legacy-companion.orerve.net
  - Scope OAuth2 obligatoire : "auth capi" (le scope "capi" seul -> 401).
  - Ne pas dépasser environ 1 requête/minute en usage normal.
"""

import json
import tomllib
from pathlib import Path

import requests

AUTH_URL = "https://auth.frontierstore.net/auth"
TOKEN_URL = "https://auth.frontierstore.net/token"

CAPI_HOST_LIVE = "https://companion.orerve.net"
CAPI_HOST_LEGACY = "https://legacy-companion.orerve.net"

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"
TOKEN_PATH = Path(__file__).resolve().parent.parent / ".capi_token.json"


class CapiNotConfigured(Exception):
    """Levée quand config.toml ou le token CAPI sont absents/incomplets."""


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        raise CapiNotConfigured(f"Fichier de config introuvable : {CONFIG_PATH}")
    with CONFIG_PATH.open("rb") as f:
        config = tomllib.load(f)
    capi_config = config.get("capi", {})
    if not capi_config.get("client_id"):
        raise CapiNotConfigured("Section [capi] incomplète dans config.toml (client_id manquant)")
    return capi_config


def host_for_environment(environment: str) -> str:
    return CAPI_HOST_LEGACY if environment == "legacy" else CAPI_HOST_LIVE


def build_authorization_url(client_id: str, redirect_uri: str, scope: str, state: str) -> str:
    """Construit l'URL vers laquelle rediriger l'utilisateur pour autoriser l'application.
    L'ouverture du navigateur et la capture du `code` de retour restent à implémenter
    (voir run_authorization_flow)."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{AUTH_URL}?{query}"


def run_authorization_flow(config: dict) -> dict:
    """TODO (non implémenté) : orchestrer le flux interactif complet —
    ouvrir le navigateur, écouter localement sur redirect_uri, récupérer le
    `code`, appeler exchange_code_for_token(). Lever explicitement pour
    signaler que ce chemin n'est pas encore utilisable automatiquement."""
    raise NotImplementedError(
        "Le flux d'autorisation interactif CAPI n'est pas encore implémenté. "
        "Voir sources/capi.py pour l'état d'avancement."
    )


def exchange_code_for_token(config: dict, code: str) -> dict:
    """Échange un code d'autorisation contre un token d'accès + refresh token."""
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def refresh_access_token(config: dict, refresh_token: str) -> dict:
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config["client_id"],
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def save_token(token: dict) -> None:
    """Sérialise le token (dict avec au moins access_token/refresh_token/expires_in)
    sur disque. TOKEN_PATH est exclu du dépôt via .gitignore."""
    with TOKEN_PATH.open("w", encoding="utf-8") as f:
        json.dump(token, f)


def load_token() -> dict | None:
    if not TOKEN_PATH.is_file():
        return None
    with TOKEN_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _get(endpoint: str, access_token: str, host: str) -> dict:
    r = requests.get(
        f"{host}{endpoint}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def get_profile(access_token: str, host: str = CAPI_HOST_LIVE) -> dict:
    return _get("/profile", access_token, host)


def get_shipyard(access_token: str, host: str = CAPI_HOST_LIVE) -> dict:
    return _get("/shipyard", access_token, host)


def get_fleetcarrier(access_token: str, host: str = CAPI_HOST_LIVE) -> dict:
    return _get("/fleetcarrier", access_token, host)
