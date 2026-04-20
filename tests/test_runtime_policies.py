from jingyantai.runtime.policies import (
    ContextStrategy,
    DegradeAction,
    PhasePolicy,
    RetryDecision,
    RetryPolicy,
    RuntimePolicy,
)


def test_runtime_policy_exposes_default_phase_policies():
    policy = RuntimePolicy.default()

    assert policy.context_strategy == ContextStrategy.CONTINUOUS_COMPACTION
    expected_degrade_actions = {
        "initialize": DegradeAction.USE_CACHED_RESULTS_ONLY,
        "expand": DegradeAction.REDUCE_SEARCH_RESULTS,
        "deepen": DegradeAction.REDUCE_DEEPEN_TARGETS,
        "challenge": DegradeAction.MARK_CANDIDATE_LOW_CONFIDENCE,
        "decide": DegradeAction.FALLBACK_GITHUB_ONLY,
    }
    for phase, expected_action in expected_degrade_actions.items():
        phase_policy = policy.phase_policies.get(phase)
        assert phase_policy
        assert phase_policy.degrade_on[0] == expected_action
    expand = policy.phase_policies["expand"]
    deepen = policy.phase_policies["deepen"]
    initialize = policy.phase_policies["initialize"]
    challenge = policy.phase_policies["challenge"]
    decide = policy.phase_policies["decide"]
    assert expand.max_attempts == 3
    assert deepen.max_attempts == 2
    assert deepen.allow_partial_success is True
    assert initialize.max_attempts == 1
    assert challenge.max_attempts == 1
    assert decide.max_attempts == 1
    assert initialize.soft_timeout_seconds == 5.0
    assert expand.soft_timeout_seconds == 30.0
    assert deepen.soft_timeout_seconds == 60.0
    assert challenge.soft_timeout_seconds == 20.0
    assert decide.soft_timeout_seconds == 15.0



def test_retry_policy_maps_timeout_to_retry_then_degrade():
    policy = RetryPolicy.default()

    first = policy.decide(error_kind="timeout", attempt=1, phase_name="deepen")
    second = policy.decide(error_kind="timeout", attempt=2, phase_name="deepen")

    assert first.decision == RetryDecision.RETRY
    assert second.decision == RetryDecision.DEGRADE
    assert second.degrade_action == DegradeAction.REDUCE_DEEPEN_TARGETS
    assert first.degrade_action is None


def test_retry_policy_marks_bad_candidate_as_skip():
    policy = RetryPolicy.default()

    decision = policy.decide(error_kind="bad_candidate", attempt=1, phase_name="deepen")

    assert decision.decision == RetryDecision.SKIP
    assert decision.degrade_action is None


def test_retry_policy_uses_phase_degrade_order_and_limits():
    policy = RetryPolicy.default()

    outcome = policy.decide(error_kind="timeout", attempt=3, phase_name="expand")

    assert outcome.decision == RetryDecision.DEGRADE
    assert outcome.degrade_action == DegradeAction.REDUCE_SEARCH_RESULTS


def test_retry_policy_unknown_error_fails_phase():
    policy = RetryPolicy.default()

    outcome = policy.decide(error_kind="network", attempt=1, phase_name="deepen")

    assert outcome.decision == RetryDecision.FAIL_PHASE
    assert outcome.degrade_action is None


def test_retry_policy_unknown_phase_fails():
    policy = RetryPolicy.default()

    outcome = policy.decide(error_kind="timeout", attempt=1, phase_name="unknown")

    assert outcome.decision == RetryDecision.FAIL_PHASE
    assert outcome.degrade_action is None


def test_runtime_policy_default_shares_phase_table_with_retry_policy():
    policy = RuntimePolicy.default()

    assert policy.retry_policy.phase_policies is policy.phase_policies


def test_retry_policy_retries_schema_validation_once_then_skips():
    policy = RetryPolicy.default()

    first = policy.decide(error_kind="schema_validation", attempt=1, phase_name="deepen")
    second = policy.decide(error_kind="schema_validation", attempt=2, phase_name="deepen")

    assert first.decision == RetryDecision.RETRY
    assert second.decision == RetryDecision.SKIP
    assert second.degrade_action is None


def test_retry_policy_retries_provider_request_then_degrades_at_limit():
    policy = RetryPolicy(
        phase_policies={
            "expand": PhasePolicy(
                soft_timeout_seconds=30.0,
                max_attempts=2,
                degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
            )
        }
    )

    first = policy.decide(error_kind="provider_request", attempt=1, phase_name="expand")
    second = policy.decide(error_kind="provider_request", attempt=2, phase_name="expand")

    assert first.decision == RetryDecision.RETRY
    assert second.decision == RetryDecision.DEGRADE
    assert second.degrade_action == DegradeAction.REDUCE_SEARCH_RESULTS


def test_retry_policy_degrades_tool_fetch_failures_immediately():
    policy = RetryPolicy(
        phase_policies={
            "deepen": PhasePolicy(
                soft_timeout_seconds=60.0,
                max_attempts=2,
                allow_partial_success=True,
                degrade_on=[DegradeAction.REDUCE_DEEPEN_TARGETS],
            )
        }
    )

    outcome = policy.decide(error_kind="tool_fetch", attempt=1, phase_name="deepen")

    assert outcome.decision == RetryDecision.DEGRADE
    assert outcome.degrade_action == DegradeAction.REDUCE_DEEPEN_TARGETS
