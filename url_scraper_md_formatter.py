"""
URL Scraper with AI Processing and Swagger/OpenAPI Support
A complete Python script that:
1. Provides a customtkinter UI for entering URLs
2. Uses crawl4ai for deep crawling of documentation
3. Extracts content via r.jina.ai in markdown format
4. Detects and processes Swagger/OpenAPI documentation with enhanced extraction
5. Processes content through AWS Bedrock LLM
6. Creates consistent knowledge base documentation
"""

import asyncio
import customtkinter as ctk
from tkinter import scrolledtext, messagebox
import json
import boto3
from botocore.config import Config
from datetime import datetime
import os
import re
from urllib.parse import urljoin, urlparse
import aiohttp
import requests
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.deep_crawling.filters import FilterChain, URLPatternFilter, DomainFilter
from typing import List, Dict, Optional, Tuple, Any
import logging
from dotenv import load_dotenv
import time
from asyncio import Semaphore
from dataclasses import dataclass, field
from enum import Enum

# Load environment variables from .env file, overriding existing ones
load_dotenv(override=True)

# Set up logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class SwaggerEnhancedScraper:
    """
    Enhanced scraper module specifically designed to handle Swagger/OpenAPI documentation pages.
    Integrated into the existing scraping script for better API documentation extraction.
    """
    
    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self.session = session
        self.sync_session = requests.Session()
        self.sync_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    async def detect_swagger_page(self, url: str, html_content: str = None) -> Dict[str, Any]:
        """
        Detect if a page is Swagger-based and return detection details.
        
        Returns:
            dict: {
                'is_swagger': bool,
                'confidence': float (0-1),
                'indicators': list,
                'spec_urls': list,
                'extraction_method': str
            }
        """
        # Strip URL fragment for processing (e.g., #/publications/get_public_rsids2pmids)
        clean_url = url.split('#')[0] if '#' in url else url
        
        if html_content is None:
            try:
                if self.session:
                    async with self.session.get(clean_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        html_content = await response.text()
                else:
                    # Fallback to sync session
                    response = self.sync_session.get(clean_url, timeout=10)
                    html_content = response.text
            except Exception as e:
                return {'is_swagger': False, 'error': str(e)}
        
        soup = BeautifulSoup(html_content, 'html.parser')
        content_lower = html_content.lower()
        
        indicators = []
        spec_urls = []
        confidence = 0.0
        
        # Detection checks with confidence weights
        checks = [
            # High confidence indicators
            ('swagger-ui div/id', lambda: soup.find('div', {'id': 'swagger-ui'}), 0.9),
            ('swagger-ui class', lambda: soup.find(class_='swagger-ui'), 0.9),
            ('swagger.json link', lambda: soup.find('a', href=re.compile(r'swagger\.json')), 0.95),
            ('openapi.json link', lambda: soup.find('a', href=re.compile(r'openapi\.json')), 0.95),
            
            # Medium confidence indicators
            ('swagger in title', lambda: 'swagger' in soup.title.get_text().lower() if soup.title else False, 0.7),
            ('opblock class', lambda: soup.find(class_=re.compile(r'opblock')), 0.8),
            ('swagger-ui bundle', lambda: 'swagger-ui-bundle' in content_lower, 0.8),
            ('try it out button', lambda: soup.find(string=re.compile(r'try.*it.*out', re.I)), 0.6),
            
            # Lower confidence indicators
            ('swagger text', lambda: 'swagger ui' in content_lower, 0.5),
            ('openapi text', lambda: 'openapi' in content_lower, 0.4),
            ('api documentation', lambda: 'api documentation' in content_lower, 0.3),
            
            # API-specific patterns that suggest swagger might be available
            ('api.html path', lambda: clean_url.endswith('/api.html'), 0.6),
            ('api docs path', lambda: '/api' in clean_url.lower() and ('doc' in clean_url.lower() or 'api.html' in clean_url.lower()), 0.5),
            ('rest api indicators', lambda: any(term in content_lower for term in ['rest api', 'api endpoint', 'api reference']), 0.4),
            ('http methods', lambda: len(re.findall(r'\b(GET|POST|PUT|DELETE|PATCH)\b', html_content)) >= 3, 0.5),
            ('json response', lambda: 'application/json' in content_lower or '"application/json"' in content_lower, 0.3),
        ]
        
        for name, check_func, weight in checks:
            try:
                if check_func():
                    indicators.append(name)
                    confidence += weight
            except:
                continue
        
        # Find potential spec URLs
        spec_patterns = [
            r'["\']([^"\']*swagger\.json[^"\']*)["\']',
            r'["\']([^"\']*openapi\.json[^"\']*)["\']',
            r'["\']([^"\']*api-docs[^"\']*)["\']',
        ]
        
        for pattern in spec_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for match in matches:
                full_url = urljoin(url, match)
                if full_url not in spec_urls:
                    spec_urls.append(full_url)
        
        # Common spec URL patterns to try
        base_patterns = [
            '/swagger.json',
            '/openapi.json',
            '/api-docs',
            '/v1/swagger.json',
            '/v2/api-docs',
            '/swagger/v1/swagger.json',
        ]
        
        parsed_url = urlparse(clean_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # Add base domain patterns
        for pattern in base_patterns:
            potential_url = base_url + pattern
            if potential_url not in spec_urls:
                spec_urls.append(potential_url)
        
        # Smart path-based patterns - try replacing common API doc paths with swagger.json
        if parsed_url.path:
            path = parsed_url.path
            
            # Pattern 1: Replace /api.html with /swagger.json (NCBI LitVar case)
            if path.endswith('/api.html'):
                swagger_path = path.replace('/api.html', '/swagger.json')
                potential_url = f"{base_url}{swagger_path}"
                if potential_url not in spec_urls:
                    spec_urls.append(potential_url)
            
            # Pattern 2: Replace /docs with /swagger.json
            elif path.endswith('/docs') or path.endswith('/docs/'):
                swagger_path = path.rstrip('/').replace('/docs', '/swagger.json')
                potential_url = f"{base_url}{swagger_path}"
                if potential_url not in spec_urls:
                    spec_urls.append(potential_url)
            
            # Pattern 3: Add swagger.json to current directory
            elif '/' in path:
                # Get directory path and add swagger.json
                dir_path = '/'.join(path.split('/')[:-1]) if not path.endswith('/') else path.rstrip('/')
                potential_url = f"{base_url}{dir_path}/swagger.json"
                if potential_url not in spec_urls:
                    spec_urls.append(potential_url)
            
            # Pattern 4: Try openapi.json variants for the same patterns
            if path.endswith('/api.html'):
                openapi_path = path.replace('/api.html', '/openapi.json')
                potential_url = f"{base_url}{openapi_path}"
                if potential_url not in spec_urls:
                    spec_urls.append(potential_url)
        
        # Determine extraction method - be more aggressive about trying swagger specs
        # Even if HTML confidence is low, we should try spec URLs if we found any
        has_potential_specs = len(spec_urls) > 0
        is_swagger = confidence > 0.3 or has_potential_specs
        
        if is_swagger:
            if spec_urls:
                extraction_method = 'openapi_spec'
            else:
                extraction_method = 'html_scraping'
        else:
            extraction_method = 'standard_scraping'
            
        return {
            'is_swagger': is_swagger,
            'confidence': min(confidence, 1.0),
            'indicators': indicators,
            'spec_urls': spec_urls,
            'extraction_method': extraction_method
        }
    
    async def extract_openapi_spec(self, spec_urls: List[str]) -> Optional[Dict]:
        """
        Try to fetch and parse OpenAPI specification from potential URLs.
        """
        for spec_url in spec_urls:
            try:
                if self.session:
                    async with self.session.get(spec_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            # Get text content first to handle JSON with comments
                            text_content = await response.text()
                            spec_data = self._parse_json_with_comments(text_content)
                            
                            # Validate it's a valid OpenAPI spec
                            if spec_data and any(key in spec_data for key in ['swagger', 'openapi', 'paths']):
                                return {
                                    'spec': spec_data,
                                    'source_url': spec_url,
                                    'success': True
                                }
                else:
                    # Fallback to sync session
                    response = self.sync_session.get(spec_url, timeout=10)
                    if response.status_code == 200:
                        text_content = response.text
                        spec_data = self._parse_json_with_comments(text_content)
                        
                        # Validate it's a valid OpenAPI spec
                        if spec_data and any(key in spec_data for key in ['swagger', 'openapi', 'paths']):
                            return {
                                'spec': spec_data,
                                'source_url': spec_url,
                                'success': True
                            }
            except Exception as e:
                logger.debug(f"Failed to fetch spec from {spec_url}: {e}")
                continue
        
        return None
    
    def _parse_json_with_comments(self, text_content: str) -> Optional[Dict]:
        """
        Parse JSON content that may contain comments (which are not valid JSON).
        """
        import json
        import re
        
        try:
            # First try standard JSON parsing
            return json.loads(text_content)
        except json.JSONDecodeError:
            try:
                # Remove single-line comments (// comment)
                cleaned_content = re.sub(r'//.*$', '', text_content, flags=re.MULTILINE)
                
                # Remove multi-line comments (/* comment */)
                cleaned_content = re.sub(r'/\*.*?\*/', '', cleaned_content, flags=re.DOTALL)
                
                # Try parsing the cleaned content
                return json.loads(cleaned_content)
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse JSON even after cleaning comments: {e}")
                return None
        except Exception as e:
            logger.debug(f"Unexpected error parsing JSON: {e}")
            return None
    
    def parse_openapi_spec(self, spec_data: Dict) -> Dict[str, Any]:
        """
        Parse OpenAPI specification and extract structured endpoint information.
        """
        endpoints = []
        
        paths = spec_data.get('paths', {})
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() in ['get', 'post', 'put', 'delete', 'patch', 'options', 'head']:
                    endpoint_info = {
                        'method': method.upper(),
                        'path': path,
                        'summary': operation.get('summary', ''),
                        'description': operation.get('description', ''),
                        'parameters': [],
                        'responses': {},
                        'examples': []
                    }
                    
                    # Extract parameters with enhanced example extraction
                    for param in operation.get('parameters', []):
                        param_info = {
                            'name': param.get('name'),
                            'in': param.get('in'),
                            'required': param.get('required', False),
                            'type': param.get('type', ''),
                            'description': param.get('description', ''),
                            'example': param.get('example')
                        }
                        endpoint_info['parameters'].append(param_info)
                    
                    # Extract request body examples
                    if 'requestBody' in operation:
                        request_body = operation['requestBody']
                        if 'content' in request_body:
                            for content_type, content_info in request_body['content'].items():
                                if 'example' in content_info:
                                    endpoint_info['examples'].append({
                                        'type': 'request_body',
                                        'content_type': content_type,
                                        'example': content_info['example']
                                    })
                                if 'examples' in content_info:
                                    for example_name, example_data in content_info['examples'].items():
                                        endpoint_info['examples'].append({
                                            'type': 'request_body',
                                            'name': example_name,
                                            'content_type': content_type,
                                            'example': example_data.get('value', example_data)
                                        })
                    
                    # Extract responses with enhanced example extraction
                    for status_code, response in operation.get('responses', {}).items():
                        response_info = {
                            'description': response.get('description', ''),
                            'schema': response.get('schema', {}),
                            'examples': {}
                        }
                        
                        # Extract response examples
                        if 'content' in response:
                            for content_type, content_info in response['content'].items():
                                if 'example' in content_info:
                                    response_info['examples'][content_type] = content_info['example']
                                    endpoint_info['examples'].append({
                                        'type': 'response',
                                        'status_code': status_code,
                                        'content_type': content_type,
                                        'example': content_info['example']
                                    })
                                if 'examples' in content_info:
                                    for example_name, example_data in content_info['examples'].items():
                                        example_value = example_data.get('value', example_data)
                                        response_info['examples'][f"{content_type}_{example_name}"] = example_value
                                        endpoint_info['examples'].append({
                                            'type': 'response',
                                            'name': example_name,
                                            'status_code': status_code,
                                            'content_type': content_type,
                                            'example': example_value
                                        })
                        
                        # Legacy examples format
                        if 'examples' in response:
                            response_info['examples'].update(response['examples'])
                            for example_name, example_value in response['examples'].items():
                                endpoint_info['examples'].append({
                                    'type': 'response',
                                    'name': example_name,
                                    'status_code': status_code,
                                    'example': example_value
                                })
                        
                        endpoint_info['responses'][status_code] = response_info
                    
                    # Look for examples in various other places
                    if 'examples' in operation:
                        if isinstance(operation['examples'], list):
                            endpoint_info['examples'].extend(operation['examples'])
                        elif isinstance(operation['examples'], dict):
                            for example_name, example_value in operation['examples'].items():
                                endpoint_info['examples'].append({
                                    'type': 'operation',
                                    'name': example_name,
                                    'example': example_value
                                })
                    
                    endpoints.append(endpoint_info)
        
        return {
            'api_info': {
                'title': spec_data.get('info', {}).get('title', ''),
                'version': spec_data.get('info', {}).get('version', ''),
                'description': spec_data.get('info', {}).get('description', ''),
                'base_url': spec_data.get('host', '') + spec_data.get('basePath', ''),
            },
            'endpoints': endpoints,
            'total_endpoints': len(endpoints)
        }
    
    def extract_examples_from_html(self, html_content: str) -> Dict[str, List[str]]:
        """
        Extract real examples from HTML content (Swagger UI pages often have examples).
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        examples = {
            'parameter_examples': [],
            'response_examples': [],
            'code_examples': []
        }
        
        # Extract examples from text content
        example_patterns = [
            r'example:\s*([^\n\r]+)',
            r'"example":\s*"([^"]+)"',
            r'"example":\s*([^,\}\]]+)',
            r'Example:\s*([^\n\r]+)',
        ]
        
        text_content = soup.get_text()
        for pattern in example_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            for match in matches:
                clean_match = match.strip().strip('"\'')
                if clean_match and len(clean_match) > 2:
                    examples['parameter_examples'].append(clean_match)
        
        # Extract code examples from code blocks
        code_blocks = soup.find_all(['code', 'pre'])
        for block in code_blocks:
            code_text = block.get_text().strip()
            if code_text and len(code_text) > 10:
                # Filter out obvious non-examples
                if not any(skip in code_text.lower() for skip in ['function', 'class', 'import', 'def ']):
                    examples['code_examples'].append(code_text)
        
        # Extract JSON-like examples
        json_pattern = r'\{[^{}]*"[^"]*":\s*"[^"]*"[^{}]*\}'
        json_matches = re.findall(json_pattern, text_content)
        for match in json_matches:
            if len(match) < 200:  # Avoid very long matches
                examples['response_examples'].append(match)
        
        return examples
    
    async def scrape_swagger_html(self, url: str, html_content: str = None) -> Dict[str, Any]:
        """
        Fallback method to scrape Swagger UI from rendered HTML.
        """
        if html_content is None:
            if self.session:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    html_content = await response.text()
            else:
                response = self.sync_session.get(url, timeout=10)
                html_content = response.text
        
        soup = BeautifulSoup(html_content, 'html.parser')
        endpoints = []
        
        # Find API title and info
        api_title = ''
        title_elem = soup.find('h1') or soup.find(class_=re.compile(r'title|header'))
        if title_elem:
            api_title = title_elem.get_text().strip()
        
        # Extract endpoint blocks
        endpoint_blocks = soup.find_all(class_=re.compile(r'opblock|endpoint|operation'))
        
        for block in endpoint_blocks:
            try:
                # Extract method
                method_elem = block.find(class_=re.compile(r'method|opblock-summary-method'))
                method = method_elem.get_text().strip().upper() if method_elem else ''
                
                # Extract path
                path_elem = block.find(class_=re.compile(r'path|opblock-summary-path|endpoint-path'))
                path = path_elem.get_text().strip() if path_elem else ''
                
                # Extract description/summary
                desc_elem = block.find(class_=re.compile(r'description|summary|opblock-summary-description'))
                description = desc_elem.get_text().strip() if desc_elem else ''
                
                # Extract parameters
                parameters = []
                param_rows = block.find_all('tr') or block.find_all(class_=re.compile(r'parameter'))
                
                for row in param_rows:
                    name_elem = row.find(class_=re.compile(r'parameter.*name|param.*name'))
                    desc_elem = row.find(class_=re.compile(r'parameter.*description|param.*desc'))
                    required_elem = row.find(string=re.compile(r'required', re.I))
                    
                    if name_elem:
                        param_name = name_elem.get_text().strip()
                        param_desc = desc_elem.get_text().strip() if desc_elem else ''
                        param_required = bool(required_elem)
                        
                        parameters.append({
                            'name': param_name,
                            'description': param_desc,
                            'required': param_required
                        })
                
                # Extract examples
                examples = []
                example_elems = block.find_all(class_=re.compile(r'example|sample'))
                for ex in example_elems:
                    example_text = ex.get_text().strip()
                    if example_text and len(example_text) > 5:  # Filter out empty/short examples
                        examples.append(example_text)
                
                if method and path:
                    endpoints.append({
                        'method': method,
                        'path': path,
                        'description': description,
                        'parameters': parameters,
                        'examples': examples
                    })
            
            except Exception as e:
                logger.debug(f"Error parsing endpoint block: {e}")
                continue
        
        return {
            'api_info': {'title': api_title},
            'endpoints': endpoints,
            'total_endpoints': len(endpoints),
            'extraction_method': 'html_scraping'
        }
    
    async def enhanced_extract(self, url: str, html_content: str = None) -> Dict[str, Any]:
        """
        Main method to intelligently extract API information from any page.
        Use this as the primary interface in the existing scraping script.
        """
        try:
            # Step 1: Detect if this is a Swagger page
            detection = await self.detect_swagger_page(url, html_content)
            
            if not detection['is_swagger']:
                return {
                    'is_swagger': False,
                    'confidence': detection['confidence'],
                    'message': 'Not a Swagger page - use standard scraping',
                    'indicators': detection['indicators']
                }
            
            # Get HTML content for example extraction if not provided
            if html_content is None:
                clean_url = url.split('#')[0] if '#' in url else url
                try:
                    if self.session:
                        async with self.session.get(clean_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                            html_content = await response.text()
                    else:
                        response = self.sync_session.get(clean_url, timeout=10)
                        html_content = response.text
                except Exception as e:
                    logger.debug(f"Failed to fetch HTML content for examples: {e}")
                    html_content = ""
            
            # Extract examples from HTML content
            html_examples = self.extract_examples_from_html(html_content) if html_content else {}
            
            # Step 2: Try OpenAPI spec extraction first (best method)
            if detection['spec_urls']:
                spec_result = await self.extract_openapi_spec(detection['spec_urls'])
                if spec_result and spec_result['success']:
                    api_data = self.parse_openapi_spec(spec_result['spec'])
                    
                    # Enhance endpoints with HTML examples
                    self._enhance_endpoints_with_html_examples(api_data['endpoints'], html_examples)
                    
                    return {
                        'is_swagger': True,
                        'confidence': detection['confidence'],
                        'extraction_method': 'openapi_spec',
                        'api_data': api_data,
                        'spec_source': spec_result['source_url'],
                        'html_examples': html_examples,
                        'success': True
                    }
            
            # Step 3: Fallback to HTML scraping
            api_data = await self.scrape_swagger_html(url, html_content)
            
            # Enhance with HTML examples
            if 'endpoints' in api_data:
                self._enhance_endpoints_with_html_examples(api_data['endpoints'], html_examples)
            
            return {
                'is_swagger': True,
                'confidence': detection['confidence'],
                'extraction_method': 'html_scraping',
                'api_data': api_data,
                'html_examples': html_examples,
                'success': True,
                'note': 'Extracted from HTML - may be incomplete'
            }
            
        except Exception as e:
            return {
                'is_swagger': detection.get('is_swagger', False) if 'detection' in locals() else False,
                'success': False,
                'error': str(e),
                'message': 'Error during extraction - fall back to standard scraping'
            }
    
    def _enhance_endpoints_with_html_examples(self, endpoints: List[Dict], html_examples: Dict):
        """
        Enhance endpoint information with examples extracted from HTML.
        """
        if not html_examples:
            return
            
        for endpoint in endpoints:
            # Add parameter examples if not already present
            for param in endpoint.get('parameters', []):
                if not param.get('example') and html_examples.get('parameter_examples'):
                    # Try to match parameter name with examples
                    param_name = param.get('name', '').lower()
                    for example in html_examples['parameter_examples']:
                        if param_name in example.lower() or len(html_examples['parameter_examples']) == 1:
                            param['example'] = example
                            break
            
            # Add response examples if not already present
            if not endpoint.get('examples') and html_examples.get('response_examples'):
                endpoint['examples'] = endpoint.get('examples', [])
                for example in html_examples['response_examples'][:3]:  # Limit to 3 examples
                    endpoint['examples'].append({
                        'type': 'html_extracted',
                        'example': example
                    })
            
            # Add code examples
            if html_examples.get('code_examples'):
                endpoint['examples'] = endpoint.get('examples', [])
                for example in html_examples['code_examples'][:2]:  # Limit to 2 code examples
                    endpoint['examples'].append({
                        'type': 'code_example',
                        'example': example
                    })

class FailureReason(Enum):
    """Enumeration of different failure types for categorization"""
    CONNECTION_ERROR = "connection_error"
    TIMEOUT_ERROR = "timeout_error"
    HTTP_ERROR = "http_error"
    PROCESSING_ERROR = "processing_error"
    CONTENT_EXTRACTION_ERROR = "content_extraction_error"
    BEDROCK_ERROR = "bedrock_error"
    SWAGGER_DETECTION_ERROR = "swagger_detection_error"
    OPENAPI_SPEC_ERROR = "openapi_spec_error"
    API_ENDPOINT_EXTRACTION_ERROR = "api_endpoint_extraction_error"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class ProcessingStats:
    """Data class to track processing statistics for each website"""
    base_url: str
    total_urls_discovered: int = 0
    successful_urls: List[str] = field(default_factory=list)
    failed_urls: Dict[str, Dict] = field(default_factory=dict)  # url -> {reason, error_msg, timestamp}
    processing_start_time: float = field(default_factory=time.time)
    processing_end_time: float = 0.0
    # Swagger-specific metrics
    swagger_pages_detected: int = 0
    api_endpoints_extracted: int = 0
    swagger_extraction_methods: Dict[str, int] = field(default_factory=dict)  # method -> count
    swagger_urls: List[str] = field(default_factory=list)
    
    @property
    def success_count(self) -> int:
        return len(self.successful_urls)
    
    @property
    def failure_count(self) -> int:
        return len(self.failed_urls)
    
    @property
    def success_rate(self) -> float:
        if self.total_urls_discovered == 0:
            return 0.0
        return (self.success_count / self.total_urls_discovered) * 100
    
    @property
    def processing_duration(self) -> float:
        end_time = self.processing_end_time if self.processing_end_time > 0 else time.time()
        return end_time - self.processing_start_time
    
    def add_success(self, url: str):
        """Add a successful URL"""
        if url not in self.successful_urls:
            self.successful_urls.append(url)
    
    def add_failure(self, url: str, reason: FailureReason, error_msg: str):
        """Add a failed URL with categorized reason"""
        self.failed_urls[url] = {
            'reason': reason.value,
            'error_msg': error_msg,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_failures_by_reason(self) -> Dict[str, List[str]]:
        """Group failed URLs by failure reason"""
        failures_by_reason = {}
        for url, failure_info in self.failed_urls.items():
            reason = failure_info['reason']
            if reason not in failures_by_reason:
                failures_by_reason[reason] = []
            failures_by_reason[reason].append(url)
        return failures_by_reason
    
    def add_swagger_detection(self, url: str, extraction_method: str, endpoints_count: int = 0):
        """Add a Swagger page detection"""
        self.swagger_pages_detected += 1
        self.swagger_urls.append(url)
        self.api_endpoints_extracted += endpoints_count
        
        # Track extraction method
        if extraction_method not in self.swagger_extraction_methods:
            self.swagger_extraction_methods[extraction_method] = 0
        self.swagger_extraction_methods[extraction_method] += 1
    
    @property
    def swagger_detection_rate(self) -> float:
        """Calculate percentage of URLs that were detected as Swagger pages"""
        if self.total_urls_discovered == 0:
            return 0.0
        return (self.swagger_pages_detected / self.total_urls_discovered) * 100

# Customize the appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class URLScraperApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Documentation Scraper & AI Processor with Swagger Support")
        self.geometry("1200x800")
        
        # AWS Bedrock client
        self.bedrock_client = None
        self.setup_aws_client()
        
        # Swagger Enhanced Scraper
        self.swagger_scraper = SwaggerEnhancedScraper()
        
        # Storage for results
        self.processed_results = []
        self.current_urls = []
        
        # Processing statistics tracking
        self.processing_stats = {}  # base_url -> ProcessingStats
        self.overall_start_time = 0.0
        self.overall_end_time = 0.0
        
        # Rate limiting for APIs - optimized to prevent AWS connection pool exhaustion
        self.jina_semaphore = Semaphore(20)  # 20 concurrent Jina requests
        self.bedrock_semaphore = Semaphore(5)  # 5 concurrent Bedrock requests (reduced from 20 to stay within AWS connection pool limit of 10)
        self.jina_rate_limiter = []  # Track request times for rate limiting
        
        self.create_widgets()
        
    def setup_aws_client(self):
        """Initialize AWS Bedrock client with connection pool configuration"""
        try:
            # Get credentials from environment variables
            aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
            aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
            aws_region = os.getenv('AWS_DEFAULT_REGION', 'us-west-2')
            
            if not aws_access_key_id or not aws_secret_access_key:
                raise ValueError("AWS credentials not found in environment variables")
            
            logger.info(f"Using AWS credentials with Access Key ID: {aws_access_key_id[:8]}...")
            logger.info(f"Using AWS region: {aws_region}")
            
            # Configure connection pool settings to prevent exhaustion
            config = Config(
                region_name=aws_region,
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'
                },
                max_pool_connections=10,  # Match the default connection pool size
                connect_timeout=30,
                read_timeout=60
            )
            
            self.bedrock_client = boto3.client(
                service_name='bedrock-runtime',
                region_name=aws_region,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                config=config
            )
            
            logger.info("AWS Bedrock client initialized successfully with connection pool configuration")
            
        except Exception as e:
            logger.error(f"Failed to initialize AWS Bedrock client: {e}")
            messagebox.showerror("AWS Error",
                               f"Failed to initialize AWS Bedrock: {str(e)}\nPlease check your .env file and AWS credentials.")
    
    def create_widgets(self):
        """Create the UI elements"""
        # Main container
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Left panel - URL input
        left_frame = ctk.CTkFrame(main_frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Title
        title_label = ctk.CTkLabel(left_frame, text="URL Input", 
                                   font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(pady=(0, 10))
        
        # URL input area
        url_label = ctk.CTkLabel(left_frame, text="Enter URLs (one per line):")
        url_label.pack(anchor="w", padx=5)
        
        self.url_text = ctk.CTkTextbox(left_frame, height=200)
        self.url_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Crawl depth setting
        depth_frame = ctk.CTkFrame(left_frame)
        depth_frame.pack(fill="x", padx=5, pady=5)
        
        depth_label = ctk.CTkLabel(depth_frame, text="Crawl Depth:")
        depth_label.pack(side="left", padx=5)
        
        self.depth_slider = ctk.CTkSlider(depth_frame, from_=0, to=3, number_of_steps=3)
        self.depth_slider.set(1)
        self.depth_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        self.depth_value = ctk.CTkLabel(depth_frame, text="1")
        self.depth_value.pack(side="left", padx=5)
        
        self.depth_slider.configure(command=self.update_depth_label)
        
        # Buttons
        button_frame = ctk.CTkFrame(left_frame)
        button_frame.pack(fill="x", padx=5, pady=10)
        
        self.scrape_button = ctk.CTkButton(button_frame, text="Start Scraping", 
                                          command=self.start_scraping)
        self.scrape_button.pack(side="left", padx=5, fill="x", expand=True)
        
        self.stop_button = ctk.CTkButton(button_frame, text="Stop", 
                                        command=self.stop_scraping, state="disabled")
        self.stop_button.pack(side="left", padx=5, fill="x", expand=True)
        
        # Progress
        self.progress_label = ctk.CTkLabel(left_frame, text="Ready")
        self.progress_label.pack(pady=5)
        
        self.progress_bar = ctk.CTkProgressBar(left_frame)
        self.progress_bar.pack(fill="x", padx=5, pady=5)
        self.progress_bar.set(0)
        
        # Right panel - Results
        right_frame = ctk.CTkFrame(main_frame)
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))
        
        # Results title
        results_label = ctk.CTkLabel(right_frame, text="Processing Results", 
                                    font=ctk.CTkFont(size=20, weight="bold"))
        results_label.pack(pady=(0, 10))
        
        # Results text area
        self.results_text = ctk.CTkTextbox(right_frame, wrap="word")
        self.results_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Export button
        self.export_button = ctk.CTkButton(right_frame, text="Export Results", 
                                          command=self.export_results, state="disabled")
        self.export_button.pack(pady=10)
        
        # Status bar
        self.status_bar = ctk.CTkLabel(self, text="Ready to process URLs", anchor="w")
        self.status_bar.pack(side="bottom", fill="x", padx=10, pady=5)
        
    def update_depth_label(self, value):
        """Update the depth label when slider changes"""
        self.depth_value.configure(text=str(int(value)))
        
    def start_scraping(self):
        """Start the scraping process"""
        urls = self.url_text.get("1.0", "end-1c").strip().split('\n')
        urls = [url.strip() for url in urls if url.strip()]
        
        if not urls:
            messagebox.showwarning("No URLs", "Please enter at least one URL")
            return
        
        self.current_urls = urls
        self.scrape_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.export_button.configure(state="disabled")
        self.results_text.delete("1.0", "end")
        self.processed_results = []
        
        # Initialize processing statistics
        self.processing_stats = {}
        self.overall_start_time = time.time()
        self.overall_end_time = 0.0
        
        # Run the async scraping in a thread
        asyncio.run(self.scrape_and_process(urls))
        
    def stop_scraping(self):
        """Stop the scraping process"""
        self.scrape_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_label.configure(text="Stopped")
        self.status_bar.configure(text="Scraping stopped by user")
        
    async def scrape_and_process(self, urls: List[str]):
        """Main scraping and processing logic with concurrent processing and comprehensive logging"""
        total_base_urls = len(urls)
        all_crawled_urls = []
        
        # Initialize processing statistics for each base URL
        for base_url in urls:
            self.processing_stats[base_url] = ProcessingStats(base_url=base_url)
        
        # Step 1: Deep crawl all base URLs
        for idx, base_url in enumerate(urls):
            try:
                logger.info(f"Starting deep crawl of base URL {idx + 1}/{total_base_urls}: {base_url}")
                self.progress_label.configure(text=f"Crawling URL {idx + 1}/{total_base_urls}")
                self.progress_bar.set((idx + 1) / total_base_urls * 0.3)  # 30% for crawling
                self.status_bar.configure(text=f"Crawling: {base_url}")
                
                crawled_urls = await self.deep_crawl_url(base_url)
                logger.info(f"Deep crawl completed. Found {len(crawled_urls)} URLs")
                
                # Update statistics with discovered URLs
                self.processing_stats[base_url].total_urls_discovered = len(crawled_urls)
                
                for url in crawled_urls:
                    all_crawled_urls.append({
                        'url': url,
                        'base_url': base_url
                    })
                    
            except Exception as e:
                logger.error(f"Error crawling {base_url}: {e}")
                # If crawling fails, we still track the base URL itself
                self.processing_stats[base_url].total_urls_discovered = 1
                all_crawled_urls.append({
                    'url': base_url,
                    'base_url': base_url
                })
        
        logger.info(f"Total URLs to process: {len(all_crawled_urls)}")
        
        # Step 2: Process all URLs concurrently with rate limiting
        self.status_bar.configure(text=f"Processing {len(all_crawled_urls)} URLs concurrently...")
        
        # Create tasks for concurrent processing
        tasks = []
        for url_info in all_crawled_urls:
            task = self.process_single_url(url_info['url'], url_info['base_url'])
            tasks.append(task)
        
        # Process with progress tracking and detailed error logging
        completed = 0
        for i, task in enumerate(asyncio.as_completed(tasks)):
            try:
                result = await task
                url_info = all_crawled_urls[i] if i < len(all_crawled_urls) else None
                
                if result:
                    self.processed_results.append(result)
                    self.update_results_display(result)
                    # Track success
                    if url_info:
                        self.processing_stats[url_info['base_url']].add_success(url_info['url'])
                        logger.info(f"✓ Successfully processed: {url_info['url']}")
                else:
                    # Track failure - result was None
                    if url_info:
                        self.processing_stats[url_info['base_url']].add_failure(
                            url_info['url'],
                            FailureReason.PROCESSING_ERROR,
                            "Processing returned None result"
                        )
                        logger.warning(f"✗ Failed to process: {url_info['url']} (No result returned)")
                
                completed += 1
                progress = 0.3 + (completed / len(tasks)) * 0.7  # 30% crawling + 70% processing
                self.progress_bar.set(progress)
                self.progress_label.configure(text=f"Processed {completed}/{len(tasks)} URLs")
                
            except Exception as e:
                logger.error(f"Error in concurrent processing: {e}")
                # Track this as a processing error
                url_info = all_crawled_urls[i] if i < len(all_crawled_urls) else None
                if url_info:
                    self.processing_stats[url_info['base_url']].add_failure(
                        url_info['url'],
                        FailureReason.PROCESSING_ERROR,
                        str(e)
                    )
                completed += 1
        
        # Finalize processing statistics
        self.overall_end_time = time.time()
        for stats in self.processing_stats.values():
            stats.processing_end_time = self.overall_end_time
        
        # Step 3: Generate and display comprehensive processing summary
        await self.generate_processing_summary()
        
        # Step 4: Save results to RAG-optimized folder structure
        await self.save_rag_optimized_results()
        
        self.scrape_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.export_button.configure(state="normal")
        self.progress_label.configure(text="Completed")
        
        # Update status with comprehensive summary
        total_success = sum(stats.success_count for stats in self.processing_stats.values())
        total_failed = sum(stats.failure_count for stats in self.processing_stats.values())
        self.status_bar.configure(text=f"Completed: {total_success} successful, {total_failed} failed")
    
    async def process_single_url(self, url: str, base_url: str) -> Optional[Dict]:
        """Process a single URL with Swagger detection, rate limiting, retry logic, and detailed error tracking"""
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"Processing {url} (attempt {attempt + 1}/{max_retries + 1})")
                
                # Step 1: Extract content via Jina with rate limiting
                try:
                    markdown_content = await self.extract_content_via_jina_rate_limited(url)
                except asyncio.TimeoutError as e:
                    if attempt < max_retries:
                        logger.warning(f"Timeout extracting content from {url}, retrying...")
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.error(f"Timeout extracting content from {url} after {max_retries + 1} attempts")
                        self.processing_stats[base_url].add_failure(
                            url, FailureReason.TIMEOUT_ERROR, str(e)
                        )
                        return None
                except aiohttp.ClientError as e:
                    if attempt < max_retries:
                        logger.warning(f"Connection error extracting content from {url}, retrying...")
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.error(f"Connection error extracting content from {url} after {max_retries + 1} attempts")
                        self.processing_stats[base_url].add_failure(
                            url, FailureReason.CONNECTION_ERROR, str(e)
                        )
                        return None
                except aiohttp.ClientResponseError as e:
                    if attempt < max_retries:
                        logger.warning(f"HTTP error extracting content from {url}, retrying...")
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.error(f"HTTP error extracting content from {url} after {max_retries + 1} attempts")
                        self.processing_stats[base_url].add_failure(
                            url, FailureReason.HTTP_ERROR, str(e)
                        )
                        return None
                except Exception as e:
                    if attempt < max_retries:
                        logger.warning(f"Error extracting content from {url}, retrying...")
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.error(f"Error extracting content from {url} after {max_retries + 1} attempts")
                        self.processing_stats[base_url].add_failure(
                            url, FailureReason.CONTENT_EXTRACTION_ERROR, str(e)
                        )
                        return None
                
                if not markdown_content:
                    if attempt < max_retries:
                        logger.warning(f"Failed to extract content from {url}, retrying...")
                        await asyncio.sleep(2)  # Wait before retry
                        continue
                    else:
                        logger.error(f"Failed to extract content from {url} after {max_retries + 1} attempts")
                        # Track content extraction failure
                        self.processing_stats[base_url].add_failure(
                            url,
                            FailureReason.CONTENT_EXTRACTION_ERROR,
                            "Failed to extract content via Jina API after all retries"
                        )
                        return None
                
                # Step 2: Check for Swagger/OpenAPI content and enhance extraction if detected
                swagger_result = None
                try:
                    logger.info(f"Checking for Swagger/OpenAPI content at {url}")
                    swagger_result = await self.swagger_scraper.enhanced_extract(url, markdown_content)
                    
                    if swagger_result['is_swagger'] and swagger_result.get('success', False):
                        logger.info(f"✓ Swagger page detected: {url} (confidence: {swagger_result['confidence']:.2f}, method: {swagger_result['extraction_method']})")
                        
                        # Track Swagger detection in statistics
                        api_data = swagger_result.get('api_data', {})
                        endpoints_count = api_data.get('total_endpoints', 0)
                        self.processing_stats[base_url].add_swagger_detection(
                            url,
                            swagger_result['extraction_method'],
                            endpoints_count
                        )
                        
                        # Enhance markdown content with structured API information
                        if endpoints_count > 0:
                            logger.info(f"Found {endpoints_count} API endpoints, enhancing content")
                            enhanced_content = self.format_swagger_content_for_llm(swagger_result, markdown_content, url)
                            markdown_content = enhanced_content
                    else:
                        logger.debug(f"Not a Swagger page: {url} (confidence: {swagger_result.get('confidence', 0):.2f})")
                        
                except Exception as e:
                    logger.warning(f"Error during Swagger detection for {url}: {e}")
                    # Track Swagger detection failure but don't fail the entire processing
                    self.processing_stats[base_url].add_failure(
                        url,
                        FailureReason.SWAGGER_DETECTION_ERROR,
                        f"Swagger detection failed: {str(e)}"
                    )
                
                # Step 3: Process with Bedrock (now with potentially enhanced content)
                processed_content = await self.process_with_bedrock_rate_limited(markdown_content, url)
                
                if not processed_content:
                    if attempt < max_retries:
                        logger.warning(f"Failed to process content with Bedrock for {url}, retrying...")
                        await asyncio.sleep(2)  # Wait before retry
                        continue
                    else:
                        logger.error(f"Failed to process content with Bedrock for {url} after {max_retries + 1} attempts")
                        # Track Bedrock processing failure
                        self.processing_stats[base_url].add_failure(
                            url,
                            FailureReason.BEDROCK_ERROR,
                            "Failed to process content with Bedrock after all retries"
                        )
                        return None
                
                # Create result with Swagger information if detected
                result = {
                    'original_url': url,
                    'base_url': base_url,
                    'raw_markdown': markdown_content,
                    'processed_content': processed_content,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Add Swagger metadata if detected
                if swagger_result and swagger_result.get('is_swagger', False):
                    result['swagger_info'] = {
                        'is_swagger': True,
                        'confidence': swagger_result.get('confidence', 0),
                        'extraction_method': swagger_result.get('extraction_method', 'unknown'),
                        'endpoints_count': swagger_result.get('api_data', {}).get('total_endpoints', 0)
                    }
                
                logger.info(f"Successfully processed: {url}")
                return result
                
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"Error processing {url} (attempt {attempt + 1}): {e}, retrying...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"Error processing {url} after {max_retries + 1} attempts: {e}")
                    # Track general processing error
                    self.processing_stats[base_url].add_failure(
                        url,
                        FailureReason.PROCESSING_ERROR,
                        f"Processing error after {max_retries + 1} attempts: {str(e)}"
                    )
                    return None
        
        return None
    
    def format_swagger_content_for_llm(self, swagger_result: Dict, original_content: str, url: str) -> str:
        """
        Format Swagger API information for enhanced LLM processing.
        Combines original content with structured API endpoint information.
        """
        try:
            api_data = swagger_result.get('api_data', {})
            api_info = api_data.get('api_info', {})
            endpoints = api_data.get('endpoints', [])
            
            # Build enhanced content
            enhanced_sections = []
            
            # Add API overview section
            enhanced_sections.append("# API Documentation Overview")
            enhanced_sections.append(f"**Source URL:** {url}")
            enhanced_sections.append(f"**Detection Method:** {swagger_result.get('extraction_method', 'unknown')}")
            enhanced_sections.append(f"**Confidence:** {swagger_result.get('confidence', 0):.2f}")
            
            if api_info.get('title'):
                enhanced_sections.append(f"**API Title:** {api_info['title']}")
            if api_info.get('version'):
                enhanced_sections.append(f"**API Version:** {api_info['version']}")
            if api_info.get('description'):
                enhanced_sections.append(f"**Description:** {api_info['description']}")
            if api_info.get('base_url'):
                enhanced_sections.append(f"**Base URL:** {api_info['base_url']}")
            
            enhanced_sections.append(f"**Total Endpoints:** {len(endpoints)}")
            enhanced_sections.append("")
            
            # Add endpoints section
            if endpoints:
                enhanced_sections.append("# API Endpoints")
                enhanced_sections.append("")
                
                for i, endpoint in enumerate(endpoints, 1):
                    enhanced_sections.append(f"## Endpoint {i}: {endpoint.get('method', 'UNKNOWN')} {endpoint.get('path', 'N/A')}")
                    
                    if endpoint.get('summary'):
                        enhanced_sections.append(f"**Summary:** {endpoint['summary']}")
                    
                    if endpoint.get('description'):
                        enhanced_sections.append(f"**Description:** {endpoint['description']}")
                    
                    # Parameters
                    parameters = endpoint.get('parameters', [])
                    if parameters:
                        enhanced_sections.append("### Parameters")
                        for param in parameters:
                            param_line = f"- **{param.get('name', 'N/A')}** ({param.get('in', 'N/A')})"
                            if param.get('required'):
                                param_line += " *[Required]*"
                            if param.get('type'):
                                param_line += f" - Type: {param['type']}"
                            if param.get('description'):
                                param_line += f" - {param['description']}"
                            enhanced_sections.append(param_line)
                        enhanced_sections.append("")
                    
                    # Responses
                    responses = endpoint.get('responses', {})
                    if responses:
                        enhanced_sections.append("### Responses")
                        for status_code, response in responses.items():
                            response_line = f"- **{status_code}**: {response.get('description', 'No description')}"
                            enhanced_sections.append(response_line)
                        enhanced_sections.append("")
                    
                    # Examples
                    examples = endpoint.get('examples', [])
                    if examples:
                        enhanced_sections.append("### Examples")
                        for example in examples:
                            enhanced_sections.append(f"```\n{example}\n```")
                        enhanced_sections.append("")
                    
                    enhanced_sections.append("---")
                    enhanced_sections.append("")
            
            # Combine with original content
            enhanced_content = "\n".join(enhanced_sections)
            
            # Add separator and original content
            enhanced_content += "\n\n# Original Page Content\n\n"
            enhanced_content += original_content
            
            logger.info(f"Enhanced Swagger content: added {len(endpoints)} endpoints to content for {url}")
            return enhanced_content
            
        except Exception as e:
            logger.error(f"Error formatting Swagger content for {url}: {e}")
            # Return original content if formatting fails
            return original_content
    
    async def extract_content_via_jina_rate_limited(self, url: str) -> Optional[str]:
        """Extract content with rate limiting (20 requests per minute) and detailed error tracking"""
        async with self.jina_semaphore:
            # Rate limiting: ensure we don't exceed 20 requests per minute
            current_time = time.time()
            
            # Remove requests older than 60 seconds
            self.jina_rate_limiter = [t for t in self.jina_rate_limiter if current_time - t < 60]
            
            # If we have 20 requests in the last minute, wait
            if len(self.jina_rate_limiter) >= 20:
                sleep_time = 60 - (current_time - self.jina_rate_limiter[0])
                if sleep_time > 0:
                    logger.info(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
                    await asyncio.sleep(sleep_time)
                    # Clean up old requests again
                    current_time = time.time()
                    self.jina_rate_limiter = [t for t in self.jina_rate_limiter if current_time - t < 60]
            
            # Record this request
            self.jina_rate_limiter.append(current_time)
            
            # Make the actual request with error handling
            try:
                return await self.extract_content_via_jina(url)
            except asyncio.TimeoutError:
                # This will be handled by the calling method as TIMEOUT_ERROR
                raise
            except aiohttp.ClientError:
                # This will be handled by the calling method as CONNECTION_ERROR
                raise
            except aiohttp.ClientResponseError:
                # This will be handled by the calling method as HTTP_ERROR
                raise
            except Exception:
                # This will be handled by the calling method as CONTENT_EXTRACTION_ERROR
                raise
    
    async def process_with_bedrock_rate_limited(self, markdown_content: str, source_url: str) -> Optional[str]:
        """Process with Bedrock with concurrency limiting to prevent connection pool exhaustion"""
        async with self.bedrock_semaphore:
            # Log current semaphore usage for monitoring
            available_slots = self.bedrock_semaphore._value
            logger.debug(f"Bedrock semaphore: {5 - available_slots}/5 slots in use")
            return await self.process_with_bedrock(markdown_content, source_url)
    
    async def generate_processing_summary(self):
        """Generate and display comprehensive processing summary with Swagger metrics"""
        logger.info("=" * 80)
        logger.info("PROCESSING SUMMARY WITH SWAGGER DETECTION")
        logger.info("=" * 80)
        
        total_processing_time = self.overall_end_time - self.overall_start_time
        total_websites = len(self.processing_stats)
        total_discovered = sum(stats.total_urls_discovered for stats in self.processing_stats.values())
        total_successful = sum(stats.success_count for stats in self.processing_stats.values())
        total_failed = sum(stats.failure_count for stats in self.processing_stats.values())
        overall_success_rate = (total_successful / total_discovered * 100) if total_discovered > 0 else 0
        
        # Swagger-specific metrics
        total_swagger_pages = sum(stats.swagger_pages_detected for stats in self.processing_stats.values())
        total_api_endpoints = sum(stats.api_endpoints_extracted for stats in self.processing_stats.values())
        swagger_detection_rate = (total_swagger_pages / total_discovered * 100) if total_discovered > 0 else 0
        
        # Overall summary
        summary_lines = [
            f"Total Processing Time: {total_processing_time:.2f} seconds",
            f"Websites Processed: {total_websites}",
            f"Total URLs Discovered: {total_discovered}",
            f"Successfully Processed: {total_successful}",
            f"Failed to Process: {total_failed}",
            f"Overall Success Rate: {overall_success_rate:.1f}%",
            "",
            "SWAGGER/API DETECTION SUMMARY:",
            f"Swagger Pages Detected: {total_swagger_pages}",
            f"API Endpoints Extracted: {total_api_endpoints}",
            f"Swagger Detection Rate: {swagger_detection_rate:.1f}%",
            ""
        ]
        
        # Per-website breakdown
        summary_lines.append("PER-WEBSITE BREAKDOWN:")
        summary_lines.append("-" * 40)
        
        for base_url, stats in self.processing_stats.items():
            parsed_url = urlparse(base_url)
            domain = parsed_url.netloc
            
            summary_lines.extend([
                f"Website: {domain}",
                f"  Base URL: {base_url}",
                f"  URLs Discovered: {stats.total_urls_discovered}",
                f"  Successfully Processed: {stats.success_count}",
                f"  Failed: {stats.failure_count}",
                f"  Success Rate: {stats.success_rate:.1f}%",
                f"  Processing Time: {stats.processing_duration:.2f} seconds",
                f"  Swagger Pages: {stats.swagger_pages_detected}",
                f"  API Endpoints: {stats.api_endpoints_extracted}",
                f"  Swagger Detection Rate: {stats.swagger_detection_rate:.1f}%",
                ""
            ])
            
            # Swagger extraction methods breakdown
            if stats.swagger_pages_detected > 0:
                summary_lines.append("  Swagger Extraction Methods:")
                for method, count in stats.swagger_extraction_methods.items():
                    summary_lines.append(f"    {method.replace('_', ' ').title()}: {count} pages")
                summary_lines.append("")
            
            # Failure breakdown by reason
            if stats.failure_count > 0:
                failures_by_reason = stats.get_failures_by_reason()
                summary_lines.append("  Failure Breakdown:")
                for reason, failed_urls in failures_by_reason.items():
                    summary_lines.append(f"    {reason.replace('_', ' ').title()}: {len(failed_urls)} URLs")
                    for failed_url in failed_urls[:3]:  # Show first 3 failed URLs
                        summary_lines.append(f"      - {failed_url}")
                    if len(failed_urls) > 3:
                        summary_lines.append(f"      ... and {len(failed_urls) - 3} more")
                summary_lines.append("")
        
        # Log the summary
        for line in summary_lines:
            logger.info(line)
        
        # Display summary in UI
        summary_text = "\n".join(summary_lines)
        self.results_text.insert("end", f"\n{'='*80}\n")
        self.results_text.insert("end", "PROCESSING SUMMARY\n")
        self.results_text.insert("end", f"{'='*80}\n")
        self.results_text.insert("end", summary_text)
        self.results_text.see("end")
        
        return summary_text
    
    async def save_rag_optimized_results(self):
        """Save results in RAG-optimized folder structure with comprehensive processing logs"""
        if not self.processed_results:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Group results by base URL (website)
        results_by_website = {}
        for result in self.processed_results:
            base_url = result['base_url']
            if base_url not in results_by_website:
                results_by_website[base_url] = []
            results_by_website[base_url].append(result)
        
        logger.info(f"Organizing {len(self.processed_results)} documents across {len(results_by_website)} websites")
        
        # Generate comprehensive processing summary for logging
        processing_summary = await self.generate_processing_summary()
        
        # Create separate folder for each website
        for base_url, website_results in results_by_website.items():
            # Extract website name for folder and prefix
            parsed_url = urlparse(base_url)
            domain = parsed_url.netloc
            
            # Create clean website name for folder
            website_name = domain.replace('.', '_').replace('-', '_')
            
            # Create website prefix (capitalize first letter of each part)
            domain_parts = domain.split('.')
            if len(domain_parts) >= 2:
                # Use main domain name (e.g., 'crawl4ai' from 'docs.crawl4ai.com')
                main_domain = domain_parts[-2] if domain_parts[-2] != 'www' else domain_parts[-3]
                website_prefix = main_domain.capitalize()
            else:
                website_prefix = domain_parts[0].capitalize()
            
            # Create RAG-optimized directory structure for this website
            rag_dir = f"knowledge_base_{website_name}_{timestamp}"
            
            # Create subdirectories
            docs_dir = os.path.join(rag_dir, "documents")
            metadata_dir = os.path.join(rag_dir, "metadata")
            chunks_dir = os.path.join(rag_dir, "chunks")
            
            os.makedirs(docs_dir, exist_ok=True)
            os.makedirs(metadata_dir, exist_ok=True)
            os.makedirs(chunks_dir, exist_ok=True)
            
            logger.info(f"Saving {len(website_results)} documents for {domain} to: {rag_dir}")
            
            # Save each document for this website
            for idx, result in enumerate(website_results):
                # Create safe filename with website-derived prefix
                parsed_result_url = urlparse(result['original_url'])
                path_parts = [p for p in parsed_result_url.path.split('/') if p]
                if path_parts:
                    filename = '_'.join(path_parts)
                else:
                    filename = 'index'
                
                filename = re.sub(r'[^\w\-_]', '_', filename)
                if not filename:
                    filename = f"doc_{idx:03d}"
                
                # Add website-derived prefix
                filename = f"{website_prefix}-{filename}"
                
                # Save processed markdown
                doc_path = os.path.join(docs_dir, f"{filename}.md")
                with open(doc_path, 'w', encoding='utf-8') as f:
                    f.write(result['processed_content'])
                
                # Save metadata
                meta_path = os.path.join(metadata_dir, f"{filename}.json")
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'url': result['original_url'],
                        'base_url': result['base_url'],
                        'website_prefix': website_prefix,
                        'timestamp': result['timestamp'],
                        'content_length': len(result['processed_content']),
                        'raw_length': len(result['raw_markdown']),
                        'filename': f"{filename}.md"
                    }, f, indent=2)
            
            # Get processing statistics for this website
            website_stats = self.processing_stats.get(base_url, ProcessingStats(base_url=base_url))
            
            # Save collection metadata for this website with comprehensive processing stats
            collection_meta = os.path.join(rag_dir, "collection_metadata.json")
            with open(collection_meta, 'w', encoding='utf-8') as f:
                json.dump({
                    'collection_name': f"{website_name}_knowledge_base",
                    'website_domain': domain,
                    'website_prefix': website_prefix,
                    'base_url': base_url,
                    'created_at': timestamp,
                    'total_documents': len(website_results),
                    'processing_summary': {
                        'total_urls_discovered': website_stats.total_urls_discovered,
                        'total_urls_processed_successfully': len(website_results),
                        'total_urls_failed': website_stats.failure_count,
                        'success_rate_percent': website_stats.success_rate,
                        'processing_duration_seconds': website_stats.processing_duration,
                        'avg_content_length': sum(len(r['processed_content']) for r in website_results) // len(website_results) if website_results else 0,
                        'successful_urls': [r['original_url'] for r in website_results],
                        'failed_urls': website_stats.failed_urls,
                        'failures_by_reason': website_stats.get_failures_by_reason()
                    }
                }, f, indent=2)
            
            # Save detailed processing log for this website
            processing_log_path = os.path.join(rag_dir, "processing_log.md")
            with open(processing_log_path, 'w', encoding='utf-8') as f:
                f.write(f"""# Processing Log: {domain}

## Summary
- **Website**: {domain}
- **Base URL**: {base_url}
- **Processing Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **Total URLs Discovered**: {website_stats.total_urls_discovered}
- **Successfully Processed**: {website_stats.success_count}
- **Failed to Process**: {website_stats.failure_count}
- **Success Rate**: {website_stats.success_rate:.1f}%
- **Processing Duration**: {website_stats.processing_duration:.2f} seconds

## Successful URLs ({website_stats.success_count})
""")
                for url in website_stats.successful_urls:
                    f.write(f"- ✅ {url}\n")
                
                if website_stats.failure_count > 0:
                    f.write(f"\n## Failed URLs ({website_stats.failure_count})\n\n")
                    failures_by_reason = website_stats.get_failures_by_reason()
                    
                    for reason, failed_urls in failures_by_reason.items():
                        f.write(f"### {reason.replace('_', ' ').title()} ({len(failed_urls)} URLs)\n\n")
                        for url in failed_urls:
                            failure_info = website_stats.failed_urls[url]
                            f.write(f"- ❌ **{url}**\n")
                            f.write(f"  - Error: {failure_info['error_msg']}\n")
                            f.write(f"  - Time: {failure_info['timestamp']}\n\n")
                
                f.write(f"\n## Processing Details\n")
                f.write(f"- Start Time: {datetime.fromtimestamp(website_stats.processing_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"- End Time: {datetime.fromtimestamp(website_stats.processing_end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"- Duration: {website_stats.processing_duration:.2f} seconds\n")
            
            # Create README for this website's collection
            readme_path = os.path.join(rag_dir, "README.md")
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(f"""# Knowledge Base: {domain}

## Collection Information
- **Website**: {domain}
- **Base URL**: {base_url}
- **File Prefix**: {website_prefix}
- **Created**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **Total Documents**: {len(website_results)}

## Directory Structure
- `documents/` - Processed markdown files optimized for RAG
- `metadata/` - Individual document metadata
- `chunks/` - Reserved for future chunking strategies
- `collection_metadata.json` - Collection-level metadata

## Usage
This knowledge base is optimized for Retrieval-Augmented Generation (RAG) systems.
Each document in the `documents/` folder contains:
- YAML front matter with metadata
- Table of contents
- Hierarchical headings
- Chunk markers for optimal retrieval
- Self-contained sections

All files are prefixed with `{website_prefix}-` for easy identification and organization.

## Documents ({len(website_results)} total)
""")
                for result in website_results:
                    parsed_result_url = urlparse(result['original_url'])
                    page_title = parsed_result_url.path or '/'
                    f.write(f"- [{page_title}]({result['original_url']})\n")
            
            logger.info(f"RAG-optimized knowledge base for {domain} saved to: {rag_dir}")
        
        # Save overall processing summary log
        await self.save_overall_processing_log(timestamp)
        
        # Update status with summary
        total_websites = len(results_by_website)
        self.status_bar.configure(text=f"Knowledge bases created for {total_websites} website(s)")
        
    async def save_overall_processing_log(self, timestamp: str):
        """Save an overall processing summary log file"""
        log_filename = f"processing_summary_{timestamp}.md"
        
        total_processing_time = self.overall_end_time - self.overall_start_time
        total_websites = len(self.processing_stats)
        total_discovered = sum(stats.total_urls_discovered for stats in self.processing_stats.values())
        total_successful = sum(stats.success_count for stats in self.processing_stats.values())
        total_failed = sum(stats.failure_count for stats in self.processing_stats.values())
        overall_success_rate = (total_successful / total_discovered * 100) if total_discovered > 0 else 0
        
        with open(log_filename, 'w', encoding='utf-8') as f:
            f.write(f"""# Overall Processing Summary

**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Overall Statistics
- **Total Processing Time**: {total_processing_time:.2f} seconds
- **Websites Processed**: {total_websites}
- **Total URLs Discovered**: {total_discovered}
- **Successfully Processed**: {total_successful}
- **Failed to Process**: {total_failed}
- **Overall Success Rate**: {overall_success_rate:.1f}%

## Per-Website Results

""")
            
            for base_url, stats in self.processing_stats.items():
                parsed_url = urlparse(base_url)
                domain = parsed_url.netloc
                
                f.write(f"""### {domain}
- **Base URL**: {base_url}
- **URLs Discovered**: {stats.total_urls_discovered}
- **Successfully Processed**: {stats.success_count}
- **Failed**: {stats.failure_count}
- **Success Rate**: {stats.success_rate:.1f}%
- **Processing Time**: {stats.processing_duration:.2f} seconds

""")
                
                if stats.success_count > 0:
                    f.write(f"**Successful URLs ({stats.success_count}):**\n")
                    for url in stats.successful_urls:
                        f.write(f"- ✅ {url}\n")
                    f.write("\n")
                
                if stats.failure_count > 0:
                    f.write(f"**Failed URLs ({stats.failure_count}):**\n")
                    failures_by_reason = stats.get_failures_by_reason()
                    
                    for reason, failed_urls in failures_by_reason.items():
                        f.write(f"\n*{reason.replace('_', ' ').title()}* ({len(failed_urls)} URLs):\n")
                        for url in failed_urls:
                            failure_info = stats.failed_urls[url]
                            f.write(f"- ❌ {url}\n")
                            f.write(f"  - Error: {failure_info['error_msg']}\n")
                    f.write("\n")
                
                f.write("---\n\n")
        
        logger.info(f"Overall processing summary saved to: {log_filename}")

    async def deep_crawl_url(self, base_url: str) -> List[str]:
        """Use crawl4ai to deep crawl a URL and return all discovered URLs"""
        crawled_urls = []
        
        try:
            logger.info(f"Parsing URL: {base_url}")
            # Parse domain for filtering
            parsed_url = urlparse(base_url)
            domain = parsed_url.netloc
            logger.info(f"Extracted domain: {domain}")
            
            # Configure filter chain
            logger.info("Configuring filter chain...")
            filter_chain = FilterChain([
                DomainFilter(allowed_domains=[domain]),
                URLPatternFilter(patterns=["*"])  # Accept all patterns for now
            ])
            
            # Configure deep crawl strategy
            depth = int(self.depth_slider.get())
            logger.info(f"Configuring deep crawl with depth: {depth}")
            config = CrawlerRunConfig(
                deep_crawl_strategy=BFSDeepCrawlStrategy(
                    max_depth=depth,
                    include_external=False,
                    filter_chain=filter_chain,
                    max_pages=50  # Limit to prevent excessive crawling
                ),
                scraping_strategy=LXMLWebScrapingStrategy(),
                verbose=False
            )
            
            # Execute crawl
            logger.info("Starting AsyncWebCrawler...")
            async with AsyncWebCrawler() as crawler:
                logger.info(f"Executing crawl for: {base_url}")
                results = await crawler.arun(base_url, config=config)
                logger.info(f"Crawl completed. Results type: {type(results)}")
                
                # Collect all crawled URLs
                if isinstance(results, list):
                    crawled_urls = [result.url for result in results]
                    logger.info(f"Found {len(crawled_urls)} URLs from list results")
                else:
                    crawled_urls = [results.url]
                    logger.info(f"Found 1 URL from single result: {results.url}")
                    
        except Exception as e:
            logger.error(f"Error in deep crawl for {base_url}: {e}")
            crawled_urls = [base_url]  # Fallback to just the base URL
            logger.info(f"Using fallback URL: {base_url}")
            
        return crawled_urls
        
    async def extract_content_via_jina(self, url: str) -> Optional[str]:
        """Extract content from URL using r.jina.ai with detailed error tracking"""
        jina_url = f"https://r.jina.ai/{url}"
        logger.info(f"Requesting Jina API: {jina_url}")
        
        try:
            logger.info("Creating aiohttp session...")
            timeout = aiohttp.ClientTimeout(total=60, connect=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                logger.info(f"Making GET request to: {jina_url}")
                async with session.get(jina_url) as response:
                    logger.info(f"Received response with status: {response.status}")
                    if response.status == 200:
                        logger.info("Reading response content...")
                        content = await response.text()
                        logger.info(f"Successfully extracted {len(content)} characters from Jina API")
                        return content
                    else:
                        error_msg = f"Jina API returned HTTP {response.status} for {url}"
                        logger.error(error_msg)
                        # This will be caught by the calling method and tracked as HTTP_ERROR
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=error_msg
                        )
        except asyncio.TimeoutError as e:
            error_msg = f"Timeout error extracting content via Jina for {url}: {e}"
            logger.error(error_msg)
            # Re-raise with specific error type for tracking
            raise asyncio.TimeoutError(error_msg)
        except asyncio.CancelledError as e:
            error_msg = f"Request cancelled for Jina extraction of {url}: {e}"
            logger.error(error_msg)
            raise asyncio.CancelledError(error_msg)
        except aiohttp.ClientError as e:
            error_msg = f"Connection error extracting content via Jina for {url}: {e}"
            logger.error(error_msg)
            # Re-raise with specific error type for tracking
            raise aiohttp.ClientError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error extracting content via Jina for {url}: {e}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
    async def process_with_bedrock(self, markdown_content: str, source_url: str) -> Optional[str]:
        """Process markdown content through AWS Bedrock with enhanced error handling and retry logic"""
        
        if not self.bedrock_client:
            logger.error("Bedrock client not initialized")
            return None
            
        logger.info(f"Constructing prompt for {len(markdown_content)} characters of content")
        # Construct the prompt
        prompt = construct_prompt_for_aws_bedrock(markdown_content, source_url)
        logger.info(f"Prompt constructed. Length: {len(prompt)} characters")
        
        # Retry configuration for connection pool exhaustion
        max_retries = 3
        base_delay = 1.0  # Base delay in seconds
        
        for attempt in range(max_retries):
            try:
                # Get model configuration from environment variables
                model_id = os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-haiku-20241022-v1:0')
                temperature = float(os.getenv('BEDROCK_TEMPERATURE', '0.1'))
                max_tokens = int(os.getenv('BEDROCK_MAX_TOKENS', '8000'))
                
                if attempt > 0:
                    logger.info(f"Bedrock retry attempt {attempt + 1}/{max_retries} for {source_url}")
                else:
                    logger.info(f"Using Bedrock model: {model_id}, temperature: {temperature}, max_tokens: {max_tokens}")
                
                # Call AWS Bedrock in executor to make it truly async
                logger.info("Invoking Bedrock model...")
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.bedrock_client.invoke_model(
                        modelId=model_id,
                        contentType='application/json',
                        accept='application/json',
                        body=json.dumps({
                            'anthropic_version': 'bedrock-2023-05-31',
                            'max_tokens': max_tokens,
                            'temperature': temperature,
                            'messages': [
                                {
                                    'role': 'user',
                                    'content': prompt
                                }
                            ]
                        })
                    )
                )
                
                logger.info("Bedrock response received, parsing...")
                # Parse response
                response_body = json.loads(response['body'].read())
                processed_content = response_body['content'][0]['text']
                logger.info(f"Bedrock processing completed successfully. Output length: {len(processed_content)} characters")
                
                return processed_content
                
            except Exception as e:
                error_str = str(e).lower()
                
                # Check for connection pool exhaustion or related connection errors
                if any(keyword in error_str for keyword in [
                    'connection pool', 'pool is full', 'connection limit',
                    'too many connections', 'connection timeout', 'connection refused'
                ]):
                    if attempt < max_retries - 1:
                        # Exponential backoff with jitter for connection pool issues
                        delay = base_delay * (2 ** attempt) + (0.1 * attempt)  # Add small jitter
                        logger.warning(f"Connection pool issue detected for {source_url}: {e}")
                        logger.info(f"Retrying in {delay:.2f} seconds (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"Connection pool exhaustion persists after {max_retries} attempts for {source_url}: {e}")
                        return None
                
                # Check for throttling errors
                elif any(keyword in error_str for keyword in [
                    'throttling', 'rate limit', 'too many requests', 'service unavailable'
                ]):
                    if attempt < max_retries - 1:
                        # Longer delay for throttling
                        delay = base_delay * (3 ** attempt) + (0.5 * attempt)
                        logger.warning(f"Throttling detected for {source_url}: {e}")
                        logger.info(f"Backing off for {delay:.2f} seconds (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"Throttling persists after {max_retries} attempts for {source_url}: {e}")
                        return None
                
                # For other errors, retry with shorter delay
                elif attempt < max_retries - 1:
                    delay = base_delay * (1.5 ** attempt)
                    logger.warning(f"Bedrock error for {source_url}: {e}")
                    logger.info(f"Retrying in {delay:.2f} seconds (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Error processing with Bedrock after {max_retries} attempts for {source_url}: {e}")
                    return None
        
        return None
    
    def update_results_display(self, result: Dict):
        """Update the results display with processed content"""
        self.results_text.insert("end", f"\n{'='*80}\n")
        self.results_text.insert("end", f"URL: {result['original_url']}\n")
        self.results_text.insert("end", f"Processed at: {result['timestamp']}\n")
        self.results_text.insert("end", f"\n{result['processed_content']}\n")
        self.results_text.see("end")
        
    def export_results(self):
        """Export all results to files, organized by website"""
        if not self.processed_results:
            messagebox.showwarning("No Results", "No results to export")
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Group results by base URL (website)
        results_by_website = {}
        for result in self.processed_results:
            base_url = result['base_url']
            if base_url not in results_by_website:
                results_by_website[base_url] = []
            results_by_website[base_url].append(result)
        
        # Create separate export directory for each website
        export_dirs = []
        for base_url, website_results in results_by_website.items():
            # Extract website name for folder and prefix
            parsed_url = urlparse(base_url)
            domain = parsed_url.netloc
            
            # Create clean website name for folder
            website_name = domain.replace('.', '_').replace('-', '_')
            
            # Create website prefix
            domain_parts = domain.split('.')
            if len(domain_parts) >= 2:
                main_domain = domain_parts[-2] if domain_parts[-2] != 'www' else domain_parts[-3]
                website_prefix = main_domain.capitalize()
            else:
                website_prefix = domain_parts[0].capitalize()
            
            # Create export directory for this website
            export_dir = f"export_{website_name}_{timestamp}"
            os.makedirs(export_dir, exist_ok=True)
            export_dirs.append(export_dir)
            
            # Export each result for this website
            for idx, result in enumerate(website_results):
                # Create filename from URL with website prefix
                parsed_result_url = urlparse(result['original_url'])
                path_parts = [p for p in parsed_result_url.path.split('/') if p]
                if path_parts:
                    filename = '_'.join(path_parts)
                else:
                    filename = 'index'
                
                filename = re.sub(r'[^\w\-_]', '_', filename)
                if not filename:
                    filename = f"page_{idx}"
                
                # Add website-derived prefix
                filename = f"{website_prefix}-{filename}"
                
                # Save processed markdown
                file_path = os.path.join(export_dir, f"{filename}.md")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(result['processed_content'])
            
            # Save metadata for this website
            metadata_path = os.path.join(export_dir, "metadata.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'export_timestamp': timestamp,
                    'website_domain': domain,
                    'website_prefix': website_prefix,
                    'base_url': base_url,
                    'total_pages': len(website_results),
                    'results': [
                        {
                            'url': r['original_url'],
                            'base_url': r['base_url'],
                            'timestamp': r['timestamp']
                        }
                        for r in website_results
                    ]
                }, f, indent=2)
        
        # Show completion message
        total_files = len(self.processed_results)
        total_websites = len(results_by_website)
        export_summary = f"Exported {total_files} files across {total_websites} website(s):\n"
        for export_dir in export_dirs:
            export_summary += f"- {export_dir}\n"
            
        messagebox.showinfo("Export Complete", export_summary)
        self.status_bar.configure(text=f"Results exported to {total_websites} directories")

def construct_prompt_for_aws_bedrock(content: str, source_url: str) -> str:
    """
    Constructs an enhanced prompt for an LLM to transform website content
    into RAG-ready markdown, with special handling for API documentation.
    """
    # Detect if content contains API documentation
    is_api_content = any(keyword in content.lower() for keyword in [
        'api documentation overview', 'api endpoints', 'swagger', 'openapi',
        'endpoint', 'parameters', 'responses', 'method:', 'get ', 'post ', 'put ', 'delete '
    ])
    
    api_instructions = ""
    if is_api_content:
        api_instructions = """
**SPECIAL INSTRUCTIONS FOR API DOCUMENTATION:**
Since this content contains API documentation, pay special attention to:
- Preserve all API endpoint information (methods, paths, parameters, responses)
- Create clear sections for each endpoint with consistent formatting
- Use code blocks for request/response examples with appropriate language tags
- Include parameter tables with proper markdown table formatting
- Maintain the hierarchical structure of API information
- Add appropriate tags like 'api', 'rest', 'endpoints', 'swagger' to the YAML front matter
- Ensure each endpoint section is self-contained for optimal RAG retrieval
"""

    prompt = f"""You are **DocuRAG** an expert Documentation Formatter and Structuring Agent specializing in creating RAG-ready markdown files optimized for retrieval and comprehension. Your mission is to transform web content into *meticulously structured, RAG-optimized, flawless, retrieval-ready Markdown*.
Adherence to the following rules is paramount for successful knowledge base ingestion and retrieval.

ORIGINAL CONTENT:
{content}

SOURCE URL: {source_url}
{api_instructions}
TASK: Transform the above "ORIGINAL CONTENT" into a perfectly formatted markdown document. You MUST follow ALL these STRICT rules:

1.  **YAML FRONT MATTER (STRICTLY REQUIRED):**
    Place this at the very beginning of the document.
    -   `title`: Extract a concise, descriptive title from the content. If no clear title exists, synthesize one that accurately reflects the main topic.
    -   `summary`: Craft a 1-2 sentence overview of the document's main purpose and key takeaways.
    -   `tags`: Generate 3-5 relevant lowercase tags (keywords or key phrases) derived from the content. Use hyphens for multi-word tags (e.g., 'machine-learning', 'data-privacy').
    -   `created`: Use today's actual date in YYYY-MM-DD format (e.g., if today is June 11, 2025, use 2025-06-11).
    -   `version`: v1.0
    -   `lang`: en
    -   `source_url`: {source_url} (Use the provided SOURCE URL here)

2.  **TABLE OF CONTENTS (TOC):**
    -   Generate a Markdown TOC immediately after the YAML front matter.
    -   The TOC should list all `##` and `###` headings.
    -   Each TOC item must be an anchor link to the corresponding heading. Ensure anchor links are correctly formatted (e.g., `- [Heading Title](#heading-title)`: lowercase, hyphens for spaces, special characters removed or transliterated).

3.  **HIERARCHICAL HEADINGS (CLEAN & CONSISTENT):**
    -   Re-structure content using a clean `#` (Main Title, usually corresponds to YAML title) -> `##` (Major Sections) -> `###` (Sub-sections) hierarchy. Avoid deeper nesting (#### or more) unless absolutely essential for clarity.
    -   Heading titles MUST be in sentence-case (e.g., 'This is a heading', not 'This Is A Heading' or 'THIS IS A HEADING').
    -   Keep heading text concise and descriptive, ideally under 80 characters.
    -   Ensure logical flow and progression of topics through headings.

4.  **CHUNK OPTIMIZATION for RAG (CRITICAL):**
    -   Divide the content into logical, self-contained chunks. Each chunk should ideally represent a distinct topic or sub-topic.
    -   Target 128-512 tokens per conceptual section (estimate). A section is typically the content under an `##` or `###` heading.
    -   Insert a `<!-- CHUNK -->` marker *before* each new major thematic section. This usually means placing `<!-- CHUNK -->` before most `##` headings, and sometimes before `###` headings if the preceding `##` section is very long or covers multiple distinct ideas.
    -   Each chunk (the content between `<!-- CHUNK -->` markers, or from the start to the first marker, or from the last marker to the end) *must* be understandable on its own, containing sufficient context.

5.  **MINI-SUMMARIES (TL;DRs for ## SECTIONS):**
    -   Immediately after the text content of *every* `##` heading's section (before any `###` subheadings within it or the next `##` heading), add a concise summary prefixed with `> **TL;DR:**`.
    -   These summaries should be 1-2 sentences maximum, capturing the essence of that specific `##` section's content.

6.  **NATIVE MARKDOWN & CONTENT CONVERSION:**
    -   Use *only* standard Markdown syntax (lists, tables, code blocks, bold, italics, links etc.).
    -   **NO raw HTML is permitted**, *except* for the `<!-- CHUNK -->` comments.
    -   Convert any HTML tables, lists, emphasis, etc., into their proper Markdown equivalents.
    -   Code Blocks:
        *   Must be enclosed in triple backticks (```).
        *   Must have a language identifier (e.g., ```python, ```javascript, ```bash, ```json, ```yaml, ```html, ```css). If the language is unknown or plain text, use ```text.
        *   Must be preceded by a brief, descriptive sentence or a small H3-like heading (e.g., `**Example: Python code for X**` or `### Python Code Example`) clearly explaining the code's purpose or context.

7.  **SELF-CONTAINED & ACCESSIBLE ELEMENTS:**
    -   Tables: Must be preceded by a short introductory sentence or paragraph explaining their content, purpose, or key insights.
    -   Images:
        *   Convert any HTML `<img>` tags to Markdown `![]()` format.
        *   If `alt` text is present in the original `<img>` tag, preserve it in the Markdown `![alt text](url)`.
        *   If `alt` text is missing, infer a brief, descriptive alt text from the surrounding content or the image's purpose. If inference is impossible, use a placeholder like `[Image: descriptive placeholder, e.g., 'workflow diagram']`.
        *   The image source (URL) must be retained. Do not attempt to embed image data.
    -   Links: Preserve all hyperlinks from the original content. Ensure they use standard markdown link format `[link text](URL)`.

8.  **FORMATTING & STRUCTURE SPECIFICS:**
    -   Use consistent spacing:
        *   One blank line after YAML front matter before the TOC.
        *   One blank line after the TOC before the first heading (`#`).
        *   One blank line before and after headings (`#`, `##`, `###`).
        *   One blank line between paragraphs.
        *   One blank line before and after lists, tables, code blocks, and `<!-- CHUNK -->` markers.
    -   Ensure all Markdown syntax is correctly and cleanly applied.
    -   The overall structure must be clean, readable, and logically organized.

FINAL OUTPUT:
Provide ONLY the fully formatted Markdown document. Your response must begin *directly* with `---` (the start of the YAML front matter) and contain nothing else before or after the markdown content. Do not include any apologies, disclaimers, or explanations outside of the Markdown content itself.
"""
    return prompt

def main():
    app = URLScraperApp()
    app.mainloop()

if __name__ == "__main__":
    main()