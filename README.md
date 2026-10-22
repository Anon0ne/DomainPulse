# Domain Pulse

A small tray app that watches a list of domains and tells you when one becomes **available** or is **about to expire**. Built by [BizHostNC](https://bizhostnc.com).

## Features

- Lives in the system tray on Windows and Linux. Closing the window keeps it running; quit from the tray menu.
- Import domains from a CSV (a `domain` column, or just the first column) or type them in.
- Export a CSV with status, registrar, expiry date, days left and last checked time.
- Desktop notifications when a domain becomes available, and at 30, 7 and 1 days before expiry. Each alert fires once, and the countdown resets when a domain is renewed.
- Color-coded status table with filter and sorting, plus a one-click "Register" link for available domains.

## How checking works

Lookups use [RDAP](https://www.icann.org/rdap), the structured successor to WHOIS, straight from each registry. There are no API keys and no third-party service.

| Situation | How often it is checked |
| --- | --- |
| Registered, more than 30 days left | Every 24 hours |
| Registered, 30 days or less | Every 6 hours |
| Available | Every 24 hours |
| Last check failed | Retried after 1 hour |

Only one lookup runs at a time with at least 4 seconds between them, and each recheck gets a little random jitter so checks spread out over the day. 250 domains work out to roughly one request every few minutes.

A few country-code TLDs don't offer RDAP yet. Those show as check errors.

## Download

Grab the latest build from [Releases](../../releases).

- **Windows:** run `DomainPulse.exe`. The alpha is unsigned, so SmartScreen may warn; choose "More info" then "Run anyway".
- **Linux:** `chmod +x DomainPulse-*.AppImage` and run it. Your desktop needs a system tray (most do; GNOME needs the AppIndicator extension). If Qt complains about `xcb-cursor`, install `libxcb-cursor0`.

Start it with `--minimized` to launch straight to the tray.

## Run from source

```
pip install -r requirements.txt
python run.py
```

Tests: `pip install pytest && python -m pytest`

## Releasing

Push a tag like `v0.1.0-alpha`, or run the **Build and release** workflow from the Actions tab and enter a version. GitHub Actions runs the tests, builds the Windows `.exe` and Linux AppImage, and attaches them to a pre-release.

Data (the domain list and its state) is stored in SQLite in your user app-data folder.
