"""Download the official City of San Francisco pages used by the RAG.

Each page is saved as markdown in data/city_docs/ with its source URL, title
and fetch date in a front-matter header. The text is the page's main content,
converted as-is (nothing is rewritten). Pages that cannot be fetched are
reported and NOT replaced.

Note: sf.gov may answer automated clients with an empty "HTTP 202" anti-bot
challenge. This script does not try to bypass it; in that case save the pages
from a browser and use scripts/import_city_docs.py.

Usage: uv run python scripts/fetch_city_docs.py
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

OUT = Path(__file__).resolve().parents[1] / "data" / "city_docs"

# (doc_id, work types covered, official URL) — the 10 pages of the corpus.
# DOC-03 and DOC-07 are listed in UNAVAILABLE below.
PAGES = [
    (
        "DOC-01",
        "kitchen,bathroom",
        "https://www.sf.gov/apply-kitchen-or-bath-remodel-permit",
    ),
    (
        "DOC-02",
        "kitchen,bathroom,interior",
        "https://www.sf.gov/step-by-step--get-otc-permit-your-interior-residential-remodel",
    ),
    (
        "DOC-04",
        "general,plans,windows",
        "https://www.sf.gov/information/check-if-your-building-permit-needs-plans",
    ),
    (
        "DOC-05",
        "adu",
        "https://www.sf.gov/get-a-building-permit-for-an-accessory-dwelling-unit-adu",
    ),
    ("DOC-06", "adu", "https://www.sf.gov/information--accessory-dwelling-units-adus"),
    ("DOC-08", "adu", "https://www.sf.gov/post-notice-your-adu"),
    ("DOC-09", "reroofing", "https://www.sf.gov/apply-reroofing-permit"),
    (
        "DOC-10",
        "exterior,windows,reroofing,deck",
        "https://www.sf.gov/step-by-step--get-otc-permit-your-exterior-residential-project",
    ),
    (
        "DOC-11",
        "solar",
        "https://www.sf.gov/step-by-step--get-permit-solar-photovoltaic-system",
    ),
    ("DOC-12", "general", "https://www.sf.gov/where-to-apply-for-your-permit"),
]

# Official pages that could NOT be retrieved on 2026-11-20 (not replaced):
UNAVAILABLE = [
    (
        "DOC-03",
        "https://www.sf.gov/information--projects-eligible-over-counter-otc-permit",
        "HTTP 404: page removed from sf.gov",
    ),
    (
        "DOC-07",
        "https://sf.gov/step-by-step/add-accessory-dwelling-unit-adu-your-property",
        "redirects to a page returning HTTP 404",
    ),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (educational RAG project; fetches public sf.gov pages)"
}


def extract(html: str) -> tuple[str, str]:
    """Return (title, markdown of the main content). Raises on empty/challenge pages."""
    soup = BeautifulSoup(html, "html.parser")
    h = soup.find("h1") or soup.title
    if h is None:
        raise RuntimeError("no title found (empty or challenge page)")
    title = h.get_text(" ", strip=True)
    main = soup.find("main") or soup.body
    if main is None:
        raise RuntimeError("no page body")
    for tag in main.find_all(
        ["script", "style", "nav", "footer", "form", "button", "svg", "noscript"]
    ):
        tag.decompose()
    md = markdownify(str(main), heading_style="ATX", strip=["img"])
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    if len(md) < 300:
        raise RuntimeError(f"content too short ({len(md)} chars)")
    return title, md


def to_markdown(
    doc_id: str, topics: str, title: str, url: str, md: str, how: str
) -> str:
    return (
        f"---\ndoc_id: {doc_id}\ntitle: {title}\nurl: {url}\ntopics: {topics}\n"
        f"publisher: City and County of San Francisco (sf.gov)\n"
        f"fetched_at: {datetime.now(UTC).date().isoformat()}\nretrieval: {how}\n---\n\n{md}\n"
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for doc_id, topics, url in PAGES:
            try:
                r = client.get(url)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}, {len(r.text)} bytes")
                title, md = extract(r.text)
            except Exception as exc:
                failed.append((doc_id, url, str(exc)))
                print(f"FAILED {doc_id} {url}: {exc}")
                continue
            (OUT / f"{doc_id}.md").write_text(
                to_markdown(doc_id, topics, title, url, md, "live"), encoding="utf-8"
            )
            print(f"ok     {doc_id} {len(md):6d} chars  {title}")
    if failed:
        print(
            f"\n{len(failed)} page(s) not fetched (NOT replaced):", *failed, sep="\n  "
        )
        print("\nSave these pages from a browser and run scripts/import_city_docs.py.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
