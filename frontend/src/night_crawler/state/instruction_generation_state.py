import asyncio

import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import get_session
from night_crawler.state.version_editor_state import VersionEditorState

POLL_INTERVAL_SECONDS = 3


class InstructionGenerationState(VersionEditorState):
    """The Instructions page's "Generate from prompt" dialog.

    A substate of the editor, so it reads the open version and the
    crawler's fields. Submitting creates an Instruction Generation, then
    a background event polls it, and then its test run, until both end.
    Closing the dialog or leaving the page stops polling; the job goes
    on on the server, and reopening the dialog picks it up again.
    """

    generation_form_open: bool = False
    generation_form_key: int = 0
    generation_prompt: str = ""
    generation_error: str = ""
    generation: dict = {}  # noqa: RUF012 - Reflex state var
    generation_execution: dict = {}  # noqa: RUF012 - Reflex state var
    has_opened_result: bool = False
    # Each poll loop runs while this is the round it started on; a new
    # round (submit, close, leaving the page) ends the older loops.
    poll_round: int = 0

    @rx.var
    def generation_status_line(self) -> str:
        if not self.generation:
            return ""
        return forms.generation_status_text(
            self.generation, self.generation_execution or None
        )

    @rx.var
    def is_generation_busy(self) -> bool:
        return self._is_busy()

    @rx.var
    def crawler_fields_text(self) -> str:
        return ", ".join(self.crawler_fields)

    @rx.var
    def generation_run_counts(self) -> str:
        """The test run's request and error counts, once it has any."""
        metrics = self.generation_execution.get("metrics") or {}
        if not metrics:
            return ""
        return (
            f"{metrics.get('request_count', 0)} requests · "
            f"{metrics.get('error_count', 0)} errors"
        )

    @rx.var
    def has_generation_failed(self) -> bool:
        return "failed" == self.generation.get("status")

    @rx.var
    def generation_warnings(self) -> list[str]:
        return self.generation.get("warnings") or []

    @rx.var
    def required_context_keys(self) -> list[str]:
        return self.generation.get("required_context_keys") or []

    @rx.var
    def has_generation_csv(self) -> bool:
        return bool(self.generation_execution) and forms.has_csv(
            self.generation_execution
        )

    @rx.event
    def set_generation_form_open(self, is_open: bool):
        self.generation_form_open = is_open
        if not is_open:
            self.poll_round += 1
            return None
        self.generation_form_key += 1
        return InstructionGenerationState.resume_polling

    @rx.event
    def stop_polling(self):
        """End the poll loop when the page goes away."""
        self.poll_round += 1

    @rx.event
    def resume_polling(self):
        """Poll again when an open dialog's job is still going."""
        if self.generation_form_open and self._is_busy():
            return InstructionGenerationState.poll_generation
        return None

    @rx.event
    async def submit_generation(self, form_data: dict):
        """Ask the AI agents to write this version's instructions."""
        self.generation_prompt = form_data.get("prompt") or ""
        payload, error = forms.build_generation_payload(form_data)
        if error:
            self.generation_error = error
            return None
        auth = await get_session(self)
        try:
            generation = await api_client.create_instruction_generation(
                auth.token, self.version_id, payload["prompt"]
            )
        except api_client.ApiError as exc:
            self.generation_error = exc.message
            return None
        self.generation_error = ""
        self.generation = generation
        self.generation_execution = {}
        self.has_opened_result = False
        return InstructionGenerationState.poll_generation

    @rx.event
    async def download_generation_sample_csv(self):
        """Hand the browser the test run's Sample CSV, as on Runs."""
        execution_id = self.generation_execution.get("id", "")
        auth = await get_session(self)
        try:
            filename, csv_text = await api_client.download_execution_sample_csv(
                auth.token, execution_id
            )
        except api_client.ApiError as exc:
            self.generation_error = exc.message
            return None
        # Bytes travel base64-encoded, so the CSV's CRLF endings survive.
        return rx.download(data=csv_text.encode(), filename=filename)

    @rx.event(background=True)
    async def poll_generation(self):
        """Follow the generation, then its test run, every few seconds."""
        async with self:
            self.poll_round += 1
            poll_round = self.poll_round
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            # Per round: a generation outlives the 5-minute access token.
            async with self:
                token = (await get_session(self)).token
            step = await self._poll_once(token, poll_round)
            if None is step:
                return
            event, is_done = step
            if None is not event:
                yield event
            if is_done:
                return

    async def _poll_once(self, token: str, poll_round: int):
        """Fetch and show the job once; `None` once a newer round began.

        Returns:
            The event to run (opening the result), and whether polling
            is over. The API is called outside the state lock.
        """
        async with self:
            if poll_round != self.poll_round:
                return None
            generation_id = self.generation.get("id", "")
            execution_id = self._execution_to_follow()
        generation, execution, error = await _fetch(token, generation_id, execution_id)
        async with self:
            if poll_round != self.poll_round:
                return None
            if error:
                self.generation_error = error
                return None, True
            return self._apply(generation, execution), not self._is_busy()

    def _is_busy(self) -> bool:
        """Tell whether the job or its test run is still going."""
        if not self.generation:
            return False
        if not forms.has_ended(self.generation):
            return True
        test_execution_id = self.generation.get("test_execution_id")
        return bool(test_execution_id) and not forms.has_ended(
            self.generation_execution
        )

    def _execution_to_follow(self) -> str:
        """Return the test run's id once the generation started one."""
        if "succeeded" != self.generation.get("status"):
            return ""
        return self.generation.get("test_execution_id") or ""

    def _apply(self, generation: dict, execution: dict):
        """Show what one poll got; return the event to run, if any."""
        self.generation = generation
        self.generation_execution = execution
        if "failed" == generation.get("status"):
            self.generation_error = generation.get("error") or "Generation failed."
        if "succeeded" != generation.get("status") or self.has_opened_result:
            return None
        self.has_opened_result = True
        return self._open_result(generation)

    def _open_result(self, generation: dict):
        """Open the version the instructions landed on, once.

        A published version forked into a new draft, which the editor
        redirects to; otherwise this version is reloaded.
        """
        result_version_id = generation.get("result_version_id")
        if result_version_id and result_version_id != self.version_id:
            return rx.redirect(f"/versions/{result_version_id}")
        return VersionEditorState.load_version


async def _fetch(
    token: str, generation_id: str, execution_id: str
) -> tuple[dict, dict, str]:
    """Return the generation, its test run (or `{}`), and any API error."""
    try:
        generation = await api_client.get_instruction_generation(token, generation_id)
        execution = (
            await api_client.get_execution(token, execution_id) if execution_id else {}
        )
    except api_client.ApiError as exc:
        return {}, {}, exc.message
    return generation, execution, ""
