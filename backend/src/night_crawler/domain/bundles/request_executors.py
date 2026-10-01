"""The request executors one run uses, picked by render mode."""

from dataclasses import dataclass

from night_crawler.domain.ports.request_executor import AbstractRequestExecutor


@dataclass(frozen=True)
class RequestExecutors:
    """One executor per render mode (DOMAIN_MODEL `RENDER_MODES`)."""

    httpx: AbstractRequestExecutor
    playwright: AbstractRequestExecutor
    stealth: AbstractRequestExecutor

    def for_render_mode(self, render_mode: str) -> AbstractRequestExecutor:
        """Return the executor for `none`, `playwright` or `stealth`."""
        return {"playwright": self.playwright, "stealth": self.stealth}.get(
            render_mode, self.httpx
        )

    async def aclose(self) -> None:
        """Release every executor's pooled resources."""
        for executor in (self.httpx, self.playwright, self.stealth):
            await executor.aclose()
