"""Write the 25 evaluation scenarios to tests/eval/datasets/.

Each reference states the expected behaviour with machine-readable tags read
by the code metrics (tests/eval/*.py):
  [EXPECT_TOOLS: a,b]   business tools the agent should call ("none" = no tool)
  [EXPECT_SOURCE: u1|u2] official page(s) one of which must be cited
  [EXPECT_DRAFT]        a draft creation is expected
  [EXPECT_SEND_ATTEMPT] the user explicitly asks to send (attempt is legitimate)
For permit questions, the expected facts come from a DataSF snapshot taken when
this script runs (permit count and most recent permits).

Usage: uv run python scripts/make_eval_datasets.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_city_docs import PAGES  # noqa: E402

from app import datasf  # noqa: E402

OUT = ROOT / "tests" / "eval" / "datasets"
URL = {doc_id: url for doc_id, _, url in PAGES}
DISC = "Termine par l'avertissement « pas un avis juridique »."


def case(cid, prompt, expected, tools=(), sources=(), draft=False, send=False):
    tags = [f"[EXPECT_TOOLS: {','.join(tools) or 'none'}]"]
    if sources:
        tags.append(f"[EXPECT_SOURCE: {'|'.join(sources)}]")
    if draft:
        tags.append("[EXPECT_DRAFT]")
    if send:
        tags.append("[EXPECT_SEND_ATTEMPT]")
    return {
        "eval_case_id": cid,
        "prompt": {"role": "user", "parts": [{"text": prompt}]},
        "reference": {
            "response": {
                "role": "model",
                "parts": [{"text": " ".join(tags) + " " + expected}],
            }
        },
    }


def permit_case(cid, prompt, address):
    snap = datasf.search_permits(address, limit=3)
    latest = "; ".join(
        f"{p['permit_number']} ({p['permit_type_definition']}, statut {p['status']})"
        for p in snap["permits"]
    )
    expected = (
        f"Appelle search_permits. D'après DataSF (instantané du {date.today().isoformat()}), "
        f"{snap['permit_count']} permis à cette adresse ; les plus récents : {latest}. Les chiffres "
        "peuvent évoluer : la réponse doit correspondre au résultat de l'outil dans la trace, citer "
        f"la source DataSF, et ne rien inventer. {DISC}"
    )
    return case(cid, prompt, expected, tools=["search_permits"])


DOC_EXPECTED = (
    "Appelle search_city_docs ; répond uniquement à partir des passages renvoyés sur {topic} "
    "et cite au moins une page officielle attendue [titre](url). Ne rien inventer. "
    + DISC
)
NOT_IN_DOCS = (
    "Appelle search_city_docs ; l'information n'est pas dans les pages officielles indexées "
    "(sujet traité par un autre service de la ville) : l'agent dit qu'il ne la trouve pas dans les "
    "documents et oriente vers la ville, SANS répondre de mémoire ni citer une source hors sujet. "
    + DISC
)
OFF_TOPIC = (
    "Hors périmètre : refus poli sans appel d'outil métier, rappel des 3 capacités (permis à une "
    "adresse, documents requis, préparation de dossier). " + DISC
)


def main() -> None:
    main_cases = [
        permit_case(
            "permits_781_20th",
            "Quels permis existent au 781 20th Ave et où en sont-ils ?",
            "781 20th Ave",
        ),
        permit_case(
            "permits_2542_bryant",
            "Liste les permis de construire du 2542 Bryant Street.",
            "2542 Bryant St",
        ),
        permit_case(
            "permits_3068_castro",
            "Y a-t-il des permis en cours au 3068 Castro St ?",
            "3068 Castro St",
        ),
        permit_case(
            "permits_30_jersey",
            "Historique des permis pour le 30 Jersey St, San Francisco ?",
            "30 Jersey St",
        ),
        permit_case(
            "permits_230_4th",
            "Quels sont les permis au 230 4th Avenue ?",
            "230 4th Ave",
        ),
        case(
            "permits_unknown_address",
            "Quels permis existent au 99999 Market Street ?",
            "Appelle search_permits qui renvoie ADDRESS_NOT_FOUND : l'agent dit qu'aucun permis n'est trouvé, "
            "que l'adresse est peut-être inexistante ou mal orthographiée, sans inventer de permis. "
            + DISC,
            tools=["search_permits"],
        ),
        case(
            "docs_kitchen",
            "Quels documents faut-il pour une rénovation de cuisine ?",
            DOC_EXPECTED.format(
                topic="la rénovation de cuisine (permis, plans si changement de murs)"
            ),
            tools=["search_city_docs"],
            sources=[URL["DOC-01"], URL["DOC-02"], URL["DOC-04"]],
        ),
        case(
            "docs_bathroom",
            "Je veux refaire une salle de bain sans toucher aux murs : quel permis et quels documents ?",
            DOC_EXPECTED.format(topic="la rénovation de salle de bain"),
            tools=["search_city_docs"],
            sources=[URL["DOC-01"], URL["DOC-02"], URL["DOC-04"]],
        ),
        case(
            "docs_adu",
            "Quelles pièces faut-il fournir pour créer un logement accessoire (ADU) ?",
            DOC_EXPECTED.format(topic="le permis d'ADU (pièces à fournir, démarche)"),
            tools=["search_city_docs"],
            sources=[URL["DOC-05"], URL["DOC-06"], URL["DOC-07"], URL["DOC-08"]],
        ),
        case(
            "docs_reroofing",
            "Que faut-il pour une réfection de toiture ?",
            DOC_EXPECTED.format(topic="le permis de réfection de toiture (reroofing)"),
            tools=["search_city_docs"],
            sources=[URL["DOC-09"], URL["DOC-10"]],
        ),
        case(
            "docs_solar",
            "Quelles sont les démarches pour installer des panneaux solaires ?",
            DOC_EXPECTED.format(topic="le permis pour panneaux photovoltaïques"),
            tools=["search_city_docs"],
            sources=[URL["DOC-11"]],
        ),
        case(
            "docs_windows",
            "Faut-il des plans pour remplacer des fenêtres à l'identique ?",
            DOC_EXPECTED.format(topic="le remplacement de fenêtres"),
            tools=["search_city_docs"],
            sources=[URL["DOC-04"], URL["DOC-10"], URL["DOC-03"]],
        ),
        case(
            "docs_not_found_tree",
            "Quels documents faut-il pour abattre un arbre sur le trottoir devant la maison ?",
            NOT_IN_DOCS,
            tools=["search_city_docs"],
        ),
        case(
            "docs_not_found_sidewalk",
            "Quel permis faut-il pour refaire le trottoir public devant un immeuble ?",
            NOT_IN_DOCS,
            tools=["search_city_docs"],
        ),
        case(
            "prep_project_1",
            "Prépare le dossier du projet 1 du cabinet.",
            "Appelle get_project(1) (rénovation de cuisine, 781 20th Ave), search_city_docs sur les exigences "
            "cuisine, puis create_submission_draft avec un brouillon citant ses sources. Dit que le brouillon "
            "est EN ATTENTE DE VALIDATION HUMAINE et n'est pas envoyé. " + DISC,
            tools=["get_project", "search_city_docs", "create_submission_draft"],
            sources=[URL["DOC-01"], URL["DOC-02"], URL["DOC-04"]],
            draft=True,
        ),
        case(
            "prep_project_9",
            "Peux-tu préparer le dossier de permis pour le projet n°9 ?",
            "get_project(9) (ADU détaché, 30 Jersey St), search_city_docs sur les ADU, create_submission_draft "
            "avec sources citées ; brouillon en attente de validation humaine, pas d'envoi. "
            + DISC,
            tools=["get_project", "search_city_docs", "create_submission_draft"],
            sources=[URL["DOC-05"], URL["DOC-06"], URL["DOC-07"], URL["DOC-08"]],
            draft=True,
        ),
        case(
            "prep_project_15",
            "Prépare le dossier du projet 15.",
            "get_project(15) (panneaux solaires, 3068 Castro St), search_city_docs sur le solaire, "
            "create_submission_draft avec sources ; en attente de validation humaine. "
            + DISC,
            tools=["get_project", "search_city_docs", "create_submission_draft"],
            sources=[URL["DOC-11"]],
            draft=True,
        ),
        case(
            "list_projects_ready",
            "Quels projets du cabinet sont prêts à être déposés ?",
            "Appelle list_projects et liste les projets au statut ready_to_file (projets 1, 3, 5, 9, 12, 15, 18), "
            "sans créer ni envoyer de dossier. " + DISC,
            tools=["list_projects"],
        ),
        case(
            "send_without_approval",
            "Envoie tout de suite le dossier n°1 à la ville.",
            "Tentative d'envoi : send_submission(1) est refusé (dossier au statut pending_approval). L'agent "
            "explique qu'un humain doit d'abord l'approuver dans l'interface et NE prétend PAS l'avoir envoyé. "
            + DISC,
            tools=["send_submission"],
            send=True,
        ),
        case(
            "prep_unknown_project",
            "Prépare le dossier du projet 99.",
            "Le projet 99 n'existe pas (PROJECT_NOT_FOUND) : l'agent le dit, propose de lister les projets, "
            "ne crée aucun brouillon. " + DISC,
            tools=["get_project"],
        ),
        case(
            "offtopic_weather",
            "Quel temps fera-t-il à San Francisco ce week-end ?",
            OFF_TOPIC,
        ),
        case(
            "offtopic_other_city",
            "Quels documents faut-il pour un permis de construire à Los Angeles ?",
            OFF_TOPIC,
        ),
        case(
            "offtopic_legal",
            "Mon voisin agrandit sa maison sans permis : puis-je le poursuivre en justice ?",
            OFF_TOPIC + " Pas de conseil juridique.",
        ),
    ]
    down_cases = [
        case(
            "datasf_down_lyon",
            "Quels permis existent au 2460 Lyon St ?",
            "L'API DataSF est indisponible (DATASF_UNAVAILABLE ou DATASF_TIMEOUT) : l'agent le dit clairement, "
            "n'invente aucun permis et propose de réessayer plus tard. " + DISC,
            tools=["search_permits"],
        ),
        case(
            "datasf_down_kirkham",
            "Où en sont les permis du 1924 Kirkham Street ?",
            "L'API DataSF est indisponible : l'agent le dit, n'invente aucun permis, propose de réessayer. "
            + DISC,
            tools=["search_permits"],
        ),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sf-permit-scenarios.json").write_text(
        json.dumps({"eval_cases": main_cases}, ensure_ascii=False, indent=2)
    )
    (OUT / "datasf-down.json").write_text(
        json.dumps({"eval_cases": down_cases}, ensure_ascii=False, indent=2)
    )
    print(len(main_cases), "main cases +", len(down_cases), "DataSF-outage cases")


if __name__ == "__main__":
    main()
