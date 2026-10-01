"""Dependency ordering for a Crawler Version's templates."""

from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageSelector, MessageTemplate
from night_crawler.domain.rules.placeholders import extract_placeholders


def template_texts(template: MessageTemplate) -> list[str]:
    """Return every template field placeholders may appear in."""
    texts = [template.action, template.url, *map(str, template.headers.values())]
    return texts if None is template.body else [*texts, template.body]


def order_message_templates(
    templates: list[MessageTemplate],
    selectors_by_template_id: dict[str, list[MessageSelector]],
) -> list[MessageTemplate]:
    """Order templates so each runs after the ones it depends on.

    A template depends on another when one of its placeholders is the
    `title` of a selector on that other template. Independent templates
    keep their order and run first, then the ones others depend on,
    then the dependents in topological order.

    Raises:
        ValidationException: templates depend on each other in a cycle
            (409).
    """
    owner_by_title = _owners_by_title(templates, selectors_by_template_id)
    depends_on = {
        template.id: _dependencies_of(template, owner_by_title)
        for template in templates
    }
    ready, dependent = _partition(templates, depends_on)
    return [*ready, *_topologically_sort(dependent, depends_on, ready)]


def _partition(
    templates: list[MessageTemplate], depends_on: dict[str, set[str]]
) -> tuple[list[MessageTemplate], list[MessageTemplate]]:
    """Split into (ready to run, dependent).

    Among the ready ones, those nobody depends on come first.
    """
    depended_upon = set().union(*depends_on.values())
    ready = [template for template in templates if not depends_on[template.id]]
    ready.sort(key=lambda template: template.id in depended_upon)
    return ready, [template for template in templates if depends_on[template.id]]


def _owners_by_title(
    templates: list[MessageTemplate],
    selectors_by_template_id: dict[str, list[MessageSelector]],
) -> dict[str, str]:
    """Map each selector title to the id of the template it's on."""
    return {
        selector.title: template.id
        for template in templates
        for selector in selectors_by_template_id.get(template.id, [])
        if selector.title
    }


def _dependencies_of(
    template: MessageTemplate, owner_by_title: dict[str, str]
) -> set[str]:
    """Return the ids of the other templates `template` depends on."""
    owners = {
        owner_by_title.get(name)
        for name in extract_placeholders(template_texts(template))
    }
    return owners - {None, template.id}


def _topologically_sort(
    dependent: list[MessageTemplate],
    depends_on: dict[str, set[str]],
    placed: list[MessageTemplate],
) -> list[MessageTemplate]:
    """Order dependents with Kahn's algorithm.

    Raises:
        ValidationException: no template is ready, i.e. a cycle.
    """
    placed_ids = {template.id for template in placed}
    remaining, ordered = list(dependent), []
    while remaining:
        ready = _ready(remaining, depends_on, placed_ids)
        ordered.extend(ready)
        placed_ids |= {template.id for template in ready}
        remaining = _unplaced(remaining, placed_ids)
    return ordered


def _unplaced(
    templates: list[MessageTemplate], placed_ids: set[str]
) -> list[MessageTemplate]:
    """Return the templates not placed yet."""
    return [template for template in templates if template.id not in placed_ids]


def _ready(
    remaining: list[MessageTemplate],
    depends_on: dict[str, set[str]],
    placed_ids: set[str],
) -> list[MessageTemplate]:
    """Return the templates whose dependencies are all placed.

    Raises:
        ValidationException: none is ready, i.e. a cycle (409).
    """
    ready = [t for t in remaining if depends_on[t.id] <= placed_ids]
    if not ready:
        raise ValidationException(
            "Circular dependency among message template placeholders.", 409
        )
    return ready
