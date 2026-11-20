"""Client for the public DataSF "Building Permits" dataset (Socrata SoQL API).

Dataset: https://data.sf.gov/resource/i98e-djp9.json (license: ODC PDDL).

* Address parsing: "781 20th Ave, San Francisco" -> street_number=781,
  street_name=20th (DataSF stores single-digit ordinals as "04th").
* SoQL query on street_number + street_name, ordered by status_date.
* Rows are de-duplicated by permit_number (the dataset has one row per address
  of a permit).
* Local SQLite cache with a TTL (default 24 h). If DataSF is down, a stale
  cached answer is returned and flagged as such.
* Errors are returned as codes: INVALID_ADDRESS, ADDRESS_NOT_FOUND,
  DATASF_TIMEOUT, DATASF_UNAVAILABLE.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

import httpx

from app import config

SOURCE = "DataSF — Building Permits (i98e-djp9), https://data.sf.gov/d/i98e-djp9"
FIELDS = [
    "permit_number",
    "permit_type_definition",
    "status",
    "status_date",
    "filed_date",
    "issued_date",
    "street_number",
    "street_name",
    "street_suffix",
    "description",
    "estimated_cost",
    "neighborhoods_analysis_boundaries",
    "zipcode",
    "data_as_of",
]
SUFFIXES = {
    "street": "St",
    "st": "St",
    "avenue": "Av",
    "ave": "Av",
    "av": "Av",
    "boulevard": "Bl",
    "blvd": "Bl",
    "bl": "Bl",
    "drive": "Dr",
    "dr": "Dr",
    "lane": "Ln",
    "ln": "Ln",
    "way": "Wy",
    "wy": "Wy",
    "road": "Rd",
    "rd": "Rd",
    "terrace": "Tr",
    "ter": "Tr",
    "tr": "Tr",
    "place": "Pl",
    "pl": "Pl",
    "court": "Ct",
    "ct": "Ct",
    "alley": "Al",
    "al": "Al",
    "highway": "Hy",
    "hwy": "Hy",
}
ADDRESS_RE = re.compile(r"^\s*(\d{1,5})[A-Za-z]?\s+(.+?)\s*$")


class DataSFError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def parse_address(address: str) -> dict[str, str | None]:
    """Split a free-text SF address into DataSF fields."""
    street_part = address.split(",")[0].strip()
    m = ADDRESS_RE.match(street_part)
    if not m:
        raise DataSFError(
            "INVALID_ADDRESS",
            f"Adresse non reconnue : « {address} » (ex. : 781 20th Ave).",
        )
    number, rest = m.group(1), m.group(2).rstrip(".")
    words = rest.split()
    suffix = None
    if len(words) > 1 and words[-1].lower().rstrip(".") in SUFFIXES:
        suffix = SUFFIXES[words.pop().lower().rstrip(".")]
    name = " ".join(words)
    ordinal = re.fullmatch(r"(\d+)(st|nd|rd|th)", name, flags=re.IGNORECASE)
    if ordinal:  # DataSF convention: "04th", "20th"
        name = f"{int(ordinal.group(1)):02d}{ordinal.group(2).lower()}"
    if not name:
        raise DataSFError("INVALID_ADDRESS", f"Nom de rue manquant dans « {address} ».")
    return {"street_number": number, "street_name": name, "street_suffix": suffix}


# ----------------------------------------------------------------- cache
def _cache() -> sqlite3.Connection:
    config.DATASF_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DATASF_CACHE_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, fetched_at REAL, payload TEXT)"
    )
    return con


def _cache_get(key: str) -> tuple[float, list[dict[str, Any]]] | None:
    with _cache() as con:
        row = con.execute(
            "SELECT fetched_at, payload FROM cache WHERE key = ?", (key,)
        ).fetchone()
    return (row[0], json.loads(row[1])) if row else None


def _cache_put(key: str, rows: list[dict[str, Any]]) -> None:
    with _cache() as con:
        con.execute(
            "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
            (key, time.time(), json.dumps(rows)),
        )


# ------------------------------------------------------------------ query
def _soql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _fetch(parsed: dict[str, str | None]) -> list[dict[str, Any]]:
    where = (
        f"street_number={_soql_literal(parsed['street_number'])} "
        f"AND upper(street_name)=upper({_soql_literal(parsed['street_name'])})"
    )
    if parsed["street_suffix"]:
        where += f" AND street_suffix={_soql_literal(parsed['street_suffix'])}"
    params = {
        "$select": ",".join(FIELDS),
        "$where": where,
        "$order": "status_date DESC",
        "$limit": "200",
    }
    headers = (
        {"X-App-Token": config.SOCRATA_APP_TOKEN} if config.SOCRATA_APP_TOKEN else {}
    )
    try:
        r = httpx.get(
            config.DATASF_URL,
            params=params,
            headers=headers,
            timeout=config.DATASF_TIMEOUT_S,
        )
        r.raise_for_status()
        return r.json()
    except httpx.TimeoutException as exc:
        raise DataSFError(
            "DATASF_TIMEOUT",
            f"L'API DataSF n'a pas répondu en {config.DATASF_TIMEOUT_S:.0f} s.",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise DataSFError(
            "DATASF_UNAVAILABLE",
            f"L'API DataSF est indisponible ({type(exc).__name__}).",
        ) from exc


def _summarize(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen, permits = set(), []
    for row in rows:
        num = row.get("permit_number")
        if not num or num in seen:
            continue
        seen.add(num)
        permits.append(
            {
                k: row.get(k)
                for k in FIELDS
                if k
                not in {"street_number", "street_name", "street_suffix", "data_as_of"}
            }
        )
    return permits[:limit]


def search_permits(address: str, limit: int = 10) -> dict[str, Any]:
    parsed = parse_address(address)
    key = json.dumps(parsed, sort_keys=True)
    cached = _cache_get(key) if config.DATASF_CACHE else None
    stale = False
    if cached and time.time() - cached[0] < config.DATASF_CACHE_TTL_S:
        rows, from_cache = cached[1], True
    else:
        try:
            rows, from_cache = _fetch(parsed), False
            if config.DATASF_CACHE:
                _cache_put(key, rows)
        except DataSFError:
            if not cached:
                raise
            rows, from_cache, stale = cached[1], True, True
    if not rows:
        raise DataSFError(
            "ADDRESS_NOT_FOUND",
            f"Aucun permis trouvé dans DataSF pour « {address} ». L'adresse est peut-être inexistante "
            "ou mal orthographiée (format attendu : numéro + rue, ex. 781 20th Ave).",
        )
    first = rows[0]
    out = {
        "address": f"{first.get('street_number')} {first.get('street_name')} {first.get('street_suffix') or ''}".strip(),
        "neighborhood": first.get("neighborhoods_analysis_boundaries"),
        "zipcode": first.get("zipcode"),
        "permit_count": len({r.get("permit_number") for r in rows}),
        "permits": _summarize(rows, limit),
        "source": SOURCE,
        "data_as_of": first.get("data_as_of"),
        "from_cache": from_cache,
    }
    if stale:
        out["warning"] = (
            "DataSF indisponible : résultat issu du cache local, possiblement non à jour."
        )
    return out
