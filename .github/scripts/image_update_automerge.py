"""Enable auto-merge only for same-repository, PAT-authored image updates."""

import base64
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote


ALLOWED_FILES = {
    f"clusters/us-east1/apps/{service}/deployment.yaml"
    for service in ("api-auth", "api-core", "api-chatbot", "website")
}
IMAGE_LINE = re.compile(
    r"(?P<prefix>[ \t]+image:[ \t]+)(?P<image>[^\s'\"#]+)(?P<suffix>[ \t]*(?:#.*)?)"
)
IMAGE_VERSION = re.compile(
    r"(?P<repository>ghcr\.io/quistock/[a-z0-9._/-]+)"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[a-f0-9]{64})"
)


def api(endpoint, *args):
    return json.loads(subprocess.check_output(
        ["gh", "api", endpoint, *args], text=True
    ))


def validate_images(before, after):
    """Require identical lines except image versions, preserving image names."""
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    if len(old_lines) != len(new_lines):
        raise ValueError("Lines were added or removed")
    changed = 0
    for old, new in zip(old_lines, new_lines):
        if old == new:
            continue
        old_match = IMAGE_LINE.fullmatch(old.rstrip("\r\n"))
        new_match = IMAGE_LINE.fullmatch(new.rstrip("\r\n"))
        if not old_match or not new_match:
            raise ValueError("A change outside an image field was found")
        old_version = IMAGE_VERSION.fullmatch(old_match["image"])
        new_version = IMAGE_VERSION.fullmatch(new_match["image"])
        if not old_version or not new_version:
            raise ValueError("Expected a versioned QuiStock GHCR image")
        if old_version["repository"] != new_version["repository"]:
            raise ValueError("The image repository changed")
        if old.replace(old_match["image"], "IMAGE", 1) != new.replace(new_match["image"], "IMAGE", 1):
            raise ValueError("Formatting or comments changed")
        changed += 1
    if not changed:
        raise ValueError("No image version changed")


def main():
    if not os.environ.get("GH_TOKEN"):
        raise ValueError("The INFRA_REPO_TOKEN organization secret is required")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    number = event["pull_request"]["number"]
    repo = os.environ["GITHUB_REPOSITORY"]
    pr = api(f"repos/{repo}/pulls/{number}")
    # The same PAT opens the PR in the service workflow. No hardcoded username.
    if pr["user"]["id"] != api("user")["id"]:
        print("Skipping PR: author is not the owner of INFRA_REPO_TOKEN")
        return
    if (pr["state"] != "open" or pr["draft"] or pr["base"]["ref"] != "main"
            or not pr["head"]["repo"] or pr["head"]["repo"]["full_name"] != repo):
        print("Skipping PR: not an eligible same-repository PR to main")
        return
    head = pr["head"]["sha"]
    comparison = api(f"repos/{repo}/compare/{pr['base']['sha']}...{head}")
    base = comparison["merge_base_commit"]["sha"]
    pages = api(f"repos/{repo}/pulls/{number}/files?per_page=100", "--paginate", "--slurp")
    files = [file for page in pages for file in page]
    if not files or len(files) != pr["changed_files"]:
        raise ValueError("The complete PR file list could not be verified")
    for file in files:
        path = file["filename"]
        if path not in ALLOWED_FILES or file["status"] != "modified":
            raise ValueError(f"File is not an allowed deployment modification: {path}")
        contents = []
        for ref in (base, head):
            data = api(f"repos/{repo}/contents/{quote(path, safe='/')}?ref={ref}")
            if data["type"] != "file" or data["encoding"] != "base64":
                raise ValueError(f"Unsupported file content: {path}")
            contents.append(base64.b64decode(data["content"]).decode("utf-8"))
        validate_images(*contents)
        print(f"Validated image version changes: {path}")
    # Refuse to merge if the head changed since validation; respect branch rules.
    subprocess.run([
        "gh", "pr", "merge", str(number), "--repo", repo,
        "--auto", "--squash", "--match-head-commit", head,
    ], check=True)


if __name__ == "__main__":
    main()
