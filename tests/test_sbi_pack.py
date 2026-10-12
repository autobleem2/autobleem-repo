"""DISC-10: tools/sbi_pack.py - the LibCrypt .sbi pack by serial (offline: saved pages, fake .sbi bytes)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import sbi_pack  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "sbi_pack")


def fixture(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


def sbi(*records):
    """A fake .sbi: header + (msf, type) records with zero payloads."""
    out = b"SBI\0"
    for msf, kind in records:
        out += bytes(msf) + bytes([kind]) + b"\0" * {1: 10, 2: 3, 3: 3}[kind]
    return out


SBI_A = sbi(((0x03, 0x12, 0x45), 1), ((0x03, 0x12, 0x46), 1))
SBI_B = sbi(((0x04, 0x01, 0x02), 1))
SBI_SHORT = sbi(((0x03, 0x12, 0x45), 2), ((0x03, 0x12, 0x46), 3))


class ParseTest(unittest.TestCase):
    def test_list_page(self):
        ids, pages = sbi_pack.parse_list(fixture("list.html").decode())
        self.assertEqual(ids, ["1234", "20"])
        self.assertEqual(pages, ["/discs/system/psx/libcrypt/2/?page=2"])

    def test_disc_page(self):
        info = sbi_pack.parse_disc(fixture("disc_1234.html").decode())
        self.assertEqual(info["serials"], ["SCES-02835", "SCES-12835"])
        self.assertEqual(info["version"], "1.1")
        self.assertEqual(info["edition"], "Rev 1")
        self.assertEqual(sbi_pack.parse_disc(fixture("disc_20.html").decode())["serials"], ["SCES-02835"])

    def test_serial_split(self):
        self.assertEqual(sbi_pack.split_serials("SLES-01234,SLES-11234 , SLES-01234"),
                         ["SLES-01234", "SLES-11234"])
        self.assertEqual(sbi_pack.split_serials("SLUS-00123; n/a"), ["SLUS-00123"])
        self.assertEqual(sbi_pack.split_serials(""), [])


class CheckTest(unittest.TestCase):
    def test_good(self):
        self.assertIsNone(sbi_pack.check_sbi(SBI_A))
        self.assertIsNone(sbi_pack.check_sbi(SBI_SHORT))
        self.assertIsNone(sbi_pack.check_sbi(b"SBI\0"))

    def test_bad(self):
        self.assertIn("header", sbi_pack.check_sbi(b"<html>"))
        self.assertIn("cut-off", sbi_pack.check_sbi(SBI_A[:-1]))
        self.assertIn("cut-off", sbi_pack.check_sbi(SBI_A + b"\x01\x02"))
        self.assertIn("type", sbi_pack.check_sbi(b"SBI\0\x03\x12\x45\x09" + b"\0" * 10))
        self.assertIn("BCD", sbi_pack.check_sbi(b"SBI\0\x0a\x12\x45\x01" + b"\0" * 10))


class PackTest(unittest.TestCase):
    def test_numbering_in_id_order_and_dedup(self):
        logs = []
        pack = sbi_pack.build_pack([("1234", ["SCES-02835", "SCES-12835"], SBI_B),
                                    ("20", ["SCES-02835"], SBI_A),
                                    ("300", ["SCES-02835"], SBI_A),  # same bytes: not repeated
                                    ("400", ["SLES-00001"], b"junk")], logs.append)
        self.assertEqual(pack["SCES-02835"], [SBI_A, SBI_B])
        self.assertEqual(pack["SCES-12835"], [SBI_B])
        self.assertNotIn("SLES-00001", pack)
        self.assertEqual(len(logs), 1)
        self.assertIn("disc 400", logs[0])

    def test_write(self):
        with tempfile.TemporaryDirectory() as out:
            index = sbi_pack.write_pack({"SCES-02835": [SBI_A, SBI_B], "SLUS-00001": [SBI_A]}, out)
            self.assertEqual(index, {"SCES-02835": ["SCES-02835.1.sbi", "SCES-02835.2.sbi"],
                                     "SLUS-00001": ["SLUS-00001.1.sbi"]})
            with open(os.path.join(out, "sbi", "index.json")) as f:
                self.assertEqual(json.load(f), index)
            with open(os.path.join(out, "sbi", "SCES-02835.2.sbi"), "rb") as f:
                self.assertEqual(f.read(), SBI_B)


class RunTest(unittest.TestCase):
    PAGE2 = b'<a href="/disc/7/">x</a> <a href="/discs/system/psx/libcrypt/2/">1</a>'

    def setUp(self):
        self.urls = []
        self.pages = {
            "/discs/system/psx/libcrypt/2/": fixture("list.html"),
            "/discs/system/psx/libcrypt/2/?page=2": self.PAGE2,
            "/disc/20/": fixture("disc_20.html"),
            "/disc/20/sbi/": SBI_A,
            "/disc/1234/": fixture("disc_1234.html"),
            "/disc/1234/sbi/": SBI_B,
            "/disc/7/": b"<tr><th>Serial</th><td>SLUS-00007</td></tr>",
            "/disc/7/sbi/": SBI_SHORT,
        }

    def opener(self, url):
        self.urls.append(url)
        return self.pages[url[len(sbi_pack.BASE):]]

    def fetcher(self):
        return sbi_pack.Fetcher(pause=0, opener=self.opener, sleep=lambda s: None)

    def test_run_follows_paging_and_caches(self):
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as cache:
            index = sbi_pack.run(out, cache, fetcher=self.fetcher(), log=lambda m: None)
            self.assertEqual(index, {"SCES-02835": ["SCES-02835.1.sbi", "SCES-02835.2.sbi"],
                                     "SCES-12835": ["SCES-12835.1.sbi"],
                                     "SLUS-00007": ["SLUS-00007.1.sbi"]})
            first = len(self.urls)
            self.assertEqual(first, 2 + 3 * 2)
            # a re-run reads the list pages again but no disc page or file
            self.urls.clear()
            sbi_pack.run(out, cache, fetcher=self.fetcher(), log=lambda m: None)
            self.assertEqual(len(self.urls), 2)

    def test_limit(self):
        with tempfile.TemporaryDirectory() as out:
            index = sbi_pack.run(out, None, limit=1, fetcher=self.fetcher(), log=lambda m: None)
            self.assertEqual(index, {"SCES-02835": ["SCES-02835.1.sbi"], "SCES-12835": ["SCES-12835.1.sbi"]})

    def test_polite_pause_and_retry(self):
        sleeps, calls = [], []

        def flaky(url):
            calls.append(url)
            if len(calls) < 3:
                raise OSError("reset")
            return b"ok"

        f = sbi_pack.Fetcher(pause=1.0, opener=flaky, sleep=sleeps.append)
        self.assertEqual(f.get("http://x/"), b"ok")
        self.assertEqual(len(calls), 3)
        self.assertIn(2.0, sleeps)  # backoff doubles
        self.assertIn(4.0, sleeps)


class PagingTest(unittest.TestCase):
    """The pager of a real list shows pages 2..110 at once; only 1..3 have discs."""

    def test_stops_at_the_first_empty_page(self):
        base = sbi_pack.BASE + sbi_pack.LIST_PATH
        pager = " ".join('<a href="%s?page=%d">%d</a>' % (sbi_pack.LIST_PATH, n, n) for n in range(2, 111))
        pages = {base: ('<a href="/disc/1/">a</a>' + pager).encode(),
                 base + "?page=2": ('<a href="/disc/2/">b</a>' + pager).encode(),
                 base + "?page=3": ('<a href="/disc/3/">c</a>' + pager).encode(),
                 base + "?page=4": pager.encode()}
        urls = []

        def opener(url):
            urls.append(url)
            return pages[url]

        f = sbi_pack.Fetcher(pause=0, opener=opener, sleep=lambda s: None)
        ids = sbi_pack.list_discs(f, log=lambda m: None)
        self.assertEqual(ids, ["1", "2", "3"])
        self.assertEqual(urls, [base, base + "?page=2", base + "?page=3", base + "?page=4"])

    def test_a_page_number_is_never_fetched_twice(self):
        base = sbi_pack.BASE + sbi_pack.LIST_PATH
        pager = '<a href="/discs/system/psx/libcrypt/2/page/2">2</a> <a href="/discs/system/psx/libcrypt/2/?page=2">2</a>'
        urls = []

        def opener(url):
            urls.append(url)
            return (pager + '<a href="/disc/%d/">x</a>' % len(urls)).encode()

        f = sbi_pack.Fetcher(pause=0, opener=opener, sleep=lambda s: None)
        self.assertEqual(sbi_pack.list_discs(f, log=lambda m: None), ["1", "2"])
        # page 2 is linked twice (two address forms) and again from page 2 itself: fetched once
        self.assertEqual(urls, [base, base.rstrip("/") + "/page/2"])


def make_pack(folder, files, index=None):
    os.makedirs(folder, exist_ok=True)
    for name, data in files.items():
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)
    if index is not False:
        with open(os.path.join(folder, "index.json"), "w") as f:
            json.dump(index if index is not None else {"SCES-02835": sorted(files)}, f)
    return folder


class CheckPackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sbi")

    def test_good(self):
        make_pack(self.dir, {"SCES-02835.1.sbi": SBI_A, "SCES-02835.2.sbi": SBI_B})
        self.assertEqual(sbi_pack.check_pack(self.dir), [])

    def test_refused(self):
        make_pack(self.dir, {"A-1.1.sbi": SBI_A}, {"A-1": ["A-1.1.sbi", "A-1.2.sbi"]})
        with open(os.path.join(self.dir, "notes.txt"), "w") as f:
            f.write("x")
        os.mkdir(os.path.join(self.dir, ".cache"))
        text = "\n".join(sbi_pack.check_pack(self.dir))
        self.assertIn("notes.txt", text)
        self.assertIn(".cache", text)
        self.assertIn("A-1.2.sbi", text)  # listed, not there

    def test_unlisted_bad_and_unparsable(self):
        make_pack(self.dir, {"A-1.1.sbi": SBI_A, "B-2.1.sbi": b"junk"}, {"A-1": ["A-1.1.sbi"], "B-2": ["B-2.1.sbi"]})
        self.assertIn("B-2.1.sbi: no SBI header", sbi_pack.check_pack(self.dir))
        make_pack(self.dir, {"C-3.1.sbi": SBI_A}, {"A-1": ["A-1.1.sbi"]})
        self.assertIn("C-3.1.sbi is not listed in index.json", sbi_pack.check_pack(self.dir))
        with open(os.path.join(self.dir, "index.json"), "w") as f:
            f.write("{nope")
        self.assertTrue(any(p.startswith("index.json") for p in sbi_pack.check_pack(self.dir)))
        os.remove(os.path.join(self.dir, "index.json"))
        self.assertTrue(any(p.startswith("index.json") for p in sbi_pack.check_pack(self.dir)))


class PublishTest(unittest.TestCase):
    """`repo_publish.sh --local sbi <dir>` into a scratch REPO_DIR (offline: no ssh, no network)."""
    SCRIPT = os.path.join(HERE, "..", "tools", "repo_publish.sh")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        self.dir = os.path.join(self.tmp.name, "out", "sbi")

    def publish(self, *args):
        env = dict(os.environ, REPO_DIR=self.repo)
        return subprocess.run(["bash", self.SCRIPT, "--local"] + list(args), capture_output=True, text=True,
                              timeout=120, env=env)

    def site(self):
        folder = os.path.join(self.repo, "sbi")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else None

    def test_publish_replaces_the_pack_whole(self):
        make_pack(self.dir, {"SCES-02835.1.sbi": SBI_A, "SCES-02835.2.sbi": SBI_B})
        r = self.publish("sbi", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.site(), ["SCES-02835.1.sbi", "SCES-02835.2.sbi", "index.json"])  # no sidecars
        with open(os.path.join(self.repo, "sbi", "SCES-02835.2.sbi"), "rb") as f:
            self.assertEqual(f.read(), SBI_B)
        # the next pack has other serials: the old files are gone, index.json is the new one
        shutil.rmtree(self.dir)
        make_pack(self.dir, {"SLUS-00001.1.sbi": SBI_A}, {"SLUS-00001": ["SLUS-00001.1.sbi"]})
        r = self.publish("sbi", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.site(), ["SLUS-00001.1.sbi", "index.json"])
        with open(os.path.join(self.repo, "sbi", "index.json")) as f:
            self.assertEqual(json.load(f), {"SLUS-00001": ["SLUS-00001.1.sbi"]})

    def test_dry_run_touches_nothing(self):
        make_pack(self.dir, {"SCES-02835.1.sbi": SBI_A})
        self.assertEqual(self.publish("sbi", self.dir).returncode, 0)
        shutil.rmtree(self.dir)
        make_pack(self.dir, {"SLUS-00001.1.sbi": SBI_A}, {"SLUS-00001": ["SLUS-00001.1.sbi"]})
        r = self.publish("--dry-run", "sbi", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SCES-02835.1.sbi", r.stdout)  # will be removed
        self.assertIn("nothing uploaded", r.stdout)
        self.assertEqual(self.site(), ["SCES-02835.1.sbi", "index.json"])

    def test_refuses_a_bad_folder(self):
        make_pack(self.dir, {"SCES-02835.1.sbi": SBI_A})
        with open(os.path.join(self.dir, "readme.txt"), "w") as f:
            f.write("x")
        r = self.publish("sbi", self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("readme.txt", r.stderr)
        self.assertFalse(os.path.exists(self.repo))
        os.remove(os.path.join(self.dir, "readme.txt"))
        make_pack(self.dir, {"SCES-02835.1.sbi": SBI_A}, {"SCES-02835": ["SCES-02835.9.sbi"]})
        r = self.publish("sbi", self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.repo))

    def test_dry_run_is_for_sbi_only(self):
        r = self.publish("--dry-run", "db", os.path.join(self.tmp.name, "x.db"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--dry-run", r.stderr)


if __name__ == "__main__":
    unittest.main()
