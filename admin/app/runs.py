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
        "created": run.get("created_at"),
        "started": run.get("run_started_at"),
        "updated": run.get("updated_at"),
        "completed": run.get("updated_at") if run["status"] == "completed" else None,
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
                 "started": j.get("started_at"), "completed": j.get("completed_at"),
                 "runner": j.get("runner_name"), "labels": j.get("labels") or [], "url": j.get("html_url"),
                 "steps": [{"number": st.get("number"), "name": st.get("name"), "status": st.get("status"),
                            "conclusion": st.get("conclusion"), "started": st.get("started_at"),
                            "completed": st.get("completed_at")} for st in (j.get("steps") or [])]}
                for j in jobs]

    def runners(self):
        """the org's self-hosted runners - a 403/404 (the App not installed with that permission yet, or none
        registered) must not break status; the caller matches `busy` runners to an active job by name"""
        def ask():
            data = self.gh.call("GET", "/orgs/%s/actions/runners?per_page=50" % self.settings.org)
            return [{"name": r["name"], "status": r["status"], "busy": r["busy"],
                     "labels": [l["name"] for l in r.get("labels", [])]} for r in data.get("runners", [])]
        return self.gh.cached("status-runners", self.settings.runs_ttl, ask)

    def status(self, now=None, recent=20):
        """{"active": [...], "recent": [...], "queue": [...], "runners": [...]} - active with their jobs and a
        steps/jobs progress count, recent the newest finished first, queue everything still waiting (oldest
        first), runners the build server's self-hosted runners with the active job each is on"""
        now = now or datetime.now(timezone.utc)
        active, finished, queue, errors = [], [], [], []
        for repo in self.settings.repos:
            try:
                runs = self.repo_runs(repo)
            except Exception as e:  # one repository's trouble must not blank the page
                errors.append({"repo": repo, "error": str(e)})
                continue
            for run in runs:
                if run["status"] == "in_progress":
                    item = summarise(repo, run, self.typical(repo, run["workflow_id"]), now)
                    jobs = self.jobs(repo, run["id"])
                    item["jobs"] = jobs
                    item["progress"] = job_progress(jobs)
                    active.append(item)
                    for j in jobs:
                        if j["status"] == "queued":
                            queue.append(queue_entry(repo, run, now, job=j))
                elif run["status"] in ACTIVE:  # queued/waiting/pending/requested: not running yet at all
                    queue.append(queue_entry(repo, run, now))
                else:
                    finished.append(summarise(repo, run, None, now))
        active.sort(key=lambda r: r["started"] or "", reverse=True)
        finished.sort(key=lambda r: r["updated"] or "", reverse=True)
        queue.sort(key=lambda q: q["since"] or "")
        try:
            runners = self.runners()
        except Exception as e:
            runners = []
            errors.append({"repo": "(runners)", "error": str(e)})
        by_runner = {j["runner"]: (a, j) for a in active for j in a["jobs"] if j.get("runner")}
        for r in runners:
            run_job = by_runner.get(r["name"])
            r["job"] = {"repo": run_job[0]["repo"], "run_id": run_job[0]["id"], "job": run_job[1]["name"]} \
                if run_job else None
        return {"active": active, "recent": finished[:recent], "queue": queue, "runners": runners,
                "errors": errors, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


def job_progress(jobs):
    """steps done/total across a run's jobs, for the progress bar"""
    done = sum(1 for j in jobs for st in j["steps"] if st["status"] == "completed")
    total = sum(len(j["steps"]) for j in jobs)
    return {"done": done, "total": total}


def queue_entry(repo, run, now, job=None):
    since = job.get("started") if job else run.get("run_started_at") or run.get("created_at")
    # a queued job has no started_at of its own until it picks up a runner; fall back to the run's own wait
    since = since or run.get("created_at")
    return {
        "repo": repo, "run_id": run["id"], "workflow": run.get("name"), "branch": run.get("head_branch"),
        "title": run.get("display_title"), "status": job["status"] if job else run["status"],
        "job": job.get("name") if job else None, "labels": job.get("labels") if job else [],
        "since": since, "waiting": seconds(parse_time(since), now) if since else None,
        "url": job.get("url") if job else run.get("html_url"),
    }
