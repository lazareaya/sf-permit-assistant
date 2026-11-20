---
marp: true
theme: default
paginate: true
size: 16:9
style: |
  section { font-size: 26px; }
  h1 { color: #1a4d8f; }
  table { font-size: 22px; }
---

<!-- Export : npx @marp-team/marp-cli slides.md --pptx   (ou --pdf), ou l'extension VS Code « Marp for VS Code » -->

# Agent IA d'analyse de fraude
### Google ADK · Gemini · MCP · RAG · Cloud Run

Cours GenAI, sujet 1 : agent avec outils et skills

---

## Le problème

- Un analyste fraude instruit des dizaines d'alertes par jour
- Pour chacune : historique, score du modèle, procédure interne, décision
- Une erreur coûte cher dans les deux sens : **fraude ratée** ou **client bloqué à tort**

**Notre agent instruit l'alerte et prépare la décision.
L'humain garde la décision irréversible.**

---

## Ce que fait l'agent

1. Historique de la carte → **base SQL**
2. Score de fraude → **mon modèle ML du projet 2** (XGBoost, via un serveur **MCP**)
3. Procédure applicable → **RAG** (Gemini embeddings + Chroma)
4. Action proposée, **avec la procédure citée**
5. **Validation humaine** avant toute exécution

---

## Architecture

```
Streamlit ──HTTP──> FastAPI (ADK) ──> Agent Gemini
                                        ├─ constructeur de contexte + 3 skills
                                        ├─ garde-fous (callbacks)
                                        ├─ McpToolset ──stdio──> Serveur MCP ──> SQLite
                                        │                              └──HTTPS──> API fraude (projet 2)
                                        └─ search_procedures ──> Chroma
Cloud Run × 2 · Secret Manager · Cloud Trace · CI/CD GitHub Actions
```

Squelette généré avec **google/agents-cli**

---

## Registre de skills et constructeur de contexte

| Skill | Outils autorisés |
|---|---|
| investigation | get_card_status, get_transaction_history, score_transaction |
| procedure_lookup | search_procedures |
| decision_prep | block_card, get_card_status |

Le prompt système est **reconstruit avant chaque appel** : règles + catalogue + instructions de la **seule skill active** + faits du dossier utiles à cette skill.

---

## Garde-fous

- Au maximum **10 appels d'outils** par demande
- **Validation Pydantic** de chaque argument
- Outil **hors de la skill active** : refusé
- **Carte inconnue** : refus, aucune action
- **Pas de `block_card` sans procédure** retrouvée par le RAG

Plus une défense en profondeur côté serveur MCP

---

## Human-in-the-loop

- `block_card` **n'exécute rien** : il crée une demande `pending_approval`
- L'analyste clique **Approuver** ou **Refuser** dans Streamlit
- Seule l'approbation bloque la carte, et chaque décision est tracée (qui, quand, quelle procédure)

---

## Évaluation : 25 scénarios, LLM juge

7 fraudes · 6 normales · 2 scores intermédiaires · 3 identifiants inconnus · 1 carte déjà bloquée · 3 hors sujet · **3 avec l'API de fraude en panne**

| Métrique | Baseline simple prompt | Agent |
|---|---|---|
| Taux de réussite (juge ≥ 4/5) | xx % | **xx %** |
| Actions inutiles | x | **x** |
| Erreurs d'outils | — | x |

`agents-cli eval run` / `eval compare`

---

## Mise en production

- `agents-cli deploy` → **Cloud Run** (agent) + API du projet 2 sur Cloud Run
- Clé API dans **Secret Manager**, jamais dans le code
- **Cloud Trace / Cloud Logging** : latence, tokens, appels d'outils
- **CI/CD** : lint + 44 tests unitaires à chaque push, déploiement staging → prod au merge

---

## Démo

1. « Alerte fraude sur la transaction 110613 »
   → score 0,9999, historique, PROC-01, demande de blocage **en attente**
2. Clic sur **Approuver** → carte bloquée
3. « Bloque la carte CARD-99999 » → refus (PROC-06)

---

## Limites et suites

- SQLite embarqué → Cloud SQL en production
- Données métier synthétiques, procédures fictives
- Suites : Memory Bank, `eval optimize`, IAP

**Merci ! Questions ?**
