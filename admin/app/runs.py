"""What the builders are doing: every repository's newest runs, the ones still going with about how long they
have left, and the ones that finished. One API call per repository per `runs_ttl`, and the durations the
estimate needs once per `HISTORY_TTL` per workflow - well inside the App's hourly allowance."""
import statistics
from datetime import datetime, timezone

HISTORY_TTL = 600
HISTORY_RUNS = 10
ACTIVE = ("queued", "in_progress", "waiting", "requested", "pending")


def parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if text else None


def seconds(start, end):
    return max(0, int((end - start).total_seconds())) if start and end else None


def median_duration(runs):
    """the median of the finished, successful runs' durations (started -> last update), or None"""
    durations = [seconds(parse_time(r.get("run_started_at")), parse_time(r.get("updated_at")))
                 for r in runs if r.get("status") == "completed" and r.get("conclusion") == "success"]
    durations = [d for d in durations if d]
    return int(statistics.median(durations)) if durations else None


def summarise(repo, run, typical, now):
    started = parse_time(run.get("run_started_at"))
    elapsed = seconds(started, now) if run["status"] != "completed" else seconds(started, parse_time(run["updated_at"]))
    left = None
    if run["status"] != "in_progress" and run["status"] in ACTIVE:
        elapsed, left = None, typical  # waiting for a runner: all of it is still ahead
    elif run["status"] == "in_progress" and typical and elapsed is not None:
        left = typical - elapsed  # may go negative: "longer than usual"
    return {
        "repo": repo,
        "id": run["id"],
        "workflow": run.get("name"),
        "workflow_id": run.get("workflow_id"),
        "title": run.get("display_title"),
        "branch": run.get("head_branch"),
        "event": run.get("event"),
        "status": run["status"],
        "conclusion": run.get("conclusion"),
        "started": run.get("run_started_at"),
        "updated": run.get("updated_at"),
        "elapsed": elapsed,
        "typical": typical,
        "left": left,
        "actor": (run.get("triggering_actor") or run.get("actor") or {}).get("login"),
        "url": run.get("html_url"),
    }


class Runs:
    def __init__(self, gh, settings):
        self.gh, self.settings = gh, settings

    def repo_runs(self, repo):
        path = "/repos/%s/%s/actions/runs?per_page=10" % (self.settings.org, repo)
        return self.gh.cached("runs:" + repo, self.settings.runs_ttl,
                              lambda: self.gh.call("GET", path).get("workflow_runs", []))

    def typical(self, repo, workflow_id):
        path = "/repos/%s/%s/actions/workflows/%s/runs?status=success&per_page=%d" % (
            self.settings.org, repo, workflow_id, HISTORY_RUNS)
        return self.gh.cached("typical:%s:%s" % (repo, workflow_id), HISTORY_TTL,
                              lambda: median_duration(self.gh.call("GET", path).get("workflow_runs", [])))

    def jobs(self, repo, run_id):
        path = "/repos/%s/%s/actions/runs/%s/jobs?per_page=50" % (self.settings.org, repo, run_id)
        jobs = self.gh.cached("jobs:%s:%s" % (repo, run_id), self.settings.runs_ttl,
                              lambda: self.gh.call("GET", path).get("jobs", []))
        return [{"name": j["name"], "status": j["status"], "conclusion": j.get("conclusion"),
                 "started": j.get("started_at"), "runner": j.get("runner_name"), "url": j.get("html_url")}
                for j in jobs]

    def status(self, now=None, recent=20):
        """{"active": [...], "recent": [...]} - active with their jobs, recent the newest finished first"""
        now = now or datetime.now(timezone.utc)
        active, finished, errors = [], [], []
        for repo in self.settings.repos:
            try:
                runs = self.repo_runs(repo)
            except Exception as e:  # one repository's trouble must not blank the page
                errors.append({"repo": repo, "error": str(e)})
                continue
            for run in runs:
                if run["status"] in ACTIVE:
                    item = summarise(repo, run, self.typical(repo, run["workflow_id"]), now)
                    item["jobs"] = self.jobs(repo, run["id"])
                    active.append(item)
                else:
                    finished.append(summarise(repo, run, None, now))
        active.sort(key=lambda r: r["started"] or "", reverse=True)
        finished.sort(key=lambda r: r["updated"] or "", reverse=True)
        return {"active": active, "recent": finished[:recent], "errors": errors,
                "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
