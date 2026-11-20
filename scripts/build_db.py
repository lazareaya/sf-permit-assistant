"""Build the enterprise SQLite database from the Project 2 credit-card dataset.

Source: the Kaggle/OpenML ``creditcard.csv`` used by Project 2
(fraud-detection-mlops): 284,807 transactions, 492 frauds, features
``Time``, ``Amount``, ``V1``..``V28`` (PCA) and ``Class``.

We keep a 20,000-row sample (all 492 frauds + 19,508 legitimate transactions)
and add *synthetic* business columns the raw dataset does not have: a card id,
a customer, a timestamp, a merchant category and a country. Frauds are
concentrated on 40 "compromised" cards so that an investigation has a story.

Usage:
    uv run python scripts/build_db.py --csv "../../PROJET 2 - ML /fraud-detection-mlops/data/raw/creditcard.csv"
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "bank.db"
DEFAULT_CSV = (
    ROOT.parents[1]
    / "PROJET 2 - ML "
    / "fraud-detection-mlops"
    / "data"
    / "raw"
    / "creditcard.csv"
)

N_ROWS = 20_000
N_CARDS = 300
N_COMPROMISED = 40
SEED = 42
START = datetime(2026, 9, 1, 0, 0, 0)

V_COLS = [f"V{i}" for i in range(1, 29)]

FIRST = [
    "Camille",
    "Lucas",
    "Emma",
    "Hugo",
    "Léa",
    "Louis",
    "Chloé",
    "Gabriel",
    "Manon",
    "Arthur",
    "Inès",
    "Jules",
    "Sarah",
    "Adam",
    "Zoé",
    "Nathan",
    "Lina",
    "Tom",
    "Jade",
    "Noah",
    "Alice",
    "Rayan",
    "Clara",
    "Sacha",
]
LAST = [
    "Martin",
    "Bernard",
    "Dubois",
    "Thomas",
    "Robert",
    "Richard",
    "Petit",
    "Durand",
    "Leroy",
    "Moreau",
    "Simon",
    "Laurent",
    "Lefebvre",
    "Michel",
    "Garcia",
    "David",
    "Bertrand",
    "Roux",
    "Vincent",
    "Fournier",
    "Morel",
]
MCC_NORMAL = [
    "supermarché",
    "restaurant",
    "carburant",
    "pharmacie",
    "transport",
    "e-commerce",
    "habillement",
    "loisirs",
    "téléphonie",
]
MCC_FRAUD = [
    "e-commerce",
    "électronique",
    "jeux en ligne",
    "crypto-monnaie",
    "transfert d'argent",
    "bijouterie",
]
COUNTRIES_FRAUD = ["FR"] * 4 + ["NG", "RU", "BR", "US", "CN", "RO"]

SCHEMA = """
DROP TABLE IF EXISTS actions;
DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS cards;

CREATE TABLE cards (
    card_id        TEXT PRIMARY KEY,           -- e.g. CARD-00042
    customer_name  TEXT NOT NULL,
    customer_phone TEXT NOT NULL,              -- fictitious
    status         TEXT NOT NULL CHECK (status IN ('active', 'blocked')),
    daily_limit    REAL NOT NULL,
    opened_at      TEXT NOT NULL
);

CREATE TABLE transactions (
    tx_id             INTEGER PRIMARY KEY,
    card_id           TEXT NOT NULL REFERENCES cards(card_id),
    ts                TEXT NOT NULL,
    amount            REAL NOT NULL,
    merchant_category TEXT NOT NULL,
    country           TEXT NOT NULL,
    time_raw          REAL NOT NULL,           -- original "Time" feature
    {v_cols},
    label_is_fraud    INTEGER NOT NULL         -- ground truth, never shown to the agent
);
CREATE INDEX idx_tx_card ON transactions(card_id, ts);

