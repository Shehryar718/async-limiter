import asyncio
import logging
import time
from collections import deque
from typing import Deque

# Set up logging with appropriate level
logger = logging.getLogger("rate_limiter")


class DualRateLimiter:
    """
    A custom rate limiter that enforces both:
    1. Maximum concurrent requests at any given time
    2. Maximum number of requests within a time period

    This is useful for APIs that have both types of rate limits.
    """

    def __init__(self, max_concurrent: int, max_requests: int, time_period: float, conservative: bool = True):
        """
        Initialize the rate limiter.

        Args:
            max_concurrent: Maximum number of concurrent requests allowed
            max_requests: Maximum number of requests allowed in the time period
            time_period: Time period in seconds for the request limit
        """
        self.max_concurrent = max_concurrent
        self.max_requests = max_requests
        self.time_period = time_period

        # Make the rate limit more conservative to avoid edge cases
        # For example, if API allows 5 requests per minute, we'll allow 4
        self._effective_max_requests = max_requests if not conservative else max(1, max_requests - 1)   

        # Semaphore to limit concurrent requests
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # Queue to track request timestamps
        self.request_times: Deque[float] = deque()

        # Lock to protect the request_times queue during concurrent access
        self.lock = asyncio.Lock()

        logger.info(
            f"DualRateLimiter initialized with: concurrent={max_concurrent}, "
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
                f"Cleaned {old_count - new_count} old requests, {new_count} remaining"
            )

    async def acquire(self):
        """
        Acquire permission to make a request.
        This blocks until both rate limits allow the request.
        """
        # First, acquire the semaphore to ensure we don't exceed concurrent limits
        await self.semaphore.acquire()

        try:
            # Then, check and wait for the time-based rate limit
            while True:
                async with self.lock:
                    await self._clean_old_requests()
                    current_count = len(self.request_times)

                    # If we have room for another request within the time period
                    if current_count < self._effective_max_requests:
                        # Record this request's timestamp
                        self.request_times.append(time.time())
                        return
                    else:
                        # Calculate wait time until the oldest request expires
                        oldest_time = self.request_times[0]
                        wait_time = oldest_time + self.time_period - time.time()
                        logger.info(
                            f"Rate limit reached ({current_count}/{self._effective_max_requests}), "
                            f"waiting {wait_time:.2f}s for a slot to open"
                        )

                # Wait until the oldest request expires
                async with self.lock:
                    if self.request_times:
                        oldest_request = self.request_times[0]
                        # Add a small buffer (1 second) to be safe
                        wait_time = max(
                            1.0, oldest_request + self.time_period - time.time() + 1
                        )
                    else:
                        wait_time = 1.0

                await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"Error in rate limiter: {str(e)}")
            # If something goes wrong, make sure we release the semaphore
            self.semaphore.release()
            raise

    def release(self):
        """Release the semaphore to allow another concurrent request."""
        self.semaphore.release()

    async def __aenter__(self):
        """Context manager entry - acquires permission to make a request."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - releases the semaphore."""
        self.release()