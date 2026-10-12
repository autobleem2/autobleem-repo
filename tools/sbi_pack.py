#!/usr/bin/env python3
"""Build the site's pack of LibCrypt .sbi files, by serial, from redump.org.

A PS1 LibCrypt disc played from a USB CD drive needs the disc's .sbi (redump's subchannel file); the launcher
fetches it from our site by serial. This reads redump's LibCrypt list for the psx system, reads each disc's page
for its serial(s), downloads <disc>/sbi/ and writes

    <out>/sbi/<SERIAL>.<n>.sbi      n = 1.. per serial, in redump disc id order
    <out>/sbi/index.json            {"SCES-02835": ["SCES-02835.1.sbi", "SCES-02835.2.sbi"], ...}

A file whose bytes equal another version of the same serial is not repeated. Every file is checked ("SBI\\0" and
whole records) and a bad one is reported and skipped. Polite: one request at a time, a pause between requests,
retries with backoff, a cache folder so a re-run fetches only the discs it has not seen (the list pages are always
read again - they are how a new disc shows up). Publishing the result: tools/repo_publish.sh sbi DIR/sbi.

    sbi_pack.py --out DIR [--cache DIR] [--limit N]
    sbi_pack.py --check PACK-DIR        only check a pack folder (repo_publish.sh sbi runs this first)
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://redump.org"
LIST_PATH = "/discs/system/psx/libcrypt/2/"
USER_AGENT = "AutoBleem-sbi-pack/1.0 (+https://autobleem.retromenele.pl/)"
PAUSE = 1.0
RETRIES = 4
TIMEOUT = 60

DISC_LINK_RE = re.compile(r'href="(?:https?://redump\.org)?/disc/(\d+)/?"')
PAGE_LINK_RE = re.compile(r'href="([^"]*?(?:/page/\d+|[?&]page=\d+)[^"]*)"')
PAGE_NUMBER_RE = re.compile(r"(?:/page/|[?&]page=)(\d+)")
ROW_RE =re.compile(r"<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
SERIAL_RE = re.compile(r"^[A-Z]{3,5}-?\d{3,6}$")


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text))).strip()


def parse_list(page):
    """(disc ids in page order, the paging links in page order) of a list page."""
    ids = []
    for m in DISC_LINK_RE.finditer(page):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    pages = []
    for m in PAGE_LINK_RE.finditer(page):
        link = html.unescape(m.group(1))
        if link not in pages:
            pages.append(link)
    return ids, pages


def split_serials(text):
    """'SCES-02835, SCES-12835' -> ['SCES-02835', 'SCES-12835'] (as redump writes them); junk is dropped."""
    out = []
    for part in re.split(r"[,;/]", text):
        s = part.strip()
        if SERIAL_RE.match(s) and s not in out:
            out.append(s)
    return out


def parse_disc(page):
    """{'serials': [...], 'version': str, 'edition': str} from a disc page's Serial/Version/Edition rows."""
    rows = {}
    for m in ROW_RE.finditer(page):
        rows.setdefault(clean(m.group(1)).lower(), clean(m.group(2)))
    return {
        "serials": split_serials(rows.get("serial", "")),
        "version": rows.get("version", ""),
        "edition": rows.get("edition", ""),
    }


def check_sbi(data):
    """None when `data` is a whole .sbi, else the reason it is not."""
    if data[:4] != b"SBI\0":
        return "no SBI header"
    pos = 4
    while pos < len(data):
        if pos + 4 > len(data):
            return "cut-off record at byte %d" % pos
        msf, kind = data[pos:pos + 3], data[pos + 3]
        if any((b >> 4) > 9 or (b & 15) > 9 for b in msf):
            return "bad BCD time at byte %d" % pos
        if kind == 1:
            size = 10
        elif kind in (2, 3):
            size = 3
        else:
            return "unknown record type %d at byte %d" % (kind, pos)
        if pos + 4 + size > len(data):
            return "cut-off record at byte %d" % pos
        pos += 4 + size
    return None


def build_pack(discs, log=print):
    """discs: [(disc id, serials, sbi bytes)] -> {serial: [bytes, ...]}, numbered in disc id order, a bad file
    reported and skipped, bytes equal to an earlier version of the same serial dropped."""
    pack = {}
    for disc_id, serials, data in sorted(discs, key=lambda d: int(d[0])):
        problem = check_sbi(data)
        if problem:
            log("disc %s: bad sbi (%s) - skipped" % (disc_id, problem))
            continue
        for serial in serials:
            versions = pack.setdefault(serial, [])
            if data not in versions:
                versions.append(data)
    return pack


def write_pack(pack, out):
    folder = os.path.join(out, "sbi")
    os.makedirs(folder, exist_ok=True)
    index = {}
    for serial in sorted(pack):
        names = []
        for n, data in enumerate(pack[serial], 1):
            name = "%s.%d.sbi" % (serial, n)
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
            names.append(name)
        index[serial] = names
    with open(os.path.join(folder, "index.json"), "w") as f:
        json.dump(index, f, indent=1, sort_keys=True)
        f.write("\n")
    return index


PACK_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.sbi$")


