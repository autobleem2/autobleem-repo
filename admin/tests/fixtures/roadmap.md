# Roadmap - trimmed fixture (2026-09-27)

A trimmed copy of the real `docs/roadmap.md`'s milestone table, for `test_roadmap.py`. Deliberately leaves
out `alpha4` (`a4`), so a `todo.md` row pointing at it (`R99`) is an "unknown milestone" the parser must
not drop or crash on.

## Where we are

| | |
|---|---|
| Last pre-release | `v2.0.0-alpha1` |

## The milestones

| Milestone | Theme | Gate (what "done" means) | Who | Size |
|---|---|---|---|---|
| **alpha2** | Ship what is already built; make the release train work | `promote alpha` runs green end to end | dev + owner decisions | ~2-3 days |
| **alpha3** | The console pass | every nightly feature proven on a console | dev + owner/testers | ~1 week |
| **beta1** | Feature-complete, one of everything | pcsx-abnxt's compatibility pass done | dev + testers | ~2 weeks |
| **rc1 -> 2.0.0** | Release hygiene | signed Windows programs, masters clean | owner + dev | ~1 week |
| **2.1+** | New features | from `docs/ideas.md` and the "later" rows of todo.md | - | - |

## The alpha releases

Not needed by the parser - the per-milestone step tables further down the real file.
