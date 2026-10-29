"""What a website user may set, and how it becomes their Preferences.

The website never sends raw Preferences: a user could otherwise point webhook_env / to_env at
the lab's secrets (and post into its Slack), or pick an expensive model. UserSettings is the
editable subset, with tighter limits; to_preferences() fills in the rest on the server:

    shared defaults   config.yaml (model, provider, weights, candidate_pool, ...)
    Slack             their own webhook, stored as the secret SLACK_WEBHOOK_<user id>
    email             only to their own (Cognito-verified) address
    WeCom             not offered on the website
"""
import copy
import re

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from digest import config
from digest.prefs import SOURCE_KEYS, Preferences

Words = list[str]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _short_list(v, most=30, length=200):
    if len(v) > most or any(len(x) > length for x in v):
        raise ValueError(f"at most {most} entries of at most {length} characters")
    return [x.strip() for x in v if x.strip()]


class SourceChoice(_Strict):
    enabled: bool = False
    query: str | None = Field(None, max_length=4000)     # that source's own syntax (advanced)


class RankingChoice(_Strict):
    preferred_authors: Words = []
    preferred_journals: Words = []
    key_words: Words = []
    min_relevance: int = Field(0, ge=0, le=10)
    min_author_h_index: int = Field(0, ge=0, le=200)
    min_journal_citedness: float = Field(0, ge=0, le=100)

    _lists = field_validator("preferred_authors", "preferred_journals", "key_words")(_short_list)


class Delivery(_Strict):
    slack: bool = False                 # needs a webhook saved with PUT /me/webhook
    email: bool = True                  # to the address they signed in with
    chinese_summary: bool = False


class UserSettings(_Strict):
    name: str = Field(min_length=1, max_length=80)
    query: str | None = Field(None, max_length=4000)      # boolean query...
    topic: str | None = Field(None, max_length=500)       # ...or plain English
    interest: str | None = Field(None, max_length=1000)
    sources: dict[str, SourceChoice] = {"pubmed": SourceChoice(enabled=True)}
    journals: Words = []
    days_back: int = Field(7, ge=1, le=60)
    max_papers: int = Field(5, ge=1, le=10)
    ranking: RankingChoice = RankingChoice()
    delivery: Delivery = Delivery()
    paused: bool = False

    _journals = field_validator("journals")(lambda v: _short_list(v, most=50))

    @field_validator("sources")
    @classmethod
    def _known_sources(cls, v):
        unknown = sorted(set(v) - set(SOURCE_KEYS))
        if unknown:
            raise ValueError(f"unknown source {', '.join(unknown)} (known: {', '.join(SOURCE_KEYS)})")
        if not any(s.enabled for s in v.values()):
            raise ValueError("switch on at least one source")
        return v

    @model_validator(mode="after")
    def _query_or_topic(self):
        if bool(self.query and self.query.strip()) == bool(self.topic and self.topic.strip()):
            raise ValueError("set exactly one of query (boolean) or topic (plain English)")
        return self


def webhook_secret(user_id):
    """The Parameter Store name (under /litfetch/) holding this user's Slack webhook URL."""
    return "SLACK_WEBHOOK_" + re.sub(r"[^A-Za-z0-9_]", "_", user_id)


def _shared():
    with open(config.CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def to_preferences(user_id, email, s: UserSettings, has_webhook: bool) -> Preferences:
    """The full settings the pipeline runs with: config.yaml's defaults + what the user chose,
    with delivery wired to their own webhook and address only. Slack needs a saved webhook."""
    if s.delivery.slack and not has_webhook:
        raise ValueError("save a Slack webhook first (PUT /me/webhook), or switch Slack off")
    shared = _shared()
    sources = {k: {"enabled": False} for k in SOURCE_KEYS}
    for k, choice in s.sources.items():
        sources[k] = {"enabled": choice.enabled, **({"query": choice.query} if choice.query else {})}
    mine = {
        "id": user_id,
        "name": s.name,
        "days_back": s.days_back,
        "max_papers": s.max_papers,
        "journals": s.journals,
        "sources": sources,
        "ranking": s.ranking.model_dump(),
        "outputs": {
            "slack": {"enabled": s.delivery.slack, "webhook_env": webhook_secret(user_id),
                      "chinese_summary": s.delivery.chinese_summary},
            "email": {"enabled": s.delivery.email, "to": [email], "chinese_summary": s.delivery.chinese_summary},
            "wecom": {"enabled": False},
        },
    }
    for key in ("query", "topic", "interest"):
        if getattr(s, key):
            mine[key] = getattr(s, key).strip()
    base = copy.deepcopy(shared)
    base.pop("sources", None)                       # the user's choice replaces the defaults entirely
    return Preferences.model_validate(config._deep_merge(base, mine))


def from_preferences(p: Preferences, paused=False) -> UserSettings:
    """The form's view of saved Preferences (inverse of to_preferences)."""
    sub = p.to_sub()
    out = sub.get("outputs") or {}
    slack, email = out.get("slack") or {}, out.get("email") or {}
    rank = sub.get("ranking") or {}
    return UserSettings(
        name=sub["name"], query=sub.get("query"), topic=sub.get("topic"), interest=sub.get("interest"),
        sources={k: SourceChoice(enabled=bool((v or {}).get("enabled")), query=(v or {}).get("query"))
                 for k, v in (sub.get("sources") or {}).items() if k in SOURCE_KEYS},
        journals=sub.get("journals") or [],
        days_back=min(max(sub.get("days_back", 7), 1), 60),
        max_papers=min(max(sub.get("max_papers", 5), 1), 10),
        ranking=RankingChoice(**{k: rank[k] for k in RankingChoice.model_fields if k in rank}),
        delivery=Delivery(slack=bool(slack.get("enabled")), email=bool(email.get("enabled")),
                          chinese_summary=bool(slack.get("chinese_summary") or email.get("chinese_summary"))),
        paused=paused,
    )
