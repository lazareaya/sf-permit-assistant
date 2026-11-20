# PROC-02 — Seuils d'alerte du score de fraude

> Document fictif rédigé pour un projet pédagogique.

Le score provient du modèle de détection de fraude (XGBoost) servi par l'API de scoring interne. Il s'agit d'une probabilité entre 0 et 1. Le modèle est calibré pour un rappel d'environ 83 % et une précision d'environ 66 %.

| Score | Niveau | Action attendue |
|---|---|---|
| ≥ 0,90 | Critique | Proposer un blocage de carte (PROC-01), soumis à validation humaine |
| entre le seuil du modèle (≈ 0,09) et 0,90 | Élevé | Contacter le client pour vérification (PROC-04) avant toute décision ; blocage seulement si signaux aggravants (PROC-03) |
| < seuil du modèle | Faible | Aucune action. Classer l'alerte comme « non confirmée » |

Le score seul ne suffit jamais : il est toujours croisé avec l'historique de la carte (PROC-03).
