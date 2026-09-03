#!/usr/bin/env bash

# deepen a shallow clone to fetch the last commit that changed _data/places.json

set -eux -o pipefail

is_inside_work_tree=$(git rev-parse --is-inside-work-tree)
[[ $is_inside_work_tree == true ]]

while commit_count=$(git rev-list @ -- _data/places.json | wc -l) || exit $? && (( commit_count < 2 )); do
	is_shallow=$(git rev-parse --is-shallow-repository)
	if [[ $is_shallow == false ]]; then
		exit 0
	fi

	git fetch --deepen=10 origin @
done
