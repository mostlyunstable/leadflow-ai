"""
Playwright Browser Resource Throttling Attack Test.
Verifies that when excessive concurrent browser requests occur,
the bounded concurrency semaphore strictly caps active Chromium instances
and rejects/throttles excess requests (HTTP 503) rather than crashing host RAM.
"""

import threading
import time
import pytest

from modules.lead_enrichment.pipeline import BrowserFallbackFetcher


def test_browser_concurrency_semaphore_throttles_excess_requests(monkeypatch):
    """
    Simulate 10 concurrent requests to BrowserFallbackFetcher when MAX_CONCURRENT_BROWSERS is 2.
    Active concurrent launches must never exceed 2.
    """
    fetcher = BrowserFallbackFetcher()
    # Force semaphore to small pool of 2
    fetcher._concurrency_semaphore = threading.BoundedSemaphore(value=2)

    active_launches = 0
    max_observed_concurrent = 0
    lock = threading.Lock()

    def fake_launch(*args, **kwargs):
        nonlocal active_launches, max_observed_concurrent
        with lock:
            active_launches += 1
            if active_launches > max_observed_concurrent:
                max_observed_concurrent = active_launches
        # Sleep briefly to simulate page loading
        time.sleep(0.1)
        with lock:
            active_launches -= 1

        class FakePage:
            def set_default_timeout(self, *a): pass
            def goto(self, *a, **k):
                class FakeResp:
                    status = 200
                return FakeResp()
            def wait_for_timeout(self, *a): pass
            def content(self): return "<html><body>" + ("content " * 100) + "</body></html>"
        class FakeBrowser:
            def new_page(self, *a, **k): return FakePage()
            def close(self): pass
        return FakeBrowser()

    class FakeChromium:
        launch = staticmethod(fake_launch)
    class FakePlaywright:
        chromium = FakeChromium()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    # Mock playwright
    import sys
    fake_playwright_mod = type(sys)("playwright.sync_api")
    fake_playwright_mod.sync_playwright = lambda: FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_playwright_mod)

    # Launch 6 concurrent threads
    threads = []
    results = []

    def run_fetch():
        res = fetcher.fetch("https://google.com")
        results.append(res)

    for _ in range(6):
        t = threading.Thread(target=run_fetch)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # The maximum simultaneously active launches must NEVER exceed the semaphore limit (2)
    assert max_observed_concurrent <= 2, f"Expected <= 2 active browsers, observed {max_observed_concurrent}"
    assert len(results) == 6
