# Official City of San Francisco pages (RAG corpus)

10 official sf.gov pages (Department of Building Inspection, Rent Board / Planning),
copied from a web browser on 2026-11-20, text reproduced word for word (nothing
summarised or translated). Menus, footers, banners and "Translate" links removed.

Each file starts with a front-matter header (`doc_id`, `title`, `url`,
`publisher`, `fetched_at`, `retrieval`); a page without its source URL is never
indexed. The list of pages is in `scripts/fetch_city_docs.py` (`PAGES`).

| doc_id | Page | URL |
|---|---|---|
| DOC-01 | Apply for a kitchen or bath remodel permit | https://www.sf.gov/apply-kitchen-or-bath-remodel-permit |
| DOC-02 | Get an Over-the-Counter permit for your interior residential remodel | https://www.sf.gov/step-by-step--get-otc-permit-your-interior-residential-remodel |
| DOC-04 | Check if your building permit needs plans | https://www.sf.gov/information/check-if-your-building-permit-needs-plans (redirects to …/information--check-if-your-building-permit-needs-plans, same page) |
| DOC-05 | Get a building permit for an Accessory Dwelling Unit (ADU) | https://www.sf.gov/get-a-building-permit-for-an-accessory-dwelling-unit-adu |
| DOC-06 | Accessory Dwelling Units (ADUs) | https://www.sf.gov/information--accessory-dwelling-units-adus |
| DOC-08 | Post a notice for your ADU | https://www.sf.gov/post-notice-your-adu |
| DOC-09 | Apply for a reroofing permit | https://www.sf.gov/apply-reroofing-permit |
| DOC-10 | Get an Over-the-Counter permit for your exterior residential project | https://www.sf.gov/step-by-step--get-otc-permit-your-exterior-residential-project |
| DOC-11 | Get a permit for a solar photovoltaic system | https://www.sf.gov/step-by-step--get-permit-solar-photovoltaic-system |
| DOC-12 | Where to apply for your permit | https://www.sf.gov/where-to-apply-for-your-permit |

**Not available (not replaced by any other content):**
- DOC-03 *Projects eligible for an Over-the-Counter (OTC) permit*: HTTP 404, page removed from sf.gov.
- DOC-07 *Add an accessory dwelling unit (ADU) to your property*: redirects to a page returning HTTP 404.

Content © City and County of San Francisco (sf.gov), reproduced for
information with a link to each source page.
