"""The port that writes a version's instructions from a recording."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from night_crawler.domain.bundles.synthesis_request import SynthesisRequest


@dataclass(frozen=True)
class InstructionsDraft:
    """A whole instructions file, as synthesized: unchecked.

    Attributes:
        yaml_text: The file.
        required_context_keys: Placeholders the file uses for redacted
            credentials (e.g. `authorization`), which only the
            Crawler's Context can fill.
    """

    yaml_text: str
    required_context_keys: tuple[str, ...] = ()


class AbstractInstructionSynthesizer(ABC):
    """Turns the requests that led to some data into instructions."""

    @abstractmethod
    async def synthesize_instructions(
        self, request: SynthesisRequest
    ) -> InstructionsDraft:
        """Return an instructions file that repeats those requests.

        The file is checked by the caller, who asks again with its
        problems; the synthesizer need not validate it.

        Raises:
            ConfigurationException: the synthesizer is not set up
                (e.g. no API key).
            ExternalServiceException: the model behind it failed, or
                its quota is spent.
        """
