import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.crawler_instructions import CrawlerInstructionsCreate
from night_crawler.schemas.message_aid_proxy import MessageAidProxyCreate
from night_crawler.services import (
    crawler_instructions_service,
    crawler_version_service,
    message_aid_proxy_service,
)

INSTRUCTIONS = {
    "settings": {"root": "search", "is_host_session_sharing_enabled": False},
    "templates": {
        "search": {"action": "GET", "url": "https://example.com/?q={{query}}"},
        "detail": {
            "action": "POST",
            "url": "https://example.com/item",
            "body": '{"id": "{{item_id}}"}',
            "headers": {"Content-Type": "application/json"},
        },
    },
    "aids": {"search": {"render_mode": "playwright", "ttl": 30}},
    "selectors": {
        "results": {"template": "search", "type": "iterator", "path": "//li"},
        "item_id": {
            "template": "search",
            "parent": "results",
            "type": "value",
            "path": "./@data-id",
            "target": "data-id",
            "title": "item_id",
        },
        "name": {"template": "detail", "type": "value", "path": "name"},
    },
}


def _instructions(**overrides) -> CrawlerInstructionsCreate:
    return CrawlerInstructionsCreate.model_validate({**INSTRUCTIONS, **overrides})


async def _draft(write_repositories, create_crawler):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    return crawler, draft


@pytest.mark.anyio
async def test_import_replaces_the_draft_tree(
    write_repositories, member, create_crawler
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    old_root_id = draft.message_template_root_id

    version = await crawler_instructions_service.import_instructions(
        write_repositories, member, draft.id, _instructions()
    )

    templates = (
        await write_repositories.message_templates.get_all_by_crawler_version_id(
            draft.id
        )
    )
    by_url = {template.url: template for template in templates}
    search = by_url["https://example.com/?q={{query}}"]
    selectors = (
        await write_repositories.message_selectors.get_all_by_message_template_id(
            search.id
        )
    )
    by_path = {selector.path: selector for selector in selectors}
    aid = await write_repositories.message_aids.get_by_message_template_id(search.id)
    assert draft.id == version.id
    assert 2 == len(templates)
    assert old_root_id not in {template.id for template in templates}
    assert search.id == version.message_template_root_id
    assert version.is_host_session_sharing_enabled is False
    assert by_path["//li"].id == by_path["./@data-id"].parent_selector_id
    assert "item_id" == by_path["./@data-id"].title
    assert "playwright" == aid.render_mode


@pytest.mark.anyio
async def test_export_then_import_round_trips(
    write_repositories, read_repositories, member, create_crawler
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    await crawler_instructions_service.import_instructions(
        write_repositories, member, draft.id, _instructions()
    )

    exported = await crawler_instructions_service.export_instructions(
        read_repositories, member, draft.id
    )
    await crawler_instructions_service.import_instructions(
        write_repositories,
        member,
        draft.id,
        CrawlerInstructionsCreate.model_validate(exported.model_dump()),
    )
    again = await crawler_instructions_service.export_instructions(
        read_repositories, member, draft.id
    )

    assert exported == again
    assert ["template_1", "template_2"] == list(exported.templates)
    assert "template_1" == exported.settings.root
    assert ["template_1.iterator", "item_id", "template_2.value"] == list(
        exported.selectors
    )
    assert "template_1.iterator" == exported.selectors["item_id"].parent
    assert {"template_1"} == set(exported.aids)


@pytest.mark.anyio
async def test_import_on_a_published_version_lands_on_a_new_draft(
    write_repositories, member, create_crawler
):
    crawler, draft = await _draft(write_repositories, create_crawler)
    published = await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )

    version = await crawler_instructions_service.import_instructions(
        write_repositories, member, published.id, _instructions()
    )

    assert published.id != version.id
    assert "draft" == version.status
    kept = await write_repositories.message_templates.get_all_by_crawler_version_id(
        published.id
    )
    assert 1 == len(kept)


@pytest.mark.anyio
async def test_import_refuses_an_archived_version(
    write_repositories, member, create_crawler
):
    crawler, draft = await _draft(write_repositories, create_crawler)
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )
    second = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, second.id
    )

    with pytest.raises(ValidationException) as exc_info:
        await crawler_instructions_service.import_instructions(
            write_repositories, member, draft.id, _instructions()
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"settings": {"root": "missing"}}, "root"),
        ({"aids": {"missing": {}}}, "aids.missing"),
        (
            {"selectors": {"a": {"template": "missing", "type": "value", "path": "x"}}},
            "selectors.a",
        ),
        (
            {
                "selectors": {
                    "a": {"template": "search", "type": "value", "path": "x"},
                    "b": {
                        "template": "detail",
                        "parent": "a",
                        "type": "value",
                        "path": "y",
                    },
                }
            },
            "selectors.b",
        ),
        (
            {
                "selectors": {
                    "a": {
                        "template": "search",
                        "parent": "b",
                        "type": "iterator",
                        "path": "x",
                    },
                    "b": {
                        "template": "search",
                        "parent": "a",
                        "type": "iterator",
                        "path": "y",
                    },
                }
            },
            "cycle",
        ),
        (
            {
                "selectors": {
                    "a": {
                        "template": "search",
                        "type": "iterator",
                        "source": "context",
                        "path": "query",
                    }
                }
            },
            "selectors.a",
        ),
    ],
)
async def test_import_lists_broken_references(
    write_repositories, member, create_crawler, overrides, problem
):
    _crawler, draft = await _draft(write_repositories, create_crawler)

    with pytest.raises(ValidationException) as exc_info:
        await crawler_instructions_service.import_instructions(
            write_repositories, member, draft.id, _instructions(**overrides)
        )

    assert 422 == exc_info.value.status_code
    assert problem in exc_info.value.message


@pytest.mark.anyio
async def test_import_checks_the_proxy_exists(
    write_repositories, member, create_crawler
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    proxy = await message_aid_proxy_service.create_proxy(
        write_repositories,
        MessageAidProxyCreate(url="http://proxy:8080", password="secret"),
    )

    known = await crawler_instructions_service.import_instructions(
        write_repositories,
        member,
        draft.id,
        _instructions(aids={"search": {"selected_proxy_id": proxy.id}}),
    )
    with pytest.raises(ValidationException) as exc_info:
        await crawler_instructions_service.import_instructions(
            write_repositories,
            member,
            draft.id,
            _instructions(aids={"search": {"selected_proxy_id": "missing"}}),
        )

    assert draft.id == known.id
    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_export_of_an_unknown_version_is_404(read_repositories, member):
    with pytest.raises(ValidationException) as exc_info:
        await crawler_instructions_service.export_instructions(
            read_repositories, member, "missing"
        )

    assert 404 == exc_info.value.status_code


def test_parse_instructions_text_reads_a_yaml_file():
    instructions = crawler_instructions_service.parse_instructions_text(
        "templates:\n  search: {action: GET, url: 'https://example.com'}\n"
    )

    assert ["search"] == list(instructions.templates)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("templates: [unclosed", "not valid YAML"),
        ("base: &b {action: GET, url: x}\ntemplates:\n  a: *b", "aliases"),
        ("templates:\n  a: {action: FETCH, url: x}", "templates.a.action"),
        ("templates: {}\nextra: 1", "extra"),
    ],
)
def test_parse_instructions_text_refuses_a_bad_file(text, message):
    with pytest.raises(ValidationException) as exc_info:
        crawler_instructions_service.parse_instructions_text(text)

    assert 422 == exc_info.value.status_code
    assert message in exc_info.value.message
