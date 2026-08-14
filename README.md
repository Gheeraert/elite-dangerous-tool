# elite-dangerous-tool

Outils personnels Elite Dangerous. Objectif à terme : un tableau de bord
croisant trois sources — API communautaires, Frontier Companion API (CAPI,
authentifiée) et fichiers journaux locaux du jeu — pour se passer d'outils
lourds type Inara.

**Phase 1** a mis en place la couche de collecte (`sources/`, `modules/`),
sans stockage persistant. **Phase 2** ajoute le pont SQLite (`storage/`)
qui archive et exploite ces collectes dans le temps, avec `storage/loop.py`
pour l'alimenter en continu pendant une session. **Interface (état actuel
de ce dépôt)** ajoute `dashboard/`, une fenêtre Tkinter qui affiche ce que
la base contient déjà.

## Architecture

```
elite-dangerous-tool/
├── sources/            # accès bruts à chaque source de données
│   ├── community.py    # tick EDCD + prix Ardent (aucune clé requise)
│   ├── capi.py          # OAuth2 + endpoints Frontier CAPI (authentifiée)
│   ├── journal.py       # lecture des fichiers Status/Cargo/ShipLocker + Journal.*.log
│   ├── edsm.py           # coordonnées d'un système par nom (EDSM, aucune clé requise)
│   └── navigation.py     # distance en années-lumière entre deux coordonnées (calcul pur)
├── modules/             # une fonction collect() -> dict par module métier
│   ├── commander.py     # Module 1 : identité, finances, vaisseau, flotte, fleet carrier
│   ├── market.py         # Module 2 : tick BGS + meilleures stations achat/vente
│   ├── logbook.py        # Module 3 : journal de bord chronologique résumé
│   └── distance.py       # Module 4 : distance à un système donné, à la volée
├── storage/              # pont SQLite entre les collectes et leur exploitation dans le temps
│   ├── db.py             # connexion + schéma (créé automatiquement au premier usage)
│   ├── collector.py       # collect() -> ligne brute dans la table `collections`
│   ├── materializer.py    # `collections` -> tables dérivées indexées
│   ├── reports.py         # requêtes en lecture seule (ex. profit par commodité)
│   └── loop.py            # boucle de collecte en fond pendant une session de jeu
├── dashboard/            # interface Tkinter, lecture seule sur la base par défaut
│   ├── app.py             # point d'entrée : python -m dashboard.app
│   ├── data.py             # accès en lecture seule à `collections` (aucune écriture)
│   └── panels/             # un fichier par onglet (commander, marché, journal, rapport)
├── config.example.toml  # à copier vers config.toml (jamais commité)
└── .gitignore
```

`sources/` sait *parler* à une source (requêtes HTTP, parsing de fichiers).
`modules/` sait *répondre à une question métier* en combinant une ou
plusieurs sources, et renvoie toujours un dict avec au minimum un champ
`collected_at` (horodatage ISO 8601 UTC de la collecte).

## Prérequis

