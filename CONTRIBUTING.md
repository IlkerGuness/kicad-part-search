# Contributing

Bug reports and pull requests are welcome.

- **Bugs**: use the issue template and paste the *Check setup* report — it answers most questions at once.
- **Parts that import wrongly**: include the LCSC number. If easyeda2kicad itself produces the wrong footprint,
  the fix may belong in [easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py).
- **Pull requests**: keep them focused, add or update a unit test, and run
  `python -m unittest discover -s tests` and `python -m pyflakes partsearch tests tools kicad_plugin`.
- **Translations**: copy `partsearch/i18n_tr.py`, translate the values (keep every `%s` / `%d` in the same order),
  and register the language in `partsearch/i18n.py`. The unit tests check that nothing is missing.
- **Library tests** need downloaded fixtures: `python tests/make_fixtures.py` (they are EasyEDA data and are
  not committed).

By contributing you agree that your contribution is licensed under the GPL-3.0-or-later, like the rest of the
project.
