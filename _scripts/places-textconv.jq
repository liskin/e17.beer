#!/usr/bin/env -S jq -r -f

# $ git config set diff.places-textconv.textconv _scripts/places-textconv.jq

# inspired by https://news.ycombinator.com/item?id=25006277

def format_day: ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][.];
def format_path:
	any(.[0], .[1]; IN("happy_hours", "day_sort_values", "time_text_sun_to_sat", "time_text_sun_to_sat_24h")) as $format_day
	| map(if type == "number" then "[\(. | if $format_day then format_day else . end)]" else ".\(.)" end) | join("");
def format: tostream | select(length == 2) | "\(.[0] | format_path) = \(.[1] | @json)";

.[]
| .section as $section
| .venues[]
| .place_name as $venue
| "\($section) → \($venue)", (format | "  \(.)"), ""
