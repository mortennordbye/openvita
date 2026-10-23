# OpenVita

An open CV builder on top of [OpenSelf](https://github.com/mortennordbye/openself). Your career
lives in an OpenSelf profile (one Markdown file per job and assignment, with its own history).
OpenVita turns it into CVs: a first draft straight from the profile, then a browser workbench
where you read the CV, select text and say what to change, while an assistant such as Claude Code
does the edits. Bring your own template, or your company's.

It works for you on your own, and for people at a company that has its own CV look.

**[OpenSelf documentation](https://mortennordbye.github.io/openself/)**: how OpenSelf, your
profile repository and OpenVita fit together, and
[getting started](https://mortennordbye.github.io/openself/getting-started/) if you have no
profile yet. OpenVita has its own page there:
[CVs with OpenVita](https://mortennordbye.github.io/openself/openvita/).

[![From profile to PDF: the profile goes through OpenSelf's public view into a first draft; in the workbench the CV is a PDF rebuilt on every save, edited by the assistant from your comments, in the template you choose; make release keeps the PDF you sent](https://raw.githubusercontent.com/mortennordbye/openself/main/docs/assets/diagrams/openvita-flow.png)](https://raw.githubusercontent.com/mortennordbye/openself/main/docs/assets/diagrams/openvita-flow.png)

> **Click to open the full-size image.** Rendered from
> [this file](https://github.com/mortennordbye/openself/blob/main/docs/assets/diagrams/openvita-flow.d2)
> in the OpenSelf repository, where all the diagrams live.

## What you get

- **A draft from your profile.** `make draft` builds a complete CV from the profile, following its
  rules: customers are named only when the profile says they may be, private references and
  anything flagged `omit` stay out, removed entries are never used.
- **A workbench** (`make serve`) on 127.0.0.1: your CVs as real PDF text, rebuilt on every save,
  revisions, applications with the job ad next to the CV, comments for the assistant, Word forms
  filled in place, and your profile in OpenSelf's own editor.
- **Templates you can bring.** Three built in (`classic`, `sidebar`, `minimal`), and any folder of
  your own or your company's. A template is only the look; the same CV moves between them.
- **Versions.** Your folder is its own git repository: every saved revision and every PDF you
  send can be found again.

Everything stays on your machine. `local/` is ignored by git, and a guard makes sure nothing
personal is committed even by accident (see "Keeping local work local" below).

## Start

Requirements: Python 3.10 or newer, git, and Docker (PDFs render in a container, so nothing else
needs installing). With WeasyPrint and poppler installed locally, `OPENVITA_RENDER=local` skips
Docker.

```sh
git clone --recurse-submodules https://github.com/mortennordbye/openvita.git
cd openvita
make new-person C=ola PROFILE=openself/example   # try it with the fictional example profile
make serve C=ola
```

With your own profile:

```sh
make new-person C=kari PROFILE=~/my-openself     # an OpenSelf home or a profile folder
make serve C=kari
```

No profile yet? `make new-person C=kari` creates an empty one. Fill it in the workbench (the
Profile view), or let an assistant interview you: put your old CVs and a LinkedIn PDF in
`local/kari/private/intake/` and run `/onboard` in Claude Code.

## Templates

```sh
make templates C=kari                       # what you can use, and where each comes from
make draft C=kari TEMPLATE=sidebar          # draft in another template
make use-template C=kari TEMPLATE=minimal   # switch an existing CV
```

Your own or your company's templates are folders with `template.json`, `cv.css` and, when the
blocks need to move (columns, boxes, another order), a `layout.html`. Every CV fits every template.
`make new-template T=<name> C=kari` starts one from a built-in, and `make template-check T=<name>`
renders the example profile in it and checks that nothing is lost. Point OpenVita at them in either
of two ways:

- for everyone on this machine: `export OPENVITA_TEMPLATES=~/work/cv-templates`
- for one person: `"templates": ["~/work/cv-templates"]` in `local/<name>/openvita.json`

A company template can carry a brand: logo, name, web address, a work email pattern and an office
address. Those go in the CV only while that template is used. See [TEMPLATES.md](TEMPLATES.md),
and [examples/templates/example-company](examples/templates/example-company) for a complete one.

## Applications

```sh
make new C=kari APP=2026-11-acme-platform   # or "New" under Applications in the workbench
make cv  C=kari APP=2026-11-acme-platform   # PDF in build/kari/applications/...
make release C=kari APP=2026-11-acme-platform   # keep the PDF you sent, numbered and tagged
```

Paste the job ad when you create the application, then "Tailor CV" asks the assistant to write it
from your profile. Before the interview, "Prepare" asks for talking points, stories, likely
questions and gaps for that job, each citing the profile entries it rests on (`prep.md`). The top
of the [Makefile](Makefile) lists every command.

## Working with an assistant

The workbench never calls an AI itself. It writes requests and comments to
`local/<name>/feedback.json`, and an assistant session reads them (`make watch-feedback C=<name>`
prints each one as it arrives). While it runs, the workbench shows "AI connected" and marks each
request the assistant has seen; otherwise it says "No AI connected" and requests wait. To connect
one, run `make ai C=<name>` in this folder: it starts Claude Code, already told to watch your
workbench (clicking the grey chip shows the same steps). [AGENTS.md](AGENTS.md) is the assistant's rule book, and the
guides in [guide/](guide/) say how CVs are written and how the profile is read. The rule that
matters most: the profile is the only source of facts. A claim it does not support is weakened or
removed, never added to the profile to make it fit.

## Layout

```
openself/            OpenSelf (git submodule): the profile format, library and web UI
templates/           built-in templates, and _shared/ fonts any template may use
examples/templates/  a fictional company's template, to copy
tools/               serve.py (workbench), draft.py, templates.py, render.py, profiles.py, ...
guide/               how CVs are written, how the profile is read
local/               your folders (gitignored): local/<name>/ per person
build/               generated PDFs and previews
```

After cloning without `--recurse-submodules`: `git submodule update --init`.

## Encrypted, versioned and on every machine: your OpenSelf home

If your profile lives in an OpenSelf home (made from
[openself-template](https://github.com/mortennordbye/openself-template)), keep your OpenVita work
there too:

```sh
make connect-home C=kari HOME=~/my-openself     # once per person
```

Your folder (CVs, applications, job ads, released PDFs, photo, comments, tuning and your own
`templates/`) moves into a vault of the home, `~/my-openself/cv/`, with its history, and
`local/kari` becomes a link to it. The profile is the home's own. From then on, `make push` in the
home encrypts every version of it into `cv.age` next to `profile.age`, and on another machine
`make pull` there followed by the same `make connect-home` brings it all back. Nothing in it is
ever readable in the repository. `build/` is not included: PDFs are rebuilt from the CVs.

Your own templates can live in `local/kari/templates/`, which OpenVita searches first, so they are
encrypted with the rest. A template your employer owns may not be yours to copy, even encrypted:
keep that one in the company's own repository and point `OPENVITA_TEMPLATES` at it.

## Keeping local work local

Your folders, CVs, job ads, profiles and your company's templates never belong in this repository.
`.gitignore` keeps them out of `git add`, and the guard (`tools/guard.py`) catches the rest: a
forced add, a copied file, a template folder dropped into `templates/`, a profile linked in as a
submodule, or a name from your profile or your company's template in an ordinary file.

- `make hooks` installs it as pre-commit and pre-push hooks. `make serve`, `make new-person` and
  `make connect` install it too, so it is in place from the first use.
- It reads what is private from this machine: every connected profile (names, email, phone,
  employers, customers), every template outside the repository (its name and brand), and the words
  you list in `local/forbidden.txt`, one per line, such as your employer's name.
- CI runs `tools/guard.py --history` on every pull request, for the path rules.
- Something meant to be shared that the guard refuses goes in `.openvita/allow`, one glob per line,
  reviewed like any other change.

## Tests

`make test` runs OpenSelf's tests and OpenVita's own (`tools/tests`), with the host Python and
no Docker.

## License

MIT, see [LICENSE](LICENSE). Bundled: Metropolis (public domain), Albert Sans (SIL OFL 1.1),
Font Awesome Free 5 (SIL OFL 1.1 for the fonts), pdf.js (Apache 2.0), marked (MIT).
