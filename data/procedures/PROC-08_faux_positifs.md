# PROC-08 — Gestion des faux positifs

> Document fictif rédigé pour un projet pédagogique.

Une alerte est un faux positif lorsque le score est faible (sous le seuil du modèle) et que l'historique ne présente aucun signal aggravant. Dans ce cas :
- l'alerte est classée « non confirmée » ;
- aucune action n'est engagée sur la carte ;
- le client n'est pas contacté.

Bloquer à tort une carte légitime dégrade fortement l'expérience client : environ un tiers des alertes du modèle sont des faux positifs (précision ≈ 66 %).
