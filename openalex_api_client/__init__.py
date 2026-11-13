"""A small, generic client for the OpenAlex REST API."""

from .client import OpenAlex, Usage
from .derive import hydrate, reconstruct_abstract
from .errors import BudgetExhausted, HTTPError, OpenAlexError, PaginationError
from .legacy import OpenAlexClient, OpenAlexClientError
from .query import filter_to_string, parse_url, short_id
from .views import VIEWS, views

__version__ = "1.1.0"

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
    "VIEWS",
    "views",
    "hydrate",
    "reconstruct_abstract",
    "OpenAlexClient",
    "OpenAlexClientError",
]
