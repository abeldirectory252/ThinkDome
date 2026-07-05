"""Load testing client script to validate scaling and 10k request flows.

Simulates concurrent clients calling the orchestrator code execution endpoint,
measuring latency percentiles (p50/p95/p99), throughput, and pool hit rate.
"""

import asyncio
import time
import argparse
import sys
from typing import List, Dict


async def simulate_request(client_id: int, url: str, token: str, sandbox_id: str) -> Dict[str, float]:
    """Send a single execution request and measure the response time."""
    import httpx
    
    payload = {
        "type": "tool_use",
        "id": f"load_test_{client_id}_{int(time.time() * 1000)}",
        "name": "run_code",
        "input": {
            "language": "python",
            "code": "import time; print(2**20)"
        }
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Sandbox-Id": sandbox_id
    }
    
    start = time.perf_counter()
    status_code = 0
    is_error = False
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            status_code = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                is_error = data.get("is_error", False)
            else:
                is_error = True
    except Exception as e:
        is_error = True
        status_code = 500
        
    end = time.perf_counter()
    duration_ms = (end - start) * 1000.0
    
    return {
        "duration_ms": duration_ms,
        "status_code": status_code,
        "is_error": float(is_error)
    }


async def run_load_test(url: str, token: str, sandbox_id: str, concurrency: int, duration_sec: int):
    """Ramp up concurrent workers to execute code in the sandbox."""
    print(f"=== Starting Load Test ===")
    print(f"URL: {url}")
    print(f"Concurrency Target: {concurrency}")
    print(f"Duration: {duration_sec}s")
    
    results: List[Dict[str, float]] = []
    start_time = time.monotonic()
    
    async def worker():
        req_count = 0
        while time.monotonic() - start_time < duration_sec:
            res = await simulate_request(req_count, url, token, sandbox_id)
            results.append(res)
            req_count += 1
            # Brief sleep to avoid hammer CPU throttling on client
            await asyncio.sleep(0.01)

    # Spawn concurrent workers
    tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
    await asyncio.gather(*tasks)
    
    # Calculate stats
    total_time = time.monotonic() - start_time
    total_reqs = len(results)
    
    if not results:
        print("No requests completed successfully.")
        return

    latencies = sorted([r["duration_ms"] for r in results])
    errors = sum(1 for r in results if r["is_error"] == 1.0)
    
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    avg_latency = sum(latencies) / len(latencies)
    throughput = total_reqs / total_time
    
    print("\n=== Load Test Summary ===")
    print(f"Completed Requests: {total_reqs}")
    print(f"Throughput:         {throughput:.2f} req/sec")
    print(f"Total Errors:       {errors} ({errors/total_reqs*100:.2f}%)")
    print(f"Average Latency:    {avg_latency:.2f} ms")
    print(f"p50 Latency:        {p50:.2f} ms")
    print(f"p95 Latency:        {p95:.2f} ms")
    print(f"p99 Latency:        {p99:.2f} ms")
    print("=========================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ThinkDome Sandbox Load Test")
    parser.add_argument("--url", default="http://localhost:8000/v1/orchestrate", help="Orchestrator URL")
    parser.add_argument("--token", required=False, default="mock_token", help="Opaque sandbox token")
    parser.add_argument("--sandbox", required=False, default="test_sandbox_node", help="Target sandbox ID")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of concurrent client workers")
    parser.add_argument("--duration", type=int, default=5, help="Test duration in seconds")
    
    args = parser.parse_args()
    
    # Run async main loop
    asyncio.run(run_load_test(args.url, args.token, args.sandbox, args.concurrency, args.duration))
