"""Build Trygg's blocklist tiers from Hagezi's lists, sized for UniFi gateways.

Run: python build.py OUTPUT_DIR

UniFi limits each dynamic network list to 100,000 lines, and all dynamic lists
on a gateway to 500,000 entries in total. So each tier is built as one merged
list: its Hagezi source lists are combined, every entry already covered by a
parent entry is removed (blocking *.example.com makes *.ads.example.com
redundant, and blocking a whole TLD makes every domain under it redundant),
and the result is split into a fixed number of parts.

A tier's number of parts never changes on its own, so a gateway set up with
every part keeps getting the whole tier. If anything looks wrong, the build
stops and the previously published lists stay in place.
"""

import ipaddress
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path

SOURCE_BASE = "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/"
PUBLISHED_BASE = "https://raw.githubusercontent.com/braaten-stack/tryggsystems-blocklists/lists/"
LICENSE_URL = "https://github.com/braaten-stack/tryggsystems-blocklists/blob/main/LICENSE"

UNIFI_LIMIT = 500_000           # all dynamic lists on one gateway, combined
MAX_ENTRIES_PER_PART = 99_000   # UniFi allows 100,000 lines per list; room for the header
TIER_BUDGET = 450_000           # a tier plus the IP lists may use at most this much
MAX_DROP = 0.5                  # a tier shrinking by more than this is treated as a bad download

# Hagezi domain lists (wildcard format) used in the tiers.
DOMAIN_SOURCES = {
    "light": "wildcard/light.txt",
    "normal": "wildcard/multi.txt",
    "pro-plus": "wildcard/pro.plus.txt",
    "tif-mini": "wildcard/tif.mini.txt",
    "tif-medium": "wildcard/tif.medium.txt",
    "dyndns": "wildcard/dyndns.txt",
    "doh": "wildcard/doh.txt",
    "spam-tlds": "wildcard/spam-tlds.txt",
    "hoster": "wildcard/hoster.txt",
}

# Lists gateways pull straight from Hagezi. They're counted here so the
# manifest can show how much room each tier leaves under UniFi's limit.
IP_LISTS = {"tif-ips": "ips/tif.txt", "doh-ips": "ips/doh.txt"}

# Spamhaus DROP is loaded by gateways straight from Spamhaus. Its terms give no
# permission to republish it, so the build only counts it, for the room checks.
SPAMHAUS_DROP_URL = "https://www.spamhaus.org/drop/drop.txt"
SPAMHAUS_DROP_ALLOWANCE = 2000  # used only if it has never been counted
RECOMMENDED_ADDONS = {"nsfw": "wildcard/nsfw.txt", "gambling-medium": "wildcard/gambling.medium.txt"}

# IPv6 addresses of encrypted DNS servers. Hagezi publishes its list for IPv4
# only. dibdot's DoH-IP-blocklists resolves public DoH servers to IPv6, but
# includes shared hosting and CDN addresses that also serve ordinary websites.
# So an IPv6 address is kept only when its server's IPv4 address is on Hagezi's
# curated list, which leaves those shared addresses out.
DIBDOT_BASE = "https://raw.githubusercontent.com/dibdot/DoH-IP-blocklists/master/"
DOH_IPV6_MINIMUM = 200
# Cloudflare's shared CDN range. Its DNS resolver range is the one exception.
SHARED_IPV6 = [ipaddress.ip_network("2606:4700::/32")]
SHARED_IPV6_EXCEPTIONS = [ipaddress.ip_network("2606:4700:4700::/48")]

