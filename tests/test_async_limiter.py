import asyncio
import logging
import time

import pytest

# Import the rate limiter
from async_limiter.async_limiter import DualRateLimiter

# Set up logging for tests
logging.basicConfig(level=logging.INFO)


# Helper for running timed tests
async def timed_execution(coro):
    """Run a coroutine and time its execution."""
    start = time.time()
    result = await coro
    duration = time.time() - start
    return result, duration


#########################
# Basic Initialization Tests
#########################


def test_initialization():
    """Test that the rate limiter initializes with correct parameters."""
    # Basic initialization
    limiter = DualRateLimiter(
        max_concurrent=5, max_requests=10, time_period=60, name="test"
    )

    assert limiter.max_concurrent == 5
    assert limiter.max_requests == 10
    assert limiter.time_period == 60
    assert limiter.name == "test"
    assert limiter._effective_max_requests == 9  # Conservative by default

    # Non-conservative initialization
    limiter = DualRateLimiter(
        max_concurrent=5, max_requests=10, time_period=60, conservative=False
    )
    assert limiter._effective_max_requests == 10


def test_invalid_initialization():
    """Test that invalid parameters raise appropriate exceptions."""
    # Test invalid max_concurrent
    with pytest.raises(ValueError, match="max_concurrent must be greater than 0"):
        DualRateLimiter(max_concurrent=0, max_requests=10, time_period=60)

    # Test invalid max_requests
    with pytest.raises(ValueError, match="max_requests must be greater than 0"):
        DualRateLimiter(max_concurrent=5, max_requests=0, time_period=60)

    # Test invalid time_period
    with pytest.raises(ValueError, match="time_period must be greater than 0"):
        DualRateLimiter(max_concurrent=5, max_requests=10, time_period=0)


#########################
# Concurrent Limit Tests
#########################


@pytest.mark.asyncio
async def test_concurrent_limit():
    """Test that the rate limiter enforces the concurrent limit."""
    max_concurrent = 3
    limiter = DualRateLimiter(
        max_concurrent=max_concurrent, max_requests=100, time_period=60
    )

    # Track acquired semaphores
    acquired = 0

    # Define a task that acquires and holds the semaphore
    async def acquire_and_hold():
        nonlocal acquired
        await limiter.acquire()
        acquired += 1
        # Hold it for a moment
        await asyncio.sleep(0.5)
        limiter.release()
        acquired -= 1

    # Start max_concurrent + 1 tasks
    tasks = [asyncio.create_task(acquire_and_hold()) for _ in range(max_concurrent + 1)]

    # Give some time for the first max_concurrent tasks to acquire
    await asyncio.sleep(0.1)

    # Verify that only max_concurrent were acquired
    assert acquired == max_concurrent

    # Let all tasks complete
    await asyncio.gather(*tasks)

    # Verify all were released
    assert acquired == 0


#########################
# Rate Limit Tests
#########################


@pytest.mark.asyncio
async def test_rate_limit():
    """Test that the rate limiter enforces the request rate limit."""
    # Create a rate limiter with tight limits for testing
    max_requests = 3
    time_period = 2  # seconds
    limiter = DualRateLimiter(
        max_concurrent=10,  # High enough to not interfere
        max_requests=max_requests,
        time_period=time_period,
        conservative=False,  # Use exact values for testing
    )

    # Make max_requests requests quickly (should not be rate limited)
    for _ in range(max_requests):
        await limiter.acquire()
        limiter.release()

    # The next request should be rate limited, timing roughly time_period
    async def timed_request():
        await limiter.acquire()
        limiter.release()

    # Time the execution of a rate-limited request
    _, duration = await timed_execution(timed_request())

    # Should be close to time_period (allowing some margin for execution overhead)
    assert 0.9 * time_period <= duration <= 1.3 * time_period


#########################
# Context Manager Tests
#########################


@pytest.mark.asyncio
async def test_context_manager():
    """Test the limiter's context manager functionality."""
    limiter = DualRateLimiter(max_concurrent=5, max_requests=10, time_period=1)

    # Use as context manager
    async with limiter:
        # Verify the semaphore was acquired
        assert limiter._metrics["current_requests"] == 1

    # Verify the semaphore was released
    assert limiter._metrics["current_requests"] == 0


