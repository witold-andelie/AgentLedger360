from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from agentledger.db import connect, init_db, transaction
from agentledger.economy import ledger


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AL_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("AL_DATA_SOURCE", "synthetic")
    # Deterministic by default: no test may call a real LLM (agent tests inject a scripted model).
    monkeypatch.setenv("AL_AGENT_MODE", "rule")
    monkeypatch.setenv("AL_LLM_PROVIDER", "mistral")
    monkeypatch.delenv("AL_LLM_MODEL", raising=False)
    monkeypatch.delenv("AL_LLM_PRICE_IN", raising=False)
    monkeypatch.delenv("AL_LLM_PRICE_OUT", raising=False)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    c = connect()
    init_db(c)
    with transaction(c):
        ledger.ensure_system_wallets(c)
    yield c
    c.close()
