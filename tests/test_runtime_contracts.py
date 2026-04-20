from jingyantai.runtime.contracts import ContractJudge, RoundContract
from jingyantai.runtime.policies import QualityRubric


def test_contract_judge_rejects_overwide_goal_cluster():
    contract = RoundContract(
        target_scope="Claude Code landscape",
        goal_cluster="expand+deepen+pricing+workflow",
        must_answer_questions=["Who are the direct competitors?"],
        required_evidence_types=["official", "github"],
        hard_checks=["direct competitor fit"],
        done_definition="Finish all research.",
        fallback_plan="Use cached evidence.",
    )

    decision = ContractJudge().run(contract)

    assert decision.is_valid is False
    assert "single goal cluster" in decision.reasons[0]


def test_contract_judge_accepts_focused_contract():
    contract = RoundContract(
        target_scope="confirmed candidates",
        goal_cluster="resolve pricing uncertainty",
        must_answer_questions=["How is access or pricing exposed?"],
        required_evidence_types=["official"],
        hard_checks=["must cite official source"],
        done_definition="At least 2 confirmed competitors have pricing/access findings.",
        fallback_plan="Keep unresolved items as uncertainties.",
    )

    decision = ContractJudge().run(contract)

    assert decision.is_valid is True


def test_contract_judge_rejects_empty_hard_checks():
    contract = RoundContract(
        target_scope="scope with focus",
        goal_cluster="resolve pricing uncertainty",
        must_answer_questions=["How is access or pricing exposed?"],
        required_evidence_types=["official"],
        hard_checks=[],
        done_definition="At least 2 confirmed competitors have pricing/access findings.",
        fallback_plan="Keep unresolved items as uncertainties.",
    )

    decision = ContractJudge().run(contract)

    assert decision.is_valid is False
    assert "hard check" in decision.reasons[0].lower()


def test_contract_judge_rejects_generic_done_definition():
    contract = RoundContract(
        target_scope="tester",
        goal_cluster="resolve pricing uncertainty",
        must_answer_questions=["How is access or pricing exposed?"],
        required_evidence_types=["official"],
        hard_checks=["must cite official source"],
        done_definition="Complete the research.",
        fallback_plan="Keep unresolved items as uncertainties.",
    )

    decision = ContractJudge().run(contract)

    assert decision.is_valid is False
    assert "done definition" in decision.reasons[0].lower()


def test_contract_judge_respects_rubric_rejection_rules():
    contract = RoundContract(
        target_scope="confirmed candidates",
        goal_cluster="expand+deepen",
        must_answer_questions=["Which direct competitors matter most?"],
        required_evidence_types=["official"],
        hard_checks=["must cite official source"],
        done_definition="At least 2 confirmed competitors are covered on workflow.",
        fallback_plan="Keep unresolved items as uncertainties.",
    )

    rubric = QualityRubric(
        rejection_rules=[
            "require_hard_checks",
            "concrete_done_definition",
        ]
    )
    decision = ContractJudge(rubric=rubric).run(contract)

    assert decision.is_valid is True
