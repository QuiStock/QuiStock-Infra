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
        obj.args = Mock(confirm_destroy=None, migrate_argocd_public=False)
        obj.argocd_tls_context = Mock(return_value=Mock())
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

    def test_admin_principal_does_not_inspect_restricted_iam_role(self):
        obj = self.instance()
        obj.config["admin_role_name"] = "voclabs"
        obj.aws = Mock()
        self.assertEqual(obj.admin_principal(), "arn:aws:iam::123456789012:role/voclabs")
        obj.aws.assert_not_called()

    def test_explicit_admin_arn_preserves_nondefault_iam_path(self):
        obj = self.instance()
        obj.config["admin_role_arn"] = "arn:aws:iam::123456789012:role/lab/operator"
        self.assertEqual(obj.admin_principal(), obj.config["admin_role_arn"])

    def test_admin_principal_rejects_other_accounts_and_session_arns(self):
        obj = self.instance()
        for arn in ("arn:aws:iam::999999999999:role/voclabs", "arn:aws:sts::123456789012:assumed-role/voclabs/session"):
            with self.subTest(arn=arn), self.assertRaisesRegex(RuntimeError, "target account"):
                obj.config["admin_role_arn"] = arn
                obj.admin_principal()

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
        obj.verify_argocd = Mock()
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

    def test_update_only_reconciles_argocd_after_successful_apply(self):
        obj = self.instance()
        obj.plan = Mock(return_value=True)
        obj.outputs = Mock(return_value={"argocd_url": {"value": "https://fixture.elb.amazonaws.com"}})
        obj.argocd = Mock()
        obj.verify_argocd = Mock()
        obj.bootstrap = Mock()
        obj.update()
        obj.argocd.assert_called_once_with(obj.outputs.return_value)
        obj.verify_argocd.assert_called_once_with(obj.outputs.return_value)
        obj.bootstrap.assert_not_called()

    def test_update_plan_only_does_not_touch_cluster(self):
        obj = self.instance()
        obj.plan = Mock(return_value=False)
        obj.argocd = Mock()
        obj.update()
        obj.argocd.assert_not_called()

    def test_plan_rejects_replacement_before_apply(self):
        obj = self.instance()
        obj.args.apply = True
        obj.preflight = Mock()
        obj.init = Mock()
        obj.tf = Mock()
        details = {"resource_changes": [{"address": "aws_eks_cluster.this", "change": {"actions": ["delete", "create"]}}]}
        with patch.object(lab, "run", side_effect=[Mock(stdout="aws_eks_cluster.this\n"), Mock(stdout=json.dumps(details))]):
            with self.assertRaisesRegex(RuntimeError, "deletion/replacement"):
                obj.plan()
        obj.init.assert_called_once_with(create=False)
        self.assertFalse(any(c.args[0] == "apply" for c in obj.tf.call_args_list))

    def test_update_refuses_missing_remote_cluster_state(self):
        obj = self.instance()
        obj.args.apply = True
        obj.preflight = Mock()
        obj.init = Mock()
        obj.tf = Mock()
        with patch.object(lab, "run", return_value=Mock(stdout="")):
            with self.assertRaisesRegex(RuntimeError, "missing from remote state"):
                obj.plan()
        obj.tf.assert_not_called()

    def test_migration_permits_only_former_argocd_entry_cleanup(self):
        details = {"resource_changes": [
            {"address": "aws_lb_listener.argocd", "change": {"actions": ["delete", "create"]}},
            {"address": "aws_vpc_security_group_ingress_rule.argocd_from_cloudfront", "change": {"actions": ["delete"]}}]}
        with self.assertRaisesRegex(RuntimeError, "deletion/replacement"):
            lab.validate_plan(details)
        lab.validate_plan(details, migrate_argocd_public=True)

    def test_migration_still_refuses_cluster_api_and_target_group_deletion(self):
        for address in ("aws_eks_cluster.this", "aws_eks_node_group.arm", "aws_lb.edge",
                        "aws_apigatewayv2_api.edge", "aws_lb_target_group.argocd"):
            details = {"resource_changes": [{"address": address, "change": {"actions": ["delete", "create"]}}]}
            with self.subTest(address=address), self.assertRaisesRegex(RuntimeError, address):
                lab.validate_plan(details, migrate_argocd_public=True)

    def test_tls_trust_reads_only_public_certificate_and_preserves_verification(self):
        obj = self.instance()
        del obj.argocd_tls_context
        certificate = "-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----"
        results = [Mock(returncode=1, stdout=""), Mock(returncode=0, stdout=lab.base64.b64encode(certificate.encode()).decode())]
        with patch.object(lab, "run", side_effect=results) as command, patch.object(lab.ssl, "SSLContext") as factory:
            context = obj.argocd_tls_context()
        factory.assert_called_once_with(lab.ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations.assert_called_once_with(cadata=certificate)
        self.assertFalse(context.check_hostname)
        self.assertNotIn("verify_mode", context.__dict__)
        self.assertTrue(all(c.args[0][-1] == r"jsonpath={.data.tls\.crt}" for c in command.call_args_list))

    def test_argocd_verification_rejects_anonymous_applications_access(self):
        obj = self.instance()
        obj.aws = Mock(return_value={"TargetHealthDescriptions": [{"TargetHealth": {"State": "healthy"}}]})
        outputs = {"argocd_target_group_arn": {"value": "target"}, "argocd_url": {"value": "https://fixture.elb.amazonaws.com"}}
        context = Mock()
        context.__enter__ = Mock(return_value=Mock(status=200))
        context.__exit__ = Mock(return_value=False)
        with patch.object(lab.urllib.request, "urlopen", return_value=context):
            with self.assertRaisesRegex(RuntimeError, "without authentication"):
                obj.verify_argocd(outputs)

    def test_argocd_verification_requires_health_then_authentication(self):
        obj = self.instance()
        obj.aws = Mock(return_value={"TargetHealthDescriptions": [{"TargetHealth": {"State": "healthy"}}]})
        url = "https://fixture.elb.amazonaws.com"
        outputs = {"argocd_target_group_arn": {"value": "target"}, "argocd_url": {"value": url}}
        context = Mock()
        context.__enter__ = Mock(return_value=Mock(status=200))
        context.__exit__ = Mock(return_value=False)
        denied = lab.urllib.error.HTTPError(url + "/api/v1/applications", 401, "Unauthorized", {}, None)
        with patch.object(lab.urllib.request, "urlopen", side_effect=[context, denied]) as request:
            obj.verify_argocd(outputs)
        denied.close()
        self.assertEqual(request.call_args_list[0].args[0], url + "/healthz")
        self.assertEqual(request.call_args_list[1].args[0], url + "/api/v1/applications")
        self.assertTrue(all(c.kwargs["context"] is obj.argocd_tls_context.return_value for c in request.call_args_list))

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
