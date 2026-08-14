"""
Onglet Commander : identité, rangs, finances, vaisseau actuel, résumé de
flotte, fleet carrier — à partir de la dernière ligne `collections` où
module = 'commander'. Lecture seule au chargement ; le bouton « Actualiser
maintenant » est la seule action qui écrit (storage.collector.record_commander).
"""

import tkinter as tk
from tkinter import ttk

from dashboard import data
from storage import collector, materializer

_NO_DATA_MSG = (
    "Aucune collecte 'commander' en base pour l'instant.\n\n"
    "Lancez storage/loop.py (ou storage/collector.py) au moins une fois, "
    "ou cliquez sur « Actualiser maintenant » ci-dessous."
)


def _format_credits(value) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:,.0f}".replace(",", " ")


def _format_ranks(ranks) -> str:
    if not isinstance(ranks, dict) or not ranks:
        return "n/a"
    return "   ".join(f"{k} : {v}" for k, v in ranks.items())


def _format_health(sante) -> str:
    if isinstance(sante, dict):
        hull = sante.get("hull")
        shield = sante.get("shield")
        parts = []
        if hull is not None:
            parts.append(f"coque {hull}")
        if shield is not None:
            parts.append(f"bouclier {shield}")
        return "   ".join(parts) if parts else "n/a"
    if sante is None:
        return "n/a"
    return f"indicateurs bruts (Flags) : {sante}"  # repli local : Status.json n'a pas de santé détaillée


def build(parent: ttk.Frame, conn) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=10)

    status_var = tk.StringVar()
    ttk.Label(frame, textvariable=status_var, foreground="#666").grid(column=0, row=0, sticky="w", pady=(0, 8))

    content = ttk.Frame(frame)
    content.grid(column=0, row=1, sticky="nsew")

    ttk.Button(frame, text="Actualiser maintenant", command=lambda: _refresh(conn, status_var, content)).grid(
        column=0, row=2, sticky="w", pady=(10, 0)
    )

    frame.rowconfigure(1, weight=1)
    frame.columnconfigure(0, weight=1)

    _render(conn, status_var, content)
    return frame


def _refresh(conn, status_var: tk.StringVar, content: ttk.Frame) -> None:
    status_var.set("Actualisation en cours (appel CAPI ou fichiers locaux)…")
    content.update_idletasks()
    try:
        collector.record_commander(conn)
        materializer.materialize(conn)  # garde les tables dérivées à jour, comme storage/loop.py
    except Exception as e:
        status_var.set(f"Échec de l'actualisation : {e}")
        return
    _render(conn, status_var, content)


def _render(conn, status_var: tk.StringVar, content: ttk.Frame) -> None:
    for child in content.winfo_children():
        child.destroy()

    payload = data.get_latest_collection(conn, "commander")
    if payload is None:
        status_var.set("")
        ttk.Label(content, text=_NO_DATA_MSG, justify="left").grid(column=0, row=0, sticky="w")
        return

    status_var.set(f"Dernière collecte : {payload.get('collected_at', '?')}  (source : {payload.get('source', '?')})")

    row = 0

    def section(title: str) -> None:
        nonlocal row
        ttk.Label(content, text=title, font=("", 10, "bold")).grid(column=0, row=row, sticky="w", pady=(8, 2))
        row += 1

    def field(label: str, value: str) -> None:
        nonlocal row
        ttk.Label(content, text=label + " :").grid(column=0, row=row, sticky="w", padx=(10, 6))
        ttk.Label(content, text=value).grid(column=1, row=row, sticky="w")
        row += 1

    identite = payload.get("identite", {})
    section("Identité")
    field("Nom", identite.get("nom") or "n/a")
    field("Rangs", _format_ranks(identite.get("rangs")))

    finances = payload.get("finances", {})
    section("Finances")
    field("Crédits", _format_credits(finances.get("credits")))
    field("Dette", _format_credits(finances.get("dette")))

    vaisseau = payload.get("vaisseau_actuel", {})
    section("Vaisseau actuel")
    field("Nom", vaisseau.get("nom") or "n/a")
    field("Type", vaisseau.get("type") or "n/a")
    valeur = vaisseau.get("valeur")
    field("Valeur totale", _format_credits(valeur.get("total")) if isinstance(valeur, dict) else "n/a")
    field("Santé", _format_health(vaisseau.get("sante")))

    flotte = payload.get("flotte") or []
    section(f"Flotte ({len(flotte)} vaisseau(x))")
    if flotte:
        tree = ttk.Treeview(content, columns=("type", "nom"), show="headings", height=min(6, len(flotte)))
        tree.heading("type", text="Type")
        tree.heading("nom", text="Nom")
        for ship in flotte:
            tree.insert("", "end", values=(ship.get("type") or "?", ship.get("nom") or "—"))
        tree.grid(column=0, row=row, columnspan=2, sticky="w", padx=(10, 0))
        row += 1
    else:
        field("", "aucun vaisseau listé")

    carrier = payload.get("fleet_carrier")
    section("Fleet carrier")
    if carrier is None:
        field("", "pas de fleet carrier associé à ce compte")
    else:
        field("Nom", carrier.get("nom") or "n/a")
        field("Callsign", carrier.get("callsign") or "n/a")
        field("Position", carrier.get("position") or "n/a")
        field("Solde", _format_credits(carrier.get("solde")))
        field("Carburant", str(carrier.get("carburant")) if carrier.get("carburant") is not None else "n/a")
        field("Taxation", str(carrier.get("taxation")) if carrier.get("taxation") is not None else "n/a")
        capacite = carrier.get("capacite")
        if isinstance(capacite, dict) and capacite.get("freeSpace") is not None:
            field("Capacité libre", str(capacite["freeSpace"]))
