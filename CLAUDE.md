# autobleem-repo - the download site's tooling

`https://autobleem.retromenele.pl/` is the build server's `/home/claude/autobleem-repo`, served read-only by
Caddy (`docker/repo/`). Everything on it is published by `tools/repo_publish.sh <kind> ...`; the three pages
(`index.html`, `rpi-install.html`, `pc-install.html`) are **generated** by `tools/repo_index.py` on every
publish - never edited on the server. `tools/repo_assets.py` stages `assets/` (the ab2 theme's picture,
Selawik Light, the emblem).

## Publishing

- Commit a page change to `develop` (and `master`) **before** publishing: the generator is three-way merged
  with the server's copy (`tools/repo_index_merge.py`), never copied over it. Publish from a git checkout.
- From Windows run it in the MSYS2 shell (Git Bash has no rsync):
  `bash tools/repo_publish.sh index` just regenerates the pages.
- Try a page change first against a copy of the tree (`python3 tools/repo_index.py <copy>`) and look at it in
  a browser - desktop and phone width - before publishing.
- A `--local` publish run as root (a CI container) hands the tree back to its owner at the end; a failed
  generator is replaced by the previous one *with its merge base*.

## The pages' look and structure - the rules (the owner's, 2026-09-23)

The owner approved the 2026-09-23 redesign ("look and feel of the page is great"). **Keep it; change it only
when asked.** New content fits into the existing pieces, it does not bring its own.

- **The top.** Every page starts with `page_head(title, tagline)`: the slim sticky bar (emblem, "AutoBleem 2
  Downloads", Manual / All files / GitHub) and the short banner - one line of text on the left, the ab2
  picture whole on the right (hidden on a phone). Never a full-width hero again, never a second header.
- **The palette and type** are `PAGE_CSS`'s `:root` tokens (navy, cyan, ink, dim; rel/pre/dev/warn) and
  Selawik Light. No colours or fonts outside them.
- **The landing page** is: one short lede, then the platform tabs (PlayStation Classic, Raspberry Pi, PC with
  its two sub-tabs, Every platform). A platform's tab is an **Install** panel first - what a user installs
  from - and then its **Build inputs** folded in a `<details class="inputs">` (what installers, image builds
  and CI fetch). Nothing a user needs goes into the folded part; nothing that is only an input goes above it.
- **One table style for every file**, `row()`/`table()` in `render_index`: What (a `<small>` note under it, a
  `badge` like PREVIEW after it) | Version (a `.chan` pill: `rel` release, `pre` pre-release, `dev`
  development build - no pill for a dated pack, the Date column says it) | Download (a button named by the
  file type, the full name on hover) | Size | Date (the day; the time on hover). A table where nothing has a
  version drops the column by itself. No bullet lists of downloads, no file names as link text.
- **Channels**: the latest stable release, the one pre-release and the newest development build
  (`nightly/`) appear in the same tables, told apart by their pills. Development builds are never an update
  channel.
- **Something a user must copy into another program** (the Raspberry Pi Imager repository address) goes in
  a `.notice` box with a **Copy** button - `imager_notice()` is the pattern.
- **A warning** is a `badge` plus a `.warn` note on its row - not a separate panel.
- **Phone width** must work: no horizontal scroll, size/date columns hidden, pills may wrap.
- Text on the pages is short and plain; the long explanations live in the manual pages
  (`rpi-install.html`, `pc-install.html`) and the user manual.
