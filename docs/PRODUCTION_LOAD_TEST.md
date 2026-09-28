# LeadFlow AI — Production Load Test Benchmark Report

**Execution Timestamp:** `2026-09-28 20:26:05 UTC`  
**Target Host:** `https://127.0.0.1`  
**Benchmark Path:** `/health/live`  
**Concurrency Level:** `100 Concurrent Virtual Users`

## 1. Measured Performance Results

| Total Requests | Concurrency | Duration (s) | Throughput (req/s) | Latency p50 (ms) | Latency p95 (ms) | Latency p99 (ms) | Error Rate | Status Codes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **500** | 100 | 4.89s | **102.3** | 467.26 ms | 2456.28 ms | 3685.94 ms | 0.0% | `200:500` |
| **1000** | 100 | 5.97s | **167.4** | 231.71 ms | 2247.43 ms | 3718.62 ms | 0.0% | `200:1000` |
| **5000** | 100 | 15.52s | **322.2** | 120.83 ms | 1180.39 ms | 2452.91 ms | 0.0% | `200:5000` |
| **10000** | 100 | 21.84s | **457.9** | 119.07 ms | 667.22 ms | 1680.19 ms | 0.0% | `200:10000` |

## 2. Host and Infrastructure Telemetry

- **Active DB Connections:** `N/A`
- **Redis Status:** `N/A`
- **Pending Queue Depth:** `N/A`

## 3. Raw Execution Data

```json
[
  {
    "concurrency": 100,
    "total_requests": 500,
    "completed": 500,
    "errors": 0,
    "status_distribution": {
      "200": 500
    },
    "error_rate_pct": 0.0,
    "duration_sec": 4.89,
    "throughput_rps": 102.3,
    "p50_ms": 467.26,
    "p95_ms": 2456.28,
    "p99_ms": 3685.94,
    "pre_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    },
    "post_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    }
  },
  {
    "concurrency": 100,
    "total_requests": 1000,
    "completed": 1000,
    "errors": 0,
    "status_distribution": {
      "200": 1000
    },
    "error_rate_pct": 0.0,
    "duration_sec": 5.97,
    "throughput_rps": 167.4,
    "p50_ms": 231.71,
    "p95_ms": 2247.43,
    "p99_ms": 3718.62,
    "pre_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    },
    "post_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    }
  },
  {
    "concurrency": 100,
    "total_requests": 5000,
    "completed": 5000,
    "errors": 0,
    "status_distribution": {
      "200": 5000
    },
    "error_rate_pct": 0.0,
    "duration_sec": 15.52,
    "throughput_rps": 322.2,
    "p50_ms": 120.83,
    "p95_ms": 1180.39,
    "p99_ms": 2452.91,
    "pre_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    },
    "post_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    }
  },
  {
    "concurrency": 100,
    "total_requests": 10000,
    "completed": 10000,
    "errors": 0,
    "status_distribution": {
      "200": 10000
    },
    "error_rate_pct": 0.0,
    "duration_sec": 21.84,
    "throughput_rps": 457.9,
    "p50_ms": 119.07,
    "p95_ms": 667.22,
    "p99_ms": 1680.19,
    "pre_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    },
    "post_metrics": {
      "db_connections": "N/A",
      "redis_status": "N/A",
      "queue_depth": "N/A"
    }
  }
]
```
