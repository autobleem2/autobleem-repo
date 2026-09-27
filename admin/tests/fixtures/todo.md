# What is left (trimmed fixture, 2026-09-27)

A trimmed copy of the real `docs/todo.md`'s shape, for `test_roadmap.py` - real rows, cut down to the
columns and quirks the parser must handle: a struck-through (done) row, a row with a `|` inside backticks,
a row with no `Team:`, and a row whose milestone code (`a4`) is not in the trimmed `roadmap.md` fixture.

## R - Release and process

| ID | What | Where | Size | Who | Ms |
|---|---|---|---|---|---|
| R1 | **Replace `v2.0.0-alpha2` with the new alpha2** (the owner, 2026-09-26): the old alpha2 stays on the testing channel until the new one exists. Team: infrastructure. | all component repos, site | M | dev | a2 |
| R9 | Code signing through SignPath: apply, publish the policy, five projects. Parked by the owner. | pc-tools, launcher | M | owner | rc |
| R21 | ~~**A PC test machine + a second CI runner**~~ **done 2026-09-27** (Wren Aldercroft): `bleemmachine` online, label `ab-main`. Team: task force (Wren Aldercroft). | PC-USB box, CI | M | dev | a2 |
| R99 | Fenced this year for the alpha4 pass (no milestone yet in the trimmed roadmap fixture, on purpose). | somewhere | S | dev | a4 |

## K - Kernel and kernel payload

| ID | What | Where | Size | Who | Ms |
|---|---|---|---|---|---|
| K14 | **PC stick install/update fails on bookworm: `pkg_first_available` always picks its first name** (found by Wren): the probe `apt-cache policy X | grep -q '^  Candidate: [^(]'` makes apt-cache die of SIGPIPE. Fix: `grep ... >/dev/null` without -q. Team: software/ui (Marcus). | installer, pcusb, rpi | S | dev | a2 |

## D - Documentation and repository hygiene

| ID | What | Where | Size | Who | Ms |
|---|---|---|---|---|---|
| D16 | Delete merged branches and workspaces - pending the owner's OK. | server | S | dev | later |
