# Known bugs (trimmed fixture, 2026-10-01)

Rows cut down from the real `docs/bugs.md` in today's shape: State is new / in progress / done / closed, the
platform cell may carry a note, the severity may be `trivial`, and the Fix cell is a todo link, a commit, a
sentence, `wontfix` or `-`.

| BUG | Title | Platform | Severity | State | Found | Fix |
|---|---|---|---|---|---|---|
| BUG-1 | A game starts by itself after leaving Options | psc | major | done | console session 318, 2026-09-27 | [CONSOLE-11](todo.md) |
| BUG-6 | The mouse pointer shows after a Bluetooth pad pairs | psc | major | in progress | console, 2026-09-26 | [KERNEL-6](todo.md) |
| BUG-9 | In-game notices are drawn before the scanlines | psc, rpi, pcusb, win | minor | done | console session 318 | [EMU-15](todo.md) |
| BUG-11 | A notice is missing (pcsx-ab is no longer developed) | psc | minor | closed | console session 318 | wontfix |
| BUG-12 | The Windows dev build crashes after loading a state | win | major | closed | Windows dev build | [EMU-8](todo.md), wontfix |
| BUG-13 | The pad is dead for 1-3 s after every game | rpi | minor | new | Pi 400 | - |
| BUG-21 | A held press runs on after a busy job | all | major | in progress | console | [CONSOLE-13](todo.md), [CONSOLE-12](todo.md) |
| BUG-23 | A fix named by its commit | all | major | done | VM | autobleem-core 8e50061 |
| BUG-25 | A d-pad press skips rows | win (dev build) | minor | in progress | laptop sandbox | doKeyUp() asymmetry fixed; the symptom is still unexplained |
| BUG-30 | No set banner after switching sets | psc (others unchecked) **PSC 2026-10-01: the stick has Showingtimeout=1** | major | in progress | the owner, 2026-09-30 | [UIREV-23](todo.md) |
| BUG-33 | The Wi-Fi panel stutters | rpi (psc unchecked) | minor | done |
| BUG-38 | The Amiga placeholder is square | all | trivial | closed | VM | launcher 6a7f1832 (Amiga 4:5) |
| BUG-40 | A repeat of an earlier report | all | minor | closed | VM | duplicate of BUG-13 |
