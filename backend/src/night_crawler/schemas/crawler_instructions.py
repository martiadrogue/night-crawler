"""The crawler instructions file: one version's tree as flat blocks.

Templates, aids, and selectors each sit in their own top-level block,
keyed by a name local to the file; entries point at each other by those
keys (`settings.root`, an aid's key, a selector's `template`/`parent`)
instead of nesting. The rules are in DOMAIN_MODEL §5.9.
"""

from typing import Annotated, Literal, Self

from night_crawler.schemas.message_aid import MessageAidBase
from night_crawler.schemas.message_selector import (
    PaginationConfigBase,
    SelectorSource,
    SelectorType,
    reject_list_suffix,
    require_config_for_pagination,
    require_regex_for_regex_sources,
)
from night_crawler.schemas.message_template import MessageTemplateBase
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

INSTRUCTIONS_FORMAT = "night-crawler/instructions/v1"
"""The file's format tag; a new one marks a breaking change."""

InstructionKey = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")
]
"""A file-local name for a template or selector; never stored."""


class InstructionSettingsBase(BaseModel):
    """The version's settings, and which template is the root."""

    model_config = ConfigDict(extra="forbid")

    root: InstructionKey | None = None
    is_proxy_ladder_enabled: bool = False
    is_host_session_sharing_enabled: bool = True


class InstructionTemplateBase(MessageTemplateBase):
    """One request: `action`, `url`, `body`, and `headers`."""

    model_config = ConfigDict(extra="forbid")


class InstructionAidBase(MessageAidBase):
    """A template's request settings, under that template's key."""

    model_config = ConfigDict(extra="forbid")


class InstructionSelectorBase(BaseModel):
    """One selector; `template` and `parent` are keys in the file."""

    model_config = ConfigDict(extra="forbid")

    template: InstructionKey
    parent: InstructionKey | None = None
    type: SelectorType
    path: str = Field(min_length=1)
    source: SelectorSource = "content"
    target: str = "__text"
    title: str | None = None
    config: PaginationConfigBase | None = None

    _validate_title = field_validator("title")(reject_list_suffix)

    @model_validator(mode="after")
    def _check_path_and_config(self) -> Self:
        """Apply the selector API's own `config` and regex checks.

        Raises:
            ValueError: `config` doesn't match the type, or a
                `headers`/`url` path is not a regex.
        """
        require_config_for_pagination(self.type, self.config)
        require_regex_for_regex_sources(self.source, self.path)
        return self


class CrawlerInstructionsBase(BaseModel):
    """Every block of the file, in the order a reader follows them."""

    model_config = ConfigDict(extra="forbid")

    settings: InstructionSettingsBase = InstructionSettingsBase()
    templates: dict[InstructionKey, InstructionTemplateBase] = Field(min_length=1)
    aids: dict[InstructionKey, InstructionAidBase] = {}
    selectors: dict[InstructionKey, InstructionSelectorBase] = {}


class CrawlerInstructionsCreate(CrawlerInstructionsBase):
    """An imported file; it replaces the version's whole tree.

    `format` may be left out; `settings.root` defaults to the first
    template.
    """

    format: Literal["night-crawler/instructions/v1"] = INSTRUCTIONS_FORMAT


class CrawlerInstructionsOut(CrawlerInstructionsBase):
    """An exported file; `format` comes first and is always written."""

    format: Literal["night-crawler/instructions/v1"]
