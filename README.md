# Trygg Systems blocklists

Copies of [Hagezi's DNS blocklists](https://github.com/hagezi/dns-blocklists), split into parts small enough for a UniFi gateway to import. Which lists a site runs is set by the segmentation and firewall standard in [tryggsystems-standards](https://github.com/braaten-stack/tryggsystems-standards).

## Why this exists

UniFi imports a domain list from a URL, but only up to 100,000 lines per list. Several of Hagezi's lists are bigger than that. This repository splits each of those into a fixed number of parts, and each part is added to the gateway as its own list.

## How it works

- [`build.py`](build.py) downloads each list from Hagezi, checks it, and splits it into parts of roughly equal size.
- A scheduled job ([`.github/workflows/build.yml`](.github/workflows/build.yml)) runs the build every six hours and publishes the parts to the [`lists`](https://github.com/braaten-stack/tryggsystems-blocklists/tree/lists) branch. That branch holds only the latest build, so the repository doesn't grow with every run.
- **A list's number of parts never changes on its own.** A gateway set up with every part keeps receiving the whole list.
- **The build stops rather than publish anything wrong.** It stops when a download doesn't match the entry count in Hagezi's own header, when a list shrinks by more than half since the last build, or when a list outgrows its parts. The last good build then stays published, and GitHub reports the failed run. A list that outgrows its parts needs its part count raised in `build.py`, and every gateway using it needs the new part added.
- [`manifest.json`](https://raw.githubusercontent.com/braaten-stack/tryggsystems-blocklists/lists/manifest.json) on the `lists` branch records when the build ran, the Hagezi version used, and the entry count of every part.

## Lists published here

Each part's address is `https://raw.githubusercontent.com/braaten-stack/tryggsystems-blocklists/lists/<file>`.

| List | Hagezi source | Parts | Files |
|---|---|---|---|
| Multi Normal | `wildcard/multi.txt` | 3 | `normal-1.txt` to `normal-3.txt` |
| Multi Pro | `wildcard/pro.txt` | 3 | `pro-1.txt` to `pro-3.txt` |
| Multi Pro++ | `wildcard/pro.plus.txt` | 3 | `pro-plus-1.txt` to `pro-plus-3.txt` |
| Threat Intelligence Feeds, Mini | `wildcard/tif.mini.txt` | 2 | `tif-mini-1.txt` to `tif-mini-2.txt` |
| Threat Intelligence Feeds, Medium | `wildcard/tif.medium.txt` | 3 | `tif-medium-1.txt` to `tif-medium-3.txt` |
| Threat Intelligence Feeds, full | `wildcard/tif.txt` | 13 | `tif-1.txt` to `tif-13.txt` |

## Lists taken straight from Hagezi

These fit within UniFi's limit, so gateways pull them from Hagezi directly. Each address is `https://raw.githubusercontent.com/hagezi/dns-blocklists/main/<path>`.

| List | Path | Type |
|---|---|---|
| Multi Light | `wildcard/light.txt` | Domain |
| Threat Intelligence Feeds, IPv4 | `ips/tif.txt` | IP |
| Encrypted DNS Bypass | `wildcard/doh.txt` | Domain |
| Encrypted DNS Bypass, IPv4 | `ips/doh.txt` | IP |
| Encrypted DNS/VPN/Tor/Proxy Bypass | `wildcard/doh-vpn-proxy-bypass.txt` | Domain |
| Dynamic DNS | `wildcard/dyndns.txt` | Domain |
| Most Abused TLDs | `wildcard/spam-tlds.txt` | Domain |
| Badware Hoster | `wildcard/hoster.txt` | Domain |
| NSFW | `wildcard/nsfw.txt` | Domain |
| Gambling, Medium | `wildcard/gambling.medium.txt` | Domain |
| Social Networks | `wildcard/social.txt` | Domain |
| URL Shortener | `wildcard/urlshortener.txt` | Domain |

## License

The lists are Hagezi's work, released under the GNU General Public License v3.0. The split copies published here are released under the same license ([LICENSE](LICENSE)). Each part keeps Hagezi's original header and states that Trygg Systems split it, when, and from which source.
