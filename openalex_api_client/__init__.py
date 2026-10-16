"""A small, generic client for the OpenAlex REST API."""

from .client import OpenAlex, Usage
from .errors import BudgetExhausted, HTTPError, OpenAlexError, PaginationError
from .legacy import OpenAlexClient, OpenAlexClientError
from .query import filter_to_string, parse_url, short_id

__version__ = "1.0.0"

__all__ = [
    "OpenAlex",
    "Usage",
    "OpenAlexError",
    "HTTPError",
    "BudgetExhausted",
    "PaginationError",
    "filter_to_string",
    "parse_url",
    "short_id",
    "OpenAlexClient",
    "OpenAlexClientError",
]
