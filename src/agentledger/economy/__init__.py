"""Deterministic economy core (laptop A): ledger, escrow, disputes, registry.

Rule: LLMs may propose; only code in this package moves money or changes order state.
"""


class DomainError(Exception):
    """Business-rule violation. `status` maps to the HTTP status the API returns."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status
