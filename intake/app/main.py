"""The tester portal's intake service: five endpoints under /submit/ (the contract is intake/README.md).

It is the only writer of the portal's data directory (except decisions/, the admin panel's) and reads the site's
testplans/ read-only. Caddy routes /submit/* here; nothing else of the data directory is served.
"""
import hashlib
import ipaddress
import json
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .store import ID_RE, Refused, Store, check_zip, new_id, stamp

STEP_STATUSES = ("ok", "problem", "na")


def utcnow():
    return datetime.now(timezone.utc)


class RateLimiter:
    """In memory, keyed by the salted hash of the client address: nothing about the address outlives its window."""

    def __init__(self, salt):
        self.salt = salt
        self.hits = {}   # (bucket, hash) -> [monotonic-or-clock seconds]

    def _key(self, bucket, addr):
        return bucket, hashlib.sha256((self.salt + addr).encode()).hexdigest()

    def _live(self, key, now, window):
        hits = [t for t in self.hits.get(key, []) if now - t < window]
        if hits:
            self.hits[key] = hits
        else:
            self.hits.pop(key, None)
        return hits

    def allowed(self, bucket, addr, limits, now):
        """False when any of the (count, seconds) limits is already used up."""
        key = self._key(bucket, addr)
        longest = max(w for _, w in limits)
        hits = self._live(key, now, longest)
        return all(sum(1 for t in hits if now - t < w) < n for n, w in limits)

    def record(self, bucket, addr, now):
        self.hits.setdefault(self._key(bucket, addr), []).append(now)


