"""``scripts/mkdocs_raw_html_urls.py``: relative URLs in raw HTML, resolved for the page URL.

Needs mkdocs (the ``docs`` dependency group): skipped without it. The docs workflow runs
it with ``uv run --group docs pytest tests/test_mkdocs_hook.py``.
"""

import importlib.util
import logging
import textwrap
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
        for path in [
            "index.md",
            "brand.md",
            "a/b.md",
            "img.png",
            "assets/x.svg",
            "assets/my logo.svg",
        ]
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
        ('<img src="assets/my%20logo.svg">', '<img src="../assets/my%20logo.svg">'),
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
        '<pre><code class="language-html">&lt;img src="assets/missing.svg"&gt;</code></pre>',
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


def test_an_inline_code_span_is_left_alone_and_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Markdown keeps the quotes in a code span, so the attribute pattern would match it.
    import markdown

    html = markdown.markdown('See `<img src="assets/missing.svg">`, then <img src="assets/x.svg">.')
    assert '<code>&lt;img src="assets/missing.svg"&gt;</code>' in html
    with caplog.at_level(logging.WARNING):
        out = _render(html)
    assert out == html.replace('src="assets/x.svg"', 'src="../assets/x.svg"')
    assert caplog.text == ""


def _build_site(tmp_path: Path, brand: str) -> None:
    from mkdocs.commands.build import build
    from mkdocs.config import load_config

    docs = tmp_path / "docs"
    (docs / "assets").mkdir(parents=True)
    (docs / "assets" / "x.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (docs / "index.md").write_text("# Home\n")
    (docs / "brand.md").write_text(brand)
    config_file = tmp_path / "mkdocs.yml"
    config_file.write_text(
        textwrap.dedent(f"""\
            site_name: test
            strict: true
            hooks:
              - {SCRIPT}
            """)
    )
    build(load_config(str(config_file), site_dir=str(tmp_path / "site")))


def test_a_strict_build_rewrites_raw_html_for_the_page_url(tmp_path: Path) -> None:
    _build_site(tmp_path, '# Brand\n\n<p><img alt="x" src="assets/x.svg"></p>\n')
    html = (tmp_path / "site" / "brand" / "index.html").read_text()
    assert 'src="../assets/x.svg"' in html


def test_a_broken_raw_html_path_fails_a_strict_build(tmp_path: Path) -> None:
    from mkdocs.exceptions import Abort

    with pytest.raises(Abort, match="strict mode"):
        _build_site(tmp_path, '# Brand\n\n<p><img alt="x" src="assets/missing.svg"></p>\n')
