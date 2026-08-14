"""
Onglet Journal de bord : les N dernières étapes de la dernière collecte
`logbook` en base — même esprit synthétique que modules/logbook.py (les
étapes sont déjà résumées à la collecte, ce panneau ne fait que les
afficher et les limiter à N).
"""

import tkinter as tk
from tkinter import ttk

from dashboard import data
from storage import collector, materializer

_DEFAULT_N = 20

_NO_DATA_MSG = (
    "Aucune collecte 'logbook' en base pour l'instant.\n\n"
    "Lancez storage/loop.py (il surveille le journal en continu), ou "
    "cliquez sur « Actualiser maintenant »."
)


def _summarize(step: dict) -> str:
    resume = step.get("resume_depuis_etape_precedente")
    if not resume:
        return ""
    parts = []
    commerce = resume.get("commerce", {})
    n_achats = len(commerce.get("achats") or [])
    n_ventes = len(commerce.get("ventes") or [])
    if n_achats:
        parts.append(f"{n_achats} achat(s)")
    if n_ventes:
        parts.append(f"{n_ventes} vente(s)")
    combat = resume.get("combat", {})
    if combat.get("primes"):
        parts.append(f"{combat['primes']} prime(s)")
    minage = resume.get("minage", {}).get("materiaux") or {}
    if minage:
        parts.append(f"minage x{sum(minage.values())}")
    exploration = resume.get("exploration", {})
    if exploration.get("signaux_detectes"):
        parts.append(f"{exploration['signaux_detectes']} signal(aux)")
    return ", ".join(parts)


def build(parent: ttk.Frame, conn) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=10)

    controls = ttk.Frame(frame)
    controls.grid(column=0, row=0, sticky="w")
    ttk.Label(controls, text="Nombre d'étapes :").grid(column=0, row=0, sticky="w")
    n_var = tk.IntVar(value=_DEFAULT_N)
    ttk.Spinbox(controls, from_=5, to=200, textvariable=n_var, width=5,
                command=lambda: _render(conn, n_var.get(), status_var, content)).grid(column=1, row=0, padx=(4, 0))

    status_var = tk.StringVar()
    ttk.Label(frame, textvariable=status_var, foreground="#666").grid(column=0, row=1, sticky="w", pady=(6, 8))

    content = ttk.Frame(frame)
    content.grid(column=0, row=2, sticky="nsew")
    frame.rowconfigure(2, weight=1)
    frame.columnconfigure(0, weight=1)

    do_refresh = lambda: _refresh(conn, n_var.get(), status_var, content)
    ttk.Button(frame, text="Actualiser maintenant", command=do_refresh).grid(
        column=0, row=3, sticky="w", pady=(10, 0)
    )

    _render(conn, n_var.get(), status_var, content)

    # Exposé pour le bouton global "Tout actualiser" de dashboard/app.py :
    # exactement la même action que le bouton de cet onglet, rien de dupliqué.
    frame.trigger_refresh = do_refresh
    return frame


def _refresh(conn, n: int, status_var: tk.StringVar, content: ttk.Frame) -> None:
    status_var.set("Actualisation en cours (lecture des fichiers journal)…")
    content.update_idletasks()
    try:
        collector.record_logbook(conn)
        materializer.materialize(conn)  # garde les tables dérivées à jour, comme storage/loop.py
    except Exception as e:
        status_var.set(f"Échec de l'actualisation : {e}")
        return
    _render(conn, n, status_var, content)


def _render(conn, n: int, status_var: tk.StringVar, content: ttk.Frame) -> None:
    for child in content.winfo_children():
        child.destroy()

    payload = data.get_latest_collection(conn, "logbook")
    if payload is None:
        status_var.set("")
        ttk.Label(content, text=_NO_DATA_MSG, justify="left").grid(column=0, row=0, sticky="w")
        return

    etapes = (payload.get("etapes") or [])[-n:]
    status_var.set(f"Dernière collecte : {payload.get('collected_at', '?')}  —  {len(payload.get('etapes') or [])} étape(s) au total en base")

    if not etapes:
        ttk.Label(content, text="Aucune étape enregistrée.").grid(column=0, row=0, sticky="w")
        return

    columns = ("horodatage", "type", "systeme", "station", "resume")
    tree = ttk.Treeview(content, columns=columns, show="headings", height=min(20, len(etapes)))
    headers = {"horodatage": "Horodatage", "type": "Type", "systeme": "Système", "station": "Station", "resume": "Résumé"}
    widths = {"horodatage": 150, "type": 140, "systeme": 160, "station": 160, "resume": 200}
    for c in columns:
        tree.heading(c, text=headers[c])
        tree.column(c, width=widths[c], anchor="w")

    for step in reversed(etapes):  # plus récent en premier
        tree.insert("", "end", values=(
            step.get("horodatage") or "",
            step.get("type") or "",
            step.get("systeme") or "",
            step.get("station") or "",
            _summarize(step),
        ))
    tree.grid(column=0, row=0, sticky="nsew")
