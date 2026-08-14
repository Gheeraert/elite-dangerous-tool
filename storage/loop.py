"""
Boucle de collecte en fond de session : trois activités concurrentes qui
alimentent la base en continu, chacune avec sa propre logique de rythme et
sa propre connexion SQLite (storage/db.py active le mode WAL pour ça —
voir db.connect()) :

  - `market`    : à intervalle fixe (par défaut 20 min — les données Ardent
    viennent de contributions EDDN communautaires, pas d'un flux temps réel :
    interroger plus souvent n'apporte pas de fraîcheur supplémentaire et ne
    fait que solliciter l'API pour rien).
  - `commander` : à intervalle fixe plus large (par défaut 25 min), et
    uniquement si un token CAPI est disponible. Sans token,
    modules.commander.collect() retomberait sur les fichiers locaux (ça ne
    plante pas), mais ce sous-ensemble de données change lentement et est
    déjà couvert par le journal de bord : pas assez de valeur pour justifier
    un minuteur dédié, donc ce collecteur se désactive silencieusement
    plutôt que de tourner pour rien.
  - `logbook`   : réactif, pas périodique — surveille la taille du fichier
    journal actif via sources.journal.watch_for_new_events() (poll simple,
    voir la justification dans ce module) et relance une collecte dès qu'il
    grossit.

Chaque collecte réussie est immédiatement matérialisée (pas d'attente d'une
passe séparée). Chaque tick est protégé individuellement : une erreur
n'arrête jamais la boucle globale, juste affichée avec un horodatage.

Point de vigilance signalé plutôt que traité ici : modules.logbook.collect()
relit l'intégralité des fichiers journal à chaque appel. Sur une session
normale (fichiers de quelques Mo), c'est resté rapide en pratique — à
optimiser (lecture incrémentale) seulement si ça devient perceptible.
"""

import argparse
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from sources import capi, journal
from storage import collector, db, materializer

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.toml"

_DEFAULTS = {
    "market_interval_minutes": 20,
    "market_commodity": "Agronomic Treatment",
    "market_station_count": 15,
    "commander_interval_minutes": 25,
    "journal_poll_seconds": 5,
}


