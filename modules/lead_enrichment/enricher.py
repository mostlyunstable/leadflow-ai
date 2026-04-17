"""
Lead Enrichment Engine — Scrape company websites and extract key information.
Uses BeautifulSoup for parsing and OpenAI for intelligent summarization.
"""

import logging
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config.settings import (
    SCRAPE_TIMEOUT,
    SCRAPE_USER_AGENT,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_BASE_URL,
)
from database.database import get_session
from database.models import Lead, LeadStatus

logger = logging.getLogger(__name__)


class LeadEnricher:
    """Scrapes company websites and enriches lead data with AI summarization."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def scrape_website(self, url: str) -> Optional[dict]:
        """
        Scrape a company website for relevant information.
        
        Returns:
            dict with keys: title, meta_description, headings, content, about_content
        """
        if not url:
            return None

        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        scraped = {
            "title": "",
            "meta_description": "",
            "headings": [],
            "content": "",
            "about_content": "",
            "url": url,
        }

        try:
            # Scrape homepage
            resp = self.session.get(url, timeout=SCRAPE_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove script/style tags
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            # Extract metadata
            scraped["title"] = soup.title.string.strip() if soup.title and soup.title.string else ""

            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                scraped["meta_description"] = meta_desc["content"].strip()

            # Extract headings
            for tag in ["h1", "h2", "h3"]:
                for heading in soup.find_all(tag, limit=5):
                    text = heading.get_text(strip=True)
                    if text and len(text) > 3:
                        scraped["headings"].append(text)

            # Extract body content (first 1000 chars of visible text)
            body_text = soup.get_text(separator=" ", strip=True)
            scraped["content"] = body_text[:1500]

            # Try to find and scrape About page
            about_url = self._find_about_page(soup, url)
            if about_url:
                scraped["about_content"] = self._scrape_about_page(about_url)

        except requests.RequestException as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error scraping {url}: {e}")
            return None

        return scraped

    def _find_about_page(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find the About page URL from the homepage."""
        about_patterns = ["about", "about-us", "about_us", "who-we-are", "our-story"]

        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            link_text = link.get_text(strip=True).lower()

            if any(pattern in href or pattern in link_text for pattern in about_patterns):
                return urljoin(base_url, link["href"])

        return None

    def _scrape_about_page(self, url: str) -> str:
        """Scrape the about page for company description."""
        try:
            resp = self.session.get(url, timeout=SCRAPE_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            return soup.get_text(separator=" ", strip=True)[:1000]
        except Exception as e:
            logger.warning(f"Failed to scrape about page {url}: {e}")
            return ""

    def summarize_with_ai(self, scraped_data: dict, company_name: str) -> dict:
        """
        Use OpenAI to summarize scraped data into structured enrichment.
        
        Returns:
            dict with keys: company_description, industry, key_offering
        """
        if not OPENAI_API_KEY:
            logger.warning("OpenAI API key not set, skipping AI enrichment")
            return self._basic_enrichment(scraped_data)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

            # Build context
            context_parts = [f"Company: {company_name}"]
            if scraped_data.get("title"):
                context_parts.append(f"Website title: {scraped_data['title']}")
            if scraped_data.get("meta_description"):
                context_parts.append(f"Meta description: {scraped_data['meta_description']}")
            if scraped_data.get("headings"):
                context_parts.append(f"Key headings: {', '.join(scraped_data['headings'][:5])}")
            if scraped_data.get("about_content"):
                context_parts.append(f"About page excerpt: {scraped_data['about_content'][:500]}")
            elif scraped_data.get("content"):
                context_parts.append(f"Homepage excerpt: {scraped_data['content'][:500]}")

            context = "\n".join(context_parts)

            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a business analyst. Given website data about a company, "
                            "extract and return a JSON object with exactly these keys:\n"
                            '- "company_description": A concise 1-2 sentence description of what the company does\n'
                            '- "industry": The company\'s primary industry/sector (e.g., "SaaS", "E-commerce", "Healthcare Tech")\n'
                            '- "key_offering": Their main product or service in one sentence\n'
                            "Return ONLY valid JSON, no markdown."
                        ),
                    },
                    {
                        "role": "user",
                        "content": context,
                    },
                ],
                temperature=0.3,
                max_tokens=300,
            )

            import json
            result_text = response.choices[0].message.content.strip()
            # Clean potential markdown wrapping
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0]

            return json.loads(result_text)

        except Exception as e:
            logger.error(f"AI enrichment failed for {company_name}: {e}")
            return self._basic_enrichment(scraped_data)

    def _basic_enrichment(self, scraped_data: dict) -> dict:
        """Fallback enrichment without AI — extract what we can."""
        return {
            "company_description": scraped_data.get("meta_description", ""),
            "industry": "",
            "key_offering": scraped_data.get("title", ""),
        }

    def enrich_lead(self, lead_id: int) -> bool:
        """
        Enrich a single lead by scraping their company website.
        Returns True if enrichment was successful.
        """
        with get_session() as session:
            lead = session.query(Lead).get(lead_id)
            if not lead:
                logger.error(f"Lead {lead_id} not found")
                return False

            if lead.enriched:
                logger.info(f"Lead {lead_id} already enriched, skipping")
                return True

            # Scrape website
            scraped = None
            if lead.website:
                scraped = self.scrape_website(lead.website)

            # Summarize
            if scraped:
                enrichment = self.summarize_with_ai(scraped, lead.company_name)
            else:
                # Minimal enrichment from available data
                enrichment = {
                    "company_description": "",
                    "industry": lead.industry or "",
                    "key_offering": "",
                }

            # Update lead
            lead.company_description = enrichment.get("company_description", "")
            if enrichment.get("industry"):
                lead.industry = enrichment["industry"]
            lead.key_offering = enrichment.get("key_offering", "")
            lead.enriched = True
            lead.status = LeadStatus.ENRICHED

            logger.info(f"Enriched lead {lead_id}: {lead.full_name} @ {lead.company_name}")
            return True

    def enrich_all_pending(self, delay: float = 1.0) -> dict:
        """
        Enrich all leads that haven't been enriched yet.
        
        Args:
            delay: Seconds between scrape requests (rate limiting)
            
        Returns:
            dict with enrichment stats
        """
        with get_session() as session:
            pending = session.query(Lead).filter_by(enriched=False).all()
            lead_ids = [lead.id for lead in pending]

        total = len(lead_ids)
        success = 0
        failed = 0

        for idx, lead_id in enumerate(lead_ids):
            logger.info(f"Enriching lead {idx + 1}/{total}...")
            try:
                if self.enrich_lead(lead_id):
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Failed to enrich lead {lead_id}: {e}")
                failed += 1

            # Rate limiting
            if idx < total - 1:
                time.sleep(delay)

        return {
            "total": total,
            "enriched": success,
            "failed": failed,
        }
