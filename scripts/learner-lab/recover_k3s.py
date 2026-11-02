"""Recover an existing Lab into K3s on permitted EC2 instances.

Keeps EKS/state intact. Copies secrets directly between authenticated APIs in
memory. Publish is separate and requires healthy new targets before removing
the old targets. Runtime journal and SSH/kubeconfig credentials stay ignored.
Requires AWS CLI, kubectl, Helm, OpenSSH, and access to the existing EKS API.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
os.environ["PATH"] = os.pathsep.join([
    str(ROOT / ".learner-lab/tools"),
    str(ROOT / ".learner-lab/tools/windows-amd64"), os.environ["PATH"]])


def command(args, *, stdin=None, quiet=False):
    # Binary stdin preserves LF for Linux shells when launched from Windows.
    result = subprocess.run([str(a) for a in args], input=stdin.encode("utf-8") if stdin is not None else None,
                            capture_output=True)
    if result.returncode:
        # Neither stdout nor stderr is safe to print when transferring secrets.
        raise RuntimeError(f"Command failed: {args[0]} {args[1]} (exit {result.returncode})")
    output = result.stdout.decode("utf-8", errors="replace")
    if not quiet and output.strip():
        print(output.strip(), flush=True)
    return output


def clean_resource(item):
    item = {k: v for k, v in item.items() if k != "status"}
    item["metadata"] = {k: v for k, v in item["metadata"].items()
                        if k in ("name", "namespace", "labels", "annotations")}
    item["metadata"].get("annotations", {}).pop("kubectl.kubernetes.io/last-applied-configuration", None)
    return item


class Recovery:
    def __init__(self, args):
        self.args = args
        self.config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        self.region = self.config["region"]
        self.account = args.account
        self.cluster = self.config["cluster_name"]
        self.old_dir = ROOT / ".learner-lab" / self.account / self.region / self.cluster
        self.old_kube = self.old_dir / "kubeconfig"
        self.directory = self.old_dir / "k3s-recovery"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = self.directory / "recovery.json"
        self.state = json.loads(self.journal.read_text()) if self.journal.exists() else {}
        self.key = self.directory / "id_ed25519"
        self.kube = self.directory / "kubeconfig"
        identity = self.aws("sts", "get-caller-identity")
        if identity["Account"] != self.account:
            raise RuntimeError("Wrong AWS account")

    def save(self):
        self.journal.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def aws(self, *args):
        return json.loads(command(["aws", *args, "--region", self.region,
                                   "--output", "json", "--no-cli-pager"], quiet=True) or "{}")

    def kubectl(self, *args, old=False, stdin=None, quiet=False):
        return command(["kubectl", "--kubeconfig", self.old_kube if old else self.kube,
                        *args], stdin=stdin, quiet=quiet)

    def prepare(self):
        if not self.key.exists():
            command(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", self.key], quiet=True)
        if "version" not in self.state:
            request = urllib.request.Request("https://api.github.com/repos/k3s-io/k3s/releases/latest",
                                             headers={"User-Agent": "QuiStock-Lab-Recovery"})
            with urllib.request.urlopen(request, timeout=20) as response:
                self.state["version"] = json.load(response)["tag_name"]
            self.save()
        group = self.aws("eks", "describe-nodegroup", "--cluster-name", self.cluster,
                         "--nodegroup-name", "quistock-arm")["nodegroup"]
        self.state["old_asg"] = group["resources"]["autoScalingGroups"][0]["name"]
        cluster = self.aws("eks", "describe-cluster", "--name", self.cluster)["cluster"]
        self.state["vpc"] = cluster["resourcesVpcConfig"]["vpcId"]
        self.state["node_sg"] = cluster["resourcesVpcConfig"]["clusterSecurityGroupId"]
        self.state["subnets"] = group["subnets"]
        self.state["ami"] = self.aws("ssm", "get-parameter", "--name",
            "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id")["Parameter"]["Value"]
        env_before = os.environ.get("TF_DATA_DIR")
        os.environ["TF_DATA_DIR"] = str(self.old_dir / "terraform-data")
        try:
            self.state["outputs"] = json.loads(command(
                ["terraform", f"-chdir={ROOT / 'terraform/eks'}", "output", "-json"], quiet=True))
        finally:
            if env_before is None:
                os.environ.pop("TF_DATA_DIR", None)
            else:
                os.environ["TF_DATA_DIR"] = env_before
        for name in ("edge_target_group_arn", "argocd_target_group_arn", "api_url", "argocd_url"):
            if name not in self.state["outputs"]:
                raise RuntimeError(f"Missing existing Terraform output: {name}")
        self.save()
        print(f"Prepared K3s {self.state['version']}; no EKS resources changed.")

    def provision(self):
        if "ami" not in self.state:
            self.prepare()
        if "admin_sg" not in self.state:
            name = f"{self.cluster}-k3s-recovery"
            groups = self.aws("ec2", "describe-security-groups", "--filters",
                f"Name=vpc-id,Values={self.state['vpc']}", f"Name=group-name,Values={name}")["SecurityGroups"]
            self.state["admin_sg"] = groups[0]["GroupId"] if groups else self.aws(
                "ec2", "create-security-group", "--group-name", name,
                "--description", "K3s recovery admin and node traffic", "--vpc-id", self.state["vpc"])["GroupId"]
            self.save()
        sg = self.state["admin_sg"]
        current = self.aws("ec2", "describe-security-groups", "--group-ids", sg)["SecurityGroups"][0]["IpPermissions"]
        wanted = []
        for port in (22, 6443):
            for cidr in self.config["admin_cidrs"]:
                if not cidr.endswith("/32"):
                    raise RuntimeError("Recovery requires exact operator IPv4 /32 CIDRs")
                wanted.append({"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
                               "IpRanges": [{"CidrIp": cidr}]})
        for protocol, port in (("tcp", 6443), ("tcp", 10250), ("udp", 8472)):
            wanted.append({"IpProtocol": protocol, "FromPort": port, "ToPort": port,
                           "UserIdGroupPairs": [{"GroupId": sg}]})
        for permission in wanted:
            field = "IpRanges" if "IpRanges" in permission else "UserIdGroupPairs"
            key = "CidrIp" if field == "IpRanges" else "GroupId"
            present = any(p.get("IpProtocol") == permission["IpProtocol"] and
                          p.get("FromPort") == permission["FromPort"] and
                          p.get("ToPort") == permission["ToPort"] and
                          any(r.get(key) == permission[field][0][key] for r in p.get(field, []))
                          for p in current)
            if not present:
                self.aws("ec2", "authorize-security-group-ingress", "--group-id", sg,
                         "--ip-permissions", json.dumps([permission]))
        pubkey = self.key.with_suffix(".pub").read_text().strip()
        user_data = "#cloud-config\n" + json.dumps({"ssh_authorized_keys": [pubkey],
            "package_update": True, "packages": ["curl", "iptables", "conntrack", "socat"]})
        for index, role in enumerate(("server", "agent")):
            if role in self.state:
                continue
            result = self.aws("ec2", "run-instances", "--image-id", self.state["ami"],
                "--instance-type", "t4g.large", "--subnet-id", self.state["subnets"][index],
                "--security-group-ids", self.state["node_sg"], sg,
                "--count", "1", "--client-token", f"{self.cluster}-k3s-recovery-{role}-v1",
                "--metadata-options", "HttpTokens=required,HttpPutResponseHopLimit=1",
                "--block-device-mappings", json.dumps([{"DeviceName": "/dev/sda1", "Ebs": {
                    "VolumeSize": 30, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}]),
                "--tag-specifications", json.dumps([{"ResourceType": "instance", "Tags": [
                    {"Key": "Name", "Value": f"{self.cluster}-k3s-{role}"},
                    {"Key": "ManagedBy", "Value": "quistock-k3s-recovery"}]}]),
                "--user-data", user_data)
            self.state[role] = result["Instances"][0]["InstanceId"]
            self.save()
            print(f"Created {role}: {self.state[role]}", flush=True)

    def instance(self, role):
        return self.aws("ec2", "describe-instances", "--instance-ids", self.state[role])["Reservations"][0]["Instances"][0]

    def ssh(self, role, remote, *, stdin=None, quiet=False):
        ip = self.instance(role).get("PublicIpAddress")
        if not ip:
            raise RuntimeError(f"{role} has no public IP yet")
        return command(["ssh", "-i", self.key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                        "-o", "StrictHostKeyChecking=accept-new", "-o",
                        f"UserKnownHostsFile={self.directory / 'known_hosts'}", f"ubuntu@{ip}", remote],
                       stdin=stdin, quiet=quiet)

    def install(self):
        version = self.state["version"]
        for role in ("server", "agent"):
            for attempt in range(90):
                try:
                    self.ssh(role, "sudo cloud-init status --wait", quiet=True)
                    break
                except RuntimeError:
                    if attempt == 89:
                        raise
                    time.sleep(10)
        server = self.instance("server")
        # No AWS API credentials are assigned to these nodes. IMDS is used only
        # by the OS; Kubernetes uses its own locally generated credentials.
        self.ssh("server", "sudo bash -s", stdin=f"""set -eu
