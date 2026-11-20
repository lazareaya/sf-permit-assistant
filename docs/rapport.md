# Rapport — Assistant permis de construire pour San Francisco

*Cours GenAI, sujet 1 : Domain Specific Agent Harness. Projet de groupe (4 personnes).*

> ⚠️ Information générale, pas un avis juridique. Vérifier auprès du Department of Building Inspection.

## 1. Problème et objectif

Dans un cabinet d'architectes, une partie du temps passe en recherches administratives :
- l'historique des permis d'une adresse ;
- les pièces exigées pour un type de travaux ;
- le montage du dossier d'un projet.

Ces informations sont publiques mais dispersées entre l'open data de la ville (DataSF) et les
pages du Department of Building Inspection (DBI) et du Planning Department.

**Objectif :** un assistant spécialisé, pour un cabinet **fictif**, limité à 3 demandes :
- a) les permis existants à une adresse et leur statut ;
- b) les documents requis pour 6 types de travaux, avec les sources citées ;
- c) la préparation du dossier d'un projet du cabinet, envoyé seulement après validation humaine.

Toute autre demande est refusée.

## 2. Architecture

- **Squelette** généré avec `google/agents-cli` : agent Google ADK, FastAPI, Dockerfile, tests,
  évaluation avec LLM juge, Terraform, CI/CD, déploiement Cloud Run.
- **Agent** Google ADK avec Gemini (`temperature=0`).
- **Outils via MCP** : un serveur MCP (SDK Python officiel, FastMCP) expose 5 outils :
  - `search_permits` : API DataSF ;
  - `list_projects` et `get_project` : SQL en lecture seule ;
  - `create_submission_draft` : brouillon au statut `pending_approval` ;
  - `send_submission` : action risquée.

  L'agent les découvre avec `McpToolset`.
- **API DataSF** (« Building Permits », Socrata, sans clé) :
  - analyse de l'adresse et requête SoQL ;
  - dédoublonnage par numéro de permis ;
  - cache SQLite de 24 h ;
  - erreurs explicites (délai dépassé, API indisponible, adresse introuvable) ;
  - cache périmé servi et signalé en cas de panne.
- **Base SQL** (SQLite) : 20 projets fictifs à de vraies adresses de San Francisco, et une table
  `submissions` qui sert de journal des dossiers.
- **RAG** :
  - 10 pages officielles de sf.gov, copiées mot pour mot le 2026-11-20, une par fichier, avec URL
    et titre. Deux pages prévues n'ont pas pu être récupérées : DOC-03 (projets éligibles au permis
    OTC, erreur 404) et DOC-07 (étapes pour ajouter un ADU, redirection vers une erreur 404). Elles
    ne sont pas remplacées ;
  - l'étiquette de type de page passe en métadonnée (`page_type`) ;
  - découpage par `##` puis `###` (111 morceaux), sections « Related » exclues, « Contact us »
    gardé en un seul morceau ;
  - chaque morceau porte `doc_id`, `title`, `section` et `url`, et l'agent cite « titre de la
    page, section (URL) » ;
  - embeddings `gemini-embedding-001` et base Chroma ;
  - seuil de pertinence : en dessous, l'outil répond `NO_RELEVANT_DOCUMENT`.

  Il reste un outil ADK direct (pas MCP), car l'index vit déjà dans le processus de l'agent.
- **Interface** Streamlit : avertissement juridique, chat, trace des outils, validation des dossiers.

## 3. Registre d'outils, registre de skills, constructeur de contexte

| Skill | Rôle | Outils autorisés |
|---|---|---|
| `permit_search` | Permis à une adresse (point a) | `search_permits` |
| `document_requirements` | Exigences documentaires, sources citées (point b) | `search_city_docs` |
| `submission_prep` | Brouillon de dossier (point c) | `list_projects`, `get_project`, `search_city_docs`, `search_permits`, `create_submission_draft`, `send_submission` |

Chaque outil a son modèle Pydantic d'entrée (`TOOL_ARG_MODELS`).

Le **constructeur de contexte** est un `InstructionProvider` d'ADK, recalculé avant chaque appel
au modèle. Il injecte :
1. les règles de base : périmètre, refus, avertissement, citations ;
2. le catalogue des skills ;
3. les instructions de la **seule** skill active ;
4. les faits du dossier utiles à cette skill (`context_keys`). Par exemple,
   `document_requirements` reçoit le type de travaux et les sources déjà trouvées, pas l'identifiant
   du dossier.

## 4. Garde-fous et validation humaine

