"""GitHub for the panel: the autobleem-admin App's installation token (everything the panel itself reads and
does), and a user's own token (a script's bearer - only to learn who it is)."""
import hashlib
import threading
import time

import httpx
import jwt

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


class GitHubError(Exception):
    def __init__(self, status, message):
        super().__init__("GitHub %s: %s" % (status, message))
        self.status = status


class GitHub:
    """`transport` is httpx's - the tests give a MockTransport"""

    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = httpx.Client(base_url=API, headers=HEADERS, timeout=30, transport=transport)
        self._lock = threading.Lock()
        self._token, self._token_until = None, 0
        self._cache = {}  # key -> (until, value)

    # ------------------------------------------------------------------ the App's token
    def _app_jwt(self):
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.settings.app_id},
                          self.settings.private_key(), algorithm="RS256")

    def token(self):
        with self._lock:
            if self._token and time.time() < self._token_until - 120:
                return self._token
            auth = {"Authorization": "Bearer " + self._app_jwt()}
            inst = self._check(self.http.get("/orgs/%s/installation" % self.settings.org, headers=auth))
            tok = self._check(self.http.post("/app/installations/%s/access_tokens" % inst["id"], headers=auth))
            self._token = tok["token"]
            self._token_until = time.time() + 3000  # an hour's token, renewed well before it ends
            return self._token

    @staticmethod
    def _check(r):
        if r.status_code >= 400:
            try:
                message = r.json().get("message", r.text)
            except ValueError:
                message = r.text
            raise GitHubError(r.status_code, message[:300])
        return r.json() if r.content else {}

    def call(self, method, path, body=None, ok=(200, 201, 202, 204)):
        r = self.http.request(method, path, json=body, headers={"Authorization": "Bearer " + self.token()})
        if r.status_code in ok:
            return r.json() if r.content else {}
        return self._check(r)

    def cached(self, key, ttl, fn):
        now = time.time()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        value = fn()
        self._cache[key] = (now + ttl, value)
        return value

    # ------------------------------------------------------------------ who someone is
    def login_of_token(self, user_token):
        """a bearer token's GitHub login, or None when GitHub does not know it"""
        key = "tok:" + hashlib.sha256(user_token.encode()).hexdigest()

        def ask():
            r = self.http.get("/user", headers={"Authorization": "Bearer " + user_token})
            return r.json().get("login") if r.status_code == 200 else None

        return self.cached(key, 300, ask)

    def is_member(self, login):
        def ask():
            r = self.http.get("/orgs/%s/members/%s" % (self.settings.org, login),
                              headers={"Authorization": "Bearer " + self.token()})
            return r.status_code == 204
        return self.cached("member:" + login, 300, ask)

    def is_release_manager(self, login):
        def ask():
            r = self.http.get("/orgs/%s/teams/%s/memberships/%s" % (self.settings.org, self.settings.release_team,
                                                                     login),
                              headers={"Authorization": "Bearer " + self.token()})
            return r.status_code == 200 and r.json().get("state") == "active"
        return self.cached("team:" + login, 300, ask)
