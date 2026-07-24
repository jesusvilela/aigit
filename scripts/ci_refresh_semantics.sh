#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-python3}"

cleanup_caches() {
	find . -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
}

list_nonsemantic_changes() {
	git status --porcelain=v1 --untracked-files=all |
		sed 's/^...//' |
		sed 's#.* -> ##' |
		grep -v '^.semantic/' || true
}

cd "$repo_root"

baseline_nonsemantic_changes="$(list_nonsemantic_changes)"

cleanup_caches
"$python_bin" -m pytest -q
"$python_bin" -m aigit.cli chunk --repo .
cleanup_caches

baseline_file="$(mktemp)"
after_file="$(mktemp)"
printf '%s\n' "$baseline_nonsemantic_changes" | sed '/^$/d' | sort -u > "$baseline_file"
list_nonsemantic_changes | sed '/^$/d' | sort -u > "$after_file"
unexpected_changes="$(comm -13 "$baseline_file" "$after_file")"
rm -f "$baseline_file" "$after_file"

if [ -n "$unexpected_changes" ]; then
	printf 'semantic refresh produced unexpected non-.semantic changes:\n%s\n' "$unexpected_changes" >&2
	exit 1
fi
