from night_crawler.domain.rules.placeholders import (
    extract_placeholders,
    render_placeholders,
    stringify,
)


def test_extracts_every_distinct_placeholder():
    assert {"parish", "category"} == extract_placeholders(
        ["{{category}} in {{ parish }}", "{{parish}}"]
    )


def test_renders_known_placeholders_and_leaves_unknown_ones():
    assert "bars in Encamp {{later}}" == render_placeholders(
        "{{category}} in {{parish}} {{later}}",
        {"category": "bars", "parish": "Encamp"},
    )


def test_stringify_writes_objects_as_json():
    assert '{"lat": 42.5}' == stringify({"lat": 42.5})
    assert "7" == stringify(7)
