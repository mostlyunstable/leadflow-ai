"""
Concurrency and Load Performance Benchmark Tests.
Simulates 10, 50, and 100 concurrent virtual requests against FastAPI ASGI application
measuring throughput, p95 latency, and zero error rates.
"""

import asyncio
import time
import statistics
import pytest
import httpx
from main import app


@pytest.mark.asyncio
async def test_concurrent_asgi_load_benchmark():
    """Execute concurrent user load tests through ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    stages = [10, 50, 100]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for concurrency in stages:
            requests_per_user = 5
            latencies = []
            errors = []

            async def user_task():
                for _ in range(requests_per_user):
                    t0 = time.perf_counter()
                    try:
                        resp = await client.get("/health/live")
                        dt = (time.perf_counter() - t0) * 1000.0
                        if resp.status_code == 200:
                            latencies.append(dt)
                        else:
                            errors.append(resp.status_code)
                    except Exception as e:
                        errors.append(str(e))

            tasks = [asyncio.create_task(user_task()) for _ in range(concurrency)]
            await asyncio.gather(*tasks)

            assert len(errors) == 0, f"Encountered errors at concurrency {concurrency}: {errors}"
            assert len(latencies) == concurrency * requests_per_user
            latencies.sort()
            p95 = latencies[int(len(latencies) * 0.95)]
            # Verify p95 is healthy (< 100ms in-process)
            assert p95 < 100.0
