"""Website settings: only safe fields, tighter limits, and delivery always wired to the user's own
webhook and address (never the lab's secrets)."""
import pytest
from pydantic import ValidationError

from api.settings import UserSettings, from_preferences, to_preferences, webhook_secret

USER = "3f1c-uuid-1234"


def good(**kw):
    base = {"name": "My digest", "topic": "graph neural networks for spatial omics",
            "sources": {"pubmed": {"enabled": True}, "arxiv": {"enabled": True}}}
    return UserSettings.model_validate({**base, **kw})


def test_becomes_full_preferences_with_shared_defaults():
    p = to_preferences(USER, "me@umich.edu", good(), has_webhook=False)
    sub = p.to_sub()
    assert sub["id"] == USER and sub["model"] and sub["provider"]              # from config.yaml
    assert sub["sources"]["pubmed"]["enabled"] and not sub["sources"]["openalex"]["enabled"]
    assert sub["outputs"]["email"] == {"enabled": True, "to": ["me@umich.edu"], "chinese_summary": False}
    assert sub["outputs"]["slack"]["enabled"] is False                          # not chosen
    assert sub["outputs"]["slack"]["webhook_env"] == webhook_secret(USER)


def test_slack_only_with_their_own_webhook():
    s = good(delivery={"slack": True, "email": False})
    with pytest.raises(ValueError, match="webhook first"):
        to_preferences(USER, "me@umich.edu", s, has_webhook=False)
    sub = to_preferences(USER, "me@umich.edu", s, has_webhook=True).to_sub()
    assert sub["outputs"]["slack"] == {"enabled": True, "webhook_env": "SLACK_WEBHOOK_3f1c_uuid_1234",
                                       "chinese_summary": False}
    assert sub["outputs"]["wecom"] == {"enabled": False}


@pytest.mark.parametrize("change, problem", [
    ({"outputs": {"slack": {"webhook_env": "SLACK_WEBHOOK_URL"}}}, "outputs"),   # the lab's secret
    ({"model": "expensive-model"}, "model"),
    ({"provider": "kimi"}, "provider"),
    ({"max_papers": 50}, "max_papers"),
    ({"days_back": 365}, "days_back"),
    ({"sources": {"pubmed": {"enabled": False}}}, "at least one source"),
    ({"sources": {"scopus": {"enabled": True}}}, "unknown source"),
    ({"query": "a AND b"}, "exactly one"),                                     # topic is set too
    ({"topic": None}, "exactly one"),
    ({"ranking": {"key_words": ["x"] * 31}}, "at most 30"),
    ({"delivery": {"email": True, "to": ["someone@else.edu"]}}, "to"),
])
def test_unsafe_or_out_of_range_settings_are_refused(change, problem):
    with pytest.raises(ValidationError) as e:
        good(**change)
    assert problem in str(e.value)


def test_round_trip_through_preferences():
    s = good(interest="spatial transcriptomics methods", journals=["Nature Methods"], max_papers=3,
             ranking={"key_words": ["GNN"], "min_relevance": 5},
             delivery={"slack": True, "email": True, "chinese_summary": True}, paused=True)
    p = to_preferences(USER, "me@umich.edu", s, has_webhook=True)
    back = from_preferences(p, paused=True)
    assert back.model_dump(exclude={"sources"}) == s.model_dump(exclude={"sources"})
    assert {k: v.enabled for k, v in back.sources.items() if v.enabled} == {"pubmed": True, "arxiv": True}
