"""Client for the BitaxePID metrics server (GET /metrics)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

REQUEST_TIMEOUT = 10  # seconds


class MetricsError(Exception):
    """The metrics server could not be read."""


async def fetch_metrics(
    session: aiohttp.ClientSession, host: str, port: int
) -> dict[str, dict[str, Any]]:
    """Read http://<host>:<port>/metrics and return {mac_address: metrics}.

    The server answers {"endpoints": [ {...one miner...}, ... ]}. The list is
    empty until BitaxePID has completed its first tuning cycle, so an empty
    result is valid.
    """
    url = f"http://{host}:{port}/metrics"
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        ) as response:
            if response.status != 200:
                raise MetricsError(f"{url} answered HTTP {response.status}")
            # bitaxepid.py sends application/json, but don't depend on it.
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise MetricsError(f"Cannot reach {url}: {err!r}") from err
    except ValueError as err:
        raise MetricsError(f"{url} did not return JSON") from err

    endpoints = payload.get("endpoints") if isinstance(payload, dict) else None
    if not isinstance(endpoints, list):
        raise MetricsError(f"{url} did not return BitaxePID metrics")

    return {
        str(item["mac_address"]): item
        for item in endpoints
        if isinstance(item, dict) and item.get("mac_address")
    }
