"""The web app's rewrites must not swallow its own pages.

This exists because they did. A rewrite was added so a customer's list could reach the API:

    { source: "/shop/:path*", destination: ".../shop/:path*" }

and it proxied **every** request under `/shop`, including the pages - so a customer opening the link
a
trader sent them received the API's raw JSON instead of a shop. The storefront was broken in
production
while every check stayed green, because a JSON document has no viewport overflow, no broken images,
no
links and no forbidden words: every assertion the browser check made was vacuously true.

The rule this test enforces is one line: **a rewrite may not shadow a route that has a page.** It
reads
the configuration as text and the filesystem as truth, in the same spirit as the audit-wiring gate -
a
claim about the shape of the project that a person cannot be relied on to re-check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NEXT_CONFIG = REPOSITORY_ROOT / "web" / "next.config.ts"
APP_ROUTES = REPOSITORY_ROOT / "web" / "app"

#: `source: "/shop/:path*"` and friends, as written in the configuration.
REWRITE_PATTERN = re.compile(r'source:\s*"([^"]+)"')


def rewrite_sources() -> list[str]:
    return REWRITE_PATTERN.findall(NEXT_CONFIG.read_text(encoding="utf-8"))


def page_routes() -> list[str]:
    """Return every route that has a page, as a URL path."""
    routes: list[str] = []
    for page in APP_ROUTES.rglob("page.tsx"):
        relative = page.parent.relative_to(APP_ROUTES)
        segments = [segment for segment in relative.parts if not segment.startswith("(")]
        routes.append("/" + "/".join(segments) if segments else "/")
    return routes


def matches(rewrite_source: str, page_url: str) -> bool:
    """Return True when a rewrite could answer for that page's address.

    The rule is exact rather than heuristic: turn the rewrite into a pattern and ask whether it
    matches
    the page's URL. `/shop/:path*` matches `/shop/kosi-s-pot` - which is why it swallowed the
    shopfront -
    while `/shop/:slug/requests/:token*` requires a third segment and cannot match it at all. Two
    earlier
    versions of this guard got that wrong in opposite directions, so it now models what actually
    happens
    instead of reasoning about prefixes.
    """
    if page_url == "/":
        return False
    pattern = "^"
    for segment in rewrite_source.strip("/").split("/"):
        if segment.startswith(":"):
            pattern += "/(?:[^/]+"
            pattern += ".*)?" if segment.endswith("*") else ")"
        elif "*" in segment:
            pattern += "/.*"
        else:
            pattern += f"/{re.escape(segment)}"
    pattern += "/?$"
    return re.match(pattern, page_url) is not None


def ends_in_a_wildcard(source: str) -> bool:
    """Return True when a rewrite's last segment is a parameter or a catch-all.

    This is the distinction that matters, and getting it wrong twice is why it is spelled out. A
    rewrite
    ending in `:path*` can match **anything** under its prefix, pages included. A rewrite like
    `/shop/:slug/requests` ends in a literal, so it can only ever match one shape of address, and
    the
    pages beneath the same prefix are untouched. The first version of this guard compared literal
    prefixes only and would have failed the correct configuration - a check that cries wolf is a
    check
    somebody deletes.
    """
    last = source.strip("/").split("/")[-1]
    return last.startswith(":") or "*" in last


def literal_prefix(source: str) -> str:
    """Return the part of a rewrite source that is not a wildcard or a parameter.

    The leading slash is dropped before splitting, and that is the whole bug this function had:
    splitting
    `"/api/:path*"` gives an empty first segment, the loop broke on it immediately, and **every**
    rewrite
    reported a prefix of `/` - which the guard then skipped as too broad to judge. It passed the
    broken
    configuration it was written to catch, which is the same failure it exists to prevent, one level
    up.
    """
    parts: list[str] = []
    for segment in source.strip("/").split("/"):
        if segment.startswith(":") or "*" in segment:
            break
        parts.append(segment)
    return "/" + "/".join(parts)


@pytest.mark.architecture
def test_no_rewrite_shadows_a_page_route() -> None:
    """A rewrite that covers a page turns that page into whatever the API answers."""
    sources = rewrite_sources()
    assert sources, "no rewrites were found; this guard is reading the wrong file"

    routes = page_routes()
    assert routes, "no page routes were found; this guard is reading the wrong directory"

    swallowed: list[str] = []
    for source in sources:
        for route in routes:
            # A page address as it really appears, with its dynamic segments stood in for.
            sample = re.sub(r"\[[^]]+\]", "sample", route)
            if matches(source, sample):
                swallowed.append(f"{source} covers the page at {route}")

    assert not swallowed, (
        "these rewrites are proxied to the API and will answer with JSON instead of a page: "
        + "; ".join(swallowed)
    )
