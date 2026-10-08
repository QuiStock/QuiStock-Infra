#!/usr/bin/env python3
"""Account-isolated Learner Lab provisioning. Requires Python 3.10+, AWS CLI,
Terraform 1.11.4+, kubectl and Helm. Never stores AWS or Bitwarden credentials.
"""
import argparse
import base64
import getpass
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SECRET_APPS = ("api-auth", "api-core", "api-chatbot")
APPS = (*SECRET_APPS, "website")


def validate_manifests():
    """Fail before provisioning if the draft application contracts are incomplete."""
    missing = [str(path.relative_to(ROOT)) for path in (ROOT / "clusters/us-east1/apps").rglob("*")
               if path.is_file() and path.suffix in (".yaml", ".conf")
               and "REPLACE_WITH_" in path.read_text(encoding="utf-8")]
    if missing:
        raise RuntimeError("Complete application image/Bitwarden placeholders first: " + ", ".join(sorted(missing)))

# Only resources belonging to the former Argo CD entry may be replaced/removed.
# Cluster, nodes, API Gateway, private NLB and target group are never allowlisted.
ARGOCD_ENTRY_MIGRATION = frozenset({
    "aws_lb_listener.argocd",
    "aws_vpc_security_group_egress_rule.argocd_to_nodes",
    "aws_vpc_security_group_ingress_rule.argocd_nodes_from_nlb",
    "aws_vpc_security_group_ingress_rule.argocd_from_cloudfront",
    "aws_cloudfront_vpc_origin.argocd",
    "aws_cloudfront_distribution.argocd",
})


def validate_plan(details, *, migrate_argocd_public=False):
    deletions = {c["address"] for c in details.get("resource_changes", []) if "delete" in c["change"]["actions"]}
    allowed = ARGOCD_ENTRY_MIGRATION if migrate_argocd_public else frozenset()
    if deletions - allowed:
        raise RuntimeError("Plan includes deletion/replacement outside the authorized Argo CD entry migration: " + ", ".join(sorted(deletions - allowed)))


def run(args, *, capture=False, stdin=None, check=True):
    result = subprocess.run([str(x) for x in args], input=stdin, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, check=False)
    if check and result.returncode:
        # Do not echo output from commands handling secrets.
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0]} {args[1]}")
    return result


