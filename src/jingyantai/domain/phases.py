from enum import StrEnum


class Phase(StrEnum):
    INITIALIZE = "initialize"
    EXPAND = "expand"
    CONVERGE = "converge"
    DEEPEN = "deepen"
    CHALLENGE = "challenge"
    DECIDE = "decide"
    STOP = "stop"


class CandidateStatus(StrEnum):
    DISCOVERED = "discovered"
    NORMALIZED = "normalized"
    PLAUSIBLE = "plausible"
    PRIORITIZED = "prioritized"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class HypothesisStatus(StrEnum):
    UNTESTED = "untested"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"


class ReviewVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class StopVerdict(StrEnum):
    STOP = "stop"
    CONTINUE = "continue"


class GapPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
