"""
Source Frontier Companion API (CAPI) : profil du commander, chantier naval,
fleet carrier. Authentifiée via OAuth2.

État de cette phase
--------------------
Le flux d'autorisation interactif (ouverture navigateur, serveur de callback
local, PKCE, vérification du state, échange du code) est implémenté dans
`run_authorization_flow()`. CE QUI RESTE À FINALISER :

  - Persistance du token (accès + refresh) sur disque : le format attendu est
    documenté dans `save_token`/`load_token`, mais aucun chiffrement n'est
    fait — le fichier token est exclu du dépôt via .gitignore, à l'utilisateur
    de le protéger sur son poste.
  - Rafraîchissement automatique en tâche de fond avant expiration : non fait,
    seule une fonction `refresh_access_token()` ponctuelle est fournie.

Utilisation en CLI :
    python -m sources.capi authorize   # ouvre le navigateur, capte le callback, sauvegarde le token
    python -m sources.capi test        # appelle /profile avec le token sauvegardé

Points de vigilance (déjà vérifiés) :
  - Host Live    : https://companion.orerve.net
  - Host Legacy  : https://legacy-companion.orerve.net
  - Scope OAuth2 obligatoire : "auth capi" (le scope "capi" seul -> 401).
  - Ne pas dépasser environ 1 requête/minute en usage normal.
"""

import base64
import datetime
import hashlib
import json
import secrets
import ssl
import time
import tomllib
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

AUTH_URL = "https://auth.frontierstore.net/auth"
TOKEN_URL = "https://auth.frontierstore.net/token"

CAPI_HOST_LIVE = "https://companion.orerve.net"
CAPI_HOST_LEGACY = "https://legacy-companion.orerve.net"

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"
TOKEN_PATH = Path(__file__).resolve().parent.parent / ".capi_token.json"
_DEV_CERT_PATH = Path(__file__).resolve().parent.parent / ".capi_dev_cert.pem"
_DEV_KEY_PATH = Path(__file__).resolve().parent.parent / ".capi_dev_key.pem"


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


def build_authorization_url(
    client_id: str, redirect_uri: str, scope: str, state: str, code_challenge: str | None = None
) -> str:
    """Construit l'URL vers laquelle rediriger l'utilisateur pour autoriser l'application."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    # quote_via=quote : espace encodé %20 (RFC 3986), et non "+" (convention
    # form-urlencoded par défaut d'urlencode) — plus conforme à OAuth2/RFC 6749.
    return f"{AUTH_URL}?{urlencode(params, quote_via=quote)}"


def _generate_pkce_pair() -> tuple[str, str]:
    """PKCE (RFC 7636) : nécessaire côté Frontier car ce type d'application (script
    local, sans backend confidentiel) ne peut pas garder client_secret secret de
    façon fiable — le challenge protège l'échange même si le `code` est intercepté."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _ensure_dev_cert(hostname: str) -> tuple[Path, Path]:
    """Certificat auto-signé pour le serveur de callback local, requis quand
    l'app Frontier impose un redirect_uri en https (le formulaire Frontier
    n'accepte pas toujours http://localhost). Régénéré si absent ; réutilisé
    sinon. Le navigateur affichera un avertissement de sécurité à accepter
    manuellement (normal pour un certificat auto-signé sur localhost) —
    cert et clé sont exclus du dépôt via .gitignore (*.pem)."""
    if _DEV_CERT_PATH.is_file() and _DEV_KEY_PATH.is_file():
        return _DEV_CERT_PATH, _DEV_KEY_PATH

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    _DEV_CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _DEV_KEY_PATH.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return _DEV_CERT_PATH, _DEV_KEY_PATH


