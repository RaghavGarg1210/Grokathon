from crier.models import Draft
from crier.store import Store
from tests.fakes import briefing, video_script


def test_add_briefing_deduplicates(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    assert store.add_briefing(briefing()) is True
    assert store.add_briefing(briefing(headline="changed")) is False
    assert [b.headline for b in store.list_briefings()] == [briefing().headline]


def test_update_and_get_briefing(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    original = briefing(verification="unverified")
    store.add_briefing(original)
    store.update_briefing(original.model_copy(update={"verification": "verified"}))
    assert store.get_briefing(original.id).verification == "verified"


def test_draft_roundtrip_and_latest(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    first = store.save_draft(Draft(id="d1", briefing_id="b1", script=video_script()))
    store.save_draft(Draft(id="d2", briefing_id="b1", script=video_script(beats=4)))
    assert store.get_draft("d1").script == first.script
    assert store.latest_draft_for("b1").id == "d2"
    assert store.list_drafts(status="approved") == []


def test_scan_runs_recorded(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.record_scan_run("Exampleton", kept=2, new=1, rejected=0, usage={"x_posts_fetched": 9})
    runs = store.list_scan_runs()
    assert runs[0]["city"] == "Exampleton" and runs[0]["new"] == 1
