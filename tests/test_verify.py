from datetime import date

from crier.models import VerificationResult
from crier.verifiers import GrokVerifier, SearchVerifier
from crier.verify import apply_verification, verify_briefing
from tests.fakes import FakeLLM, FakeSearch, briefing, hit

DOMAINS = ["exampleton.gov", "georgia.gov"]
OFFICIAL = "https://www.exampleton.gov/grant"


def unverified(**overrides):
    return briefing(verification="unverified", official_url=None, **overrides)


def test_verified_on_allowed_domain_updates_deadline():
    result = VerificationResult(
        status="verified", official_url=OFFICIAL, notes="Confirmed.", deadline="2026-12-15"
    )
    updated = apply_verification(unverified(), result, DOMAINS)
    assert updated.verification == "verified"
    assert updated.official_url == OFFICIAL
    assert updated.deadline == date(2026, 12, 15)


def test_verified_on_other_domain_is_downgraded():
    result = VerificationResult(
        status="verified", official_url="https://exampleton-news.com/x", notes=""
    )
    updated = apply_verification(unverified(), result, DOMAINS)
    assert updated.verification == "announced_only"
    assert updated.official_url is None


def test_subdomain_counts_as_allowed():
    result = VerificationResult(
        status="verified", official_url="https://econdev.exampleton.gov/a", notes=""
    )
    assert apply_verification(briefing(), result, DOMAINS).verification == "verified"


def test_contradicted_blocks_video():
    result = VerificationResult(
        status="contradicted", official_url="https://exampleton.gov/closed", notes="Program closed."
    )
    updated = apply_verification(briefing(), result, DOMAINS)
    assert updated.verification == "contradicted"
    assert not updated.can_make_video(override_unverified=True)


def test_no_domains_means_announced_only_without_api_call():
    llm = FakeLLM()
    updated = verify_briefing(SearchVerifier(FakeSearch(), llm), unverified(), [])
    assert updated.verification == "announced_only"
    assert llm.calls == []


def test_announcement_on_official_site_verifies_itself():
    search, llm = FakeSearch(), FakeLLM()
    page = unverified(post_url=OFFICIAL, author_handle="exampleton.gov")
    updated = verify_briefing(SearchVerifier(search, llm), page, DOMAINS)
    assert updated.verification == "verified" and updated.official_url == OFFICIAL
    assert search.calls == [] and llm.calls == []


def test_search_verifier_restricts_search_to_official_domains():
    search = FakeSearch([[hit(OFFICIAL, "Facade grant applications close Dec 15.")]])
    llm = FakeLLM(
        [VerificationResult(status="verified", official_url=OFFICIAL, notes="Confirmed.")]
    )
    updated = verify_briefing(SearchVerifier(search, llm), unverified(), DOMAINS)
    assert search.calls[0]["include_domains"] == DOMAINS
    assert OFFICIAL in llm.calls[0]["prompt"]
    assert updated.verification == "verified"


def test_search_verifier_without_results_skips_the_model():
    llm = FakeLLM()
    result = SearchVerifier(FakeSearch([[]]), llm).check(unverified(), DOMAINS)
    assert result.status == "announced_only" and llm.calls == []


def test_search_verifier_rejects_page_it_was_not_shown():
    search = FakeSearch([[hit(OFFICIAL)]])
    llm = FakeLLM(
        [
            VerificationResult(
                status="verified", official_url="https://exampleton.gov/invented", notes="ok"
            )
        ]
    )
    result = SearchVerifier(search, llm).check(unverified(), DOMAINS)
    assert result.status == "announced_only"


def test_grok_verifier_uses_domain_filter():
    grok = FakeLLM([VerificationResult(status="announced_only", notes="Nothing found.")])
    updated = verify_briefing(GrokVerifier(grok), unverified(), DOMAINS)
    assert grok.calls[0]["tools"][0] == {
        "type": "web_search",
        "filters": {"allowed_domains": DOMAINS},
    }
    assert updated.verification == "announced_only"
