"""Import official sf.gov pages saved from a web browser.

sf.gov answers automated HTTP clients with an anti-bot challenge, so the pages
listed in scripts/fetch_city_docs.py can be saved manually instead: open each
URL in a browser, "Save Page As... > Web Page, HTML only" into one folder, then:

    uv run python scripts/import_city_docs.py ~/Downloads/sf_pages/

Each saved file is matched to its official URL through its canonical link
(<link rel="canonical"> or og:url), the main content is converted as-is to
markdown, and the source URL/title are kept. Files that do not match one of
the expected official URLs are ignored, and missing pages are listed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_city_docs import OUT, PAGES, extract, to_markdown


def _norm(url: str) -> str:
    return (
        url.split("?")[0]
        .split("#")[0]
        .rstrip("/")
        .replace("://sf.gov", "://www.sf.gov")
    )


def main(folder: Path) -> int:
    by_url = {_norm(url): (doc_id, topics, url) for doc_id, topics, url in PAGES}
    found: set[str] = set()
    OUT.mkdir(parents=True, exist_ok=True)
    for path in sorted(folder.glob("*.htm*")):
        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("link", rel="canonical") or soup.find(
            "meta", property="og:url"
        )
        url = (link.get("href") or link.get("content") or "") if link else ""
        match = by_url.get(_norm(url))
        if not match:
            print(
                f"skip   {path.name}: canonical URL {url!r} is not in the expected list"
            )
            continue
        doc_id, topics, official = match
        try:
            title, md = extract(html)
        except RuntimeError as exc:
            print(f"skip   {path.name}: {exc}")
            continue
        (OUT / f"{doc_id}.md").write_text(
            to_markdown(doc_id, topics, title, official, md, "browser-saved"),
            encoding="utf-8",
        )
        found.add(doc_id)
        print(f"ok     {doc_id} {len(md):6d} chars  {title}")
    missing = [(d, u) for d, _, u in PAGES if d not in found]
    if missing:
        print(
            f"\n{len(missing)} page(s) still missing:",
            *(f"{d} {u}" for d, u in missing),
            sep="\n  ",
        )
    return 0


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
