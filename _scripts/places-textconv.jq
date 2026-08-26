#!/usr/bin/env -S jq -r -f

# $ git config set diff.places-textconv.textconv _scripts/places-textconv.jq

# inspired by https://news.ycombinator.com/item?id=25006277

def format_key: if . | test("\\W") then . | @json else . end;
def format_day: ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][.];
def format_path: map(if type == "number" then "[\(. | format_day)]" else ".\(. | format_key)" end) | join("");
def format: tostream | select(length == 2) | "\(.[0] | format_path) = \(.[1] | @json)";

.[]
| .section as $section
| .venues[]
| .place_name as $venue
| "\($section) → \($venue)", (format | "  \(.)"), ""
