# Automatic image update merges

Service repositories open PRs in this repository using the organization secret
`INFRA_REPO_TOKEN`. The image-update workflow accepts PRs authored by the owner
of that PAT, from an automation branch in this repository to `main`, and only
changes to image tags or SHA-256 digests in the five application `deployment.yaml` files.
Image repository names, all other fields, comments and formatting must remain
unchanged. Forks and drafts are excluded. Other authors are skipped.

Automation branches follow the existing service publisher conventions:
`codex/deploy/<service>-<tag>` or `codex/deploy-<service>-<tag>`, where service is
`api-auth`, `api-core`, `api-chatbot`, `website` or `observe`. The workflow
filters the branch prefix and the trusted script checks the complete pattern,
then verifies the current PR and PAT owner through the API. Ordinary feature,
infrastructure and documentation PRs are skipped without enabling auto-merge.
An eligible automation PR with forbidden files or non-image edits still fails.

The workflow uses trusted base-branch code and reads PR files through the API;
it never executes PR code. It enables squash auto-merge for the validated head
commit and respects required checks and branch protection. It does not submit
an approval or bypass branch rules. Validation checks the change's scope, not
whether the published image is healthy or deployable.

Before use, in GitHub Settings > General > Pull Requests, enable:

- Allow squash merging.
- Allow auto-merge.
- Automatically delete head branches (also applies to other merged PRs).

Ensure `INFRA_REPO_TOKEN` is available to this repository and has permissions
to read repository contents and read/write pull requests and contents. For a
fine-grained PAT, grant Contents and Pull requests read/write on this repository.
The rules for `main` must permit merging without approval as intended. Configure
any required deployment checks in the branch rules so auto-merge waits for them.

The workflow must first be merged into `main`. Existing open PRs can trigger it
on their next push or when reopened. Re-running an old event can still use the
old base revision; trigger a new event after the fix reaches `main`.
If a service starts editing a different manifest or using a different branch
convention, update the script's explicit allowlists deliberately.
