"""``scripts/mkdocs_raw_html_urls.py``: relative URLs in raw HTML, resolved for the page URL.

Needs mkdocs (the ``docs`` dependency group): skipped without it. The docs workflow runs
it with ``uv run --group docs pytest tests/test_mkdocs_hook.py``.
"""

import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("mkdocs")

from mkdocs.config.defaults import MkDocsConfig  # noqa: E402
from mkdocs.structure.files import File, Files  # noqa: E402
from mkdocs.structure.pages import Page  # noqa: E402

SCRIPT = Path(__file__).parent.parent / "scripts" / "mkdocs_raw_html_urls.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mkdocs_raw_html_urls", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()

FILES = Files(
    [
        File(path, "docs", "site", use_directory_urls=True)
        for path in ["index.md", "brand.md", "a/b.md", "img.png", "assets/x.svg"]
    ]
)


def _render(html: str, page_path: str = "brand.md") -> Any:
    file = FILES.get_file_from_path(page_path)
    assert file is not None
    config = MkDocsConfig()
    page = Page(None, file, config)
    return hook.on_page_content(html, page=page, config=config, files=FILES)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<img src="assets/x.svg">', '<img src="../assets/x.svg">'),
        (
            '<img src="assets/x.svg#gh-dark-mode-only">',
            '<img src="../assets/x.svg#gh-dark-mode-only">',
        ),
        ('<img src="assets/x.svg?v=1">', '<img src="../assets/x.svg?v=1">'),
        (
            '<source srcset="assets/x.svg, assets/x.svg 2x">',
            '<source srcset="../assets/x.svg, ../assets/x.svg 2x">',
        ),
        ('<source srcset="assets/x.svg\t2x">', '<source srcset="../assets/x.svg 2x">'),
        ('<source srcset="assets/x.svg, ">', '<source srcset="../assets/x.svg">'),
        ("<img src='assets/x.svg'>", "<img src='../assets/x.svg'>"),
    ],
)
def test_resolves_relative_urls_for_the_page_url(html: str, expected: str) -> None:
    assert _render(html) == expected


@pytest.mark.parametrize(
    "html",
    [
        '<img src="https://example.com/a.svg">',
        '<img src="/assets/x.svg">',
        '<img src="#top">',
        '<img src="tel:+49123">',
        '<img data-src="assets/x.svg">',
        '<source srcset="data:image/svg+xml,a,b">',
        "<code>src=&quot;assets/x.svg&quot;</code>",  # escaped in a code block
    ],
)
def test_leaves_non_relative_and_non_attribute_urls_alone(html: str) -> None:
    assert _render(html) == html


def test_leaves_a_url_that_already_works_for_the_page_alone() -> None:
    # A Markdown image MkDocs already rewrote: a/b.md is served at a/b/.
    html = '<img src="../../img.png">'
    assert _render(html, "a/b.md") == html


def test_root_page_urls_stay_as_they_are() -> None:
    assert _render('<img src="assets/x.svg">', "index.md") == '<img src="assets/x.svg">'


def test_a_url_that_names_no_file_is_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    html = '<img src="assets/missing.svg">'
    with caplog.at_level(logging.WARNING):
        assert _render(html) == html
    assert "'assets/missing.svg' names no file in docs/" in caplog.text
