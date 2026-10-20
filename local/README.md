# Local data

Everything personal lives here: one folder per person, for example `local/kari/`, and notes about
employers and brokers in `local/customers/`. Everything in `local/` is in `.gitignore` (except this
README and the customer template): it stays on your machine and is never pushed.

Create a folder with `make new-person C=kari [PROFILE=<path>]`, or `/onboard` in Claude Code. Then
work in it with `make serve C=kari`, the browser workbench described in the root `README.md`.
Set `OPENVITA_LOCAL` to keep these folders somewhere else.

```
local/kari/
  openvita.json         where the profile is, extra template folders, CV language, default template
  AGENTS.md             your standing wishes for an assistant
  tuning.md             what the assistant has learned from your feedback in the workbench
  feedback.json         your comments and requests from the workbench, kept as history
  photo.jpg             optional
  base/generic/cv.html  your general CV, the starting point for every application
  applications/         one folder per application: cv.html, job-ad.md, notes.md, prep.md, forms/
  releases/             numbered PDFs of versions you sent (make release)
  profile/              your OpenSelf profile, unless openvita.json points elsewhere; its own git history
  private/intake/       old CVs, LinkedIn PDF and other source material, never copied into a CV as is
```

`local/forbidden.txt` (optional): words that must never appear in the openvita repository, one per
line, such as your employer's or customers' names. The guard (`make hooks`) checks every commit and
push for them, along with the names in your profile and your company's templates.

`openvita.json`, all keys optional:

```json
{
  "profile": "~/my-openself",
  "templates": ["~/work/cv-templates"],
  "language": "en",
  "template": "classic",
  "customers": "named"
}
```

`customers`: `named` (the default) names customers where the profile allows it (`customer_public:
public`); `hidden` names none, only each customer's alias or sector, for a CV that may travel
further. `make draft CUSTOMERS=hidden` does the same for one draft.

Application folders are named `yyyy-mm-company-role`. The workbench creates them from a pasted job
ad ("New" under Applications), or use `make new C=kari APP=2026-11-acme-platform`.

Keep it encrypted and on every machine with `make connect-home C=kari HOME=~/my-openself`: the
folder moves into your OpenSelf home as the vault `cv/` and `local/kari` links to it (see the root
README). Your own templates go in `local/kari/templates/`.

Your folder is its own local git repository. **Save** in the workbench (or `make save C=kari`) takes
a snapshot, and the clock button lists the snapshots of the CV you are looking at.
`make release C=kari` saves the next numbered version (v1, v2, ...) as a PDF in `releases/` and tags
it. Back the folder up yourself (for example to a private repository): nothing here is pushed.
