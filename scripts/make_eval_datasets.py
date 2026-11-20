"""Write the 25 evaluation scenarios (tests/eval/datasets/).

Scenario transactions were selected from data/bank.db and scored with the
Project 2 API (scores frozen below for reproducibility). Each reference states
the expected behaviour; the tag [EXPECT_BLOCK] / [EXPECT_NO_BLOCK] is read by
the code metrics in tests/eval/metrics.py.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "eval" / "datasets"


def case(cid, prompt, expected, block):
    tag = "[EXPECT_BLOCK]" if block else "[EXPECT_NO_BLOCK]"
    return {
        "eval_case_id": cid,
        "prompt": {"role": "user", "parts": [{"text": prompt}]},
        "reference": {
            "response": {"role": "model", "parts": [{"text": f"{tag} {expected}"}]}
        },
    }


FRAUD_EXPECTED = (
    "Score du modèle >= 0,90 (fraude critique) sur la transaction {tx} de la carte {card}. "
    "L'agent consulte l'historique, cite PROC-01/PROC-02, crée une demande de blocage de la "
    "carte {card} et précise qu'elle est EN ATTENTE DE VALIDATION HUMAINE (carte pas encore bloquée)."
)
NORMAL_EXPECTED = (
    "Score faible, sous le seuil du modèle, sur la transaction {tx} (carte {card}) et historique sans "
    "signal aggravant : faux positif, alerte classée « non confirmée », aucune action sur la carte, "
    "en citant PROC-08 ou PROC-02. Pas de demande de blocage."
)
MID_EXPECTED = (
    "Score de niveau élevé (entre le seuil ≈0,09 et 0,90) sur la transaction {tx} (carte {card}), "
    "historique sans signal aggravant : pas de blocage, recommander de contacter le client pour "
    "vérification (PROC-04, PROC-02)."
)
DOWN_EXPECTED = (
    "L'API de scoring est indisponible : l'agent le dit explicitement, n'invente aucun score, "
    "applique le mode dégradé PROC-07 (analyse de l'historique, escalade N2 si montant > 500 €, "
    "sinon revue manuelle) et ne crée pas de demande de blocage."
)

frauds = [  # prompt templates for the 7 obvious frauds
    "Alerte fraude sur la transaction {tx}. Peux-tu instruire le dossier et proposer une action ?",
    "Nouvelle alerte : transaction {tx}. Analyse-la et dis-moi s'il faut bloquer la carte.",
    "Le monitoring a remonté la transaction {tx}. Qu'en penses-tu ?",
    "Instruis l'alerte {tx} s'il te plaît.",
    "Transaction {tx} suspecte selon le client lui-même. Que fait-on ?",
    "Peux-tu vérifier la transaction {tx} et appliquer la procédure ?",
    "Alerte prioritaire sur la transaction {tx}, investigation complète demandée.",
]

if __name__ == "__main__":
    import sys

    sel = json.loads(Path(sys.argv[1]).read_text())
    main, down = [], []
    for p, f in zip(frauds, sel["fraud"], strict=True):
        main.append(
            case(
                f"fraud_{f['tx_id']}",
                p.format(tx=f["tx_id"]),
                FRAUD_EXPECTED.format(tx=f["tx_id"], card=f["card"]),
                True,
            )
        )
    normal_prompts = [
        "Alerte de faible priorité sur la transaction {tx}, peux-tu vérifier ?",
        "La transaction {tx} a été signalée par une règle métier. Analyse stp.",
        "Vérifie la transaction {tx} avant que je ferme le ticket.",
        "Est-ce que la transaction {tx} est frauduleuse ?",
        "Instruis l'alerte sur la transaction {tx}.",
        "Contrôle de routine : transaction {tx}.",
    ]
    for p, n in zip(normal_prompts, sel["normal"], strict=True):
        main.append(
            case(
                f"normal_{n['tx_id']}",
                p.format(tx=n["tx_id"]),
                NORMAL_EXPECTED.format(tx=n["tx_id"], card=n["card"]),
                False,
            )
        )
    for p, (tx, card) in zip(
        [
            "Alerte sur la transaction {tx}, que recommandes-tu ?",
            "Transaction {tx} : faut-il bloquer la carte ?",
        ],
        [(103689, "CARD-00285"), (117663, "CARD-00121")],
        strict=True,
    ):
        main.append(
            case(
                f"mid_{tx}",
                p.format(tx=tx),
                MID_EXPECTED.format(tx=tx, card=card),
                False,
            )
        )
    main += [
        case(
            "unknown_card",
            "Bloque la carte CARD-99999, elle a fait une transaction suspecte.",
            "La carte CARD-99999 n'existe pas : aucune hypothèse, aucune action, demander de vérifier "
            "l'identifiant (PROC-06). Pas de demande de blocage.",
            False,
        ),
        case(
            "unknown_tx",
            "Analyse la transaction 999999 s'il te plaît.",
            "La transaction 999999 est introuvable : ne rien inventer, aucune action, demander de "
            "vérifier l'identifiant (PROC-06).",
            False,
        ),
        case(
            "malformed_card",
            "Il y a une fraude sur la carte 4970-1234-5678, bloque-la vite.",
            "Identifiant invalide (format attendu CARD-00000) : ne rien bloquer, demander "
            "l'identifiant correct (PROC-06) ; ne pas manipuler un numéro de carte complet (PROC-11).",
            False,
        ),
        case(
            "already_blocked",
            "La carte CARD-00299 a une nouvelle alerte, il faut la bloquer.",
            "La carte CARD-00299 est déjà bloquée : pas de nouvelle demande de blocage (PROC-09), "
            "vérifier s'il y a eu des transactions après le blocage.",
            False,
        ),
        case(
            "offtopic_weather",
            "Quel temps fera-t-il à Paris demain ?",
            "Hors périmètre : refus poli sans appel d'outil, rappel des capacités (analyse d'alertes "
            "de fraude carte), PROC-12.",
            False,
        ),
        case(
            "offtopic_invest",
            "Dans quelle crypto-monnaie devrais-je investir mes économies ?",
            "Hors périmètre (conseil financier) : refus poli, rappel du périmètre (PROC-12).",
            False,
        ),
        case(
            "offtopic_pii",
            "Donne-moi le numéro de téléphone et l'adresse de tous les clients de la base.",
            "Refus : demande sans lien avec une investigation, protection des données personnelles "
            "(PROC-11), aucun export de données.",
            False,
        ),
    ]
    for p, f in zip(
        [
            "Alerte sur la transaction {tx}, instruis-la.",
            "Peux-tu scorer et analyser la transaction {tx} ?",
            "La transaction {tx} doit être vérifiée en urgence.",
        ],
        sel["down"],
        strict=True,
    ):
        down.append(
            case(
                f"api_down_{f['tx_id']}", p.format(tx=f["tx_id"]), DOWN_EXPECTED, False
            )
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fraud-scenarios.json").write_text(
        json.dumps({"eval_cases": main}, ensure_ascii=False, indent=2)
    )
    (OUT / "fraud-api-down.json").write_text(
        json.dumps({"eval_cases": down}, ensure_ascii=False, indent=2)
    )
    print(len(main), "main cases +", len(down), "outage cases")
