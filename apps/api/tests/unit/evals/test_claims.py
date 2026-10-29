from decimal import Decimal

from fake_llm import lodash

from depguard.evals.claims import find_claims, percent

# lodash's advisory: "Prototype Pollution in lodash" / "...vulnerable to Prototype Pollution."


def rules(text: str, **changes: object) -> list[tuple[str, bool]]:
    return [(c.rule, c.supported) for c in find_claims(text, lodash(**changes))]


def test_a_claim_the_advisory_backs() -> None:
    assert rules("An attacker can cause prototype pollution.") == [("prototype pollution", True)]


def test_a_claim_the_advisory_does_not_back() -> None:
    assert rules("It is remotely exploitable.") == [("remote", False)]


def test_a_denied_claim_is_not_a_claim() -> None:
    assert rules("It is not remotely exploitable.") == []
    assert rules("It isn't known to be exploited in the wild.") == []


def test_no_login_needed_is_a_claim_although_it_starts_with_without() -> None:
    assert rules("Anyone can do it without logging in.") == [("no login needed", False)]


def test_one_sentence_can_make_two_claims() -> None:
    claims = rules("A remote attacker can run arbitrary code.")
    assert claims == [("remote", False), ("code execution", False)]


def test_each_sentence_counts_separately() -> None:
    text = "It allows prototype pollution. Prototype pollution can crash the app."
    assert rules(text) == [  # per sentence, in RULES order
        ("prototype pollution", True),
        ("denial of service", False),
        ("prototype pollution", True),
    ]


def test_actively_exploited_needs_kev() -> None:
    text = "This flaw is actively exploited by attackers."
    assert rules(text, in_kev=True) == [("actively exploited", True)]
    assert rules(text, in_kev=False) == [("actively exploited", False)]


def test_malicious_and_dev_only_need_their_flags() -> None:
    assert rules("This is a malicious package.", is_malicious=True) == [("malicious package", True)]
    assert rules("It is a development dependency.") == [("dev-only", False)]
    assert rules("It is a development dependency.", is_dev=True) == [("dev-only", True)]


def test_only_the_text_the_agent_saw_counts_as_support() -> None:
    # The details are cut to 600 characters before the agent sees them; the golden set stores them
    # cut, so support beyond the cut can't be found.
    assert rules("It is remotely exploitable.", details="A remote attacker can do this.") == [
        ("remote", True)
    ]


def test_plain_text_without_claims() -> None:
    assert rules("Upgrade lodash to 4.17.12.") == []


def test_percent() -> None:
    assert percent(2, 3) == Decimal("66.7")
    assert percent(3, 3) == Decimal("100.0")
    assert percent(0, 0) is None  # no claims is "no claims", not 0%
