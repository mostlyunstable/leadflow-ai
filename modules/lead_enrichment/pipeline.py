"""
Layered Website Enrichment Pipeline with SSRF Defense & Browser Fallback.
Implements:
1. SSRF-validated network fetching with re-validation on every redirect hop.
2. Anti-bot / JS-shell detection triggering automated browser fallback.
3. Content cleaning, semantic segmentation, and metadata extraction.
4. Confidence scoring and structured profile generation.
"""

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from core.config import settings
from core.security import validate_and_sanitize_target_url

logger = logging.getLogger("leadflow.enrichment")


@dataclass
class FetchedDocument:
    url: str
    final_url: str
    resolved_ip: Optional[str]
    fetch_method: str  # 'http' or 'browser'
    status_code: int
    raw_html: str
    is_usable: bool
    fallback_triggered: bool = False
    error: Optional[str] = None


@dataclass
class ExtractedProfile:
    target_url: str
    fetch_method: str
    http_status: int
    resolved_ip: Optional[str]
    title: str = ""
    meta_description: str = ""
    headings: List[str] = field(default_factory=list)
    clean_text: str = ""
    company_description: str = ""
    industry: str = ""
    key_offering: str = ""
    confidence_score: float = 0.0
    error: Optional[str] = None


class SSRFSafeHTTPFetcher:
    """
    HTTP Client with strict SSRF defenses.
    Re-validates resolved IPs before connecting and on every redirect hop.
    """

    def __init__(self, timeout: int = 10, max_redirects: int = 3):
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.SCRAPE_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch(self, url: str) -> FetchedDocument:
        """
        Fetch URL safely without following redirects blindly into private subnets.
        """
        current_url = url
        resolved_ip_str = None

        for redirect_hop in range(self.max_redirects + 1):
            # Validate URL against SSRF before every request hop
            is_safe, sanitized_url, rejection_reason = validate_and_sanitize_target_url(current_url)
            if not is_safe:
                logger.warning(f"SSRF blocked request to {current_url}: {rejection_reason}")
                return FetchedDocument(
                    url=url,
                    final_url=current_url,
                    resolved_ip=None,
                    fetch_method="http",
                    status_code=400,
                    raw_html="",
                    is_usable=False,
                    error=f"Blocked by SSRF policy: {rejection_reason}",
                )

            current_url = sanitized_url

            # Capture resolved IP
            try:
                hostname = urlparse(current_url).hostname
                addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                resolved_ip_str = addr_info[0][4][0]
            except Exception:
                pass

            try:
                resp = self.session.get(
                    current_url,
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=True,
                )

                # Cap content length
                content_chunks = []
                bytes_read = 0
                for chunk in resp.iter_content(chunk_size=16384, decode_unicode=False):
                    content_chunks.append(chunk)
                    bytes_read += len(chunk)
                    if bytes_read > settings.SCRAPE_MAX_CONTENT_LENGTH:
                        logger.warning(f"Truncated large response from {current_url} at {bytes_read} bytes")
                        break

                raw_bytes = b"".join(content_chunks)
                # Decode text with fallback
                try:
                    encoding = resp.encoding or "utf-8"
                    raw_html = raw_bytes.decode(encoding, errors="replace")
                except Exception:
                    raw_html = raw_bytes.decode("utf-8", errors="replace")

                # Handle redirect
                if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        break
                    current_url = urljoin(current_url, location)
                    logger.debug(f"Following safe redirect hop {redirect_hop + 1} to {current_url}")
                    continue

                # Finished all redirects
                is_usable = self._evaluate_usability(resp.status_code, raw_html)
                return FetchedDocument(
                    url=url,
                    final_url=current_url,
                    resolved_ip=resolved_ip_str,
                    fetch_method="http",
                    status_code=resp.status_code,
                    raw_html=raw_html,
                    is_usable=is_usable,
                    fallback_triggered=not is_usable,
                )

            except requests.Timeout:
                return FetchedDocument(
                    url=url,
                    final_url=current_url,
                    resolved_ip=resolved_ip_str,
                    fetch_method="http",
                    status_code=408,
                    raw_html="",
                    is_usable=False,
                    error="Connection timeout during HTTP fetch",
                )
            except Exception as e:
                logger.warning(f"HTTP fetch error on {current_url}: {e}")
                return FetchedDocument(
                    url=url,
                    final_url=current_url,
                    resolved_ip=resolved_ip_str,
                    fetch_method="http",
                    status_code=500,
                    raw_html="",
                    is_usable=False,
                    error=str(e),
                )

        return FetchedDocument(
            url=url,
            final_url=current_url,
            resolved_ip=resolved_ip_str,
            fetch_method="http",
            status_code=310,
            raw_html="",
            is_usable=False,
            error="Exceeded maximum redirects",
        )

    def _evaluate_usability(self, status_code: int, html: str) -> bool:
        """
        Check if the returned HTML contains meaningful content or indicates
        a JS shell / Cloudflare bot block requiring browser fallback.
        """
        if status_code != 200:
            return False

        lower_html = html.lower()
        # Detect WAF / Cloudflare challenge patterns
        waf_triggers = [
            "just a moment...",
            "cf-browser-verification",
            "attention required! | cloudflare",
            "please turn javascript on and reload",
            "access denied | www.",
            "enable javascript to run this app",
        ]
        if any(trigger in lower_html for trigger in waf_triggers):
            logger.info("Anti-bot / Cloudflare challenge detected in HTTP response")
            return False

        # Detect empty single-page app shells
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        if not body:
            return False

        body_text = body.get_text(separator=" ", strip=True)
        # If body text is under 100 characters, it's typically an empty JS container
        if len(body_text) < 100:
            logger.info(f"Insufficient body text ({len(body_text)} chars) - JS shell suspected")
            return False

        return True


