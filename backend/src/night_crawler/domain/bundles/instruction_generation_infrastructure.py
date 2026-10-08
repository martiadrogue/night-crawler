"""What one Instruction Generation needs from the infrastructure."""

from dataclasses import dataclass

from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.ports.browser_agent_recorder import (
    AbstractBrowserAgentRecorder,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.instruction_synthesizer import (
    AbstractInstructionSynthesizer,
)
from night_crawler.domain.ports.user_directory import AbstractUserDirectory


@dataclass(frozen=True)
class InstructionGenerationInfrastructure:
    """The ports a generation's worker task opens and closes.

    The browser agent may take minutes, so repositories come as
    factories for short-lived sets, never one transaction held across
    it.

    Attributes:
        user_directory: Where the worker looks up who asked, to act as
            them.
        recording_max_bytes: The most a stored recording may take, as
            JSON (`GENERATION_RECORDING_MAX_BYTES`).
        synthesis_max_attempts: How many files the synthesizer may
            write before the generation fails
            (`SYNTHESIS_MAX_ATTEMPTS`).
        ignored_hosts: Analytics and ads hosts the recording filter
            drops (`SYNTHESIS_IGNORED_HOSTS`).
    """

    repository_factories: RepositorySetFactories
    user_directory: AbstractUserDirectory
    recorder: AbstractBrowserAgentRecorder
    synthesizer: AbstractInstructionSynthesizer
    execution_dispatcher: AbstractExecutionDispatcher
    recording_max_bytes: int
    synthesis_max_attempts: int
    ignored_hosts: tuple[str, ...]
