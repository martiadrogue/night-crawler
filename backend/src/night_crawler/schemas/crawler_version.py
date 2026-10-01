"""Request and response models for Crawler Versions."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CrawlerVersionOut(BaseModel):
    """A Crawler Version as returned by the API.

    Status only changes through the draft, publish, and delete actions.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    crawler_id: str
    status: str
    message_template_root_id: str | None
    published_at: datetime | None
    is_proxy_ladder_enabled: bool
    is_host_session_sharing_enabled: bool
    created_at: datetime
    updated_at: datetime


class CrawlerVersionUpdate(BaseModel):
    """Body for a partial settings update; unset fields stay unchanged.

    Request settings (proxy, codes, retry budgets) live on each
    template's Message Aid. Changing a published version auto-forks a
    draft to hold the change.
    """

    is_proxy_ladder_enabled: bool | None = None
    is_host_session_sharing_enabled: bool | None = None


class CrawlerVersionRootTemplateUpdate(BaseModel):
    """Body pointing a version's root at another of its templates.

    Changing a published version auto-forks a draft to hold the change.
    """

    message_template_id: str
