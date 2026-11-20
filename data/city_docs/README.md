# Official City of San Francisco pages (RAG corpus)

One file per official page, produced by `scripts/fetch_city_docs.py` (or
`scripts/import_city_docs.py` for pages saved from a browser). Each file starts
with a front-matter header (`doc_id`, `title`, `url`, `publisher`,
`fetched_at`); a page without its source URL is never indexed.

Content © City and County of San Francisco (sf.gov), reproduced for
information with a link to each source page.
