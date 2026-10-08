"""Acceptance tests = data contract. Used by the buyer (accept or dispute) and by the adjudicator
(re-executes the same code; trusts neither party). Critical failures -> full refund, performance -> partial.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from agentledger.contracts import (
    AcceptanceCriteria,
    Capability,
    CheckResult,
    Deliverable,
    QualityReport,
    canonical_hash,
)
from agentledger.market import backtest, data


def evaluate(deliverable: Deliverable, criteria: AcceptanceCriteria) -> QualityReport:
    checks: list[CheckResult] = []
    metrics: dict[str, float] = {}
    df = pd.DataFrame(deliverable.rows)

    missing = [c for c in criteria.required_columns if c not in df.columns]
    checks.append(CheckResult(name="schema", critical=True, passed=not missing,
                              detail=f"missing columns: {missing}" if missing else "ok"))
    checks.append(CheckResult(name="min_rows", critical=True, passed=len(df) >= criteria.min_rows,
                              detail=f"{len(df)} rows, need {criteria.min_rows}"))
    if missing or df.empty:
        return _report(checks, metrics)

    nulls = int(df[criteria.required_columns].isna().sum().sum())
    checks.append(CheckResult(name="not_null", critical=True, passed=nulls == 0, detail=f"{nulls} nulls"))

    if "date" in df.columns:
        dates = pd.to_datetime(df["date"])
        last = dates.max().date()
        fresh_cutoff = deliverable.as_of - timedelta(days=criteria.max_staleness_days)
        checks.append(CheckResult(name="freshness", critical=True, passed=last >= fresh_cutoff,
                                  detail=f"last row {last}, need >= {fresh_cutoff}"))
        # point-in-time integrity (TradingAgents-style): nothing dated after the as-of cutoff
        checks.append(CheckResult(name="point_in_time", critical=True, passed=last <= deliverable.as_of,
                                  detail=f"last row {last}, as_of {deliverable.as_of}"))

    if deliverable.capability == Capability.SIGNAL_5D:
        df["date"] = pd.to_datetime(df["date"])
        oracle = data.load_prices(deliverable.symbol, as_of=deliverable.as_of)
        result = backtest.evaluate_signal(df, oracle)
        metrics = result.as_metrics()
        if criteria.min_hit_rate is not None:
            checks.append(CheckResult(name="hit_rate", critical=False, passed=result.hit_rate >= criteria.min_hit_rate,
                                      detail=f"{result.hit_rate:.3f} vs min {criteria.min_hit_rate}"))
        if criteria.min_rank_ic is not None:
            checks.append(CheckResult(name="rank_ic", critical=False, passed=result.rank_ic >= criteria.min_rank_ic,
                                      detail=f"{result.rank_ic:.3f} vs min {criteria.min_rank_ic}"))

    if deliverable.capability == Capability.RESEARCH or criteria.min_note_chars is not None:
        _research_checks(checks, df, deliverable, criteria)
    return _report(checks, metrics)


def _research_checks(checks: list[CheckResult], df: pd.DataFrame, deliverable: Deliverable,
                     criteria: AcceptanceCriteria) -> None:
    """A research note is one row. The stance must match the tape; the prose must name the symbol."""
    from agentledger.market.research_note import expected_stance

    one_row = len(df) == 1
    checks.append(CheckResult(name="one_row", critical=True, passed=one_row, detail=f"{len(df)} rows"))
    if not one_row or "symbol" not in df.columns or "stance" not in df.columns or "note" not in df.columns:
        return
    row = df.iloc[0]
    symbol_ok = str(row["symbol"]).upper() == deliverable.symbol.upper()
    checks.append(CheckResult(name="symbol", critical=True, passed=symbol_ok,
                              detail=f"{row['symbol']} vs {deliverable.symbol}"))
    stance = str(row["stance"])
    vocab_ok = stance in ("LONG", "FLAT")
    checks.append(CheckResult(name="stance_vocab", critical=True, passed=vocab_ok, detail=stance))
    expected = expected_stance(deliverable.symbol, deliverable.as_of)
    checks.append(CheckResult(name="stance_matches_tape", critical=True, passed=stance == expected,
                              detail=f"{stance} vs tape {expected}"))
    note = str(row["note"])
    lo = criteria.min_note_chars or 40
    hi = criteria.max_note_chars or 400
    length_ok = lo <= len(note) <= hi
    checks.append(CheckResult(name="note_length", critical=True, passed=length_ok,
                              detail=f"{len(note)} chars, need {lo}-{hi}"))
    mentions = deliverable.symbol.upper() in note.upper()
    checks.append(CheckResult(
        name="note_mentions_symbol", critical=True, passed=mentions,
        detail="ok" if mentions else "missing",
    ))


def _report(checks: list[CheckResult], metrics: dict[str, float]) -> QualityReport:
    passed = all(c.passed for c in checks)
    score = sum(c.passed for c in checks) / len(checks) if checks else 0.0
    evidence = {"checks": [c.model_dump() for c in checks], "metrics": metrics}
    return QualityReport(passed=passed, score=round(score, 3), checks=checks, metrics=metrics,
                         evidence_hash=canonical_hash(evidence))
