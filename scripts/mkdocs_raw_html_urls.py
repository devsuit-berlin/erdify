"""MkDocs hook: resolve relative ``src``/``srcset`` URLs in raw HTML for the page's URL.

MkDocs rewrites relative links and images written in Markdown, but not raw HTML
(``<img>``, ``<picture><source srcset>``). With directory URLs ``docs/brand.md`` is
served at ``brand/``, so ``src="assets/x.svg"`` would load ``brand/assets/x.svg``.
This hook rewrites those URLs the way MkDocs rewrites Markdown links, so the same HTML
works on GitHub (relative to the file) and on the docs site. A relative URL that names
no file in ``docs/`` is a warning, so ``mkdocs build --strict`` fails on it.

Enabled via ``hooks:`` in ``mkdocs.yml``.
"""

from __future__ import annotations

import logging
import posixpath
import re
from typing import Any
from urllib.parse import unquote

from mkdocs.structure.files import File, Files
from mkdocs.structure.pages import Page
from mkdocs.utils import get_relative_url

log = logging.getLogger(f"mkdocs.hooks.{__name__}")

# Attribute values in the rendered HTML, in single or double quotes. The lookbehind keeps
# `data-src=` and the like out.
_ATTR = re.compile(r'(?<![\w-])(?P<attr>src|srcset)=(?P<q>["\'])(?P<value>.+?)(?P=q)')
# Code is example text, not markup: an inline code span keeps its quotes
# (`<img src="x">` renders as <code>&lt;img src="x"&gt;</code>), so skip it entirely.
_CODE = re.compile(r"<code\b.*?</code>", re.DOTALL | re.IGNORECASE)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")  # https:, data:, mailto:, ...


def _is_relative(url: str) -> bool:
    return not (url.startswith(("/", "#")) or _SCHEME.match(url))


def _file(base: str, path: str, files: Files) -> File | None:
    # The URL may be percent-encoded ("my%20logo.svg"); the file path is not.
    return files.get_file_from_path(posixpath.normpath(posixpath.join(base, unquote(path))))


def _resolve(url: str, page: Page, files: Files) -> str:
    if not _is_relative(url):
        return url
    # Only the path names a file; a query or fragment is kept as it is.
    split = min((i for i in (url.find("?"), url.find("#")) if i != -1), default=len(url))
    path, suffix = url[:split], url[split:]
    # Already right for the page URL (e.g. a Markdown image MkDocs rewrote): leave it.
    # This check comes first, so a path that names a file both relative to the page URL
    # and relative to the source file is taken as page-relative.
    if _file(posixpath.dirname(page.url), path, files) is not None:
        return url
    file = _file(posixpath.dirname(page.file.src_uri), path, files)
    if file is None:
        log.warning(f"{page.file.src_uri}: raw HTML URL {url!r} names no file in docs/")
        return url
    return get_relative_url(file.url, page.url) + suffix


def _resolve_srcset(value: str, page: Page, files: Files) -> str:
    if value.startswith("data:"):
        return value  # may contain commas; not a list of file URLs
    # "a.svg, b.svg 2x": each candidate is a URL plus an optional descriptor.
    candidates = []
    for candidate in value.split(","):
        parts = candidate.split(None, 1)  # any whitespace before "2x"
        if not parts:
            continue  # "a.svg, " or "a.svg,,b.svg"
        url, *descriptor = parts
        candidates.append(" ".join([_resolve(url, page, files), *descriptor]))
    return ", ".join(candidates)


def on_page_content(html: str, *, page: Page, config: Any, files: Files) -> str:
    def rewrite(match: re.Match[str]) -> str:
        value = match["value"]
        if match["attr"] == "srcset":
            new = _resolve_srcset(value, page, files)
        else:
            new = _resolve(value, page, files)
        return f"{match['attr']}={match['q']}{new}{match['q']}"

    # Rewrite only outside <code> elements; the code itself is kept as it is.
    out, pos = [], 0
    for code in _CODE.finditer(html):
        out += [_ATTR.sub(rewrite, html[pos : code.start()]), code[0]]
        pos = code.end()
    out.append(_ATTR.sub(rewrite, html[pos:]))
    return "".join(out)
