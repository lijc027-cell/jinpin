from pydantic import BaseModel, Field, field_validator

from jingyantai.domain.models import BudgetPolicy
from jingyantai.runtime.policies import QualityRubric


class ResearchSpec(BaseModel):
    target: str
    mission: str
    product_type: str
    competitor_definition: str
    scope: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    required_dimensions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    research_agenda: list[str] = Field(default_factory=list)
    stop_policy: str
    budget: BudgetPolicy
    quality_rubric: QualityRubric


class RoundContract(BaseModel):
    target_scope: str
    goal_cluster: str
    must_answer_questions: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    hard_checks: list[str] = Field(default_factory=list)
    done_definition: str
    fallback_plan: str

    @field_validator("target_scope", "goal_cluster", "done_definition", "fallback_plan")
    def _non_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty or whitespace")
        return value


class ContractDecision(BaseModel):
    is_valid: bool
    reasons: list[str] = Field(default_factory=list)


GENERIC_DONE_DEFINITIONS = (
    "finish all research",
    "complete the research",
    "complete research",
    "research everything",
    "research all",
)


def _is_generic_done_definition(definition: str) -> bool:
    normalized = definition.lower().strip().rstrip(".")
    return any(normalized.startswith(phrase) for phrase in GENERIC_DONE_DEFINITIONS)


class ContractJudge:
    def __init__(self, rubric: QualityRubric | None = None) -> None:
        self.rubric = rubric or QualityRubric.default()

    def run(self, contract: RoundContract) -> ContractDecision:
        rejection_rules = set(self.rubric.rejection_rules)

        if "single_goal_cluster" in rejection_rules and "+" in contract.goal_cluster:
            return ContractDecision(
                is_valid=False,
                reasons=["RoundContract must focus on a single goal cluster."],
            )
        if "require_hard_checks" in rejection_rules and not contract.hard_checks:
            return ContractDecision(
                is_valid=False,
                reasons=["RoundContract must include at least one hard check."],
            )
        if "concrete_done_definition" in rejection_rules and _is_generic_done_definition(contract.done_definition):
            return ContractDecision(
                is_valid=False,
                reasons=["Done definition must be concretely verifiable."],
            )
        return ContractDecision(is_valid=True, reasons=[])
