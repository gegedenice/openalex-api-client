# -*- coding: utf-8 -*-
import requests
import json
from collections import defaultdict
import re
import json
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class OpenAlexClientError(Exception):
    """Custom exception class for OpenAlexClient errors."""
    pass

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
                logging.warning(f"Error parsing {field}: {e}")

        # IDs
        try:
            ids = work_data.get('ids', {})
            parsed_data['pmid'] = ids.get('pmid', '')
            parsed_data['mag'] = ids.get('mag', '')
        except Exception as e:
            logging.warning(f"Error parsing IDs: {e}")

        # APC paid
        try:
            apc_paid_value = work_data.get('apc_paid')
            if isinstance(apc_paid_value, dict):
                parsed_data['apc_paid'] = apc_paid_value.get('value_usd')
            else:
                parsed_data['apc_paid'] = apc_paid_value
        except Exception as e:
            logging.warning(f"Error parsing apc_paid: {e}")

        # Counts
        count_fields = ['referenced_works_count', 'cited_by_count', 'countries_distinct_count',
                       'institutions_distinct_count', 'locations_count', 'fwci']
        for field in count_fields:
            try:
                parsed_data[field] = work_data.get(field)
            except Exception as e:
                logging.warning(f"Error parsing {field}: {e}")

        # Primary location
        try:
            primary_location = work_data.get('primary_location', {}).get('source', {})
            parsed_data['primary_location_display_name'] = primary_location.get('display_name')
            parsed_data['primary_location_host_organization_name'] = primary_location.get('host_organization_name')
        except Exception as e:
            logging.warning(f"Error parsing primary_location: {e}")

        # Publication date
        try:
            publication_date = work_data.get('publication_date')
            if publication_date:
                parsed_data['publication_date'] = OpenAlexParser.convert_publication_date(publication_date)
        except Exception as e:
            logging.warning(f"Error parsing publication_date: {e}")

        # Percentiles
        try:
            percentiles = work_data.get('citation_normalized_percentile', {})
            for key, value in percentiles.items():
                parsed_data[f"percentiles_{key}"] = value
        except Exception as e:
            logging.warning(f"Error parsing citation_normalized_percentile: {e}")

        # Open access
        try:
            open_access = work_data.get('open_access', {})
            parsed_data['open_access_is_oa'] = open_access.get('is_oa')
            parsed_data['open_access_oa_status'] = open_access.get('oa_status')
        except Exception as e:
            logging.warning(f"Error parsing open_access: {e}")

        # Grants
        try:
            grants = work_data.get('grants', [])
            for i, grant in enumerate(grants):
                parsed_data[f"grants[{i}]_funder_display_name"] = grant.get("funder_display_name")
        except Exception as e:
            logging.warning(f"Error parsing grants: {e}")

        # Country codes
        try:
            parsed_data["countries_codes"] = OpenAlexParser.extract_unique_country_codes(work_data.get("authorships", []))
        except Exception as e:
            logging.warning(f"Error parsing countries_codes: {e}")

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
            logging.warning(f"Error parsing display_names: {e}")

        # Abstract
        if include_abstract:
            try:
                parsed_data['abstract'] = OpenAlexParser.extract_abstract(work_data.get('abstract_inverted_index'))
            except Exception as e:
                logging.warning(f"Error parsing abstract: {e}")
        return OpenAlexParser.merge_and_deduplicate(parsed_data)