- Python 3.11+ (utilise `tomllib`, dans la bibliothèque standard depuis 3.11)
- `pip install requests cryptography` (`cryptography` sert uniquement à
  générer le certificat TLS auto-signé local pour le callback CAPI, voir
  plus bas)

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
python -m modules.distance "Sol"  # à combien d'années-lumière suis-je de Sol ?
```

## Distance à un système

`modules/distance.py` répond à une question posée à la volée — « à combien
d'années-lumière suis-je du système X ? » — en combinant la position
actuelle du commander (dernier `FSDJump`/`CarrierJump`/`Location` du
journal local) et les coordonnées du système cible (EDSM). Distance
arrondie à l'entier le plus proche :

```
$ python -m modules.distance "Sol"
Sol est à 64 années-lumière de votre position actuelle (Sosoling).
```

Cette même distance est aussi injectée automatiquement dans les résultats
de `modules/market.py` : chaque station retournée (achat comme vente) porte
un champ `distance_from_commander_ly`, calculé sans appel réseau
supplémentaire — Ardent fournit déjà les coordonnées de chaque système dans
ses réponses. Le contexte de calcul (`position_commander`) est inclus une
fois dans le résultat. Si la position du commander est introuvable (jeu
jamais lancé localement), ces champs sont `null` plutôt que de faire
échouer la collecte.

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

### Rapports (`storage/reports.py`)

Lecture seule sur le pont SQLite — uniquement des `SELECT`, jamais
d'écriture. Premier rapport : profit réel par commodité, comparé au
meilleur prix communautaire connu au moment de chaque vente.

```
python -m storage.reports --days 30
```

Pour chaque commodité ayant au moins une transaction dans la fenêtre :
nombre et quantité d'achats/ventes, crédits dépensés/reçus, profit réel
brut (`credits_recus - credits_depenses`). Pour les ventes, un « écart
marché » : la différence entre ce que la vente a réellement rapporté et ce
qu'elle aurait rapporté au meilleur prix connu dans `price_checks` juste
avant la transaction (instantané le plus proche mais antérieur ou égal).
Si aucun `price_check` n'existe dans les 7 jours précédant une vente, elle
est exclue du calcul d'écart plutôt que de comparer à une donnée trop
ancienne — le nombre de ventes ainsi exclues est rappelé en pied de rapport.

Exemple de sortie (illustratif, sur un jeu de données de démonstration —
`n/a` quand aucune vente de la commodité n'a de `price_check` comparable) :

```
Commodité                 Achats  Ventes  Qté ach. Qté vendue       Dépensé          Reçu   Profit réel  Écart marché  Écart %
--------------------------------------------------------------------------------------------------------------------------------
Agronomic Treatment           35      28    30 384     23 600    79 666 848   468 253 120   388 586 272  -142 008 256   -33.3%
gold                          22       6     1 436      2 269     6 559 803   122 034 498   115 474 695           n/a      n/a

