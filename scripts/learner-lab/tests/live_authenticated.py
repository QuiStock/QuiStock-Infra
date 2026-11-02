"""Live AWS smoke test. Credentials remain in memory; no migrations or business writes.

Creates one synthetic conversation. Optional restart targets only the IA deployment.
"""
import argparse
from datetime import datetime, timezone
from getpass import getpass
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


class LiveTest:
    def __init__(self, base):
        self.base = base.rstrip("/")
        parsed = urlsplit(self.base)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path):
            raise ValueError("Use an HTTPS origin without credentials, path, query or fragment")
        self.cookies = CookieJar()
        self.auth = build_opener(HTTPCookieProcessor(self.cookies))
        self.core = build_opener()
        self.token = None
        self.conversation = None
        self.ended = False
        self.results = []
        self.requests = []

    def request(self, path, *, method="GET", body=None, auth=False, csrf=None):
        headers = {"Accept": "application/json", "Origin": self.base}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if not auth:
            if not self.token:
                raise RuntimeError("No authenticated session")
            headers["Authorization"] = "Bearer " + self.token
        if csrf:
            headers["X-CSRF-TOKEN"] = csrf
        req = Request(self.base + path, method=method, headers=headers,
                      data=json.dumps(body).encode() if body is not None else None)
        try:
            response = (self.auth if auth else self.core).open(req, timeout=35)
        except HTTPError as error:
            code = error.code
            error.close()
            raise RuntimeError(f"{method} {path}: HTTP {code}") from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError(f"{method} {path}: transport failure") from None
        with response:
            raw = response.read()
            if not raw:
                return None
            if response.headers.get_content_type() != "application/json":
                raise RuntimeError(f"{method} {path}: expected JSON")
            return json.loads(raw)

    def record(self, name, action):
        start = time.monotonic()
        try:
            detail = action()
            row = {"test": name, "result": "pass"}
            if detail is not None:
                row["detail"] = detail
        except Exception as error:
            # Never report exception bodies that could contain API data or credentials.
            row = {"test": name, "result": "fail", "error_type": type(error).__name__}
            if isinstance(error, (RuntimeError, AssertionError)):
                row["error"] = str(error)[:180]
            self.results.append(row)
            print(json.dumps(row), flush=True)
            raise
        row["seconds"] = round(time.monotonic() - start, 2)
        self.results.append(row)
        print(json.dumps(row), flush=True)

    def load_token(self):
        tokens = [cookie.value for cookie in self.cookies if cookie.name == "access_token"]
        if len(tokens) != 1:
            raise RuntimeError("Auth did not return exactly one access cookie")
        self.token = tokens[0]

    def csrf(self):
        data = self.request("/auth/csrf", auth=True)
        if not isinstance(data, dict) or not data.get("token"):
            raise RuntimeError("Auth CSRF response has no token")
        return data["token"]

    def login(self):
        email = input("Conta comercial de teste (MANAGER/EMPLOYEE): ").strip()
        password = getpass("Senha (oculta, enviada somente ao Auth AWS): ")
        try:
            self.request("/auth/login", method="POST", auth=True,
                         body={"email": email, "password": password, "platform": "mobile"})
        finally:
            del email, password
        self.load_token()
        return {"access_cookie_received": True}

    def profile(self):
        data = self.request("/api/profile")
        assert isinstance(data, dict), "Profile response is not an object"
        return {"profile_loaded": True}

    def branches(self):
        data = self.request("/api/branches")
        assert isinstance(data, list) and data, "No active store returned for the test account"
        return {"store_count": len(data)}

    def message(self, message, *, require_success=False):
        payload = {"message": message}
        if self.conversation:
            payload["conversation_id"] = self.conversation
        data = self.request("/api/chat", method="POST", body=payload)
        assert isinstance(data, dict) and data.get("conversation_id"), "Chat returned no conversation ID"
        if self.conversation:
            assert data["conversation_id"] == self.conversation, "Conversation changed unexpectedly"
        self.conversation = data["conversation_id"]
        assert data.get("response"), "Chat returned an empty response"
        allowed = {"success"} if require_success else {"success", "clarification_required"}
        assert data.get("status") in allowed, "Chat status: " + str(data.get("status"))
        if data.get("request_id"):
            self.requests.append(data["request_id"])
        return {"status": data["status"], "request_id": data.get("request_id"),
                "response_characters": len(data["response"])}

    def history(self):
        data = self.request("/api/chat/conversations/" + quote(self.conversation, safe="") + "/messages")
        assert isinstance(data, dict) and isinstance(data.get("messages"), list), "History format is invalid"
        assert len(data["messages"]) >= 6, "History did not persist all three test turns"
        return {"messages": len(data["messages"])}

    def end(self):
        data = self.request("/api/chat/conversations/" + quote(self.conversation, safe="") + "/end",
                            method="POST", body={})
        self.ended = True
        return {"request_accepted": True}

    def refresh(self):
        self.request("/auth/refresh", method="POST", auth=True, body={}, csrf=self.csrf())
        self.load_token()
        self.profile()
        return {"new_access_validated_by_core": True}

    def logout(self):
        self.request("/auth/logout", method="POST", auth=True, body={}, csrf=self.csrf())
        self.token = None
        self.cookies.clear()
        return {"test_session_closed": True}

    def restart(self, kubeconfig, account):
        env = dict(os.environ, AWS_PROFILE="quistock-lab")
        observed = subprocess.check_output(["aws", "sts", "get-caller-identity", "--query", "Account",
                                            "--output", "text"], env=env, text=True).strip()
        if observed != account:
            raise RuntimeError("Refusing restart in a different AWS account")
        command = ["kubectl", "--kubeconfig", str(kubeconfig), "-n", "api-chatbot"]
        subprocess.run(command + ["rollout", "restart", "deployment/api-chatbot"], env=env, check=True)
        subprocess.run(command + ["rollout", "status", "deployment/api-chatbot", "--timeout=5m"], env=env, check=True)
        return {"deployment_ready_after_restart": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--report", default=".learner-lab/live-authenticated-results.json")
    parser.add_argument("--restart-kubeconfig", type=Path)
    parser.add_argument("--account")
    args = parser.parse_args()
    if args.restart_kubeconfig and (not args.account or not args.restart_kubeconfig.is_file()):
        parser.error("Restart requires an existing kubeconfig and an explicit expected account")
    test = LiveTest(args.base_url)
    try:
        test.record("commercial_login", test.login)
        test.record("authenticated_profile", test.profile)
        test.record("authorized_store_read", test.branches)
        test.record("chat_greeting", lambda: test.message("Ola", require_success=True))
        test.record("chat_faq", lambda: test.message("O Quistock executa pedidos ou promocoes automaticamente?", require_success=True))
        test.record("chat_commercial_read", lambda: test.message("Mostre as sugestoes comerciais vigentes de pedido para minha loja."))
        test.record("persisted_conversation_history", test.history)
        test.record("end_conversation", test.end)
        test.record("refresh_and_core_access", test.refresh)
        if args.restart_kubeconfig:
            test.record("controlled_ia_restart", lambda: test.restart(args.restart_kubeconfig, args.account))
            test.record("history_survives_ia_restart", test.history)
        test.record("logout", test.logout)
    except Exception:
        if test.token and test.conversation and not test.ended:
            try:
                test.record("close_test_conversation_after_failure", test.end)
            except Exception:
                pass
        if test.token:
            try:
                test.record("close_test_session_after_failure", test.logout)
            except Exception:
                pass
    finally:
        report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "base_url": test.base,
                  "conversation_id": test.conversation, "request_ids": test.requests, "tests": test.results,
                  "passed": sum(row["result"] == "pass" for row in test.results),
                  "failed": sum(row["result"] == "fail" for row in test.results)}
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {target}; {report['passed']} passed; {report['failed']} failed.")
    return int(bool(report["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