**Garde-fous en entrée** (`before_tool_callback`) :
- budget de 10 appels d'outils par demande ;
- outil hors skill refusé ;
- validation Pydantic des arguments ;
- projet inconnu refusé ;
- brouillon refusé s'il ne cite aucune URL retrouvée par le RAG ;
- envoi refusé si le dossier n'est pas `approved` (revérifié côté MCP).

**Garde-fou en sortie** (`after_model_callback`) : l'avertissement juridique est imposé dans
chaque réponse finale. Si des documents ont été consultés sans qu'aucune URL ne soit citée, les
sources sont ajoutées.

**Validation humaine :**
- l'agent prépare le brouillon ;
- l'architecte approuve ou refuse dans Streamlit ;
- seul un dossier approuvé peut être envoyé, et chaque décision ne peut être prise qu'une fois ;
- l'envoi est simulé.

## 5. Traces et observabilité

- **Interface** : chaque appel d'outil, ses arguments et son résultat.
- **Production** : traces OpenTelemetry dans Cloud Trace (spans du modèle et des outils, latence,
  tokens) et journaux dans Cloud Logging.
- **Journal métier** : la table `submissions` (qui a validé, quand, date d'envoi).

## 6. Évaluation

**Protocole.** 25 scénarios, chacun avec les outils attendus, les éléments de réponse et la
source attendue :
- 4 permis à une adresse réelle (vérité terrain : instantané DataSF) et 1 adresse inexistante ;
- 7 questions sur les documents requis et 1 question « qui contacter », dont les éléments attendus
  sont repris mot pour mot des fiches ;
- 1 question sur un sujet absent des fiches (piscine) et 1 question sur le contenu d'une page
  manquante (DOC-03) ;
- 3 préparations de dossier, 1 liste de projets, 1 envoi sans validation, 1 projet inconnu ;
- 2 demandes hors périmètre ;
- 2 cas avec l'API DataSF en panne.

L'assistant et la baseline à simple prompt (même modèle, même périmètre, sans outils) sont
servis par le même serveur. `agents-cli eval generate` produit les traces, puis
`agents-cli eval grade` les note et `agents-cli eval compare` compare les deux.

**Métriques :**
- LLM juge de 1 à 5 (réussite si la note est d'au moins 4) ;
- outils attendus appelés ;
- conformité (avertissement + source citée) ;
- actions inutiles ;
- erreurs d'outils ;
- nombre d'appels d'outils.

**Résultats** : voir [eval_results.md](eval_results.md), généré par `bash scripts/run_eval.sh`.

| Métrique | Baseline | Assistant |
|---|---|---|
| Taux de réussite | _xx %_ | _xx %_ |
| Conformité (avertissement + source) | _xx %_ | _xx %_ |
| Actions inutiles | _x_ | _x_ |
| Erreurs d'outils | — | _x_ |

**Analyse attendue :**
- La baseline n'a ni données ni sources. Elle ne peut pas connaître les permis d'une adresse et
  risque d'inventer des exigences ou des URL. Elle ne sait pas non plus qu'un projet n'existe pas.
- L'assistant répond à partir de la trace et cite ses sources.
- Ses risques sont un nombre d'appels d'outils plus élevé (latence, coût) et des erreurs de
  séquencement des skills. Les garde-fous les captent et la métrique d'erreurs d'outils les mesure.

## 7. Déploiement

- **Cloud Run**, via `agents-cli deploy`.
- **Secret Manager** pour le jeton DataSF, qui est optionnel.
- Gemini est appelé via Vertex AI avec l'identité du service, sans clé.
- **CI/CD** :
  - `ci.yaml` lance le lint et les tests unitaires sans identifiants cloud ;
  - les workflows générés par `agents-cli infra cicd` lancent les tests sur PR, puis déploient en
    staging et en production au merge.

## 8. Limites et pistes

- Envoi simulé, sans dépôt réel.
- SQLite embarqué : on passerait à Cloud SQL en production.
- Les pages de la ville évoluent : il faut rafraîchir le corpus.
- sf.gov bloque les clients automatisés : le corpus se met à jour en copiant les pages depuis un
  navigateur. Deux pages prévues sont introuvables (erreur 404).
- Pistes :
  - suivi automatique des changements de statut d'un permis ;
  - checklists par type de travaux ;
  - authentification de l'interface (IAP).

## 9. Répartition du travail

| Membre | Partie |
|---|---|
| _moi_ | Serveur MCP (DataSF, base projets), évaluation contre la baseline, déploiement Cloud Run et CI/CD |
| _membre 2_ | RAG (corpus officiel, embeddings, Chroma) |
| _membre 3_ | Interface Streamlit et validation humaine |
| _membre 4_ | Scénarios d'évaluation, rapport, slides |
