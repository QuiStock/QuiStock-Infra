import base64
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("image_update_automerge", Path(__file__).parents[1] / "image_update_automerge.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

REPO = "QuiStock/QuiStock-Infra"
BRANCH = "codex/deploy-api-chatbot-v1.2.3"
DEPLOYMENT = "clusters/us-east1/apps/api-chatbot/deployment.yaml"


class AutoMergeTests(unittest.TestCase):
    def fixture(self, stack, branch=BRANCH, files=None, after=None):
        pr = {"number":55, "user":{"id":123}, "state":"open", "draft":False,
              "base":{"ref":"main", "sha":"base"},
              "head":{"ref":branch, "sha":"head", "repo":{"full_name":REPO}}, "changed_files":1}
        files = files if files is not None else [{"filename":DEPLOYMENT, "status":"modified"}]
        pr["changed_files"] = len(files)
        before = "  image: ghcr.io/quistock/api-chatbot:v1.2.2\n"
        after = after or "  image: ghcr.io/quistock/api-chatbot:v1.2.3\n"

        def api(endpoint, *args):
            if endpoint == f"repos/{REPO}/pulls/55":
                return pr
            if endpoint == "user":
                return {"id":123}
            if "/compare/" in endpoint:
                return {"merge_base_commit":{"sha":"merge-base"}}
            if "/files?" in endpoint:
                return [files]
            if "/contents/" in endpoint:
                text = before if endpoint.endswith("ref=merge-base") else after
                return {"type":"file", "encoding":"base64", "content":base64.b64encode(text.encode()).decode()}
            raise AssertionError(f"Unexpected API request: {endpoint}")

        stack.enter_context(patch.dict(module.os.environ, {
            "GITHUB_EVENT_PATH":"event.json", "GITHUB_REPOSITORY":REPO, "GH_TOKEN":"test-token"}))
        stack.enter_context(patch.object(module.Path, "read_text", return_value=json.dumps({"pull_request":pr})))
        api_mock = stack.enter_context(patch.object(module, "api", side_effect=api))
        merge = stack.enter_context(patch.object(module.subprocess, "run"))
        return pr, api_mock, merge

    def test_existing_publisher_branch_conventions(self):
        for service in ("api-auth", "api-core", "api-chatbot", "website", "observe"):
            for separator in ("/", "-"):
                self.assertIsNotNone(module.AUTOMATION_BRANCH.fullmatch(f"codex/deploy{separator}{service}-v1.2.3"))
        for branch in ("codex/disposable-k3s-lab-lifecycle", "codex/deploy-unknown-v1", "codex/deploy-website-", "codex/deploy-website-v1/extra"):
            self.assertIsNone(module.AUTOMATION_BRANCH.fullmatch(branch))

    def test_ordinary_pr_skips_without_token_or_api_calls(self):
        with ExitStack() as stack:
            _, api, merge = self.fixture(stack, branch="codex/disposable-k3s-lab-lifecycle")
            stack.enter_context(patch.dict(module.os.environ, {"GH_TOKEN":""}))
            module.main()
            api.assert_not_called()
            merge.assert_not_called()

    def test_image_update_preserves_match_head_merge_guard(self):
        with ExitStack() as stack:
            _, _, merge = self.fixture(stack)
            module.main()
            merge.assert_called_once_with([
                "gh", "pr", "merge", "55", "--repo", REPO, "--auto", "--squash", "--match-head-commit", "head"], check=True)

    def test_automation_pr_cannot_modify_pipeline(self):
        with ExitStack() as stack:
            _, _, merge = self.fixture(stack, files=[{"filename":".github/workflows/eks-validate.yml", "status":"modified"}])
            with self.assertRaisesRegex(ValueError, "not an allowed deployment"):
                module.main()
            merge.assert_not_called()

    def test_automation_pr_cannot_change_image_repository(self):
        with ExitStack() as stack:
            _, _, merge = self.fixture(stack, after="  image: ghcr.io/quistock/other:v1.2.3\n")
            with self.assertRaisesRegex(ValueError, "repository changed"):
                module.main()
            merge.assert_not_called()

    def test_automation_pr_cannot_change_non_image_fields(self):
        with ExitStack() as stack:
            _, _, merge = self.fixture(stack, after="  replicas: 3\n")
            with self.assertRaisesRegex(ValueError, "outside an image field"):
                module.main()
            merge.assert_not_called()

    def test_other_author_is_skipped(self):
        with ExitStack() as stack:
            pr, _, merge = self.fixture(stack)
            pr["user"]["id"] = 456
            module.main()
            merge.assert_not_called()

    def test_fork_is_skipped(self):
        with ExitStack() as stack:
            pr, _, merge = self.fixture(stack)
            pr["head"]["repo"]["full_name"] = "fork/QuiStock-Infra"
            module.main()
            merge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
