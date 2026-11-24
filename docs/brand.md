# Brand

How to use erdify's logo and colours: in these docs, in READMEs, and in tools built on
erdify such as [erdify-studio](https://github.com/devsuit-berlin/erdify-studio).

## Logo

| Asset | File | Use |
| --- | --- | --- |
| Icon | `docs/assets/erdify-icon.svg` (`-512.png`, `-1024.png`) | Avatars, app icons, the docs header, square spaces |
| Wordmark, light | `docs/assets/erdify-wordmark-light.svg` (`.png`) | On white or light backgrounds |
| Wordmark, dark | `docs/assets/erdify-wordmark-dark.svg` (`.png`) | On dark backgrounds |
| Favicon | `docs/assets/favicon.png` (64 px) | Browser tabs on the docs site |

<p align="center">
  <img alt="erdify icon" src="assets/erdify-icon.svg" width="160">
  &nbsp;&nbsp;
  <img alt="erdify wordmark" src="assets/erdify-wordmark-light.svg#gh-light-mode-only" width="400">
  <img alt="erdify wordmark" src="assets/erdify-wordmark-dark.svg#gh-dark-mode-only" width="400">
</p>

### Anatomy

- **Frame:** a rounded square in indigo (corner radius 224/1024).
- **Entity cards:** two white cards with navy headers, a yellow key dot and lavender field
  bars. They stand for two tables.
- **Relation:** a white line with round caps from one card to the other, with a bar at
  the start and a crow's foot at the end: a one-to-many relationship.
- **Wordmark:** the icon next to "erdify", with "erd" in indigo and "ify" in navy. The
  dark variant uses periwinkle and white.

### Usage

- **Clear space:** keep at least a quarter of the icon's height free on every side.
- **Minimum size:** icon 16 px (favicon), wordmark 120 px wide.
- **Light/dark:** use the light wordmark on light backgrounds and the dark one on dark
  backgrounds. In READMEs, switch with `<picture>` and `prefers-color-scheme`. On the docs
  site, which has its own light/dark toggle, use two `<img>` with GitHub's
  `#gh-light-mode-only` / `#gh-dark-mode-only` fragments instead (as above); the site's
  stylesheet hides the wrong one for the selected palette. The icon works on both.
- **README and PyPI:** reference the assets by absolute `raw.githubusercontent.com` URLs
  on `main`. PyPI renders the README as the long description, and relative paths break
  there. erdify's README heading:

  ```html
  <p align="center">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/devsuit-berlin/erdify/main/docs/assets/erdify-wordmark-dark.svg">
      <img alt="erdify" src="https://raw.githubusercontent.com/devsuit-berlin/erdify/main/docs/assets/erdify-wordmark-light.svg" width="420">
    </picture>
  </p>
  ```

### Don'ts

- Don't recolour, stretch, rotate or add effects (shadows, gradients, outlines).
- Don't type the wordmark in a font. It's outlined paths: use the SVGs.
- Don't put the light wordmark on a dark background, or the other way round.
- Don't use erdify's icon for a tool built on erdify. Give the tool its own variant (see
  [Family](#family)).

## Colours

The devsuit palette, also used by the docs theme (`docs/stylesheets/extra.css`).
Contrast ratios are WCAG 2.x.

| Name | Hex | Role | Contrast |
| --- | --- | --- | --- |
| Indigo | `#4150AA` | Primary, icon frame, "erd", links (light) | 7.11:1 on white |
| Indigo light | `#6573C3` | Primary, light variant | 4.38:1 on white: large text and UI only |
| Navy | `#192346` | Card headers, "ify", dark primary | 15.33:1 on white |
| Cyan | `#18B4E0` | Accent on dark backgrounds | 2.43:1 on white: **don't use for text on light** |
| Cyan dark | `#087F9E` | Accent on light backgrounds, link hover | 4.63:1 on white (AA) |
| Periwinkle | `#8C9EFF` | "erd" and links on dark backgrounds | 6.48:1 on `#1E2129` (a dark background like Material's slate scheme) |
| Yellow | `#F5DC19` | Key dot only (decorative) | 1.39:1 on white: never text |
| Lavender | `#C5CAE9` | Field bars only (decorative) | — |
| White | `#FFFFFF` | Cards, relation line, "ify" on dark | 7.11:1 on indigo |

## Typography

- **Docs site:** MkDocs Material's theme fonts (Roboto, Roboto Mono).
- **Wordmark:** outlined paths, never live text. Edit the SVGs instead of retyping them.

## Family

Tools built on erdify share its frame, palette, entity cards and relation line, and add
one element of their own. They also keep "erdify" in the wordmark, drawn with erdify's
glyphs.

| Tool | Own element | Brand guide |
| --- | --- | --- |
| [erdify-studio](https://github.com/devsuit-berlin/erdify-studio) | The lower card is lifted out of a dashed cyan slot, with a pointer on its header. "studio" is a monoline word in cyan dark (light) or cyan (dark) | [erdify-studio `docs/brand.md`](https://github.com/devsuit-berlin/erdify-studio/blob/main/docs/brand.md) |

If erdify's icon or palette changes, update the family to match.

## Changing the assets

The SVGs are the sources. Regenerate the PNGs with `rsvg-convert` (from librsvg, e.g.
`brew install librsvg` or `apt install librsvg2-bin`), from `docs/assets/`:

```bash
rsvg-convert -w 1024 erdify-icon.svg -o erdify-icon-1024.png
rsvg-convert -w 512 erdify-icon.svg -o erdify-icon-512.png
rsvg-convert -w 64 erdify-icon.svg -o favicon.png
rsvg-convert -h 1120 erdify-wordmark-light.svg -o erdify-wordmark-light.png
rsvg-convert -h 1120 erdify-wordmark-dark.svg -o erdify-wordmark-dark.png
```
