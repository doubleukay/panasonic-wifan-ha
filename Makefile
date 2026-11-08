.PHONY: bump release preflight

# Bump the patch version, push the commit + tag, then publish the GitHub release.
bump: preflight
	bump-my-version bump patch
	git push --atomic --follow-tags
	$(MAKE) release

# Verify the repo is in a safe state to bump (fails with a message otherwise).
preflight:
	@set -e; \
	command -v bump-my-version >/dev/null || { echo "preflight: bump-my-version not found" >&2; exit 1; }; \
	command -v gh >/dev/null || { echo "preflight: gh not found" >&2; exit 1; }; \
	gh auth status >/dev/null 2>&1 || { echo "preflight: gh not authenticated (run gh auth login)" >&2; exit 1; }; \
	branch=$$(git branch --show-current); \
	[ "$$branch" = "main" ] || { echo "preflight: not on main (on '$${branch:-detached HEAD}')" >&2; exit 1; }; \
	git fetch -q origin; \
	[ "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" ] || { echo "preflight: HEAD != origin/main (unpushed or behind commits)" >&2; exit 1; }; \
	next=v$$(bump-my-version show new_version --increment patch); \
	if git rev-parse -q --verify "refs/tags/$$next" >/dev/null; then \
		echo "preflight: tag $$next already exists locally (git tag -d $$next)" >&2; exit 1; \
	fi; \
	if git ls-remote --exit-code --tags origin "refs/tags/$$next" >/dev/null 2>&1; then \
		echo "preflight: tag $$next already exists on origin" >&2; exit 1; \
	fi; \
	echo "preflight ok (next tag $$next)"

# Publish a GitHub release for the current version's tag (re-runnable if gh failed).
# Notes default to commit subjects since the previous tag (bump commits excluded);
# override with: make release NOTES_FILE=notes.md
release:
	@set -e; \
	tag=v$$(bump-my-version show current_version); \
	prev=$$(git describe --tags --abbrev=0 "$$tag^"); \
	if [ -n "$(NOTES_FILE)" ]; then \
		notes=$$(cat "$(NOTES_FILE)"); \
	else \
		notes=$$(git log --no-merges --format='- %s' "$$prev..$$tag" | grep -v '^- Bump version' || true); \
	fi; \
	echo "Creating release $$tag (changes since $$prev)"; \
	gh release create "$$tag" --verify-tag --notes "$$notes"
