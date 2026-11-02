"""Disposable K3s lab: plan/up/verify/access/down. No application data backups."""
import argparse
import base64
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from recover_k3s import ROOT, Recovery, command
import lab as legacy

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TF_ROOT = ROOT / "terraform/lab"
NODE_ADDRESSES = [f'aws_instance.node["{role}"]' for role in ("server", "agent")]


def validate_config(config):
    for key in ("region", "cluster_name", "availability_zones", "admin_cidrs", "ami_id", "k3s_version", "infra_ref"):
        if not config.get(key) or "REPLACE" in str(config[key]):
            raise RuntimeError(f"Complete {key} in the configuration")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,35}", config["cluster_name"]):
        raise RuntimeError("Invalid cluster name")
    if not re.fullmatch(r"ami-[a-f0-9]+", config["ami_id"]):
        raise RuntimeError("Use a pinned ARM64 Ubuntu AMI ID")
    if not re.fullmatch(r"v\d+\.\d+\.\d+\+k3s\d+", config["k3s_version"]):
        raise RuntimeError("Use a pinned K3s version")
    for cidr in config["admin_cidrs"]:
        network = ipaddress.ip_network(cidr, strict=True)
        if network.version != 4 or network.prefixlen != 32:
            raise RuntimeError("Administrative access requires IPv4 /32 addresses")
    legacy.allowed_origins(config)
    legacy.runtime_secret_ids(config)


def legacy_config(resources):
    by_name = {r["type"] + "." + r["name"]: r["values"] for r in resources}
    cluster = by_name.get("aws_eks_cluster.this")
    if not cluster or "aws_eks_node_group.arm" not in by_name:
        return None
    node = by_name["aws_eks_node_group.arm"]
    return {"cluster_role_arn": cluster["role_arn"], "node_role_arn": node["node_role_arn"],
            "admin_role_arn": by_name["aws_eks_access_entry.admin"]["principal_arn"],
            "kubernetes_version": cluster["version"], "instance_types": node["instance_types"],
            "node_count": max(1, node["scaling_config"][0]["max_size"]), "addon_versions": {
                "vpc_cni": by_name["aws_eks_addon.network"]["addon_version"],
                "coredns": by_name["aws_eks_addon.coredns"]["addon_version"],
                "kube_proxy": by_name["aws_eks_addon.kube_proxy"]["addon_version"]}}


def check_plan(plan, *, adoption=False, keep_network=False, retire_legacy=False):
    """Never silently replace public URLs or delete legacy EKS during up."""
    allowed = set(NODE_ADDRESSES)
    for role in ("server", "agent"):
        allowed.update({f'aws_lb_target_group_attachment.{name}_node["{role}"]' for name in ("edge", "argocd")})
    if adoption:
        allowed.update({"aws_autoscaling_attachment.edge", "aws_autoscaling_attachment.argocd",
                        "aws_vpc_security_group_ingress_rule.nodes_from_nlb",
                        "aws_vpc_security_group_ingress_rule.argocd_nodes_from_nlb",
                        "aws_vpc_security_group_egress_rule.nlb_to_nodes",
                        "aws_vpc_security_group_egress_rule.argocd_to_nodes"})
    if retire_legacy:
        allowed.update({"aws_eks_cluster.this[0]", "aws_eks_node_group.arm[0]",
            "aws_eks_access_entry.admin[0]", "aws_eks_access_policy_association.admin[0]",
            'aws_eks_addon.network["vpc-cni"]', "aws_eks_addon.coredns[0]", "aws_eks_addon.kube_proxy[0]"})
    unexpected = [c["address"] for c in plan.get("resource_changes", [])
                  if "delete" in c["change"]["actions"] and c["address"] not in allowed]
    if unexpected:
        raise RuntimeError("Plan would remove/replace protected infrastructure: " + ", ".join(unexpected))


def needs_rebuild(plan):
    return any(c["address"] in NODE_ADDRESSES and "delete" in c["change"]["actions"]
               for c in plan.get("resource_changes", []) + plan.get("resource_drift", []))


