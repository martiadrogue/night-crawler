"""The port for handing an Instruction Generation to a worker."""

from abc import ABC, abstractmethod


class AbstractInstructionGenerationDispatcher(ABC):
    """Enqueues generations onto the AI agents queue."""

    @abstractmethod
    async def dispatch(self, generation_id: str) -> None:
        """Enqueue one pending Instruction Generation."""
