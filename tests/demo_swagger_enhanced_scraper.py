#!/usr/bin/env python3
"""
SwaggerEnhancedScraper Demonstration Script

This script demonstrates the enhanced Swagger/OpenAPI documentation processing capabilities
integrated into the URL Scraper with AI Processing system. It showcases:

1. Automatic Swagger/OpenAPI detection
2. Enhanced API documentation extraction
3. Improved statistics tracking
4. Better content formatting for RAG optimization
5. Real-world examples with popular API documentation sites

Features:
- Interactive demo scenarios
- Before/after comparison
- Performance metrics
- Educational explanations
- Real-world API documentation examples
"""

import asyncio
import aiohttp
import json
import time
import sys
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse
import requests
from dataclasses import dataclass
import logging

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from url_scraper_md_formatter import SwaggerEnhancedScraper, ProcessingStats
except ImportError as e:
    print(f"❌ Error importing SwaggerEnhancedScraper: {e}")
    print("Please ensure url_scraper_md_formatter.py is in the same directory")
    sys.exit(1)

# Configure logging for demo
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class DemoResult:
    """Container for demo processing results"""
    url: str
    is_swagger: bool
    confidence: float
    indicators: List[str]
    spec_urls: List[str]
    extraction_method: str
    endpoints_found: int
    processing_time: float
    enhanced_content_length: int
    error: Optional[str] = None

