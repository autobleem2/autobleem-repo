# autobleem-repo - the download site's tooling

`https://autobleem.retromenele.pl/` is the build server's `/home/claude/autobleem-repo`, served read-only by
Caddy (`docker/repo/`). Everything on it is published by `tools/repo_publish.sh <kind> ...`; the three pages
(`index.html`, `rpi-install.html`, `pc-install.html`) are **generated** by `tools/repo_index.py` on every
publish - never edited on the server. `tools/repo_assets.py` stages `assets/` from `tools/site-assets/` (the
ab2.0.0 background, the C3 logo, the emblem, the icon, the Support button, Red Hat Text with its OFL.txt -
autobleem-design's `www/` makes them).

## The site's addresses (2026-10-01)

`/` is the **splash** (`render_splash()`: the "Where we are" block updates itself - `splash_release_rows` from the releases (the
newest stable, the newer pre-release, the next milestone), `SPLASH_STATUS` for extra rows by hand, the
nightly row comes from `index_nightly`, `KOFI_URL` is the Support button - empty = no button). The download
listing and the two manuals live in **`/repository/`** (`index.html`, `rpi-install.html`, `pc-install.html`);
the old `/rpi-install.html` and `/pc-install.html` are small refresh + link stubs (`render_moved`). The store page
stays at `/store/`. The **data paths do not move** (`releases/`, `nightly/`, `store/`, `extensions/`, `emu/`,
`pc/`, `psc/`, `rpi/`, `db/`, `manuals/`, `mirror/`, `rpi-imager/`, `samples/`): every updater, installer and
the Store read JSON there. The brand goes to `/`; "Downloads", "Manual" and "<- Downloads" go to `/repository/`.
Caddy's `@volatile` (max-age=300) covers whatever is replaced under the same name - `*.json`, every `*.html`,
every folder listing (`*/`), `/manuals/*` and `/testplans/*`; everything else (the versioned folders) is
max-age=86400. A new kind of file that is replaced in place goes into `@volatile` too (2026-10-03: a day's
cache showed the old manuals).
**Order of a publish that changes the look:** `repo_publish.sh assets` first (the pages' CSS needs the new fonts
and logos), then the page.

## Publishing

- Commit a page change to `develop` (and `master`) **before** publishing: the generator is three-way merged
  with the server's copy (`tools/repo_index_merge.py`), never copied over it. Publish from a git checkout.
- From Windows Git Bash or the MSYS2 shell (Git Bash has no rsync: the script then runs ssh and rsync from
  MSYS2's bin folder by itself, and stops non-zero with a message when there is no rsync or an upload fails;
  `MSYS2_BIN` overrides the folder):
  `bash tools/repo_publish.sh index` just regenerates the pages. It finds a Windows Python by itself (an MSYS2
  login shell drops the Windows PATH: `find_python` looks under %LOCALAPPDATA%); `PYTHON=<path>` overrides it.
- A withdrawn release goes with `repo_publish.sh withdraw version <v>` (always `--dry-run` first): every folder of
  that version - the release, both image sets, the emulators and the development builds counted from it. A
  leftover of it makes the index prune a newer version as "older" (2026-10-03, the old alpha2 and the new alpha1).
- Try a page change first against a copy of the tree (`python3 tools/repo_index.py <copy>`) and look at it in
  a browser - desktop and phone width - before publishing.
- A `--local` publish run as root (a CI container) hands the tree back to its owner at the end; a failed
  generator is replaced by the previous one *with its merge base*.
- `mirror/<name>/` holds third-party files our builds fetch (`repo_publish.sh mirror <name> FILES`), such as
  an App's freeware game data (`mirror/opentyrian/tyrian21.zip`, which `app_opentyrian`'s `ci/build.sh` pins
  by sha256). The page does not list it and the index never prunes it; a file there is never replaced in
  place - a new version is a new file name.

## The download counter (2026-10-03)

The admin panel's **Download stats** tab (release team only) counts downloads per file and day. Caddy serves the
files statically, so nothing is in the download path: Caddy's JSON access log (the `(counted)` snippet in
`docker/repo/Caddyfile`, HTTPS name only, IPs and all headers deleted by its filter, bots skipped) goes to the
`caddy_logs` volume and the admin service reads it incrementally into `downloads.sqlite3` (`admin/app/downloads.py`).
Counted: GET + 200 of a download file type; not HEAD/206/304/404. Stored: day, path, count - no personal data.
What is counted, where it lives, how to switch it on and the tests: `admin/README.md`, "Download stats". The
Caddy log settings must keep the filter - never add an IP or header field to the log.

## The volunteer tester pages (2026-10-03)

