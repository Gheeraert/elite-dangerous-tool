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
