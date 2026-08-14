# elite-dangerous-tool

Outils personnels Elite Dangerous. Objectif à terme : un tableau de bord
croisant trois sources — API communautaires, Frontier Companion API (CAPI,
authentifiée) et fichiers journaux locaux du jeu — pour se passer d'outils
lourds type Inara.

**Phase 1 (état actuel de ce dépôt)** : uniquement la couche de collecte.
Pas d'interface graphique, pas de base de données persistante. Chaque
module se contente de récupérer et structurer les données de sa source.

## Architecture

```
elite-dangerous-tool/
├── sources/            # accès bruts à chaque source de données
│   ├── community.py    # tick EDCD + prix Ardent (aucune clé requise)
│   ├── capi.py          # OAuth2 + endpoints Frontier CAPI (authentifiée)
│   └── journal.py       # lecture des fichiers Status/Cargo/ShipLocker + Journal.*.log
├── modules/             # une fonction collect() -> dict par module métier
│   ├── commander.py     # Module 1 : identité, finances, vaisseau, flotte, fleet carrier
│   ├── market.py         # Module 2 : tick BGS + meilleures stations achat/vente
│   └── logbook.py        # Module 3 : journal de bord chronologique résumé
├── config.example.toml  # à copier vers config.toml (jamais commité)
└── .gitignore
```

`sources/` sait *parler* à une source (requêtes HTTP, parsing de fichiers).
`modules/` sait *répondre à une question métier* en combinant une ou
plusieurs sources, et renvoie toujours un dict avec au minimum un champ
`collected_at` (horodatage ISO 8601 UTC de la collecte).

## Prérequis

- Python 3.11+ (utilise `tomllib`, dans la bibliothèque standard depuis 3.11)
- `pip install requests`

## Configuration

```
cp config.example.toml config.toml
```

Remplir `config.toml` avec vos identifiants CAPI si vous voulez utiliser
`modules/commander.py` en mode authentifié (sinon il retombe automatiquement
sur les fichiers locaux). `config.toml` est exclu du dépôt via `.gitignore` :
n'y committez jamais de valeurs réelles.

## Lancer un module isolément

Chaque module s'exécute seul et affiche son `collect()` en JSON sur stdout :

```
python -m modules.market "Agronomic Treatment"
python -m modules.commander
python -m modules.logbook 20     # 20 dernières étapes du journal de bord
```

## État de `sources/capi.py`

Le squelette OAuth2 (constantes des endpoints, échange de code, refresh
token, appels `/profile` `/shipyard` `/fleetcarrier`) est en place, mais le
flux d'autorisation interactif (ouverture navigateur, capture du `code` de
retour) n'est pas implémenté — voir les commentaires en tête de fichier.
`modules/commander.py` détecte cette absence et retombe silencieusement sur
les fichiers locaux.

## Ajouter un nouveau module

1. Si la donnée vient d'une source pas encore couverte, ajouter un fichier
   dans `sources/` avec des fonctions bas niveau (une requête HTTP ou une
   lecture de fichier = une fonction).
2. Créer `modules/mon_module.py` avec une fonction :

   ```python
   def collect(...) -> dict:
       return {
           "collected_at": datetime.now(timezone.utc).isoformat(),
           # ... champs métier, catégorisés clairement ...
       }
   ```

3. Ne jamais laisser une exception réseau ou de parsing remonter jusqu'à
   l'appelant : capturer, consigner dans un champ `errors`/`error` du dict
   renvoyé, et renvoyer les données partielles disponibles plutôt que de
   planter.
4. Ajouter un bloc `if __name__ == "__main__":` qui imprime `collect()` en
   JSON, pour pouvoir tester le module isolément (voir `modules/market.py`
   pour l'exemple).

## Sécurité

Ne jamais committer de secrets (client_id/secret CAPI, tokens, cookies de
session, dumps de journal personnel). Voir `.gitignore` et
`config.example.toml`.