class Cluster(Recovery):
    def __init__(self, args):
        self.args = args
        self.config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        validate_config(self.config)
        for tool in ("aws", "terraform", "kubectl", "helm", "ssh", "ssh-keygen"):
            if not shutil.which(tool):
                raise RuntimeError(f"Missing executable: {tool}; install prerequisites before provisioning")
        self.account = args.account
        self.region = self.config["region"]
        self.cluster = self.config["cluster_name"]
        if not re.fullmatch(r"\d{12}", self.account):
            raise RuntimeError("Expected a 12-digit account ID")
        self.old_dir = ROOT / ".learner-lab" / self.account / self.region / self.cluster
        # Reuse the emergency SSH key during adoption; the journal is only cache.
        self.directory = self.old_dir / "k3s-recovery"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.key = self.directory / "id_ed25519"
        self.kube = self.directory / "kubeconfig"
        self.journal = self.directory / "recovery.json"
        self.state = json.loads(self.journal.read_text()) if self.journal.exists() else {}
        self.bucket = f"quistock-tfstate-{self.account}-{self.region}"
        self.variables_file = self.old_dir / "lab-variables.json"
        os.environ["TF_DATA_DIR"] = str(self.old_dir / "lab-terraform-data")
        os.environ["KUBECONFIG"] = str(self.kube)
        print(f"Target: {self.account} / {self.region} / {self.cluster}", flush=True)
        if self.aws("sts", "get-caller-identity")["Account"] != self.account:
            raise RuntimeError("Wrong AWS account; no infrastructure changed")

    def tf(self, *args, quiet=False):
        params = ["terraform", f"-chdir={TF_ROOT}", *args]
        if quiet:
            return command(params, quiet=True)
        # Terraform never receives machine tokens or application Secrets; stream
        # resource progress instead of appearing frozen during NLB creation.
        result = subprocess.run([str(p) for p in params])
        if result.returncode:
            raise RuntimeError(f"Terraform {args[0]} failed; inspect the preceding output")
        return ""

    def init(self, create=False):
        print("Checking remote Terraform state...", flush=True)
        head = subprocess.run(["aws", "s3api", "head-bucket", "--bucket", self.bucket,
            "--expected-bucket-owner", self.account, "--region", self.region], capture_output=True)
        if head.returncode:
            error = head.stderr.decode(errors="replace")
            if not create or not ("404" in error or "NoSuchBucket" in error):
                raise RuntimeError("State bucket inaccessible; check credentials/permissions. Never use an empty state as fallback.")
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
                "--server-side-encryption-configuration", json.dumps({"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}))
        # Historical key retained deliberately: adopting the current resources
        # never copies them into a second competing Terraform state.
        self.tf("init", "-input=false", "-reconfigure", f"-backend-config=bucket={self.bucket}",
                f"-backend-config=key={self.cluster}/eks.tfstate", f"-backend-config=region={self.region}",
                "-backend-config=use_lockfile=true", quiet=True)

    def outputs(self):
        return json.loads(self.tf("output", "-json", quiet=True))

    def prepare_variables(self, compute=True):
        details = json.loads(self.tf("show", "-json", quiet=True) or "{}")
        resources = details.get("values", {}).get("root_module", {}).get("resources", [])
        retained_eks = legacy_config(resources) or details.get("values", {}).get("outputs", {}).get("legacy_eks_config", {}).get("value")
        managed = any(r["address"].startswith("aws_instance.node[") for r in resources)
        adoption = bool(retained_eks and not managed)
        if adoption and not self.args.adopt_legacy:
            raise RuntimeError("Existing EKS state found. First run requires --adopt-legacy and review of its plan.")
        lost_key = not self.key.exists()
        if lost_key:
            command(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", self.key], quiet=True)
        variables = {k: self.config[k] for k in ("region", "cluster_name", "availability_zones", "admin_cidrs")}
        variables.update(account_id=self.account, ami_id=self.config["ami_id"],
            instance_type=self.config.get("instance_type", "t4g.large"),
            cors_allowed_origins=legacy.allowed_origins(self.config),
            ssh_public_key=self.key.with_suffix(".pub").read_text().strip(), compute_enabled=compute,
            legacy_eks=None if getattr(self.args, "retire_legacy", False) else retained_eks,
            adopt_instances={}, adopt_security_group=None)
        subnets = {r["values"]["id"]: r["index"] for r in resources if r["type"] == "aws_subnet" and r["name"] == "public"}
        placement = details.get("values", {}).get("outputs", {}).get("node_subnet_indices", {}).get("value", {"server":0,"agent":1})
        if managed:
            placement = dict(placement)
            for resource in resources:
                if resource["type"] == "aws_instance" and resource["name"] == "node":
                    placement[resource["index"]] = subnets[resource["values"]["subnet_id"]]
        variables["node_subnet_indices"] = self.config.get("node_subnet_indices", placement)
        if adoption:
            if lost_key:
                raise RuntimeError("Emergency SSH key missing: restore it before adopting current nodes")
            if not all(self.state.get(k) for k in ("server", "agent", "admin_sg")):
                raise RuntimeError("Adoption requires the emergency recovery journal with both EC2 IDs and admin_sg")
            variables["adopt_instances"] = {k:self.state[k] for k in ("server", "agent")}
            variables["adopt_security_group"] = self.state["admin_sg"]
            placement = {role:subnets[self.instance(role)["SubnetId"]] for role in ("server", "agent")}
            variables["node_subnet_indices"] = placement
        self.variables_file.write_text(json.dumps(variables, indent=2), encoding="utf-8")
        return adoption, lost_key and managed

    def plan(self, compute=True, destroy=False):
        adoption, lost_key = self.prepare_variables(compute)
        self.tf("validate", quiet=True)
        path = self.old_dir / "lab.tfplan"
        params = ["plan", "-input=false", f"-var-file={self.variables_file}", f"-out={path}"]
        if destroy:
            params += ["-destroy"]
        elif compute and (lost_key or self.args.rebuild):
            params += [f"-replace={address}" for address in NODE_ADDRESSES]
        self.tf(*params)
        details = json.loads(self.tf("show", "-json", path, quiet=True))
        if not destroy:
            check_plan(details, adoption=adoption, keep_network=not compute,
                       retire_legacy=getattr(self.args, "retire_legacy", False))
            if adoption and needs_rebuild(details):
                raise RuntimeError("Adoption must preserve the existing pair; inspect instance attributes before applying")
            # A lost node means a disposable pair; never join an old agent to a
            # fresh server with stale node credentials or a stale private IP.
            if compute and needs_rebuild(details) and not (lost_key or self.args.rebuild):
                self.tf(*params, *[f"-replace={address}" for address in NODE_ADDRESSES])
                details = json.loads(self.tf("show", "-json", path, quiet=True))
                check_plan(details, adoption=adoption, retire_legacy=getattr(self.args, "retire_legacy", False))
        if not self.args.apply:
            print("Plan only. No EC2 started, replaced or destroyed. Repeat with --apply.")
            return False
        if not destroy and compute and any(c["address"] == NODE_ADDRESSES[0] and "create" in c["change"]["actions"]
                                           for c in details.get("resource_changes", [])):
            self.machine_token = os.environ.get("BWS_ACCESS_TOKEN")
            if not self.machine_token:
                if getattr(self.args, "non_interactive", False) or not sys.stdin.isatty():
                    raise RuntimeError("New cluster requires BWS_ACCESS_TOKEN or an interactive terminal; no plan applied")
                self.machine_token = getpass.getpass("Bitwarden machine token (hidden, memory only): ")
                if not self.machine_token:
                    raise RuntimeError("Empty Bitwarden token; no plan applied")
        self.tf("apply", "-input=false", path)
        return True

    def sync(self):
        outputs = self.outputs()
        nodes = outputs.get("nodes", {}).get("value", {})
        if any(role in nodes and self.state.get(role) != nodes[role]["id"] for role in ("server", "agent")):
            (self.directory / "known_hosts").unlink(missing_ok=True)
        self.state.update(outputs=outputs, version=self.config["k3s_version"])
        for role in ("server", "agent"):
            self.state.pop(role, None)
            if role in nodes:
                self.state[role] = nodes[role]["id"]
        self.save()
        return nodes

    def start_nodes(self):
        started = False
        for role in ("server", "agent"):
            item = self.instance(role)
            state = item["State"]["Name"]
            if state == "stopping":
                self.aws("ec2", "wait", "instance-stopped", "--instance-ids", item["InstanceId"])
                state = "stopped"
            if state == "stopped":
                print(f"Starting {role} {item['InstanceId']}", flush=True)
                self.aws("ec2", "start-instances", "--instance-ids", item["InstanceId"])
                started = True
            self.aws("ec2", "wait", "instance-running", "--instance-ids", item["InstanceId"])
        return started

    def install(self):
        try:
            server = self.instance("server")
            config = self.ssh("server", "sudo cat /etc/rancher/k3s/k3s.yaml", quiet=True)
            self.kube.write_text(config.replace("127.0.0.1", server["PublicIpAddress"]), encoding="utf-8")
            info = json.loads(self.kubectl("get", "nodes", "-o", "json", "--request-timeout=10s", quiet=True))
            ready = [n for n in info["items"] if n["metadata"]["labels"].get("kubernetes.io/arch") == "arm64"
                and n["status"]["nodeInfo"]["kubeletVersion"] == self.config["k3s_version"]
                and any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"])]
            if len(ready) == 2:
                print("Existing K3s pair Ready; installation preserved.", flush=True)
                return
        except (RuntimeError, KeyError, json.JSONDecodeError):
            pass
        super().install()

    def lab(self):
        # Reuse application contracts without Lab.__init__ or any EKS API call.
        obj = legacy.Lab.__new__(legacy.Lab)
        obj.args = self.args
        obj.config = dict(self.config, node_count=2)
        obj.account, obj.region, obj.dir = self.account, self.region, self.directory
        obj.kubeconfig = lambda: None
        obj.outputs = self.outputs
        obj.aws = self.aws
        os.environ["KUBECONFIG"] = str(self.kube)
        return obj

    def bootstrap(self):
        legacy.validate_manifests()
        helper = self.lab()
        try:
            releases = (("argocd", "argocd", "10.9.6"), ("sm-operator", "sm-operator-system", "2.0.3"))
            charts_ready = all(
                (release := json.loads(command(["helm", "get", "metadata", name, "-n", namespace, "-o", "json"], quiet=True)))["status"] == "deployed"
                and release["version"] == version for name, namespace, version in releases)
            applications = json.loads(self.kubectl("get", "applications", "-n", "argocd", "-o", "json", quiet=True))["items"]
            refs = {app["metadata"]["name"]:app["spec"]["source"]["targetRevision"] for app in applications}
            if charts_ready and all(refs.get(app) == self.config["infra_ref"] for app in legacy.APPS):
                for app in legacy.SECRET_APPS:
                    helper.wait_secret(app)
                helper.runtime_config(self.outputs())
                print("Existing charts and Applications match the pinned versions; bootstrap preserved.", flush=True)
                return
        except (RuntimeError, KeyError, json.JSONDecodeError):
            pass
        command(["helm", "repo", "add", "argo", "https://argoproj.github.io/argo-helm", "--force-update"], quiet=True)
        command(["helm", "repo", "add", "bitwarden", "https://charts.bitwarden.com/", "--force-update"], quiet=True)
        command(["helm", "repo", "update", "argo", "bitwarden"], quiet=True)
        print("Reconciling Argo CD and Bitwarden charts...", flush=True)
        helper.argocd(self.outputs())
        for app in legacy.APPS:
            self.kubectl("apply", "-f", "-", stdin=json.dumps({"apiVersion":"v1", "kind":"Namespace", "metadata":{"name":app}}), quiet=True)
        command(["helm", "upgrade", "--install", "sm-operator", "bitwarden/sm-operator", "-n", "sm-operator-system",
            "--create-namespace", "--version", "2.0.3", "--wait", "--timeout", "10m"], quiet=True)
        self.kubectl("wait", "--for=condition=Established", "crd/bitwardensecrets.k8s.bitwarden.com", "--timeout=2m", quiet=True)
        token = None
        for app in legacy.SECRET_APPS:
            existing = json.loads(self.kubectl("get", "secret", "bw-auth-token", "-n", app,
                "--ignore-not-found", "-o", "json", quiet=True) or "{}")
            if not existing.get("data", {}).get("token"):
                if token is None:
                    token = getattr(self, "machine_token", None) or os.environ.get("BWS_ACCESS_TOKEN")
                    if not token:
                        if getattr(self.args, "non_interactive", False) or not sys.stdin.isatty():
                            raise RuntimeError("Bitwarden token missing; run interactively or supply BWS_ACCESS_TOKEN")
                        token = getpass.getpass("Bitwarden machine token (hidden): ")
                    if not token:
                        raise RuntimeError("Bitwarden machine token required for a new cluster")
                secret = {"apiVersion":"v1", "kind":"Secret", "metadata":{"name":"bw-auth-token", "namespace":app},
                    "type":"Opaque", "data":{"token":base64.b64encode(token.encode()).decode()}}
                self.kubectl("apply", "--server-side", "--field-manager=learner-lab-bootstrap", "-f", "-", stdin=json.dumps(secret), quiet=True)
            self.kubectl("apply", "-f", ROOT / f"clusters/us-east1/apps/{app}/bitwarden-secret.yaml", quiet=True)
            helper.wait_secret(app)
        del token
        helper.apply_runtime_secrets()
        helper.runtime_config(self.outputs())
        for app in legacy.APPS:
            helper.apply_application(app)
        for app in legacy.APPS:
            helper.wait_application(app)
            self.kubectl("rollout", "status", f"deployment/{app}", "-n", app, "--timeout=10m")

    def up(self):
        legacy.validate_manifests()
        self.init(create=True)
        if not self.plan():
            return
        self.sync()
        if self.start_nodes():
            # Starting EC2 changes public IPs after the preceding apply. Persist
            # refreshed outputs without changing infrastructure.
            self.tf("apply", "-refresh-only", "-input=false", "-auto-approve", f"-var-file={self.variables_file}")
            self.sync()
        self.install()
        self.bootstrap()
        self.verify()
        print(f"KUBECONFIG={self.kube}")
        print(f"Website: {self.state['outputs']['api_url']['value']}")

    def access(self):
        self.init()
        nodes = self.sync()
        if len(nodes) != 2:
            raise RuntimeError("No compute pair. Run up --apply first")
        server = self.instance("server")
        config = self.ssh("server", "sudo cat /etc/rancher/k3s/k3s.yaml", quiet=True)
        self.kube.write_text(config.replace("127.0.0.1", server["PublicIpAddress"]), encoding="utf-8")
        print(f"KUBECONFIG={self.kube}")
        print(f"Argo CD: {self.state['outputs']['argocd_url']['value']}")

    def down(self):
        if self.args.confirm_destroy != self.account:
            raise RuntimeError("down requires --confirm-destroy with the expected account ID")
        self.init()
        if self.plan(compute=False, destroy=not self.args.keep_network):
            self.sync()
            print("Compute removed; network and URLs retained." if self.args.keep_network else
                  "Managed infrastructure removed. External databases, Bitwarden and state bucket preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "verify", "access", "down"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--adopt-legacy", action="store_true", help="Adopt emergency EC2s into historical Terraform state; preserve EKS at zero nodes")
    parser.add_argument("--rebuild", action="store_true", help="Replace the disposable pair; application data remains external")
    parser.add_argument("--retire-legacy", action="store_true", help="After adoption: remove the unused EKS control plane while keeping K3s and URLs")
    parser.add_argument("--keep-network", action="store_true")
    parser.add_argument("--confirm-destroy")
    parser.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting when a bootstrap token is missing")
    args = parser.parse_args()
    args.migrate_website = False
    if (args.rebuild or args.adopt_legacy or args.retire_legacy) and args.command != "up":
        parser.error("--rebuild, --adopt-legacy and --retire-legacy are only valid with up")
    if args.adopt_legacy and args.retire_legacy:
        parser.error("Adopt first; verify K3s before retiring EKS in a separate plan")
    if args.keep_network and args.command != "down":
        parser.error("--keep-network is only valid with down")
    cluster = Cluster(args)
    if args.command == "verify":
        cluster.init()
        cluster.sync()
    getattr(cluster, args.command)()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError) as error:
        print(f"Stopped: {error}. Keep the remote state and repeat the same command after correction.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted. Keep the remote state and repeat the same command to resume.", file=sys.stderr)
        sys.exit(130)
