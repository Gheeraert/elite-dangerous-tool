"""
Source locale : fichiers journal du jeu et fichiers d'état.

Dossier par défaut (Windows) :
  %USERPROFILE%\\Saved Games\\Frontier Developments\\Elite Dangerous\\

Points de vigilance :
  - Status.json, Cargo.json, ShipLocker.json sont réécrits en continu par le jeu
    (pas des logs append-only) : on les relit à chaque appel.
  - Journal.*.log s'appendent ligne par ligne (un objet JSON par ligne).
    Une session de jeu peut être coupée sur plusieurs fichiers successifs.
  - Un événement inconnu ou une ligne mal formée ne doit jamais faire planter
    le parsing : on l'ignore silencieusement.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Iterator


def default_journal_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return home / "Saved Games" / "Frontier Developments" / "Elite Dangerous"


def _read_json_file(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_status(journal_dir: Path) -> dict | None:
    return _read_json_file(journal_dir / "Status.json")


def read_cargo(journal_dir: Path) -> dict | None:
    return _read_json_file(journal_dir / "Cargo.json")


def read_shiplocker(journal_dir: Path) -> dict | None:
    return _read_json_file(journal_dir / "ShipLocker.json")


def list_journal_files(journal_dir: Path) -> list[Path]:
    """Fichiers Journal.*.log triés chronologiquement (le nom de fichier encode
    l'horodatage de démarrage de session, donc un tri lexicographique suffit)."""
    if not journal_dir.is_dir():
        return []
    return sorted(journal_dir.glob("Journal.*.log"))


def latest_journal_file(journal_dir: Path) -> Path | None:
    files = list_journal_files(journal_dir)
    return files[-1] if files else None


def watch_for_new_events(
    journal_dir: Path, poll_interval: float = 5.0, stop_event: threading.Event | None = None
) -> Iterator[Path]:
    """Génère le fichier journal actif chaque fois qu'il a grossi depuis la
    dernière vérification — signe qu'un nouvel événement de jeu vient d'être
    écrit (le jeu réécrit Journal.*.log en append-only, jamais en place).

    Poll simple (taille de fichier toutes les `poll_interval` secondes)
    plutôt que `watchdog` : pas de nouvelle dépendance, cohérent avec la
    sobriété du projet, et la fréquence d'écriture réelle (au mieux
    quelques événements par minute en jeu) ne justifie pas une lib de
    notification filesystem. Si ça devait s'avérer insuffisant en pratique
    (latence perçue trop grande), c'est le paramètre à ajuster en premier
    avant d'envisager watchdog.

    S'arrête proprement dès que `stop_event` est déclenché (permet un Ctrl+C
    réactif depuis storage/loop.py) ; sans `stop_event`, boucle indéfiniment."""
    last_path: Path | None = None
    last_size: int | None = None
    while stop_event is None or not stop_event.is_set():
        current = latest_journal_file(journal_dir)
        size = None
        if current is not None:
            try:
                size = current.stat().st_size
            except OSError:
                current = None

        if current is not None:
            if last_path is not None and (current != last_path or size != last_size):
                yield current
            last_path, last_size = current, size

        if stop_event is not None:
            if stop_event.wait(poll_interval):
                break
        else:
            time.sleep(poll_interval)


def iter_journal_events(files: list[Path]) -> Iterator[dict]:
    """Parcourt les événements de plusieurs fichiers journal, dans l'ordre.
    Une ligne illisible est ignorée proprement plutôt que de faire planter le parsing."""
    for path in files:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def latest_position(journal_dir: Path) -> dict | None:
    """Position stellaire la plus récente connue du commander, d'après le
    dernier événement portant un `StarPos` (FSDJump, CarrierJump, Location —
    ce dernier écrit notamment à la connexion/respawn). Coordonnées en
    années-lumière, telles que fournies par le jeu. None si rien trouvé
    (aucun journal, ou aucun de ces événements dedans)."""
    latest: dict | None = None
    for event in iter_journal_events(list_journal_files(journal_dir)):
        if event.get("event") in ("FSDJump", "CarrierJump", "Location") and "StarPos" in event:
            latest = {
                "system": event.get("StarSystem"),
                "coords": event.get("StarPos"),
                "timestamp": event.get("timestamp"),
            }
    return latest
