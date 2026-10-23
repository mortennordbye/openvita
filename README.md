# OpenVita

**[Docs](https://mortennordbye.github.io/openself/openvita/)** ·
[OpenSelf](https://github.com/mortennordbye/openself) ·
[Templates](TEMPLATES.md)

An open CV builder on top of [OpenSelf](https://github.com/mortennordbye/openself). It turns your
profile into CVs: a first draft straight from the profile, then a workbench in the browser where
you select text and say what to change, while an assistant such as Claude Code does the edits.
Bring your own template, or your company's. Everything stays on your machine.

[![From profile to PDF: the profile goes through OpenSelf's public view into a first draft; in the workbench the CV is a PDF rebuilt on every save, edited by the assistant from your comments, in the template you choose; make release keeps the PDF you sent](https://raw.githubusercontent.com/mortennordbye/openself/main/docs/assets/diagrams/openvita-flow.png)](https://raw.githubusercontent.com/mortennordbye/openself/main/docs/assets/diagrams/openvita-flow.png)

## Start

Needs Python 3.10+, git and Docker (PDFs render in a container). Try it with the fictional example
profile:

```sh
git clone --recurse-submodules https://github.com/mortennordbye/openvita.git
cd openvita
make new-person C=ola PROFILE=openself/example
make serve C=ola
```

With your own profile, made from
[openself-template](https://github.com/mortennordbye/openself-template) (no profile yet? see
[getting started](https://mortennordbye.github.io/openself/getting-started/)):

```sh
make connect-home C=<you> HOME=~/path/to/your-home   # your CVs are kept encrypted in the home
make serve C=<you>
```

## Day to day

| Command | What it does |
|---|---|
| `make serve C=<you>` | The workbench: your CVs as PDFs, revisions, comments for the assistant |
| `make ai C=<you>` | Start Claude Code watching the workbench |
| `make draft C=<you> [TEMPLATE=sidebar]` | A complete CV from the profile |
| `make new C=<you> APP=2026-11-acme-platform` | An application, with the job ad next to its CV |
| `make release C=<you> APP=...` | Keep the PDF you sent, numbered and tagged |
| `make templates C=<you>` | The templates you can use |

The top of the [Makefile](Makefile) lists every command. Templates (built in: `classic`,
`sidebar`, `minimal`, or your own folder) are explained in [TEMPLATES.md](TEMPLATES.md); the
assistant's rules are in [AGENTS.md](AGENTS.md).

## Nothing personal is committed

Your folders live in `local/`, which git ignores, and a guard (installed as git hooks on first
use) refuses anything personal that slips into a commit: names and details from connected
profiles, templates from outside the repository, and any word you list in `local/forbidden.txt`,
such as your employer's name.

## License

MIT, see [LICENSE](LICENSE). Bundled: Metropolis (public domain), Albert Sans (SIL OFL 1.1),
Font Awesome Free 5 (SIL OFL 1.1 for the fonts), pdf.js (Apache 2.0), marked (MIT).
Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).