# (tier name, source lists, number of parts)
TIERS = [
    ("low-power", ["light", "tif-mini", "dyndns", "doh"], 3),
    ("low-power-tlds", ["light", "tif-mini", "dyndns", "doh", "spam-tlds"], 3),
    ("standard", ["normal", "tif-mini", "dyndns", "doh"], 4),
    ("standard-tlds", ["normal", "tif-mini", "dyndns", "doh", "spam-tlds"], 3),
    ("strict", ["pro-plus", "tif-medium", "dyndns", "doh", "spam-tlds", "hoster"], 4),
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


def stated_count(header):
    """The entry count Hagezi states in a list's header, if it states one."""
    value = header_value(header, "Number of entries")
    if value is not None:
        return int(value.replace(",", ""))
    tlds = header_value(header, "Number of latin TLDs")  # the Most Abused TLDs list
    if tlds is not None:
        return sum(int(n) for n in re.findall(r"\d+", tlds))
    return None


def load_domain_list(name, path, problems):
    source = SOURCE_BASE + path
    print(f"{name}: fetching {source}", flush=True)
    header, entries = parse(fetch(source))
    stated = stated_count(header)
    if stated is None or stated != len(entries):
        problems.append(f"{name}: header says {stated} entries, file has {len(entries)}")
    domains = set()
    for entry in entries:
        if not entry.startswith("*."):
            problems.append(f"{name}: unexpected entry format {entry!r}")
            break
        domains.add(entry[2:].lower())
    return {
        "title": header_value(header, "Title"),
        "version": header_value(header, "Version") or header_value(header, "Last modified"),
        "source": source,
        "domains": domains,
    }


def count_list(path, problems, minimum):
    _, entries = parse(fetch(SOURCE_BASE + path))
    if len(entries) < minimum:
        problems.append(f"{path}: only {len(entries)} entries")
    return len(entries)


def merge(domain_sets):
    """Combine domain sets, dropping any domain already covered by a parent."""
    combined = set().union(*domain_sets)
    kept = []
    for domain in combined:
        labels = domain.split(".")
        if any(".".join(labels[i:]) in combined for i in range(1, len(labels))):
            continue
        kept.append(domain)
    # Sort by reversed labels so a domain sits next to its relatives.
    kept.sort(key=lambda d: d.split(".")[::-1])
    return kept


def parse_annotated(text):
    """dibdot's lists: one address per line, then '# domain, domain'."""
    servers = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        address, _, names = line.partition("#")
        servers[address.strip()] = {n.strip() for n in names.split(",") if n.strip()}
    return servers


def is_shared(address):
    ip = ipaddress.ip_address(address)
    if any(ip in net for net in SHARED_IPV6_EXCEPTIONS):
        return False
    return any(ip in net for net in SHARED_IPV6)


def build_doh_ipv6(problems):
    print("doh-ipv6: building from dibdot and Hagezi", flush=True)
    _, hagezi = parse(fetch(SOURCE_BASE + IP_LISTS["doh-ips"]))
    hagezi = set(hagezi)
    ipv4 = parse_annotated(fetch(DIBDOT_BASE + "doh-ipv4.txt"))
    ipv6 = parse_annotated(fetch(DIBDOT_BASE + "doh-ipv6.txt"))
    trusted = set()
    for address, names in ipv4.items():
        if address in hagezi:
            trusted |= names
    kept = sorted(
        (a for a, names in ipv6.items() if names & trusted and not is_shared(a)),
        key=ipaddress.ip_address,
    )
    if len(kept) < DOH_IPV6_MINIMUM:
        problems.append(f"doh-ipv6: only {len(kept)} addresses")
    return kept


def count_spamhaus_drop(previous, warnings):
    try:
        lines = [line.split(";")[0].strip() for line in fetch(SPAMHAUS_DROP_URL).splitlines()]
        entries = [line for line in lines if line]
        if len(entries) < 200:
            raise ValueError(f"only {len(entries)} entries")
        return len(entries)
    except Exception as error:  # noqa: BLE001 - keep building with the last known count
        fallback = previous.get("spamhaus-drop", SPAMHAUS_DROP_ALLOWANCE)
        warnings.append(f"spamhaus-drop: couldn't be counted ({error}); using {fallback}")
        return fallback


def previous_counts():
    try:
        manifest = json.loads(fetch(PUBLISHED_BASE + "manifest.json", attempts=1))
        counts = {name: info["entries"] for name, info in manifest["tiers"].items()}
        for name, info in manifest.get("ip_lists", {}).items():
            counts[name] = info["entries"]
        for name, info in manifest.get("ipv6_lists", {}).items():
            counts[name] = info["entries"]
        return counts
    except Exception:  # noqa: BLE001 - first build of this layout
        return {}


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    built = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    problems, warnings = [], []

    sources = {name: load_domain_list(name, path, problems) for name, path in DOMAIN_SOURCES.items()}
    previous = previous_counts()
    ip_counts = {name: count_list(path, problems, 500) for name, path in IP_LISTS.items()}
    drop_count = count_spamhaus_drop(previous, warnings)
    addon_counts = {name: count_list(path, problems, 1000) for name, path in RECOMMENDED_ADDONS.items()}
    doh_ipv6 = build_doh_ipv6(problems)
    ip_total = sum(ip_counts.values()) + drop_count + len(doh_ipv6)
    addon_total = sum(addon_counts.values())

    manifest = {
        "built": built,
        "unifi_limit": UNIFI_LIMIT,
        "ip_lists": {
            **{name: {"url": SOURCE_BASE + path, "entries": ip_counts[name]} for name, path in IP_LISTS.items()},
            "spamhaus-drop": {
                "url": SPAMHAUS_DROP_URL,
                "entries": drop_count,
                "note": "Loaded straight from Spamhaus; counted here, not republished",
            },
        },
        "recommended_addons": {
            name: {"url": SOURCE_BASE + path, "entries": addon_counts[name]} for name, path in RECOMMENDED_ADDONS.items()
        },
        "tiers": {},
    }
    outputs = {}

    if "doh-ipv6" in previous and len(doh_ipv6) < previous["doh-ipv6"] * (1 - MAX_DROP):
        problems.append(f"doh-ipv6: {len(doh_ipv6)} addresses, down from {previous['doh-ipv6']}")
    outputs["doh-ipv6.txt"] = "\n".join([
        "# Title: Trygg Systems Encrypted DNS Bypass, IPv6",
        "# Description: IPv6 addresses of public encrypted DNS servers, kept only for servers whose IPv4",
        "#   addresses are on Hagezi's Encrypted DNS Bypass IPv4 list, so shared hosting and CDN addresses stay out",
        f"# Sources: {DIBDOT_BASE}doh-ipv6.txt, {DIBDOT_BASE}doh-ipv4.txt, {SOURCE_BASE}{IP_LISTS['doh-ips']}",
        f"# License: GPL-3.0, see {LICENSE_URL}",
        f"# Built: {built}",
        f"# Entries: {len(doh_ipv6)}",
        "#",
    ] + doh_ipv6) + "\n"
    manifest["ipv6_lists"] = {
        "doh-ipv6": {"url": PUBLISHED_BASE + "doh-ipv6.txt", "entries": len(doh_ipv6)},
    }

    for tier, members, parts in TIERS:
        entries = merge([sources[m]["domains"] for m in members])
        count = len(entries)
        with_ips = count + ip_total
        per_part = math.ceil(count / parts)
        print(f"{tier}: {count} entries, {with_ips} with the IP lists, {parts} parts of up to {per_part}", flush=True)

        if per_part > MAX_ENTRIES_PER_PART:
            problems.append(f"{tier}: {count} entries no longer fit in {parts} parts; raise its part count")
        if with_ips > TIER_BUDGET:
            problems.append(f"{tier}: {with_ips} entries with the IP lists, over the {TIER_BUDGET} budget")
        if tier in previous and count < previous[tier] * (1 - MAX_DROP):
            problems.append(f"{tier}: {count} entries, down from {previous[tier]}")
        if not tier.startswith("strict") and with_ips + addon_total > UNIFI_LIMIT:
            warnings.append(
                f"{tier}: with NSFW and Gambling Medium added, the gateway would hold "
                f"{with_ips + addon_total} entries, over UniFi's {UNIFI_LIMIT} limit"
            )

        files = []
        for index in range(parts):
            chunk = entries[index * per_part:(index + 1) * per_part]
            file_name = f"{tier}-{index + 1}.txt"
            lines = [
                f"# Title: Trygg Systems blocklist, {tier} tier, part {index + 1} of {parts}",
                "# Description: Hagezi's lists below, merged, with entries already covered by a parent entry removed",
                "# Sources:",
            ]
            lines += [f"#   {sources[m]['title']} ({sources[m]['version']}), {sources[m]['source']}" for m in members]
            lines += [
                "# Homepage of the source lists: https://github.com/hagezi/dns-blocklists",
                f"# License: GPL-3.0, see {LICENSE_URL}",
                f"# Built: {built}",
                f"# Entries in this part: {len(chunk)}",
                f"# Entries in this tier: {count}",
                "#",
            ]
            lines += [f"*.{domain}" for domain in chunk]
            outputs[file_name] = "\n".join(lines) + "\n"
            files.append({"file": file_name, "url": PUBLISHED_BASE + file_name, "entries": len(chunk)})

        manifest["tiers"][tier] = {
            "sources": members,
            "entries": count,
            "entries_with_ip_lists": with_ips,
            "room_under_unifi_limit": UNIFI_LIMIT - with_ips,
            "parts": files,
        }

    manifest["sources"] = {
        name: {"title": s["title"], "version": s["version"], "url": s["source"], "entries": len(s["domains"])}
        for name, s in sources.items()
    }

    for warning in warnings:
        print(f"::warning::{warning}", flush=True)
    if problems:
        print("Build stopped; nothing was published:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        sys.exit(1)

    for file_name, text in outputs.items():
        (out / file_name).write_text(text, encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python build.py OUTPUT_DIR")
    main(sys.argv[1])
