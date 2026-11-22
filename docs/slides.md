---
marp: true
theme: default
paginate: true
size: 16:9
style: |
  section { font-size: 26px; }
  h1 { color: #1a4d8f; }
  table { font-size: 21px; }
---

<!-- Export : npx @marp-team/marp-cli slides.md --pptx   (ou --pdf), ou l'extension VS Code « Marp for VS Code » -->

# Assistant permis de construire — San Francisco
### Google ADK · Gemini · MCP · API DataSF · RAG · Cloud Run

Cours GenAI, sujet 1 : Domain Specific Agent Harness

---

## Le problème

- Un cabinet d'architectes passe des heures en recherches administratives
- Permis existants, pièces exigées, montage du dossier : les informations sont publiques mais **dispersées** (open data, DBI, Planning)
- Une erreur coûte cher : un dossier incomplet, ou une information inventée

**Un assistant spécialisé, limité à 3 demandes, qui cite ses sources et ne dépose rien sans validation humaine**

---

## Le périmètre

| Demande | Source |
|---|---|
| a) Permis existants à une adresse et leur statut | **API DataSF** (open data, cache) |
| b) Documents requis : cuisine, salle de bain, ADU, toiture, solaire, fenêtres | **RAG** sur 10 fiches officielles de sf.gov, cite « titre, section (URL) » |
| c) Préparer le dossier d'un projet du cabinet | **SQL** + brouillon, **validation humaine** |

Tout le reste : refus poli

---

## Architecture

```
Streamlit ──HTTP──> FastAPI (ADK) ──> Agent Gemini
                                        ├─ constructeur de contexte + 3 skills
                                        ├─ garde-fous (entrée + sortie)
                                        ├─ McpToolset ──stdio──> Serveur MCP ──> SQLite (projets, dossiers)
                                        │                              └──HTTPS──> API DataSF (+ cache)
                                        └─ search_city_docs ──> Chroma (pages sf.gov)
Cloud Run · Secret Manager · Cloud Trace · CI/CD GitHub Actions
```

Squelette généré avec **google/agents-cli**

---

## Skills et constructeur de contexte

| Skill | Outils autorisés |
|---|---|
| permit_search | search_permits |
| document_requirements | search_city_docs |
| submission_prep | list_projects, get_project, search_city_docs, search_permits, create_submission_draft, send_submission |

Le prompt est **reconstruit avant chaque appel** : règles + catalogue + instructions de la **seule skill active** + faits utiles à cette skill

---

## Garde-fous

- Au maximum **10 appels d'outils** par demande · **Pydantic** sur chaque argument
- Outil **hors de la skill active** : refusé · **projet inconnu** : refusé
- **Brouillon sans source officielle** : refusé
- **Envoi** refusé si le dossier n'est pas approuvé (revérifié par le serveur MCP)
- En sortie : **avertissement juridique imposé**, sources ajoutées si oubliées

⚠️ *Information générale, pas un avis juridique. Vérifier auprès du DBI.*

---

## Human-in-the-loop

1. L'agent prépare le brouillon : statut `pending_approval`
2. L'architecte clique **Approuver** ou **Refuser** dans Streamlit
3. Seul un dossier `approved` peut être **envoyé** (envoi simulé)
4. Tout est tracé : qui a validé, quand, date d'envoi

---

## Évaluation : 25 scénarios, LLM juge

5 permis (dont 1 adresse inexistante) · 10 documents (dont 1 réponse absente et 1 page manquante) · 6 dossiers (dont 1 envoi non validé et 1 projet inconnu) · 2 hors périmètre · **2 avec DataSF en panne**

| Métrique | Baseline simple prompt | Assistant |
|---|---|---|
| Taux de réussite (juge ≥ 4/5) | xx % | **xx %** |
| Conformité (avertissement + source) | xx % | **xx %** |
| Actions inutiles | x | **x** |

`agents-cli eval run` / `eval compare`

---

## Mise en production

- `agents-cli deploy` → **Cloud Run**
- Clé Gemini (AI Studio, gratuite) dans **Secret Manager** · Cloud Run à 0 instance au repos
- **Cloud Trace / Cloud Logging** : latence, tokens, appels d'outils
- **CI/CD** : lint et tests unitaires à chaque push, staging puis prod au merge

---

## Démo

1. « Quels permis existent au 781 20th Ave ? » → DataSF, 8 permis, statuts
2. « Quels documents pour un ADU ? » → réponse sourcée sf.gov
3. « Prépare le dossier du projet 9 » → brouillon **en attente** → **Approuver** → **Envoyer**
4. « Envoie le dossier n°1 » → refusé, car non approuvé

---

## Limites et suites

- Envoi simulé · SQLite → Cloud SQL · corpus à rafraîchir
- Suites : suivi des statuts de permis, checklists par type de travaux, IAP

**Merci ! Questions ?**