CREATE TABLE actions (
    action_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id       TEXT NOT NULL REFERENCES cards(card_id),
    tx_id         INTEGER,
    action_type   TEXT NOT NULL,               -- block_card
    justification TEXT NOT NULL,
    procedure_id  TEXT NOT NULL,               -- cited internal procedure
    status        TEXT NOT NULL CHECK (status IN ('pending_approval', 'executed', 'rejected')),
    requested_by  TEXT NOT NULL,
    decided_by    TEXT,
    created_at    TEXT NOT NULL,
    decided_at    TEXT
);
""".format(v_cols=",\n    ".join(f"{c} REAL NOT NULL" for c in V_COLS))


def build(csv_path: Path, db_path: Path) -> None:
    rng = np.random.default_rng(SEED)
    df = pd.read_csv(csv_path)
    frauds = df[df["Class"] == 1]
    normals = df[df["Class"] == 0].sample(N_ROWS - len(frauds), random_state=SEED)
    sample = pd.concat([frauds, normals]).sort_values("Time").reset_index(drop=True)

    card_ids = [f"CARD-{i:05d}" for i in range(1, N_CARDS + 1)]
    compromised = rng.choice(card_ids, size=N_COMPROMISED, replace=False)

    is_fraud = sample["Class"].to_numpy() == 1
    cards_col = np.where(
        is_fraud,
        rng.choice(compromised, size=len(sample)),
        rng.choice(card_ids, size=len(sample)),
    )
    # Synthetic context with realistic noise: frauds *tend* to be in risky
    # categories / abroad (70 %), and 3-5 % of legitimate payments are too, so
    # these signals help but are never a perfect giveaway.
    n = len(sample)
    risky_mcc = np.where(is_fraud, rng.random(n) < 0.70, rng.random(n) < 0.03)
    mcc = np.where(risky_mcc, rng.choice(MCC_FRAUD, size=n), rng.choice(MCC_NORMAL, size=n))
    abroad = np.where(is_fraud, rng.random(n) < 0.60, rng.random(n) < 0.05)
    country = np.where(
        abroad,
        rng.choice([c for c in COUNTRIES_FRAUD if c != "FR"], size=n),
        rng.choice(["FR"], size=n),
    )
    # The dataset spans 2 days; stretch it over 30 days for a realistic history.
    ts = [
        (START + timedelta(seconds=float(t) * 15)).isoformat(timespec="seconds")
        for t in sample["Time"]
    ]

    tx = pd.DataFrame(
        {
            "tx_id": np.arange(100001, 100001 + len(sample)),
            "card_id": cards_col,
            "ts": ts,
            "amount": sample["Amount"].round(2),
            "merchant_category": mcc,
            "country": country,
            "time_raw": sample["Time"],
            **{c: sample[c] for c in V_COLS},
            "label_is_fraud": sample["Class"].astype(int),
        }
    )

    cards = pd.DataFrame(
        {
            "card_id": card_ids,
            "customer_name": [
                f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in card_ids
            ],
            "customer_phone": [
                f"+33 6 00 {i // 100:02d} {i % 100:02d} 00"
                for i in range(1, N_CARDS + 1)
            ],
            "status": "active",
            "daily_limit": rng.choice([1000.0, 2000.0, 3000.0, 5000.0], size=N_CARDS),
            "opened_at": [
                (datetime(2018, 1, 1) + timedelta(days=int(d))).date().isoformat()
                for d in rng.integers(0, 2800, size=N_CARDS)
            ],
        }
    )
    # A few cards are already blocked (previous incidents).
    cards.loc[cards["card_id"].isin(["CARD-00299", "CARD-00300"]), "status"] = "blocked"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as con:
        con.executescript(SCHEMA)
        cards.to_sql("cards", con, if_exists="append", index=False)
        tx.to_sql("transactions", con, if_exists="append", index=False)
        con.execute("VACUUM")
    print(
        f"Built {db_path}: {len(cards)} cards ({N_COMPROMISED} compromised), "
        f"{len(tx)} transactions ({int(is_fraud.sum())} frauds)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    build(args.csv, args.db)
