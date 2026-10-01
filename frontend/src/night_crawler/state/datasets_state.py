import json

import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import AuthState


class DatasetsState(rx.State):
    """The Datasets crawlers download, field by field; admins edit and delete."""

    datasets: list[dict] = []  # noqa: RUF012 - Reflex state var
    error: str = ""

    form_open: bool = False
    editing_dataset_id: str = ""
    form_name: str = ""
    form_fields_text: str = ""
    form_error: str = ""

    @rx.event
    async def load_datasets(self):
        auth = await self.get_state(AuthState)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        try:
            datasets = await api_client.list_datasets(auth.token)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.datasets = [
            {
                **dataset,
                "fields_text": forms.fields_summary(dataset["fields"]),
            }
            for dataset in datasets
        ]
        self.error = ""
        return None

    @rx.event
    def start_create(self):
        self._open_form(
            {"fields": [{"name": "item_id", "is_required": True, "is_unique": True}]}
        )

    @rx.event
    def start_edit(self, dataset: dict):
        self._open_form(dataset)

    def _open_form(self, dataset: dict) -> None:
        """Open the dialog on `dataset`, or a new one's defaults."""
        self.editing_dataset_id = dataset.get("id", "")
        self.form_name = dataset.get("name", "")
        self.form_fields_text = json.dumps(dataset.get("fields", []), indent=2)
        self.form_error = ""
        self.form_open = True

    @rx.event
    def set_form_open(self, is_open: bool):
        self.form_open = is_open

    @rx.event
    async def submit_form(self, form_data: dict):
        payload, error = forms.build_dataset_payload(form_data)
        if error:
            self.form_error = error
            return None
        auth = await self.get_state(AuthState)
        try:
            if self.editing_dataset_id:
                await api_client.update_dataset(
                    auth.token, self.editing_dataset_id, payload
                )
            else:
                await api_client.create_dataset(auth.token, payload)
        except api_client.ApiError as exc:
            self.form_error = exc.message
            return None
        self.form_open = False
        return DatasetsState.load_datasets

    @rx.event
    async def delete_dataset(self, dataset_id: str):
        auth = await self.get_state(AuthState)
        try:
            await api_client.delete_dataset(auth.token, dataset_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        return DatasetsState.load_datasets
