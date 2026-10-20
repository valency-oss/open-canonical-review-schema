#!/usr/bin/env python3
"""Convert a saved OpenReview forum page into OCRS reviews, one JSON file per Official Review.

    uv run scripts/openreview_page_to_ocrs.py "Paper title | OpenReview.html" -o reviews/

Save the page from a browser (File > Save Page As) after the replies have loaded. Each review
links back to its note: `provenance.source_url` opens the forum at that note, and
`extensions.openreview.source_fields` says which page field each OCRS value came from.

The page shows dates without a time zone; pass the one the page was viewed in with `--timezone`
(an IANA name such as America/Los_Angeles, an offset written `--timezone=-07:00`, or `local`).
"""

import argparse
import json
import os
import re
import sys
from datetime import UTC, timedelta, timezone, tzinfo
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from ocrs import validate_canonical
from ocrs.mappers.openreview_page import parse_forum_page, reviews_from_forum


class SystemLocalTime(tzinfo):
    """The computer's time zone, with its daylight saving rules for each date it is asked about.

    `datetime.astimezone().tzinfo` is only today's fixed offset, which is wrong for dates on the
    other side of a clock change."""

    def utcoffset(self, dt):
        return dt.replace(tzinfo=None).astimezone().utcoffset()

    def dst(self, dt):
        return dt.replace(tzinfo=None).astimezone().dst()

    def tzname(self, dt):
        return "local" if dt is None else dt.replace(tzinfo=None).astimezone().tzname()


SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")


def parse_timezone(name: str) -> tzinfo:
    if name.casefold() == "local":
        return SystemLocalTime()
    offset = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", name)
    if offset:
        hours, minutes = int(offset.group(2)), int(offset.group(3))
        if hours > 23 or minutes > 59:
            raise argparse.ArgumentTypeError(f"invalid UTC offset {name!r}")
        delta = timedelta(hours=hours, minutes=minutes)
        return timezone(-delta if offset.group(1) == "-" else delta)
    try:
        return ZoneInfo(name)
    except Exception as error:  # unknown name, or no time zone database on this system
        raise argparse.ArgumentTypeError(f"unknown time zone {name!r}: {error}") from error


def asset_base(page: Path, out_dir: Path) -> str:
    """Where images saved beside the page are, as seen from the output folder: a path between
    the two, or the page folder's file URI when there is none (different drives on Windows)."""
    folder = page.resolve().parent
    try:
        return quote(Path(os.path.relpath(folder, out_dir.resolve())).as_posix())
    except ValueError:
        return folder.as_uri()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("page", type=Path, help="the saved OpenReview forum page (.html)")
    parser.add_argument("-o", "--out-dir", type=Path, help="default: ocrs-<forum id>/")
    parser.add_argument("--timezone", type=parse_timezone, default=UTC, metavar="ZONE")
    parser.add_argument("--keep-raw", action="store_true", help="keep each note in raw_payload")
    args = parser.parse_args()

    # Bytes decoded as they are, so the recorded hash is the file's own.
    html = args.page.read_bytes().decode("utf-8")
    out_dir = args.out_dir or Path(f"ocrs-{parse_forum_page(html).id}")
    forum = parse_forum_page(html, asset_base=asset_base(args.page, out_dir))
    reviews = reviews_from_forum(forum, tz=args.timezone, keep_raw=args.keep_raw)
    if not reviews:
        print(f"No Official Reviews on the page for forum {forum.id}.", file=sys.stderr)
        return 1

    # A review's ID comes from the page and names its file, so it must not name a path.
    unsafe = [r["review_id"] for r in reviews if not SAFE_ID.fullmatch(r["review_id"])]
    if unsafe:
        print(f"Refusing to write: unsafe review IDs on the page: {unsafe}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for review in reviews:
        validate_canonical(review)
        path = out_dir / f"{review['review_id']}.json"
        path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rating = next((m["value"] for m in review.get("metrics", []) if m["key"] == "overall"), "-")
        print(f"{path}  {review['referees'][0].get('referee_id', '?')}  rating {rating}")
        print(f"  {review['provenance']['source_url']}")
    zone = reviews[0]["extensions"]["openreview"]["source_page"]["timezone_assumed"]
    print(f"{len(reviews)} reviews of {forum.title!r}; page dates read as {zone}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
