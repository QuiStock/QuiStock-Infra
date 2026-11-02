"""Exercise the real Nginx config with HTTP fixtures on a Docker host.

No AWS resources, credentials, or application databases are used.
"""
import http.client
import http.server
import inspect
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]


class Fixture(http.server.BaseHTTPRequestHandler):
    def handle_request(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        payload = json.dumps({"service": self.server.service, "method": self.command,
                              "path": self.path, "body": body,
                              "authorization": self.headers.get("Authorization"),
                              "cookie": self.headers.get("Cookie"),
                              "origin": self.headers.get("Origin"),
                              "auth_csrf": self.headers.get("X-CSRF-TOKEN"),
                              "core_csrf": self.headers.get("X-XSRF-TOKEN"),
                              "prefix": self.headers.get("X-Forwarded-Prefix"),
                              "proto": self.headers.get("X-Forwarded-Proto")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.server.service == "ai":
            self.send_header("Set-Cookie", "observability_session=fixture; Path=/api/v1/observability; Secure; HttpOnly; SameSite=None")
        else:
            self.send_header("Set-Cookie", "access_token=fixture; Path=/; Secure; HttpOnly")
            self.send_header("Set-Cookie", "refresh_token=fixture; Path=/; Secure; HttpOnly")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = handle_request
    do_POST = handle_request
    do_PATCH = handle_request

    def log_message(self, *args):
        pass


class ProxyIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = "quistock-proxy-test-" + uuid.uuid4().hex[:12]
        cls.fixture = cls.container + "-fixture"
        cls.network = cls.container + "-network"
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.cleanup)
        fixture_script = Path(cls.temp.name) / "fixture.py"
        fixture_script.write_text(
            "import http.server, json, threading, time\n" + inspect.getsource(Fixture) +
            "\nfor service, port in [('core', 8081), ('auth', 8082), ('ai', 8083), ('observe', 8084)]:\n"
            "    server = http.server.ThreadingHTTPServer(('0.0.0.0', port), Fixture)\n"
            "    server.service = service\n"
            "    threading.Thread(target=server.serve_forever, daemon=True).start()\n"
            "while True: time.sleep(60)\n", encoding="utf-8")
        conf = (ROOT / "clusters/us-east1/apps/website/nginx.conf").read_text(encoding="utf-8-sig")
        conf = conf.replace("kube-dns.kube-system.svc.cluster.local", "127.0.0.11")
        conf = conf.replace("api-core.api-core.svc.cluster.local", cls.fixture + ":8081")
        conf = conf.replace("api-auth.api-auth.svc.cluster.local", cls.fixture + ":8082")
        conf = conf.replace("api-chatbot.api-chatbot.svc.cluster.local", cls.fixture + ":8083")
        conf = conf.replace("observe.observe.svc.cluster.local", cls.fixture + ":8084")
        path = Path(cls.temp.name) / "nginx.conf"
        path.write_text(conf, encoding="utf-8")
        html = Path(cls.temp.name) / "html"
        html.mkdir()
        (html / "index.html").write_text('<html><div id="root">React fixture</div></html>', encoding="utf-8")
        (html / "assets").mkdir()
        (html / "assets/app.js").write_text('console.log("fixture");', encoding="utf-8")
        (html / "assets/app.css").write_text('body { color: black; }', encoding="utf-8")
        (html / "assets/app.wasm").write_bytes(b'\x00asm\x01\x00\x00\x00')
        subprocess.run(["docker", "network", "create", cls.network], check=True, stdout=subprocess.PIPE)
        subprocess.run(["docker", "run", "-d", "--rm", "--network", cls.network,
                        "--name", cls.fixture, "--mount",
                        f"type=bind,source={fixture_script},target=/fixture.py,readonly",
                        "python:3.12-alpine", "python", "/fixture.py"], check=True, stdout=subprocess.PIPE)
        subprocess.run(["docker", "run", "-d", "--rm", "--network", cls.network,
                        "-p", "127.0.0.1::8080", "--name", cls.container,
                        "--mount", f"type=bind,source={html},target=/usr/share/nginx/html,readonly",
                        "--mount", f"type=bind,source={path},target=/etc/nginx/nginx.conf,readonly",
                        os.environ.get("NGINX_TEST_IMAGE", "nginx:1.28.0-alpine")], check=True, stdout=subprocess.PIPE)
        port = subprocess.check_output(["docker", "port", cls.container, "8080/tcp"], text=True).strip().rsplit(":", 1)[1]
        cls.url = "http://127.0.0.1:" + port
        for _ in range(60):
            try:
                for route in ("/website-health", "/auth/health", "/api/health/readiness"):
                    with urllib.request.urlopen(cls.url + route, timeout=1) as response:
                        if response.status != 200:
                            raise RuntimeError("Fixture is not ready")
                return
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError):
                time.sleep(1)
        subprocess.run(["docker", "logs", cls.container], check=False)
        raise RuntimeError("Nginx fixture did not start")

    @classmethod
    def cleanup(cls):
        subprocess.run(["docker", "rm", "-f", cls.container, cls.fixture], check=False, stdout=subprocess.PIPE)
        subprocess.run(["docker", "network", "rm", cls.network], check=False, stdout=subprocess.PIPE)
        cls.temp.cleanup()

    def request(self, path, method="GET", body=None, cookie="refresh_token=fixture"):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=body.encode() if body is not None else None,
                                     headers={"Authorization": "Bearer fixture", "Cookie": cookie,
                                              "Origin": "https://any-site.example", "Content-Type": "application/json",
                                              "X-CSRF-TOKEN": "auth-fixture", "X-XSRF-TOKEN": "core-fixture"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read()), r.headers

    def test_observe_api_keeps_native_path_body_and_cookie(self):
        body = '{"email":"fixture@example.com","password":"fixture"}'
        result, headers = self.request("/api/v1/observability/login?test=1", "POST", body,
                                       cookie="observability_session=fixture")
        self.assertEqual((result["service"], result["path"], result["body"]),
                         ("ai", "/api/v1/observability/login?test=1", body))
        self.assertEqual(result["cookie"], "observability_session=fixture")
        self.assertIn("Path=/api/v1/observability;", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("no-store", headers["Cache-Control"])

    def test_observe_redirect_stays_relative_and_preserves_query(self):
        connection = http.client.HTTPConnection(self.url.removeprefix("http://"))
        try:
            connection.request("GET", "/observe?screen=lab")
            response = connection.getresponse()
            self.assertEqual(response.status, 308)
            self.assertEqual(response.getheader("Location"), "/observe/?screen=lab")
            response.read()
        finally:
            connection.close()

    def test_observe_frontend_keeps_subpath(self):
        result, _ = self.request("/observe/assets/app.js")
        self.assertEqual((result["service"], result["path"]),
                         ("observe", "/observe/assets/app.js"))

    def test_core_post_strips_only_api_prefix_and_keeps_body_query_headers(self):
        body = '{"prompt":"fixture"}'
        result, headers = self.request("/api/chat?mode=test", "POST", body)
        self.assertEqual((result["service"], result["method"], result["path"], result["body"]),
                         ("core", "POST", "/chat?mode=test", body))
        self.assertEqual(result["authorization"], "Bearer fixture")
        self.assertEqual(result["cookie"], "refresh_token=fixture")
        self.assertEqual(result["proto"], "https")
        self.assertEqual(result["origin"], "https://any-site.example")
        self.assertEqual(result["core_csrf"], "core-fixture")
        self.assertEqual(result["prefix"], "/api")
        self.assertEqual(len(headers.get_all("Set-Cookie")), 2)

    def test_auth_post_strips_public_prefix_and_preserves_request(self):
        body = '{"email":"fixture@example.com","password":"not-a-secret"}'
        result, _ = self.request("/auth/login?mode=test", "POST", body)
        self.assertEqual((result["service"], result["method"], result["path"], result["body"]),
                         ("auth", "POST", "/login?mode=test", body))
        self.assertEqual(result["auth_csrf"], "auth-fixture")
        self.assertEqual(result["prefix"], "/auth")
        self.assertEqual(result["origin"], "https://any-site.example")

    def test_auth_session_and_documentation_routes_strip_prefix(self):
        for route, method in (("csrf", "GET"), ("refresh", "POST"), ("logout", "POST"),
                              ("v3/api-docs", "GET"), ("swagger-ui/index.html", "GET")):
            with self.subTest(route=route):
                result, _ = self.request("/auth/" + route, method)
                self.assertEqual((result["service"], result["path"]), ("auth", "/" + route))

    def test_nested_core_patch_preserves_query(self):
        result, _ = self.request("/api/products/42?q=a%20b", "PATCH", '{}')
        self.assertEqual((result["method"], result["path"]), ("PATCH", "/products/42?q=a%20b"))

    def test_health_jwks_and_exact_base_paths(self):
        for public, service, native in (("/auth/health", "auth", "/health"),
                                        ("/auth/.well-known/jwks.json", "auth", "/.well-known/jwks.json"),
                                        ("/api/health/readiness", "core", "/health/readiness"),
                                        ("/api", "core", "/"), ("/auth", "auth", "/")):
            with self.subTest(path=public):
                result, _ = self.request(public)
                self.assertEqual((result["service"], result["path"]), (service, native))

    def test_spa_fallback_and_static_assets(self):
        for path in ("/", "/home", "/apix/products", "/authentication/login"):
            with self.subTest(path=path), urllib.request.urlopen(self.url + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"React fixture", response.read())
                self.assertIn("text/html", response.headers["Content-Type"])
        with urllib.request.urlopen(self.url + "/assets/app.js", timeout=5) as response:
            self.assertIn(b"console.log", response.read())
        with urllib.request.urlopen(self.url + "/index.html", timeout=5) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_static_assets_have_browser_compatible_mime_types(self):
        for path, mime in (("/assets/app.js", "application/javascript"),
                           ("/assets/app.css", "text/css"),
                           ("/assets/app.wasm", "application/wasm")):
            with self.subTest(path=path), urllib.request.urlopen(self.url + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), mime)

    def test_unknown_assets_return_404(self):
        for path in ("/assets/missing.js",):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
