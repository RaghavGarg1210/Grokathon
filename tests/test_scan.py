from datetime import date

import pytest

from crier.models import ScanResult
from crier.ports import ParsedResult, ScanBatch
from crier.scan import scan_city, to_briefing
from crier.scanners import EXTRACT_INSTRUCTIONS, SearchScanner, XSearchScanner
from tests.fakes import CITY, POST_URL, FakeLLM, FakeSearch, hit, scanned_post

TODAY = date(2026, 11, 2)
FROM = date(2026, 10, 3)
PAGE_URL = "https://www.exampleton.gov/news/facade-grant/"


def grounded(*urls: str) -> ScanBatch:
    return ScanBatch(posts=[], source_urls=list(urls), grounded=True)


def convert(post, batch=None):
    return to_briefing(post, CITY, batch or grounded(post.post_url), today=TODAY, from_date=FROM)


def test_x_post_becomes_briefing_with_canonical_url():
    post = scanned_post(post_url="https://twitter.com/ExampletonGA/status/42?s=20")
    briefing = convert(post, grounded("https://x.com/ExampletonGA/status/42"))
    assert briefing is not None
    assert briefing.post_url == "https://x.com/ExampletonGA/status/42"
    assert briefing.is_x_post and briefing.source_label == "@ExampletonGA on X"
    assert briefing.deadline == date(2026, 12, 1)


def test_official_page_becomes_briefing_labelled_by_host():
    briefing = convert(scanned_post(post_url=PAGE_URL, author_handle=""))
    assert briefing is not None
    assert briefing.post_url == "https://www.exampleton.gov/news/facade-grant"
    assert briefing.author_handle == "exampleton.gov"
    assert not briefing.is_x_post and briefing.source_label == "exampleton.gov"


def test_grounded_scan_rejects_urls_missing_from_search_results():
    batch = grounded("https://x.com/ExampletonGA/status/999")
    assert convert(scanned_post(), batch) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/post/1",
        "https://x.com/SomeoneElse/status/1",
        "https://exampleton-news.com/grant",
        "not a url",
    ],
)
def test_untrusted_sources_are_rejected(url):
    assert convert(scanned_post(post_url=url)) is None


@pytest.mark.parametrize("posted_on", ["2027-01-01", "2026-09-01", "soon"])
def test_dates_outside_scan_window_are_rejected(posted_on):
    assert convert(scanned_post(posted_on=posted_on)) is None


def test_ungrounded_uncited_post_is_downgraded_to_low_confidence():
    batch = ScanBatch(posts=[], source_urls=["https://x.com/ExampletonGA/status/9"], grounded=False)
    briefing = convert(scanned_post(), batch)
    assert briefing is not None and briefing.confidence == "low"


def test_ungrounded_cited_post_keeps_confidence():
    batch = ScanBatch(posts=[], source_urls=[POST_URL], grounded=False)
    assert convert(scanned_post(), batch).confidence == "high"


def test_search_scanner_queries_x_and_city_site_then_extracts():
    search = FakeSearch([[hit()], [hit(PAGE_URL), hit()]])
    llm = FakeLLM(
        [
            ScanResult(
                posts=[
                    scanned_post(),
                    scanned_post(post_url=PAGE_URL, author_handle=""),
                    scanned_post(post_url="https://x.com/ExampletonGA/status/777"),
                ]
            )
        ]
    )
    scan = scan_city(SearchScanner(search, llm), CITY, today=TODAY, scan_days=30)
    x_call, web_call = search.calls
    assert x_call["include_domains"] == ["x.com", "twitter.com"]
    assert "@ExampletonGA" in x_call["query"]
    assert web_call["include_domains"] == ["exampleton.gov"]
    assert x_call["start_date"] == FROM and x_call["end_date"] == date(2026, 11, 3)
    assert llm.calls[0]["instructions"] == EXTRACT_INSTRUCTIONS
    assert PAGE_URL in llm.calls[0]["prompt"]
    assert len(scan.briefings) == 2 and scan.rejected == 1
    assert scan.usage["search_results"] == 2


def test_search_scanner_skips_llm_when_search_finds_nothing():
    llm = FakeLLM()
    scan = scan_city(SearchScanner(FakeSearch(), llm), CITY, today=TODAY, scan_days=30)
    assert scan.briefings == [] and llm.calls == []


def test_search_scanner_uses_domains_only_when_no_handles():
    search = FakeSearch()
    city = CITY.model_copy(update={"handles": []})
    scan_city(SearchScanner(search, FakeLLM()), city, today=TODAY, scan_days=30)
    assert [c["include_domains"] for c in search.calls] == [["exampleton.gov"]]


def test_city_without_handles_or_domains_cannot_be_scanned():
    city = CITY.model_copy(update={"handles": [], "domains": []})
    with pytest.raises(ValueError):
        scan_city(SearchScanner(FakeSearch(), FakeLLM()), city, today=TODAY, scan_days=30)


def test_x_search_scanner_sends_handle_and_date_filters():
    result = ScanResult(
        posts=[scanned_post(), scanned_post(post_url="https://x.com/Other/status/1")]
    )
    grok = FakeLLM([ParsedResult(result, citations=[], usage={"x": 1})])
    scan = scan_city(XSearchScanner(grok, max_turns=2), CITY, today=TODAY, scan_days=30)
    tool = grok.calls[0]["tools"][0]
    assert tool["type"] == "x_search"
    assert tool["allowed_x_handles"] == CITY.handles
    assert tool["from_date"] == "2026-10-03" and tool["to_date"] == "2026-11-03"
    assert grok.calls[0]["max_turns"] == 2
    assert len(scan.briefings) == 1 and scan.rejected == 1


def test_x_search_scanner_requires_handles():
    scanner = XSearchScanner(FakeLLM(), max_turns=1)
    assert scanner.missing_config(CITY.model_copy(update={"handles": []}))


def test_publishable_filters_campaign_and_low_relevance():
    briefing = convert(scanned_post())
    assert briefing.is_publishable(50)
    assert not briefing.model_copy(update={"is_campaign_or_personal": True}).is_publishable(50)
    assert not briefing.model_copy(update={"relevance_score": 40}).is_publishable(50)
    assert not briefing.model_copy(update={"category": "not_relevant"}).is_publishable(50)
