# OpenVita: rules for an assistant

CVs built from a person's OpenSelf profile. The person works in a browser workbench
(`make serve`), where they read the CV, select text and write what to change. You (an assistant
such as Claude Code) write and edit the CVs, keep the profile in the person's own words, and learn
from the feedback.

## Layout

```
guide/                  shared rules
  writing.md              how CVs are written: facts, language, voice, titles, structure
  profile.md              how the profile is read and filled in
TEMPLATES.md            what a template is, where they are found, the markup every template styles
openself/               OpenSelf, the profile format (git submodule): SPEC.md, schema/, labels/,
                        tech-names.txt, example/ (fictional), the library and CLI, the web UI.
                        Change it in its own repository.
templates/<name>/       built-in templates (classic, sidebar, minimal): template.json, cv.css
templates/_shared/      fonts.css and the fonts every template may use
examples/templates/     a fictional company's template, to copy
tools/                  serve.py (workbench), draft.py (CV from the profile), templates.py,
                        render.py and render-worker.py (WeasyPrint in Docker), profiles.py (finds
                        each person's profile), profile_api.py, watch-feedback.py, fill-docx.py,
                        how-it-works.html, static/, vendor/ (pdf.js and marked), tests/
local/                  everything personal, gitignored, one folder per person (`make new-person`)
  <name>/                 its own git repository
    openvita.json           {"profile": path, "templates": [paths], "language": "en"|"nb", "template": name}
    AGENTS.md               the person's standing wishes
    tuning.md               lessons learned from their feedback
    feedback.json           comments and requests from the workbench, kept as history
    photo.jpg               optional
    base/<variant>/cv.html  general CVs (generic, and any variant the person wants)
    applications/<yyyy-mm-company-role>/   cv.html, job-ad.md, notes.md, forms/
    profile/                the profile, unless openvita.json points elsewhere; its own git repository
    private/intake/         old CVs, LinkedIn PDF and other source material, never copied as is
    releases/               numbered PDFs from `make release`
  customers/              notes about employers and brokers that come back, one <name>.md each
build/                  generated PDFs and previews (disposable)
```

## The flow

1. **Instructions**: this file and `guide/` (shared), then the person's `AGENTS.md` and `tuning.md`.
2. **Facts**: the profile (`make profile-path C=<name>`). **Job**: `applications/<app>/job-ad.md`.
3. **Draft**: `make draft` builds a CV from the profile with the export rules applied. It is a
   starting point, not the result: rewrite it for the reader following `guide/writing.md`.
4. **Tailor**: "New application" in the workbench runs `make new` and stores the pasted ad;
   "Tailor CV" queues a request. You write the CV (see "Tailoring a CV to a job").
5. **Review**: the person reads the CV, selects text and comments. You edit and answer.
6. **Learn**: lasting preferences go to `tuning.md`, which step 1 reads next time.

The workbench never calls an AI. It only writes files: `feedback.json` for requests, the `cv.html`
files you edit for results (it rebuilds on every save). Without an assistant session, requests wait.

### Watching for feedback

When the person is in the workbench (or says so), run `make watch-feedback C=<name>` as a
background monitor so each new comment and request reaches you as it is made. Items already open
are printed first. Otherwise handle open items when asked, or when you start work on a CV.

## First time: onboarding

New people run `/onboard` (`.claude/skills/onboard/SKILL.md`). It sets up their folder, reads
what they put in `private/intake/`, writes their profile, interviews them to fill the gaps, and
builds their base CV. The same skill adds a finished assignment to an existing profile.

## Build

Run from the repository root. Rendering happens in the `openvita` Docker image, built on first use.

- `make serve [C=<name>] [VARIANT=<v> | APP=<app>] [PORT=8000]`: the workbench
- `make draft C=<name> [VARIANT=<v> | APP=<app>] [TEMPLATE=<t>] [CVLANG=en|nb] [FORCE=1]`: CV from
  the profile; refuses to replace a CV edited since its last draft unless `FORCE=1`
- `make cv C=<name> [VARIANT=<v> | APP=<app>]`: the PDF, in `build/<name>/...`
- `make png C=<name> [APP=<app>]`: a PNG of each page, for checking the layout
- `make new C=<name> APP=<yyyy-mm-company-role> [TEMPLATE=<t>]`: new application from the base CV
- `make templates [C=<name>]`, `make use-template C=<name> [APP=<app>] TEMPLATE=<t>`
- `make new-person C=<name> [PROFILE=<path>]`, `make connect C=<name> PROFILE=<path>`
- `make save C=<name> MSG="..."`: snapshot the person's folder
- `make release C=<name> [APP=<app>] [TAG=<label>]`: the next numbered PDF in `releases/`, tagged
- `make versions C=<name>`
- `make profile-path|profile-index|lint-profile|profile-new|profile-commit|profile-log|profile-restore|profile-as-of C=<name> ...`
- `make form-add C=<name> APP=<app> FORM=<file.docx>`, `make form C=<name> APP=<app>`
- `make test`

