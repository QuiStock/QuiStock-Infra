"""Exercise the real Nginx config with HTTP fixtures on a Linux Docker host.

No AWS resources, credentials, or application databases are used.
"""
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
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
                              "proto": self.headers.get("X-Forwarded-Proto")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
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


@unittest.skipUnless(os.name == "posix", "Real proxy integration runs on the Linux CI Docker host")
class ProxyIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers = []
        cls.container = "quistock-proxy-test-" + uuid.uuid4().hex[:12]
        for service in ("core", "auth"):
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
            server.service = service
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.servers.append(server)
        conf = (ROOT / "clusters/us-east1/edge/nginx.conf").read_text(encoding="utf-8-sig")
        conf = conf.replace("kube-dns.kube-system.svc.cluster.local", "127.0.0.1")
        conf = conf.replace("api-core.api-core.svc.cluster.local", f"127.0.0.1:{cls.servers[0].server_port}")
        conf = conf.replace("api-auth.api-auth.svc.cluster.local", f"127.0.0.1:{cls.servers[1].server_port}")
        cls.temp = tempfile.TemporaryDirectory()
        path = Path(cls.temp.name) / "nginx.conf"
        path.write_text(conf, encoding="utf-8")
        cls.addClassCleanup(cls.cleanup)
        subprocess.run(["docker", "run", "-d", "--rm", "--network", "host", "--name", cls.container,
                        "--mount", f"type=bind,source={path},target=/etc/nginx/nginx.conf,readonly",
                        "nginx:1.28.0-alpine"], check=True)
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8080/edge-health", timeout=1) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1)
        subprocess.run(["docker", "logs", cls.container], check=False)
        raise RuntimeError("Nginx fixture did not start")

    @classmethod
    def cleanup(cls):
        subprocess.run(["docker", "rm", "-f", cls.container], check=False)
        for server in cls.servers:
            server.shutdown()
            server.server_close()
        cls.temp.cleanup()

    def request(self, path, method="GET", body=None):
        req = urllib.request.Request("http://127.0.0.1:8080" + path, method=method,
                                     data=body.encode() if body is not None else None,
                                     headers={"Authorization": "Bearer fixture", "Cookie": "refresh_token=fixture",
                                              "Origin": "https://any-site.example", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read()), r.headers

    def test_core_post_strips_only_api_prefix_and_keeps_body_query_headers(self):
        body = '{"prompt":"fixture"}'
        result, headers = self.request("/api/chat?mode=test", "POST", body)
        self.assertEqual((result["service"], result["method"], result["path"], result["body"]),
                         ("core", "POST", "/chat?mode=test", body))
        self.assertEqual(result["authorization"], "Bearer fixture")
        self.assertEqual(result["cookie"], "refresh_token=fixture")
        self.assertEqual(result["proto"], "https")
        self.assertIsNone(result["origin"])
        self.assertEqual(len(headers.get_all("Set-Cookie")), 2)

    def test_auth_post_preserves_native_auth_prefix(self):
        body = '{"email":"fixture@example.com","password":"not-a-secret"}'
        result, _ = self.request("/auth/login?mode=test", "POST", body)
        self.assertEqual((result["service"], result["method"], result["path"], result["body"]),
                         ("auth", "POST", "/auth/login?mode=test", body))

    def test_nested_core_patch_preserves_query(self):
        result, _ = self.request("/api/products/42?q=a%20b", "PATCH", '{}')
        self.assertEqual((result["method"], result["path"]), ("PATCH", "/products/42?q=a%20b"))

    def test_health_jwks_and_exact_base_paths(self):
        for public, service, native in (("/auth/health", "auth", "/health"),
                                        ("/auth/.well-known/jwks.json", "auth", "/.well-known/jwks.json"),
                                        ("/api/health/readiness", "core", "/health/readiness"),
                                        ("/api", "core", "/"), ("/auth", "auth", "/auth")):
            with self.subTest(path=public):
                result, _ = self.request(public)
                self.assertEqual((result["service"], result["path"]), (service, native))

    def test_unknown_paths_do_not_leak_into_apis(self):
        for path in ("/", "/apix/products", "/authentication/login"):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
