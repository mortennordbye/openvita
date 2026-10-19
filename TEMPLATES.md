# Templates

A template is the look of a CV: layout, colours, fonts and, for a company, its brand. It is not
the content. Every CV uses the same markup (below), so a CV switches template by changing one
link, and the text stays as it was.

## A template is a folder

```
acme/
  template.json      label, description, brand (optional)
  cv.css             the styles, for WeasyPrint
  assets/            logo and other images (optional)
  fonts/             your own fonts (optional)
```

`template.json`:

```json
{
  "name": "acme",
  "label": "Acme",
  "description": "Acme's CV: logo top left, teal accents.",
  "languages": ["en", "nb"],
  "brand": {
    "name": "Acme AS",
    "url": "https://acme.example",
    "logo": "assets/logo.svg",
    "email": "{first}.{last}@acme.example",
    "address": "Main Street 1, Example City"
  }
}
```

- `name` defaults to the folder name: lower case letters, digits, `-` and `_`.
- `brand` is optional. When present, a draft puts a brand block in the CV (logo, name, web
  address), uses the work email made from the pattern (`{first}` and `{last}` from the person's
  name, æ ø å folded to ASCII) and the office address instead of the person's own, and keeps the
  person's phone number. Switching an untouched draft to another template drafts it again, so the
  contact lines follow the brand. A CV that was edited keeps its text: only the stylesheet and
  the brand block change, and `make draft FORCE=1` refreshes the rest.

## Where templates are found

In this order, and the first template with a given name wins:

1. `local/<name>/templates/` and then the `templates` list in `local/<name>/openvita.json`, for one
   person (a folder in an OpenSelf home is encrypted with the rest, see the README),
2. `OPENVITA_TEMPLATES`, folders separated by `:`, for everyone on the machine,
3. `templates/` in this repository.

Each folder in the list is either one template (it has `template.json` or `cv.css`) or a folder of
templates. A company keeps its templates in its own (private) repository and points
`OPENVITA_TEMPLATES` at the checkout. Nothing about the company goes into OpenVita.

Never copy a company's template into this repository's `templates/`: the guard refuses it, and
refuses any file that mentions a template's name or brand from outside the repository.

`make templates C=<name>` lists what was found, and where from. A folder that is not a valid
template is reported, never skipped silently.

## How a CV refers to its template

```html
<link rel="stylesheet" href="template:acme/cv.css">
<img class="brand-logo" src="template:acme/assets/logo.svg" alt="Acme AS">
```

The `template:` links are resolved when the CV is rendered, so the CV does not care where the
template lives. In Docker every template is mounted read-only at `/tpl/<name>/` and the shared
fonts at `/tpl/_shared/`; without Docker a temporary folder of links gives the same layout.
Inside `cv.css`, relative URLs work as usual (`url(fonts/x.woff)`, `url(assets/bg.svg)`), and
the shared fonts are always at `../_shared/`:

```css
@import url(../_shared/fonts.css);   /* Head (Metropolis), Body (Albert Sans), FA, FABrands */
```

## The markup every template styles

This is what `make draft` writes. A CV written or edited by hand keeps to the same classes.

```html
<!-- brand --><div class="brand"> img.brand-logo, p.brand-name, p.brand-url </div><!-- /brand -->
<div class="photo"><img></div>                      only when local/<name>/photo.jpg exists
<header class="header">
  h1.name, p.role,
  div.contact > p.phone | p.email | p.place          each with span.icon.fa-phone|fa-envelope|fa-marker
</header>
<section class="profile"> h2.section, p ... </section>
<aside class="sidebar main"> h2, ul.keys | h2, ul.certs | h2, ul.languages </aside>
<aside class="sidebar social"> h2, p.linkedin | p.github | p.link (span.icon + a) </aside>
<section class="edu"> h2.section, div.entry ... </section>
<h2 class="page-title">Experience</h2>
<section class="timeline experience"> div.entry ... </section>
<h2 class="page-title">Projects</h2>
<section class="timeline projects"> div.entry ... </section>

div.entry: p.date, h3 (title or role), p.org (employer or customer), div.body (p, ul), p.tags
```

- The brand block always sits between the `<!-- brand -->` markers, empty or not.
- `.sidebar` holds what a two-column layout puts in its side column. A one-column template shows
  it in place, after the profile text.
- `h2.page-title` is where a template may start a new page. The built-in templates differ:
  `sidebar` starts page 2 there, `classic` and `minimal` do not.
- Generated blocks carry `data-entry` (and `data-section`) with the profile id they came from.
  Templates can ignore them.
- Icons: `.icon` with one of `fa-phone`, `fa-envelope`, `fa-marker`, `fa-link`, `fa-linkedin`,
  `fa-github`, defined in `_shared/fonts.css`.

## Making one

Copy a built-in template or [examples/templates/example-company](examples/templates/example-company)
to your own folder, point `OPENVITA_TEMPLATES` at its parent, and change the CSS. The workbench
rebuilds on every save of `cv.css`, so you see each change in a second. Check every page with
`make png`: no entry alone on a page, no heading at the bottom of one, the name on one line.

WeasyPrint supports most of CSS for print: `@page` with margin boxes for page numbers, flexbox,
floats, absolute positioning against the page. A layout that differs on page 1 uses `@page :first`
and absolutely positioned blocks, as `templates/sidebar/cv.css` does.

Fonts: use fonts you are allowed to embed in a PDF. Many brand fonts are licensed for a design tool
only; pick a free one of the same width instead.