curl -sfL --retry 3 --connect-timeout 10 --max-time 60 https://raw.githubusercontent.com/k3s-io/k3s/{version}/install.sh -o /tmp/install-k3s.sh
INSTALL_K3S_VERSION='{version}' sh /tmp/install-k3s.sh server --disable traefik --disable servicelb --tls-san {server['PublicIpAddress']} --node-ip {server['PrivateIpAddress']} --write-kubeconfig-mode 600
""", quiet=True)
        token = self.ssh("server", "sudo cat /var/lib/rancher/k3s/server/node-token", quiet=True).strip()
        # Token is sent over SSH stdin, never user-data, argv or tool output.
        self.ssh("agent", "sudo bash -s", stdin=f"""set -eu
curl -sfL --retry 3 --connect-timeout 10 --max-time 60 https://raw.githubusercontent.com/k3s-io/k3s/{version}/install.sh -o /tmp/install-k3s.sh
export K3S_TOKEN='{token}'
INSTALL_K3S_VERSION='{version}' K3S_URL='https://{server['PrivateIpAddress']}:6443' sh /tmp/install-k3s.sh agent
""", quiet=True)
        del token
        config = self.ssh("server", "sudo cat /etc/rancher/k3s/k3s.yaml", quiet=True)
        self.kube.write_text(config.replace("127.0.0.1", server["PublicIpAddress"]), encoding="utf-8")
        self.kubectl("wait", "--for=condition=Ready", "nodes", "--all", "--timeout=5m")
        self.kubectl("get", "nodes", "-o", "wide")

    def migrate(self):
        os.environ["KUBECONFIG"] = str(self.kube)
        # Preserve the original Argo password, signing key, TLS and repo access.
        namespaces = ("argocd", "api-auth", "api-core", "api-chatbot", "observe", "website")
        for namespace in namespaces:
            manifest = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}
            self.kubectl("apply", "-f", "-", stdin=json.dumps(manifest), quiet=True)
            secrets = json.loads(self.kubectl("get", "secrets", "-n", namespace, "-o", "json", old=True, quiet=True))
            copied = 0
            for secret in secrets["items"]:
                if secret.get("type") in ("helm.sh/release.v1", "kubernetes.io/service-account-token"):
                    continue
                self.kubectl("apply", "--server-side", "--field-manager=k3s-recovery", "-f", "-",
                             stdin=json.dumps(clean_resource(secret)), quiet=True)
                copied += 1
            print(f"Transferred {copied} Secrets to {namespace}; values suppressed.", flush=True)
        command(["helm", "repo", "add", "argo", "https://argoproj.github.io/argo-helm", "--force-update"])
        command(["helm", "repo", "add", "bitwarden", "https://charts.bitwarden.com/", "--force-update"])
        command(["helm", "repo", "update"], quiet=True)
        command(["helm", "upgrade", "--install", "argocd", "argo/argo-cd", "-n", "argocd",
                 "--version", "10.9.6", "-f", ROOT / "clusters/us-east1/argocd/values.yaml",
                 "--set-string", f"configs.cm.url={self.state['outputs']['argocd_url']['value']}",
                 "--wait", "--timeout", "15m"], quiet=True)
        command(["helm", "upgrade", "--install", "sm-operator", "bitwarden/sm-operator", "-n",
                 "sm-operator-system", "--create-namespace", "--version", "2.0.3", "--wait", "--timeout", "10m"], quiet=True)
        lab = self.lab()
        lab.runtime_config(self.state["outputs"])
        lab.apply_runtime_secrets()
        for app in namespaces[1:]:
            lab.apply_application(app)
        for app in namespaces[1:]:
            lab.wait_application(app)
            self.kubectl("rollout", "status", f"deployment/{app}", "-n", app, "--timeout=10m")
        self.state["migrated"] = True
        self.save()

    def lab(self):
        spec = importlib.util.spec_from_file_location("lab", Path(__file__).with_name("lab.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        obj = module.Lab(argparse.Namespace(config=self.args.config, account=self.account,
            apply=False, vector_size=None, migrate_argocd_public=False, migrate_node_role=False,
            migrate_website=False, confirm_destroy=None))
        obj.kubeconfig = lambda: None
        obj.outputs = lambda: self.state["outputs"]
        os.environ["KUBECONFIG"] = str(self.kube)
        return obj

    def publish(self):
        if not self.state.get("migrated"):
            raise RuntimeError("Run migrate and validate applications before publishing")
        targets = [{"Id": self.state[role]} for role in ("server", "agent")]
        for name in ("edge_target_group_arn", "argocd_target_group_arn"):
            arn = self.state["outputs"][name]["value"]
            self.aws("elbv2", "register-targets", "--target-group-arn", arn,
                     "--targets", json.dumps(targets))
            for attempt in range(90):
                health = self.aws("elbv2", "describe-target-health", "--target-group-arn", arn,
                                  "--targets", json.dumps(targets))["TargetHealthDescriptions"]
                if len(health) == 2 and all(t["TargetHealth"]["State"] == "healthy" for t in health):
                    break
                if attempt == 89:
                    raise RuntimeError(f"New targets not healthy: {name}; old targets preserved")
                time.sleep(10)
        # Persist rollback inventory before detaching existing ASG registrations.
        if "previous_targets" not in self.state:
            self.state["previous_targets"] = {}
            for name in ("edge_target_group_arn", "argocd_target_group_arn"):
                arn = self.state["outputs"][name]["value"]
                old = self.aws("elbv2", "describe-target-health", "--target-group-arn", arn)["TargetHealthDescriptions"]
                self.state["previous_targets"][name] = [t["Target"] for t in old
                    if t["Target"]["Id"] not in (self.state["server"], self.state["agent"])]
            self.save()
        for name in ("edge_target_group_arn", "argocd_target_group_arn"):
            arn = self.state["outputs"][name]["value"]
            self.aws("autoscaling", "detach-load-balancer-target-groups",
                     "--auto-scaling-group-name", self.state["old_asg"], "--target-group-arns", arn)
        self.state["published"] = True
        self.save()
        print("Published through existing NLBs; original EKS nodes and Terraform state retained.")

    def verify(self):
        lab = self.lab()
        public_check = lab.verify_public
        argo_check = lab.verify_argocd

        def verify_public(url):
            print("Checking public application routing and authentication...", flush=True)
            public_check(url)
            print("Public application checks passed.", flush=True)

        def verify_argocd(outputs):
            print("Checking Argo CD targets and authenticated access (old targets may be draining)...", flush=True)
            argo_check(outputs)

        lab.verify_public = verify_public
        lab.verify_argocd = verify_argocd
        lab.verify()
        self.state["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "provision", "install", "migrate", "publish", "verify"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    getattr(Recovery(args), args.phase)()


if __name__ == "__main__":
    main()