#########################
# Decorator Tests
#########################


@pytest.mark.asyncio
async def test_decorator():
    """Test the limiter's decorator functionality."""
    limiter = DualRateLimiter(max_concurrent=5, max_requests=10, time_period=1)

    # Define a decorated function
    call_count = 0

    @limiter.limit()
    async def rate_limited_function():
        nonlocal call_count
        call_count += 1
        return "success"

    # Call the decorated function
    result = await rate_limited_function()

    # Verify it was called and returned correctly
    assert call_count == 1
    assert result == "success"
    assert limiter._metrics["total_requests"] == 1
    assert (
        limiter._metrics["current_requests"] == 0
    )  # Should be released after execution


#########################
# Exception Handling Tests
#########################


@pytest.mark.asyncio
async def test_exception_propagation():
    """Test that exceptions in the rate-limited code are properly propagated."""
    limiter = DualRateLimiter(max_concurrent=5, max_requests=10, time_period=1)

    # Define a function that raises an exception
    @limiter.limit()
    async def failing_function():
        raise ValueError("Test exception")

    # Call the function and check exception propagation
    with pytest.raises(ValueError, match="Test exception"):
        await failing_function()

    # Verify semaphore was released despite the exception
    assert limiter._metrics["current_requests"] == 0


@pytest.mark.asyncio
async def test_cancellation():
    """Test proper handling of task cancellation."""
    limiter = DualRateLimiter(max_concurrent=1, max_requests=1, time_period=5)

    # Make one request to reach the limit
    await limiter.acquire()

    # Start a task that will be rate-limited
    async def rate_limited_task():
        await limiter.acquire()
        limiter.release()

    task = asyncio.create_task(rate_limited_task())

    # Give it a moment to start waiting
    await asyncio.sleep(0.1)

    # Cancel the task
    task.cancel()

    # Wait for the task to complete (should raise CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await task

    # Release the initial request
    limiter.release()

    # Verify metrics are consistent
    assert limiter._metrics["current_requests"] == 0


#########################
# Metrics Tests
#########################


@pytest.mark.asyncio
async def test_metrics():
    """Test that metrics are properly tracked."""
    limiter = DualRateLimiter(max_concurrent=5, max_requests=5, time_period=1)

    # Make some requests
    for _ in range(3):
        await limiter.acquire()
        limiter.release()

    # Check metrics
    metrics = limiter.get_metrics()
    assert metrics["total_requests"] == 3
    assert metrics["current_requests"] == 0
    assert metrics["errors"] == 0

    # Reset metrics
    limiter.reset_metrics()
    metrics = limiter.get_metrics()
    assert metrics["total_requests"] == 0


@pytest.mark.asyncio
async def test_delay_metrics():
    """Test that delay metrics are properly tracked."""
    # Create a rate limiter with tight limits to trigger delays
    limiter = DualRateLimiter(max_concurrent=5, max_requests=2, time_period=1)

    # Make requests until we hit the rate limit
    await limiter.acquire()
    limiter.release()
    await limiter.acquire()
    limiter.release()

    # This one should be delayed
    await limiter.acquire()
    limiter.release()

    # Check metrics
    metrics = limiter.get_metrics()
    assert metrics["rate_limit_delays"] >= 1
    assert metrics["total_delay_time"] > 0


#########################
# Multiple Limiter Tests
#########################


@pytest.mark.asyncio
async def test_multiple_limiters():
    """Test that multiple rate limiters can be used independently."""
    limiter1 = DualRateLimiter(
        max_concurrent=1, max_requests=5, time_period=1, name="limiter1"
    )
    limiter2 = DualRateLimiter(
        max_concurrent=1, max_requests=5, time_period=1, name="limiter2"
    )

    # Acquire both limiters
    await limiter1.acquire()
    await limiter2.acquire()

    # Both should be acquired
    assert limiter1._metrics["current_requests"] == 1
    assert limiter2._metrics["current_requests"] == 1

    # Release both
    limiter1.release()
    limiter2.release()

    # Both should be released
    assert limiter1._metrics["current_requests"] == 0
    assert limiter2._metrics["current_requests"] == 0


if __name__ == "__main__":
    pytest.main(["-vs", __file__])