def _log(label: str, message: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {label:<10} {message}", flush=True)


def _load_loop_config() -> dict:
    """Fusionne les défauts avec config.toml si présent (les options CLI,
    appliquées après, ont toujours le dernier mot). Les intervalles viennent
    de `[loop]` ; la commodité/nombre de stations du collecteur marché
    réutilisent `[market]` (déjà présent dans config.example.toml pour
    d'autres usages futurs) plutôt que de dupliquer les mêmes réglages sous
    un nom différent dans `[loop]`."""
    values = dict(_DEFAULTS)
    if CONFIG_PATH.is_file():
        with CONFIG_PATH.open("rb") as f:
            config = tomllib.load(f)
        values.update(config.get("loop", {}))
        market_config = config.get("market", {})
        if market_config.get("default_commodity"):
            values["market_commodity"] = market_config["default_commodity"]
        if market_config.get("default_station_count"):
            values["market_station_count"] = market_config["default_station_count"]
    return values


def _commander_capi_available() -> bool:
    try:
        capi.load_config()
    except capi.CapiNotConfigured:
        return False
    return capi.load_token() is not None


def _run_periodic(
    label: str,
    interval_seconds: float,
    stop_event: threading.Event,
    record_fn,
) -> None:
    """Boucle générique : collecte immédiate, matérialisation immédiate,
    attente de `interval_seconds` (interruptible), on recommence. Chaque
    thread ouvre sa propre connexion et ne la partage jamais."""
    conn = db.connect()
    try:
        while not stop_event.is_set():
            try:
                collection_id = record_fn(conn)
                result = materializer.materialize(conn)
                _log(label, f"collecte #{collection_id} matérialisée ({result['processed']} ligne(s))")
                for err in result["errors"]:
                    _log(label, f"avertissement matérialisation : {err}")
            except Exception as e:
                _log(label, f"erreur ignorée, la boucle continue : {e}")

            stop_event.wait(interval_seconds)
    finally:
        conn.close()


def _run_journal_watch(
    journal_dir: Path,
    poll_interval: float,
    stop_event: threading.Event,
) -> None:
    label = "logbook"
    conn = db.connect()

    def _tick(reason: str) -> None:
        try:
            collection_id = collector.record_logbook(conn)
            result = materializer.materialize(conn)
            _log(label, f"{reason} -> collecte #{collection_id} matérialisée ({result['processed']} ligne(s))")
            for err in result["errors"]:
                _log(label, f"avertissement matérialisation : {err}")
        except Exception as e:
            _log(label, f"erreur ignorée, la boucle continue : {e}")

    try:
        _tick("collecte initiale")
        for _changed_file in journal.watch_for_new_events(journal_dir, poll_interval, stop_event):
            if stop_event.is_set():
                break
            _tick("nouvel événement détecté")
    finally:
        conn.close()


def run(
    market_interval_minutes: float = _DEFAULTS["market_interval_minutes"],
    market_commodity: str = _DEFAULTS["market_commodity"],
    market_station_count: int = _DEFAULTS["market_station_count"],
    commander_interval_minutes: float = _DEFAULTS["commander_interval_minutes"],
    journal_poll_seconds: float = _DEFAULTS["journal_poll_seconds"],
    enable_market: bool = True,
    enable_commander: bool = True,
    enable_journal: bool = True,
) -> None:
    # Assure la création du schéma + le passage en mode WAL une seule fois,
    # avant que les threads n'ouvrent chacun leur propre connexion : sur une
    # base toute neuve, deux connexions concurrentes déclenchant `PRAGMA
    # journal_mode = WAL` au même instant peuvent se heurter en
    # "database is locked" (observé en test).
    db.connect().close()

    stop_event = threading.Event()
    threads: list[threading.Thread] = []

    if enable_market:
        threads.append(threading.Thread(
            name="market-loop",
            target=_run_periodic,
            args=(
                "market",
                market_interval_minutes * 60,
                stop_event,
                lambda conn: collector.record_market(conn, market_commodity, market_station_count),
            ),
            daemon=True,
        ))

    if enable_commander:
        if _commander_capi_available():
            threads.append(threading.Thread(
                name="commander-loop",
                target=_run_periodic,
                args=("commander", commander_interval_minutes * 60, stop_event, collector.record_commander),
                daemon=True,
            ))
        else:
            _log("commander", "aucun token CAPI disponible : collecteur désactivé (voir sources/capi.py authorize)")

    if enable_journal:
        threads.append(threading.Thread(
            name="logbook-watch",
            target=_run_journal_watch,
            args=(journal.default_journal_dir(), journal_poll_seconds, stop_event),
            daemon=True,
        ))

    if not threads:
        _log("loop", "rien à faire : tous les collecteurs sont désactivés.")
        return

    for t in threads:
        t.start()
    _log("loop", f"démarrée avec {len(threads)} activité(s) : {', '.join(t.name for t in threads)}. Ctrl+C pour arrêter.")

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        _log("loop", "arrêt demandé, attente de la fin des collectes en cours...")
        stop_event.set()
        for t in threads:
            t.join(timeout=30)
        _log("loop", "arrêtée proprement.")


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # évite le mojibake sur les consoles Windows non-UTF8

    parser = argparse.ArgumentParser(description="Boucle de collecte en fond, à lancer pendant une session de jeu.")
    cfg = _load_loop_config()
    parser.add_argument("--market-interval", type=float, default=cfg["market_interval_minutes"],
                         help=f"Intervalle marché en minutes (défaut config : {cfg['market_interval_minutes']})")
    parser.add_argument("--market-commodity", type=str, default=cfg["market_commodity"],
                         help=f"Commodité suivie par le collecteur marché (défaut : {cfg['market_commodity']})")
    parser.add_argument("--market-stations", type=int, default=cfg["market_station_count"],
                         help=f"Nombre de stations par sens (défaut : {cfg['market_station_count']})")
    parser.add_argument("--commander-interval", type=float, default=cfg["commander_interval_minutes"],
                         help=f"Intervalle commander en minutes (défaut config : {cfg['commander_interval_minutes']})")
    parser.add_argument("--journal-poll-seconds", type=float, default=cfg["journal_poll_seconds"],
                         help=f"Fréquence de sondage du journal actif (défaut : {cfg['journal_poll_seconds']}s)")
    parser.add_argument("--no-market", action="store_true", help="Désactive le collecteur marché")
    parser.add_argument("--no-commander", action="store_true", help="Désactive le collecteur commander (même si un token CAPI existe)")
    parser.add_argument("--no-journal", action="store_true", help="Désactive la surveillance du journal de bord")
    args = parser.parse_args()

    run(
        market_interval_minutes=args.market_interval,
        market_commodity=args.market_commodity,
        market_station_count=args.market_stations,
        commander_interval_minutes=args.commander_interval,
        journal_poll_seconds=args.journal_poll_seconds,
        enable_market=not args.no_market,
        enable_commander=not args.no_commander,
        enable_journal=not args.no_journal,
    )
