# Rapport — Agent IA d'analyse de fraude

*Cours GenAI, sujet 1 : agent avec outils et skills. Projet de groupe (4 personnes).*

## 1. Problème et objectif

Un analyste fraude reçoit chaque jour des alertes sur des transactions par carte. Pour chacune, il
doit rassembler les faits (historique, score du modèle), retrouver la procédure interne
applicable, puis décider : bloquer la carte, contacter le client, escalader ou classer l'alerte.
Ce travail est répétitif, et une erreur coûte cher dans les deux sens : une fraude ratée, ou un
client légitime bloqué.

**Objectif :** un agent qui instruit l'alerte de bout en bout et **prépare** la décision avec
sa justification et la procédure citée. Il laisse la décision irréversible à un humain.

**Lien avec le projet 2 :** le modèle de détection de fraude (XGBoost, PR-AUC 0,83, rappel 83 %)
servi par une API FastAPI devient un **outil** de l'agent, exposé via un serveur MCP.

## 2. Architecture

- **Squelette** généré avec `google/agents-cli` : agent Google ADK, serveur FastAPI, Dockerfile,
  tests, évaluation avec LLM juge, Terraform, CI/CD GitHub Actions, déploiement Cloud Run.
- **Agent** Google ADK avec Gemini (`temperature=0`).
- **Outils via MCP** : un serveur MCP (SDK Python officiel, FastMCP) expose
  `score_transaction` (appel HTTP à l'API du projet 2), `get_transaction_history` et
  `get_card_status` (SQL en lecture seule), et `block_card` (action risquée). L'agent les
  découvre au démarrage avec `McpToolset`, au lieu de les avoir écrits en dur.
- **Base SQL** (SQLite) : 20 000 transactions réelles du jeu de données du projet 2, dont les
  492 fraudes. Les colonnes métier (carte, client, date, catégorie, pays) sont synthétiques.
  Tables `cards`, `transactions` et `actions`, qui sert de journal des décisions.
- **RAG** : 12 procédures fictives découpées par section (19 morceaux), embeddings
  `gemini-embedding-001`, base vectorielle Chroma. L'outil renvoie les 3 passages les plus
  proches avec leur source (`PROC-XX`, section, fichier).
- **Interface** Streamlit : chat, trace des outils appelés et validation humaine.

## 3. Registre d'outils, registre de skills, constructeur de contexte

**Registre d'outils** : les 4 outils MCP, plus `search_procedures` et `activate_skill`. Chaque
outil a un modèle Pydantic d'entrée (`app/schemas.py`, dictionnaire `TOOL_ARG_MODELS`).

**Registre de skills** (`app/skills.py`, dictionnaire `SKILL_REGISTRY`) :

| Skill | Rôle | Outils autorisés |
|---|---|---|
| `investigation` | Statut, historique, score | `get_card_status`, `get_transaction_history`, `score_transaction` |
| `procedure_lookup` | Trouver la procédure applicable | `search_procedures` |
| `decision_prep` | Proposer une action justifiée | `block_card`, `get_card_status` |

**Constructeur de contexte** : l'instruction système est une fonction (`InstructionProvider`
d'ADK) recalculée avant chaque appel au modèle. Elle injecte uniquement :
1. les règles de base ;
2. le catalogue des skills (une ligne chacune) ;
3. les instructions complètes de la **seule** skill active ;
4. les faits du dossier dont cette skill a besoin (`context_keys`). Par exemple,
   `procedure_lookup` voit le score mais pas l'action en attente.

Le dossier est tenu à jour par un callback après chaque outil (`after_tool`).

## 4. Garde-fous et validation humaine

Ils sont implémentés dans un `before_tool_callback` ADK : un outil refusé n'est pas exécuté, et
le modèle reçoit le motif du refus.

1. **Budget** : 10 appels d'outils métier au maximum par demande.
2. **Allowlist par skill** : un outil hors de la skill active est refusé.
3. **Validation Pydantic** des arguments (format `CARD-00000`, bornes, longueur de la
   justification).
4. **Carte inconnue** : refus, sans appel à la base en écriture.
5. **Pas d'action sans procédure** : `block_card` est refusé si la procédure citée n'a pas été
   retrouvée par `search_procedures` dans la conversation.

Une défense en profondeur s'ajoute côté serveur MCP : l'outil revalide les entrées, refuse une
procédure inexistante et une carte déjà bloquée.

**Validation humaine** : `block_card` n'exécute rien. L'outil écrit une demande
`pending_approval` dans la table `actions`. L'analyste approuve ou refuse dans Streamlit
(`POST /actions/{id}/approve|reject`). Seule l'approbation passe la carte à `blocked`. Une
décision ne peut être prise qu'une fois. ADK propose aussi un mécanisme de confirmation des
outils, mais l'état « en attente » en base a été préféré : il survit à la session, il est
auditable et il est partagé avec l'interface.

## 5. Traces et observabilité

- **Dans l'interface** : chaque appel d'outil, ses arguments et son résultat, étape par étape.
- **En production** : traces OpenTelemetry exportées vers Cloud Trace (une span par appel au
  modèle et par outil, avec la latence et les tokens), journaux vers Cloud Logging.
- **Journal métier** : la table `actions` (qui a demandé quoi, avec quelle procédure, qui a
  décidé, et quand).

## 6. Évaluation

**Protocole.** 25 scénarios, chacun avec le comportement attendu :
- 7 fraudes évidentes ;
- 6 transactions normales ;
- 2 scores intermédiaires ;
- 3 cartes ou transactions inconnues ou mal formées ;
- 1 carte déjà bloquée ;
- 3 demandes hors sujet ou portant sur des données personnelles ;
- 3 cas avec l'API de fraude en panne (serveur relancé avec une URL injoignable).

Les deux systèmes sont servis par le même serveur, avec le même modèle et la même consigne métier :
- **l'agent** : outils, skills, RAG et garde-fous ;
- **la baseline à simple prompt** : sans outils.

`agents-cli eval generate` produit les traces, puis `agents-cli eval grade` les note et
`agents-cli eval compare` compare les deux systèmes.

**Métriques :**
- **LLM juge** (Gemini) de 1 à 5, avec une grille propre au domaine. Un fait absent de la trace
  compte comme inventé. Un scénario est réussi si la note est d'au moins 4.
- **Actions inutiles** : blocage demandé ou recommandé alors qu'il ne fallait pas.
- **Erreurs d'outils** : arguments invalides ou refus des garde-fous.
- **Nombre d'appels d'outils.**

**Résultats** : voir [eval_results.md](eval_results.md), généré par `bash scripts/run_eval.sh`.

| Métrique | Baseline | Agent |
|---|---|---|
| Taux de réussite | _xx %_ | _xx %_ |
| Actions inutiles | _x_ | _x_ |
| Erreurs d'outils | — | _x_ |

**Analyse attendue :**
- La baseline n'a accès à aucune donnée. Elle ne peut que demander des informations ou inventer
  un score, et elle ne sait ni qu'une carte est inconnue ni qu'une API est en panne.
- L'agent répond à partir des faits et cite la procédure.
- Les principaux risques de l'agent sont un nombre d'appels d'outils plus élevé (latence, coût)
  et des erreurs de séquencement des skills. Ces erreurs sont captées par les garde-fous et
  mesurées par la métrique d'erreurs d'outils.

## 7. Déploiement

- Les deux services tournent sur **Cloud Run** : l'agent (`agents-cli deploy`) et l'API du
  projet 2 (image construite par Cloud Build).
- La clé de l'API de fraude est rangée dans **Secret Manager** et injectée dans les deux services
  sous forme de variable d'environnement. Elle n'apparaît jamais dans le code.
- **CI/CD** :
  - `ci.yaml` lance le lint et les 44 tests unitaires sans identifiants cloud ;
  - les workflows générés par `agents-cli infra cicd` lancent les tests sur chaque PR, puis
    déploient en staging et en production au merge.

## 8. Limites et pistes

- SQLite embarqué : chaque instance Cloud Run a sa copie. En production, on passerait à
  Cloud SQL ou PostgreSQL.
- Les colonnes métier sont synthétiques. Les signaux contextuels (catégorie, pays) restent
  volontairement imparfaits : de 33 à 40 % de fraudes dans les catégories à risque.
- La notification du client et la commande d'une nouvelle carte ne sont pas implémentées.
- Pistes :
  - mémoire long terme (Memory Bank) pour retrouver les dossiers précédents d'un client ;
  - optimisation des prompts avec `agents-cli eval optimize` ;
  - authentification de l'interface (IAP).

## 9. Répartition du travail

| Membre | Partie |
|---|---|
| _moi_ | Serveur MCP + intégration de l'API du projet 2, évaluation contre la baseline, déploiement Cloud Run et CI/CD |
| _membre 2_ | RAG (procédures, embeddings, Chroma) |
| _membre 3_ | Interface Streamlit |
| _membre 4_ | Rédaction des procédures et des scénarios, rapport |
