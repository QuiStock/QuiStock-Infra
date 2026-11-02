import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("recover_k3s", Path(__file__).parents[1] / "recover_k3s.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def test_linux_stdin_preserves_lf_on_windows(self):
        output = recovery.command([sys.executable, "-c",
            "import sys; print(repr(sys.stdin.buffer.read()))"], stdin="set -eu\necho ready\n", quiet=True)
        self.assertEqual(output.strip(), "b'set -eu\\necho ready\\n'")

    def test_secret_command_failure_does_not_print_credentials(self):
        with self.assertRaises(RuntimeError) as error:
            recovery.command([sys.executable, "-c",
                "import sys; print(sys.stdin.read()); sys.exit(1)"], stdin="secret-canary", quiet=True)
        self.assertNotIn("secret-canary", str(error.exception))

    def test_clean_resource_removes_old_cluster_identity_and_cached_secret(self):
        secret = {"apiVersion": "v1", "kind": "Secret", "data": {"token": "encoded"},
            "metadata": {"name": "bw-auth-token", "namespace": "api-auth", "uid": "old",
                "resourceVersion": "12", "ownerReferences": [{"uid": "old-owner"}],
                "annotations": {"kubectl.kubernetes.io/last-applied-configuration": "secret-copy",
                                "meta.helm.sh/release-name": "argocd"}}, "status": {}}
        cleaned = recovery.clean_resource(secret)
        self.assertEqual(cleaned["data"], {"token": "encoded"})
        self.assertEqual(cleaned["metadata"], {"name": "bw-auth-token", "namespace": "api-auth",
            "annotations": {"meta.helm.sh/release-name": "argocd"}})
        self.assertNotIn("status", cleaned)

    def test_unhealthy_new_targets_never_detach_old_asg(self):
        obj = recovery.Recovery.__new__(recovery.Recovery)
        obj.state = {"migrated": True, "server": "new-server", "agent": "new-agent",
                     "outputs": {"edge_target_group_arn": {"value": "edge"}}}
        obj.aws = Mock(side_effect=lambda *args: {"TargetHealthDescriptions": [
            {"TargetHealth": {"State": "unhealthy"}}]} if args[1] == "describe-target-health" else {})
        with patch.object(recovery.time, "sleep"), self.assertRaises(RuntimeError):
            obj.publish()
        self.assertFalse(any(call.args[0] == "autoscaling" for call in obj.aws.call_args_list))


if __name__ == "__main__":
    unittest.main()
