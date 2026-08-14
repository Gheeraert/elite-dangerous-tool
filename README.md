# elite-dangerous-tool

Outils personnels Elite Dangerous. Objectif à terme : un tableau de bord
croisant trois sources — API communautaires, Frontier Companion API (CAPI,
authentifiée) et fichiers journaux locaux du jeu — pour se passer d'outils
lourds type Inara.

**Phase 1** a mis en place la couche de collecte (`sources/`, `modules/`),
sans stockage persistant. **Phase 2 (état actuel de ce dépôt)** ajoute le
pont SQLite (`storage/`) qui archive et exploite ces collectes dans le
temps. Toujours pas d'interface graphique — pour une phase ultérieure.

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
├── storage/              # pont SQLite entre les collectes et leur exploitation dans le temps
│   ├── db.py             # connexion + schéma (créé automatiquement au premier usage)
│   ├── collector.py       # collect() -> ligne brute dans la table `collections`
│   └── materializer.py    # `collections` -> tables dérivées indexées
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

## Stockage

Deux niveaux, pas un seul schéma normalisé monolithique :

1. **Journal brut, append-only** (`collections`) : une ligne par appel
   `collect()`, jamais modifiée après écriture, le dict complet sérialisé
   en JSON dans une colonne `payload`. C'est la source de vérité — elle ne
   casse jamais quand le format renvoyé par un module évolue.
2. **Tables dérivées, indexées** (`stations`, `market_transactions`,
   `price_checks`) : reconstruites à partir du journal brut par le
   *matérialiseur* (`storage/materializer.py`) — seulement ce qui a vraiment
   besoin d'être interrogé efficacement en SQL.

Séparation stricte : les modules (`modules/*.py`) n'ont aucune connaissance
du stockage ; `storage/db.py` n'a aucune connaissance de comment les
données ont été collectées (CAPI, journal, Ardent). Le matérialiseur est le
seul composant qui connaît à la fois la forme des dicts `collect()` et le
schéma SQL — c'est volontairement le seul endroit à toucher si un module
change de forme.

La base est une simple base SQLite locale (chemin configurable via
`[storage] path` dans `config.toml`, défaut `elite.db` à la racine). Le
schéma est appliqué automatiquement à la première connexion — aucun script
de migration à lancer à part.

### Lancer une collecte

```
python -m storage.collector all "Agronomic Treatment"   # commander + market + logbook
python -m storage.collector market "Agronomic Treatment"
python -m storage.collector commander
python -m storage.collector logbook
```

Chaque appel insère une ligne brute dans `collections` et affiche l'`id`
inséré.

### Matérialiser

```
python -m storage.materializer
```

Traite toutes les lignes de `collections` pas encore matérialisées (marque
de progression conservée dans `materialization_progress`) et peuple
`stations`/`market_transactions`/`price_checks`. Relancer sans nouvelle
collecte ne fait rien (`processed: 0`) — c'est idempotent. Une ligne au
payload incomplet ou en erreur (champ `errors` déjà renseigné par le
`collect()` d'origine) est ignorée proprement, sans bloquer les suivantes.

Le module `commander` n'a pas encore de table dérivée dans ce schéma :
`_materialize_commander()` est un point d'extension documenté, à
implémenter dans une phase future si un historique (crédits, flotte...)
devient utile.

### Exemple de requête : profit réel par commodité sur 30 jours

Rendue possible par `market_transactions`, qui garde achats et ventes
individuels (et non de simples agrégats) :

```sql
SELECT
    commodity,
    SUM(CASE WHEN direction = 'vente' THEN total_value ELSE 0 END)
        - SUM(CASE WHEN direction = 'achat' THEN total_value ELSE 0 END) AS profit,
    SUM(CASE WHEN direction = 'achat' THEN quantity ELSE 0 END) AS unites_achetees,
    SUM(CASE WHEN direction = 'vente' THEN quantity ELSE 0 END) AS unites_vendues
FROM market_transactions
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY commodity
ORDER BY profit DESC;
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
session, dumps de journal personnel, base SQLite réelle ou tout export de
celle-ci). Voir `.gitignore` et `config.example.toml`.
