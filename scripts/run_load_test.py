"""
LeadFlow AI — Production Load Testing Benchmark Script.
Simulates concurrent user load (10, 50, 100 concurrent virtual users)
against API endpoints using asyncio/httpx without sending real emails.
Measures requests/sec, p50, p95, p99 latency, and error rates.
"""

import asyncio
import time
import statistics
import sys
from typing import List, Dict, Any
import httpx


async def worker_task(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    request_count: int,
    latencies: List[float],
    errors: List[str],
):
    for _ in range(request_count):
        start = time.perf_counter()
        try:
            resp = await client.get(f"{base_url}/health/live", headers=headers, timeout=5.0)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if resp.status_code == 200:
                latencies.append(elapsed_ms)
            else:
                errors.append(f"HTTP {resp.status_code}")
        except Exception as e:
            errors.append(str(e))


async def run_stage(base_url: str, concurrency: int, requests_per_user: int) -> Dict[str, Any]:
    total_requests = concurrency * requests_per_user
    latencies: List[float] = []
    errors: List[str] = []

    print(f"\n--- Running Load Test: {concurrency} Concurrent Users ({total_requests} requests) ---")

    headers = {"User-Agent": "LeadFlow-LoadTest/2.0"}
    start_time = time.perf_counter()

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=concurrency + 10)) as client:
        tasks = [
            asyncio.create_task(
                worker_task(client, base_url, headers, requests_per_user, latencies, errors)
            )
            for _ in range(concurrency)
        ]
        await asyncio.gather(*tasks)

    total_time = time.perf_counter() - start_time
    rps = len(latencies) / total_time if total_time > 0 else 0

    if latencies:
        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]
    else:
        p50 = p95 = p99 = 0.0

    error_rate = (len(errors) / total_requests) * 100 if total_requests > 0 else 0

    result = {
        "concurrency": concurrency,
        "total_requests": total_requests,
        "completed": len(latencies),
        "errors": len(errors),
        "error_rate_pct": round(error_rate, 2),
        "total_time_sec": round(total_time, 2),
        "throughput_rps": round(rps, 1),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
    }

    print(f"Completed:  {result['completed']} / {total_requests}")
    print(f"Errors:     {result['errors']} ({result['error_rate_pct']}%)")
    print(f"Throughput: {result['throughput_rps']} req/sec")
    print(f"p50:        {result['latency_p50_ms']} ms")
    print(f"p95:        {result['latency_p95_ms']} ms")
    print(f"p99:        {result['latency_p99_ms']} ms")
    return result


async def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    print(f"Targeting LeadFlow API at: {base_url}")

    # Stage 1: 10 concurrent users
    await run_stage(base_url, concurrency=10, requests_per_user=10)

    # Stage 2: 50 concurrent users
    await run_stage(base_url, concurrency=50, requests_per_user=10)

    # Stage 3: 100 concurrent users
    await run_stage(base_url, concurrency=100, requests_per_user=10)


if __name__ == "__main__":
    asyncio.run(main())