`testplans/<version>/<platform>.yaml` is what the hub's CI publishes (`repo_publish.sh testplans FILES...`: each file
goes into the folder its own `version:` line names; the hub's folder is only a short name like `alpha1`). Every index
run reads them (`index_testplans`, a small YAML-subset parser - the server has no PyYAML) and writes
`testplans/index.json` (the contract is `intake/README.md`) and the **Testing** pages under `testing/`: `index.html`
(a card per platform, the coverage hint from `/submit/coverage`), `<platform>.html` (the task page: the whole plan
embedded as JSON, one section shown after `/submit/claim`), `report.html`, `thanks.html`, `status.html`. No
`testplans/` folder = no pages. The pages use `page_head` and `PAGE_CSS` plus `TESTING_CSS` (from
`mockups/testing/site.css`); the plan's texts only ever reach the page as JSON data and `textContent`. Every page's
top bar links **Testing** (`/testing/`) once a plan exists. A `<platform>.pdf` published in the same call as its
`<platform>.yaml` (the hub's printable plan) goes into the same folder and the landing card links it as "Printable
version". Tested in `tests/test_testing_pages.py`.

## The AutoBleem Store's catalog (2026-09-24)

`store/<platform>/` (psc, rpi, rpi64, pcusb, win) is what the AutoBleem Store extension offers; its layout is
set by the launcher's `docs/store-plan.md`.
- **Publishing**: `repo_publish.sh store <platform> FILES...` puts the files there. Each item is an
  `<id>.item.json` descriptor (id, kind, title, version, author, licence, description, image, files by name
  with an optional disc, requires, `category` and `source_url`) next to its files. **`category`** is the package type
  (games, emulators, tools, media, other or packages = game data; anything else is dropped): `catalog.json` keeps it
  and the page shows it as "Type". **`uses`** (the content kinds an engine runs), **`provides`** (the kinds a game-data
  package holds) and `requires` (ids to install first) pass into `catalog.json` too (kinds lower-cased, junk dropped);
  the page shows "Needs: <title>" / "Needs game data: <kinds>" / "Content: <kinds>". **kind `package`** is a game-data
  package (a zip with a `package.ini`; the Store puts it in `Packages/`), listed in its own "Game data packages"
  section. **kind `pe`** is a PE App (the Store's
  "PE Apps" tab, APPS-8): `files` is the one `.mod`, `licence` and `source_url` (the address of the source archive on
  our site, `source/<id>/...`; an http(s) address, passed into `catalog.json`) are shown in the item's details. A
  source archive (`*-source.tar.gz`) is **never** in `files` - it would land on the stick - so a descriptor naming one
  is left out and said so.
- **Indexing**: `index_store()` writes `catalog.json` with every file's size, sha256 and url. It leaves out a
  descriptor whose files are not all there, and prunes a file no descriptor names (an App's previous
  version). Tested in `tests/test_store_index.py`.
- **Its page** (2026-09-24, the owner asked for one instead of Caddy's file list): `render_store()` writes
  `store/index.html` with the approved pieces only - `page_head`, a tab per system (the two Raspberry Pi
  flavours as sub-tabs; Windows only once it has a catalog), the Apps and the games in the one table style
  (`file_row`/`files_table`, module-level now and shared with `render_index`; an item's picture floats in its
  What cell), and the catalog's URL folded under **Build inputs**. The top bar links it as **Store**; the
  landing page's Every platform tab has a short AutoBleem Store panel pointing at it.
- **The Store itself** (2026-09-24): an extension's own packages live in `extensions/<name>/<version>/`,
  published by its repository's CI with `repo_publish.sh --local extension <name> <version> FILES...` (ext_store's
  `site` job, on the self-hosted runner). `index_extensions()` (`EXTENSION_RE`: `ext_<name>-<platform>-<v>.zip`
  and `abstored-<os>-<arch>-<v>.tar.gz|zip`) keeps the newest release (`1.2.3`) and the newest development
  build (`1.2.3-<date>-<commit>`) published after it, and writes `extensions/<name>/latest.json`. The Store
  page shows them: each system's tab opens with a **The Store itself** panel (release, then "dev <version>"),
  Windows gets its tab once it has the extension, and a **LAN server** tab lists abstored per machine with
  the Linux setup guide folded under Build inputs; LAN Share (pc-tools' Windows app, `extensions/lanshare/`,
  `lanshare-windows-x86_64-<v>.zip`) is listed there too. Tested in `tests/test_extension_index.py`.

### PE Apps: the page, the source mirror, the dependency mirror (APPS-8, 2026-10-05)

- **The page**: `render_store` has a **PE Apps** panel between Apps and Games (kind `pe`): name, version pill,
  "Licence: ...", a **Source code** link to the item's `source_url`, and the `.mod` as a download button (for a
  manual copy into the stick's `Mods/`). The 2020 environment's name is never on the page.
- **`source/<id>/`** holds the GPL source archives `<id>-<version>-source.tar.gz` of pe_ports' releases - exactly the
  address `tools/mkmod.py` writes into SOURCE.txt (`AB_SOURCE_BASE` = `<site>/source`). Published with
  `repo_publish.sh pe-source <id> FILES` (refuses any name that is not `<id>-*-source.tar.gz`); pe_ports' `site` job
  does it on a v* tag. **Kept at least 3 years after the item's last release**: nothing prunes it - the index only
  reads `store/`, and `cleanup.yml`/`server_cleanup.sh` never name it (`tests/test_pe_site.py` guards both). Delete
  by hand only after the 3 years. `pe-source` and `deps` never replace a file in place: the same bytes again is a
  no-op, other bytes under the same name stop the publish (`no_overwrite`). pe_ports' `site` job also publishes each
  release's `.mod`, icon and `pe/<id>` descriptor with `store psc` (its `tools/store_item.py`).
- **`deps/<name>/`** holds third-party build dependencies our builds fetch, pinned by sha256 (`deps/boost/
  boost_1_74_0.tar.bz2`, 109 MB, for Commander Genius): `repo_publish.sh deps <name> FILES`. Not listed on any page,
  never pruned, a file is never replaced in place. (`mirror/` is the older folder for the same idea: an App's game
  data.)

## The PS1 emulators' channels (2026-09-27, RELEASE-4)

`emu/<name>/` (`pcsx-ab`, `pcsx-abnxt`) has three channels now, like every other tab: a v* tag build under
`emu/<name>/<version>/` is **release** (a plain tag) or **testing** (a pre-release tag - `is_prerelease`), a
develop push is **nightly**, published to `emu/<name>/nightly/<version>/`. `index_pcsx` (`pcsx_channel_of`
tells a version's channel apart) keeps the newest build of each channel and prunes an older one of the same
channel - an older nightly goes the way an older extension development build does; the function and
`repo_index.py`'s nightly/ reading are generic over `name`, so either emulator can have a nightly channel.
`emu/<name>/latest.json` keeps its old top-level shape (`"version"`/`"files"`/...) unchanged -
`make_win_package.sh` (autobleem2/autobleem) and autobleem-appliance both still
`json.load(...)["files"]["win64"]["url"]` it that way to build the Windows product - as the newest **tag**
build (release, else testing; a nightly-only tree falls back to the nightly rather than leave the top level
missing, but a nightly is never the top level while a tag build exists); the channels themselves sit beside
it under `"channels"`, keyed release/testing/nightly, which is what the download page's PS1 emulators tab
(and `index_pcsx`'s return value) reads. `repo_publish.sh pcsx`/`pcsx-ab` still publish a v* tag build; the
new `pcsx-nightly` kind (and its `withdraw` counterpart) publishes a pcsx-abnxt develop push - **pcsx-ab is no
longer developed (the owner's decision), so it has no nightly kind and its CI publishes tag releases only**;
`pcsx-ab`'s existing release still indexes and pills the same way, and would pick up a nightly channel from
`emu/pcsx-ab/nightly/` too if one were ever published there by hand. The PS1 emulators tab on the download
page draws the same three pills (`rel`/`pre`/`dev`) as every other tab. Tested in `tests/test_pcsx_index.py`.

## The PSC stick zips (PLATFORM-21)

A release and a development build carry `autobleem-psc-<v>-base.zip` (the stick without RetroArch) and
`autobleem-psc-<v>-full.zip` (with RetroArch and its cores), made by autobleem-appliance's `tools/psc_zips.py`; neither has
a BIOS file. They are the package kinds `psc-base` and `psc-full` (before the old single-zip `psc` in `PACKAGE_KINDS`;
`of_version` accepts the `-base`/`-full` suffix) and sit in the PlayStation Classic Install table beside the
installer, each with a one-line note. `unstable.json` leaves them out, like `psc` - the console's update reads the
`psc-fs` tarball only. Tested in `tests/test_psc_zips_page.py`.

## The pages' look and structure - the rules (the owner's, 2026-09-23)

The owner approved the 2026-09-23 redesign ("look and feel of the page is great"). **Keep it; change it only
when asked.** New content fits into the existing pieces, it does not bring its own.

- **The top.** Every inner page starts with `page_head(title, tagline)`: the slim sticky bar (emblem, "AutoBleem 2
  Downloads", Store / Manual / All files / Testing / GitHub - Testing only when the site has `testplans/index.json`,
  `HAS_TESTING`) and the short banner - one line of text on the left, the C3
  logo on the right (hidden on a phone). Never a full-width hero again, never a second header.
- **The palette and type** are `PAGE_CSS`'s `:root` tokens (graphite, cyan, magenta, ink, dim; rel/pre/dev/warn)
  and Red Hat Text. No colours or fonts outside them.
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
