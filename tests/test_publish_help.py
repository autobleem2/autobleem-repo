"""AUTOBLEEM-9: `repo_publish.sh --help` prints the whole leading comment block (never a fixed line range),
and the ssh index run is piped into an explicit bash."""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "tools", "repo_publish.sh")


def test_help_is_complete():
    r = subprocess.run(["bash", SCRIPT, "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "cleanup-partial" in r.stdout
    assert "removes <channel>/<version>.partial" in r.stdout
    assert "indexes (tools/nightly_carry.py)" in r.stdout
    assert "The page generator travels with every publish" in r.stdout


def test_ssh_index_runs_under_bash():
    text = open(SCRIPT, encoding="utf-8").read()
    assert 'remote_index | ssh "$REPO_HOST" bash' in text
    assert 'ssh "$REPO_HOST" "$(remote_index)"' not in text
