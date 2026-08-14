"""
Calcul de distance entre deux positions galactiques. Pas d'accès réseau ni
fichier ici — la position d'origine vient de sources.journal.latest_position,
celle d'une cible arbitraire de sources.edsm.get_system_coordinates ; ce
module ne fait que la géométrie entre les deux.
"""

import math


def distance_ly(coords_a: list[float], coords_b: list[float]) -> int:
    """Distance euclidienne en années-lumière entre deux coordonnées
    `[x, y, z]`, arrondie à l'entier le plus proche."""
    dx = coords_a[0] - coords_b[0]
    dy = coords_a[1] - coords_b[1]
    dz = coords_a[2] - coords_b[2]
    return round(math.sqrt(dx * dx + dy * dy + dz * dz))
