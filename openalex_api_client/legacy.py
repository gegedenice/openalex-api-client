"""Deprecated v0 API (`OpenAlexClient`), kept for one version as a thin wrapper over `OpenAlex`."""

import re
import warnings
from collections import defaultdict
from datetime import datetime
import logging

from .client import OpenAlex
from .errors import OpenAlexError

logger = logging.getLogger(__name__)

# v0 name of the base exception.
OpenAlexClientError = OpenAlexError


class OpenAlexParser:
    """Parser class for OpenAlex JSON responses that provides digested data."""
    
    @staticmethod
    def merge_and_deduplicate(data):
        """Merges and deduplicates data with array indices."""
        merged_data = defaultdict(set)
        for key, value in data.items():
            if re.search(r'\[\d+\]', key):
                normalized_key = re.sub(r'\[\d+\]', '', key)
                merged_data[normalized_key].add(value)
            else:
                merged_data[key] = {value}
        return {k: '|'.join(sorted(v)) if len(v) > 1 else next(iter(v)) for k, v in merged_data.items()}

    @staticmethod
    def find_display_names(obj, path=""):
        """Recursively finds all display_name fields in the JSON object."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key
                if "display_name" in key:
                    yield new_path, value
                else:
                    yield from OpenAlexParser.find_display_names(value, new_path)
        elif isinstance(obj, list):
            for index, item in enumerate(obj):
                new_path = f"{path}[{index}]"
                yield from OpenAlexParser.find_display_names(item, new_path)

    @staticmethod
    def extract_unique_country_codes(authorships):
        """Extracts unique country codes from authorships."""
        country_codes = set()
        for author in authorships:
            country_codes.update(author.get('countries', []))
        return '|'.join(sorted(country_codes))

    @staticmethod
    def convert_publication_date(publication_date_str):
        """Converts a publication date string to ISO format."""
        try:
            dt = datetime.strptime(publication_date_str, '%Y-%m-%d')
            return dt.isoformat() + 'Z'
        except ValueError:
            return None

    @staticmethod
    def extract_abstract(abstract_inverted_index):
        """Convert an abstract_inverted_index into a readable text format."""
        if not abstract_inverted_index:
            return "No abstract available"
        abstract_length = max(max(pos) for pos in abstract_inverted_index.values()) + 1
        abstract_words = [""] * abstract_length
        for word, positions in abstract_inverted_index.items():
            for pos in positions:
                abstract_words[pos] = word
        return " ".join(word for word in abstract_words if word)

    @staticmethod
    def parse_work(work_data, include_abstract=False):
        """Parses a work JSON object into a digested format."""
        parsed_data = {}
        
        # Basic fields
        basic_fields = ['id', 'doi', 'title', 'publication_year', 'language', 'type']
        for field in basic_fields:
            try:
                if field == 'doi':
                    parsed_data[field] = work_data.get(field, '')
                else:
                    parsed_data[field] = work_data.get(field)
            except Exception as e:
                logger.warning(f"Error parsing {field}: {e}")

        # IDs
        try:
            ids = work_data.get('ids', {})
            parsed_data['pmid'] = ids.get('pmid', '')
            parsed_data['mag'] = ids.get('mag', '')
        except Exception as e:
            logger.warning(f"Error parsing IDs: {e}")

        # APC paid
        try:
            apc_paid_value = work_data.get('apc_paid')
            if isinstance(apc_paid_value, dict):
                parsed_data['apc_paid'] = apc_paid_value.get('value_usd')
            else:
                parsed_data['apc_paid'] = apc_paid_value
        except Exception as e:
            logger.warning(f"Error parsing apc_paid: {e}")

        # Counts
        count_fields = ['referenced_works_count', 'cited_by_count', 'countries_distinct_count',
                       'institutions_distinct_count', 'locations_count', 'fwci']
        for field in count_fields:
            try:
                parsed_data[field] = work_data.get(field)
            except Exception as e:
                logger.warning(f"Error parsing {field}: {e}")

        # Primary location
        try:
            primary_location = work_data.get('primary_location', {}).get('source', {})
            parsed_data['primary_location_display_name'] = primary_location.get('display_name')
            parsed_data['primary_location_host_organization_name'] = primary_location.get('host_organization_name')
        except Exception as e:
            logger.warning(f"Error parsing primary_location: {e}")

        # Publication date
        try:
            publication_date = work_data.get('publication_date')
            if publication_date:
                parsed_data['publication_date'] = OpenAlexParser.convert_publication_date(publication_date)
        except Exception as e:
            logger.warning(f"Error parsing publication_date: {e}")

        # Percentiles
        try:
            percentiles = work_data.get('citation_normalized_percentile', {})
            for key, value in percentiles.items():
                parsed_data[f"percentiles_{key}"] = value
        except Exception as e:
            logger.warning(f"Error parsing citation_normalized_percentile: {e}")

        # Open access
        try:
            open_access = work_data.get('open_access', {})
            parsed_data['open_access_is_oa'] = open_access.get('is_oa')
            parsed_data['open_access_oa_status'] = open_access.get('oa_status')
        except Exception as e:
            logger.warning(f"Error parsing open_access: {e}")

        # Grants
        try:
            grants = work_data.get('grants', [])
            for i, grant in enumerate(grants):
                parsed_data[f"grants[{i}]_funder_display_name"] = grant.get("funder_display_name")
        except Exception as e:
            logger.warning(f"Error parsing grants: {e}")

        # Country codes
        try:
            parsed_data["countries_codes"] = OpenAlexParser.extract_unique_country_codes(work_data.get("authorships", []))
        except Exception as e:
            logger.warning(f"Error parsing countries_codes: {e}")

        # Display names
        try:
            display_names = {}
            for path, value in OpenAlexParser.find_display_names(work_data):
                if ("authorships" in path or "topics" in path or "keywords" in path or 
                    "sustainable_development_goals" in path) and "display_name" in path:
                    if path not in display_names:
                        display_names[path] = []
                    display_names[path].append(value)
            # After collecting all values, limit to first 10 if needed (preventing massive authorships for example)
            for path in display_names:
                if len(display_names[path]) > 10:
                    display_names[path] = display_names[path][:10]
                    
            for path, values in display_names.items():
                parsed_data[path.replace(".","_")] = "|".join(values)
        except Exception as e:
            logger.warning(f"Error parsing display_names: {e}")

        # Abstract
        if include_abstract:
            try:
                parsed_data['abstract'] = OpenAlexParser.extract_abstract(work_data.get('abstract_inverted_index'))
            except Exception as e:
                logger.warning(f"Error parsing abstract: {e}")
        return OpenAlexParser.merge_and_deduplicate(parsed_data)


def _deprecated(name):
    warnings.warn(
        f"OpenAlexClient.{name} is deprecated; use openalex_api_client.OpenAlex instead",
        DeprecationWarning,
        stacklevel=3,
    )


class OpenAlexClient:
    """Deprecated. Use `OpenAlex`. `digest=True` is only available here."""

    WORKS = "works"
    INSTITUTIONS = "institutions"
    AUTHORS = "authors"
    TOPICS = "topics"
    FUNDERS = "funders"
    PUBLISHERS = "publishers"

    def __init__(self, api_key=None, default_per_page=10, **kwargs):
        _deprecated("__init__")
        self.default_per_page = default_per_page
        self._oa = OpenAlex(api_key=api_key, **kwargs)

    def __repr__(self):
        return f"OpenAlexClient({self._oa!r})"

    def _digest(self, api_endpoint, records, digest, abstract):
        if digest and api_endpoint == self.WORKS:
            return [OpenAlexParser.parse_work(r, include_abstract=abstract) for r in records]
        return records

    def get_resource(self, api_endpoint, resource_id, digest=False, abstract=False):
        _deprecated("get_resource")
        data = self._oa.get(api_endpoint, resource_id)
        return self._digest(api_endpoint, [data], digest, abstract)[0]

    def list_resources(self, api_endpoint, digest=False, abstract=False, **kwargs):
        """One page of results (v0 behaviour)."""
        _deprecated("list_resources")
        kwargs.setdefault("per_page", self.default_per_page)
        if "filter" in kwargs:
            kwargs["filter"] = self._filter(kwargs["filter"])
        data = self._oa._request("GET", f"/{api_endpoint}", kwargs)
        return self._digest(api_endpoint, data.get("results", []), digest, abstract)

    def get_total_count(self, api_endpoint, **kwargs):
        _deprecated("get_total_count")
        kwargs.pop("per_page", None)
        return self._oa.count(api_endpoint, **kwargs)

    def list_all_resources(self, api_endpoint, digest=False, abstract=False, per_page=None, **kwargs):
        """All results, now with cursor paging (no 10,000 limit)."""
        _deprecated("list_all_resources")
        kwargs.pop("page", None)
        records = self._oa.list(api_endpoint, per_page=min(per_page or 100, 100), **kwargs)
        return self._digest(api_endpoint, records, digest, abstract)

    @staticmethod
    def _filter(value):
        from .query import filter_to_string

        return filter_to_string(value)

    def get_work(self, work_id, digest=False, abstract=False):
        return self.get_resource(self.WORKS, work_id, digest=digest, abstract=abstract)

    def list_works(self, digest=False, abstract=False, **kwargs):
        return self.list_resources(self.WORKS, digest=digest, abstract=abstract, **kwargs)

    def list_all_works(self, digest=False, abstract=False, per_page=None, **kwargs):
        return self.list_all_resources(self.WORKS, digest=digest, abstract=abstract, per_page=per_page, **kwargs)

    def get_institution(self, institution_id):
        return self.get_resource(self.INSTITUTIONS, institution_id)

    def list_institutions(self, **kwargs):
        return self.list_resources(self.INSTITUTIONS, **kwargs)

    def list_all_institutions(self, per_page=None, **kwargs):
        return self.list_all_resources(self.INSTITUTIONS, per_page=per_page, **kwargs)

    def get_author(self, author_id):
        return self.get_resource(self.AUTHORS, author_id)

    def list_authors(self, **kwargs):
        return self.list_resources(self.AUTHORS, **kwargs)

    def list_all_authors(self, per_page=None, **kwargs):
        return self.list_all_resources(self.AUTHORS, per_page=per_page, **kwargs)

    def get_topic(self, topic_id):
        return self.get_resource(self.TOPICS, topic_id)

    def list_topics(self, **kwargs):
        return self.list_resources(self.TOPICS, **kwargs)

    def list_all_topics(self, per_page=None, **kwargs):
        return self.list_all_resources(self.TOPICS, per_page=per_page, **kwargs)

    def get_funder(self, funder_id):
        return self.get_resource(self.FUNDERS, funder_id)

    def list_funders(self, **kwargs):
        return self.list_resources(self.FUNDERS, **kwargs)

    def list_all_funders(self, per_page=None, **kwargs):
        return self.list_all_resources(self.FUNDERS, per_page=per_page, **kwargs)

    def get_publisher(self, publisher_id):
        return self.get_resource(self.PUBLISHERS, publisher_id)

    def list_publishers(self, **kwargs):
        return self.list_resources(self.PUBLISHERS, **kwargs)

    def list_all_publishers(self, per_page=None, **kwargs):
        return self.list_all_resources(self.PUBLISHERS, per_page=per_page, **kwargs)
