from pathlib import Path

from jingyantai.runtime.memory import FileMemoryStore, MemorySnapshot, RunMemoryEntry, WatchlistItem


def test_file_memory_store_persists_snapshot_and_watchlist(tmp_path: Path):
    store = FileMemoryStore(tmp_path)
    snapshot = MemorySnapshot(
        top_competitors=["Aider", "OpenAI Codex"],
        unresolved_uncertainties=["Pricing remains unclear."],
        trusted_sources=["https://aider.chat"],
        repeated_failure_patterns=["timeout: developers.google.com"],
    )
    watchlist = [
        WatchlistItem(
            entity_name="OpenAI Codex",
            canonical_url="https://openai.com/index/codex",
            watch_reason="pricing uncertainty",
            revisit_trigger="official pricing page changes",
            priority="high",
            last_seen_run_id="run-1",
        )
    ]

    store.save_snapshot(snapshot)
    store.save_watchlist(watchlist)

    assert store.load_snapshot() == snapshot
    assert store.load_watchlist() == watchlist


def test_load_returns_defaults_when_files_missing(tmp_path: Path):
    store = FileMemoryStore(tmp_path)

    assert store.load_snapshot() == MemorySnapshot()
    assert store.load_watchlist() == []


def test_save_overwrites_previous_values(tmp_path: Path):
    store = FileMemoryStore(tmp_path)

    first_snapshot = MemorySnapshot(top_competitors=["Initial"])
    second_snapshot = MemorySnapshot(top_competitors=["Updated"])
    first_watchlist = [
        WatchlistItem(
            entity_name="Initial Enemy",
            canonical_url="https://initial.example",
            watch_reason="initial reason",
            revisit_trigger="initial trigger",
            priority="low",
            last_seen_run_id="run-init",
        )
    ]
    second_watchlist = [
        WatchlistItem(
            entity_name="Updated Enemy",
            canonical_url="https://updated.example",
            watch_reason="updated reason",
            revisit_trigger="updated trigger",
            priority="high",
            last_seen_run_id="run-updated",
        )
    ]

    store.save_snapshot(first_snapshot)
    store.save_watchlist(first_watchlist)
    assert store.load_snapshot() == first_snapshot
    assert store.load_watchlist() == first_watchlist

    store.save_snapshot(second_snapshot)
    store.save_watchlist(second_watchlist)
    assert store.load_snapshot() == second_snapshot
    assert store.load_watchlist() == second_watchlist


def test_file_memory_store_persists_memory_entries(tmp_path: Path):
    store = FileMemoryStore(tmp_path)
    entries = [
        RunMemoryEntry(
            run_id="run-1",
            target="Claude Code",
            confirmed_entities=["Aider", "OpenAI Codex"],
            unresolved_uncertainties=["Pricing remains unclear."],
            trusted_sources=["https://aider.chat"],
            repeated_failure_patterns=["timeout: developers.google.com"],
        )
    ]

    store.save_memory(entries)

    assert store.load_memory() == entries
