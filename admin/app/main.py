"""The admin panel's service: the JSON API under /admin/api/ (the page is one client of it, scripts and Claude
sessions another) and the page itself at /admin/.

Who is asking: a script sends `Authorization: Bearer <GitHub token>` and GitHub says whose it is; the browser
comes through oauth2-proxy, which has done the GitHub login and passes the user on in X-Forwarded-User
(Caddy strips that header from every incoming request, so only oauth2-proxy can set it). Every org member may
read; acting needs the release team. A browser's action must carry X-AB-Request (a cross-site form cannot set
it). Every action goes to the audit log, whoever and however.
"""
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .actions import Actions, Audit
from .config import settings as default_settings
from .github import GitHub, GitHubError
from .notify import Notifier
from .runs import Runs
from .site import Health, channels

STATIC = os.path.join(os.path.dirname(__file__), "static")


class NightlyRequest(BaseModel):
    platforms: list = []
    rebuild_all: bool = False
    dry_run: bool = False


class PromoteRequest(BaseModel):
    kind: str
    version: str = ""
    dry_run: bool = True


class RerunRequest(BaseModel):
    failed_only: bool = True


class WithdrawRequest(BaseModel):
    kind: str
    version: str
    restore: bool = False


def create_app(settings=default_settings, gh=None, start_notifier=True):
    gh = gh or GitHub(settings)
    runs, health, actions = Runs(gh, settings), Health(gh, settings), Actions(gh, settings)
    audit = Audit(settings.data_dir)
    app = FastAPI(title="AutoBleem admin", docs_url=None, redoc_url=None, openapi_url="/admin/api/openapi.json")

    def viewer(request: Request):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            login, via = gh.login_of_token(auth[7:].strip()), "api"
        else:
            login = (request.headers.get("x-forwarded-preferred-username")
                     or request.headers.get("x-forwarded-user"))
            via = "browser"
        if not login:
            raise HTTPException(401, "not logged in")
        if not gh.is_member(login):
            raise HTTPException(403, "%s is not a member of %s" % (login, settings.org))
        return {"login": login, "via": via, "can_act": gh.is_release_manager(login)}

    def actor(request: Request, who=Depends(viewer)):
        if not who["can_act"]:
            raise HTTPException(403, "%s is not in the %s team" % (who["login"], settings.release_team))
        if who["via"] == "browser" and request.headers.get("x-ab-request") != "1":
            raise HTTPException(403, "missing X-AB-Request")
        return who

    def act(who, action, params, fn):
        try:
            result = fn()
        except ValueError as e:
            audit.add(who["login"], who["via"], action, params, "refused: %s" % e)
            raise HTTPException(400, str(e))
        except GitHubError as e:
            audit.add(who["login"], who["via"], action, params, "failed: %s" % e)
            raise HTTPException(502, str(e))
        audit.add(who["login"], who["via"], action, params, result)
        return {"result": result}

    @app.get("/admin/api/me")
    def me(who=Depends(viewer)):
        return who

    @app.get("/admin/api/status")
    def status(who=Depends(viewer)):
        return runs.status()

    @app.get("/admin/api/channels")
    def get_channels(who=Depends(viewer)):
        return channels(settings.repo_dir)

    @app.get("/admin/api/health")
    def get_health(who=Depends(viewer)):
        return health.report()

    @app.get("/admin/api/audit")
    def get_audit(who=Depends(viewer)):
        return audit.recent()

    @app.get("/admin/api/promote/preview")
    def preview(kind: str, version: str = "", who=Depends(viewer)):
        try:
            return {"tag": actions.preview(kind, version or None)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/admin/api/nightly")
    def nightly(body: NightlyRequest, who=Depends(actor)):
        return act(who, "nightly", body.model_dump(),
                   lambda: actions.nightly(body.platforms, body.rebuild_all, body.dry_run))

    @app.post("/admin/api/promote")
    def promote(body: PromoteRequest, who=Depends(actor)):
        return act(who, "promote", body.model_dump(),
                   lambda: actions.promote(body.kind, body.version, body.dry_run))

    @app.post("/admin/api/runs/{repo}/{run_id}/cancel")
    def cancel(repo: str, run_id: int, who=Depends(actor)):
        return act(who, "cancel", {"repo": repo, "run": run_id}, lambda: actions.cancel(repo, run_id))

    @app.post("/admin/api/runs/{repo}/{run_id}/rerun")
    def rerun(repo: str, run_id: int, body: RerunRequest = RerunRequest(), who=Depends(actor)):
        return act(who, "rerun", {"repo": repo, "run": run_id, "failed_only": body.failed_only},
                   lambda: actions.rerun(repo, run_id, body.failed_only))

    @app.post("/admin/api/withdraw")
    def withdraw(body: WithdrawRequest, who=Depends(actor)):
        return act(who, "withdraw", body.model_dump(),
                   lambda: actions.withdraw(body.kind, body.version, body.restore))

    @app.post("/admin/api/page")
    def page(who=Depends(actor)):
        return act(who, "page", {}, actions.page)

    @app.get("/admin/")
    def index(who=Depends(viewer)):
        return FileResponse(os.path.join(STATIC, "index.html"))

    if start_notifier:
        Notifier(runs, settings).start()
    return app


app = create_app() if os.environ.get("AB_ADMIN_NO_APP") != "1" else None
