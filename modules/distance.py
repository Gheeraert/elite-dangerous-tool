"""
Module 4 — Distance à un système donné.

Répond à une question posée à la volée : « à combien d'années-lumière suis-je
du système X ? ». Combine la position actuelle du commander (dernier
FSDJump/CarrierJump/Location du journal local, sources.journal) et les
coordonnées du système cible (EDSM, sources.edsm) pour calculer la distance
(sources.navigation). Arrondie à l'entier le plus proche.
"""

from datetime import datetime, timezone

from sources import edsm, journal, navigation


def collect(target_system: str) -> dict:
    result: dict = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "origine": None,
        "cible": {"requested": target_system, "system": None, "coords": None},
        "distance_ly": None,
        "errors": [],
    }

    position = journal.latest_position(journal.default_journal_dir())
    if position is None:
        result["errors"].append(
            "Position actuelle introuvable dans le journal local "
            "(aucun FSDJump/CarrierJump/Location trouvé)."
        )
        return result
    result["origine"] = position

    try:
        target = edsm.get_system_coordinates(target_system)
    except Exception as e:
        result["errors"].append(f"edsm.get_system_coordinates: {e}")
        return result

    if target is None:
        result["errors"].append(f"Système introuvable sur EDSM : « {target_system} »")
        return result

    result["cible"] = {"requested": target_system, "system": target["system"], "coords": target["coords"]}
    result["distance_ly"] = navigation.distance_ly(position["coords"], target["coords"])
    return result


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        raise SystemExit("Usage : python -m modules.distance <système>")

    r = collect(" ".join(sys.argv[1:]))
    if r["errors"]:
        for err in r["errors"]:
            print(f"Erreur : {err}")
    else:
        print(
            f"{r['cible']['system']} est à {r['distance_ly']} années-lumière "
            f"de votre position actuelle ({r['origine']['system']})."
        )
