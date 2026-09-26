"""repo_index_merge.py must not crash decoding git's output when it holds non-ASCII text (the manual
language names added in cdfe75d, e.g. "Română"/"简体中文") on a system whose default
locale encoding cannot represent every byte - Windows' ANSI code page on a Polish machine (cp1250) being
the one that actually broke a publish. Before the fix, `git()` and the `git merge-file` call used
`universal_newlines=True`, which decodes with `locale.getpreferredencoding()`; cp1250 has no code point for
0x83 (part of a-breve's UTF-8 encoding), so the reader thread raised UnicodeDecodeError, stdout came back
None, and `neutral(None)` blew up with a TypeError. The fix pins both calls to `encoding="utf-8"` regardless
of locale, so this must succeed even when the environment is pushed towards a narrow legacy encoding
(PYTHONUTF8=0, a "C"/POSIX locale, and - the closest this can get to the original report on a non-Windows
CI runner - PYTHONLEGACYWINDOWSSTDIO on Windows)."""
import os
import subprocess
import sys
import tempfile

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
MERGE_SCRIPT = os.path.join(TOOLS_DIR, "repo_index_merge.py")

# distinct non-ASCII additions each anchored next to a different unchanged line, so the three-way diff
# combines them without a conflict (two insertions at the very same spot are themselves a conflict - not
# what this test is about)
BASE_TEXT = 'LANGS = {\n    "en": "English",\n    "pl": "Polski",\n    "de": "Deutsch",\n}\n'
MINE_TEXT = ('LANGS = {\n    "en": "English",\n    "pl": "Polski",\n    "ro": "Română",\n'
             '    "de": "Deutsch",\n}\n')
THEIRS_TEXT = ('LANGS = {\n    "en": "English",\n    "pl": "Polski",\n    "de": "Deutsch",\n'
               '    "zh": "简体中文",\n}\n')


def run_merge(tmp_dir, env_overrides):
    """Runs the real script as a subprocess (like repo_publish.sh does), so the child Python picks the
    encoding from the environment exactly as it would on the operator's machine."""
    mine = os.path.join(tmp_dir, "mine.py")
    theirs = os.path.join(tmp_dir, "theirs.py")
    theirs_base = os.path.join(tmp_dir, "theirs.base.py")
    theirs_rev = os.path.join(tmp_dir, "theirs.rev")
    out = os.path.join(tmp_dir, "out.py")
    out_base = os.path.join(tmp_dir, "out.base.py")
    out_rev = os.path.join(tmp_dir, "out.rev")

    for path, text in ((mine, MINE_TEXT), (theirs, THEIRS_TEXT), (theirs_base, BASE_TEXT)):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    with open(theirs_rev, "w", encoding="utf-8") as f:
        f.write("0" * 40 + "\n")

    env = dict(os.environ)
    env.update(env_overrides)
    # a plain temp dir is never inside a git work tree, so the script's own git() calls for mine's base
    # (fetch/merge-base/show) all report "not a repository" and are skipped - only `git merge-file` runs,
    # which is enough to exercise the bug
    result = subprocess.run(
        [sys.executable, MERGE_SCRIPT, "--mine", mine, "--theirs", theirs, "--theirs-base", theirs_base,
         "--theirs-rev", theirs_rev, "--out", out, "--out-base", out_base, "--out-rev", out_rev],
        cwd=tmp_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    return result, out


def test_merge_succeeds_under_a_narrow_legacy_locale():
    env_overrides = {
        "PYTHONUTF8": "0",
        "PYTHONIOENCODING": "",
        "LC_ALL": "C",
        "LANG": "C",
    }
    if sys.platform == "win32":
        # the closest a non-Polish machine can get to the operator's cp1250 report: force the legacy
        # (narrow, locale-driven) console/stdio code path instead of Python's UTF-8 mode
        env_overrides["PYTHONLEGACYWINDOWSSTDIO"] = "1"
    env_overrides = {k: v for k, v in env_overrides.items() if v != ""}

    with tempfile.TemporaryDirectory() as tmp_dir:
        result, out = run_merge(tmp_dir, env_overrides)

        assert result.returncode == 0, (
            "expected a clean merge, got exit %d\nstdout: %s\nstderr: %s"
            % (result.returncode, result.stdout, result.stderr))
        assert "UnicodeDecodeError" not in (result.stderr or "")
        assert "TypeError" not in (result.stderr or "")

        with open(out, encoding="utf-8") as f:
            merged = f.read()
        assert '"ro": "Română"' in merged
        assert '"zh": "简体中文"' in merged


def test_a_missing_git_output_is_a_clear_error_not_a_typeerror():
    """git() returning None (no git, or a decode failure) must not reach neutral()/VERSION_RE.sub with
    None - it should be reported and exit 1, not crash."""
    sys.path.insert(0, TOOLS_DIR)
    import repo_index_merge  # noqa: E402

    assert repo_index_merge.git(["not-a-real-git-subcommand"], os.getcwd()) is None
