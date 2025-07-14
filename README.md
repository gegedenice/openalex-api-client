# OpenAlex API Client

A Python client for interacting with the OpenAlex API, providing easy access to scholarly metadata and offering data digestion capabilities.

## Features

- Simple and intuitive interface for OpenAlex API
- Automatic pagination handling
- Data digestion for works (simplified, flattened format)
- Optional inclusion of work abstracts in digested output
- Support for all OpenAlex endpoints (works, authors, institutions, etc.)
- Comprehensive filtering and sorting options
- Error handling and logging

## Installation

```bash
pip install git+https://github.com/gegedenice/openalex-api-client
```

## Quick Start

```python
from openalex_api_client import OpenAlexClient

# Initialize the client
client = OpenAlexClient(email="your.email@example.com")

# Get a single work
work = client.get_work("W2741809807")

# Get a digested version of a work (simplified format)
digested_work = client.get_work("W2741809807", digest=True)

# Get digested work with abstract included
digested_with_abstract = client.get_work("W2741809807", digest=True, abstract=True)

# List works with filters
works = client.list_works(
    filter="publication_year:2020,is_oa:true",
    per_page=25
)

# List digested works with abstract
works = client.list_works(
    digest=True,
    abstract=True,
    filter="publication_year:2020",
    per_page=25
)

# Get all works matching criteria (with pagination)
all_works = client.list_all_works(
    digest=True,
    filter="publication_year:2020",
    per_page=100
)
```

## API Reference

### Client Initialization

```python
client = OpenAlexClient(
    email="your.email@example.com",  # Optional, but recommended
    default_per_page=10              # Optional, defaults to 10
)
```

### Main Methods

#### Get Single Resource
```python
# Get a single work
work = client.get_work(work_id, digest=False)

# Get digested work with optional abstract
digested_work = client.get_work(work_id, digest=True, abstract=True)

# Get a single author
author = client.get_author(author_id)

# Get a single institution
institution = client.get_institution(institution_id)
```

#### List Resources (Single Page)
```python
# List works
works = client.list_works(
    filter="publication_year:2020",
    sort="cited_by_count:desc",
    per_page=25,
    digest=True,
    abstract=True
)

# List authors
authors = client.list_authors(
    filter="works_count:>100",
    per_page=25
)
```

#### List All Resources (With Pagination)
```python
# Get all works
all_works = client.list_all_works(
    filter="publication_year:2020",
    per_page=100,
    digest=True,
    abstract=True
)

# Get all institutions
all_institutions = client.list_all_institutions(
    filter="country_code:FR",
    per_page=100
)
```

#### Get Total Count
```python
# Get count of works
total_works = client.get_total_count(
    client.WORKS,
    filter="publication_year:2020"
)
```

### Filter Examples

```python
# Basic filters
"publication_year:2020"
"is_oa:true"
"type:journal-article"

# Multiple conditions
"publication_year:2020,is_oa:true"

# Comparison operators
"cited_by_count:>100"
"cited_by_count:>=100"
"cited_by_count:<100"

# Nested properties
"institutions.country_code:FR"
"authors.institutions.country_code:US"

# Complex filters
"publication_year:2020,is_oa:true,type:journal-article,institutions.country_code:FR"
```

### Data Digestion

When using `digest=True`, works are transformed into a simplified format with:

- Flattened structure
- Deduplicated values
- Consistent field names
- Merged arrays
- Standardized date formats
- Optional abstract field when abstract=True

Example of digested work:
```python
{
    "id": "W1234567890",
    "doi": "10.1234/example",
    "title": "Example Title",
    "publication_year": 2020,
    "cited_by_count": 100,
    "open_access_is_oa": true,
    "open_access_oa_status": "gold",
    "countries_codes": "FR|US|DE",
    "authorships_display_name": "Author 1|Author 2|Author 3",
	"abstract": "This paper presents...",  # Only if abstract=True
    # ... other fields
}
```

### Data Processing Notes

- **Display Names Limitation**: To prevent massive data loads and improve performance, the system limits display names (authors, institutions, topics, etc.) to the first 10 entries per category. This applies to:
  - Author names
  - Institution names
  - Topics
  - Keywords
  - Sustainable Development Goals

## Error Handling

The client includes comprehensive error handling:

```python
from openalex_api_client import OpenAlexClientError

try:
    works = client.list_works(filter="invalid:filter")
except OpenAlexClientError as e:
    print(f"Error: {e}")
```

## Logging

The client uses Python's logging module. Configure logging as needed:

```python
import logging
logging.basicConfig(level=logging.INFO)
```
