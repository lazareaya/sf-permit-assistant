"""Build data/projects.db: the projects of a FICTITIOUS architecture firm.

Addresses are real San Francisco addresses taken from the public DataSF
Building Permits dataset (so `search_permits` finds real permit history), but
clients, descriptions, costs and statuses are invented.

Usage: uv run python scripts/build_projects_db.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "projects.db"

SCHEMA = """
DROP TABLE IF EXISTS submissions;
DROP TABLE IF EXISTS projects;
CREATE TABLE projects (
    id             INTEGER PRIMARY KEY,
    client         TEXT NOT NULL,
    address        TEXT NOT NULL,
    work_type      TEXT NOT NULL CHECK (work_type IN
                   ('kitchen_remodel','bathroom_remodel','adu','reroofing','solar','windows')),
    description    TEXT NOT NULL,
    estimated_cost REAL NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('design','ready_to_file','filed'))
);
CREATE TABLE submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    draft       TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('pending_approval','approved','rejected','sent')),
    created_at  TEXT NOT NULL,
    decided_by  TEXT,
    decided_at  TEXT,
    sent_at     TEXT
);
"""

# (client [fictitious], real SF address, work_type, description, cost, status)
PROJECTS = [
    (
        "Client fictif A. Moreau",
        "781 20th Ave",
        "kitchen_remodel",
        "Rénovation de cuisine sans modification des murs : nouveaux meubles, plan de travail, électroménager.",
        65000,
        "ready_to_file",
    ),
    (
        "Client fictif B. Chen",
        "2460 Lyon St",
        "kitchen_remodel",
        "Cuisine ouverte sur le séjour : suppression d'une cloison non porteuse.",
        120000,
        "design",
    ),
    (
        "Client fictif C. Duarte",
        "153 Sickles Ave",
        "kitchen_remodel",
        "Remplacement à l'identique de la cuisine existante.",
        38000,
        "ready_to_file",
    ),
    (
        "Client fictif D. Okafor",
        "2126 18th St",
        "kitchen_remodel",
        "Rénovation de cuisine avec déplacement de l'évier et nouveaux circuits électriques.",
        85000,
        "design",
    ),
    (
        "Client fictif E. Larsen",
        "1900 15th Ave",
        "bathroom_remodel",
        "Rénovation de salle de bain sans changement de plan.",
        30000,
        "ready_to_file",
    ),
    (
        "Client fictif F. Romero",
        "245 Silver Ave",
        "bathroom_remodel",
        "Ajout d'une douche dans une salle d'eau existante.",
        42000,
        "design",
    ),
    (
        "Client fictif G. Patel",
        "2542 Bryant St",
        "bathroom_remodel",
        "Rénovation de deux salles de bain à l'identique.",
        55000,
        "filed",
    ),
    (
        "Client fictif H. Kowalski",
        "40 Sycamore St",
        "adu",
        "Création d'un logement accessoire (ADU) au rez-de-chaussée, dans l'ancien garage.",
        280000,
        "design",
    ),
    (
        "Client fictif I. Nakamura",
        "30 Jersey St",
        "adu",
        "ADU détaché en fond de parcelle.",
        350000,
        "ready_to_file",
    ),
    (
        "Client fictif J. Haddad",
        "1924 Kirkham St",
        "adu",
        "ADU dans le sous-sol existant.",
        210000,
        "design",
    ),
    (
        "Client fictif K. Silva",
        "1527 10th Ave",
        "adu",
        "Conversion du rez-de-chaussée en ADU avec entrée indépendante.",
        260000,
        "filed",
    ),
    (
        "Client fictif L. Dubois",
        "31 Beatrice Ln",
        "reroofing",
        "Réfection de la toiture sans remplacement de la charpente.",
        18000,
        "ready_to_file",
    ),
    (
        "Client fictif M. Ivanova",
        "1145 Munich St",
        "reroofing",
        "Réfection complète de la toiture avec remplacement du voligeage.",
        32000,
        "design",
    ),
    (
        "Client fictif N. O'Brien",
        "12 Chattanooga St",
        "reroofing",
        "Réfection de toiture à l'identique.",
        22000,
        "filed",
    ),
    (
        "Client fictif O. Mensah",
        "3068 Castro St",
        "solar",
        "Installation de panneaux photovoltaïques en toiture (5 kW), sans batterie.",
        21000,
        "ready_to_file",
    ),
    (
        "Client fictif P. Fischer",
        "66 Bradford St",
        "solar",
        "Panneaux photovoltaïques avec batterie de stockage.",
        34000,
        "design",
    ),
    (
        "Client fictif Q. Tanaka",
        "207 Los Palmos Dr",
        "solar",
        "Installation photovoltaïque avec mise à niveau du tableau électrique.",
        29000,
        "design",
    ),
    (
        "Client fictif R. Castillo",
        "223 Richland Ave",
        "windows",
        "Remplacement des fenêtres à l'identique (mêmes dimensions, mêmes emplacements).",
        16000,
        "ready_to_file",
    ),
    (
        "Client fictif S. Novak",
        "1528 11th Ave",
        "windows",
        "Création de deux nouvelles ouvertures en façade arrière.",
        27000,
        "design",
    ),
    (
        "Client fictif T. Wright",
        "2610 Pacific Ave",
        "windows",
        "Remplacement des fenêtres en façade sur rue.",
        24000,
        "design",
    ),
]

SEED_SUBMISSIONS = [
    # (project_id, draft, status, created_at, decided_by, decided_at, sent_at)
    (
        5,
        "Brouillon de dossier — rénovation de salle de bain, 1900 15th Ave (exemple de démonstration).",
        "pending_approval",
        "2026-11-18T10:00:00+00:00",
        None,
        None,
        None,
    ),
    (
        12,
        "Brouillon de dossier — réfection de toiture, 31 Beatrice Ln (exemple de démonstration).",
        "approved",
        "2026-11-17T09:00:00+00:00",
        "architecte référent",
        "2026-11-17T15:00:00+00:00",
        None,
    ),
    (
        7,
        "Dossier envoyé — salles de bain, 2542 Bryant St (exemple de démonstration).",
        "sent",
        "2026-11-10T09:00:00+00:00",
        "architecte référent",
        "2026-11-10T11:00:00+00:00",
        "2026-11-10T11:05:00+00:00",
    ),
]


def build(db: Path = DB) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as con:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO projects (id, client, address, work_type, description, estimated_cost, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(i, *p) for i, p in enumerate(PROJECTS, start=1)],
        )
        con.executemany(
            "INSERT INTO submissions (project_id, draft, status, created_at, decided_by, decided_at, sent_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            SEED_SUBMISSIONS,
        )
    print(
        f"Built {db}: {len(PROJECTS)} projects, {len(SEED_SUBMISSIONS)} seed submissions"
    )


if __name__ == "__main__":
    build()
