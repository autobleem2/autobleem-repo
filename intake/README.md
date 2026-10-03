# The tester portal: intake service and its contract

The volunteer tester portal (the plan: autobleem-main `docs/tester-portal-plan.md`): volunteers take one ~10-minute
section of a platform's test plan, answer its steps, and send the result; anyone can send an issue report. The site
stays static and read-only; this service (`intake/`) is the only writer, behind Caddy at `/submit/*`. The admin
panel (`admin/`) reads what it stored. This file is the contract the three parts share - the pages
(`tools/repo_index.py`), this service and the panel's tabs. Change it here first, then the code.

## Test plans on the site

- The source is the hub (autobleem-main `testing/<version>/<platform>.yaml`); its CI copies each version's YAML files
  to the site's **`testplans/<version>/<platform>.yaml`** (platforms: `psc`, `rpi`, `pcusb`, `win`).
- A plan: `id`, `title`, `version`, `before_you_start` (list of lines), `sections` - each `{id, title, minutes, needs,
  steps}`, each step `{id, do, expect}` (the `status`/`comment` keys in the files are blanks for people; ignore them).
  Section ids are unique per plan, step ids are `<section id>.<n>`.
- **The current version** = the highest version folder under `testplans/` by `tools/repo_index.py`'s `version_key`.
  The generator writes `testplans/index.json`: `{"current": "<version>", "versions": ["<version>", ...],
  "platforms": {"<platform>": {"title": "...", "sections": N, "minutes": N}}}` (for the current version).

## Endpoints (all JSON unless stated; errors are `{"error": "<message>"}` with 400/404/413/429)

| Method, path | Body / query | Answer |
|---|---|---|
| `POST /submit/claim` | `{platform, version, claim?, release?}` | `{claim, section: {id, title, minutes, needs}, expires}` - without `claim` (or with an expired/closed one): a new claim on the section with the fewest passes for that platform and version (ties: fewest open claims, then plan order); with an open `claim`: the same section again; `release: true` closes the claim unused and answers `{released: true}` |
| `GET /submit/coverage?version=<v>` | `version` optional (default: current) | `{version, target, platforms: {<platform>: {section: {id, title}, passes}}}` - per platform the most needed section only |
| `POST /submit/testplan` | `{platform, version, section, claim, steps: [{id, status, comment}], device?, contact?, website?}` | `{id}` - `status` is `ok` / `problem` / `na`; every step of the section answered once; comment <= 2000 chars, required on `problem`; a missing/foreign claim is accepted but stored as `unassigned: true` |
| `POST /submit/issue` | multipart: `platform`, `version`, `steps`, `expected`, `actual`, `logs` (a `.zip`, optional), `contact` (optional), `consent_logs` (`on`, required with logs), `website` (honeypot) | `{id}` |
| `GET /submit/status/<id>` | - | `{id, kind: "issue" | "testplan", received, state}` - `state` one of `received`, `needs-info`, `to-reproduce`, `bug BUG-N`, `not-a-bug`, `idea`; nothing else of the report |

`id` = 8 random characters `[a-z0-9]`. A filled honeypot `website` is answered like a success (a fake id) and not
stored. Limits: a test result body <= 256 KB, an issue <= 25 MB, `logs` a `.zip` only, total uncompressed <= 100 MB
and no entry path with `..` or a leading `/` (refused, never extracted). Rate limit per client address: 5 per hour,
20 per day for `testplan` + `issue` together, `claim` 30 per hour (the address held only as a salted hash, only for
the window). Text caps: `steps`/`expected`/`actual` 5000, `contact` 200, `device` 200.

## The data directory (`AB_INTAKE_DIR`, a volume; the service never sees the site tree except `testplans/` read-only)

```
testplans/<platform>/<version>/<YYYY-MM-DD>T<HHMMSS>-<id>.json   one result = one section: the request fields +
                                                                received (ISO UTC) + unassigned
claims/<platform>/<version>/<claim>.json      {claim, section, made, expires, closed_by: <result id> | "released" | null}
issues/<YYYY-MM-DD>/<id>/report.json          the form fields + received + has_logs
issues/<YYYY-MM-DD>/<id>/logs.zip             only when attached
decisions/<id>.json                           written ONLY by the admin panel: {state, reason?, bug?, by, at}
settings.json                                 {"target_passes": 3, "claim_hours": 48} (defaults when missing)
```

A **pass** = a stored, assigned-or-not result for a section with every step answered (a result with a `problem`
still counts, and is listed under problems). A claim expires `claim_hours` after `made` - worked out when claims are
read, no timer. Writes are atomic (a temp file in the same folder, then rename). The state of a report or result
for `/submit/status` is `decisions/<id>.json`'s `state` when it exists, else `received`.

## Who reads and writes what

- `intake` (this service): writes everything above except `decisions/`; reads `testplans/` from the site read-only.
- `admin` (the panel): reads all of it; writes only `decisions/` (release-managers' Approve / Reject / Idea / Record
  as bug), every decision also in its audit log.
- Caddy: routes `/submit/*` to `intake` on both the HTTPS name and `:9090`; nothing else of the data directory is
  served.
