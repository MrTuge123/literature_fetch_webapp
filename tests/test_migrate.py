"""scripts/migrate_files.py copies the files into DynamoDB, checks itself, and can run twice."""
import importlib.util
import os
import shutil

import pytest

from digest.storage import FileStore
from tests.test_prefs import ROOT_CONFIG
from tests.test_store_contract import A, B

pytest.importorskip("moto")
spec = importlib.util.spec_from_file_location("migrate_files", os.path.join("scripts", "migrate_files.py"))
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture
def files(tmp_path, monkeypatch):
    """A folder like the repo: one active subscriber, one switched off (_), and their files."""
    shutil.copy(ROOT_CONFIG, tmp_path / "config.yaml")
    (tmp_path / "subscribers").mkdir()
    shutil.copy(os.path.join("subscribers", "_template.yaml"), tmp_path / "subscribers" / "lab.yaml")
    (tmp_path / "subscribers" / "_old.yaml").write_text("name: switched off\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "1")
    fs = FileStore()
    fs.add_seen("lab", {"10.1/a", "111"})
    fs.save_history("lab", [A, B], posted=[A])
    fs.add_seen("old", {"10.1/z"})                            # data of a subscriber who left
    return tmp_path


def test_dry_run_touches_nothing(files, dynamo_table, capsys):
    assert migrate.main(["--dry-run"]) == 0
    assert dynamo_table.scan()["Count"] == 0
    out = capsys.readouterr().out
    assert "lab" in out and "old" in out and "Dry run" in out


def test_copies_everything_and_checks_it(files, dynamo_table):
    from digest.dynamo_store import DynamoStore
    assert migrate.main([]) == 0
    ds = DynamoStore()
    assert ds.load_seen("lab") == {"10.1/a", "111"} and ds.load_seen("old") == {"10.1/z"}
    assert len(ds.load_history("lab")) == 2
    assert ds.list_subscribers() == ["lab"]                   # switched-off subscribers get no PREFS


def test_running_twice_changes_nothing(files, dynamo_table):
    assert migrate.main([]) == 0
    before = sorted((i["PK"], i["SK"]) for i in dynamo_table.scan()["Items"])
    assert migrate.main([]) == 0
    assert sorted((i["PK"], i["SK"]) for i in dynamo_table.scan()["Items"]) == before


def test_only_one_subscriber(files, dynamo_table):
    assert migrate.main(["--only", "old"]) == 0
    assert {i["PK"] for i in dynamo_table.scan()["Items"]} == {"USER#old"}
