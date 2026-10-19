"""FileStore-only behavior: the files keep today's format (the GitHub workflow merges them).
What every store must do is in test_store_contract.py."""
import json

from digest import paper
from digest.storage import FileStore
from tests.test_store_contract import A, B


def test_files_keep_their_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "1")
    fs = FileStore()
    fs.add_seen("lab", paper.ids(A) | paper.ids(B))
    fs.save_history("lab", [A, B], posted=[A])
    assert json.load(open("seen/lab.json")) == sorted(paper.ids(A) | paper.ids(B))
    lines = [json.loads(line) for line in open("history/lab.jsonl")]
    assert [r["title"] for r in lines] == [A["title"], B["title"]]
