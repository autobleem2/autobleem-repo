"""The intake service's settings - all from the environment (intake/README.md, "Running it")."""
import os
import secrets
from dataclasses import dataclass, field

PLATFORMS = ("psc", "rpi", "pcusb", "win")

KB = 1024
MB = 1024 * 1024


def _salt():
    # generated at start when unset: the rate-limit hashes then change on every restart, which is fine
    return os.environ.get("AB_INTAKE_SALT") or secrets.token_hex(16)


@dataclass
class Settings:
    # the volume this service writes (claims, results, issues; decisions/ is the panel's)
    data_dir: str = os.environ.get("AB_INTAKE_DIR", "/data")
    # the site's testplans/ folder, mounted read-only
    plans_dir: str = os.environ.get("AB_TESTPLANS_DIR", "/srv/testplans")
    salt: str = field(default_factory=_salt)
    # peers whose X-Forwarded-For is believed: the Caddy container's network (private ranges by default)
    trusted_proxies: list = field(default_factory=lambda: [
        x for x in os.environ.get(
            "AB_INTAKE_TRUSTED", "127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 ::1/128 fc00::/7").split() if x])
    # body limits (bytes)
    max_result_body: int = 256 * KB
    max_issue_body: int = 25 * MB
    max_claim_body: int = 16 * KB
    max_zip_total: int = 100 * MB
    max_zip_entries: int = 5000
    # text caps (characters)
    cap_comment: int = 2000
    cap_long: int = 5000       # steps / expected / actual
    cap_short: int = 200       # contact / device
    # rate limits per client address: (count, seconds)
    limit_submit: tuple = ((5, 3600), (20, 86400))   # testplan + issue together
    limit_claim: tuple = ((30, 3600),)
    # defaults of settings.json
    target_passes: int = 3
    claim_hours: int = 48
