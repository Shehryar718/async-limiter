"""
Async Dual Rate Limiter

A production-ready asyncio-based rate limiter for Python that enforces
both concurrent and time-based rate limits.
"""

from .async_limiter import DualRateLimiter

__version__ = "1.1.0"
__all__ = ["DualRateLimiter"]
