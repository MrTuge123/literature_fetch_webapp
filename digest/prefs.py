"""What one subscriber wants: config.yaml + subscribers/<id>.yaml merged, then checked here.

Preferences validates the merged settings once, when they're loaded, so a typo (max_paper:) or a
bad value (days_back: 0) stops the run with a clear message instead of being silently ignored.
Later the website's settings form and the DynamoDB PREFS item use the same model.

The rest of the pipeline still reads a plain dict: to_sub() gives the settings back exactly as
they were loaded (only the keys that were set, ints still ints), so nothing downstream changes.
"""
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SOURCE_KEYS = ("pubmed", "europepmc", "openalex", "semantic_scholar", "arxiv")
Number = Union[int, float]      # keeps 60 as 60 and 0.3 as 0.3 (a plain float would turn 60 into 60.0)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")      # unknown keys (typos) are errors


class SourceSettings(_Strict):
    enabled: bool = False
    query: str | None = None                       # this source's own syntax; overrides the translated query
    candidate_pool: int | None = Field(None, ge=1, le=500)


class Ranking(_Strict):
    relevance_weight: Number = Field(1.0, ge=0)
    author_weight: Number = Field(0.6, ge=0)
    journal_weight: Number = Field(0.4, ge=0)
    relevance_batch: int = Field(25, ge=1)
    relevance_thinking: bool = False
    author_h_cap: Number = Field(60, gt=0)
    journal_citedness_cap: Number = Field(10, gt=0)
    min_relevance: Number = Field(0, ge=0, le=10)
    min_score: Number = Field(0, ge=0, le=1)
    min_author_h_index: Number = Field(0, ge=0)
    min_journal_citedness: Number = Field(0, ge=0)
    keep_unmatched: bool = True
    unmatched_score: Number = Field(0.3, ge=0, le=1)
    preprint_journal_score: Number = Field(0.3, ge=0, le=1)
    keep_preprints: bool = True
    keyword_credit: Number = Field(0.1, ge=0)
    preferred_authors: list[str] = []
    preferred_journals: list[str] = []
    key_words: list[str] = []


class Connections(_Strict):
    enabled: bool = True
    min_relevance: Number = Field(5, ge=0, le=10)
    max_share: Number = Field(0.3, ge=0, le=1)
    max_items: int = Field(3, ge=0)
    refresh_days: int = Field(90, ge=0)


class WebhookOutput(_Strict):                       # Slack, WeCom
    enabled: bool = False
    webhook_env: str | None = None                  # NAME of the secret holding the URL, never the URL
    chinese_summary: bool = False


class EmailOutput(_Strict):
    enabled: bool = False
    to: str | list[str] = []
    to_env: str | None = None                       # NAME of a secret with comma-separated addresses
    chinese_summary: bool = False


class Outputs(_Strict):
    slack: WebhookOutput | None = None
    wecom: WebhookOutput | None = None
    email: EmailOutput | None = None


class Preferences(_Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")    # file name today, the user's id on the website
    file: str | None = None                         # where it was loaded from (None on the website)
    name: str
    provider: Literal["groq", "kimi"] | None = None
    model: str
    pubmed_sort: Literal["relevance", "pub_date"] = "relevance"
    days_back: int = Field(ge=1, le=365)
    candidate_pool: int = Field(50, ge=1, le=500)
    max_papers: int = Field(ge=1, le=50)
    overview_min_relevance: Number = Field(5, ge=0, le=10)
    query: str | None = None                        # boolean query...
    topic: str | None = None                        # ...or plain English (the LLM writes the query)
    interest: str | None = None
    journals: list[str] = []
    sources: dict[str, SourceSettings | None] = {}
    connections: Connections | None = None
    ranking: Ranking = Ranking()
    outputs: Outputs | None = None

    @field_validator("sources")
    @classmethod
    def _known_sources(cls, v):
        unknown = sorted(set(v) - set(SOURCE_KEYS))
        if unknown:
            raise ValueError(f"unknown source {', '.join(unknown)} (known: {', '.join(SOURCE_KEYS)})")
        return v

    @model_validator(mode="after")
    def _query_or_topic(self):
        if self.query and self.topic:
            raise ValueError("set either query: (boolean) or topic: (plain English), not both")
        return self

    def to_sub(self):
        """The plain dict the pipeline reads: only the keys that were set, as they were set."""
        return self.model_dump(exclude_unset=True)


def problems(err: ValidationError):
    """One short line per problem, e.g. 'ranking.min_relevance: must be <= 10'."""
    out = []
    for e in err.errors():
        where = ".".join(str(p) for p in e["loc"]) or "settings"
        msg = e["msg"].replace("Extra inputs are not permitted", "unknown setting (typo?)")
        msg = msg.replace("Value error, ", "").replace("Input should be", "must be")
        out.append(f"{where}: {msg}")
    return out
