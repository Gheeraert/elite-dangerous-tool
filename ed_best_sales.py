"""
Outil Elite Dangerous : dernier tick + meilleures stations pour vendre une commodité.

Sources de données (communautaires, sans clé API, sans authentification) :
  - Tick    : https://tick.edcd.io/api/tick            (EDCD TickDetector)
  - Prix    : https://api.ardent-insight.com/v2/...     (projet Ardent, alimenté par EDDN)

Dépendances : requests (pip install requests --break-system-packages)
tkinter est fourni avec Python (sous Linux : paquet python3-tk si absent).
"""

import csv
import io
import re
import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import messagebox, ttk

import requests

TICK_URL = "https://tick.edcd.io/api/tick"
COMMODITIES_URL = "https://api.ardent-insight.com/v2/commodities"
IMPORTS_URL_TMPL = "https://api.ardent-insight.com/v2/commodity/name/{name}/imports"
# Référentiel EDCD : donne les noms lisibles ("Agronomic Treatment") associés
# aux commodités, pour habiller les slugs bruts renvoyés par Ardent ("agronomictreatment").
FDEVIDS_COMMODITY_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv"


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


class EDTraderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Elite Dangerous — Meilleures ventes")
        self._commodity_index: dict[str, str] = {}  # nom normalisé -> commodityName réel
        self.tick_dt: datetime | None = None

        try:
            commodity_names = self.load_commodity_names()
        except Exception:
            commodity_names = []

        frm = ttk.Frame(root, padding=10)
        frm.grid()

        ttk.Label(frm, text="Commodité :").grid(column=0, row=0, sticky="w")
        default_commodity = "Agronomic Treatment" if "Agronomic Treatment" in commodity_names else (
            commodity_names[0] if commodity_names else ""
        )
        self.commodity_var = tk.StringVar(value=default_commodity)
        ttk.Combobox(
            frm,
            textvariable=self.commodity_var,
            values=commodity_names,
            state="readonly" if commodity_names else "normal",
            width=30,
        ).grid(column=1, row=0, pady=2)

        ttk.Label(frm, text="Nb de stations :").grid(column=0, row=1, sticky="w")
        self.n_var = tk.IntVar(value=15)
        ttk.Spinbox(frm, from_=5, to=20, textvariable=self.n_var, width=5).grid(
            column=1, row=1, sticky="w", pady=2
        )

        ttk.Button(frm, text="Rafraîchir", command=self.refresh).grid(
            column=0, row=2, columnspan=2, pady=6
        )

        self.tick_label = ttk.Label(frm, text="Dernier tick : —", font=("", 10, "bold"))
        self.tick_label.grid(column=0, row=3, columnspan=2, sticky="w", pady=(0, 10))

        columns = ("rank", "system", "station", "price", "demand", "pad", "distance", "maj")
        headers = {
            "rank": "#", "system": "Système", "station": "Station", "price": "Prix (Cr)",
            "demand": "Demande", "pad": "Piste", "distance": "Distance", "maj": "Mis à jour",
        }
        widths = {
            "rank": 30, "system": 150, "station": 190, "price": 90,
            "demand": 90, "pad": 55, "distance": 80, "maj": 130,
        }
        self.tree = ttk.Treeview(frm, columns=columns, show="headings", height=15)
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.grid(column=0, row=4, columnspan=2, pady=5)

        self.refresh()

    # -- Récupération des données -------------------------------------------------

    def fetch_tick(self) -> None:
        try:
            r = requests.get(TICK_URL, timeout=10)
            r.raise_for_status()
            iso = r.json()  # ex. "2026-08-11T17:04:17+00:00"
            self.tick_dt = datetime.fromisoformat(iso)
            self.tick_label.config(
                text=f"Dernier tick : {self.tick_dt.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        except Exception as e:
            self.tick_dt = None
            self.tick_label.config(text=f"Dernier tick : indisponible ({e})")

    def load_commodity_names(self) -> list[str]:
        """Liste triée des noms lisibles des commodités suivies par Ardent (ex. "Agronomic
        Treatment"), en les habillant via le référentiel EDCD quand un nom lisible existe."""
        if not self._commodity_index:
            r = requests.get(COMMODITIES_URL, timeout=20)
            r.raise_for_status()
            for entry in r.json():
                name = entry.get("commodityName", "")
                self._commodity_index[normalize(name)] = name

        pretty_names: dict[str, str] = {}  # nom normalisé -> nom lisible EDCD
        try:
            r = requests.get(FDEVIDS_COMMODITY_URL, timeout=20)
            r.raise_for_status()
            for row in csv.DictReader(io.StringIO(r.text)):
                pretty_names[normalize(row["name"])] = row["name"]
        except Exception:
            pass  # tant pis : on retombe sur les slugs bruts d'Ardent

        display_names = [
            pretty_names.get(norm_name, slug) for norm_name, slug in self._commodity_index.items()
        ]
        display_names.sort()
        return display_names

    def resolve_commodity(self, human_name: str) -> str:
        """Convertit un nom lisible ('Agronomic Treatments') vers le slug technique
        utilisé par Ardent ('agronomictreatment'), en tolérant singulier/pluriel."""
        target = normalize(human_name)
        if not self._commodity_index:
            r = requests.get(COMMODITIES_URL, timeout=20)
            r.raise_for_status()
            for entry in r.json():
                name = entry.get("commodityName", "")
                self._commodity_index[normalize(name)] = name
        if target in self._commodity_index:
            return self._commodity_index[target]
        if target.endswith("s") and target[:-1] in self._commodity_index:
            return self._commodity_index[target[:-1]]
        if (target + "s") in self._commodity_index:
            return self._commodity_index[target + "s"]
        raise ValueError(f"Commodité introuvable : « {human_name} »")

    def fetch_best_sales(self, commodity_slug: str) -> list[dict]:
        url = IMPORTS_URL_TMPL.format(name=commodity_slug)
        # "imports" = endroits qui achètent la commodité = endroits où LA VENDRE,
        # triés par Ardent du prix le plus élevé au plus bas.
        r = requests.get(url, params={"minVolume": 1, "minPrice": 1}, timeout=20)
        r.raise_for_status()
        return r.json()

    def freshness_cutoff(self) -> datetime:
        """Horodatage en dessous duquel une donnée de marché est jugée trop vieille :
        le dernier tick s'il est connu, sinon un repli de 24h."""
        if self.tick_dt is not None:
            return self.tick_dt
        return datetime.now(timezone.utc) - timedelta(hours=24)

    def filter_fresh(self, data: list[dict], cutoff: datetime) -> list[dict]:
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

    # -- Rafraîchissement de l'interface -------------------------------------------

    def refresh(self) -> None:
        self.fetch_tick()
        for row in self.tree.get_children():
            self.tree.delete(row)

        human_name = self.commodity_var.get().strip()
        try:
            slug = self.resolve_commodity(human_name)
        except Exception as e:
            messagebox.showerror("Commodité", str(e))
            return

        try:
            data = self.fetch_best_sales(slug)
        except Exception as e:
            messagebox.showerror("Erreur réseau", str(e))
            return

        data = self.filter_fresh(data, self.freshness_cutoff())[: self.n_var.get()]

        if not data:
            messagebox.showinfo(
                "Résultat",
                "Aucune donnée de marché fraîche (postérieure au dernier tick) pour cette commodité.",
            )
            return

        for i, entry in enumerate(data, start=1):
            system = first_present(entry, "systemName", "system")
            station = first_present(entry, "stationName", "station")
            price = first_present(entry, "sellPrice", "price", "buyPrice")
            demand = first_present(entry, "demand")
            pad = first_present(entry, "maxLandingPadSize", "padSize")
            distance = first_present(entry, "distanceToArrival", "distance")
            updated = first_present(entry, "updatedAt", "timestamp")
            self.tree.insert("", "end", values=(i, system, station, price, demand, pad, distance, updated))


if __name__ == "__main__":
    root = tk.Tk()
    EDTraderApp(root)
    root.mainloop()
