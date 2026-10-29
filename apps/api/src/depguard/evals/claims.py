"""Free-text claims (spec §7): does the advisory back what the explanation says in words?

Deterministic rules, no LLM. Each rule has trigger phrases (the explanation makes the claim) and
either support phrases (the advisory summary or details the agent saw must contain one) or a
stored flag (KEV, malicious, dev-only) that must be true. Only these claim types are measured;
docs/evals.md says what that leaves out.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from depguard.agent.context import FindingContext

# "not remotely exploitable", "isn't in CISA's known exploited list": a claim denied, not made.
NEGATION = re.compile(r"\b(?:not|no|never|without|cannot)\b|n't\b", re.IGNORECASE)
NEGATION_WORDS = 6  # how far before the trigger a negation counts, within its clause
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
# "If you don't upgrade, attackers can run code": the negation is in another clause.
CLAUSE_BREAK = re.compile(r"[,;:]")


@dataclass(frozen=True)
class Rule:
    name: str
    triggers: tuple[str, ...]
    support: tuple[str, ...] = ()
    flag: Callable[[FindingContext], bool] | None = None  # when set, only the flag backs it


RULES = (
    Rule(
        "remote",
        (r"\bremote(?:ly)?\b", r"\bover the (?:network|internet)\b"),
        (r"\bremote", r"\bnetwork", r"\binternet", r"\bhttp", r"\burl"),
    ),
    Rule(
        "no login needed",
        (
            r"\bunauthenticated\b",
            r"\bwithout (?:logging in|a login|login|authentication|credentials|an account)\b",
            r"\bno (?:login|authentication|credentials) (?:is )?(?:needed|required)\b",
        ),
        (
            r"\bunauthenticated",
            r"\bwithout authentication",
            r"\bno authentication",
            r"\banonymous",
            r"\bany user\b",
        ),
    ),  # fmt: skip
    Rule(
        "code execution",
        (
            r"\b(?:execute|run)s? (?:arbitrary |malicious |their own |any )?(?:code|commands?)\b",
            r"\bcode execution\b",
            r"\brce\b",
        ),
        (
            r"\b(?:execut|run)\w* (?:arbitrary |malicious )?(?:code|commands?|scripts?)",
            r"\bcode execution",
            r"\brce\b",
            r"\bcode injection",
            r"\bcommand injection",
        ),
    ),  # fmt: skip
    Rule(
        "denial of service",
        (
            r"\bdenial[- ]of[- ]service\b",
            r"\bdos\b",
            r"\bredos\b",
            r"\bcrash",
            r"\bhang",
            r"\bfreeze",
            r"\bexhaust",
        ),
        (
            r"\bdenial[- ]of[- ]service",
            r"\bdos\b",
            r"\bredos\b",
            r"\bregular expression",
            r"\bcrash",
            r"\bexhaust",
            r"\bhang",
            r"\binfinite loop",
            r"\bbacktracking",
            r"\bresource consumption",
            r"\bmemory",
        ),
    ),  # fmt: skip
    Rule(
        "prototype pollution",
        (
            r"\bprototype pollution\b",
            r"\b(?:change|modify|pollute)\w* (?:the )?(?:object )?prototype",
        ),
        (r"\bprototype",),
    ),
    Rule(
        "cross-site scripting",
        (
            r"\bcross[- ]site scripting\b",
            r"\bxss\b",
            r"\binject\w* (?:malicious )?(?:scripts?|html|javascript)\b",
        ),
        (r"\bcross[- ]site scripting", r"\bxss\b", r"\bscript", r"\bhtml"),
    ),  # fmt: skip
    Rule("sql injection", (r"\bsql injection\b",), (r"\bsql",)),
    Rule("command injection", (r"\bcommand injection\b",), (r"\bcommand injection", r"\bshell")),
    Rule(
        "path traversal",
        (
            r"\b(?:path|directory) traversal\b",
            r"\b(?:read|write|access)\w* (?:any |arbitrary )?files? outside\b",
        ),
        (
            r"\b(?:path|directory) traversal",
            r"\.\./",
            r"\boutside (?:of )?the",
            r"\barbitrary files?",
        ),
    ),  # fmt: skip
    Rule(
        "information disclosure",
        (
            r"\b(?:leak|expos|disclos|reveal)\w* (?:sensitive |private |confidential )?"
            r"(?:information|data|credentials|secrets)\b",
        ),
        (r"\bleak", r"\bexpos", r"\bdisclos", r"\breveal", r"\bsensitive"),
    ),  # fmt: skip
    Rule(
        "actively exploited",
        (
            r"\bactively exploited\b",
            r"\bexploited in the wild\b",
            r"\bknown to be exploited\b",
            r"\battackers are (?:already )?(?:using|exploiting)\b",
        ),
        flag=lambda context: context.in_kev,
    ),  # fmt: skip
    Rule(
        "malicious package",
        (
            r"\bmalicious package\b",
            r"\bpackage (?:itself )?(?:is|was) malicious\b",
            r"\bmalware\b",
            r"\bcontains malicious code\b",
        ),
        flag=lambda context: context.is_malicious,
    ),  # fmt: skip
    Rule(
        "dev-only",
        (
            r"\bonly (?:used |needed )?(?:in|for|during) development\b",
            r"\bdev(?:elopment)?[- ]only\b",
            r"\bdevelopment dependency\b",
            r"\bdevdependenc",
        ),
        flag=lambda context: context.is_dev,
    ),  # fmt: skip
)


@dataclass(frozen=True)
class Claim:
    rule: str
    sentence: str
    supported: bool


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(text) if s.strip()]


def negated(sentence: str, start: int) -> bool:
    clause = CLAUSE_BREAK.split(sentence[:start])[-1]
    before = clause.split()[-NEGATION_WORDS:]
    return bool(NEGATION.search(" ".join(before)))


def makes(rule: Rule, sentence: str) -> bool:
    for trigger in rule.triggers:
        for match in re.finditer(trigger, sentence, re.IGNORECASE):
            if not negated(sentence, match.start()):
                return True
    return False


def supported(rule: Rule, context: FindingContext) -> bool:
    if rule.flag is not None:
        return rule.flag(context)
    # The same text the agent saw: the summary and the details cut to MAX_DETAILS_CHARS.
    advisory = f"{context.summary or ''}\n{context.details or ''}"
    return any(re.search(phrase, advisory, re.IGNORECASE) for phrase in rule.support)


def find_claims(text: str, context: FindingContext) -> list[Claim]:
    """Each rule counts once per sentence; a sentence can make several claims."""
    return [
        Claim(rule.name, sentence, supported(rule, context))
        for sentence in sentences(text)
        for rule in RULES
        if makes(rule, sentence)
    ]


def percent(part: int, whole: int) -> Decimal | None:
    """One decimal; None when there is nothing to divide (no claims is not 0%)."""
    if whole == 0:
        return None
    return (Decimal(100) * part / whole).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
