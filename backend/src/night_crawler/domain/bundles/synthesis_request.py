"""What instruction synthesis is given, per attempt."""

from dataclasses import dataclass

from night_crawler.domain.ports.browser_agent_recorder import FilteredRecording


@dataclass(frozen=True)
class SynthesisRequest:
    """One attempt at writing a version's instructions file.

    Attributes:
        prompt: What the crawler should get, in plain words.
        crawler_fields: The dataset fields each row must carry; the
            selectors harvesting them are titled after them.
        current_instructions_yaml: The targeted version's file, a
            starting point that may be kept or replaced.
        filtered_recording: The recorded requests that led to the data.
        previous_yaml: The last attempt's file, when it had problems.
        previous_problems: What was wrong with it, to fix this time.
    """

    prompt: str
    crawler_fields: tuple[str, ...]
    current_instructions_yaml: str
    filtered_recording: FilteredRecording
    previous_yaml: str | None = None
    previous_problems: tuple[str, ...] = ()
