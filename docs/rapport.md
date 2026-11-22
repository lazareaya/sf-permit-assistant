# Rapport — Assistant permis de construire pour San Francisco

*Cours GenAI, sujet 1 : Domain Specific Agent Harness. Projet réalisé seul.*

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
- 1 question dont la réponse est absente des fiches (peinture au plomb lors d'un remplacement de
  fenêtres) et 1 question sur le contenu d'une page manquante (DOC-03) ;
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

Run du 2026-11-22. Assistant et baseline sur `gemini-3.5-flash-lite`, juge `gemini-3.1-flash-lite`.

| Métrique | Baseline simple prompt | Assistant |
|---|---|---|
| Taux de réussite (juge ≥ 4/5) | 20 % | **96 %** |
| Note moyenne du juge (1-5) | 2,88 | **4,80** |
| Outils attendus appelés | 8 % | **96 %** |
| Conformité (avertissement + source citée) | 78 % | **100 %** |
| Actions inutiles | 0 | **0** |
| Erreurs d'outils | — | **0** |
| Appels d'outils moyens par scénario | 0 | 2,4 |

**Analyse :**
- **La baseline** échoue sur 20 scénarios sur 25. Elle n'a ni données ni sources : elle ne peut
  pas connaître les permis d'une adresse, ne voit pas qu'un projet ou une adresse n'existe pas, et
  cite rarement une page officielle. Elle ne réussit que les refus hors périmètre et quelques
  questions génériques.
- **L'assistant** réussit 24 scénarios sur 25. Il répond à partir de la trace d'outils, cite
  toujours ses sources et l'avertissement, et ne fait aucune action non demandée. Il signale
  correctement l'adresse inexistante, la page manquante, la réponse absente des fiches et la panne
  de DataSF.
- **Seul échec** : la liste des formulaires pour un ADU (note 3/5). La réponse est juste mais
  incomplète, il manque une partie des formulaires de la fiche DOC-05. C'est la piste
  d'amélioration principale : une deuxième recherche dans le RAG ciblée sur les formulaires.
- **Coût** : 2,4 appels d'outils par scénario en moyenne, contre 0 pour la baseline. C'est le prix
  de la fiabilité, en latence et en tokens.

**Corrections faites pendant l'évaluation :**
- Un premier passage a mis en évidence deux défauts. Le juge des actions inutiles comptait à tort
  l'historique des permis d'une adresse comme un « dossier envoyé » : sa consigne a été précisée.
  L'agent refusait la question « qui contacter » comme hors périmètre : la règle de périmètre a été
  corrigée.
- L'assistant a ensuite été réévalué sur les 25 scénarios. Les traces de la baseline, inchangée,
  ont été réutilisées.

## 7. Déploiement

- **Cloud Run**, via `agents-cli deploy`.
- **Secret Manager** pour la clé Gemini et le jeton DataSF optionnel.
- Gemini est appelé avec une clé Google AI Studio (offre gratuite), lue depuis Secret Manager. Tout reste dans les offres gratuites.
- **CI/CD** :
  - `ci.yaml` lance le lint et les tests unitaires sans identifiants cloud ;
  - `cd.yaml` relance les tests puis redéploie Cloud Run à chaque merge sur `main`. GitHub
    s'authentifie par Workload Identity Federation (aucune clé stockée sur GitHub). Ce pipeline sur
    un seul projet remplace la CI/CD staging + production d'`agents-cli infra cicd`, qui demandait
    plusieurs projets.
- **Observabilité vérifiée** : Cloud Trace montre `invoke_agent` → `generate_content` (latence,
  tokens d'entrée et de sortie) → `execute_tool` → `MCP tools/call`. Le processeur reste alloué
  pendant la vie de l'instance : en facturation à la requête, les traces n'étaient jamais envoyées.

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