class SwaggerDemoRunner:
    """
    Interactive demonstration runner for SwaggerEnhancedScraper functionality
    """
    
    def __init__(self):
        self.scraper = SwaggerEnhancedScraper()
        self.session = None
        self.demo_sites = {
            'swagger_examples': [
                {
                    'name': 'Swagger Petstore (Classic Demo)',
                    'url': 'https://petstore.swagger.io/',
                    'description': 'The classic Swagger demo site with full OpenAPI 3.0 spec',
                    'expected_features': ['OpenAPI spec', 'Interactive UI', 'Multiple endpoints']
                },
                {
                    'name': 'Swagger Editor Demo',
                    'url': 'https://editor.swagger.io/',
                    'description': 'Online Swagger editor with live preview',
                    'expected_features': ['Swagger UI', 'Live editing', 'Spec validation']
                },
                {
                    'name': 'OpenAPI Generator',
                    'url': 'https://openapi-generator.tech/',
                    'description': 'OpenAPI Generator documentation site',
                    'expected_features': ['Documentation', 'Code examples', 'API references']
                }
            ],
            'api_docs': [
                {
                    'name': 'GitHub API Documentation',
                    'url': 'https://docs.github.com/en/rest',
                    'description': 'GitHub REST API documentation',
                    'expected_features': ['REST endpoints', 'Authentication', 'Examples']
                },
                {
                    'name': 'JSONPlaceholder API',
                    'url': 'https://jsonplaceholder.typicode.com/',
                    'description': 'Fake REST API for testing and prototyping',
                    'expected_features': ['Simple endpoints', 'JSON responses', 'Testing data']
                }
            ],
            'regular_docs': [
                {
                    'name': 'Python Documentation',
                    'url': 'https://docs.python.org/3/',
                    'description': 'Standard Python documentation (non-API)',
                    'expected_features': ['Language docs', 'Tutorials', 'References']
                },
                {
                    'name': 'MDN Web Docs',
                    'url': 'https://developer.mozilla.org/en-US/',
                    'description': 'Web development documentation',
                    'expected_features': ['Web standards', 'Tutorials', 'References']
                }
            ]
        }
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'SwaggerDemo/1.0 (Educational Demo)'}
        )
        self.scraper.session = self.session
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    def print_header(self, title: str, char: str = "="):
        """Print a formatted header"""
        print(f"\n{char * 80}")
        print(f"{title:^80}")
        print(f"{char * 80}")

    def print_section(self, title: str):
        """Print a section header"""
        print(f"\n{'─' * 60}")
        print(f"📋 {title}")
        print(f"{'─' * 60}")

    def print_result_summary(self, result: DemoResult):
        """Print a formatted result summary"""
        status_icon = "🔍" if result.is_swagger else "📄"
        confidence_bar = "█" * int(result.confidence * 10) + "░" * (10 - int(result.confidence * 10))
        
        print(f"\n{status_icon} {result.url}")
        print(f"   Swagger Detection: {'✅ YES' if result.is_swagger else '❌ NO'}")
        print(f"   Confidence: {result.confidence:.2f} [{confidence_bar}]")
        print(f"   Processing Time: {result.processing_time:.2f}s")
        
        if result.is_swagger:
            print(f"   🎯 Indicators Found: {len(result.indicators)}")
            print(f"   📊 API Endpoints: {result.endpoints_found}")
            print(f"   🔧 Extraction Method: {result.extraction_method}")
            print(f"   📝 Enhanced Content: {result.enhanced_content_length:,} chars")
            
            if result.indicators:
                print(f"   🔍 Detection Signals: {', '.join(result.indicators[:3])}")
                if len(result.indicators) > 3:
                    print(f"      ... and {len(result.indicators) - 3} more")
        
        if result.error:
            print(f"   ⚠️  Error: {result.error}")

    async def demonstrate_detection(self, sites: List[Dict]) -> List[DemoResult]:
        """Demonstrate Swagger detection on a list of sites"""
        results = []
        
        for site in sites:
            print(f"\n🔍 Testing: {site['name']}")
            print(f"   URL: {site['url']}")
            print(f"   Description: {site['description']}")
            
            start_time = time.time()
            
            try:
                # Perform Swagger detection
                detection_result = await self.scraper.detect_swagger_page(site['url'])
                processing_time = time.time() - start_time
                
                # Create demo result
                result = DemoResult(
                    url=site['url'],
                    is_swagger=detection_result.get('is_swagger', False),
                    confidence=detection_result.get('confidence', 0.0),
                    indicators=detection_result.get('indicators', []),
                    spec_urls=detection_result.get('spec_urls', []),
                    extraction_method=detection_result.get('extraction_method', 'unknown'),
                    endpoints_found=0,  # Will be populated if we extract endpoints
                    processing_time=processing_time,
                    enhanced_content_length=0,
                    error=detection_result.get('error')
                )
                
                # If Swagger detected, try to extract more details
                if result.is_swagger and not result.error:
                    try:
                        # Try to get enhanced content
                        enhanced_result = await self.scraper.enhanced_extract(site['url'])
                        if enhanced_result and enhanced_result.get('success') and 'api_data' in enhanced_result:
                            api_data = enhanced_result['api_data']
                            result.endpoints_found = api_data.get('total_endpoints', 0)
                            result.enhanced_content_length = len(str(enhanced_result))
                    except Exception as e:
                        logger.debug(f"Could not extract enhanced content: {e}")
                
                results.append(result)
                self.print_result_summary(result)
                
            except Exception as e:
                error_result = DemoResult(
                    url=site['url'],
                    is_swagger=False,
                    confidence=0.0,
                    indicators=[],
                    spec_urls=[],
                    extraction_method='error',
                    endpoints_found=0,
                    processing_time=time.time() - start_time,
                    enhanced_content_length=0,
                    error=str(e)
                )
                results.append(error_result)
                self.print_result_summary(error_result)
        
        return results

    def analyze_results(self, results: List[DemoResult]):
        """Analyze and display comprehensive results"""
        self.print_section("📊 Analysis Summary")
        
        total_sites = len(results)
        swagger_sites = sum(1 for r in results if r.is_swagger)
        avg_confidence = sum(r.confidence for r in results) / total_sites if total_sites > 0 else 0
        total_endpoints = sum(r.endpoints_found for r in results)
        avg_processing_time = sum(r.processing_time for r in results) / total_sites if total_sites > 0 else 0
        
        print(f"📈 Detection Statistics:")
        print(f"   Total Sites Tested: {total_sites}")
        print(f"   Swagger Sites Found: {swagger_sites} ({swagger_sites/total_sites*100:.1f}%)")
        print(f"   Average Confidence: {avg_confidence:.2f}")
        print(f"   Total API Endpoints: {total_endpoints}")
        print(f"   Average Processing Time: {avg_processing_time:.2f}s")
        
        # Breakdown by category
        swagger_results = [r for r in results if r.is_swagger]
        if swagger_results:
            print(f"\n🎯 Swagger Sites Details:")
            for result in swagger_results:
                print(f"   • {urlparse(result.url).netloc}: {result.endpoints_found} endpoints, "
                      f"{result.confidence:.2f} confidence")
        
        # Detection methods used
        methods = {}
        for result in swagger_results:
            method = result.extraction_method
            methods[method] = methods.get(method, 0) + 1
        
        if methods:
            print(f"\n🔧 Extraction Methods Used:")
            for method, count in methods.items():
                print(f"   • {method}: {count} sites")

    def demonstrate_enhancement_comparison(self, swagger_result: DemoResult):
        """Show before/after comparison of content enhancement"""
        if not swagger_result.is_swagger:
            return
            
        self.print_section("🔄 Content Enhancement Comparison")
        
        print("📄 Standard Processing:")
        print("   • Basic HTML content extraction")
        print("   • Generic markdown formatting")
        print("   • Limited API structure recognition")
        print("   • Standard metadata collection")
        
        print("\n🚀 Enhanced Swagger Processing:")
        print("   • Automatic API documentation detection")
        print("   • OpenAPI specification parsing")
        print("   • Structured endpoint extraction")
        print("   • Enhanced metadata with API details")
        print("   • RAG-optimized content formatting")
        print("   • Fallback to HTML scraping when needed")
        
        print(f"\n📊 Enhancement Impact:")
        print(f"   • API Endpoints Extracted: {swagger_result.endpoints_found}")
        print(f"   • Detection Confidence: {swagger_result.confidence:.2f}")
        print(f"   • Enhanced Content Size: {swagger_result.enhanced_content_length:,} characters")
        print(f"   • Processing Method: {swagger_result.extraction_method}")

    async def interactive_demo(self):
        """Run interactive demonstration"""
        self.print_header("🚀 SwaggerEnhancedScraper Interactive Demo")
        
        print("Welcome to the SwaggerEnhancedScraper demonstration!")
        print("This demo showcases enhanced API documentation processing capabilities.")
        print("\nAvailable demo scenarios:")
        print("1. 🔍 Swagger/OpenAPI Sites Detection")
        print("2. 📚 API Documentation Sites")
        print("3. 📄 Regular Documentation Sites (for comparison)")
        print("4. 🎯 Custom URL Testing")
        print("5. 📊 Comprehensive Analysis")
        print("0. Exit")
        
        all_results = []
        
        while True:
            try:
                choice = input("\n👉 Select demo scenario (0-5): ").strip()
                
                if choice == "0":
                    print("\n👋 Thank you for trying the SwaggerEnhancedScraper demo!")
                    break
                    
                elif choice == "1":
                    self.print_header("🔍 Swagger/OpenAPI Sites Detection", "=")
                    print("Testing sites known to use Swagger/OpenAPI documentation...")
                    results = await self.demonstrate_detection(self.demo_sites['swagger_examples'])
                    all_results.extend(results)
                    
                    # Show enhancement comparison for first Swagger site found
                    swagger_results = [r for r in results if r.is_swagger]
                    if swagger_results:
                        self.demonstrate_enhancement_comparison(swagger_results[0])
                    
                elif choice == "2":
                    self.print_header("📚 API Documentation Sites", "=")
                    print("Testing general API documentation sites...")
                    results = await self.demonstrate_detection(self.demo_sites['api_docs'])
                    all_results.extend(results)
                    
                elif choice == "3":
                    self.print_header("📄 Regular Documentation Sites", "=")
                    print("Testing non-API documentation sites for comparison...")
                    results = await self.demonstrate_detection(self.demo_sites['regular_docs'])
                    all_results.extend(results)
                    
                elif choice == "4":
                    self.print_header("🎯 Custom URL Testing", "=")
                    url = input("Enter URL to test: ").strip()
                    if url:
                        custom_site = {
                            'name': 'Custom URL',
                            'url': url,
                            'description': 'User-provided URL for testing'
                        }
                        results = await self.demonstrate_detection([custom_site])
                        all_results.extend(results)
                    else:
                        print("❌ No URL provided")
                        
                elif choice == "5":
                    if all_results:
                        self.print_header("📊 Comprehensive Analysis", "=")
                        self.analyze_results(all_results)
                        self.show_practical_benefits()
                    else:
                        print("❌ No results to analyze. Please run some tests first.")
                        
                else:
                    print("❌ Invalid choice. Please select 0-5.")
                    
            except KeyboardInterrupt:
                print("\n\n👋 Demo interrupted by user. Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error during demo: {e}")
                logger.exception("Demo error")

    def show_practical_benefits(self):
        """Display practical benefits of the enhancement"""
        self.print_section("🎯 Practical Benefits for RAG Applications")
        
        print("🔍 Enhanced Detection:")
        print("   • Automatically identifies API documentation sites")
        print("   • Confidence scoring helps prioritize processing")
        print("   • Multiple detection methods ensure comprehensive coverage")
        
        print("\n📊 Better Content Structure:")
        print("   • Structured API endpoint information")
        print("   • Parameter and response documentation")
        print("   • Clear separation of API methods and paths")
        print("   • Enhanced metadata for better search and retrieval")
        
        print("\n🚀 RAG Optimization:")
        print("   • Content formatted specifically for LLM processing")
        print("   • Improved context for API-related queries")
        print("   • Better semantic understanding of API documentation")
        print("   • Enhanced retrieval accuracy for technical questions")
        
        print("\n⚡ Performance Benefits:")
        print("   • Minimal processing overhead")
        print("   • Graceful fallback mechanisms")
        print("   • Preserved backward compatibility")
        print("   • Robust error handling")

    async def quick_demo(self):
        """Run a quick demonstration with pre-selected sites"""
        self.print_header("⚡ Quick SwaggerEnhancedScraper Demo")
        
        print("Running quick demo with representative sites...")
        
        # Select one site from each category
        demo_sites = [
            self.demo_sites['swagger_examples'][0],  # Swagger Petstore
            self.demo_sites['api_docs'][0],          # GitHub API
            self.demo_sites['regular_docs'][0]       # Python Docs
        ]
        
        results = await self.demonstrate_detection(demo_sites)
        
        print("\n" + "="*60)
        print("📋 QUICK DEMO SUMMARY")
        print("="*60)
        
        self.analyze_results(results)
        
        # Show enhancement for any Swagger sites found
        swagger_results = [r for r in results if r.is_swagger]
        if swagger_results:
            self.demonstrate_enhancement_comparison(swagger_results[0])
        
        self.show_practical_benefits()