class Lab:
    def __init__(self, args):
        self.args = args
        self.config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if "REPLACE_" in json.dumps(self.config):
            raise RuntimeError("Complete all REPLACE_ values in the configuration first.")
        for tool in ("aws", "terraform", "kubectl", "helm"):
            if not shutil.which(tool):
                raise RuntimeError(f"Missing executable: {tool}")
        self.region = self.config["region"]
        identity = self.aws("sts", "get-caller-identity")
        self.account = identity["Account"]
        if self.account != args.account:
            raise RuntimeError(f"Wrong AWS account: expected {args.account}, got {self.account}")
        self.dir = ROOT / ".learner-lab" / self.account / self.region / self.config["cluster_name"]
        self.dir.mkdir(parents=True, exist_ok=True)
        os.environ["KUBECONFIG"] = str(self.dir / "kubeconfig")
        os.environ["TF_DATA_DIR"] = str(self.dir / "terraform-data")
        self.bucket = f"quistock-tfstate-{self.account}-{self.region}"

    def aws(self, *args):
        result = run(["aws", *args, "--region", self.region, "--output", "json", "--no-cli-pager"], capture=True)
        return json.loads(result.stdout or "{}")

    def tf(self, *args):
        return run(["terraform", f"-chdir={ROOT / 'terraform/eks'}", *args])

    def admin_principal(self):
        # Learner Lab denies GetRole on voclabs. Building a configured principal
        # does not inspect or change IAM; EKS validates it when creating access.
        arn = self.config.get("admin_role_arn")
        if not arn:
            name = self.config.get("admin_role_name", "")
            arn = f"arn:aws:iam::{self.account}:role/{name}"
        if not re.fullmatch(rf"arn:aws:iam::{self.account}:role/[A-Za-z0-9_+=,.@/-]+", arn):
            raise RuntimeError("Administrative principal must be an IAM role ARN in the target account, not an STS session ARN.")
        return arn

    def preflight(self):
        validate_manifests()
        print(f"Target: {self.account} / {self.region} / {self.config['cluster_name']}")
        variables = {k: self.config[k] for k in (
            "region", "cluster_name", "kubernetes_version", "availability_zones",
            "admin_cidrs", "instance_types", "node_count", "addon_versions")}
        variables["account_id"] = self.account
        variables["admin_role_arn"] = self.admin_principal()
        for kind in ("cluster", "node"):
            role = self.aws("iam", "get-role", "--role-name", self.config[f"{kind}_role_name"])["Role"]
            variables[f"{kind}_role_arn"] = role["Arn"]
            if kind != "admin":
                expected = "eks.amazonaws.com" if kind == "cluster" else "ec2.amazonaws.com"
                statements = role["AssumeRolePolicyDocument"]["Statement"]
                if not any(s.get("Effect") == "Allow" and expected in
                           ([s.get("Principal", {}).get("Service")] if isinstance(s.get("Principal", {}).get("Service"), str)
                            else s.get("Principal", {}).get("Service", [])) for s in statements):
                    raise RuntimeError(f"Role {kind} does not trust {expected}")
        if variables["admin_role_arn"] == variables["node_role_arn"]:
            raise RuntimeError("Operator role must differ from node role: EKS creates an EC2_LINUX access entry for nodes.")
        types = self.aws("ec2", "describe-instance-types", "--instance-types", *self.config["instance_types"])["InstanceTypes"]
        if not all("arm64" in t["ProcessorInfo"]["SupportedArchitectures"] for t in types):
            raise RuntimeError("All instance types must support ARM64.")
        for name, version in self.config["addon_versions"].items():
            addon = {"vpc_cni": "vpc-cni", "kube_proxy": "kube-proxy", "coredns": "coredns"}[name]
            info = self.aws("eks", "describe-addon-versions", "--addon-name", addon,
                            "--kubernetes-version", self.config["kubernetes_version"])
            matches = [v for a in info["addons"] for v in a["addonVersions"]
                       if v["addonVersion"] == version and "arm64" in v["architecture"]]
            if not matches:
                raise RuntimeError(f"Incompatible ARM addon: {addon} {version}")
        (self.dir / "variables.json").write_text(json.dumps(variables), encoding="utf-8")
        print("Read checks passed. PassRole, service-linked roles, quotas and billing still require lab verification.")

    def init(self, create=False):
        head = run(["aws", "s3api", "head-bucket", "--bucket", self.bucket,
                    "--expected-bucket-owner", self.account, "--region", self.region], capture=True, check=False)
        if head.returncode:
            if not create:
                raise RuntimeError("State bucket unavailable; do not start a new state for existing resources.")
            params = ["s3api", "create-bucket", "--bucket", self.bucket]
            if self.region != "us-east-1":
                params += ["--create-bucket-configuration", f"LocationConstraint={self.region}"]
            self.aws(*params)
        if create:
            self.aws("s3api", "put-public-access-block", "--bucket", self.bucket,
                     "--public-access-block-configuration", "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true")
            self.aws("s3api", "put-bucket-versioning", "--bucket", self.bucket,
                     "--versioning-configuration", "Status=Enabled")
            self.aws("s3api", "put-bucket-encryption", "--bucket", self.bucket,
                     "--server-side-encryption-configuration", json.dumps({"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}))
        self.tf("init", "-input=false", "-reconfigure", f"-backend-config=bucket={self.bucket}",
                f"-backend-config=key={self.config['cluster_name']}/eks.tfstate",
                f"-backend-config=region={self.region}", "-backend-config=use_lockfile=true")

    def kubeconfig(self):
        run(["aws", "eks", "update-kubeconfig", "--name", self.config["cluster_name"],
             "--region", self.region, "--kubeconfig", self.dir / "kubeconfig"])

    def plan(self, *, create=False):
        self.preflight()
        self.init(create=create)
        if not create:
            state = run(["terraform", f"-chdir={ROOT / 'terraform/eks'}", "state", "list"], capture=True)
            if "aws_eks_cluster.this" not in state.stdout.splitlines():
                raise RuntimeError("Existing cluster missing from remote state. Check account, region and cluster name; update will not create a new cluster.")
        self.tf("validate")
        plan = self.dir / "cluster.tfplan"
        self.tf("plan", "-input=false", f"-var-file={self.dir / 'variables.json'}", f"-out={plan}")
        if not self.args.apply:
            print("Plan only. Re-run with --apply after review.")
            return False
        details = json.loads(run(["terraform", f"-chdir={ROOT / 'terraform/eks'}", "show", "-json", plan], capture=True).stdout)
        validate_plan(details, migrate_argocd_public=self.args.migrate_argocd_public)
        self.tf("apply", "-input=false", plan)
        return True

    def update(self):
        """Update existing state and Argo CD without rewriting application secrets."""
        if self.plan():
            outputs = self.outputs()
            self.argocd(outputs)
            self.verify_argocd(outputs)

    def argocd(self, outputs):
        self.kubeconfig()
        run(["helm", "repo", "add", "argo", "https://argoproj.github.io/argo-helm", "--force-update"])
        run(["helm", "repo", "update", "argo"])
        run(["helm", "upgrade", "--install", "argocd", "argo/argo-cd", "--namespace", "argocd",
             "--create-namespace", "--version", "10.9.6", "--values", ROOT / "clusters/us-east1/argocd/values.yaml",
             "--set-string", f"configs.cm.url={outputs['argocd_url']['value']}",
             "--wait", "--timeout", "20m"])

    def bootstrap(self):
        validate_manifests()
        self.kubeconfig()
        run(["kubectl", "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=15m"])
        run(["helm", "repo", "add", "argo", "https://argoproj.github.io/argo-helm", "--force-update"])
        run(["helm", "repo", "add", "bitwarden", "https://charts.bitwarden.com/", "--force-update"])
        run(["helm", "repo", "update"])
        self.argocd(self.outputs())
        for app in SECRET_APPS:
            run(["kubectl", "apply", "-f", ROOT / f"clusters/us-east1/bootstrap/{app}-namespace.yaml"])
        run(["helm", "upgrade", "--install", "sm-operator", "bitwarden/sm-operator", "--namespace",
             "sm-operator-system", "--create-namespace", "--version", "2.0.3", "--wait", "--timeout", "10m"])
        run(["kubectl", "wait", "--for=condition=Established", "crd/bitwardensecrets.k8s.bitwarden.com", "--timeout=2m"])
        token = getpass.getpass("Bitwarden machine token (hidden): ")
        if not token:
            raise RuntimeError("Empty token; bootstrap stopped.")
        for app in SECRET_APPS:
            secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "bw-auth-token", "namespace": app},
                      "type": "Opaque", "data": {"token": base64.b64encode(token.encode()).decode()}}
            run(["kubectl", "apply", "--server-side", "--field-manager=learner-lab-bootstrap", "-f", "-"],
                stdin=json.dumps(secret), capture=True)
            run(["kubectl", "apply", "-f", ROOT / f"clusters/us-east1/apps/{app}/bitwarden-secret.yaml"])
            self.wait_secret(app)
            run(["kubectl", "apply", "-f", ROOT / f"clusters/us-east1/bootstrap/{app}-application.yaml"])
            self.wait_application(app)
        del token
        self.verify(include_public=False)
        self.public()

    def wait_secret(self, app):
        # Query only key names; secret values never enter this process or logs.
        manifest = (ROOT / f"clusters/us-east1/apps/{app}/bitwarden-secret.yaml").read_text(encoding="utf-8")
        required = set(re.findall(r"^\s+secretKeyName:\s*(\S+)\s*$", manifest, re.MULTILINE))
        if not required:
            raise RuntimeError(f"No mapped Bitwarden keys for {app}")
        for _ in range(120):
            r = run(["kubectl", "get", "secret", app.removeprefix("api-") + "-external", "-n", app,
                     "-o", 'go-template={{range $k,$v := .data}}{{$k}}{{"\\n"}}{{end}}'], capture=True, check=False)
            if r.returncode == 0 and required <= set(r.stdout.splitlines()):
                return
            time.sleep(5)
        raise RuntimeError(f"Secret synchronization timed out: {app}")

    def wait_application(self, app):
        for _ in range(240):
            r = run(["kubectl", "get", "application", app, "-n", "argocd", "-o", "json"], capture=True)
            status = json.loads(r.stdout).get("status", {})
            if status.get("sync", {}).get("status") == "Synced" and status.get("health", {}).get("status") == "Healthy":
                return
            time.sleep(5)
        raise RuntimeError(f"Argo Application did not become Synced/Healthy: {app}")

    def verify(self, *, include_public=True):
        self.kubeconfig()
        nodes = json.loads(run(["kubectl", "get", "nodes", "-o", "json"], capture=True).stdout)["items"]
        if not nodes or any(n["metadata"]["labels"].get("kubernetes.io/arch") != "arm64" or
                            not any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"]) for n in nodes):
            raise RuntimeError("Expected Ready ARM64 nodes.")
        for app in SECRET_APPS:
            self.wait_secret(app)
            self.wait_application(app)
            run(["kubectl", "rollout", "status", f"deployment/{app}", "-n", app, "--timeout=10m"])
        run(["kubectl", "get", "pods", "-A"])
        if include_public:
            self.wait_application("website")
            run(["kubectl", "rollout", "status", "deployment/website", "-n", "website", "--timeout=10m"])
            outputs = self.outputs()
            self.verify_public(outputs["api_url"]["value"])
            self.verify_argocd(outputs)
        print("All four applications ready. Complete functional tests in the runbook." if include_public
              else "Internal applications ready; website publication follows.")

    def outputs(self):
        self.init()
        return json.loads(run(["terraform", f"-chdir={ROOT / 'terraform/eks'}", "output", "-json"], capture=True).stdout)

    def public(self):
        """Reconcile React and its proxy through the existing Terraform-owned gateway."""
        validate_manifests()
        self.kubeconfig()
        outputs = self.outputs()
        target = outputs["edge_target_group_arn"]["value"]
        self.migrate_website()
        run(["kubectl", "apply", "-f", ROOT / "clusters/us-east1/bootstrap/website-application.yaml"])
        self.wait_application("website")
        run(["kubectl", "rollout", "status", "deployment/website", "-n", "website", "--timeout=10m"])
        for _ in range(120):
            targets = self.aws("elbv2", "describe-target-health", "--target-group-arn", target)["TargetHealthDescriptions"]
            if targets and all(t["TargetHealth"]["State"] == "healthy" for t in targets):
                break
            time.sleep(5)
        else:
            raise RuntimeError("Private NLB targets did not become healthy. Check NodePort 30080, security groups and website Pods.")
        self.verify_public(outputs["api_url"]["value"])
        print(f"API HTTPS: {outputs['api_url']['value']}")
        print(f"Website HTTPS: {outputs['api_url']['value']}")
        print(f"Core: {outputs['core_url']['value']}")
        print(f"Auth: {outputs['auth_url']['value']}")
        self.verify_argocd(outputs)

    def migrate_website(self):
        """Release the fixed NodePort; never delete the legacy namespace or secrets."""
        legacy = run(["kubectl", "get", "service", "edge", "-n", "edge", "--ignore-not-found", "-o", "name"], capture=True)
        application = run(["kubectl", "get", "application", "edge", "-n", "argocd", "--ignore-not-found", "-o", "name"], capture=True)
        deployment = run(["kubectl", "get", "deployment", "edge", "-n", "edge", "--ignore-not-found", "-o", "name"], capture=True)
        if not any(result.stdout.strip() for result in (legacy, application, deployment)):
            return
        if not self.args.migrate_website:
            raise RuntimeError("Legacy edge detected. Re-run with --migrate-website after reviewing the website migration runbook (brief public downtime).")
        if application.stdout.strip():
            run(["kubectl", "patch", "application", "edge", "-n", "argocd", "--type=merge", "-p", '{"metadata":{"finalizers":[]}}'])
            run(["kubectl", "delete", "application", "edge", "-n", "argocd", "--wait=true"])
        run(["kubectl", "delete", "service", "edge", "-n", "edge", "--ignore-not-found", "--wait=true"])
        run(["kubectl", "delete", "deployment", "edge", "-n", "edge", "--ignore-not-found", "--wait=true"])

    def verify_argocd(self, outputs):
        target = outputs["argocd_target_group_arn"]["value"]
        for _ in range(120):
            targets = self.aws("elbv2", "describe-target-health", "--target-group-arn", target)["TargetHealthDescriptions"]
            if targets and all(t["TargetHealth"]["State"] == "healthy" for t in targets):
                break
            time.sleep(5)
        else:
            raise RuntimeError("Argo CD NLB targets did not become healthy. Check NodePort 30081 and the Helm upgrade.")
        url = outputs["argocd_url"]["value"]
        context = self.argocd_tls_context()
        for attempt in range(120):
            try:
                with urllib.request.urlopen(url + "/healthz", timeout=10, context=context) as response:
                    if response.status != 200:
                        raise RuntimeError("Argo CD public health check failed.")
                with urllib.request.urlopen(url + "/api/v1/applications", timeout=10, context=context):
                    raise RuntimeError("Argo CD applications API is accessible without authentication.")
            except urllib.error.HTTPError as error:
                if error.code in (401, 403) and error.url == url + "/api/v1/applications":
                    print(f"Argo CD HTTPS: {url}")
                    return
                if attempt == 119:
                    raise RuntimeError("Argo CD public NLB endpoint failed HTTP verification.") from error
            except (urllib.error.URLError, TimeoutError):
                if attempt == 119:
                    raise RuntimeError("Argo CD public NLB endpoint did not become reachable.")
            time.sleep(5)

    def argocd_tls_context(self):
        # Read only the public certificate through authenticated Kubernetes.
        # Never read the password/private key or disable TLS globally.
        for secret in ("argocd-server-tls", "argocd-secret"):
            result = run(["kubectl", "get", "secret", secret, "-n", "argocd",
                          "-o", r"jsonpath={.data.tls\.crt}"], capture=True, check=False)
            if result.returncode == 0 and result.stdout.strip():
                certificate = base64.b64decode(result.stdout, validate=True).decode("ascii")
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                # The generated certificate lacks the NLB DNS name. Trust the
                # cluster certificate while retaining certificate verification.
                context.check_hostname = False
                context.load_verify_locations(cadata=certificate)
                return context
        raise RuntimeError("Argo CD TLS certificate missing. Check the Helm rollout and server.insecure=false.")

    def verify_public(self, url):
        # No tokens/passwords are used here. Real login remains an operator test.
        origin = "https://development.example"
        preflight = urllib.request.Request(url + "/auth/login", method="OPTIONS", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        for attempt in range(60):
            try:
                with urllib.request.urlopen(preflight, timeout=10) as response:
                    if response.status not in (200, 204) or response.headers.get("Access-Control-Allow-Origin") != origin or response.headers.get("Access-Control-Allow-Credentials") != "true":
                        raise RuntimeError("Credentialed CORS preflight failed; inspect HTTP API CORS configuration.")
                for path in ("/auth/health", "/api/health/readiness", "/auth/.well-known/jwks.json"):
                    with urllib.request.urlopen(url + path, timeout=10) as response:
                        if response.status != 200:
                            raise RuntimeError(f"Public routing check failed: {path}")
                for path in ("/", "/index.html", "/home"):
                    with urllib.request.urlopen(url + path, timeout=10) as response:
                        html = response.read().lower()
                        if response.status != 200 or "text/html" not in response.headers.get("Content-Type", "") or b"<html" not in html:
                            raise RuntimeError(f"React website/SPA routing check failed: {path}")
                return
            except (urllib.error.URLError, TimeoutError):
                if attempt == 59:
                    raise RuntimeError("Public gateway did not become reachable/healthy; inspect VPC link and integrations.")
                time.sleep(5)

    def down(self):
        if self.args.confirm_destroy != self.account:
            raise RuntimeError("Destruction requires --confirm-destroy ACCOUNT_ID")
        self.init()
        if not (self.dir / "variables.json").exists():
            raise RuntimeError("Run preflight in this account first to regenerate variables; do not replace the remote state.")
        self.kubeconfig()
        # Refuse infrastructure deletion while cloud-owned load balancers still exist.
        services = json.loads(run(["kubectl", "get", "svc", "-A", "-o", "json"], capture=True).stdout)["items"]
        if any(s["spec"].get("type") == "LoadBalancer" for s in services):
            raise RuntimeError("Remove LoadBalancer Services and wait for AWS load balancer deletion before down.")
        ingresses = json.loads(run(["kubectl", "get", "ingress", "-A", "-o", "json"], capture=True).stdout)["items"]
        if ingresses:
            raise RuntimeError("Remove Ingress resources and verify cloud cleanup before down.")
        for app in ("edge", *reversed(APPS)):
            run(["kubectl", "delete", "application", app, "-n", "argocd", "--ignore-not-found"])
        self.tf("destroy", "-input=false", "-auto-approve", f"-var-file={self.dir / 'variables.json'}")
        print("Infrastructure removed. State bucket retained for recovery/audit; check AWS for residual resources.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "up", "update", "bootstrap", "verify", "public", "down"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--apply", action="store_true", help="Apply the saved plan for up/update; otherwise only plan")
    parser.add_argument("--migrate-argocd-public", action="store_true", help="For update only: allow replacement/cleanup of the former Argo CD entry, never cluster/API resources")
    parser.add_argument("--confirm-destroy")
    parser.add_argument("--migrate-website", action="store_true", help="For up/bootstrap/public: replace the old edge with the website on NodePort 30080 (brief downtime)")
    args = parser.parse_args()
    if args.migrate_argocd_public and args.command != "update":
        parser.error("--migrate-argocd-public is only supported with update")
    if args.migrate_website and args.command not in ("up", "bootstrap", "public"):
        parser.error("--migrate-website is only supported with up/bootstrap/public")
    lab = Lab(args)
    if args.command == "up":
        if lab.plan(create=True):
            lab.bootstrap()
    else:
        getattr(lab, args.command)()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyboardInterrupt) as error:
        print(f"Stopped: {error}. Preserve state; inspect the error before resuming the same account.", file=sys.stderr)
        sys.exit(1)
