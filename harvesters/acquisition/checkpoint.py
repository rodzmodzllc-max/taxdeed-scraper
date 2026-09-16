"""Resumability checkpoints - Phase 39 Sections 56-57.

A long acquisition run that dies on page 40 of 60 should resume at page 40,
not at zero. This module holds the checkpoint value type and a small
file-backed store; adapters produce and consume checkpoints through
`AcquisitionResult.checkpoint` (a plain dict, deliberately - it has to
survive JSON serialization to be useful across processes).

Deliberately NOT a database table: Section 51/52 forbid schema changes and
production data modification this phase, and a checkpoint is operational
state, not product data. The JSON-file store below is enough for the
GitHub Actions runner model this project actually uses, and a future phase
can move it without changing any adapter, because adapters only ever see
the dict.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Checkpoint:
    """Section 56's logical checkpoint fields."""

    source_id: str
    state: str | None = None
    county: str | None = None
    page: int | None = None
    cursor: str | None = None
    last_record_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Checkpoint":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in payload.items() if k in known})

    @property
    def key(self) -> str:
        """Checkpoints are per (source, jurisdiction) - a Harris County run
        and a Tarrant County run against the same adapter must never share
        a resume point (Section 50's adversarial test 5, county-specific
        source state)."""
        jurisdiction = f"{self.state or '?'}/{self.county or 'statewide'}"
        return f"{self.source_id}::{jurisdiction}"


class CheckpointStore:
    """Small JSON-file store. Atomic write (temp file + replace) so an
    interrupted save cannot corrupt an existing checkpoint."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load_all(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt store must not stop an acquisition run - resuming
            # from zero is always safe, silently crashing is not.
            return {}

    def save(self, checkpoint: Checkpoint) -> None:
        data = self._load_all()
        data[checkpoint.key] = checkpoint.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def load(self, source_id: str, *, state: str | None = None, county: str | None = None) -> Checkpoint | None:
        probe = Checkpoint(source_id=source_id, state=state, county=county)
        payload = self._load_all().get(probe.key)
        return Checkpoint.from_dict(payload) if payload else None

    def clear(self, source_id: str, *, state: str | None = None, county: str | None = None) -> None:
        probe = Checkpoint(source_id=source_id, state=state, county=county)
        data = self._load_all()
        if probe.key in data:
            del data[probe.key]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)

    def keys(self) -> list[str]:
        return sorted(self._load_all().keys())
