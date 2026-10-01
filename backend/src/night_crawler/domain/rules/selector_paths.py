"""How a selector path is read."""

XPATH_PREFIXES: tuple[str, ...] = ("/", "./", "../", "(")


def is_xpath(path: str) -> bool:
    """Tell XPath from a CSS selector for HTML content.

    XPath paths start from a node: `/`, `./`, `../`, or a `(` group.
    Anything else (`div.venue > a`, `#panel`) is CSS.
    """
    return path.lstrip().startswith(XPATH_PREFIXES)