(84 vente(s) sans price_check dans les 7 jours précédents : exclues du calcul d'écart marché.)
```

Ici, l'écart négatif signifie que les ventes réelles ont rapporté ~33 %
de moins que si elles avaient été faites au meilleur prix communautaire
connu juste avant chaque vente — un signal concret pour ajuster ses
routes commerciales.

Si la base n'a pas encore de table dérivée (aucune collecte lancée), le
script affiche un message clair invitant à lancer `storage/collector.py`
puis `storage/materializer.py`, plutôt qu'une trace d'erreur brute.

## Boucle de collecte (`storage/loop.py`)

`storage/collector.py` ne remplit la base que si on le lance à la main.
`storage/loop.py` est fait pour tourner en fond **pendant une session de
jeu** et alimenter la base en continu, sans intervention :

```
python -m storage.loop
```

Trois activités concurrentes, chacune avec sa propre connexion SQLite
(`storage/db.py` active le mode WAL pour permettre des écritures
concurrentes sans erreurs `database is locked`) :

- **`logbook`** : réactif, pas périodique — surveille la taille du fichier
  `Journal.*.log` actif (sondage simple, quelques secondes, voir
  `sources.journal.watch_for_new_events`) et relance une collecte dès qu'il
  grossit (un `Docked`, `FSDJump`, etc. vient d'être écrit par le jeu).
- **`market`** : à intervalle fixe (20 min par défaut) — les données Ardent
  viennent de contributions EDDN communautaires, interroger plus souvent
  n'apporte pas de fraîcheur supplémentaire.
- **`commander`** : à intervalle fixe plus large (25 min par défaut), et
  **uniquement si un token CAPI est disponible** (`.capi_token.json`
  présent, voir la section CAPI plus bas) — sinon ce collecteur se
  désactive silencieusement au démarrage (un seul message, pas de tentative
  répétée qui échoue en boucle).

Chaque collecte réussie est immédiatement matérialisée (pas d'attente
d'une passe `storage/materializer.py` séparée). Chaque tick est protégé
individuellement : une erreur réseau ou autre est affichée avec un
horodatage mais n'arrête jamais la boucle globale. `Ctrl+C` arrête
proprement (attend la fin des collectes en cours, ferme les connexions).

Options utiles (défauts lisibles dans `[loop]`/`[market]` de
`config.toml`, surchargeables sans toucher au code) :

```
python -m storage.loop --market-interval 30 --commander-interval 45
python -m storage.loop --no-commander          # pas de token CAPI configuré
python -m storage.loop --market-commodity "Gold" --market-stations 10
```

Pas de service système (systemd/tâche planifiée) dans cette passe : un
script à lancer manuellement dans un terminal en début de session suffit.

## Interface (`dashboard/app.py`)

Fenêtre Tkinter (bibliothèque standard, pas de nouvelle dépendance) qui
affiche ce que la base contient déjà :

```
python -m dashboard.app
```

**`storage/loop.py` doit tourner à côté (ou avoir tourné avant)** pour
qu'il y ait quelque chose à afficher — l'interface ne fait aucun appel
réseau au chargement, elle lit uniquement la base via sa propre connexion
(`storage.db.connect()`). Sans données en base, chaque onglet affiche un
message clair plutôt qu'un écran vide.

Quatre onglets, chacun sur la dernière collecte en base pour son module :

- **Commander** : identité, rangs, finances, vaisseau actuel, résumé de
  flotte, fleet carrier (s'il existe).
- **Marché** : champ commodité (défaut : `[market].default_commodity` de
  `config.toml`), meilleures stations d'achat/vente de la dernière collecte
  correspondante, distance au commander incluse quand le champ est présent
  (les collectes antérieures à son ajout ne l'ont pas — affiché `n/a`).
- **Journal de bord** : les N dernières étapes de la dernière collecte,
  résumées (pas un dump brut) — même esprit que `modules/logbook.py`.
- **Rapport** : `storage.reports.profit_by_commodity()` réutilisée telle
  quelle, avec la fenêtre en jours ajustable.

**Lecture seule par défaut.** Chaque onglet a son propre bouton
« Actualiser maintenant », seule action qui écrit : elle appelle
`storage.collector.record_xxx()` une fois puis relit — jamais en
automatique, jamais au chargement (pas de thread de rafraîchissement
caché). C'est `storage/loop.py`, pas l'interface, qui a la responsabilité
de remplir la base en continu.

## `sources/capi.py` — authentification CAPI

Le flux OAuth2 complet est implémenté et testé en conditions réelles :
PKCE (pas besoin de `client_secret` si l'app Frontier n'en fournit pas),
serveur de callback local, vérification du `state` (CSRF), échange du code,
sauvegarde du token dans `.capi_token.json` (exclu du dépôt).

```
python -m sources.capi authorize   # ouvre le navigateur, capte le callback, sauvegarde le token
python -m sources.capi test        # vérifie le token en appelant /profile
```

Prérequis dans `config.toml` (voir `config.example.toml`) : `client_id`
(et `client_secret` si votre app Frontier en a un — sinon laissez vide,
PKCE suffit) et `redirect_uri`. Créer l'app sur
https://user.frontierstore.net/ (menu "Developer Zone" > "Create Client").

**Point de vigilance découvert en testant** : le formulaire Frontier peut
imposer un `redirect_uri` en **https**, y compris pour `localhost`. Le
serveur de callback local gère ce cas en générant un certificat TLS
auto-signé à la volée (dépendance `cryptography`, fichiers `.capi_dev_cert.pem`
/ `.capi_dev_key.pem` exclus du dépôt) : le navigateur affichera un
avertissement de sécurité sur `localhost` à accepter manuellement une fois
— normal pour un certificat auto-signé, pas un signe de mauvaise
configuration.

`modules/commander.py` utilise la CAPI en priorité si `.capi_token.json`
existe, et retombe silencieusement sur les fichiers locaux sinon (champ
`source: "local"` vs `"capi"` dans le résultat de `collect()`).

Ce qui reste non fait : rafraîchissement automatique du token avant
expiration (`refresh_access_token()` existe mais n'est pas appelé
automatiquement — un `.capi_token.json` expiré nécessite de relancer
`authorize`).

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