def print_welcome():
    """Print welcome message and instructions"""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    SwaggerEnhancedScraper Demonstration                      ║
║                                                                              ║
║  This demo showcases the enhanced Swagger/OpenAPI documentation processing  ║
║  capabilities integrated into the URL Scraper with AI Processing system.    ║
║                                                                              ║
║  Key Features Demonstrated:                                                  ║
║  • Automatic Swagger/OpenAPI detection with confidence scoring              ║
║  • Enhanced API documentation extraction and processing                     ║
║  • Improved statistics tracking for API documentation                       ║
║  • Better content formatting optimized for RAG applications                 ║
║  • Real-world examples with popular API documentation sites                 ║
║                                                                              ║
║  Demo Modes:                                                                 ║
║  • Interactive: Choose specific demo scenarios                              ║
║  • Quick: Run automated demo with representative sites                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

async def main():
    """Main demo function"""
    print_welcome()
    
    # Check if running in quick mode
    quick_mode = len(sys.argv) > 1 and sys.argv[1].lower() in ['quick', 'q', '--quick']
    
    try:
        async with SwaggerDemoRunner() as demo:
            if quick_mode:
                await demo.quick_demo()
            else:
                await demo.interactive_demo()
                
    except KeyboardInterrupt:
        print("\n\n👋 Demo interrupted. Goodbye!")
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        logger.exception("Demo failure")
        return 1
    
    return 0

if __name__ == "__main__":
    # Run the demo
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)