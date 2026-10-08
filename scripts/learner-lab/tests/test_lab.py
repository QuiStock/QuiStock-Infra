import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location("lab", Path(__file__).parents[1] / "lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class SafetyTests(unittest.TestCase):
    def instance(self):
        obj = lab.Lab.__new__(lab.Lab)
        obj.account = "123456789012"
        obj.args = Mock(confirm_destroy=None)
        obj.config = {"cluster_name": "quistock"}
        obj.region = "us-east-1"
        obj.dir = Path("isolated")
        return obj

    def test_wrong_account_stops_before_files_or_resources(self):
        config = {"region": "us-east-1"}
        with patch.object(lab.Path, "read_text", return_value=json.dumps(config)), \
             patch.object(lab.shutil, "which", return_value="tool"), \
             patch.object(lab.Lab, "aws", return_value={"Account": "111111111111"}), \
             patch.object(lab.Path, "mkdir") as mkdir:
            with self.assertRaisesRegex(RuntimeError, "Wrong AWS account"):
                lab.Lab(Mock(config="config.json", account="222222222222"))
            mkdir.assert_not_called()

    def test_destroy_requires_account_confirmation(self):
        obj = self.instance()
        obj.init = Mock()
        with self.assertRaisesRegex(RuntimeError, "confirm-destroy"):
            obj.down()
        obj.init.assert_not_called()

    def test_destroy_refuses_load_balancer(self):
        obj = self.instance()
        obj.args.confirm_destroy = obj.account
        obj.init = Mock()
        obj.kubeconfig = Mock()
        obj.tf = Mock()
        with patch.object(lab.Path, "exists", return_value=True), \
             patch.object(lab, "run", return_value=Mock(stdout=json.dumps({"items": [{"spec": {"type": "LoadBalancer"}}]}))):
            with self.assertRaisesRegex(RuntimeError, "LoadBalancer"):
                obj.down()
        obj.tf.assert_not_called()

    def test_secret_wait_checks_all_required_keys(self):
        obj = self.instance()
        incomplete = Mock(returncode=0, stdout="DB_URL\n")
        complete = Mock(returncode=0, stdout="DB_URL\nDB_USERNAME\nDB_PASSWORD\nAUTH_JWT_ISSUER\n")
        with patch.object(lab, "run", side_effect=[incomplete, complete]) as command, patch.object(lab.time, "sleep"):
            obj.wait_secret("api-core")
        self.assertEqual(command.call_count, 2)
        self.assertIn("go-template", command.call_args.args[0][-1])

    def test_application_requires_both_sync_and_health(self):
        obj = self.instance()
        states = [{"sync": {"status": "Synced"}, "health": {"status": "Progressing"}},
                  {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}]
        with patch.object(lab, "run", side_effect=[Mock(stdout=json.dumps({"status": s})) for s in states]) as command, \
             patch.object(lab.time, "sleep"):
            obj.wait_application("api-auth")
        self.assertEqual(command.call_count, 2)

    def publication(self):
        obj = self.instance()
        obj.kubeconfig = Mock()
        obj.wait_application = Mock()
        obj.verify_public = Mock()
        obj.outputs = Mock(return_value={
            "edge_target_group_arn": {"value": "target-arn"},
            "api_url": {"value": "https://fixture.execute-api.us-east-1.amazonaws.com"},
            "core_url": {"value": "https://fixture.execute-api.us-east-1.amazonaws.com/api"},
            "auth_url": {"value": "https://fixture.execute-api.us-east-1.amazonaws.com/auth"}})
        return obj

    def test_public_waits_for_healthy_nlb_before_https_verification(self):
        obj = self.publication()
        obj.aws = Mock(side_effect=[{"TargetHealthDescriptions": []},
                                   {"TargetHealthDescriptions": [{"TargetHealth": {"State": "healthy"}}]}])
        with patch.object(lab, "run") as command, patch.object(lab.time, "sleep"):
            obj.public()
        self.assertEqual(obj.aws.call_count, 2)
        obj.wait_application.assert_called_once_with("edge")
        obj.verify_public.assert_called_once_with("https://fixture.execute-api.us-east-1.amazonaws.com")
        self.assertTrue(any("edge-application.yaml" in str(c.args[0]) for c in command.call_args_list))

    def test_public_refuses_to_report_ready_without_nlb_targets(self):
        obj = self.publication()
        obj.aws = Mock(return_value={"TargetHealthDescriptions": []})
        with patch.object(lab, "run"), patch.object(lab.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "did not become healthy"):
                obj.public()
        obj.verify_public.assert_not_called()

    def test_credentialed_cors_cannot_return_literal_wildcard(self):
        obj = self.instance()
        response = Mock(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true"})
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch.object(lab.urllib.request, "urlopen", return_value=context):
            with self.assertRaisesRegex(RuntimeError, "CORS preflight failed"):
                obj.verify_public("https://fixture.example")

    def test_gitops_paths_and_arm_images_are_preserved(self):
        for app in ("api-auth", "api-core"):
            application = (lab.ROOT / f"clusters/us-east1/bootstrap/{app}-application.yaml").read_text()
            deployment = (lab.ROOT / f"clusters/us-east1/apps/{app}/deployment.yaml").read_text()
            self.assertIn(f"path: clusters/us-east1/apps/{app}", application)
            self.assertIn("kubernetes.io/arch: arm64", deployment)
            self.assertNotIn("cloud.google.com", deployment)
            self.assertRegex(deployment, r"image: ghcr.io/[^\s]+@sha256:[a-f0-9]{64}")


if __name__ == "__main__":
    unittest.main()
