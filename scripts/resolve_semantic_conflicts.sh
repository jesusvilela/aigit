#!/usr/bin/env bash
# Resolve pull requests that conflict with their base only in .semantic/.
#
# A hosted merge button runs no custom merge driver, so a pull request whose
# generated artifacts conflict with its base cannot be merged there even when
# its source merges cleanly. For each pull request GitHub reports as
# conflicting, this merges the base in with the AIGit merge driver and pushes
# the result. A pull request whose source conflicts, or whose merged artifacts
# would be stale, is left for its author. One pull request failing -- its
# branch moved, the token may not push to it -- never stops the others.
#
# Usage: resolve_semantic_conflicts.sh [PR_NUMBER...]   (default: all open PRs)
# Needs: gh (authenticated), a checkout with push access, AIGit installed.
# AIGIT_DISPATCH_CI=<workflow file>: for the default Actions token, whose
# pushes leave the pull request's workflow runs awaiting approval. Those runs
# are approved, so their checks report on the pull request; if that is not
# permitted, the named workflow is dispatched on the branch instead.

set -euo pipefail

attempts="${AIGIT_MERGEABLE_ATTEMPTS:-10}"
# The driver must be the installed AIGit, not whatever a pull request's branch
# holds in ./aigit: -P keeps the work tree off sys.path (Python 3.11+).
python=("${PYTHON:-python3}")
if "${python[@]}" -P -c '' 2>/dev/null; then
	python+=(-P)
fi

git config merge.aigit-semantic.name 'AIGit semantic artifact merge'
git config merge.aigit-semantic.driver "${python[*]} -m aigit.cli merge-driver %O %A %B %P"
# Route the artifacts even on branches cut before .gitattributes routed them.
info_attributes="$(git rev-parse --git-path info/attributes)"
mkdir -p "$(dirname "$info_attributes")"
for artifact in manifest.jsonl chunk_index.json edges.jsonl provenance.jsonl; do
	line=".semantic/$artifact merge=aigit-semantic"
	grep -qxF "$line" "$info_attributes" 2>/dev/null || printf '%s\n' "$line" >>"$info_attributes"
done

mergeable_state() {
	# GitHub computes mergeability lazily and can report a verdict made
	# against an older base: a "mergeable" counts only if GitHub's trial merge
	# was built on the base tip we fetched. CONFLICTING, MERGEABLE or UNKNOWN.
	local pr="$1" base_sha="$2" state merge_sha parent
	for ((i = 0; i < attempts; i++)); do
		IFS=$'\t' read -r state merge_sha < <(
			gh api "repos/{owner}/{repo}/pulls/$pr" -q '[(.mergeable | tostring), (.merge_commit_sha // "")] | @tsv'
		) || state=null
		if [ "$state" = false ]; then
			echo CONFLICTING
			return
		fi
		if [ "$state" = true ] && [ -n "$merge_sha" ]; then
			parent="$(gh api "repos/{owner}/{repo}/commits/$merge_sha" -q '.parents[0].sha' 2>/dev/null || true)"
			if [ "$parent" = "$base_sha" ]; then
				echo MERGEABLE
				return
			fi
		fi
		sleep 6
	done
	echo UNKNOWN
}

resolve() {
	local pr="$1" head base cross state
	if ! IFS=$'\t' read -r head base cross < <(
		gh pr view "$pr" --json headRefName,baseRefName,isCrossRepository \
			-q '[.headRefName, .baseRefName, .isCrossRepository] | @tsv'
	); then
		echo "#$pr: could not be read; skipped"
		return
	fi
	if [ "$cross" = true ]; then
		echo "#$pr: from a fork, which this token cannot push to; skipped"
		return
	fi
	if ! git fetch -q origin "$base" "$head"; then
		echo "#$pr: could not fetch $base and $head; skipped"
		return
	fi
	state="$(mergeable_state "$pr" "$(git rev-parse "origin/$base")")"
	case "$state" in
	MERGEABLE)
		echo "#$pr: no conflict with $base"
		return
		;;
	UNKNOWN)
		echo "#$pr: GitHub has no verdict against the current $base yet; skipped until the next event"
		return
		;;
	esac
	git checkout -q -B "aigit/resolve-$pr" "origin/$head"
	if ! git merge -q --no-edit "origin/$base"; then
		git merge --abort 2>/dev/null || git reset -q --hard
		echo "#$pr: the source conflicts with $base; left for the author"
		return
	fi
	if ! "${python[@]}" -m aigit.cli chunk --repo . --check; then
		echo "#$pr: the merged artifacts would be stale; left for the author"
		return
	fi
	if ! git push -q origin "HEAD:refs/heads/$head"; then
		echo "#$pr: push refused (the branch moved, or this token may not push to it); left alone"
		return
	fi
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
			-q '.[] | select(.conclusion == "action_required") | .databaseId' || true)"
		[ -n "$ids" ] && break
		sleep 5
	done
	for id in $ids; do
		gh api -X POST "repos/{owner}/{repo}/actions/runs/$id/approve" >/dev/null 2>&1 && approved=1
	done
	if [ "$approved" = 1 ]; then
		echo "#$pr: approved the pull request's workflow runs on $sha"
	elif gh workflow run "$AIGIT_DISPATCH_CI" --ref "$head"; then
		echo "#$pr: dispatched $AIGIT_DISPATCH_CI on $head"
	else
		echo "#$pr: could neither approve nor dispatch checks on $sha"
	fi
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
