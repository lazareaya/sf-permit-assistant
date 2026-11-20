"""Generate and execute notebooks/demo.ipynb: uv run python scripts/make_notebook.py"""

from pathlib import Path

import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md(
        "# Assistant permis de construire — San Francisco : notebook de démonstration\n\n"
        "Chaque brique de l'agent, **sans passer par le LLM** : l'API DataSF, la base des projets du "
        "cabinet (fictif), le RAG sur les pages officielles de la ville, le serveur MCP, les skills, "
        "les garde-fous et la validation humaine. Puis les résultats de l'évaluation.\n\n"
        "> ⚠️ Information générale, pas un avis juridique. Vérifier auprès du Department of Building Inspection."
    ),
    code(
        "import os, shutil, sys, tempfile, json\n"
        "from pathlib import Path\n"
        "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
        "sys.path.insert(0, str(ROOT)); os.chdir(ROOT)\n"
        "os.environ.setdefault('RAG_EMBEDDINGS', 'local')  # 'gemini' si une clé est configurée\n"
        "from app import config\n"
        "tmp = Path(tempfile.mkdtemp())  # copie de la base : le notebook ne modifie rien\n"
        "shutil.copy(config.ROOT/'data'/'projects.db', tmp/'projects.db')\n"
        "config.PROJECTS_DB_PATH = tmp/'projects.db'; config.CHROMA_DIR = tmp/'chroma'\n"
        "config.DATASF_CACHE_PATH = tmp/'datasf.sqlite'\n"
        "import pandas as pd, sqlite3\n"
        "con = sqlite3.connect(config.PROJECTS_DB_PATH)"
    ),
    md("## 1. API DataSF « Building Permits » (permis existants à une adresse)"),
    code(
        "from app import tools\n"
        "r = tools.search_permits('781 20th Ave')\n"
        "print(r['address'], '|', r['neighborhood'], '|', r['permit_count'], 'permis | source :', r['source'])\n"
        "pd.DataFrame(r['permits'])[['permit_number','permit_type_definition','status','status_date','estimated_cost']]"
    ),
    code(
        "print(tools.search_permits('781 20th Ave')['from_cache'])  # 2e appel : cache local\n"
        "print(tools.search_permits('99999 Market St'))           # adresse introuvable\n"
        "config.DATASF_URL, url = 'http://127.0.0.1:9/x.json', config.DATASF_URL; config.DATASF_CACHE = False\n"
        "print(tools.search_permits('2460 Lyon St'))              # API en panne\n"
        "config.DATASF_URL = url; config.DATASF_CACHE = True"
    ),
    md("## 2. La base des projets du cabinet (fictif, adresses réelles)"),
    code(
        "pd.read_sql('SELECT id, client, address, work_type, estimated_cost, status FROM projects', con)"
    ),
    code(
        "pd.read_sql('SELECT id, project_id, status, created_at FROM submissions', con)"
    ),
    md("## 3. RAG sur les pages officielles de la ville (Chroma)"),
    code(
        "from app.rag import load_chunks, search_city_docs\n"
        "chunks = load_chunks(); print(len(chunks), 'morceaux indexés')\n"
        "res = search_city_docs('documents required for an ADU building permit')\n"
        "res if 'error' in res else [(p['title'], p['url'], p['score']) for p in res['passages']]"
    ),
    md("## 4. Le serveur MCP"),
    code(
        "from mcp import ClientSession, StdioServerParameters\n"
        "from mcp.client.stdio import stdio_client\n"
        "params = StdioServerParameters(command=sys.executable, args=['-m','mcp_server.server'], cwd=str(ROOT),\n"
        "    env={**os.environ, 'PYTHONPATH': str(ROOT), 'PROJECTS_DB_PATH': str(config.PROJECTS_DB_PATH)})\n"
        "async def list_tools():\n"
        "    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:\n"
        "        await s.initialize(); return [(t.name, t.description.splitlines()[0]) for t in (await s.list_tools()).tools]\n"
        "await list_tools()"
    ),
    md("## 5. Skills et constructeur de contexte"),
    code(
        "from types import SimpleNamespace\n"
        "from app.skills import SKILL_REGISTRY, build_instruction\n"
        "for s in SKILL_REGISTRY.values(): print(f'{s.name:22} -> {s.allowed_tools}')\n"
        "ctx = SimpleNamespace(state={'active_skill': 'submission_prep', 'case': {'project_id': 9,\n"
        "    'address': '30 Jersey St', 'work_type': 'adu'}})\n"
        "print(build_instruction(ctx)[-1200:])"
    ),
    md("## 6. Garde-fous"),
    code(
        "from app.guardrails import check_tool_call, enforce_output\n"
        "state = {'active_skill': 'submission_prep'}\n"
        "draft = {'project_id': 9, 'content': 'Brouillon sans aucune source. ' * 10}\n"
        "print(check_tool_call('create_submission_draft', draft, state, 'i1'))  # refus : aucune source\n"
        "print(check_tool_call('send_submission', {'submission_id': 1}, state, 'i1'))  # refus : non approuvé\n"
        "print(check_tool_call('search_permits', {'address': '1 Main'}, {'active_skill': 'document_requirements'}, 'i1'))\n"
        "print(enforce_output('Réponse sans avertissement.', None))"
    ),
    md("## 7. Validation humaine"),
    code(
        "from app import db\n"
        "print(tools.send_submission(1))                 # en attente -> refusé\n"
        "print(db.decide_submission(1, approve=True, reviewer='architecte référent'))\n"
        "print(tools.send_submission(1))                 # approuvé -> envoyé (simulé)"
    ),
    md(
        "## 8. Évaluation : assistant vs assistant à simple prompt\nProduite par `bash scripts/run_eval.sh`."
    ),
    code(
        "from IPython.display import Markdown\n"
        "p = ROOT/'docs'/'eval_results.md'\n"
        "Markdown(p.read_text() if p.exists() else '_Lancer `bash scripts/run_eval.sh` pour produire les résultats._')"
    ),
]
nb = nbf.v4.new_notebook(
    cells=cells,
    metadata={
        "kernelspec": {
            "name": "python3",
            "display_name": "Python 3",
            "language": "python",
        }
    },
)
out = Path(__file__).resolve().parents[1] / "notebooks" / "demo.ipynb"

if __name__ == "__main__":
    from nbclient import NotebookClient

    NotebookClient(
        nb,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(out.parent)}},
    ).execute()
    nbf.write(nb, out)
    print("executed ->", out)
