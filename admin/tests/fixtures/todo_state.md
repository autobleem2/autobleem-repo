# What is left (trimmed fixture, 2026-10-01)

Rows cut down from the real `docs/todo.md` in today's shape: a seventh `State` column, no strike-through, the
`alpha1` milestone code and a typo in the Ms cell (`EMU-16`).

## RELEASE - Release and process

| ID | What | Where | Size | Who | Ms | State |
|---|---|---|---|---|---|---|
| RELEASE-3 | Masters before the first `release`: some carry CI commits that never went through a release. | all | S | owner | rc | new |

## UIREV - Launcher UI review (the owner approved the list, 2026-09-29)

| ID | What | Where | Size | Who | Ms | State |
|---|---|---|---|---|---|---|
| UIREV-40 | A launcher screen fix. Team: software/ui. | launcher `evoui_launcher_screen.cpp`, themes | S | designer+dev+tester | alpha1 | in progress |
| UIREV-41 | A menu fix, merged and waiting for the check. | launcher `evoui/controls/evoui_menu.cpp` | S | dev+tester | alpha1 | done |
| UIREV-2 | The d-pad hint arrows are readable on the light hint bars (PSC check 2026-09-30: PASS) | core `panel_style.cpp` | S | dev+tester | - | closed |

## EMU - Emulators

| ID | What | Where | Size | Who | Ms | State |
|---|---|---|---|---|---|---|
| EMU-17 | A row whose Ms cell holds a row id by mistake | launcher `rc/launch.sh` | S | dev+tester | EMU-16 | new |
