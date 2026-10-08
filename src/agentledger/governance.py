"""Capability switches. Dangerous actions stay off unless an env flag or the operator token allows them.

The gate is created once per process. Pause/resume flips `paused` at runtime; the other switches
come from the environment and do not change until restart.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agentledger.economy import DomainError


@dataclass(frozen=True)
class Capabilities:
    open_funding: bool
    llm_rulings: bool
    max_order_minor: int
    market_paused_default: bool

    @classmethod
    def from_env(cls) -> Capabilities:
        return cls(
            open_funding=os.getenv("AL_CAP_OPEN_FUNDING", "0") == "1",
            llm_rulings=os.getenv("AL_CAP_LLM_RULINGS", "1") != "0",
            max_order_minor=int(os.getenv("AL_CAP_MAX_ORDER_MINOR", "500")),
            market_paused_default=os.getenv("AL_CAP_MARKET_PAUSED", "0") == "1",
        )


class CapabilityGate:
    def __init__(self, caps: Capabilities) -> None:
        self.caps = caps
        self.paused = caps.market_paused_default

    def require_funding(self, amount_minor: int, token_ok: bool) -> None:
        """Public signup may not mint money unless open funding is on or the operator token matches."""
        if amount_minor > 0 and not (self.caps.open_funding or token_ok):
            raise DomainError("open funding is disabled", 403)

    def require_hold(self, amount_minor: int) -> None:
        if self.paused:
            raise DomainError("market is paused", 503)
        if amount_minor > self.caps.max_order_minor:
            raise DomainError("amount exceeds the global order cap", 403)

    def snapshot(self) -> dict[str, bool | int]:
        return {
            "open_funding": self.caps.open_funding,
            "llm_rulings": self.caps.llm_rulings,
            "market_paused": self.paused,
            "max_order_minor": self.caps.max_order_minor,
        }
