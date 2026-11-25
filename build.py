"""Split Hagezi blocklists into parts that fit UniFi's 100,000-line limit per list.

Run: python build.py OUTPUT_DIR

Each list in LISTS is downloaded from Hagezi, checked, and split into a fixed
number of parts of roughly equal size. The number of parts never changes on its
own, so a gateway set up with every part of a list keeps getting all of it. If a
list grows past what its parts can hold, the build fails instead of dropping
entries, and the previously published lists stay in place.
"""

import json
import math
import sys
import time
import urllib.request
from pathlib import Path

SOURCE_BASE = "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/"
PUBLISHED_BASE = "https://raw.githubusercontent.com/braaten-stack/tryggsystems-blocklists/lists/"
LICENSE_URL = "https://github.com/braaten-stack/tryggsystems-blocklists/blob/main/LICENSE"

# Most entries a single part may hold. UniFi allows 100,000 lines per list;
# this leaves room for the header lines at the top of each part.
MAX_ENTRIES_PER_PART = 99_000

# A list that shrinks by more than this since the last build is treated as a
# broken download, and the build stops.
MAX_DROP = 0.5

# (published name, Hagezi path, number of parts)
LISTS = [
    ("normal", "wildcard/multi.txt", 3),
    ("pro", "wildcard/pro.txt", 3),
    ("pro-plus", "wildcard/pro.plus.txt", 3),
    ("tif-mini", "wildcard/tif.mini.txt", 2),
    ("tif-medium", "wildcard/tif.medium.txt", 3),
    ("tif", "wildcard/tif.txt", 13),
]


def fetch(url, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read().decode("utf-8")
        except Exception as error:  # noqa: BLE001 - retry on any download error
            if attempt == attempts:
                raise
            print(f"  download failed ({error}), retrying", flush=True)
            time.sleep(10 * attempt)


def parse(text):
    header, entries = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not entries:
                header.append(line)
            continue
        entries.append(line)
    return header, entries


def header_value(header, key):
    prefix = f"# {key}:"
    for line in header:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def previous_counts():
    try:
        manifest = json.loads(fetch(PUBLISHED_BASE + "manifest.json", attempts=1))
        return {name: info["entries"] for name, info in manifest["lists"].items()}
    except Exception:  # noqa: BLE001 - first build, or nothing published yet
        return {}


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    built = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    previous = previous_counts()
    manifest = {"built": built, "lists": {}}
    problems = []

    for name, path, parts in LISTS:
        source = SOURCE_BASE + path
        print(f"{name}: fetching {source}", flush=True)
        header, entries = parse(fetch(source))
        count = len(entries)

        stated = header_value(header, "Number of entries")
        if stated is None or int(stated.replace(",", "")) != count:
            problems.append(f"{name}: header says {stated} entries, file has {count}")
            continue
        if name in previous and count < previous[name] * (1 - MAX_DROP):
            problems.append(f"{name}: {count} entries, down from {previous[name]}")
            continue
        per_part = math.ceil(count / parts)
        if per_part > MAX_ENTRIES_PER_PART:
            problems.append(
                f"{name}: {count} entries no longer fit in {parts} parts; raise its part count"
            )
            continue

        files = []
        for index in range(parts):
            chunk = entries[index * per_part:(index + 1) * per_part]
            file_name = f"{name}-{index + 1}.txt"
            lines = [f"# Trygg Systems split of the list below: part {index + 1} of {parts}"]
            lines += header
            lines += [
                f"# Modified: split into {parts} parts by Trygg Systems, built {built}",
                f"# Split source: {source}",
                f"# Split license: GPL-3.0, see {LICENSE_URL}",
                f"# Entries in this part: {len(chunk)}",
                "#",
            ]
            lines += chunk
            (out / file_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
            files.append({"file": file_name, "url": PUBLISHED_BASE + file_name, "entries": len(chunk)})

        manifest["lists"][name] = {
            "title": header_value(header, "Title"),
            "source": source,
            "version": header_value(header, "Version"),
            "entries": count,
            "parts": files,
        }
        print(f"  {count} entries in {parts} parts of up to {per_part}", flush=True)

    if problems:
        print("Build stopped; nothing was published:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        sys.exit(1)

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python build.py OUTPUT_DIR")
    main(sys.argv[1])
