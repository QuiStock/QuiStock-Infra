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
import urllib.error
import urllib.request
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


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

    def bootstrap(self):
        self.kubeconfig()
        run(["kubectl", "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=15m"])
        run(["helm", "repo", "add", "argo", "https://argoproj.github.io/argo-helm", "--force-update"])
        run(["helm", "repo", "add", "bitwarden", "https://charts.bitwarden.com/", "--force-update"])
        run(["helm", "repo", "update"])
        run(["helm", "upgrade", "--install", "argocd", "argo/argo-cd", "--namespace", "argocd",
             "--create-namespace", "--version", "10.9.6", "--values", ROOT / "clusters/us-east1/argocd/values.yaml",
             "--wait", "--timeout", "20m"])
        for app in ("api-auth", "api-core"):
            run(["kubectl", "apply", "-f", ROOT / f"clusters/us-east1/bootstrap/{app}-namespace.yaml"])
        run(["helm", "upgrade", "--install", "sm-operator", "bitwarden/sm-operator", "--namespace",
             "sm-operator-system", "--create-namespace", "--version", "2.0.3", "--wait", "--timeout", "10m"])
        run(["kubectl", "wait", "--for=condition=Established", "crd/bitwardensecrets.k8s.bitwarden.com", "--timeout=2m"])
        token = getpass.getpass("Bitwarden machine token (hidden): ")
        if not token:
            raise RuntimeError("Empty token; bootstrap stopped.")
        for app in ("api-auth", "api-core"):
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
        required = {"DB_URL", "DB_USERNAME", "DB_PASSWORD", "AUTH_JWT_ISSUER"}
        if app == "api-auth":
            required |= {"MONGODB_URI", "MONGODB_DATABASE", "AUTH_JWT_PRIVATE_KEY_BASE64",
                         "AUTH_JWT_PUBLIC_KEY_BASE64", "AUTH_JWT_KEY_ID", "AUTH_RATE_LIMIT_HMAC_KEY"}
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
        for app in ("api-auth", "api-core"):
            self.wait_secret(app)
            self.wait_application(app)
            run(["kubectl", "rollout", "status", f"deployment/{app}", "-n", app, "--timeout=10m"])
        run(["kubectl", "get", "pods", "-A"])
        if include_public:
            self.wait_application("edge")
            self.verify_public(self.outputs()["api_url"]["value"])
        print("Cluster and applications ready. Complete real login/database tests in the runbook.")

    def outputs(self):
        self.init()
        return json.loads(run(["terraform", f"-chdir={ROOT / 'terraform/eks'}", "output", "-json"], capture=True).stdout)

    def public(self):
        """Reconcile the GitOps proxy and verify the Terraform-owned gateway."""
        self.kubeconfig()
        run(["kubectl", "apply", "-f", ROOT / "clusters/us-east1/bootstrap/edge-application.yaml"])
        self.wait_application("edge")
        run(["kubectl", "rollout", "status", "deployment/edge", "-n", "edge", "--timeout=10m"])
        outputs = self.outputs()
        target = outputs["edge_target_group_arn"]["value"]
        for _ in range(120):
            targets = self.aws("elbv2", "describe-target-health", "--target-group-arn", target)["TargetHealthDescriptions"]
            if targets and all(t["TargetHealth"]["State"] == "healthy" for t in targets):
                break
            time.sleep(5)
        else:
            raise RuntimeError("Private NLB targets did not become healthy. Check NodePort 30080, security groups and edge Pods.")
        self.verify_public(outputs["api_url"]["value"])
        print(f"API HTTPS: {outputs['api_url']['value']}")
        print(f"Core: {outputs['core_url']['value']}")
        print(f"Auth: {outputs['auth_url']['value']}")

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
        for app in ("edge", "api-core", "api-auth"):
            run(["kubectl", "delete", "application", app, "-n", "argocd", "--ignore-not-found"])
        self.tf("destroy", "-input=false", "-auto-approve", f"-var-file={self.dir / 'variables.json'}")
        print("Infrastructure removed. State bucket retained for recovery/audit; check AWS for residual resources.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "up", "bootstrap", "verify", "public", "down"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--apply", action="store_true", help="Apply the saved plan and bootstrap; otherwise up only plans")
    parser.add_argument("--confirm-destroy")
    args = parser.parse_args()
    lab = Lab(args)
    if args.command == "up":
        lab.preflight()
        lab.init(create=True)
        lab.tf("validate")
        plan = lab.dir / "cluster.tfplan"
        lab.tf("plan", "-input=false", f"-var-file={lab.dir / 'variables.json'}", f"-out={plan}")
        if args.apply:
            details = json.loads(run(["terraform", f"-chdir={ROOT / 'terraform/eks'}", "show", "-json", plan], capture=True).stdout)
            if any("delete" in change["change"]["actions"] for change in details.get("resource_changes", [])):
                raise RuntimeError("Plan includes deletion/replacement. Review manually; up will not destroy existing resources.")
            lab.tf("apply", "-input=false", plan)
            lab.bootstrap()
        else:
            print("Plan only (state bucket created/configured). Re-run with --apply after review.")
    else:
        getattr(lab, args.command)()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyboardInterrupt) as error:
        print(f"Stopped: {error}. Renew credentials if needed, then resume the same account.", file=sys.stderr)
        sys.exit(1)
