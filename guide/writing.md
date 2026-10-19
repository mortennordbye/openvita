# Writing a CV

How a CV is written from a profile, whoever writes it: the person, an assistant, or `make draft`
followed by an edit. A company that has its own rules keeps them in its own template folder or in
the person's `local/<name>/AGENTS.md`; they apply on top of these.

## 1. Facts

- Every claim must be backed by the profile (see `profile.md`).
- A claim that is not backed is weakened or removed. Never add to the profile to justify a claim.
  Only the person adds facts, in their own words.
- Numbers (scale, users, servers, time saved) only when the profile has them. No estimates dressed
  as facts.
- Seniority shows in what the person owned and decided, not in adjectives.

## 2. Language

- One language per CV: the language of the job ad, else the person's CV language
  (`openvita.json`, else the profile's first language).
- Technology keeps its canonical English name (Kubernetes, Infrastructure as Code, CI/CD), as
  listed in `openself/tech-names.txt`. Do not translate these.
- Spell out a niche acronym the first time: "Azure Monitor Baseline Alerts (AMBA)". Well known
  ones (CI/CD, GDPR) need no expansion.

## 3. Voice

- A third-person CV has no pronouns: start with the action. "Led the upgrade of around 40
  servers", not "I led" and not "She led". A first-person variant (for example `base/first-person`)
  is a separate CV the person asks for.
- Do not use "the consultant" or "the candidate" as a stand-in subject. It reads stiff.
- Team work stays team work: say "the team" or use the passive where the person did not do it alone.
- No filler superlatives (robust, cutting-edge, world-class, passionate). Scale and outcomes carry
  the message.

## 4. Titles and names

- Job titles are the real titles held, as the employer used them. A reference check must find the
  same title. Responsibilities beyond the title go in the text, never in the title.
- No employer-internal jargon: say what it is, not what it was called inside the company.
- Customers are named only when the assignment has `customer_public: public`. Otherwise use its
  `customer_alias`, or the sector ("a public agency", "a customer in health care"). `unknown`
  counts as not nameable. An `nda` assignment is left out unless the person says otherwise.

## 5. Structure

The markup is in `../TEMPLATES.md`; what goes in it:

- **Profile**: three or four short paragraphs. Strengths, where the experience comes from, how
  the person works.
- **Key skills**: the technology with the most evidence in the profile (`INDEX.md` ranks it),
  then what the target role asks for.
- **Experience**: one entry per job, newest first.
- **Projects**: one entry per assignment, in two short parts: the context (the customer's need),
  then the person's own contribution and the result.
- **General words in the text, tools in the tags.** The text says what was done and what it gave.
  Product names stay in the text only when they are the point. Tools go in the tags line under
  the entry (`p.tags`), only those in the entry's `tech` field.
- **Dates**: month and year, or years. Allocation and team size go in the text when an ad asks
  for them, and only from the profile (`allocation`, `team_size`).
- **Clearance and certifications** in the side column, only valid ones from the profile.

## 6. Contact and personal data

- The person's own phone, email and town, or the brand's work email and office address when the
  CV uses a company template with a brand.
- Never a home address, birth date or ID number unless the person puts it in and asks for it.
- Everything about the person stays on their machine (`local/` is gitignored).

## 7. Layout

- Layout lives in the template's CSS. A CV adds no styles of its own.
- Check every build with `make png` before it is sent: no entry alone on a page, no heading at the
  bottom of a page, the name on one line.

## 8. Forms

Forms such as a competence matrix are filled from the profile with the same rules, and go back in
the sender's own format (`make form-add`, `make form`).

- "Yes" only when the profile shows it was done, "No" when it does not, "Partly" with the
  description saying which part.
- The description names the customer (as allowed), what was done and the result, in the CV's voice.
- Every claim in a form must hold up against the CV sent with it.
- Fields that are the person's to give (birth year, start date, rate) stay empty until they say.
