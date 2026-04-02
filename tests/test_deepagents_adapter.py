from __future__ import annotations

from jingyantai.agents.deepagents_adapter import DeepagentsRoleAdapter
from jingyantai.domain.models import ResearchBrief


def test_deepagents_adapter_maps_runner_payload_to_model():
    def fake_runner(system_prompt: str, payload: dict) -> dict:
        assert "Initializer" in system_prompt
        assert payload["target"] == "Claude Code"
        return {
            "target": "Claude Code",
            "product_type": "coding-agent",
            "competitor_definition": "Direct competitors are terminal-native coding agents.",
            "required_dimensions": ["positioning", "workflow"],
            "stop_policy": "Stop after enough covered competitors.",
            "budget": {
                "max_rounds": 4,
                "max_active_candidates": 8,
                "max_deepen_targets": 3,
                "max_external_fetches": 30,
                "max_run_duration_minutes": 20,
            },
        }

    adapter = DeepagentsRoleAdapter(role_prompt="You are the Initializer.", runner=fake_runner)
    result = adapter.run({"target": "Claude Code"}, ResearchBrief)

    assert result.target == "Claude Code"
    assert result.product_type == "coding-agent"
