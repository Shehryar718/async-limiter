# Async Dual Rate Limiter

[![PyPI](https://img.shields.io/pypi/v/async-limiter)](https://pypi.org/project/async-limiter/)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11-blue)](https://pypi.org/project/async-limiter/)
[![License](https://img.shields.io/github/license/Shehryar718/async-limiter)](https://github.com/Shehryar718/async-limiter/blob/main/LICENSE)

A production-ready asyncio-based rate limiter for Python that enforces both concurrent and time-based rate limits.

## Features

- Enforce maximum concurrent requests
- Enforce maximum requests per time period
- Works as a context manager, decorator, or with explicit acquire/release
- Comprehensive metrics collection
- Production-ready error handling
- Task cancellation support

## Installation

```bash
# Install from PyPI
pip install async-limiter
```

Or install from source:

```bash
# Clone the repository
git clone https://github.com/Shehryar718/async-limiter.git
cd async-limiter

# Install in development mode
pip install -e .

# Install with test dependencies
pip install -e ".[test]"
```

## Usage

### Basic Usage

```python
import asyncio
from async_limiter import DualRateLimiter

# Create a rate limiter with max 5 concurrent requests and max 100 requests per minute
limiter = DualRateLimiter(max_concurrent=5, max_requests=100, time_period=60)

# Use as a context manager
async def fetch_data():
    async with limiter:
        # Your API call here
        return await api_call()

# Or use acquire/release manually
async def fetch_data_manual():
    await limiter.acquire()
    try:
        # Your API call here
        return await api_call()
    finally:
        limiter.release()

# Or use as a decorator
@limiter.limit()
async def fetch_data_decorated():
    # Your API call here
    return await api_call()
```

### With API Client Example

```python
import asyncio
from aiohttp import ClientSession
from async_limiter import DualRateLimiter

class ApiClient:
    def __init__(self, base_url="https://api.example.com"):
        self.base_url = base_url
        
        # Create a rate limiter for this API
        self.rate_limiter = DualRateLimiter(
            max_concurrent=5,
            max_requests=10,
            time_period=60,
            name="example_api"
        )
        
    async def get_data(self, path, params=None):
        """Make a rate-limited GET request."""
        url = f"{self.base_url}/{path}"
        
        # Use the rate limiter as a context manager
        async with self.rate_limiter:
            async with ClientSession() as session:
                response = await session.get(url, params=params)
                data = await response.json()
                return data
                
    @property
    def metrics(self):
        """Get rate limiter metrics."""
        return self.rate_limiter.get_metrics()

# Usage
async def main():
    api = ApiClient()
    
    # Make multiple concurrent requests (will be automatically rate limited)
    tasks = [api.get_data(f"resource/{i}") for i in range(20)]
    results = await asyncio.gather(*tasks)
    
    # Check metrics
    print(api.metrics)
    
if __name__ == "__main__":
    asyncio.run(main())
```

## Metrics

Get detailed metrics from the rate limiter:

```python
metrics = limiter.get_metrics()
print(metrics)
```

Example output:

```python
{
    "total_requests": 100,
    "current_requests": 2,
    "rate_limit_delays": 5,
    "total_delay_time": 12.5,
    "errors": 0,
    "current_queue_size": 3,
    "max_concurrent": 5,
    "max_requests_per_period": 9,
    "time_period": 60
}
```

## Running Tests

The package includes comprehensive tests. To run them:

```bash
# Install test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run specific test file
pytest tests/test_async_limiter.py

# Run tests with detailed output
pytest -v

# Run tests with log output
pytest -v --log-cli-level=INFO

# Run tests with coverage report
pytest --cov=async_limiter
```

## Development

This project uses modern Python packaging with `pyproject.toml`. The development tools configured include:

- **pytest**: For running tests
- **ruff**: For code formatting and linting
- **mypy**: For type checking
- **coverage**: For measuring test coverage

## Why Use Async Dual Rate Limiter?

Many APIs impose both concurrent and time-based rate limits. This package provides a clean, 
efficient solution to handle both types of limits with minimal overhead and maximum flexibility.

Key advantages:
- **Production Ready**: Thoroughly tested with extensive error handling
- **Flexible API**: Use as a context manager, decorator, or with explicit calls
- **Detailed Metrics**: Track usage and performance with built-in metrics
- **Type Annotated**: Full type annotations make integration easier
- **Pure Python**: No external dependencies required

## License

MIT License 