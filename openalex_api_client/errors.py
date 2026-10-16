"""Exceptions raised by the client. Messages never contain the API key."""


class OpenAlexError(Exception):
    """Base class for every error raised by the client."""


class HTTPError(OpenAlexError):
    """A non-retryable HTTP error, or a retryable one after the last retry."""

    def __init__(self, status, url, body_excerpt="", validation=None):
        self.status = status
        self.url = url  # api_key already removed
        self.body_excerpt = body_excerpt
        self.validation = validation
        detail = validation if validation else body_excerpt
        super().__init__(f"HTTP {status} for {url}: {detail}")


class BudgetExhausted(OpenAlexError):
    """HTTP 429 with X-RateLimit-Remaining: 0. Retrying before the reset is pointless."""

    def __init__(self, reset_seconds=None):
        self.reset_seconds = reset_seconds
        when = f"resets in {reset_seconds} s" if reset_seconds is not None else "reset time unknown"
        super().__init__(f"OpenAlex budget exhausted ({when})")


class PaginationError(OpenAlexError):
    """Cursor loop, result count changing during iteration (strict mode), or a checkpoint mismatch."""