## Tailoring a CV to a job

When someone pastes a job ad or names a role, or the workbench sends a `generate` request:

1. `make new C=<name> APP=<yyyy-mm-company-role>` and save the ad in its `job-ad.md`. (The
   workbench has already done this for a `generate` request.)
2. Read the profile the way `guide/profile.md` says: `INDEX.md` first, then the entries that match
   (grep `tech`, sector, role), with their flags and `customer_public`. Then the person's
   `AGENTS.md` and `tuning.md`, and `local/customers/<company>.md` if it exists.
3. Pick the experience, projects and skills that match the ad. Reorder and reframe, but do not
   invent anything.
4. Edit the application's `cv.html` following `guide/writing.md`, in the markup of `TEMPLATES.md`.
   Write a short `notes.md` on what was emphasised and why, listing the profile ids each part is
   built from (`<id>#<section>`).
5. `make png` and check the layout still holds.
6. Write in the language of the ad.
7. If you learned something about the company that will matter next time, add it to
   `local/customers/<company>.md`.
8. If the person's feedback shows a lasting preference, add a bullet to their `tuning.md`.

Leave `base/` alone unless the person asks for their general CV to change.

### Word forms (competence matrix and the like)

1. `make form-add C=<name> APP=<app> FORM=<file.docx>`. The original is kept as is in `forms/`,
   and `forms/<form>.json` gets one entry per table row with empty cells. Never edit the .docx.
2. Write the answers in `fill`, following the forms section of `guide/writing.md`. A newline
   starts a new paragraph in the cell. Leave fields the profile does not cover empty.
3. `make form C=<name> APP=<app>`: fills only cells that were empty, keeps every other byte, and
   renders a PDF with LibreOffice for checking.
4. Tell the person which fields were left for them (birth year, start date, rate).

## Handling feedback

Each item in `local/<name>/feedback.json` has `kind` (`comment`, `generate`, or
`profile-interview`), `file` (the path the selected text is from), `target`, `source`, `quote`,
`comment`, `revision` (set when written on an old revision), `status` (`open`, `done`,
`archived`) and `note`.

| `target` | `source` | What it is |
|---|---|---|
| `<name>/base/<v>`, `<name>/applications/<app>` | `cv`, `job-ad.md`, `notes.md` | A CV, or its ad or notes. |
| `<name>/applications/<app>` | `form:<form>` | A filled form. Edit `forms/<form>.json`, never the .docx. |
| `<name>/raw` | `profile` | The person's profile. `file` is the entry, `section` the section id. |
| `<name>/personal` | `personal` | The person's `AGENTS.md` and `tuning.md`. |
| `doc/prompt` | `prompt` | This file, `guide/` and `TEMPLATES.md`, shared. |
| `doc/how` | `how` | `tools/how-it-works.html`. |

For each open item:

1. A CV comment: `make save C=<name>` before editing, then change the `cv.html` by finding the
   `quote`. A request that needs a fact the profile does not have is not done: say so in `note`.
2. `source: profile` is the person's own words about their profile. Change the profile only when
   the comment says so, in their words (rule 0 in `guide/profile.md`), then `make profile-index`,
   `make lint-profile` and `make profile-commit` for that entry.
3. `source: prompt` or `personal` asks to change the instructions. Personal wishes go in
   `local/<name>/AGENTS.md`. Shared rules change only through a pull request to this repository.
4. `generate`: follow "Tailoring a CV to a job". `profile-interview`: interview the person about
   `entry` (empty: a new one) as phase 3 of the onboarding skill, then index, lint and
   `make profile-commit ACTOR=claude`.
5. Set `status` to `done` with a short `note`. Never delete items: the person archives them.
6. Distill every lasting lesson into `local/<name>/tuning.md`: one bullet with the rule, why and
   source. Skip one-off edits.

## Hard rules

- The profile is the only source of facts. A CV claim it does not support gets weakened or
  removed. Never add to the profile to justify a claim; only the person adds facts, in their own
  words.
- Every change to a profile is committed to its own history (`make profile-commit`, actor
  `claude`), one change per commit, so the person can see and undo it.
- The person also edits the profile in the workbench. Re-read an entry right before you change it.
- A profile in an OpenSelf home is uploaded encrypted with `./self push` there. Leave that to the
  person unless they ask.
- `local/` stays on the person's machine and is gitignored. The guard (`tools/guard.py`, installed
  as git hooks by `make hooks`) refuses commits and pushes that carry local work. Never bypass it
  (`--no-verify`), never force-add anything from `local/`, and
  never copy a person's, employer's or customer's details into shared files (guide/, templates/,
  tools/, the skill, README). A company's template lives in the company's own folder, found
  through `OPENVITA_TEMPLATES`, not in this repository.
- Contact details: the person's own, or the brand's when the CV uses a company template with one.
- Before changing a `cv.html`, run `make save C=<name>` so the previous version can be restored.
- Layout belongs in the template's CSS, never in a CV.
