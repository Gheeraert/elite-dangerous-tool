"""
Onglet Marché : commodité choisie par l'utilisateur (défaut :
[market].default_commodity de config.toml), meilleures stations
d'achat/vente d'après la dernière collecte marché en base pour cette
commodité — distance au commander incluse quand le champ est présent
(les collectes antérieures à son ajout ne l'ont pas : .get() partout,
jamais un accès direct qui suppose sa présence).
"""

import tkinter as tk
from tkinter import ttk

from dashboard import data
from storage import collector, materializer

_COLUMNS = [
    ("system", "Système", 150),
    ("station", "Station", 190),
    ("price", "Prix", 90),
    ("quantity", "Demande/Stock", 100),
    ("distance", "Distance (al)", 100),
    ("updated_at", "Mis à jour", 160),
]


def _fmt(value) -> str:
    return "n/a" if value is None else str(value)


def build(parent: ttk.Frame, conn) -> ttk.Frame:
    app_config = data.load_app_config()
    frame = ttk.Frame(parent, padding=10)

    controls = ttk.Frame(frame)
    controls.grid(column=0, row=0, sticky="w")
    ttk.Label(controls, text="Commodité :").grid(column=0, row=0, sticky="w")
    commodity_var = tk.StringVar(value=app_config["market_default_commodity"])
    entry = ttk.Entry(controls, textvariable=commodity_var, width=30)
    entry.grid(column=1, row=0, padx=(4, 10))

    status_var = tk.StringVar()
    ttk.Label(frame, textvariable=status_var, foreground="#666").grid(column=0, row=1, sticky="w", pady=(6, 8))

    content = ttk.Frame(frame)
    content.grid(column=0, row=2, sticky="nsew")
    frame.rowconfigure(2, weight=1)
    frame.columnconfigure(0, weight=1)

    def show_from_db() -> None:
        _render(conn, commodity_var.get().strip(), status_var, content)

    ttk.Button(controls, text="Afficher", command=show_from_db).grid(column=2, row=0)
    entry.bind("<Return>", lambda _e: show_from_db())

    buttons = ttk.Frame(frame)
    buttons.grid(column=0, row=3, sticky="w", pady=(10, 0))
    ttk.Button(
        buttons, text="Actualiser maintenant",
        command=lambda: _refresh(conn, commodity_var.get().strip(), app_config, status_var, content),
    ).grid(column=0, row=0)

    show_from_db()
    return frame


def _refresh(conn, commodity_name: str, app_config: dict, status_var: tk.StringVar, content: ttk.Frame) -> None:
    if not commodity_name:
        status_var.set("Entrez d'abord une commodité.")
        return
    status_var.set(f"Actualisation de « {commodity_name} » en cours (appel réseau)…")
    content.update_idletasks()
    try:
        collector.record_market(conn, commodity_name, app_config["market_default_station_count"])
        materializer.materialize(conn)  # garde les tables dérivées à jour, comme storage/loop.py
    except Exception as e:
        status_var.set(f"Échec de l'actualisation : {e}")
        return
    _render(conn, commodity_name, status_var, content)


def _render(conn, commodity_name: str, status_var: tk.StringVar, content: ttk.Frame) -> None:
    for child in content.winfo_children():
        child.destroy()

    if not commodity_name:
        status_var.set("Entrez une commodité puis cliquez sur « Afficher ».")
        return

    payload = data.get_latest_market_collection(conn, commodity_name)
    if payload is None:
        status_var.set("")
        ttk.Label(
            content,
            justify="left",
            text=(
                f"Aucune collecte marché en base pour « {commodity_name} ».\n\n"
                "Lancez storage/loop.py, ou cliquez sur « Actualiser maintenant »."
            ),
        ).grid(column=0, row=0, sticky="w")
        return

    tick = payload.get("tick", {}).get("time") or "n/a"
    status_var.set(
        f"Collecte du {payload.get('collected_at', '?')}  —  dernier tick BGS : {tick}  "
        f"—  résolu en : {payload.get('commodity', {}).get('resolved_name', '?')}"
    )

    ttk.Label(content, text="Meilleures stations pour VENDRE", font=("", 10, "bold")).grid(
        column=0, row=0, sticky="w"
    )
    _build_table(content, row=1, stations=payload.get("best_sell_stations") or [])

    ttk.Label(content, text="Meilleures stations pour ACHETER", font=("", 10, "bold")).grid(
        column=0, row=2, sticky="w", pady=(12, 0)
    )
    _build_table(content, row=3, stations=payload.get("best_buy_stations") or [])


def _build_table(content: ttk.Frame, row: int, stations: list[dict]) -> None:
    if not stations:
        ttk.Label(content, text="(aucune donnée fraîche)").grid(column=0, row=row, sticky="w")
        return

    columns = [c[0] for c in _COLUMNS]
    tree = ttk.Treeview(content, columns=columns, show="headings", height=min(8, len(stations)))
    for key, header, width in _COLUMNS:
        tree.heading(key, text=header)
        tree.column(key, width=width, anchor="center")

    for s in stations:
        quantity = s.get("demand") if s.get("demand") is not None else s.get("supply")
        tree.insert("", "end", values=(
            _fmt(s.get("system")),
            _fmt(s.get("station")),
            _fmt(s.get("price")),
            _fmt(quantity),
            _fmt(s.get("distance_from_commander_ly")),
            _fmt(s.get("updated_at")),
        ))
    tree.grid(column=0, row=row, sticky="w")
