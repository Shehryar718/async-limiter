import logging
import sys


# Configure logging for tests
def pytest_configure(config):
    """Set up logging for tests."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    # Disable asyncio debug logging which can be noisy
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Make sure our rate limiter logger is visible
    logging.getLogger("rate_limiter").setLevel(logging.DEBUG)


# Remove the deprecated event_loop fixture - it's no longer needed
# as pytest-asyncio handles this automatically
