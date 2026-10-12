"""DISC-10: tools/sbi_pack.py - the LibCrypt .sbi pack by serial (offline: saved pages, fake .sbi bytes)."""
import json
import os
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


if __name__ == "__main__":
    unittest.main()
