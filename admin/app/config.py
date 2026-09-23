"""The panel's settings - all from the environment (admin/.env on the server, admin/README.md lists them)."""
import os
from dataclasses import dataclass, field


def _list(name, default):
    return [x for x in os.environ.get(name, default).split() if x]


@dataclass
class Settings:
    org: str = os.environ.get("AB_ORG", "autobleem2")
    # who may act (trigger, promote, cancel, withdraw); every org member may look
    release_team: str = os.environ.get("AB_RELEASE_TEAM", "release-managers")
    # the GitHub App (autobleem-admin): its id and private key (PEM text or a path to it)
    app_id: str = os.environ.get("AB_APP_ID", "")
    app_key: str = os.environ.get("AB_APP_KEY", "")
    app_key_file: str = os.environ.get("AB_APP_KEY_FILE", "")
    # the site's tree, mounted read-only (channels, disk space)
    repo_dir: str = os.environ.get("AB_REPO_DIR", "/srv/repo")
    # where the audit log and the notifier's memory live
    data_dir: str = os.environ.get("AB_DATA_DIR", "/data")
    # the repositories whose runs the panel shows
    repos: list = field(default_factory=lambda: _list("AB_REPOS", (
        "autobleem autobleem-core autobleem-console-tools autobleem-pc-tools autobleem-appliance "
        "autobleem-build autobleem-repo autobleem-main autobleem-manuals autobleem-samples autobleem-themes "
        "pcsx-ab pcsx-abnxt retroarch-psc psc-kernel-payload")))
    # Telegram: nothing is sent when either is empty
    telegram_token: str = os.environ.get("AB_TELEGRAM_TOKEN", "")
    telegram_chat: str = os.environ.get("AB_TELEGRAM_CHAT", "")
    # how long a repository's run list is reused before GitHub is asked again (seconds)
    runs_ttl: int = int(os.environ.get("AB_RUNS_TTL", "30"))

    def private_key(self):
        if self.app_key:
            return self.app_key.replace("\\n", "\n")
        if self.app_key_file:
            with open(self.app_key_file, encoding="utf-8") as f:
                return f.read()
        return ""


settings = Settings()
