import json

import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import AuthState

NO_SELECTION = forms.NO_SELECTION


class VersionEditorState(rx.State):
    """One version: settings, templates, selectors, and aids.

    Editing a published version makes the API fork a draft; the editor
    then moves to that draft.
    """

    version: dict = {}  # noqa: RUF012 - Reflex state var
    crawler_title: str = ""
    crawler_fields: list[str] = []  # noqa: RUF012 - Reflex state var
    templates: list[dict] = []  # noqa: RUF012 - Reflex state var
    selected_template_id: str = ""
    selectors_by_template: dict[str, list[dict]] = {}  # noqa: RUF012 - Reflex state var
    proxy_options: list[dict] = []  # noqa: RUF012 - Reflex state var
    rate_limit_options: list[dict] = []  # noqa: RUF012 - Reflex state var
    rate_limits: list[dict] = []  # noqa: RUF012 - Reflex state var

    rate_limit_form_open: bool = False
    rate_limit_form_name: str = ""
    rate_limit_form_version: int = 0
    rate_limit_form_error: str = ""
    error: str = ""
    notice: str = ""

    template_form_open: bool = False
    editing_template_id: str = ""
    template_action: str = "GET"
    template_url: str = ""
    template_body: str = ""
    template_headers_text: str = "{}"
    template_form_error: str = ""

    selector_form_open: bool = False
    editing_selector_id: str = ""
    selector_path: str = ""
    selector_type: str = "value"
    selector_source: str = "content"
    selector_target: str = "__text"
    selector_title: str = ""
    selector_parent_id: str = NO_SELECTION
    selector_config_text: str = ""
    selector_form_error: str = ""

    aids: dict[str, dict] = {}  # noqa: RUF012 - Reflex state var
    aid_render_mode: str = "none"
    aid_proxy_id: str = NO_SELECTION
    aid_rate_limit_id: str = NO_SELECTION
    aid_ttl: str = ""
    aid_retry_codes: str = ""
    aid_success_codes: str = ""
    aid_max_retry_attempts: str = ""

    @rx.var
    def is_archived(self) -> bool:
        return "archived" == self.version.get("status")

    @rx.var
    def is_published(self) -> bool:
        return "published" == self.version.get("status")

    @rx.var
    def is_draft(self) -> bool:
        return "draft" == self.version.get("status")

    @rx.var
    def subtitle(self) -> str:
        if not self.version or not self.crawler_title:
            return ""
        return f"{self.crawler_title} · {self.version['status']}"

    @rx.var
    def selectors(self) -> list[dict]:
        """The open template's selectors, as a tree."""
        return self.selectors_by_template.get(self.selected_template_id, [])

    @rx.var
    def parent_options(self) -> list[dict]:
        """The selectors a selector may nest under; never itself."""
        return [
            {"value": row["id"], "label": row["tree_label"]}
            for row in self.selectors_by_template.get(self.selected_template_id, [])
            if row["id"] != self.editing_selector_id
        ]

    # --- Loading ------------------------------------------------------------
    @rx.event
    async def load_version(self):
        auth = await self.get_state(AuthState)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        try:
            self.notice = ""
            self.crawler_title = ""
            self.version = await api_client.get_version(auth.token, self.version_id)
            crawler = await api_client.get_crawler(
                auth.token, self.version["crawler_id"]
            )
            self.crawler_title = crawler["title"]
            self.crawler_fields = crawler.get("fields", [])
            templates = await api_client.list_templates(auth.token, self.version_id)
            self.aids = await _load_aids(auth.token, templates)
            self.selectors_by_template = await _load_selectors(
                auth.token, templates, self.crawler_fields
            )
            self.proxy_options = forms.id_options(
                await api_client.list_proxies(auth.token), "url"
            )
            await self._load_rate_limits(auth.token)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.templates = [self._template_row(template) for template in templates]
        self._keep_selection()
        return None

    def _template_row(self, template: dict) -> dict:
        """Return a template with its aid summary and selector count."""
        return {
            **template,
            "aid_label": forms.aid_summary(self.aids[template["id"]]),
            "selector_count": len(self.selectors_by_template[template["id"]]),
        }

    def _keep_selection(self) -> None:
        """Keep the open template if it is still here, else close it."""
        if self.selected_template_id not in self.selectors_by_template:
            self.selected_template_id = ""

    @rx.event
    def toggle_template(self, template_id: str):
        """Show a template's selectors, or hide them when shown."""
        self.selected_template_id = forms.toggle_selection(
            self.selected_template_id, template_id
        )

    async def _after_change(self, template_id: str | None = None):
        """Reload, or move to the draft a published version forked.

        `template_id` is the template the change landed on, as the API
        returned it; after a fork that is the clone, so it stays
        selected in the draft.
        """
        self.error = ""
        self.selected_template_id = template_id or self.selected_template_id
        if not self.is_published:
            return VersionEditorState.load_version
        auth = await self.get_state(AuthState)
        try:
            versions = await api_client.list_versions(
                auth.token, self.version["crawler_id"]
            )
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        draft_id = forms.draft_id(versions)
        if None is draft_id:
            return VersionEditorState.load_version
        return rx.redirect(f"/versions/{draft_id}")

    async def _mutate(self, call, *args):
        """Run an API call; return the follow-up event, or `None`."""
        auth = await self.get_state(AuthState)
        try:
            await call(auth.token, *args)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        return await self._after_change()

    # --- Settings -------------------------------------------------------------
    @rx.event
    async def publish(self):
        """Publish this draft; the API archives the published version."""
        auth = await self.get_state(AuthState)
        try:
            published = await api_client.publish_version(
                auth.token, self.version["crawler_id"], self.version_id
            )
        except api_client.ApiError as exc:
            self.error = exc.message
            return
        self.error = ""
        self.version = published
        self.notice = "Published."

    @rx.event
    async def run_test(self):
        """Run this exact version once on the `testing` queue."""
        auth = await self.get_state(AuthState)
        try:
            execution = await api_client.create_test_execution(
                auth.token, self.version_id
            )
        except api_client.ApiError as exc:
            self.notice = ""
            self.error = exc.message
            return
        self.error = ""
        self.notice = (
            f"Test run {execution['id']} is {execution['status']} on the "
            f"{execution['queue']} queue."
        )

    @rx.event
    def open_version_history(self):
        """Open this version's crawler history."""
        if not self.version:
            return None
        return rx.redirect(f"/crawlers/{self.version['crawler_id']}")

    @rx.event
    async def save_settings(self, form_data: dict):
        payload = forms.build_settings_payload(form_data)
        return await self._mutate(api_client.update_version, self.version_id, payload)

    async def _load_rate_limits(self, token: str) -> None:
        """Fetch the rules, for the aid's select and the domain lookup."""
        self.rate_limits = await api_client.list_rate_limits(token)
        self.rate_limit_options = forms.id_options(self.rate_limits, "name")

    # --- Templates --------------------------------------------------------------
    @rx.event
    def start_create_template(self):
        self.editing_template_id = ""
        self.template_action = "GET"
        self.template_url = ""
        self.template_body = ""
        self.template_headers_text = "{}"
        self._fill_aid(None)
        self.template_form_error = ""
        self.template_form_open = True

    @rx.event
    def start_edit_template(self, template: dict):
        self.editing_template_id = template["id"]
        self.template_action = template["action"]
        self.template_url = template["url"]
        self.template_body = template.get("body") or ""
        self.template_headers_text = json.dumps(template.get("headers") or {}, indent=2)
        self._fill_aid(self.aids.get(template["id"]))
        self.template_form_error = ""
        self.template_form_open = True

    @rx.event
    def set_template_form_open(self, is_open: bool):
        self.template_form_open = is_open

    @rx.event
    def set_template_action(self, action: str):
        self.template_action = action

    @rx.event
    def note_template_url(self, url: str):
        """Keep the URL as typed, for the domain rate-limit lookup.

        The input stays uncontrolled; this only records its value.
        """
        self.template_url = url

    # --- Domain rate limit ------------------------------------------------------
    @rx.event
    def add_domain_rate_limit(self):
        """Pick the rule named after the URL's domain, or create one."""
        host = forms.url_host(self.template_url)
        if not host:
            self.template_form_error = (
                "Enter a URL with a fixed domain to find its rate limit."
            )
            return
        self.template_form_error = ""
        rate_limit_id = forms.find_rate_limit_for_host(self.rate_limits, host)
        if rate_limit_id:
            self.aid_rate_limit_id = rate_limit_id
            return
        self.rate_limit_form_name = host
        self.rate_limit_form_error = ""
        self.rate_limit_form_version += 1
        self.rate_limit_form_open = True

    @rx.event
    def set_rate_limit_form_open(self, is_open: bool):
        self.rate_limit_form_open = is_open

    @rx.event
    async def submit_domain_rate_limit(self, form_data: dict):
        """Create the domain's rule and select it on the template's aid."""
        payload, error = forms.build_rate_limit_payload(form_data)
        if error:
            self.rate_limit_form_error = error
            return
        auth = await self.get_state(AuthState)
        try:
            created = await api_client.create_rate_limit(auth.token, payload)
            await self._load_rate_limits(auth.token)
        except api_client.ApiError as exc:
            self.rate_limit_form_error = exc.message
            return
        self.rate_limit_form_open = False
        return VersionEditorState.select_rate_limit(created["id"])

    @rx.event
    def select_rate_limit(self, rate_limit_id: str):
        """Select a rule once its option is on the page.

        Runs as its own event, after the refreshed options rendered.
        """
        self.aid_rate_limit_id = rate_limit_id

    @rx.event
    async def submit_template(self, form_data: dict):
        """Save the template, then its aid, as one form.

        The aid is put on the template the API returned, which after an
        auto-fork is the clone in the new draft.
        """
        payload, error = forms.build_template_payload(form_data, self.template_action)
        aid_payload, aid_error = self._aid_payload(form_data)
        if error or aid_error:
            self.template_form_error = error or aid_error
            return None
        auth = await self.get_state(AuthState)
        try:
            template = await self._save_template(auth.token, payload)
            await self._save_aid(auth.token, template["id"], aid_payload)
        except api_client.ApiError as exc:
            self.template_form_error = exc.message
            return None
        self.template_form_open = False
        return await self._after_change(template["id"])

    async def _save_template(self, token: str, payload: dict) -> dict:
        """Update the edited template, or create one."""
        if self.editing_template_id:
            return await api_client.update_template(
                token, self.editing_template_id, payload
            )
        return await api_client.create_template(token, self.version_id, payload)

    async def _save_aid(self, token: str, template_id: str, payload: dict | None):
        """Put the aid, or, when it is all defaults, drop the stored one."""
        if payload and not forms.is_default_aid(payload):
            await api_client.put_aid(token, template_id, payload)
        elif self.aids.get(self.editing_template_id):
            await api_client.delete_aid(token, template_id)

    @rx.event
    async def delete_template(self, template_id: str):
        return await self._mutate(api_client.delete_template, template_id)

    @rx.event
    async def set_root_template(self, template_id: str):
        return await self._mutate(
            api_client.set_root_template, self.version_id, template_id
        )

    # --- Selectors --------------------------------------------------------------
    @rx.event
    def start_create_selector(self):
        self.editing_selector_id = ""
        self.selector_path = ""
        self.selector_type = "value"
        self.selector_source = "content"
        self.selector_target = "__text"
        self.selector_title = ""
        self.selector_parent_id = NO_SELECTION
        self.selector_config_text = ""
        self.selector_form_error = ""
        self.selector_form_open = True

    @rx.event
    def start_edit_selector(self, selector: dict):
        self.editing_selector_id = selector["id"]
        self.selector_path = selector["path"]
        self.selector_type = selector["type"]
        self.selector_source = selector.get("source") or "content"
        self.selector_target = selector.get("target") or "__text"
        self.selector_title = selector.get("title") or ""
        self.selector_parent_id = forms.to_select(selector.get("parent_selector_id"))
        config = selector.get("config")
        self.selector_config_text = json.dumps(config, indent=2) if config else ""
        self.selector_form_error = ""
        self.selector_form_open = True

    @rx.event
    def set_selector_form_open(self, is_open: bool):
        self.selector_form_open = is_open

    @rx.event
    def set_selector_type(self, selector_type: str):
        self.selector_type = selector_type

    @rx.event
    def set_selector_source(self, source: str):
        self.selector_source = source

    @rx.event
    def set_selector_parent_id(self, parent_id: str):
        self.selector_parent_id = parent_id

    @rx.event
    async def submit_selector(self, form_data: dict):
        payload, error = forms.build_selector_payload(
            form_data,
            {
                "type": self.selector_type,
                "source": self.selector_source,
                "parent_selector_id": self.selector_parent_id,
            },
        )
        if error:
            self.selector_form_error = error
            return None
        auth = await self.get_state(AuthState)
        try:
            if self.editing_selector_id:
                selector = await api_client.update_selector(
                    auth.token, self.editing_selector_id, payload
                )
            else:
                selector = await api_client.create_selector(
                    auth.token, self.selected_template_id, payload
                )
        except api_client.ApiError as exc:
            self.selector_form_error = exc.message
            return None
        self.selector_form_open = False
        return await self._after_change(selector["message_template_id"])

    @rx.event
    async def delete_selector(self, selector_id: str):
        return await self._mutate(api_client.delete_selector, selector_id)

    # --- Aid (part of the template form) -----------------------------------
    def _fill_aid(self, aid: dict | None) -> None:
        """Show an aid in the template form, or the defaults."""
        aid = aid or {}
        self.aid_render_mode = aid.get("render_mode") or "none"
        self.aid_proxy_id = forms.to_select(aid.get("selected_proxy_id"))
        self.aid_rate_limit_id = forms.to_select(aid.get("rate_limit_id"))
        self.aid_ttl = forms.optional_text(aid.get("ttl"))
        self.aid_retry_codes = forms.codes_text(aid.get("retry_codes"))
        self.aid_success_codes = forms.codes_text(aid.get("success_codes"))
        self.aid_max_retry_attempts = forms.optional_text(aid.get("max_retry_attempts"))

    def _aid_payload(self, form_data: dict) -> tuple[dict, str]:
        """Return the aid body from the template form, or an error."""
        return forms.build_aid_payload(
            form_data,
            {
                "render_mode": self.aid_render_mode,
                "selected_proxy_id": self.aid_proxy_id,
                "rate_limit_id": self.aid_rate_limit_id,
            },
        )

    @rx.event
    def set_aid_render_mode(self, render_mode: str):
        self.aid_render_mode = render_mode

    @rx.event
    def set_aid_proxy_id(self, proxy_id: str):
        self.aid_proxy_id = proxy_id

    @rx.event
    def set_aid_rate_limit_id(self, rate_limit_id: str):
        """Keep a picked rule, or `NO_SELECTION` for none.

        A Radix select reports "" when its value briefly has no matching
        item (a rule just created, before its option renders); that is
        never a choice, so it is ignored.
        """
        if rate_limit_id:
            self.aid_rate_limit_id = rate_limit_id


async def _load_aids(token: str, templates: list[dict]) -> dict[str, dict]:
    """Return each template's aid, `{}` for one without."""
    return {
        template["id"]: await api_client.get_aid(token, template["id"]) or {}
        for template in templates
    }


async def _load_aids(token: str, templates: list[dict]) -> dict[str, dict]:
    """Return each template's aid, `{}` for one without."""
    return {
        template["id"]: await api_client.get_aid(token, template["id"]) or {}
        for template in templates
    }


def _landed_template_id(result: dict | None) -> str | None:
    """Return the template an aid landed on; `None` for other results."""
    return (result or {}).get("message_template_id")


async def _load_selectors(
    token: str, templates: list[dict], crawler_fields: list[str]
) -> dict[str, list[dict]]:
    """Return each template's selectors, as a tree."""
    return {
        template["id"]: forms.selector_tree_rows(
            await api_client.list_selectors(token, template["id"]), crawler_fields
        )
        for template in templates
    }
