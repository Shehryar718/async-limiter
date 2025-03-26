#!/usr/bin/env python3
"""
Example API client using the DualRateLimiter.

This example demonstrates how to use the rate limiter with a real API
by creating a client for the JSONPlaceholder API.

Usage:
    python api_client.py
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, TypeAlias, Union

from aiohttp import ClientSession

from async_limiter import DualRateLimiter

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("example")

# Define API result type alias
ApiResult: TypeAlias = Union[Dict[str, Any], List[Dict[str, Any]]]


class JsonPlaceholderClient:
    """
    Client for the JSONPlaceholder API with rate limiting.

    This example client enforces a maximum of 5 concurrent requests
    and 10 requests per 5 seconds (artificially low for demonstration).
    """

    def __init__(self, base_url: str = "https://jsonplaceholder.typicode.com"):
        self.base_url = base_url

        # Create a rate limiter
        self.rate_limiter = DualRateLimiter(
            max_concurrent=5,
            max_requests=10,
            time_period=5.0,  # 5 seconds
            name="jsonplaceholder",
        )

    async def get_posts(self) -> List[Dict[str, Any]]:
        """Get all posts."""
        return await self._get("posts")

    async def get_post(self, post_id: int) -> Dict[str, Any]:
        """Get a specific post by ID."""
        return await self._get(f"posts/{post_id}")

    async def get_comments(self, post_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get comments, optionally filtered by post ID."""
        if post_id:
            return await self._get(f"posts/{post_id}/comments")
        return await self._get("comments")

    async def get_users(self) -> List[Dict[str, Any]]:
        """Get all users."""
        return await self._get("users")

    async def _get(self, path: str) -> Any:
        """
        Make a rate-limited GET request to the API.

        This method uses the rate limiter as a context manager to ensure
        we don't exceed API rate limits.
        """
        url = f"{self.base_url}/{path}"

        # Use the rate limiter as a context manager
        async with self.rate_limiter:
            logger.info(f"Making request to {url}")

            async with ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    return await response.json()

    @property
    def metrics(self) -> Dict[str, Any]:
        """Get current rate limiter metrics."""
        return self.rate_limiter.get_metrics()


async def print_metrics(client: JsonPlaceholderClient) -> None:
    """Print the current metrics from the client."""
    metrics = client.metrics
    print("\n=== Rate Limiter Metrics ===")
    print(f"Total Requests: {metrics['total_requests']}")
    print(f"Current Concurrent Requests: {metrics['current_requests']}")
    print(f"Rate Limit Delays: {metrics['rate_limit_delays']}")
    print(f"Total Delay Time: {metrics['total_delay_time']:.2f}s")
    print(f"Errors: {metrics['errors']}")
    print("===========================\n")


async def main():
    """
    Main example function that demonstrates using the rate limiter.

    This will make multiple API requests in parallel, which will be
    automatically rate limited according to our configuration.
    """
    # Create the API client
    client = JsonPlaceholderClient()

    # Fetch data about posts 1-20
    logger.info("Fetching posts and their comments...")

    # Start measuring time
    start_time = time.time()

    # Make many requests in parallel - these will be rate limited
    post_tasks: List[asyncio.Task[ApiResult]] = []
    for post_id in range(1, 21):
        # Fetch both the post and its comments, wrapping each in a task
        post_tasks.append(asyncio.create_task(client.get_post(post_id)))
        post_tasks.append(asyncio.create_task(client.get_comments(post_id)))

    # Execute all requests concurrently (but rate limited)
    post_results = await asyncio.gather(*post_tasks)

    end_time = time.time()

    # Print results
    logger.info(
        f"Fetched {len(post_results)} resources in {end_time - start_time:.2f} seconds"
    )

    # Print rate limiter metrics
    await print_metrics(client)

    # Fetch all users
    logger.info("Fetching all users...")
    users = await client.get_users()
    logger.info(f"Fetched {len(users)} users")

    # Final metrics
    await print_metrics(client)


if __name__ == "__main__":
    asyncio.run(main())