def create_app(settings=None, clock=utcnow):
    s = settings or Settings()
    store = Store(s, clock)
    store.prepare()
    limiter = RateLimiter(s.salt)
    trusted = [ipaddress.ip_network(n, strict=False) for n in s.trusted_proxies]
    app = FastAPI(title="AutoBleem tester intake", docs_url=None, redoc_url=None, openapi_url=None)

    def now_s():
        return clock().timestamp()

    def client_addr(request):
        """The direct peer; the first hop of X-Forwarded-For only when the peer is in the trusted (Caddy) network."""
        peer = request.client.host if request.client else "unknown"
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded and any(peer_ip in net for net in trusted):
            try:
                return str(ipaddress.ip_address(forwarded.split(",")[0].strip()))
            except ValueError:
                return peer
        return peer

    async def read_body(request, limit):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise Refused("request too large", 413)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise Refused("request too large", 413)
            chunks.append(chunk)
        return b"".join(chunks)

    def parse_json(body):
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Refused("the body is not valid JSON")
        if not isinstance(data, dict):
            raise Refused("the body must be a JSON object")
        return data

    def text(data, key, cap, required=False):
        value = data.get(key)
        if value is None or value == "":
            if required:
                raise Refused("%s is required" % key)
            return ""
        if not isinstance(value, str):
            raise Refused("%s must be text" % key)
        if len(value) > cap:
            raise Refused("%s is longer than %d characters" % (key, cap))
        return value

    @app.exception_handler(Refused)
    async def refused(_request, exc):
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    def too_many():
        return Refused("too many requests, try again later", 429)

    # ---- POST /submit/claim

    @app.post("/submit/claim")
    async def claim(request: Request):
        addr = client_addr(request)
        if not limiter.allowed("claim", addr, s.limit_claim, now_s()):
            raise too_many()
        data = parse_json(await read_body(request, s.max_claim_body))
        platform, version = data.get("platform"), data.get("version")
        plan = store.plan(platform, version)
        limiter.record("claim", addr, now_s())
        given = data.get("claim")
        rec = store.get_claim(platform, version, given) if isinstance(given, str) else None
        if rec is not None and store.claim_open(rec):
            if data.get("release") is True:
                store.close_claim(platform, version, rec, "released")
                return {"released": True}
        elif data.get("release") is True:
            if not isinstance(given, str):
                raise Refused("release needs a claim")
            return {"released": True}   # already closed or expired: nothing left to release
        else:
            rec = None
        if rec is None:
            section, _ = store.neediest(platform, version)
            rec = store.make_claim(platform, version, section["id"])
        section = next(x for x in plan["sections"] if x["id"] == rec["section"])
        return {"claim": rec["claim"],
                "section": {k: section[k] for k in ("id", "title", "minutes", "needs")},
                "expires": rec["expires"]}

    # ---- GET /submit/coverage

    @app.get("/submit/coverage")
    async def coverage(version: str = ""):
        version = version or store.current_version()
        if not version or version not in store.versions():
            raise Refused("unknown version", 404)
        platforms = {}
        for platform in store.platforms_of(version):
            section, passes = store.neediest(platform, version)
            platforms[platform] = {"section": {"id": section["id"], "title": section["title"]}, "passes": passes}
        return {"version": version, "target": store.knobs()[0], "platforms": platforms}

    # ---- POST /submit/testplan

    @app.post("/submit/testplan")
    async def testplan(request: Request):
        addr = client_addr(request)
        if not limiter.allowed("submit", addr, s.limit_submit, now_s()):
            raise too_many()
        data = parse_json(await read_body(request, s.max_result_body))
        if data.get("website"):
            return {"id": new_id()}   # the honeypot: a normal-looking answer, nothing stored
        platform, version, section_id = data.get("platform"), data.get("version"), data.get("section")
        plan = store.plan(platform, version)
        section = next((x for x in plan["sections"] if x["id"] == section_id), None) \
            if isinstance(section_id, str) else None
        if section is None:
            raise Refused("unknown section")
        device = text(data, "device", s.cap_short)
        contact = text(data, "contact", s.cap_short)
        steps = data.get("steps")
        if not isinstance(steps, list):
            raise Refused("steps must be a list")
        seen = {}
        for st in steps:
            if not isinstance(st, dict) or not isinstance(st.get("id"), str):
                raise Refused("every step needs an id")
            if st["id"] not in section["steps"]:
                raise Refused("step %s is not in section %s" % (st["id"][:40], section_id))
            if st["id"] in seen:
                raise Refused("step %s is answered twice" % st["id"])
            if st.get("status") not in STEP_STATUSES:
                raise Refused("step %s: status must be ok, problem or na" % st["id"])
            comment = text(st, "comment", s.cap_comment)
            if st["status"] == "problem" and not comment.strip():
                raise Refused("step %s: a comment is required on a problem" % st["id"])
            seen[st["id"]] = {"id": st["id"], "status": st["status"], "comment": comment}
        missing = [x for x in section["steps"] if x not in seen]
        if missing:
            raise Refused("steps not answered: %s" % ", ".join(missing))
        given = data.get("claim")
        if given is not None and (not isinstance(given, str) or len(given) > 64):
            raise Refused("claim must be text")
        rec = store.get_claim(platform, version, given) if given else None
        assigned = rec is not None and rec.get("section") == section_id and rec.get("closed_by") is None
        rid = new_id()
        record = {"id": rid, "platform": platform, "version": version, "section": section_id,
                  "claim": given or None, "steps": [seen[x] for x in section["steps"]],
                  "device": device, "contact": contact,
                  "received": stamp(clock()), "unassigned": not assigned}
        store.store_result(platform, version, record)
        if assigned:
            store.close_claim(platform, version, rec, rid)
        limiter.record("submit", addr, now_s())
        return {"id": rid}

    # ---- POST /submit/issue

    @app.post("/submit/issue")
    async def issue(request: Request):
        addr = client_addr(request)
        if not limiter.allowed("submit", addr, s.limit_submit, now_s()):
            raise too_many()
        body = await read_body(request, s.max_issue_body)
        sent = {"done": False}

        async def replay():
            if sent["done"]:
                return {"type": "http.disconnect"}
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        try:
            form = await Request(request.scope, replay).form()
        except Exception:
            raise Refused("the body must be a multipart form")
        if form.get("website"):
            return {"id": new_id()}   # the honeypot
        data = {k: v for k, v in form.items() if isinstance(v, str)}
        platform, version = data.get("platform"), data.get("version")
        store.plan(platform, version)
        steps = text(data, "steps", s.cap_long, required=True)
        expected = text(data, "expected", s.cap_long, required=True)
        actual = text(data, "actual", s.cap_long, required=True)
        contact = text(data, "contact", s.cap_short)
        upload = form.get("logs")
        logs = None
        if upload is not None and not isinstance(upload, str) and (upload.filename or "") != "":
            if not upload.filename.lower().endswith(".zip"):
                raise Refused("logs must be a .zip file")
            logs = await upload.read()
            if logs:
                check_zip(logs, s.max_zip_total, s.max_zip_entries)
            else:
                logs = None
        if logs is not None and data.get("consent_logs") != "on":
            raise Refused("attaching logs needs the consent tick")
        rid = new_id()
        record = {"id": rid, "platform": platform, "version": version, "steps": steps, "expected": expected,
                  "actual": actual, "contact": contact, "consent_logs": "on" if logs is not None else "",
                  "received": stamp(clock()), "has_logs": logs is not None}
        store.store_issue(record, logs)
        limiter.record("submit", addr, now_s())
        return {"id": rid}

    # ---- GET /submit/status/<id>

    @app.get("/submit/status/{rid}")
    async def status(rid: str):
        found = store.find_report(rid) if ID_RE.match(rid) else None
        if found is None:
            raise Refused("unknown id", 404)
        kind, received = found
        return {"id": rid, "kind": kind, "received": received, "state": store.decision_state(rid)}

    return app


app = create_app() if os.environ.get("AB_INTAKE_NO_APP") != "1" else None
