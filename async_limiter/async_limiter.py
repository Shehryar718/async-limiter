import asyncio
import functools
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

# Set up logging with appropriate level
logger = logging.getLogger("rate_limiter")


class DualRateLimiter:
    """
    A custom rate limiter that enforces both:
    1. Maximum concurrent requests at any given time
    2. Maximum number of requests within a time period

    This is useful for APIs that have both types of rate limits.

    Usage:
        # Create a rate limiter with 5 concurrent requests and 100 requests per minute
        limiter = DualRateLimiter(max_concurrent=5, max_requests=100, time_period=60)

        # Use as a context manager
        async with limiter:
            await api_call()

        # Or use acquire/release manually
        await limiter.acquire()
        try:
            await api_call()
        finally:
            limiter.release()

        # Or use as a decorator
        @limiter.limit()
        async def my_function():
            await api_call()
    """

    def __init__(
        self,
        max_concurrent: int,
        max_requests: int,
        time_period: float,
        conservative: bool = True,
        name: Optional[str] = None,
    ):
        """
        Initialize the rate limiter.

        Args:
            max_concurrent: Maximum number of concurrent requests allowed
            max_requests: Maximum number of requests allowed in the time period
            time_period: Time period in seconds for the request limit
            conservative: If True, use a more conservative limit to avoid edge cases
            name: Optional name for this rate limiter instance (useful for logging)
        """
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be greater than 0")
        if max_requests <= 0:
            raise ValueError("max_requests must be greater than 0")
        if time_period <= 0:
            raise ValueError("time_period must be greater than 0")

        self.max_concurrent = max_concurrent
        self.max_requests = max_requests
        self.time_period = time_period
        self.name = name or "default"

        # Make the rate limit more conservative to avoid edge cases
        # For example, if API allows 5 requests per minute, we'll allow 4
        self._effective_max_requests = (
            max_requests if not conservative else max(1, max_requests - 1)
        )

        # Semaphore to limit concurrent requests
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # Queue to track request timestamps
        self.request_times: Deque[float] = deque()

        # Lock to protect the request_times queue during concurrent access
        self.lock = asyncio.Lock()

        # Metrics
        self._metrics = {
            "total_requests": 0,
            "current_requests": 0,
            "rate_limit_delays": 0,
            "total_delay_time": 0.0,
            "errors": 0,
        }

        logger.info(
            f"DualRateLimiter '{self.name}' initialized with: concurrent={max_concurrent}, "
            f"requests={self._effective_max_requests}/{time_period}s "
            f"(conservative from original {max_requests})"
        )

    async def _clean_old_requests(self):
        """Remove request timestamps that are outside the time period."""
        current_time = time.time()
        cutoff_time = current_time - self.time_period

        old_count = len(self.request_times)
        while self.request_times and self.request_times[0] < cutoff_time:
            self.request_times.popleft()
        new_count = len(self.request_times)

        if old_count != new_count and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"[{self.name}] Cleaned {old_count - new_count} old requests, {new_count} remaining"
            )

    async def acquire(self):
        """
        Acquire permission to make a request.
        This blocks until both rate limits allow the request.

        Raises:
            asyncio.CancelledError: If the task is cancelled while waiting
            RuntimeError: If other unexpected errors occur during acquisition
        """
        # First, acquire the semaphore to ensure we don't exceed concurrent limits
        try:
            await self.semaphore.acquire()
            self._metrics["current_requests"] += 1
        except asyncio.CancelledError:
            logger.warning(
                f"[{self.name}] Request cancelled while waiting for semaphore"
            )
            raise
        except Exception as e:
            self._metrics["errors"] += 1
            logger.error(f"[{self.name}] Error acquiring semaphore: {str(e)}")
            raise RuntimeError(
                f"Failed to acquire rate limit semaphore: {str(e)}"
            ) from e

        try:
            # Then, check and wait for the time-based rate limit
            delay_start = None
            while True:
                async with self.lock:
                    await self._clean_old_requests()
                    current_count = len(self.request_times)

                    # If we have room for another request within the time period
                    if current_count < self._effective_max_requests:
                        # Record this request's timestamp
                        self.request_times.append(time.time())
                        self._metrics["total_requests"] += 1

                        # Record delay metrics if there was a delay
                        if delay_start is not None:
                            delay_time = time.time() - delay_start
                            self._metrics["total_delay_time"] += delay_time
                            logger.debug(
                                f"[{self.name}] Request allowed after waiting {delay_time:.2f}s"
                            )

                        return
                    else:
                        # Calculate wait time until the oldest request expires
                        oldest_time = self.request_times[0]
                        wait_time = oldest_time + self.time_period - time.time()

                        # Record that we hit the rate limit
                        if delay_start is None:
                            delay_start = time.time()
                            self._metrics["rate_limit_delays"] += 1

                        logger.info(
                            f"[{self.name}] Rate limit reached ({current_count}/{self._effective_max_requests}), "
                            f"waiting {wait_time:.2f}s for a slot to open"
                        )

                # Wait until the oldest request expires
                async with self.lock:
                    if self.request_times:
                        oldest_request = self.request_times[0]
                        # Add a small buffer (0.1 second) to be safe
                        wait_time = max(
                            0.1, oldest_request + self.time_period - time.time() + 0.1
                        )
                    else:
                        wait_time = 0.1

                try:
                    await asyncio.sleep(wait_time)
                except asyncio.CancelledError:
                    logger.warning(
                        f"[{self.name}] Request cancelled while waiting for rate limit"
                    )
                    self.semaphore.release()
                    self._metrics["current_requests"] = max(
                        0, self._metrics["current_requests"] - 1
                    )
                    raise
        except Exception as e:
            # If something goes wrong, make sure we release the semaphore
            self._metrics["errors"] += 1
            logger.error(f"[{self.name}] Error in rate limiter: {str(e)}")
            self.semaphore.release()
            self._metrics["current_requests"] = max(
                0, self._metrics["current_requests"] - 1
            )
            raise RuntimeError(f"Rate limiter error: {str(e)}") from e

    def release(self):
        """Release the semaphore to allow another concurrent request."""
        try:
            self.semaphore.release()
            self._metrics["current_requests"] = max(
                0, self._metrics["current_requests"] - 1
            )
        except ValueError:
            # This means we're releasing more than we acquired
            logger.warning(
                f"[{self.name}] Attempted to release rate limiter that wasn't acquired"
            )

    async def __aenter__(self):
        """Context manager entry - acquires permission to make a request."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - releases the semaphore."""
        self.release()

    def limit(self):
        """
        Decorator for rate limiting async functions.

        Usage:
            @rate_limiter.limit()
            async def my_function():
                pass
        """

        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                async with self:
                    return await func(*args, **kwargs)

            return wrapper

        return decorator

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics for this rate limiter.

        Returns:
            Dictionary with metrics including total requests, current concurrent
            requests, rate limit delays, etc.
        """
        return {
            **self._metrics,
            "current_queue_size": len(self.request_times),
            "max_concurrent": self.max_concurrent,
            "max_requests_per_period": self._effective_max_requests,
            "time_period": self.time_period,
        }

    def reset_metrics(self):
        """Reset all metrics counters except for current state values."""
        current_requests = self._metrics["current_requests"]
        self._metrics = {
            "total_requests": 0,
            "current_requests": current_requests,  # Preserve this value
            "rate_limit_delays": 0,
            "total_delay_time": 0.0,
            "errors": 0,
        }
