# OpenVita

An open CV builder on top of [OpenSelf](https://github.com/mortennordbye/openself). Your profile
(who you are and everything you have done, in your own words) stays in one OpenSelf profile; OpenVita
reads it and writes CVs from it, each one tailored to a role, a customer or a language, and each
one traceable back to the profile entries it is built from.

Status: just started. Nothing to run yet.

## Plan

- Read a profile with the `openself` library (a git submodule here, standard library only).
- Choose what goes in: which assignments, which technologies, how much detail, respecting the
  profile's rules (`customer_public`, `omit` flags and the private `reference` section are never
  shown).
- Write the CV as Markdown, HTML and PDF from templates you can change.
- Keep every CV as a version, linked to the profile revision it came from.

## Layout

```
openself/    the OpenSelf library and format (git submodule)
```

After cloning: `git submodule update --init`.

## License

MIT.
