import argparse
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))
import cluster


def changes(address, actions):
    return {"address": address, "change": {"actions": actions}}


class LifecycleTests(unittest.TestCase):
    def test_network_replacement_rejected_even_during_adoption(self):
        for address in ("aws_lb.edge", "aws_apigatewayv2_api.edge", "aws_vpc.this", "aws_eks_cluster.this[0]"):
            with self.subTest(address=address), self.assertRaises(RuntimeError):
                cluster.check_plan({"resource_changes": [changes(address, ["delete", "create"])]}, adoption=True)

    def test_pair_replacement_and_legacy_attachment_removal_allowed(self):
        cluster.check_plan({"resource_changes": [changes(cluster.NODE_ADDRESSES[0], ["delete", "create"]),
                           changes("aws_autoscaling_attachment.edge", ["delete"])]}, adoption=True)

    def test_old_attachment_deletion_requires_explicit_adoption(self):
        with self.assertRaises(RuntimeError):
            cluster.check_plan({"resource_changes": [changes("aws_autoscaling_attachment.edge", ["delete"])]})

    def test_retire_legacy_does_not_authorize_network_removal(self):
        cluster.check_plan({"resource_changes": [changes("aws_eks_cluster.this[0]", ["delete"])]}, retire_legacy=True)
        with self.assertRaises(RuntimeError):
            cluster.check_plan({"resource_changes": [changes("aws_lb.argocd", ["delete"])]}, retire_legacy=True)

    def test_missing_node_drift_rebuilds_pair_but_fresh_creation_does_not(self):
        self.assertTrue(cluster.needs_rebuild({"resource_drift": [changes(cluster.NODE_ADDRESSES[1], ["delete"])]}))
        self.assertFalse(cluster.needs_rebuild({"resource_changes": [changes(cluster.NODE_ADDRESSES[0], ["create"])]}))

    def test_lost_agent_replans_replacement_of_both_nodes(self):
        obj = cluster.Cluster.__new__(cluster.Cluster)
        obj.args = argparse.Namespace(apply=False, rebuild=False, retire_legacy=False)
        obj.old_dir, obj.variables_file = Path("."), Path("variables.json")
        obj.prepare_variables = Mock(return_value=(False, False))
        first = {"resource_drift": [changes(cluster.NODE_ADDRESSES[1], ["delete"])]}
        final = {"resource_changes": [changes(a, ["delete", "create"]) for a in cluster.NODE_ADDRESSES]}
        obj.tf = Mock(side_effect=["", "", json.dumps(first), "", json.dumps(final)])
        self.assertFalse(obj.plan())
        plans = [c.args for c in obj.tf.call_args_list if c.args[0] == "plan"]
        self.assertEqual(len(plans), 2)
        for address in cluster.NODE_ADDRESSES:
            self.assertIn(f"-replace={address}", plans[1])

    def test_forbidden_state_bucket_never_creates_empty_replacement(self):
        obj = cluster.Cluster.__new__(cluster.Cluster)
        obj.bucket, obj.account, obj.region = "state", "123456789012", "us-east-1"
        obj.aws, obj.tf = Mock(), Mock()
        with patch.object(cluster.subprocess, "run", return_value=SimpleNamespace(returncode=1, stderr=b"403 Forbidden")):
            with self.assertRaisesRegex(RuntimeError, "State bucket inaccessible"):
                obj.init(create=True)
        obj.aws.assert_not_called()
        obj.tf.assert_not_called()

    def test_new_server_without_bootstrap_token_does_not_apply_plan(self):
        obj = cluster.Cluster.__new__(cluster.Cluster)
        obj.args = argparse.Namespace(apply=True, rebuild=True, retire_legacy=False, non_interactive=True)
        obj.old_dir, obj.variables_file = Path("."), Path("variables.json")
        obj.prepare_variables = Mock(return_value=(False, False))
        plan = {"resource_changes": [changes(a, ["delete", "create"]) for a in cluster.NODE_ADDRESSES]}
        obj.tf = Mock(side_effect=["", "", json.dumps(plan)])
        with patch.dict(cluster.os.environ, {"BWS_ACCESS_TOKEN":""}), patch.object(cluster.sys.stdin, "isatty", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "no plan applied"):
                obj.plan()
        self.assertFalse(any(c.args[0] == "apply" for c in obj.tf.call_args_list))

    def test_down_without_account_confirmation_does_not_access_state(self):
        obj = cluster.Cluster.__new__(cluster.Cluster)
        obj.args = argparse.Namespace(confirm_destroy=None)
        obj.account = "123456789012"
        obj.init = Mock()
        with self.assertRaises(RuntimeError):
            obj.down()
        obj.init.assert_not_called()

    def test_stopped_nodes_are_started_without_replacement(self):
        obj = cluster.Cluster.__new__(cluster.Cluster)
        obj.instance = Mock(side_effect=[{"InstanceId":"server", "State":{"Name":"stopped"}},
                                        {"InstanceId":"agent", "State":{"Name":"running"}}])
        obj.aws = Mock()
        obj.start_nodes()
        self.assertEqual([c.args for c in obj.aws.call_args_list if c.args[1] == "start-instances"],
                         [("ec2", "start-instances", "--instance-ids", "server")])
        self.assertFalse(any(c.args[1] == "terminate-instances" for c in obj.aws.call_args_list))

    def test_bootstrap_adapter_never_initializes_eks_lab(self):
        obj = cluster.Cluster.__new__(cluster.Cluster)
        obj.args = argparse.Namespace()
        obj.config = {}
        obj.account, obj.region, obj.directory, obj.kube = "123456789012", "us-east-1", Path("."), Path("kubeconfig")
        with patch.object(cluster.legacy.Lab, "__init__", side_effect=AssertionError("Must not call EKS initialization")):
            helper = obj.lab()
        self.assertIsNone(helper.kubeconfig())
        self.assertEqual(helper.config["node_count"], 2)

    def test_resume_reuses_charts_without_contacting_repositories(self):
        obj = cluster.Cluster.__new__(cluster.Cluster)
        obj.config = {"infra_ref":"tested-commit"}
        helper = Mock()
        obj.lab = Mock(return_value=helper)
        obj.outputs = Mock(return_value={})
        obj.kubectl = Mock(return_value=json.dumps({"items":[
            {"metadata":{"name":name}, "spec":{"source":{"targetRevision":"tested-commit"}}} for name in cluster.legacy.APPS]}))
        releases = [json.dumps({"status":"deployed", "version":version})
                    for version in ("10.9.6", "2.0.3")]
        with patch.object(cluster.legacy, "validate_manifests"), patch.object(cluster, "command", side_effect=releases) as run:
            obj.bootstrap()
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(c.args[0][1:3] == ["get", "metadata"] for c in run.call_args_list))
        helper.apply_application.assert_not_called()

    def test_admin_access_must_be_single_ipv4(self):
        config = json.loads((Path(__file__).parents[1] / "cluster.example.json").read_text())
        config.update(infra_ref="main", admin_cidrs=["0.0.0.0/0"])
        with self.assertRaisesRegex(RuntimeError, "IPv4 /32"):
            cluster.validate_config(config)


if __name__ == "__main__":
    unittest.main()
