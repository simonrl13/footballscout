"""Labelling UI: CSV round trip, atomic save, API, local-only guard (no DB, no GPU, no network)."""
import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from scout.finetune import label_ui
from scout.finetune.labels import COLUMNS, check, template

DOCS = pd.DataFrame({"doc_id": ["d1", "d2"], "url": ["u1", "u2"], "title": ["A B", "C D"], "snapshot": ["2020-09-01"] * 2,
                     "text": ["He joined Leeds on 3 July 2019.\nHe was injured.", "Nothing here."]})
EV = {"type": "transfer", "date": "2019-07-03", "contract_until": "", "injury_type": "", "duration_days": "",
      "evidence": "He joined Leeds on 3 July 2019", "note": "a, \"quoted\" note\nwith a newline"}


@pytest.fixture
def sheet(tmp_path):
    p = tmp_path / "test.csv"
    template(DOCS).to_csv(p, index=False)
    return p


def test_round_trip_keeps_the_template_byte_for_byte(sheet):
    before = sheet.read_bytes()
    label_ui.write_sheet(sheet, DOCS.doc_id.tolist(), label_ui.read_sheet(sheet))
    assert sheet.read_bytes() == before


def test_round_trip_with_events_renumbers_and_passes_check(sheet):
    rows = {"d1": [EV, EV | {"type": "injury", "date": "", "evidence": "He was injured"}], "d2": [{"type": "none"}]}
    label_ui.write_sheet(sheet, ["d1", "d2"], rows)
    df = pd.read_csv(sheet, dtype=str, keep_default_na=False)
    assert list(df.columns) == COLUMNS and df.row.tolist() == ["1", "2", "1"]
    assert label_ui.read_sheet(sheet)["d1"][0] == EV  # commas, quotes and newlines survive
    assert check(df, dict(zip(DOCS.doc_id, DOCS.text))) == []


def test_failed_save_leaves_the_sheet_intact(sheet, monkeypatch):
    before = sheet.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        label_ui.write_sheet(sheet, ["d1", "d2"], {"d1": [EV], "d2": [{"type": "none"}]})
    assert sheet.read_bytes() == before


def test_backup_copies_the_sheet(sheet):
    bak = label_ui.backup(sheet)
    assert bak.suffix == ".bak" and bak.read_bytes() == sheet.read_bytes()


def test_api_saves_reports_problems_and_resumes(sheet):
    c = TestClient(label_ui.create_app(DOCS, sheet), base_url="http://127.0.0.1:8765")
    d = c.get("/api/docs").json()
    assert (d["done"], d["total"], d["first_unlabelled"]) == (0, 2, 0)
    r = c.put("/api/doc/0", json={"rows": [EV | {"evidence": "not in the text"}]}).json()
    assert r["problems"] and "verbatim" in r["problems"][0] and r["progress"]["with_problems"] == [0]
    r = c.put("/api/doc/0", json={"rows": [EV]}).json()
    assert r["problems"] == [] and r["progress"]["done"] == 1 and r["progress"]["first_unlabelled"] == 1
    assert label_ui.read_sheet(sheet)["d1"] == [EV]
    assert c.put("/api/doc/0", json={"rows": []}).json()["labelled"] is False  # cleared: one blank row again
    assert pd.read_csv(sheet, dtype=str, keep_default_na=False).doc_id.tolist() == ["d1", "d2"]


def test_only_local_host_names_are_served(sheet):
    c = TestClient(label_ui.create_app(DOCS, sheet), base_url="http://127.0.0.1:8765")
    assert c.get("/", headers={"host": "evil.example:8765"}).status_code == 403
    assert c.get("/api/docs", headers={"host": "127.0.0.1:8765"}).status_code == 200
    assert c.get("/", headers={"host": "testserver"}).status_code == 403  # TestClient's default host isn't allowed


def test_page_never_shows_extractions_or_suggestions():
    page = label_ui.PAGE.read_text(encoding="utf-8")
    src = open(label_ui.__file__, encoding="utf-8").read()
    for word in ("text_extractions", "text_signals", "extract-v", "suggest"):
        assert word not in page and word not in src.split('"""', 2)[2]  # code below the docstring
