from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class WatchlistItem(BaseModel):
    entity_name: str
    canonical_url: str
    watch_reason: str
    revisit_trigger: str
    priority: str
    last_seen_run_id: str


class MemorySnapshot(BaseModel):
    top_competitors: list[str] = Field(default_factory=list)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    trusted_sources: list[str] = Field(default_factory=list)
    repeated_failure_patterns: list[str] = Field(default_factory=list)


class RunMemoryEntry(BaseModel):
    run_id: str
    target: str
    confirmed_entities: list[str] = Field(default_factory=list)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    trusted_sources: list[str] = Field(default_factory=list)
    repeated_failure_patterns: list[str] = Field(default_factory=list)


class FileMemoryStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.global_dir = self.root_dir / "_global"

    def save_snapshot(self, snapshot: MemorySnapshot) -> None:
        payload = snapshot.model_dump()
        self._write_json_atomic(self.global_dir / "latest-snapshot.json", payload)

    def load_snapshot(self) -> MemorySnapshot:
        snapshot_path = self.global_dir / "latest-snapshot.json"
        if not snapshot_path.exists():
            return MemorySnapshot()

        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return MemorySnapshot.model_validate(payload)

    def save_watchlist(self, items: list[WatchlistItem]) -> None:
        data = [item.model_dump() for item in items]
        self._write_json_atomic(self.global_dir / "watchlist.json", data)

    def load_watchlist(self) -> list[WatchlistItem]:
        watchlist_path = self.global_dir / "watchlist.json"
        if not watchlist_path.exists():
            return []

        payload = json.loads(watchlist_path.read_text(encoding="utf-8"))
        return [WatchlistItem.model_validate(item) for item in payload]

    def save_memory(self, entries: list[RunMemoryEntry]) -> None:
        data = [entry.model_dump() for entry in entries]
        self._write_json_atomic(self.global_dir / "memory.json", data)

    def load_memory(self) -> list[RunMemoryEntry]:
        memory_path = self.global_dir / "memory.json"
        if not memory_path.exists():
            return []

        payload = json.loads(memory_path.read_text(encoding="utf-8"))
        return [RunMemoryEntry.model_validate(item) for item in payload]

    def _write_json_atomic(self, target: Path, payload: object) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, indent=2)
        temp_path = target.with_name(f"{target.name}.tmp")
        temp_path.write_text(serialized, encoding="utf-8")
        temp_path.replace(target)
