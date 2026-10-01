"""Playwright implementation of the request executor."""

from night_crawler.domain.ports.request_executor import (
    AbstractRequestExecutor,
    DispatchRequest,
    DispatchResult,
)
from night_crawler.infrastructure.external.browser_dispatch import (
    BrowserEngine,
    BrowserExecution,
)
from playwright.async_api import Error, TimeoutError, async_playwright

_ENGINE = BrowserEngine(async_playwright, Error, TimeoutError)


class PlaywrightRequestExecutor(AbstractRequestExecutor):
    """Renders `render_mode = "playwright"` templates in Chromium.

    Browser resources live for one execution and close in `aclose()`.
    """

    def __init__(self) -> None:
        """Create a browser manager for one crawler execution."""
        self._execution = BrowserExecution(_ENGINE)

    async def execute(self, request: DispatchRequest) -> DispatchResult:
        """Render one request and harvest it.

        Raises:
            ExternalServiceException: the render failed or timed out, or
                the status is 400 or above.
        """
        return await self._execution.execute(request)

    async def aclose(self) -> None:
        """Close browser resources retained for this execution."""
        await self._execution.aclose()
