from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from agentledger.contracts import Capability, Deliverable, TaskSpec, canonical_hash
from agentledger.market import quality
from agentledger.market.research_note import build_note
from agentledger.sellers.app import create_app
from agentledger.sellers.catalog import RESEARCH_TERMS, frame_to_rows

AS_OF = date(2026, 10, 7)


def _deliverable(frame) -> Deliverable:
    rows = frame_to_rows(frame)
    digest = canonical_hash(rows)
    return Deliverable(
        order_id="ord_note", seller_agent_id="res-note", capability=Capability.RESEARCH,
        symbol="AAPL", as_of=AS_OF, columns=list(rows[0].keys()), rows=rows, content_hash=digest,
    )


def test_research_seller_quotes_and_the_note_passes_the_contract():
    client = TestClient(create_app())
    task = TaskSpec(capability=Capability.RESEARCH, symbol="AAPL", as_of=AS_OF)
    quoted = client.post("/agents/res-note/tasks", json=task.model_dump(mode="json"))
    assert quoted.status_code == 402
    assert quoted.json()["amount_minor"] == 80
    frame = build_note(task)
    report = quality.evaluate(_deliverable(frame), RESEARCH_TERMS)
    assert report.passed, [c.detail for c in report.checks if not c.passed]


def test_a_stance_that_contradicts_the_tape_fails():
    task = TaskSpec(capability=Capability.RESEARCH, symbol="AAPL", as_of=AS_OF)
    frame = build_note(task)
    frame.loc[0, "stance"] = "FLAT" if frame.loc[0, "stance"] == "LONG" else "LONG"
    report = quality.evaluate(_deliverable(frame), RESEARCH_TERMS)
    assert not report.passed
    assert any(c.name == "stance_matches_tape" and not c.passed and c.critical for c in report.checks)
