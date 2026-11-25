# Trygg Systems blocklists

Trygg's blocklist tiers, built from [Hagezi's DNS blocklists](https://github.com/hagezi/dns-blocklists) and sized for UniFi gateways. Which tier a site runs is set by the segmentation and firewall standard in [tryggsystems-standards](https://github.com/braaten-stack/tryggsystems-standards).

## Why this exists

UniFi imports domain and IP lists from a URL, with two limits:

- **100,000 lines per list.**
- **500,000 entries across all dynamic lists on a gateway.** Past that, UniFi truncates the lists.

Hagezi's lists overlap. The same domain can be on several lists, and a list often blocks a domain whose parent another list already blocks. Each counts toward UniFi's limit. So each tier here is one merged list: its Hagezi lists are combined, and every entry already covered by a parent entry is removed. Blocking `*.example.com` makes `*.ads.example.com` redundant, and blocking a whole TLD such as `.top` makes every domain under it redundant. The merged list is then split into parts under 100,000 lines, and each part is added to the gateway as its own list.

## Tiers

Each part's address is `https://raw.githubusercontent.com/braaten-stack/tryggsystems-blocklists/lists/<file>`.

| Tier | Hagezi lists merged | Parts | Files |
|---|---|---|---|
| Low-power | Multi Light, TIF Mini, Dynamic DNS, Encrypted DNS Bypass | 3 | `low-power-1.txt` to `low-power-3.txt` |
| Low-power with TLDs | The same, plus Most Abused TLDs | 3 | `low-power-tlds-1.txt` to `low-power-tlds-3.txt` |
| Standard | Multi Normal, TIF Mini, Dynamic DNS, Encrypted DNS Bypass | 4 | `standard-1.txt` to `standard-4.txt` |
| Standard with TLDs | The same, plus Most Abused TLDs | 3 | `standard-tlds-1.txt` to `standard-tlds-3.txt` |
| Strict | Multi Pro++, TIF Medium, Dynamic DNS, Encrypted DNS Bypass, Most Abused TLDs, Badware Hoster | 4 | `strict-1.txt` to `strict-4.txt` |

A gateway runs one tier, with every one of its parts. Running two tiers on one gateway would count the same domains twice.

## Lists taken straight from Hagezi

These go alongside the tier. Each address is `https://raw.githubusercontent.com/hagezi/dns-blocklists/main/<path>`.

| List | Path | Type | Used |
|---|---|---|---|
| Threat Intelligence Feeds, IPv4 | `ips/tif.txt` | IP | Every site |
| Encrypted DNS Bypass, IPv4 | `ips/doh.txt` | IP | Every site |
| NSFW | `wildcard/nsfw.txt` | Domain | Recommended |
| Gambling, Medium | `wildcard/gambling.medium.txt` | Domain | Recommended |
| Social Networks | `wildcard/social.txt` | Domain | When a client asks |
| URL Shortener | `wildcard/urlshortener.txt` | Domain | When a client asks |
| Encrypted DNS/VPN/Tor/Proxy Bypass | `wildcard/doh-vpn-proxy-bypass.txt` | Domain | When a client asks |

**The Encrypted DNS Bypass IPv4 list includes Cloudflare's and Quad9's DNS addresses** (`1.1.1.1`, `1.0.0.1`, `9.9.9.9`, `149.112.112.112`), which the gateway uses for its own lookups. Apply it to client zones only, never to traffic from the gateway itself.

## Staying under the 500,000-entry limit

[`manifest.json`](https://raw.githubusercontent.com/braaten-stack/tryggsystems-blocklists/lists/manifest.json) on the `lists` branch shows, for every tier:
- its entry count,
- its count with the two IP lists added,
- the room left under UniFi's limit.

It also shows the current size of each recommended list. Check the room left before adding any list from Hagezi to a gateway.

## How it works

- [`build.py`](build.py) downloads the Hagezi lists, checks them, merges each tier, and splits it into parts.
- A scheduled job ([`.github/workflows/build.yml`](.github/workflows/build.yml)) runs the build every six hours. It publishes the parts and the manifest to the [`lists`](https://github.com/braaten-stack/tryggsystems-blocklists/tree/lists) branch. That branch holds only the latest build, so the repository doesn't grow with every run.
- **A tier's number of parts never changes on its own.** A gateway set up with every part keeps receiving the whole tier.
- **The build stops rather than publish anything wrong,** and the last good build stays published, with GitHub reporting the failed run. It stops when:
  - a download doesn't match the entry count in Hagezi's own header;
  - a tier shrinks by more than half since the last build;
  - a tier outgrows its parts, which means raising its part count in `build.py` and adding the new part on every gateway using it;
  - a tier plus the IP lists passes 450,000 entries.
- When a tier (other than Strict) plus NSFW and Gambling Medium would pass UniFi's limit, the run shows a warning.

## License

The lists are Hagezi's work, released under the GNU General Public License v3.0. The merged lists published here are released under the same license ([LICENSE](LICENSE)). Each part names the Hagezi lists and versions it was built from, and that Trygg Systems merged them.
