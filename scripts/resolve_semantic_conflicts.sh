#!/usr/bin/env bash
# Resolve pull requests that conflict with their base only in .semantic/.
#
# A hosted merge button runs no custom merge driver, so a pull request whose
# generated artifacts conflict with its base cannot be merged there even when
# its source merges cleanly. For each pull request GitHub reports as
# conflicting, this merges the base in with the AIGit merge driver and pushes
# the result. A pull request whose source conflicts, or whose merged artifacts
# would be stale, is left for its author.
#
# Usage: resolve_semantic_conflicts.sh [PR_NUMBER...]   (default: all open PRs)
# Needs: gh (authenticated), a checkout with push access, AIGit installed.
# AIGIT_DISPATCH_CI=<workflow file>: for the default Actions token, whose
# pushes leave the pull request's workflow runs awaiting approval. Those runs
# are approved, so their checks report on the pull request; if that is not
# permitted, the named workflow is dispatched on the branch instead.

set -euo pipefail

python_bin="${PYTHON:-python3}"
attempts="${AIGIT_MERGEABLE_ATTEMPTS:-10}"

git config merge.aigit-semantic.name 'AIGit semantic artifact merge'
git config merge.aigit-semantic.driver "$python_bin -m aigit.cli merge-driver %O %A %B %P"
# Route the artifacts even on branches cut before .gitattributes routed them.
info_attributes="$(git rev-parse --git-path info/attributes)"
mkdir -p "$(dirname "$info_attributes")"
for artifact in manifest.jsonl chunk_index.json edges.jsonl provenance.jsonl; do
	line=".semantic/$artifact merge=aigit-semantic"
	grep -qxF "$line" "$info_attributes" 2>/dev/null || printf '%s\n' "$line" >>"$info_attributes"
done

mergeable_state() {
	# GitHub computes mergeability lazily; UNKNOWN means "not yet".
	local state=UNKNOWN
	for ((i = 0; i < attempts; i++)); do
		state="$(gh pr view "$1" --json mergeable -q .mergeable)"
		[ "$state" != UNKNOWN ] && break
		sleep 6
	done
	printf '%s\n' "$state"
}

resolve() {
	local pr="$1" head base cross
	IFS=$'\t' read -r head base cross < <(
		gh pr view "$pr" --json headRefName,baseRefName,isCrossRepository \
			-q '[.headRefName, .baseRefName, .isCrossRepository] | @tsv'
	)
	if [ "$cross" = true ]; then
		echo "#$pr: from a fork, which this token cannot push to; skipped"
		return
	fi
	if [ "$(mergeable_state "$pr")" != CONFLICTING ]; then
		echo "#$pr: no conflict with $base"
		return
	fi
	git fetch -q origin "$base" "$head"
	git checkout -q -B "aigit/resolve-$pr" "origin/$head"
	if ! git merge -q --no-edit "origin/$base"; then
		git merge --abort
		echo "#$pr: the source conflicts with $base; left for the author"
		return
	fi
	if ! "$python_bin" -m aigit.cli chunk --repo . --check; then
		echo "#$pr: the merged artifacts would be stale; left for the author"
		return
	fi
	git push -q origin "HEAD:refs/heads/$head"
	echo "#$pr: merged $base with the semantic merge driver and pushed"
	if [ -n "${AIGIT_DISPATCH_CI:-}" ]; then
		start_checks "$pr" "$head" "$(git rev-parse HEAD)"
	fi
}

start_checks() {
	# Runs started by the default token's push wait for approval and report
	# nothing on the pull request until approved.
	local pr="$1" head="$2" sha="$3" ids="" approved=0
	for ((i = 0; i < attempts * 2; i++)); do
		ids="$(gh run list --commit "$sha" --json databaseId,conclusion \
			-q '.[] | select(.conclusion == "action_required") | .databaseId')"
		[ -n "$ids" ] && break
		sleep 5
	done
	for id in $ids; do
		gh api -X POST "repos/{owner}/{repo}/actions/runs/$id/approve" >/dev/null 2>&1 && approved=1
	done
	if [ "$approved" = 1 ]; then
		echo "#$pr: approved the pull request's workflow runs on $sha"
		return
	fi
	gh workflow run "$AIGIT_DISPATCH_CI" --ref "$head"
	echo "#$pr: dispatched $AIGIT_DISPATCH_CI on $head"
}

if [ "$#" -eq 0 ]; then
	mapfile -t prs < <(gh pr list --state open --limit 200 --json number -q '.[].number')
	set -- "${prs[@]}"
fi

start="$(git rev-parse HEAD)"
for pr in "$@"; do
	resolve "$pr"
done
git checkout -q --detach "$start"