def check_pack(folder):
    """The reasons a pack folder must not be published (empty = fine): only index.json and *.sbi, index.json
    parses and lists whole files that are all there, and every .sbi is listed."""
    if not os.path.isdir(folder):
        return ["not a folder: %s" % folder]
    problems, sbis = [], set()
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if name == "index.json":
            continue
        if not PACK_FILE_RE.match(name) or os.path.islink(path) or not os.path.isfile(path):
            problems.append("not part of the pack (index.json and *.sbi only): %s" % name)
        else:
            sbis.add(name)
    try:
        with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
            index = json.load(f)
    except (OSError, ValueError) as e:
        return problems + ["index.json: %s" % e]
    if not isinstance(index, dict) or not all(
            isinstance(k, str) and isinstance(v, list) and all(isinstance(n, str) for n in v)
            for k, v in index.items()):
        return problems + ["index.json is not {serial: [file names]}"]
    listed = set()
    for serial, names in index.items():
        for name in names:
            listed.add(name)
            if name not in sbis:
                problems.append("index.json lists %s (%s) but the folder has no such file" % (name, serial))
    for name in sorted(sbis - listed):
        problems.append("%s is not listed in index.json" % name)
    for name in sorted(sbis & listed):
        with open(os.path.join(folder, name), "rb") as f:
            bad = check_sbi(f.read())
        if bad:
            problems.append("%s: %s" % (name, bad))
    return problems


class Fetcher:
    def __init__(self, pause=PAUSE, opener=None, sleep=time.sleep):
        self.pause = pause
        self.sleep = sleep
        self.opener = opener or self._open
        self.last = None

    @staticmethod
    def _open(url):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()

    def get(self, url):
        """The body of `url`; one request at a time, `pause` seconds apart, retried with backoff."""
        delay = 2.0
        for attempt in range(1, RETRIES + 1):
            if self.last is not None:
                wait = self.pause - (time.monotonic() - self.last)
                if wait > 0:
                    self.sleep(wait)
            try:
                return self.opener(url)
            except (urllib.error.URLError, OSError) as e:
                code = getattr(e, "code", None)
                if code is not None and 400 <= code < 500 and code != 429:
                    raise
                if attempt == RETRIES:
                    raise
                self.sleep(delay)
                delay *= 2
            finally:
                self.last = time.monotonic()


def cached(cache, name, fetch):
    """The bytes of cache/name, fetched (and saved) only when not there yet."""
    path = os.path.join(cache, name) if cache else None
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    data = fetch()
    if path:
        os.makedirs(cache, exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    return data


def list_discs(fetcher, limit=None, log=print):
    """Every LibCrypt disc id of the list, following its paging links. Always fetched fresh."""
    ids, fetched, todo = [], set(), {1: BASE + LIST_PATH}  # page number -> address
    while todo:
        number = min(todo)  # the pager shows pages 2..N at once: go in order, stop at the first empty one
        url = todo.pop(number)
        fetched.add(number)
        page = fetcher.get(url).decode("utf-8", "replace")
        found, pages = parse_list(page)
        log("list %s: %d discs" % (url, len(found)))
        if not found:
            break
        for i in found:
            if i not in ids:
                ids.append(i)
        for link in pages:
            full = urllib.parse.urljoin(url, link)
            m = PAGE_NUMBER_RE.search(full)
            if m and full.startswith(BASE + LIST_PATH) and int(m.group(1)) not in fetched:
                todo.setdefault(int(m.group(1)), full)
        if limit and len(ids) >= limit:
            break
    return ids[:limit] if limit else ids


def run(out, cache, limit=None, fetcher=None, log=print):
    fetcher = fetcher or Fetcher()
    ids = list_discs(fetcher, limit, log)
    discs = []
    for disc_id in ids:
        try:
            page = cached(cache, "disc-%s.html" % disc_id,
                          lambda: fetcher.get("%s/disc/%s/" % (BASE, disc_id))).decode("utf-8", "replace")
            info = parse_disc(page)
            if not info["serials"]:
                log("disc %s: no serial on its page - skipped" % disc_id)
                continue
            data = cached(cache, "disc-%s.sbi" % disc_id,
                          lambda: fetcher.get("%s/disc/%s/sbi/" % (BASE, disc_id)))
        except (urllib.error.URLError, OSError) as e:
            log("disc %s: %s - skipped" % (disc_id, e))
            continue
        log("disc %s: %s %s %s" % (disc_id, ",".join(info["serials"]), info["version"], info["edition"]))
        discs.append((disc_id, info["serials"], data))
    return write_pack(build_pack(discs, log), out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="folder that gets sbi/")
    ap.add_argument("--cache", default=None, help="cache folder (default: <out>/.cache)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N discs of the list")
    ap.add_argument("--check", metavar="DIR", help="only check a pack folder (what repo_publish.sh sbi does)")
    args = ap.parse_args(argv)
    if args.check:
        problems = check_pack(args.check)
        for p in problems:
            print("sbi_pack: %s" % p, file=sys.stderr)
        return 1 if problems else 0
    if not args.out:
        ap.error("--out is required")
    try:
        index = run(args.out, args.cache or os.path.join(args.out, ".cache"), args.limit)
    except (urllib.error.URLError, OSError) as e:
        print("sbi_pack: cannot read redump's list: %s" % e, file=sys.stderr)
        return 1
    print("%d serials, %d files in %s" % (len(index), sum(len(v) for v in index.values()),
                                          os.path.join(args.out, "sbi")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
