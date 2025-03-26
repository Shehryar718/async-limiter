import asyncio
import logging
from typing import Tuple, cast
from unittest.mock import MagicMock

import aiohttp
import pytest
from aiohttp import ClientResponse, ClientSession
from aiohttp.client import RequestInfo

from async_limiter.async_limiter import DualRateLimiter

logger = logging.getLogger("integration_test")


class MockResponse:
    """Mock aiohttp response for testing."""

    def __init__(self, status=200, content=None, headers=None):
        self.status = status
        self._content = content or b"{}"
        self.headers = headers or {}

    async def json(self):
        import json

        return json.loads(self._content)

    async def read(self):
        return self._content

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def raise_for_status(self):
        if self.status >= 400:
            # Create an empty RequestInfo for the error
            request_info = cast(RequestInfo, MagicMock())  # Type cast to satisfy mypy
            history: Tuple[ClientResponse, ...] = tuple()  # Empty history tuple

            raise aiohttp.ClientResponseError(
                request_info=request_info,
                history=history,
                status=self.status,
                message=f"HTTP Error {self.status}",
            )


class MockClientSession:
    """Mock aiohttp ClientSession for testing."""

    def __init__(self, responses=None, delay=0):
        self.responses = responses or []
        self.response_index = 0
        self.calls = []
        self.delay = delay

    async def get(self, url, **kwargs):
        await asyncio.sleep(self.delay)  # Simulate network delay
        self.calls.append(("get", url, kwargs))

        if self.response_index < len(self.responses):
            response = self.responses[self.response_index]
            self.response_index += 1
            return response
        return MockResponse(status=200)

    async def post(self, url, **kwargs):
        await asyncio.sleep(self.delay)  # Simulate network delay
        self.calls.append(("post", url, kwargs))

        if self.response_index < len(self.responses):
            response = self.responses[self.response_index]
            self.response_index += 1
            return response
        return MockResponse(status=200)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class ApiClient:
    """Example API client that uses the rate limiter."""

    def __init__(self, base_url="https://api.example.com", session=None):
        self.base_url = base_url
        self.session = session

        # Create a rate limiter for this API
        # Assume API limits: 5 concurrent, 10 requests per minute
        self.rate_limiter = DualRateLimiter(
            max_concurrent=5, max_requests=10, time_period=60, name="example_api"
        )

    async def get_data(self, path, params=None):
        """Make a rate-limited GET request."""
        url = f"{self.base_url}/{path}"

        # Use the rate limiter as a context manager
        async with self.rate_limiter:
            if self.session:
                response = await self.session.get(url, params=params)
                return response
            else:
                async with ClientSession() as session:
                    response = await session.get(url, params=params)
                    data = await response.json()
                    return data

    @property
    def metrics(self):
        """Get rate limiter metrics."""
        return self.rate_limiter.get_metrics()


#########################
# Integration Tests
#########################


@pytest.mark.asyncio
async def test_api_client_rate_limiting():
    """Test that the API client properly rate limits requests."""
    # Create a mock session with controlled responses
    mock_session = MockClientSession(
        responses=[
            MockResponse(status=200, content=b'{"id": 1}'),
            MockResponse(status=200, content=b'{"id": 2}'),
            MockResponse(status=200, content=b'{"id": 3}'),
        ],
        delay=0.05,  # Small delay to simulate network
    )

    # Create API client with mock session
    api_client = ApiClient(session=mock_session)

    # Use a smaller time period to speed up the test
    api_client.rate_limiter = DualRateLimiter(
        max_concurrent=5,
        max_requests=10,
        time_period=1,  # 1 second instead of 60
        name="test_api",
    )

    # Make concurrent requests
    test_range = 15  # More than our rate limit
    tasks = [api_client.get_data(f"resource/{i}") for i in range(test_range)]

    # Execute all tasks concurrently
    await asyncio.gather(*tasks)

    # Verify metrics show correct rate limiting
    metrics = api_client.metrics
    assert metrics["total_requests"] == test_range
    assert metrics["rate_limit_delays"] > 0  # Should have rate limited at least once

    # Verify all calls were made (but not necessarily in order)
    assert len(mock_session.calls) == test_range

    # Create a set of all expected resource paths
    expected_resources = {f"resource/{i}" for i in range(test_range)}

    # Check that all resources were requested (regardless of order)
    actual_resources = set()
    for method, url, _ in mock_session.calls:
        assert method == "get"  # All should be GET requests

        # Extract the resource path from the URL
        resource_path = url.split("/")[-2] + "/" + url.split("/")[-1]
        actual_resources.add(resource_path)

    # Verify all expected resources were requested
    assert expected_resources == actual_resources


@pytest.mark.asyncio
async def test_api_client_concurrent_limiting():
    """Test that the API client limits concurrent requests."""
    # Track when requests are active
    active_requests = 0
    max_active = 0

    # Create a semaphore to synchronize the test
    ready_sem = asyncio.Semaphore(0)

    async def delayed_mock_get(url, **kwargs):
        nonlocal active_requests, max_active

        # Increment active counter
        active_requests += 1
        max_active = max(max_active, active_requests)

        # Signal that we're active
        ready_sem.release()

        # Simulate a slow API call
        await asyncio.sleep(0.5)

        # Decrement active counter
        active_requests -= 1

        return MockResponse(status=200, content=b'{"result": "ok"}')

    # Create a mock session with our custom method
    mock_session = MagicMock()
    mock_session.get = delayed_mock_get

    # Create API client with lower concurrent limit
    api_client = ApiClient(session=mock_session)
    api_client.rate_limiter = DualRateLimiter(
        max_concurrent=3,  # Limit to 3 concurrent
        max_requests=100,  # High enough to not interfere
        time_period=1,
        name="test_concurrent",
    )

    # Start more tasks than the concurrent limit
    num_tasks = 10
    tasks = [
        asyncio.create_task(api_client.get_data(f"resource/{i}"))
        for i in range(num_tasks)
    ]

    # Wait for the max concurrent tasks to become active
    for _ in range(api_client.rate_limiter.max_concurrent):
        await ready_sem.acquire()

    # Allow some time for any potential additional tasks to start
    await asyncio.sleep(0.2)

    # Verify we didn't exceed the concurrent limit
    assert max_active <= api_client.rate_limiter.max_concurrent

    # Let all tasks complete
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_api_error_handling():
    """Test that errors from the API are properly handled."""
    # Create a mock session with an error response
    mock_session = MockClientSession(
        responses=[
            MockResponse(status=429, content=b'{"error": "Too Many Requests"}'),
        ]
    )

    # Create API client with mock session
    api_client = ApiClient(session=mock_session)

    # Create a rate-limited function that handles errors
    @api_client.rate_limiter.limit()
    async def fetch_with_retry():
        try:
            response = await mock_session.get("resource/1")
            response.raise_for_status()
            return await response.json()
        except aiohttp.ClientResponseError as e:
            if e.status == 429:
                # Simulate retrying after a 429 error
                await asyncio.sleep(0.1)
                # For this test, just return a mock success response
                return {"retried": True}
            raise

    # Call the function
    result = await fetch_with_retry()

    # Verify we got the retry response
    assert result == {"retried": True}

    # Verify metrics
    assert api_client.rate_limiter._metrics["total_requests"] == 1
    assert (
        api_client.rate_limiter._metrics["current_requests"] == 0
    )  # Should be released


if __name__ == "__main__":
    pytest.main(["-vs", __file__])
