# The profile

A person's facts live in their OpenSelf profile: one folder, one Markdown file per employment and
per assignment, with its own git history. The format is defined in
[`openself/SPEC.md`](../openself/SPEC.md), and [`openself/example/`](../openself/example/) is a
complete fictional profile. This file says how OpenVita uses it and how an assistant fills it in.

The profile is the only source of facts for the person's CVs and forms.

## Where it is

`make profile-path C=<name>`. By default `local/<name>/profile/`. `local/<name>/openvita.json`
(`{"profile": "<path>"}`, set by `make connect`) can point anywhere else: a profile folder, or an
OpenSelf home (made from openself-template) whose `profile/` holds the entries. The profile is its
own git repository; the person's folder ignores it.

Source documents (old CVs, LinkedIn PDF, exports) stay in `local/<name>/private/intake/`.

## Reading it

1. Start with `INDEX.md`: every employment and assignment, technology with the assignments that
   show it, and open questions. It is generated; never edit it.
2. Open or grep only the entries you need: `assignments/<id>.md`, `employments/<id>.md`.
3. Respect what the entries say about presentation (SPEC sections 5 and 8):
   - `customer_public`: name the customer only when it is `public`. `anonymised` and `unknown` use
     `customer_alias` or the sector. `nda`: leave it out unless the person says otherwise.
   - `⚑ omit` and `⚑ emphasis` flags are standing wishes, in every CV.
   - The private reference section never goes in a CV or form.
   - Facts with `confidence: old-cv`, `linkedin` or `needs-confirmation` may be used, but say in
     `notes.md` which ones, so the person can confirm.
4. Cite ids: list the entries a CV is built from in the application's `notes.md`, as
   `<id>#<section>`. Drafts carry the ids in `data-entry` attributes.

## Writing it

Entries are written in the profile's language (`languages` in `openself.json`), with that
language's section headings from `openself/labels/<lang>.json`. Field names stay English.

- A new entry: `make profile-new C=<name> TYPE=assignment ARGS='kind=client employment=<id>
  customer="Acme AS" role=Architect start=2026-01 end=ongoing'`, then fill the sections. The id is
  the file name and never changes.
- `confidence` says where a fact came from: `old-cv`, `linkedin`, `stated` (the person said it),
  `verified` (the person checked the entry).
- Unknown is empty, never a guess. Conflicts between sources are `- ⚑ conflict: ...`, open
  questions `- ⚑ question: ...`, resolved by the person only.
- Use the canonical names from `openself/tech-names.txt` in `tech`.
- Remove an entry by moving it to `_removed/` (`python3 -m openself remove`), never by deleting.
- After editing: `make profile-index C=<name>` and `make lint-profile C=<name>` (0 errors), then
  `make profile-commit C=<name> ID=<id> MSG="<what changed, and from what>"`. One change, one
  commit: the person can go back to any version (`make profile-log`, `make profile-restore`).

## Rules of engagement

0. **Never back-fill.** If a CV claim is not supported by the profile, weaken or remove the claim.
   The profile changes only when the person gives new facts, asks to correct an entry, or edits it
   themselves.
1. **Do not compress.** If the person gives eight facts in one sentence, keep all eight.
2. **Keep their words.** Quote their phrasing for tone (in the "own words" section when it is worth
   keeping verbatim); do not introduce terms they did not use.
3. **Ask in numbered lists, one entry at a time.** Stay on that employment or assignment until the
   person says "next". Note other open threads at the end instead of asking about them.
4. **Do not ask about presentation while gathering.** Wording and emphasis are decided when a CV is
   built. Whether a customer may be named is a fact, and goes in `customer_public`.
5. **Refer by id and section** when presenting an entry back, with the bullets numbered, so the
   person can correct by reference ("in vestkraft, contribution 2: ...").
6. **When told something is missing or compressed, rewrite the section** from the conversation.
7. **Audit after each round:** facts captured, places your wording replaced theirs, questions not
   answered. `make lint-profile` lists the gaps (prompts); they are the next questions.
8. **Set `last_reviewed`** on every entry you change.
