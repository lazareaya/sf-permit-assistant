# PROC-01 — Blocage d'une carte suspectée de fraude

> Document fictif rédigé pour un projet pédagogique. Ne reflète les règles d'aucune banque réelle.

## Quand bloquer
Un blocage de carte est proposé lorsque le score de fraude du modèle est **supérieur ou égal à 0,90** sur au moins une transaction récente, OU lorsque le score dépasse le seuil du modèle et qu'au moins un signal aggravant est présent (voir PROC-03).

## Qui décide
L'agent d'analyse ne bloque jamais une carte lui-même. Il rédige une **demande de blocage** contenant : l'identifiant de la carte, la transaction en cause, le score, les signaux observés et la procédure appliquée. Un analyste humain (niveau 1 ou plus) approuve ou refuse la demande.

## Après approbation
La carte passe au statut « bloquée ». Le client est prévenu selon PROC-04. Une nouvelle carte peut être commandée après confirmation de l'identité du client.

## Ce qu'il ne faut pas faire
- Ne pas bloquer une carte sur la seule base du montant.
- Ne pas bloquer une carte déjà bloquée (doublon).
- Ne pas proposer de blocage sans citer la procédure appliquée.
