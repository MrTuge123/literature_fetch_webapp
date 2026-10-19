"""Where a subscriber's state lives: which papers they've received (seen) and every candidate
ranked for them (history). The pipeline only talks to a Store, so the same code runs with:

    FileStore    seen/<id>.json and history/<id>.jsonl in this folder (today, and local runs)
    DynamoStore  the LitFetch DynamoDB table (M2; same five methods)
"""
from typing import Protocol, runtime_checkable

from digest import history, store


@runtime_checkable
class Store(Protocol):
    def load_seen(self, sid: str) -> set[str]:
        """Every ID of every paper the subscriber has received."""

    def add_seen(self, sid: str, ids: set[str]) -> None:
        """Remember these IDs as received (never forgets older ones)."""

    def load_history(self, sid: str) -> list[dict]:
        """Every candidate ranked for the subscriber, one record per paper, oldest first."""

    def save_history(self, sid: str, ranked: list[dict], posted: list[dict]) -> None:
        """Add this run's ranked candidates; `posted` are the ones some chat received."""

    def set_references(self, sid: str, updates: dict) -> None:
        """Save reference lists OpenAlex had no data for when a paper was first saved."""


class FileStore:
    """seen/ and history/ files (digest/store.py and digest/history.py do the work)."""

    def load_seen(self, sid):
        return store.load_seen(sid)

    def add_seen(self, sid, ids):
        store.save_seen(sid, ids)

    def load_history(self, sid):
        return history.load_history(sid)

    def save_history(self, sid, ranked, posted):
        history.save_history(sid, ranked, posted)

    def set_references(self, sid, updates):
        history.set_references(sid, updates)
