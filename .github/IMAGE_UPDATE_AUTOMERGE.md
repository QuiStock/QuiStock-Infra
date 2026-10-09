# Automatic image update merges

Service repositories open PRs in this repository using the organization secret
`INFRA_REPO_TOKEN`. The image-update workflow accepts PRs authored by the owner
of that PAT, from a branch in this repository to `main`, and only changes to
image tags or SHA-256 digests in the four service `deployment.yaml` files.
Image repository names, all other fields, comments and formatting must remain
unchanged. Forks and drafts are excluded. Other authors are skipped.

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
on their next push or when reopened. If a service starts editing a different
manifest, update `ALLOWED_FILES` in the script deliberately.
