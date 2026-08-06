#!/usr/bin/env python3
"""Rotate which <item> sits first in family_quotes.xml.

TRMNL's Featured layout renders only the topmost <item>, so the quote on the
display is whichever one leads the file. This script reorders the item blocks
every 6 hours so all 90 cycle through.

Ordering
--------
    cycle    = floor(unix_seconds / 21600)      # 21600s = 6h
    position = cycle % 90
    seed     = cycle // 90

`seed` picks a shuffle of the 90 items; `position` picks which item in that
shuffle leads the file. Across cycles 0..89 the seed is constant and position
walks 0..89, so every quote leads exactly once before any repeat. At cycle 90
the seed increments and a fresh permutation begins.

Determinism
-----------
The shuffle sorts items by sha256(seed:guid) rather than using random.shuffle().
random's Fisher-Yates is not contractually stable across CPython versions, and a
runner upgrade silently changing the permutation would break the "all 90 before
any repeat" guarantee mid-block. A hash sort is stable forever, on any Python 3.

The shuffle is computed from a CANONICAL item order (sorted by guid number), not
from the file's current order. The file's order changes every run, so seeding off
it would make output depend on history instead of only on the cycle.

The whole output is derived from (cycle, file contents) alone -- rerunning the
same cycle on the same commit reproduces the same bytes, so an unchanged result
is detected and skipped rather than committed.

Only the order of <item> blocks changes. Their inner bytes, the channel block,
indentation and line endings are untouched.
"""
import argparse
import hashlib
import re
import sys
import time

FEED = "family_quotes.xml"
CYCLE_SECONDS = 6 * 3600

# Captures each complete "    <item>...</item>" block, including its indent.
ITEM_RE = re.compile(r"    <item>\n.*?\n    </item>\n", re.S)
GUID_RE = re.compile(r"^      <guid[^>]*>([^<]*)</guid>$", re.M)


def split_feed(text):
    """-> (prefix, [item blocks], suffix). Concatenating them rebuilds the file."""
    blocks = list(ITEM_RE.finditer(text))
    if not blocks:
        raise SystemExit("no <item> blocks found in %s" % FEED)
    prefix = text[: blocks[0].start()]
    suffix = text[blocks[-1].end() :]
    # Items must be contiguous; anything between them would be lost on reassembly.
    for a, b in zip(blocks, blocks[1:]):
        if a.end() != b.start():
            raise SystemExit("unexpected content between items at byte %d" % a.end())
    return prefix, [m.group(0) for m in blocks], suffix


def guid_of(block):
    m = GUID_RE.search(block)
    if not m:
        raise SystemExit("item block has no <guid>:\n" + block)
    return m.group(1)


def guid_sort_key(guid):
    """quote-7 sorts before quote-10 (numeric, not lexical)."""
    m = re.search(r"(\d+)$", guid)
    return (0, int(m.group(1)), guid) if m else (1, 0, guid)


def shuffled(items, seed):
    """Deterministic permutation of items, keyed on seed. Stable across versions."""
    def key(block):
        g = guid_of(block)
        return hashlib.sha256(("%d:%s" % (seed, g)).encode("utf-8")).hexdigest(), g

    return sorted(items, key=key)


def rotate(text, cycle):
    prefix, items, suffix = split_feed(text)
    if len(items) != 90:
        raise SystemExit("expected 90 items, found %d" % len(items))

    canonical = sorted(items, key=lambda b: guid_sort_key(guid_of(b)))
    order = shuffled(canonical, cycle // 90)
    position = cycle % 90
    order = order[position:] + order[:position]  # chosen item to the front
    return prefix + "".join(order) + suffix


def cycle_now():
    return int(time.time()) // CYCLE_SECONDS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", type=int, help="override the computed cycle (dry runs)")
    ap.add_argument("--print-first", action="store_true",
                    help="print the leading quote's guid and exit; writes nothing")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the file would change; writes nothing")
    args = ap.parse_args()

    cycle = args.cycle if args.cycle is not None else cycle_now()
    with open(FEED, encoding="utf-8", newline="") as fh:
        before = fh.read()
    after = rotate(before, cycle)

    if args.print_first:
        print(guid_of(split_feed(after)[1][0]))
        return 0
    if args.check:
        return 1 if after != before else 0

    if after == before:
        print("cycle %d: order already current, nothing to do" % cycle)
        return 0

    # newline="" keeps the LF endings the feed is pinned to; Windows would
    # otherwise translate them to CRLF and break byte fidelity.
    with open(FEED, "w", encoding="utf-8", newline="") as fh:
        fh.write(after)
    print("cycle %d: %s now leads the feed" % (cycle, guid_of(split_feed(after)[1][0])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