def run_authorization_flow(config: dict, timeout: float = 300) -> dict:
    """Orchestre le flux interactif complet : ouvre le navigateur système vers
    Frontier, démarre un serveur HTTP local le temps de capter le callback sur
    redirect_uri, vérifie le `state` (protection CSRF), échange le `code` contre
    un token (PKCE) et le sauvegarde. Bloque jusqu'à réception du callback ou
    expiration de `timeout` (secondes)."""
    state = secrets.token_urlsafe(16)
    verifier, challenge = _generate_pkce_pair()
    scope = config.get("scope", "auth capi")
    auth_url = build_authorization_url(
        config["client_id"], config["redirect_uri"], scope, state, code_challenge=challenge
    )

    redirect = urlparse(config["redirect_uri"])
    callback_path = redirect.path or "/"
    received: dict = {}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            received["code"] = params.get("code", [None])[0]
            received["state"] = params.get("state", [None])[0]
            received["error"] = params.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = "Autorisation reçue, vous pouvez fermer cet onglet." if received.get("code") else "Autorisation refusée ou incomplète."
            self.wfile.write(f"<html><body>{message}</body></html>".encode("utf-8"))

        def log_message(self, format, *args):
            pass  # silence les logs HTTP par défaut sur stderr

    default_port = 443 if redirect.scheme == "https" else 80
    server = HTTPServer((redirect.hostname or "localhost", redirect.port or default_port), _CallbackHandler)
    if redirect.scheme == "https":
        cert_path, key_path = _ensure_dev_cert(redirect.hostname or "localhost")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print(
            "Certificat auto-signé local : le navigateur va afficher un avertissement "
            "de sécurité sur le callback localhost — c'est attendu, cliquez sur "
            "'Avancé' / 'Continuer vers localhost (dangereux)' pour poursuivre."
        )
    print(f"Ouverture du navigateur vers Frontier : {auth_url}")
    webbrowser.open(auth_url)
    # Boucle plutôt qu'un handle_request() unique : une requête parasite du
    # navigateur (favicon.ico, sonde TLS, etc.) ne doit pas consommer notre
    # unique chance de capter le vrai callback avant l'échéance globale.
    deadline = time.monotonic() + timeout
    while "code" not in received and "error" not in received:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        server.timeout = remaining
        server.handle_request()
    server.server_close()

    if received.get("error"):
        raise ValueError(f"Autorisation refusée par Frontier : {received['error']}")
    if received.get("state") != state:
        raise ValueError("state OAuth2 invalide : la réponse ne correspond pas à la requête envoyée (CSRF).")
    if not received.get("code"):
        raise ValueError("Aucun code d'autorisation reçu (timeout, ou callback jamais atteint).")

    token = exchange_code_for_token(config, received["code"], code_verifier=verifier)
    save_token(token)
    return token


def exchange_code_for_token(config: dict, code: str, code_verifier: str | None = None) -> dict:
    """Échange un code d'autorisation contre un token d'accès + refresh token."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    if config.get("client_secret"):
        data["client_secret"] = config["client_secret"]
    r = requests.post(TOKEN_URL, data=data, timeout=20)
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


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # évite le mojibake sur les consoles Windows non-UTF8
    action = sys.argv[1] if len(sys.argv) > 1 else None
    cfg = load_config()

    if action == "authorize":
        token = run_authorization_flow(cfg)
        # On n'affiche jamais access_token/refresh_token : uniquement des métadonnées.
        print(f"Token obtenu et enregistré dans {TOKEN_PATH}")
        print(f"scope: {token.get('scope')} | expires_in: {token.get('expires_in')}s")
    elif action == "test":
        saved = load_token()
        if saved is None:
            raise SystemExit("Aucun token enregistré. Lancez d'abord : python -m sources.capi authorize")
        host = host_for_environment(cfg.get("environment", "live"))
        profile = get_profile(saved["access_token"], host)
        commander = profile.get("commander", {})
        print("Connexion CAPI OK.")
        print(f"Commander : {commander.get('name')}")
        print(f"Crédits   : {commander.get('credits')}")
        print(f"Dette     : {commander.get('debt')}")
    else:
        print("Usage : python -m sources.capi authorize|test")
