"""
Interface de bureau (Tkinter) : affiche ce que la base contient déjà.
storage/loop.py est responsable de remplir la base ; cette interface la lit
en lecture seule au chargement — aucun appel réseau au démarrage ni en
tâche de fond. Chaque onglet a son propre bouton « Actualiser maintenant »,
seule action qui écrit (via storage.collector), jamais automatique ; le
bouton global « Tout actualiser » ne fait qu'enchaîner ces mêmes actions
en un clic (même nombre d'appels réseau, juste moins de clics).
"""

import tkinter as tk
from tkinter import ttk

from dashboard.panels import commander_panel, logbook_panel, market_panel, report_panel
from storage import db


def main() -> None:
    try:
        conn = db.connect()
    except Exception as e:
        # Pas de fenêtre Tk affichable de façon fiable sans root ; on imprime
        # aussi sur stderr pour le cas où l'utilisateur lance depuis un terminal.
        print(f"Impossible d'ouvrir la base : {e}")
        raise SystemExit(1)

    root = tk.Tk()
    root.title("Elite Dangerous — Tableau de bord")
    root.geometry("900x600")

    toolbar = ttk.Frame(root, padding=(10, 8))
    toolbar.pack(fill="x")
    global_status_var = tk.StringVar()
    ttk.Label(toolbar, textvariable=global_status_var, foreground="#666").pack(side="left", padx=(10, 0))

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    # Commander/marché/logbook d'abord (chacun matérialise ses propres
    # collectes), rapport en dernier pour qu'il reflète les données fraîches.
    tabs = [
        ("Commander", commander_panel),
        ("Marché", market_panel),
        ("Journal de bord", logbook_panel),
        ("Rapport", report_panel),
    ]
    tab_frames = []
    for title, panel_module in tabs:
        try:
            tab = panel_module.build(notebook, conn)
        except Exception as e:
            tab = ttk.Frame(notebook, padding=10)
            ttk.Label(tab, text=f"Erreur de chargement de cet onglet :\n{e}", foreground="red").pack(anchor="w")
        notebook.add(tab, text=title)
        tab_frames.append((title, tab))

    def refresh_all() -> None:
        for tab_title, tab_frame in tab_frames:
            trigger = getattr(tab_frame, "trigger_refresh", None)
            if trigger is None:
                continue  # onglet qui n'a pas pu se construire : rien à actualiser
            global_status_var.set(f"Actualisation : {tab_title}…")
            root.update_idletasks()
            try:
                trigger()
            except Exception as refresh_error:
                global_status_var.set(f"Échec sur {tab_title} : {refresh_error}")
                root.update_idletasks()
        global_status_var.set("Tout actualisé.")

    ttk.Button(toolbar, text="Tout actualiser", command=refresh_all).pack(side="left")

    def on_close() -> None:
        conn.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
