#!/usr/bin/env -S jq -r -f

# $ git config edit
#
# [diff "places-textconv"]
#     textconv = _scripts/places-textconv.jq

# inspired by https://news.ycombinator.com/item?id=25006277

def format_key: if . | test("\\W") then . | @json else . end;
def format_path: map(if type == "number" then "[\(.)]" else ".\(. | format_key)" end) | join("");
def format: tostream | select(length == 2) | "\(.[0] | format_path) = \(.[1] | @json)";

.[]
| .section as $section
| .venues[]
| .place_name as $venue
| "\($section) → \($venue)", (format | "  \(.)"), ""
