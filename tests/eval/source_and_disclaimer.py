"""Code metric: compliance of the final answer (0-1).
0.5 for the legal disclaimer + 0.5 for citing an expected official source
(the source half is granted when the case expects no source)."""

import json
import re


def evaluate(instance):
    response = str(instance.get("response", ""))
    reference = json.dumps(instance.get("reference", ""), ensure_ascii=False)
    disclaimer = "pas un avis juridique" in response.lower()
    m = re.search(r"\[EXPECT_SOURCE: ([^\]]*)\]", reference)
    if m:
        urls = [u.strip().rstrip("/") for u in m.group(1).split("|")]
        cited = any(
            u in response or u.replace("://www.", "://") in response for u in urls
        )
    else:
        cited = True
    return {
        "score": 0.5 * disclaimer + 0.5 * cited,
        "explanation": f"disclaimer={disclaimer}, expected_source_cited={cited if m else 'n/a'}",
    }
