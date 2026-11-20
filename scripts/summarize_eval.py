"""Turn two agents-cli grade result files into the README evaluation table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

PASS_SCORE = 4


def per_case_scores(path: Path) -> list[dict[str, float]]:
    """Collect {metric: score} for every graded case (robust to schema changes)."""
    data = json.loads(path.read_text())
    cases: list[dict[str, float]] = []

    def walk(node):
        if isinstance(node, dict):
            mr = node.get("metric_results")
            if isinstance(mr, dict):
                cases.append(
                    {k: v.get("score") for k, v in mr.items() if isinstance(v, dict)}
                )
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data.get("eval_case_results", data))
    return cases


def summarize(cases: list[dict[str, float]]) -> dict[str, float]:
    def vals(m):
        return [c[m] for c in cases if c.get(m) is not None]

    def avg(m):
        v = vals(m)
        return mean(v) if v else float("nan")

    q = vals("custom_response_quality")
    return {
        "n": len(cases),
        "pass_rate": 100 * sum(s >= PASS_SCORE for s in q) / len(q)
        if q
        else float("nan"),
        "quality": avg("custom_response_quality"),
        "expected_tools": 100 * avg("expected_tools"),
        "compliance": 100 * avg("source_and_disclaimer"),
        "unnecessary": sum(vals("unnecessary_action")),
        "tool_errors": sum(vals("tool_errors")),
        "tool_calls": avg("tool_call_count") if vals("tool_call_count") else 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/eval_results.md"))
    ap.add_argument("--readme", type=Path, default=Path("README.md"))
    a = ap.parse_args()
    s_agent, s_base = (
        summarize(per_case_scores(a.agent)),
        summarize(per_case_scores(a.baseline)),
    )
    rows = [
        ("Scénarios évalués", "n", "{:.0f}"),
        ("Taux de réussite (juge ≥ 4/5)", "pass_rate", "{:.0f} %"),
        ("Note moyenne du juge (1-5)", "quality", "{:.2f}"),
        ("Outils attendus appelés", "expected_tools", "{:.0f} %"),
        ("Conformité (avertissement + source citée)", "compliance", "{:.0f} %"),
        (
            "Actions inutiles (brouillon/envoi non demandé, envoi prétendu)",
            "unnecessary",
            "{:.0f}",
        ),
        ("Erreurs d'outils", "tool_errors", "{:.0f}"),
        ("Appels d'outils moyens / scénario", "tool_calls", "{:.1f}"),
    ]
    lines = [
        "| Métrique | Baseline simple prompt | Assistant (outils + skills + RAG) |",
        "|---|---|---|",
    ]
    for label, key, fmt in rows:
        lines.append(
            f"| {label} | {fmt.format(s_base[key])} | **{fmt.format(s_agent[key])}** |"
        )
    md = "\n".join(lines) + "\n"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("# Résultats de l'évaluation\n\n" + md)
    # Paste the table into the README between the markers.
    if a.readme.exists():
        text = a.readme.read_text()
        start, end = "<!-- EVAL_TABLE_START -->", "<!-- EVAL_TABLE_END -->"
        if start in text and end in text:
            before, rest = text.split(start, 1)
            after = rest.split(end, 1)[1]
            a.readme.write_text(f"{before}{start}\n{md}{end}{after}")
    print(md)


if __name__ == "__main__":
    main()