class OpenAlexClient:
    """
    A Python client for interacting with the OpenAlex API.
    Handles authentication, basic requests, and pagination for common endpoints.
    """

    # Endpoint constants
    WORKS = "works"
    INSTITUTIONS = "institutions"
    AUTHORS = "authors"
    TOPICS = "topics"
    FUNDERS = "funders"
    PUBLISHERS = "publishers"

    def __init__(self, email: str = None, default_per_page=10):
        """
        Initializes the OpenAlexClient.

        Args:
            email (str, optional): Email for API identification. Defaults to None.
            default_per_page (int): Default number of results per page. Defaults to 10.
        """
        self.base_url = "https://api.openalex.org"
        self.email = email
        self.default_per_page = default_per_page
        self.headers = {
            'Accept': 'application/json',
        }
        # Use a session for connection pooling and better Brotli handling
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        logging.info(f"OpenAlexClient initialized with email: {self.email}")

    def _build_params(self, **kwargs):
        """Helper to build request parameters, including API keys."""
        params = {"mailto": self.email}
        params.update({k: v for k, v in kwargs.items() if v is not None})
        return params

    def _request(self, method, url, params=None, **kwargs):
        """Makes an HTTP request to the OpenAlex API."""
        try:
            # Use session instead of requests.request for better connection handling
            response = self.session.request(method, url, params=params, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            error_message = f"API request failed ({method} {url}): {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_message += f"\nStatus Code: {e.response.status_code}"
                    error_message += f"\nResponse: {json.dumps(error_details, indent=2)}"
                except json.JSONDecodeError:
                    error_message += f"\nStatus Code: {e.response.status_code}"
                    error_message += f"\nResponse Text: {e.response.text[:500]}..."
            raise OpenAlexClientError(error_message) from e

    def get_resource(self, api_endpoint, resource_id, digest=False, abstract=False):
        """
        Fetches a single resource by its ID from a specified endpoint.

        Args:
            api_endpoint (str): The API endpoint name (e.g., "works", "authors").
            resource_id (str): The unique ID of the resource.
            digest (bool): If True, returns digested data using OpenAlexParser.
            abstract (bool): If True, returns the abstract inside digested data.

        Returns:
            dict: The JSON representation of the resource or digested data if digest=True.
        """
        url = f"{self.base_url}/{api_endpoint}/{resource_id}"
        params = self._build_params()
        logging.debug(f"Fetching single resource: GET {url}")
        response = self._request('GET', url, params=params)
        data = response.json()
        
        if digest and api_endpoint == self.WORKS:
            return OpenAlexParser.parse_work(data, include_abstract=abstract)
        return data

    def list_resources(self, api_endpoint, digest=False, abstract=False, **kwargs):
        """
        Fetches a single page of resources from an API endpoint.

        Args:
            api_endpoint (str): The API endpoint name (e.g., "works", "authors").
            digest (bool): If True, returns digested data using OpenAlexParser.
            abstract (bool): If True, returns the abstract inside digested data.
            **kwargs: Query parameters (page, per_page, sort_by, etc.).

        Returns:
            dict: A dictionary containing the results and metadata.
        """
        url = f"{self.base_url}/{api_endpoint}"
        if 'per_page' not in kwargs:
            kwargs['per_page'] = self.default_per_page

        params = self._build_params(**kwargs)
        logging.debug(f"Listing resources (single page): GET {url} with params: {params}")
        response = self._request('GET', url, params=params)
        data = response.json()
        
        if digest and api_endpoint == self.WORKS:
            #data['results'] = [OpenAlexParser.parse_work(work) for work in data.get('results', [])]
            data['results'] = [OpenAlexParser.parse_work(work, include_abstract=abstract) for work in data.get('results', [])]
        return data.get('results', [])

    def get_total_count(self, api_endpoint, **kwargs):
        """
        Gets the total count of resources matching the given filters.

        Args:
            api_endpoint (str): The API endpoint name (e.g., "works", "authors").
            **kwargs: Query parameters (filter, sort, select, etc.).

        Returns:
            int: The total count of matching resources.
        """
        url = f"{self.base_url}/{api_endpoint}"
        # Set per_page to 1 to minimize data transfer
        kwargs['per_page'] = 1
        params = self._build_params(**kwargs)
        
        try:
            response = self._request('GET', url, params=params)
            data = response.json()
            return data.get('meta', {}).get('count', 0)
        except OpenAlexClientError as e:
            logging.error(f"Error getting total count: {str(e)}")
            return 0

    def list_all_resources(self, api_endpoint, digest=False, abstract=False, per_page=None, **kwargs):
        """
        Fetches ALL resources from an endpoint, handling pagination.

        Args:
            api_endpoint (str): The API endpoint name (e.g., "works", "authors").
            digest (bool): If True, returns digested data using OpenAlexParser.
            abstract (bool): If True, returns the abstract inside digested data.
            per_page (int, optional): Results per page. Defaults to client's default_per_page.
            **kwargs: Additional query parameters (filter, sort, select).
                      'page' parameter is ignored as pagination is handled internally.

        Returns:
            list: A list containing JSON representations of ALL matching resources.
        """
        if per_page is None:
            per_page = self.default_per_page

        # Remove page from kwargs if present to avoid conflicts
        kwargs.pop('page', None)
        
        # Get total count using the dedicated method
        total_count = self.get_total_count(api_endpoint, **kwargs)
        if total_count == 0:
            logging.warning(f"No resources found for endpoint '{api_endpoint}' with given filters")
            return []
        
        total_pages = (total_count + per_page - 1) // per_page
        logging.info(f"Fetching {total_count} resources from {total_pages} pages for endpoint '{api_endpoint}'")

        all_records = []
        # Fetch all pages
        for page in range(1, total_pages + 1):
            try:
                response = self.list_resources(api_endpoint, digest=digest, abstract=abstract, page=page, per_page=per_page, **kwargs)
                if response:
                    all_records.extend(response)
                    logging.info(f"Fetched page {page}/{total_pages} - Total records so far: {len(all_records)}")
                else:
                    logging.warning(f"Empty response for page {page}")
                    break
            except OpenAlexClientError as e:
                logging.error(f"Error fetching page {page}: {str(e)}")
                break

        logging.info(f"Completed fetching {len(all_records)} resources from endpoint '{api_endpoint}'")
        return all_records

    # Convenience methods for common endpoints
    def get_work(self, work_id, digest=False, abstract=False,):
        """Fetches a single work by ID."""
        return self.get_resource(self.WORKS, work_id, digest=digest, abstract=abstract)

    def list_works(self, digest=False, abstract=False, **kwargs):
        """Fetches a single page of works."""
        return self.list_resources(self.WORKS, digest=digest, abstract=abstract, **kwargs)

    def list_all_works(self, digest=False, abstract=False,per_page=None, **kwargs):
        """Fetches ALL works, handling pagination."""
        return self.list_all_resources(self.WORKS, digest=digest, abstract=abstract, per_page=per_page, **kwargs)

    # -- Institutions --
    def get_institution(self, institution_id):
        """Fetches a single media resource by ID."""
        # Your read_media_file logic maps here
        return self.get_resource(self.INSTITUTIONS, institution_id)

    def list_institutions(self, **kwargs):
        """Fetches a single page of media resources."""
        # Your read_media_files logic maps here (for one page)
        return self.list_resources(self.INSTITUTIONS, **kwargs)

    def list_all_institutions(self, per_page=None, **kwargs):
        """Fetches ALL media resources, handling pagination."""
        # Your read_media_files logic maps here (for all pages)
        return self.list_all_resources(self.INSTITUTIONS, per_page=per_page, **kwargs)

    # -- Authors --
    def get_author(self, author_id):
        """Fetches a single item set (collection) by ID."""
        return self.get_resource(self.AUTHORS, author_id)

    def list_authors(self, **kwargs):
        """Fetches a single page of item sets (collections)."""
        return self.list_resources(self.AUTHORS, **kwargs)

    def list_all_authors(self, per_page=None, **kwargs):
        """Fetches ALL item sets (collections), handling pagination."""
        return self.list_all_resources(self.AUTHORS, per_page=per_page, **kwargs)

    # -- Topics --
    def get_topic(self, topic_id):
        """Fetches a single resource template by ID."""
        return self.get_resource(self.TOPICS, topic_id)

    def list_topics(self, **kwargs):
        """Fetches a single page of resource templates."""
        return self.list_resources(self.TOPICS, **kwargs)

    def list_all_topics(self, per_page=None, **kwargs):
        """Fetches ALL resource templates, handling pagination."""
        return self.list_all_resources(self.TOPICS, per_page=per_page, **kwargs)

    # -- Funders --
    def get_funder(self, funder_id):
        """Fetches a single site by ID."""
        return self.get_resource(self.FUNDERS, funder_id)

    def list_funders(self, **kwargs):
        """Fetches a single page of sites."""
        return self.list_resources(self.FUNDERS, **kwargs)

    def list_all_funders(self, per_page=None, **kwargs):
        """Fetches ALL sites, handling pagination."""
        return self.list_all_resources(self.FUNDERS, per_page=per_page, **kwargs)

    # -- Publishers --
    def get_publisher(self, publisher_id):
        """Fetches a single resource class by ID."""
        return self.get_resource(self.PUBLISHERS, publisher_id)

    def list_publishers(self, **kwargs):
        """Fetches a single page of resource classes."""
        return self.list_resources(self.PUBLISHERS, **kwargs)

    def list_all_publishers(self, per_page=None, **kwargs):
        """Fetches ALL resource classes, handling pagination."""
        return self.list_all_resources(self.PUBLISHERS, per_page=per_page, **kwargs)

