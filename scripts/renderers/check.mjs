// Render erdify's Mermaid and HTML output with the real Mermaid in headless Chromium.
//
// Usage: node check.mjs OUT_DIR   (OUT_DIR from scripts/render_outputs.py)
//
// - Every OUT_DIR/*.mmd is parsed and rendered with mermaid.render().
// - Every OUT_DIR/*.html page is loaded as a user would open it. Its Mermaid
//   CDN script is answered with the pinned local copy (package.json), and any
//   other network request is blocked, so nothing leaves the runner. The page
//   must render an SVG, show no Mermaid error, and log no console error.
//
// Exits 1 and lists every failing file if one fails.

import { readdir, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";
import puppeteer from "puppeteer";

const require = createRequire(import.meta.url);
const MERMAID_JS = require.resolve("mermaid/dist/mermaid.min.js");
// The CDN script erdify's HTML output loads (generator.MERMAID_CDN).
const CDN_PREFIX = "https://cdn.jsdelivr.net/npm/mermaid@";
const MERMAID_VERSION = require("mermaid/package.json").version;
const MERMAID_MAJOR = MERMAID_VERSION.split(".")[0];

const outDir = process.argv[2];
if (!outDir) {
  console.error("usage: node check.mjs OUT_DIR");
  process.exit(2);
}
const files = (await readdir(outDir)).sort();
const mermaidFiles = files.filter((f) => f.endsWith(".mmd"));
const htmlFiles = files.filter((f) => f.endsWith(".html"));
if (mermaidFiles.length === 0 || htmlFiles.length === 0) {
  console.error(`no .mmd / .html files in ${outDir}`);
  process.exit(2);
}
const mermaidSource = await readFile(MERMAID_JS, "utf8");
const failures = [];

// GitHub's Ubuntu runners restrict the user namespaces Chromium's sandbox
// needs; the pages are erdify's own output, loaded with the network blocked.
const browser = await puppeteer.launch({
  headless: "shell",
  args: process.env.CI ? ["--no-sandbox"] : [],
});
try {
  // Mermaid files: one page, every diagram rendered in turn.
  const page = await browser.newPage();
  await page.setContent("<!DOCTYPE html><html><body></body></html>");
  await page.addScriptTag({ content: mermaidSource });
  await page.evaluate(() => window.mermaid.initialize({ startOnLoad: false }));
  for (const [i, file] of mermaidFiles.entries()) {
    const text = await readFile(path.join(outDir, file), "utf8");
    const error = await page.evaluate(
      async (id, diagram) => {
        try {
          await window.mermaid.parse(diagram);
          const { svg } = await window.mermaid.render(id, diagram);
          return svg.includes("<svg") ? null : "no SVG rendered";
        } catch (e) {
          return String(e && e.message ? e.message : e);
        }
      },
      `d${i}`,
      text,
    );
    if (error) failures.push(`${file}: ${error}`);
  }
  await page.close();

  // HTML files: each page loaded as a browser opens it.
  for (const file of htmlFiles) {
    const error = await checkHtml(browser, path.join(outDir, file));
    if (error) failures.push(`${file}: ${error}`);
  }
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(`${failures.length} file(s) failed to render:`);
  for (const failure of failures) console.error(`  ${failure}`);
  process.exit(1);
}
console.log(
  `Rendered ${mermaidFiles.length} Mermaid diagrams and ${htmlFiles.length} HTML pages ` +
    `with Mermaid ${MERMAID_VERSION}`,
);

async function checkHtml(browser, file) {
  const page = await browser.newPage();
  const problems = [];
  let servedMermaid = false;
  page.on("console", (msg) => {
    if (msg.type() === "error") problems.push(`console error: ${msg.text()}`);
  });
  page.on("pageerror", (err) => problems.push(`page error: ${err.message}`));
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = request.url();
    if (url.startsWith("file:")) return request.continue();
    if (url.startsWith(CDN_PREFIX)) {
      // The page must ask for the major this check renders with.
      const major = url.slice(CDN_PREFIX.length).split(/[./]/)[0];
      if (major !== MERMAID_MAJOR) {
        problems.push(`the page loads mermaid@${major}, the check has Mermaid ${MERMAID_VERSION}`);
      }
      servedMermaid = true;
      return request.respond({
        status: 200,
        contentType: "application/javascript",
        body: mermaidSource,
      });
    }
    problems.push(`unexpected request: ${url}`);
    return request.abort();
  });
  try {
    await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
    // Wait for the end state, the SVG: Mermaid marks the block processed
    // before its async render finishes, and a failed render logs nothing at
    // the default log level. No SVG within the timeout is the failure.
    const rendered = await page
      .waitForSelector("pre.mermaid svg", { timeout: 15000 })
      .then(() => true)
      .catch(() => false);
    if (!servedMermaid) problems.push(`the page does not load Mermaid from ${CDN_PREFIX}…`);
    if (!rendered) {
      problems.push("no SVG rendered");
    } else {
      // A syntax error is rendered too: as an SVG that shows the error.
      const error = await page.evaluate(() =>
        /Syntax error|Parse error/i.test(document.querySelector("pre.mermaid").textContent || ""),
      );
      if (error) problems.push("Mermaid shows an error");
    }
  } catch (e) {
    problems.push(String(e && e.message ? e.message : e));
  } finally {
    await page.close();
  }
  return problems.length ? problems.join("; ") : null;
}
