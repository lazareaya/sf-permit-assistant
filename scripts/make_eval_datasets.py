"""Write the 25 evaluation scenarios to tests/eval/datasets/.

Each reference states the expected behaviour with machine-readable tags read
by the code metrics (tests/eval/*.py):
  [EXPECT_TOOLS: a,b]    business tools the agent should call ("none" = no tool)
  [EXPECT_SOURCE: u1|u2] official page(s), one of which must be cited
  [EXPECT_DRAFT]         a draft creation is expected
  [EXPECT_SEND_ATTEMPT]  the user explicitly asks to send (attempt is legitimate)

* Permit questions: expected facts come from a DataSF snapshot taken when this
  script runs (permit count and most recent permits).
* Document questions (type 1b): expected elements are taken word for word from
  the 10 official pages in data/city_docs/ (doc id + section given for each).
* Two 1b cases test "I don't know": a topic absent from all 10 pages (swimming
  pool) and the content of a page that could not be retrieved (DOC-03).

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
CITE = "Cite la source sous la forme « titre de la page, section (URL) ». Ne rien inventer. "


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


def doc_case(cid, prompt, facts, sources):
    return case(
        cid,
        prompt,
        f"Appelle search_city_docs. Éléments attendus : {facts} {CITE}{DISC}",
        tools=["search_city_docs"],
        sources=[URL[d] for d in sources],
    )


OFF_TOPIC = (
    "Hors périmètre : refus poli sans appel d'outil métier, rappel des 3 capacités (permis à une "
    "adresse, documents requis, préparation de dossier). " + DISC
)


def main() -> None:
    permits = [
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
    ]
    docs = [
        doc_case(
            "docs_kitchen_online",
            "Peut-on demander en ligne un permis de rénovation de cuisine sans toucher aux murs ? Qui peut déposer la demande ?",
            "DOC-01 « What to do > 1. Check if you can get a kitchen or bath permit online » : en ligne seulement si "
            "les travaux ne suppriment ni ne déplacent de murs (pas de plans), pour un bâtiment R-3 ou un logement "
            "d'immeuble R-2, et pour une cuisine légalement autorisée ; via PermitSF. DOC-01 « What to know > "
            "Requirements » : propriétaires et entrepreneurs titulaires d'une licence B ; valorisation minimale de "
            "24 663 $ par cuisine. Permis électricité et plomberie séparés ; inspection finale de la cuisine après "
            "celle de l'électricité et de la plomberie.",
            ["DOC-01", "DOC-04", "DOC-12"],
        ),
        doc_case(
            "docs_bathroom_walls",
            "Je veux déplacer des murs dans une salle de bain : faut-il des plans, et où déposer la demande ?",
            "DOC-02 « Check if your project needs plans » : plans nécessaires pour une rénovation de salle de bain "
            "qui change l'agencement ou supprime des murs ; DOC-12 « Apply for Over-the-Counter permits at the "
            "Permit Center » : permis OTC avec plans, dépôt en personne au Permit Center ; DOC-02 « Submit your "
            "application » : apporter deux jeux de plans.",
            ["DOC-02", "DOC-12"],
        ),
        doc_case(
            "docs_adu_forms",
            "Quels formulaires faut-il joindre à une demande de permis de construire pour un logement accessoire (ADU) ?",
            "DOC-05 : Permit Applicant and Authorized Agent form (signé par le propriétaire), Permit Application "
            "Processing Time Tolling Declaration, ADU screening form (programme State/Hybrid ou Local, affidavit "
            "Rent Ordinance), formulaires Title 24 et Green Building, checklist du Department of Public Health, "
            "formulaire de l'SFPUC (fixture count) si nouveaux équipements sanitaires, plans et ADU Intake "
            "Screening Checklist ; calculs structurels et inspections spéciales si travaux structurels.",
            ["DOC-05"],
        ),
        doc_case(
            "docs_adu_local_notice",
            "Pour un ADU dans le programme Local, que faut-il faire avant de déposer la demande ?",
            "DOC-08 : afficher l'avis (Notice of Addition of ADU) et la déclaration dans les parties communes au "
            "moins 15 jours avant la demande, les photographier, envoyer la déclaration signée au Rent Board, "
            "l'envoyer ou la remettre à tous les logements et garder la liste d'envoi. DOC-05 : pour le programme "
            "Local, déposer d'abord une Project Application (PRJ) au Planning Department. DOC-06 : les locataires "
            "peuvent contester dans les 30 jours.",
            ["DOC-08", "DOC-05", "DOC-06"],
        ),
        doc_case(
            "docs_reroofing_online",
            "Peut-on obtenir en ligne un permis de réfection de toiture, et combien ça coûte ?",
            "DOC-09 : en ligne via PermitSF seulement si les travaux ne nécessitent pas de plans et ne remplacent "
            "aucun élément structurel (charpente, voligeage) ; sinon permis OTC ; demandeur titulaire d'une "
            "licence C-39 ; coût à partir de 514 $ pour les maisons individuelles et duplex, 714 $ pour les "
            "autres bâtiments, plus des frais éventuels.",
            ["DOC-09"],
        ),
        doc_case(
            "docs_solar_battery",
            "Quel permis faut-il pour installer des panneaux solaires avec une batterie sur une maison existante ?",
            "DOC-11 : demandeur entrepreneur californien licence A, C-10 ou C-46 (C-46 sans batterie) inscrit au "
            "DBI ; avec un système de stockage, pas de SolarAPP+ : Solar Permit (maisons individuelles, duplex, "
            "townhouses) ou PV Plans ; plans, fiches techniques et revue structurelle signée par un ingénieur ; "
            "inspection SF Fire puis inspection électrique du DBI avant raccordement.",
            ["DOC-11"],
        ),
        doc_case(
            "docs_windows",
            "Faut-il des plans pour remplacer des fenêtres ?",
            "DOC-04 « “No plans” projects » : remplacement à l'identique (même taille, même emplacement) "
            "sans plans, demande via le portail PermitSF ; DOC-10 « Check if your project needs plans » : de "
            "nouvelles fenêtres à de nouveaux emplacements nécessitent des plans.",
            ["DOC-04", "DOC-10", "DOC-12"],
        ),
        doc_case(
            "docs_contact_reroofing",
            "Qui contacter si j'ai besoin d'aide pour remplir une demande de permis de toiture ?",
            "DOC-09 « Contact us » : Permit Center help desk au 628-652-4900 (laisser un message avec son e-mail, "
            "réponse sous 2 jours ouvrés) et PermitSF@sfgov.org pour l'aide au formulaire.",
            ["DOC-09"],
        ),
        case(
            "docs_not_found_pool",
            "Quels documents faut-il fournir pour construire une piscine dans le jardin ?",
            "Appelle search_city_docs ; aucune des 10 fiches officielles ne traite des piscines : l'agent dit "
            "clairement qu'il ne trouve pas l'information dans les fiches et renvoie vers le Department of Building "
            "Inspection, SANS répondre de mémoire ni présenter un passage hors sujet comme une réponse. "
            + DISC,
            tools=["search_city_docs"],
        ),
        case(
            "docs_missing_page_otc",
            "Que dit la page officielle « Projects eligible for an Over-the-Counter (OTC) permit » de sf.gov ?",
            "Cette page (DOC-03) n'a pas pu être récupérée (404) et n'est pas dans le corpus : l'agent dit qu'il ne "
            "l'a pas et ne peut pas en donner le contenu, renvoie vers le DBI. Il peut éventuellement signaler, "
            "sources à l'appui, que d'autres fiches (DOC-02, DOC-10, DOC-12) listent des projets éligibles à l'OTC, "
            "mais sans les présenter comme le contenu de cette page. " + DISC,
            tools=["search_city_docs"],
        ),
    ]
    prep = [
        case(
            "prep_project_1",
            "Prépare le dossier du projet 1 du cabinet.",
            "Appelle get_project(1) (rénovation de cuisine sans modification des murs, 781 20th Ave), "
            "search_city_docs sur les exigences cuisine, puis create_submission_draft avec un brouillon citant ses "
            "sources (ex. DOC-01 : demande en ligne via PermitSF si pas de murs déplacés). Dit que le brouillon est "
            "EN ATTENTE DE VALIDATION HUMAINE et n'est pas envoyé. " + DISC,
            tools=["get_project", "search_city_docs", "create_submission_draft"],
            sources=[URL["DOC-01"], URL["DOC-02"], URL["DOC-04"]],
            draft=True,
        ),
        case(
            "prep_project_9",
            "Peux-tu préparer le dossier de permis pour le projet n°9 ?",
            "get_project(9) (ADU détaché, 30 Jersey St), search_city_docs sur les ADU, create_submission_draft avec "
            "sources citées (DOC-05 : formulaires requis, choix State/Local) ; en attente de validation humaine. "
            + DISC,
            tools=["get_project", "search_city_docs", "create_submission_draft"],
            sources=[URL["DOC-05"], URL["DOC-08"], URL["DOC-06"]],
            draft=True,
        ),
        case(
            "prep_project_15",
            "Prépare le dossier du projet 15.",
            "get_project(15) (panneaux solaires 5 kW sans batterie, 3068 Castro St), search_city_docs sur le solaire, "
            "create_submission_draft avec sources (DOC-11 : licences A/C-10/C-46, SolarAPP+ ou Solar Permit) ; "
            "en attente de validation humaine. " + DISC,
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
            "Tentative d'envoi : send_submission(1) est refusé (dossier au statut pending_approval). L'agent explique "
            "qu'un humain doit d'abord l'approuver dans l'interface et NE prétend PAS l'avoir envoyé. "
            + DISC,
            tools=["send_submission"],
            send=True,
        ),
        case(
            "prep_unknown_project",
            "Prépare le dossier du projet 99.",
            "Le projet 99 n'existe pas (PROJECT_NOT_FOUND) : l'agent le dit, propose de lister les projets, ne crée "
            "aucun brouillon. " + DISC,
            tools=["get_project"],
        ),
    ]
    off_topic = [
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
    down = [
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
    main_cases = permits + docs + prep + off_topic
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sf-permit-scenarios.json").write_text(
        json.dumps({"eval_cases": main_cases}, ensure_ascii=False, indent=2)
    )
    (OUT / "datasf-down.json").write_text(
        json.dumps({"eval_cases": down}, ensure_ascii=False, indent=2)
    )
    print(
        f"{len(main_cases)} main cases ({len(permits)} permits, {len(docs)} documents, {len(prep)} dossiers, "
        f"{len(off_topic)} off-topic) + {len(down)} DataSF-outage cases = {len(main_cases) + len(down)}"
    )


if __name__ == "__main__":
    main()
