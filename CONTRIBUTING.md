# Contributing

Thanks for helping. How OpenVita fits with OpenSelf is in the
[OpenSelf docs](https://mortennordbye.github.io/openself/openvita/).

## Ground rules

- **Nothing personal is ever committed**: no CVs, profiles, job ads, company templates or names
  from them. Personal work lives in `local/` (ignored by git), and the guard refuses the rest.
  Use the fictional example profile (`openself/example`) and `examples/templates/example-company`.
- **Never bypass the guard** (`--no-verify`). Something safe it refuses goes in `.openvita/allow`.
- Changes to the profile format belong in [openself](https://github.com/mortennordbye/openself).

## Flow

1. Fork, branch from `main`, and clone with `--recurse-submodules`.
2. `make hooks` installs the guard as git hooks.
3. Make the change, with a test when it changes behaviour.
4. `make test` (OpenSelf's tests, OpenVita's own, and the example profile lint).
5. Open a pull request. `main` is protected: it needs a pull request and green checks.

## Pull request titles

Titles follow [Conventional Commits](https://www.conventionalcommits.org) and become the squash
commit:

```
feat(workbench): show the job ad next to the CV
fix(draft): keep omitted entries out of the skills list
docs: explain company templates
```
