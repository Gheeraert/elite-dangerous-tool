"""
Onglet Rapport : storage.reports.profit_by_commodity(), réutilisée telle
quelle (aucune réimplémentation de la logique de comparaison marché ici).
Pas de collecteur dédié à « rapport » : le bouton relance seulement la
requête (utile si storage/loop.py a ajouté des données depuis l'ouverture
de l'onglet), il ne déclenche aucun appel réseau.
"""

import tkinter as tk
from tkinter import ttk

from storage import reports

_DEFAULT_DAYS = 30

_COLUMNS = [
    ("commodity", "Commodité", 160),
    ("achats", "Achats", 60),
    ("ventes", "Ventes", 60),
    ("qte_achetee", "Qté ach.", 80),
    ("qte_vendue", "Qté vendue", 80),
    ("depense", "Dépensé", 100),
    ("recu", "Reçu", 100),
    ("profit", "Profit réel", 100),
    ("ecart", "Écart marché", 100),
    ("ecart_pct", "Écart %", 80),
]


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.1f}".replace(",", " ")
    return f"{value:,}".replace(",", " ")


def build(parent: ttk.Frame, conn) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=10)

    controls = ttk.Frame(frame)
    controls.grid(column=0, row=0, sticky="w")
    ttk.Label(controls, text="Fenêtre (jours) :").grid(column=0, row=0, sticky="w")
    days_var = tk.IntVar(value=_DEFAULT_DAYS)
    ttk.Spinbox(controls, from_=1, to=3650, textvariable=days_var, width=6).grid(column=1, row=0, padx=(4, 10))

    status_var = tk.StringVar()
    content = ttk.Frame(frame)

    def refresh() -> None:
        _render(conn, days_var.get(), status_var, content)

    ttk.Button(controls, text="Actualiser", command=refresh).grid(column=2, row=0)

    ttk.Label(frame, textvariable=status_var, foreground="#666").grid(column=0, row=1, sticky="w", pady=(6, 8))
    content.grid(column=0, row=2, sticky="nsew")
    frame.rowconfigure(2, weight=1)
    frame.columnconfigure(0, weight=1)

    refresh()
    return frame


def _render(conn, days: int, status_var: tk.StringVar, content: ttk.Frame) -> None:
    for child in content.winfo_children():
        child.destroy()

    try:
        results = reports.profit_by_commodity(conn, days=days)
    except reports.ReportUnavailable as e:
        status_var.set("")
        ttk.Label(content, text=str(e), justify="left", wraplength=600).grid(column=0, row=0, sticky="w")
        return

    if not results:
        status_var.set(f"Aucune transaction dans les {days} derniers jours.")
        return

    status_var.set(f"{len(results)} commodité(s) avec au moins une transaction sur {days} jours.")

    columns = [c[0] for c in _COLUMNS]
    tree = ttk.Treeview(content, columns=columns, show="headings", height=min(20, len(results)))
    for key, header, width in _COLUMNS:
        tree.heading(key, text=header)
        tree.column(key, width=width, anchor="center")

    for r in results:
        cm = r["comparaison_marche"]
        ecart_pct = f"{cm['ecart_pct']:.1f}%" if cm["ecart_pct"] is not None else "n/a"
        tree.insert("", "end", values=(
            r["commodity"],
            _fmt(r["achats"]["count"]),
            _fmt(r["ventes"]["count"]),
            _fmt(r["achats"]["quantite"]),
            _fmt(r["ventes"]["quantite"]),
            _fmt(r["achats"]["credits_depenses"]),
            _fmt(r["ventes"]["credits_recus"]),
            _fmt(r["profit_reel"]),
            _fmt(cm["ecart_credits"]),
            ecart_pct,
        ))
    tree.grid(column=0, row=0, sticky="nsew")