import threading


class BrowserFallbackFetcher:
    """
    Headless browser fetcher for dynamic, JavaScript-rendered websites.
    Guarded by a bounded concurrency semaphore to prevent host RAM exhaustion.
    """
    _concurrency_semaphore = threading.BoundedSemaphore(
        value=getattr(settings, "MAX_CONCURRENT_BROWSERS", 3)
    )

    def fetch(self, url: str) -> FetchedDocument:
        is_safe, sanitized_url, reason = validate_and_sanitize_target_url(url)
        if not is_safe:
            return FetchedDocument(
                url=url,
                final_url=url,
                resolved_ip=None,
                fetch_method="browser",
                status_code=400,
                raw_html="",
                is_usable=False,
                error=f"SSRF blocked: {reason}",
            )

        # Enforce bounded concurrency
        acquired = self._concurrency_semaphore.acquire(timeout=5.0)
        if not acquired:
            logger.warning("Browser concurrency pool exhausted. Throttling browser request to prevent host memory exhaustion.")
            return FetchedDocument(
                url=url,
                final_url=url,
                resolved_ip=None,
                fetch_method="browser",
                status_code=503,
                raw_html="",
                is_usable=False,
                error="Browser pool busy (concurrency cap reached)",
            )

        logger.info(f"Executing browser fetch for {sanitized_url}...")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=settings.SCRAPE_USER_AGENT,
                )
                page.set_default_timeout(settings.BROWSER_TIMEOUT_MS)
                response = page.goto(sanitized_url, wait_until="domcontentloaded")
                # Wait briefly for dynamic hydration
                page.wait_for_timeout(1500)
                content = page.content()
                status = response.status if response else 200
                browser.close()

                return FetchedDocument(
                    url=url,
                    final_url=sanitized_url,
                    resolved_ip=None,
                    fetch_method="browser",
                    status_code=status,
                    raw_html=content,
                    is_usable=len(content) > 200,
                )
        except Exception as e:
            logger.warning(f"Browser fallback execution error for {url}: {e}")
            return FetchedDocument(
                url=url,
                final_url=sanitized_url,
                resolved_ip=None,
                fetch_method="browser",
                status_code=500,
                raw_html="",
                is_usable=False,
                error=f"Browser fallback failed: {e}",
            )
        finally:
            self._concurrency_semaphore.release()


class EnrichmentPipeline:
    """
    Orchestrates the layered enrichment process:
    SSRF-Safe HTTP Fetch -> Browser Fallback (if needed) -> DOM Parsing -> Profile Extraction
    """

    def __init__(self):
        self.http_fetcher = SSRFSafeHTTPFetcher()
        self.browser_fetcher = BrowserFallbackFetcher()

    def process(self, url: str, company_name: str = "") -> ExtractedProfile:
        """Execute full layered enrichment pipeline."""
        # Step 1: HTTP Fetch
        doc = self.http_fetcher.fetch(url)

        # Step 2: Browser Fallback if HTTP was unusable and not blocked by SSRF
        if not doc.is_usable and (not doc.error or "SSRF" not in doc.error):
            logger.info(f"HTTP fetch was unusable for {url}. Attempting browser fallback...")
            browser_doc = self.browser_fetcher.fetch(url)
            if browser_doc.is_usable:
                doc = browser_doc

        if not doc.is_usable:
            return ExtractedProfile(
                target_url=url,
                fetch_method=doc.fetch_method,
                http_status=doc.status_code,
                resolved_ip=doc.resolved_ip,
                error=doc.error or f"Failed to extract usable HTML (status {doc.status_code})",
            )

        # Step 3: Clean, parse, and segment DOM
        return self._extract_features(doc, company_name)

    def _extract_features(self, doc: FetchedDocument, company_name: str) -> ExtractedProfile:
        soup = BeautifulSoup(doc.raw_html, "html.parser")

        # Decompose non-content tags
        for tag in soup(["script", "style", "nav", "footer", "header", "svg", "iframe", "noscript"]):
            tag.decompose()

        # 1. Title
        title = soup.title.string.strip() if (soup.title and soup.title.string) else ""

        # 2. Meta description & OpenGraph
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"].strip()
        else:
            og_tag = soup.find("meta", attrs={"property": "og:description"})
            if og_tag and og_tag.get("content"):
                meta_desc = og_tag["content"].strip()

        # 3. Headings
        headings: List[str] = []
        for h in soup.find_all(["h1", "h2", "h3"], limit=6):
            txt = h.get_text(strip=True)
            if txt and len(txt) > 3:
                headings.append(txt)

        # 4. Clean visible text (first 2500 characters)
        body = soup.find("body") or soup
        body_text = body.get_text(separator=" ", strip=True)
        # Collapse whitespace and control characters
        body_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', body_text)
        clean_text = re.sub(r'\s+', ' ', body_text).strip()[:2500]

        # 5. Extract fallback summary heuristics
        company_description = meta_desc or (clean_text[:300] + "..." if len(clean_text) > 300 else clean_text)
        key_offering = headings[0] if headings else (title or "Business services")

        # 6. Calculate extraction confidence score (0.0 to 1.0)
        confidence = 0.2  # base for successful fetch
        if title:
            confidence += 0.2
        if meta_desc:
            confidence += 0.3
        if headings:
            confidence += 0.2
        if len(clean_text) > 300:
            confidence += 0.1

        return ExtractedProfile(
            target_url=doc.url,
            fetch_method=doc.fetch_method,
            http_status=doc.status_code,
            resolved_ip=doc.resolved_ip,
            title=title,
            meta_description=meta_desc,
            headings=headings,
            clean_text=clean_text,
            company_description=company_description,
            key_offering=key_offering,
            confidence_score=round(min(confidence, 1.0), 2),
        )
