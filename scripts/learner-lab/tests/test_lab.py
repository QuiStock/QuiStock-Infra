import importlib.util
import json
import tempfile
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
        obj.args = Mock(confirm_destroy=None, migrate_argocd_public=False, migrate_website=False, migrate_node_role=False)
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
        obj.migrate_website = Mock()
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
        with patch.object(lab, "validate_manifests"), patch.object(lab, "run") as command, patch.object(lab.time, "sleep"):
            obj.public()
        self.assertEqual(obj.aws.call_count, 2)
        obj.wait_application.assert_called_once_with("website")
        obj.verify_public.assert_called_once_with("https://fixture.execute-api.us-east-1.amazonaws.com")
        self.assertTrue(any("website-application.yaml" in str(c.args[0]) for c in command.call_args_list))

    def test_public_refuses_to_report_ready_without_nlb_targets(self):
        obj = self.publication()
        obj.aws = Mock(return_value={"TargetHealthDescriptions": []})
        with patch.object(lab, "validate_manifests"), patch.object(lab, "run"), patch.object(lab.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "did not become healthy"):
                obj.public()
        obj.verify_public.assert_not_called()

    def test_draft_placeholders_stop_before_cloud_preflight(self):
        obj = self.instance()
        obj.aws = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "clusters/us-east1/apps/website/deployment.yaml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("image: REPLACE_WITH_WEBSITE_ARM64_IMAGE_DIGEST", encoding="utf-8")
            with patch.object(lab, "ROOT", root), self.assertRaisesRegex(RuntimeError, "placeholders"):
                obj.preflight()
        obj.aws.assert_not_called()

    def test_chatbot_secret_wait_requires_its_mapped_credentials(self):
        obj = self.instance()
        manifest = (lab.ROOT / "clusters/us-east1/apps/api-chatbot/bitwarden-secret.yaml").read_text(encoding="utf-8")
        keys = {line.split(":", 1)[1].strip() for line in manifest.splitlines()
                if line.strip().startswith("secretKeyName:")}
        self.assertTrue(keys, "The chatbot must declare mapped Bitwarden keys")
        for missing in sorted(keys):
            with self.subTest(missing=missing), \
                 patch.object(lab, "run", side_effect=[Mock(returncode=0, stdout="\n".join(keys - {missing})),
                                                      Mock(returncode=0, stdout="\n".join(keys))]) as command, \
                 patch.object(lab.time, "sleep") as sleep:
                obj.wait_secret("api-chatbot")
                self.assertEqual(command.call_count, 2)
                sleep.assert_called_once_with(5)
                self.assertIn("chatbot-external", command.call_args.args[0])

    def test_website_migration_requires_explicit_flag_before_mutation(self):
        obj = self.instance()
        with patch.object(lab, "run", side_effect=[Mock(stdout="service/edge"), Mock(stdout="application/edge"),
                                                 Mock(stdout="deployment/edge")]) as command:
            with self.assertRaisesRegex(RuntimeError, "migrate-website"):
                obj.migrate_website()
        self.assertTrue(all(c.args[0][1] == "get" for c in command.call_args_list))

    def test_website_migration_releases_nodeport_without_deleting_namespace(self):
        obj = self.instance()
        obj.args.migrate_website = True
        with patch.object(lab, "run", side_effect=[Mock(stdout="service/edge"), Mock(stdout="application/edge"),
                                                 Mock(stdout="deployment/edge"), Mock(), Mock(), Mock(), Mock()]) as command:
            obj.migrate_website()
        mutations = [c.args[0] for c in command.call_args_list[3:]]
        self.assertEqual(mutations[0][1:4], ["patch", "application", "edge"])
        self.assertIn('{"metadata":{"finalizers":[]}}', mutations[0])
        self.assertEqual([args[2] for args in mutations[1:]], ["application", "service", "deployment"])
        self.assertFalse(any("namespace" in args or "secret" in args for args in mutations))

    def test_website_migration_resumes_when_only_old_deployment_remains(self):
        obj = self.instance()
        obj.args.migrate_website = True
        with patch.object(lab, "run", side_effect=[Mock(stdout=""), Mock(stdout=""), Mock(stdout="deployment/edge"),
                                                 Mock(), Mock()]) as command:
            obj.migrate_website()
        self.assertEqual(command.call_args.args[0][1:4], ["delete", "deployment", "edge"])

    def test_website_migration_is_noop_on_new_cluster(self):
        obj = self.instance()
        with patch.object(lab, "run", return_value=Mock(stdout="")) as command:
            obj.migrate_website()
        self.assertEqual(command.call_count, 3)
        self.assertTrue(all(c.args[0][1] == "get" for c in command.call_args_list))

    def test_public_preserves_legacy_entry_when_remote_outputs_are_unavailable(self):
        obj = self.publication()
        obj.outputs.side_effect = RuntimeError("State bucket unavailable")
        with patch.object(lab, "validate_manifests"), self.assertRaisesRegex(RuntimeError, "State bucket"):
            obj.public()
        obj.migrate_website.assert_not_called()

    def test_bootstrap_installs_tokens_and_applications_for_all_internal_services(self):
        obj = self.instance()
        obj.kubeconfig = Mock()
        obj.argocd = Mock()
        obj.outputs = Mock(return_value={})
        obj.wait_secret = Mock()
        obj.wait_application = Mock()
        obj.verify = Mock()
        obj.public = Mock()
        with patch.object(lab, "validate_manifests"), patch.object(lab.getpass, "getpass", return_value="fixture"), \
             patch.object(lab, "run") as command:
            obj.bootstrap()
        secrets = [json.loads(c.kwargs["stdin"]) for c in command.call_args_list if "stdin" in c.kwargs]
        self.assertEqual([s["metadata"]["namespace"] for s in secrets], list(lab.SECRET_APPS))
        self.assertEqual([c.args[0] for c in obj.wait_secret.call_args_list], list(lab.SECRET_APPS))
        self.assertEqual([c.args[0] for c in obj.wait_application.call_args_list], list(lab.SECRET_APPS))
        obj.public.assert_called_once_with()

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

    def node_migration_plan(self):
        before = {"node_role_arn": "arn:aws:iam::123456789012:role/LabRole",
                  "cluster_name": "quistock", "node_group_name": "quistock-arm",
                  "ami_type": "AL2023_ARM_64_STANDARD", "capacity_type": "ON_DEMAND",
                  "instance_types": ["t4g.medium"], "subnet_ids": ["subnet-a", "subnet-b"],
                  "scaling_config": [{"desired_size": 2, "min_size": 2, "max_size": 2}], "disk_size": 20}
        after = dict(before, node_role_arn="arn:aws:iam::123456789012:role/LabEksNodeRole")
        changes = [{"address": "aws_eks_node_group.arm", "change": {
            "actions": ["delete", "create"], "before": before, "after": after,
            "replace_paths": [["node_role_arn"]]}}]
        for name in ("edge", "argocd"):
            changes.append({"address": f"aws_autoscaling_attachment.{name}", "change": {
                "actions": ["delete", "create"], "replace_paths": [["autoscaling_group_name"]],
                "before": {"autoscaling_group_name": "old", "lb_target_group_arn": name},
                "after": {"autoscaling_group_name": None, "lb_target_group_arn": name}}})
        return {"resource_changes": changes}

    def test_node_role_replacement_requires_explicit_migration_flag(self):
        details = self.node_migration_plan()
        with self.assertRaisesRegex(RuntimeError, "deletion/replacement"):
            lab.validate_plan(details)
        lab.validate_plan(details, migrate_node_role=True)

    def test_plan_passes_node_migration_flag_before_applying_saved_plan(self):
        obj = self.instance()
        obj.args.apply = True
        obj.args.migrate_node_role = True
        obj.preflight = Mock()
        obj.init = Mock()
        obj.tf = Mock()
        details = self.node_migration_plan()
        with patch.object(lab, "run", side_effect=[Mock(stdout="aws_eks_cluster.this\n"),
                                                 Mock(stdout=json.dumps(details))]):
            self.assertTrue(obj.plan())
        self.assertEqual(obj.tf.call_args.args[0], "apply")

    def test_node_migration_refuses_capacity_network_and_image_changes(self):
        for key, value in (("ami_type", "AL2023_X86_64_STANDARD"), ("cluster_name", "other"),
                           ("node_group_name", "other"), ("subnet_ids", ["subnet-c"]),
                           ("instance_types", ["t4g.large"]), ("scaling_config", []), ("disk_size", 40)):
            details = self.node_migration_plan()
            details["resource_changes"][0]["change"]["after"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "only a role replacement"):
                lab.validate_plan(details, migrate_node_role=True)

    def test_node_migration_refuses_additional_replacement_causes_or_pure_deletion(self):
        for actions, paths in ((["delete"], [["node_role_arn"]]),
                               (["delete", "create"], [["node_role_arn"], ["version"]])):
            details = self.node_migration_plan()
            details["resource_changes"][0]["change"].update(actions=actions, replace_paths=paths)
            with self.assertRaisesRegex(RuntimeError, "only a role replacement"):
                lab.validate_plan(details, migrate_node_role=True)

    def test_node_migration_preserves_target_groups_and_unrelated_resources(self):
        details = self.node_migration_plan()
        details["resource_changes"][1]["change"]["after"]["lb_target_group_arn"] = "different"
        with self.assertRaisesRegex(RuntimeError, "preserve both NLB"):
            lab.validate_plan(details, migrate_node_role=True)
        for address in ("aws_eks_cluster.this", "aws_lb.edge", "aws_lb.argocd",
                        "aws_lb_target_group.edge", "aws_apigatewayv2_api.edge", "aws_eks_access_entry.admin"):
            details = self.node_migration_plan()
            details["resource_changes"].append({"address": address, "change": {"actions": ["delete", "create"]}})
            with self.subTest(address=address), self.assertRaisesRegex(RuntimeError, address):
                lab.validate_plan(details, migrate_node_role=True, migrate_argocd_public=True)

    def test_node_migration_can_resume_attachment_replacement_after_interruption(self):
        details = self.node_migration_plan()
        details["resource_changes"][0]["change"].update(actions=["create"], before=None, replace_paths=[])
        lab.validate_plan(details, migrate_node_role=True)
        details["resource_changes"].pop(0)
        with self.assertRaisesRegex(RuntimeError, "deletion/replacement"):
            lab.validate_plan(details, migrate_node_role=True)

    def test_wait_nodes_requires_registered_schedulable_ready_arm64_capacity(self):
        obj = self.instance()
        obj.config["node_count"] = 2
        ready = {"metadata": {"labels": {"kubernetes.io/arch": "arm64"}},
                 "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
        cordoned = dict(ready, spec={"unschedulable": True})
        amd64 = dict(ready, metadata={"labels": {"kubernetes.io/arch": "amd64"}})
        responses = [[], [amd64, cordoned], [ready], [ready, ready]]
        with patch.object(lab, "run", side_effect=[Mock(stdout=json.dumps({"items": n})) for n in responses]) as command, \
             patch.object(lab.time, "sleep") as sleep:
            obj.wait_nodes()
        self.assertEqual(command.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_argocd_does_not_start_helm_when_nodes_never_register(self):
        obj = self.instance()
        obj.config["node_count"] = 2
        obj.kubeconfig = Mock()
        with patch.object(lab, "run", return_value=Mock(stdout='{"items": []}')) as command, \
             patch.object(lab.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "ARM64 nodes did not become Ready"):
                obj.argocd({})
        self.assertTrue(all(c.args[0][0] == "kubectl" for c in command.call_args_list))

    def test_argocd_refuses_pending_helm_without_automatic_rollback(self):
        obj = self.instance()
        obj.kubeconfig = Mock()
        obj.wait_nodes = Mock()
        with patch.object(lab, "run", return_value=Mock(returncode=0, stdout='{"info":{"status":"pending-upgrade"}}')) as command:
            with self.assertRaisesRegex(RuntimeError, "pending Helm operation"):
                obj.argocd({})
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0][0:2], ["helm", "status"])

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
