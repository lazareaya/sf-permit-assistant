# PROC-07 — Mode dégradé : outil de scoring indisponible

> Document fictif rédigé pour un projet pédagogique.

Si l'API de scoring de fraude ne répond pas ou renvoie une erreur :
1. ne **jamais** inventer ni estimer un score ;
2. ne **pas** proposer de blocage sur la seule base de l'historique, sauf signaux aggravants multiples et manifestes ;
3. réaliser l'analyse de l'historique (PROC-03) et la transmettre ;
4. escalader au niveau 2 (PROC-05) si le montant dépasse 500 €, sinon placer l'alerte en file de revue manuelle ;
5. signaler l'indisponibilité à l'équipe MLOps.
