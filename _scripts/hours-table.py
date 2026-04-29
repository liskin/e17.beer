#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "click>=8.3.2",
#     "jinja2>=3.1.6",
# ]
# ///

import json
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader, select_autoescape


def parse_weekday_text(weekday_text):
    ret = {}
    for line in weekday_text:
        day, _, hours = line.partition(": ")
        if day and hours:
            ret[day] = hours
    return ret


def test_parse_weekday_text():
    assert parse_weekday_text(
        [
            "Monday: 4:00\u202fPM\u2009\u2013\u200912:00\u202fAM",
            "Tuesday: 12:00\u202fPM\u2009\u2013\u200912:00\u202fAM",
        ]
    ) == {
        "Monday": "4:00\u202fPM\u2009–\u200912:00\u202fAM",
        "Tuesday": "12:00\u202fPM\u2009\u2013\u200912:00\u202fAM",
    }


@click.command()
@click.argument("data", type=click.File())
def main(data) -> None:
    places = json.load(data)
    for place in places:
        place["human_readable_hours"] = parse_weekday_text(place["weekday_text"])

    env = Environment(
        loader=FileSystemLoader(Path(__file__).resolve().parent),
        autoescape=select_autoescape(),
    )
    template = env.get_template("hours-table.html")
    print(template.render(places=places))


if __name__ == "__main__":
    main()
