"""Telegram: a message when a run finishes - success, failure or cancelled - with how long it took and its
link. A background thread looks at the same run lists the page shows; the runs already reported are
remembered on disk, so a restart does not repeat them. And one message when the build server's disk runs low
(one more when it has room again)."""
import json
import os
import shutil
import threading
import time

import httpx


def disk_free(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None

ICON = {"success": "✅", "failure": "❌", "cancelled": "⛔"}


def message(run):
    minutes = "%dm" % round((run.get("elapsed") or 0) / 60)
    return "%s %s · %s · %s — %s in %s\n%s" % (
        ICON.get(run.get("conclusion"), "ℹ"), run["repo"], run.get("workflow"), run.get("branch"),
        run.get("conclusion"), minutes, run.get("url"))


class Notifier:
    def __init__(self, runs, settings, send=None, interval=30):
        self.runs, self.settings, self.interval = runs, settings, interval
        self.path = os.path.join(settings.data_dir, "notified.json")
        self.send = send or self.telegram
        self.seen_active = set()
        self.disk_low = False
        self.notified = self._load()
        self.started = time.time()

    def enabled(self):
        return bool(self.settings.telegram_token and self.settings.telegram_chat)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return set(json.load(f))
        except (OSError, ValueError):
            return set()

    def _save(self):
        os.makedirs(self.settings.data_dir, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(sorted(self.notified)[-1000:], f)

    def telegram(self, text):
        httpx.post("https://api.telegram.org/bot%s/sendMessage" % self.settings.telegram_token,
                   json={"chat_id": self.settings.telegram_chat, "text": text, "disable_web_page_preview": True},
                   timeout=20)

    def tick(self):
        """one look: report each run that finished since it was seen running (or, on the first look after a
        start, never - old runs are not news)"""
        status = self.runs.status()
        for run in status["active"]:
            self.seen_active.add((run["repo"], run["id"]))
        sent = False
        for run in status["recent"]:
            key = (run["repo"], run["id"])
            ident = "%s/%s" % key
            if key in self.seen_active and ident not in self.notified:
                self.send(message(run))
                self.notified.add(ident)
                self.seen_active.discard(key)
                sent = True
        if sent:
            self._save()
        self.check_disk()

    def check_disk(self):
        """one message when the build server's free space drops under low_disk_gb, one more when it is back
        above it (+2 GB, so a disk hovering at the line does not chatter)"""
        free = disk_free(self.settings.repo_dir)
        if free is None:
            return
        limit = self.settings.low_disk_gb * 1e9
        if not self.disk_low and free < limit:
            self.disk_low = True
            self.send("⚠️ Build server disk: %.1f GB free (under %d GB). A full disk stops the runner and every "
                      "publish - clean up before the next build." % (free / 1e9, self.settings.low_disk_gb))
        elif self.disk_low and free > limit + 2e9:
            self.disk_low = False
            self.send("✅ Build server disk: %.1f GB free again." % (free / 1e9))

    def run_forever(self):
        while True:
            try:
                self.tick()
            except Exception as e:  # a GitHub or Telegram hiccup: try again next time
                print("notifier:", e, flush=True)
            time.sleep(self.interval)

    def start(self):
        if self.enabled():
            threading.Thread(target=self.run_forever, daemon=True).start()
