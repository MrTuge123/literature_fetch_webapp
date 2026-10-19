"""Preferences: every real settings file passes, typos and bad values fail, and the dict the
pipeline reads is exactly what it read before the model existed."""
import copy
import glob
import os

import pytest
import yaml

from digest import config
from digest.prefs import Preferences, ValidationError, problems


def merged(path):
    """What load_subscribers built before Preferences existed (the old behavior, by hand)."""
    with open(config.CONFIG_FILE) as f:
        shared = yaml.safe_load(f) or {}
    with open(path) as f:
        sub = config._deep_merge(shared, yaml.safe_load(f) or {})
    sid = os.path.splitext(os.path.basename(path))[0]
    sub.update(id=sid, file=path)
    sub.setdefault("name", sid)
    sub["ranking"] = sub.get("ranking") or {}
    return sub


FILES = sorted(glob.glob("subscribers/*.yaml"))       # _template.yaml always; real ones when present


@pytest.mark.parametrize("path", FILES)
def test_every_settings_file_is_valid(path):
    Preferences.model_validate(merged(path))


@pytest.mark.parametrize("path", FILES)
def test_pipeline_gets_the_same_dict_as_before(path):
    raw = merged(path)
    out = Preferences.model_validate(copy.deepcopy(raw)).to_sub()
    assert out == raw
    assert type(out["days_back"]) is type(raw["days_back"])          # ints stay ints


def base():
    return merged("subscribers/_template.yaml")


@pytest.mark.parametrize("change, expected", [
    ({"max_paper": 3}, "max_paper: unknown setting"),                 # typo at the top
    ({"ranking": {"min_relevence": 4}}, "ranking.min_relevence: unknown setting"),
    ({"days_back": 0}, "days_back"),
    ({"max_papers": 0}, "max_papers"),
    ({"ranking": {"min_relevance": 11}}, "ranking.min_relevance"),
    ({"ranking": {"min_score": 1.5}}, "ranking.min_score"),
    ({"provider": "openai"}, "provider"),
    ({"pubmed_sort": "newest"}, "pubmed_sort"),
    ({"sources": {"scopus": {"enabled": True}}}, "unknown source scopus"),
    ({"topic": "spatial omics"}, "not both"),                         # the template already has query:
    ({"outputs": {"slack": {"enabled": True, "webhook": "https://x"}}}, "outputs.slack.webhook"),
    ({"id": "bad name!"}, "id"),
])
def test_bad_settings_are_rejected_with_a_clear_message(change, expected):
    sub = config._deep_merge(base(), change)
    with pytest.raises(ValidationError) as e:
        Preferences.model_validate(sub)
    assert any(expected in line for line in problems(e.value)), problems(e.value)


def test_load_subscribers_matches_the_files(tmp_path, monkeypatch):
    (tmp_path / "subscribers").mkdir()
    (tmp_path / "config.yaml").write_text(open(config.CONFIG_FILE).read())
    (tmp_path / "subscribers" / "lab.yaml").write_text(open("subscribers/_template.yaml").read())
    (tmp_path / "subscribers" / "_off.yaml").write_text("name: skipped\n")
    monkeypatch.chdir(tmp_path)
    subs = config.load_subscribers()
    assert [s["id"] for s in subs] == ["lab"]                         # _ files are skipped
    assert subs[0] == merged("subscribers/lab.yaml")


def test_a_bad_file_stops_the_run_naming_it(tmp_path, monkeypatch):
    (tmp_path / "subscribers").mkdir()
    (tmp_path / "config.yaml").write_text(open(config.CONFIG_FILE).read())
    (tmp_path / "subscribers" / "lab.yaml").write_text('query: "a AND b"\nmax_paper: 3\n')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        config.load_subscribers()
    assert "subscribers/lab.yaml" in str(e.value) and "max_paper" in str(e.value)
