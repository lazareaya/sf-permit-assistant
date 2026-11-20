"""Generate notebooks/demo.ipynb (run it with: uv run python scripts/make_notebook.py)."""

from pathlib import Path

import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# Agent IA d'analyse de fraude — notebook de démonstration\n\n"
       "Ce notebook montre chaque brique de l'agent **sans passer par le LLM** : la base SQL, "
       "le scoring par l'API du projet 2, le RAG sur les procédures, le serveur MCP, les skills, "
       "les garde-fous et la validation humaine. Il se termine par les résultats de l'évaluation.\n\n"
       "Prérequis : l'API de fraude du projet 2 tourne sur `FRAUD_API_URL` (voir README)."),
    code("import os, shutil, sys, tempfile, json\n"
         "from pathlib import Path\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
         "sys.path.insert(0, str(ROOT)); os.chdir(ROOT)\n"
         "os.environ.setdefault('RAG_EMBEDDINGS', 'local')  # 'gemini' si une clé est configurée\n"
         "from app import config\n"
         "# On travaille sur une copie de la base pour ne pas la modifier\n"
         "tmp = Path(tempfile.mkdtemp()); shutil.copy(config.ROOT/'data'/'bank.db', tmp/'bank.db')\n"
         "config.BANK_DB_PATH = tmp/'bank.db'; config.CHROMA_DIR = tmp/'chroma'\n"
         "import pandas as pd, sqlite3\n"
         "con = sqlite3.connect(config.BANK_DB_PATH)"),
    md("## 1. La base de données d'entreprise (SQLite)\n"
       "20 000 transactions issues du jeu de données du projet 2 (toutes les 492 fraudes + 19 508 "
       "transactions normales), réparties sur 300 cartes, avec des colonnes métier synthétiques."),
    code("pd.read_sql('SELECT (SELECT COUNT(*) FROM cards) AS cartes, COUNT(*) AS transactions, "
         "SUM(label_is_fraud) AS fraudes FROM transactions', con)"),
    code("pd.read_sql('''SELECT merchant_category, COUNT(*) AS n, ROUND(100.0*AVG(label_is_fraud),2) AS taux_fraude_pct\n"
         "FROM transactions GROUP BY 1 ORDER BY 3 DESC''', con)"),
    md("## 2. Outils SQL (lecture seule)"),
    code("from app import tools\n"
         "h = tools.get_transaction_history('CARD-00262', limit=5)\n"
         "print(h['stats']); pd.DataFrame(h['transactions'])"),
    code("tools.get_card_status('CARD-99999')  # carte inconnue -> erreur explicite"),
    md("## 3. Scoring via l'API de détection de fraude du projet 2"),
    code("for tx in [110613, 111410, 117663]:\n"
         "    r = tools.score_transaction(tx)\n"
         "    print(tx, r.get('fraud_probability', r.get('error')), r.get('card_id'))"),
    md("## 4. RAG sur les procédures internes (Chroma)"),
    code("from app.rag import search_procedures\n"
         "for p in search_procedures(\"l'API de scoring ne répond plus\")['passages']:\n"
         "    print(p['procedure_id'], '|', p['section'], '|', p['score'])"),
    md("## 5. Le serveur MCP\nL'agent découvre ses outils via le protocole MCP (stdio)."),
    code("from mcp import ClientSession, StdioServerParameters\n"
         "from mcp.client.stdio import stdio_client\n"
         "params = StdioServerParameters(command=sys.executable, args=['-m','mcp_server.server'], cwd=str(ROOT),\n"
         "    env={**os.environ, 'PYTHONPATH': str(ROOT), 'BANK_DB_PATH': str(config.BANK_DB_PATH)})\n"
         "async def list_tools():\n"
         "    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:\n"
         "        await s.initialize(); return [(t.name, t.description.splitlines()[0]) for t in (await s.list_tools()).tools]\n"
         "await list_tools()"),
    md("## 6. Skills et constructeur de contexte"),
    code("from types import SimpleNamespace\n"
         "from app.skills import SKILL_REGISTRY, build_instruction\n"
         "for s in SKILL_REGISTRY.values(): print(f'{s.name:18} -> {s.allowed_tools}')\n"
         "ctx = SimpleNamespace(state={'active_skill': 'decision_prep', 'case': {'card_id': 'CARD-00262', 'tx_id': 110613,\n"
         "    'fraud_probability': 0.9999, 'cited_procedures': ['PROC-01','PROC-02']}})\n"
         "print(build_instruction(ctx)[-900:])"),
    md("## 7. Garde-fous"),
    code("from app.guardrails import check_tool_call\n"
         "state = {'active_skill': 'decision_prep'}\n"
         "block = {'card_id': 'CARD-00262', 'procedure_id': 'PROC-01', 'justification': 'score 0.9999, 3 pays étrangers'}\n"
         "print(check_tool_call('block_card', block, state, 'inv1'))       # refusé : aucune procédure consultée\n"
         "print(check_tool_call('score_transaction', {'tx_id': 1}, state, 'inv1'))  # refusé : hors skill\n"
         "state['active_skill'] = 'investigation'\n"
         "print(check_tool_call('get_card_status', {'card_id': 'CARD-99999'}, state, 'inv1'))  # carte inconnue"),
    md("## 8. Validation humaine (human-in-the-loop)"),
    code("from app import db\n"
         "req = tools.block_card('CARD-00262', 'Score 0.9999 sur la transaction 110613, catégorie à risque.', 'PROC-01', 110613)\n"
         "print(req['message']); print('statut carte :', db.get_card_status('CARD-00262')['status'])\n"
         "print(db.decide_action(req['action_id'], approve=True, reviewer='analyste N1'))\n"
         "print('statut carte après approbation :', db.get_card_status('CARD-00262')['status'])"),
    md("## 9. Évaluation : agent vs assistant à simple prompt\n"
       "Générée par `bash scripts/run_eval.sh` (25 scénarios, LLM juge)."),
    code("from IPython.display import Markdown\n"
         "p = ROOT/'docs'/'eval_results.md'\n"
         "Markdown(p.read_text() if p.exists() else '_Lancer `bash scripts/run_eval.sh` pour produire les résultats._')"),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}})
out = Path(__file__).resolve().parents[1] / "notebooks" / "demo.ipynb"
nbf.write(nb, out)

if __name__ == "__main__":
    from nbclient import NotebookClient

    NotebookClient(nb, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(out.parent)}}).execute()
    nbf.write(nb, out)
    print("executed ->", out)
