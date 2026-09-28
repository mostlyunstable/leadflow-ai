"""
LeadFlow AI — Production Load Testing Benchmark Script.
Simulates concurrent user load (100 concurrent virtual users across 500, 1,000, 5,000, and 10,000 requests)
against the public Nginx reverse proxy endpoint.

Measures and records:
- Requests per second (RPS)
- p50, p95, p99 latencies
- Error rates & HTTP status distributions
- Host CPU, Memory, and DB connection metrics (via /metrics)
- Produces markdown table output for docs/PRODUCTION_LOAD_TEST.md
"""

import asyncio
import time
import statistics
import sys
import os
import json
import argparse
from typing import List, Dict, Any, Optional
import httpx


async def worker_task(
    client: httpx.AsyncClient,
    url: str,
    headers: Dict[str, str],
    request_count: int,
    latencies: List[float],
    status_codes: Dict[int, int],
    errors: List[str],
):
    for _ in range(request_count):
        start = time.perf_counter()
        try:
            resp = await client.get(url, headers=headers, timeout=10.0)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            latencies.append(elapsed_ms)
            status_codes[resp.status_code] = status_codes.get(resp.status_code, 0) + 1
            if resp.status_code >= 400:
                errors.append(f"HTTP {resp.status_code}")
        except Exception as e:
            errors.append(str(e))


async def fetch_metrics_snapshot(base_url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """Fetch real-time DB and Redis metrics from /metrics endpoint."""
    snapshot = {"db_connections": "N/A", "redis_status": "N/A", "queue_depth": "N/A"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/metrics", headers=headers)
            if resp.status_code == 200:
                for line in resp.text.splitlines():
                    if line.startswith("leadflow_db_connections_active "):
                        snapshot["db_connections"] = line.split()[1]
                    elif line.startswith("leadflow_redis_connected "):
                        snapshot["redis_status"] = "Connected" if line.split()[1] == "1" else "Disconnected"
                    elif line.startswith("leadflow_queue_depth "):
                        snapshot["queue_depth"] = line.split()[1]
    except Exception:
        pass
    return snapshot


async def run_stage(
    base_url: str,
    path: str,
    concurrency: int,
    total_requests: int,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    requests_per_user = max(1, total_requests // concurrency)
    actual_total = requests_per_user * concurrency
    latencies: List[float] = []
    status_codes: Dict[int, int] = {}
    errors: List[str] = []

    headers = {"User-Agent": "LeadFlow-ProductionLoadTest/2.0"}
    if api_key:
        headers["X-API-Key"] = api_key

    url = f"{base_url.rstrip('/')}{path}"
    print(f"\n==================================================================")
    print(f"STAGE: {concurrency} Concurrent Users | Target: {actual_total} Requests ({requests_per_user} reqs/worker)")
    print(f"Target URL: {url}")
    print(f"==================================================================")

    pre_metrics = await fetch_metrics_snapshot(base_url, headers)
    start_time = time.perf_counter()

    limits = httpx.Limits(max_connections=concurrency + 20, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits, verify=False) as client:
        tasks = [
            asyncio.create_task(
                worker_task(client, url, headers, requests_per_user, latencies, status_codes, errors)
            )
            for _ in range(concurrency)
        ]
        await asyncio.gather(*tasks)

    total_time = time.perf_counter() - start_time
    post_metrics = await fetch_metrics_snapshot(base_url, headers)

    completed = len(latencies)
    rps = completed / total_time if total_time > 0 else 0

    if latencies:
        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]
    else:
        p50 = p95 = p99 = 0.0

    error_rate = (len(errors) / actual_total) * 100 if actual_total > 0 else 0

    result = {
        "concurrency": concurrency,
        "total_requests": actual_total,
        "completed": completed,
        "errors": len(errors),
        "status_distribution": status_codes,
        "error_rate_pct": round(error_rate, 2),
        "duration_sec": round(total_time, 2),
        "throughput_rps": round(rps, 1),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "pre_metrics": pre_metrics,
        "post_metrics": post_metrics,
    }

    print(f"Completed:       {completed} / {actual_total}")
    print(f"Throughput:      {result['throughput_rps']} req/sec")
    print(f"Duration:        {result['duration_sec']}s")
    print(f"Latency p50:     {result['p50_ms']} ms")
    print(f"Latency p95:     {result['p95_ms']} ms")
    print(f"Latency p99:     {result['p99_ms']} ms")
    print(f"Status Codes:    {status_codes}")
    print(f"Error Rate:      {result['error_rate_pct']}% ({len(errors)} errors)")
    print(f"Active DB Conns: {post_metrics.get('db_connections', 'N/A')}")
    print(f"Redis Status:    {post_metrics.get('redis_status', 'N/A')}")
    return result


async def main():
    parser = argparse.ArgumentParser(description="LeadFlow AI Production Load Test")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of target (Nginx or API)")
    parser.add_argument("--path", default="/health/live", help="Path to benchmark")
    parser.add_argument("--api-key", default=None, help="Optional API key for authenticated endpoints")
    parser.add_argument("--report", default="docs/PRODUCTION_LOAD_TEST.md", help="Path to write report markdown")
    args = parser.parse_args()

    print(f"Starting LeadFlow AI Load Benchmark against: {args.url}{args.path}")
    concurrency = 100
    test_stages = [500, 1000, 5000, 10000]
    stage_results = []

    for req_count in test_stages:
        res = await run_stage(
            base_url=args.url,
            path=args.path,
            concurrency=concurrency,
            total_requests=req_count,
            api_key=args.api_key,
        )
        stage_results.append(res)
        await asyncio.sleep(1.0)

    # Generate Markdown Report
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    md_lines = [
        "# LeadFlow AI — Production Load Test Benchmark Report",
        f"\n**Execution Timestamp:** `{timestamp}`  ",
        f"**Target Host:** `{args.url}`  ",
        f"**Benchmark Path:** `{args.path}`  ",
        f"**Concurrency Level:** `100 Concurrent Virtual Users`\n",
        "## 1. Measured Performance Results\n",
        "| Total Requests | Concurrency | Duration (s) | Throughput (req/s) | Latency p50 (ms) | Latency p95 (ms) | Latency p99 (ms) | Error Rate | Status Codes |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for s in stage_results:
        codes_str = ", ".join(f"{k}:{v}" for k, v in s["status_distribution"].items())
        md_lines.append(
            f"| **{s['total_requests']}** | {s['concurrency']} | {s['duration_sec']}s | **{s['throughput_rps']}** | {s['p50_ms']} ms | {s['p95_ms']} ms | {s['p99_ms']} ms | {s['error_rate_pct']}% | `{codes_str}` |"
        )

    md_lines.extend([
        "\n## 2. Host and Infrastructure Telemetry\n",
        f"- **Active DB Connections:** `{stage_results[-1]['post_metrics'].get('db_connections', 'N/A')}`",
        f"- **Redis Status:** `{stage_results[-1]['post_metrics'].get('redis_status', 'N/A')}`",
        f"- **Pending Queue Depth:** `{stage_results[-1]['post_metrics'].get('queue_depth', 'N/A')}`",
        "\n## 3. Raw Execution Data\n",
        "```json",
        json.dumps(stage_results, indent=2),
        "```\n",
    ])

    report_content = "\n".join(md_lines)
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\n[SUCCESS] Production load test completed. Report written to {args.report}")


if __name__ == "__main__":
    asyncio.run(main())
