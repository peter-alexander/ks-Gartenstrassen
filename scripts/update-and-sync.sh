#!/usr/bin/env bash
set -euo pipefail

# Synchronisiert main in beide Richtungen, ohne Historie zu überschreiben.
# Lokale, nicht ignorierte Änderungen werden vor dem Abgleich committet.

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
branch=main
commit_message="Sync local changes ($(date -u +%Y-%m-%dT%H:%M:%SZ))"

usage() {
	cat <<'EOF'
Usage: ./scripts/update-and-sync.sh [--message TEXT]

Synchronisiert den lokalen main-Branch bidirektional mit origin/main:
  1. committet alle nicht ignorierten lokalen Änderungen,
  2. holt origin/main und rebased lokale Commits darauf,
  3. pusht main und verifiziert danach lokalen und Remote-Stand.

Optionen:
  -m, --message TEXT  Commit-Nachricht für lokale Änderungen.
  -h, --help          Diese Hilfe anzeigen.
EOF
}

while (($#)); do
	case "$1" in
		-m|--message)
			if (($# < 2)); then
				echo "Abbruch: $1 benötigt eine Commit-Nachricht." >&2
				exit 2
			fi
			commit_message=$2
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unbekannte Option: $1" >&2
			usage >&2
			exit 2
			;;
	esac
	shift
done

cd "$repo_dir"

if [[ $(git branch --show-current) != "$branch" ]]; then
	echo "Abbruch: Das Skript darf nur auf '$branch' laufen." >&2
	exit 1
fi

for operation in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
	if [[ -e $(git rev-parse --git-path "$operation") ]]; then
		echo "Abbruch: Eine Git-Operation ist noch offen ($operation)." >&2
		exit 1
	fi
done

if [[ -n $(git status --porcelain) ]]; then
	echo "Committe lokale Änderungen …"
	git add -A
	git commit -m "$commit_message"
fi

echo "Hole origin/$branch …"
git fetch --prune origin "$branch"
remote_before_rebase=$(git rev-parse "origin/$branch")
git rebase "origin/$branch"

# Zwischen Fetch und Rebase kann der Remote-Branch weitergelaufen sein.
git fetch --prune origin "$branch"
remote_after_rebase=$(git rev-parse "origin/$branch")
if [[ $remote_before_rebase != "$remote_after_rebase" ]]; then
	echo "origin/$branch hat sich während des Syncs geändert; rebase erneut …"
	git rebase "$remote_after_rebase"
fi

echo "Pushe $branch …"
git push origin "$branch"

git fetch --prune origin "$branch"
if [[ $(git rev-parse HEAD) != $(git rev-parse "origin/$branch") ]]; then
	echo "Abbruch: Lokaler und Remote-Stand unterscheiden sich nach dem Push." >&2
	exit 1
fi
if [[ -n $(git status --porcelain) ]]; then
	echo "Abbruch: Arbeitsbaum ist nach dem Sync nicht sauber." >&2
	exit 1
fi

echo "Sync erfolgreich: $(git rev-parse --short HEAD) entspricht origin/$branch."
