from enum import StrEnum

from pydantic import BaseModel, Field

from jingyantai.runtime.quality_rubric import QualityRubric


class ContextStrategy(StrEnum):
    CONTINUOUS_COMPACTION = "continuous_compaction"
    PERIODIC_RESET = "periodic_reset"
    HYBRID = "hybrid"


class RetryDecision(StrEnum):
    RETRY = "retry"
    DEGRADE = "degrade"
    SKIP = "skip"
    FAIL_PHASE = "fail_phase"


class DegradeAction(StrEnum):
    REDUCE_DEEPEN_TARGETS = "reduce_deepen_targets"
    REDUCE_SEARCH_RESULTS = "reduce_search_results"
    USE_CACHED_RESULTS_ONLY = "use_cached_results_only"
    FALLBACK_GITHUB_ONLY = "fallback_github_only"
    MARK_CANDIDATE_LOW_CONFIDENCE = "mark_candidate_low_confidence"
    SKIP_SLOWEST_CANDIDATES = "skip_slowest_candidates"


class PhasePolicy(BaseModel):
    soft_timeout_seconds: float = Field(..., gt=0)
    allow_partial_success: bool = False
    max_attempts: int = Field(1, ge=1)
    degrade_on: list[DegradeAction] = Field(default_factory=list)


class RetryOutcome(BaseModel):
    decision: RetryDecision
    degrade_action: DegradeAction | None = None


def _default_phase_policies() -> dict[str, PhasePolicy]:
    return {
        "initialize": PhasePolicy(
            soft_timeout_seconds=5.0,
            max_attempts=1,
            degrade_on=[DegradeAction.USE_CACHED_RESULTS_ONLY],
        ),
        "expand": PhasePolicy(
            soft_timeout_seconds=30.0,
            max_attempts=3,
            degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
        ),
        "deepen": PhasePolicy(
            soft_timeout_seconds=60.0,
            allow_partial_success=True,
            max_attempts=2,
            degrade_on=[
                DegradeAction.REDUCE_DEEPEN_TARGETS,
                DegradeAction.SKIP_SLOWEST_CANDIDATES,
            ],
        ),
        "challenge": PhasePolicy(
            soft_timeout_seconds=20.0,
            max_attempts=1,
            degrade_on=[DegradeAction.MARK_CANDIDATE_LOW_CONFIDENCE],
        ),
        "decide": PhasePolicy(
            soft_timeout_seconds=15.0,
            max_attempts=1,
            degrade_on=[DegradeAction.FALLBACK_GITHUB_ONLY],
        ),
    }


class RetryPolicy(BaseModel):
    phase_policies: dict[str, PhasePolicy] = Field(default_factory=_default_phase_policies)

    @classmethod
    def default(cls) -> "RetryPolicy":
        return cls()

    def decide(self, *, error_kind: str, attempt: int, phase_name: str) -> RetryOutcome:
        phase_policy = self.phase_policies.get(phase_name)
        if error_kind == "bad_candidate":
            return RetryOutcome(decision=RetryDecision.SKIP)
        if phase_policy is None:
            return RetryOutcome(decision=RetryDecision.FAIL_PHASE)
        if error_kind == "schema_validation":
            if attempt == 1:
                return RetryOutcome(decision=RetryDecision.RETRY)
            return RetryOutcome(decision=RetryDecision.SKIP)
        if error_kind == "provider_request":
            if attempt < phase_policy.max_attempts:
                return RetryOutcome(decision=RetryDecision.RETRY)
            degrade_action = phase_policy.degrade_on[0] if phase_policy.degrade_on else None
            return RetryOutcome(
                decision=RetryDecision.DEGRADE,
                degrade_action=degrade_action,
            )
        if error_kind in {"tool_fetch", "page_extract_failure"}:
            degrade_action = phase_policy.degrade_on[0] if phase_policy.degrade_on else None
            return RetryOutcome(
                decision=RetryDecision.DEGRADE,
                degrade_action=degrade_action,
            )
        if error_kind == "timeout":
            if attempt < phase_policy.max_attempts:
                return RetryOutcome(decision=RetryDecision.RETRY)
            degrade_action = phase_policy.degrade_on[0] if phase_policy.degrade_on else None
            return RetryOutcome(
                decision=RetryDecision.DEGRADE,
                degrade_action=degrade_action,
            )
        return RetryOutcome(decision=RetryDecision.FAIL_PHASE)


class RuntimePolicy(BaseModel):
    context_strategy: ContextStrategy
    phase_policies: dict[str, PhasePolicy] = Field(default_factory=_default_phase_policies)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy.default)

    @classmethod
    def default(cls) -> "RuntimePolicy":
        phase_policies = _default_phase_policies()
        retry_policy = RetryPolicy(phase_policies=phase_policies)
        runtime_policy = cls(
            context_strategy=ContextStrategy.CONTINUOUS_COMPACTION,
            phase_policies=phase_policies,
            retry_policy=retry_policy,
        )
        runtime_policy.retry_policy.phase_policies = runtime_policy.phase_policies
        return runtime_policy


class StopBar(BaseModel):
    """Stop thresholds for StopJudge and future convergence gates.

    Note: convergence-related fields are reserved for a follow-up gate and are not fully enforced yet.
    """

    min_confirmed_candidates: int = Field(3, ge=1)
    min_coverage_ratio: float = Field(0.8, ge=0.0, le=1.0)
    max_high_impact_uncertainties: int = Field(0, ge=0)
    max_new_confirmed_for_convergence: int = Field(
        1,
        ge=0,
        description="Reserved for a future convergence gate; not fully enforced yet.",
    )
    max_new_findings_for_convergence: int = Field(
        2,
        ge=0,
        description="Reserved for a future convergence gate; not fully enforced yet.",
    )

    @classmethod
    def default(cls) -> "StopBar":
        return cls()
