"""
Integration Tests for Layered Enrichment Pipeline & SSRF Protection.
Tests:
1. Normal HTML parsing and feature extraction.
2. SSRF enforcement blocking internal and cloud metadata IPs.
3. WAF / Anti-bot challenge detection.
4. Confidence score computation.
"""

from unittest.mock import patch, MagicMock
import pytest

from modules.lead_enrichment.pipeline import (
    EnrichmentPipeline, SSRFSafeHTTPFetcher, FetchedDocument
)


def test_enrichment_feature_extraction_on_html():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Stripe: Financial Infrastructure for the Internet</title>
        <meta name="description" content="Stripe is a suite of APIs powering online payment processing.">
    </head>
    <body>
        <h1>Payments Infrastructure</h1>
        <h2>Millions of businesses rely on Stripe</h2>
        <p>From startups to Fortune 500 companies, businesses use Stripe software to accept payments.</p>
    </body>
    </html>
    """

    pipeline = EnrichmentPipeline()

    mock_doc = FetchedDocument(
        url="https://stripe.com",
        final_url="https://stripe.com",
        resolved_ip="199.60.103.106",
        fetch_method="http",
        status_code=200,
        raw_html=sample_html,
        is_usable=True,
    )

    with patch.object(pipeline.http_fetcher, "fetch", return_value=mock_doc):
        profile = pipeline.process("https://stripe.com", company_name="Stripe")

        assert "Stripe" in profile.title
        assert "suite of APIs" in profile.meta_description
        assert len(profile.headings) >= 2
        assert "Payments Infrastructure" in profile.headings[0]
        assert profile.confidence_score >= 0.7


@pytest.mark.parametrize("blocked_url", [
    "http://127.0.0.1:8000/api",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/secrets",
    "http://localhost:5432",
])
def test_ssrf_fetcher_strictly_blocks_dangerous_targets(blocked_url):
    fetcher = SSRFSafeHTTPFetcher()
    doc = fetcher.fetch(blocked_url)

    assert doc.is_usable is False
    assert doc.status_code == 400
    assert "SSRF" in (doc.error or "")


def test_anti_bot_detection_flags_unusable_http():
    cloudflare_challenge = """
    <html>
    <head><title>Just a moment...</title></head>
    <body>
        <h1>Attention Required! | Cloudflare</h1>
        <p>Please complete the security check to access example.com</p>
    </body>
    </html>
    """

    fetcher = SSRFSafeHTTPFetcher()
    is_usable = fetcher._evaluate_usability(200, cloudflare_challenge)
    assert is_usable is False  # Should flag for browser fallback
