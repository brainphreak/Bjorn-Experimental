# Pager Bjorn

A port/rewrite of [Bjorn](https://github.com/infinition/Bjorn) - the autonomous network reconnaissance Tamagotchi - for the WiFi Pineapple Pager.

![Bjorn on Pager](screenshot.png)

## What is Bjorn?

Bjorn is a Tamagotchi-style autonomous network reconnaissance companion. It automatically:

- **Scans networks** for live hosts and open ports
- **Brute forces** discovered services (FTP, SSH, Telnet, SMB, RDP, MySQL)
- **Exfiltrates data** when credentials are found
- **Displays status** with cute Viking animations

## Features

- **Autonomous Operation** - Set it and forget it. Bjorn continuously scans and attacks.
- **Host-by-Host Attack Strategy** - Runs all applicable attacks on one host before moving to the next
- **Network Discovery** - ARP scanning with ICMP ping fallback for alive host detection
- **Hostname Resolution** - Multiple fallback methods (reverse DNS, NetBIOS, mDNS, nmap)
- **Port Scanning** - Configurable port list with nmap integration
- **Credential Brute Force** - Dictionary attacks against discovered services
- **Guest/Anonymous Detection** - Detects and logs guest access, skips brute force to avoid false positives
- **File Exfiltration** - Automatically steals sensitive files from compromised hosts
- **SQL Data Theft** - Dumps database tables from MySQL servers
- **Web Interface** - Real-time log viewer and control panel at `http://<pager-ip>:8000`
- **LCD Display** - Status updates on the Pager's full color screen with auto-dim for battery saving

## Supported Protocols

| Protocol | Port | Brute Force | File Stealing | Status |
|----------|------|-------------|---------------|--------|
| FTP      | 21   | Yes         | Yes           | Ported |
| SSH      | 22   | Yes         | Yes           | Ported |
| Telnet   | 23   | Yes         | Yes           | Ported |
| SMB      | 445  | Yes         | Yes           | Ported |
| MySQL    | 3306 | Yes         | Yes           | Ported |
| RDP      | 3389 | Yes         | Disabled*     | Ported |

*RDP file exfiltration requires full xfreerdp with drive channels (not available on MIPS)

## Requirements

- WiFi Pineapple Pager (tested on firmware 1.0.7)
- **Network connection** - Pager must be connected to a network to scan (WiFi client mode or Ethernet/USB)
- **Internet connection** (first run only) - Required to install Python3 and nmap via opkg
- All Python dependencies are bundled in `lib/` - only system packages need internet

## Installation

1. Copy the `payloads/` directory to your Pager's SD card:
   ```bash
   scp -r payloads/ root@<pager-ip>:/root/
   ```

2. Launch from the Pager's payload menu: **Reconnaissance > Bjorn**

3. Press **GREEN** to start Bjorn

## Usage

### Graphical Menu

When launching Bjorn, a graphical menu is displayed on the Pager LCD:

1. Dependencies are checked automatically
2. Network connectivity is verified
3. The menu displays:
   - **Start Raid** — Begin scanning and attacking
   - **Interface** — Select which network interface to use (LEFT/RIGHT to cycle)
   - **Web UI** — Toggle the web interface on/off (LEFT/RIGHT to toggle)
   - **Clear Data** — Submenu to clear logs, credentials, stolen data, or all data
   - **Exit** — Return to the Pager launcher

Use **UP/DOWN** to navigate, **A (GREEN)** to select, **B (RED)** to go back.

### Controls While Running

| Button | Action |
|--------|--------|
| **B (RED)** | Open Pause Menu |

### Pause Menu

Press **B** while Bjorn is running to open the pause menu:

| Option | Description |
|--------|-------------|
| **BACK** | Return to Bjorn |
| **Main Menu** | Stop Bjorn and return to the graphical start menu |
| **> Pagergotchi** | Hand off to Pagergotchi (only shown if installed) |
| **Exit Bjorn** | Stop Bjorn and return to the Pager launcher |

The pause menu also includes an integrated **brightness control** — use **UP/DOWN** to adjust brightness (20-100%), **LEFT/RIGHT** to navigate menu options, **GREEN** to confirm, **RED** to go back.

**Payload handoff:** Bjorn dynamically discovers other payloads via `launch_*.sh` scripts in the payload directory. Each launcher script declares a `# Title:` and `# Requires:` path — if the required path exists, the launcher appears as a menu option. Selecting it writes the launcher path to `data/.next_payload` and exits with code 42, which `payload.sh` picks up to launch the target payload.

The screen automatically dims after a configurable timeout to save battery. Any button press wakes the screen.

### Web Interface

Access the web UI at `http://<pager-ip>:8000`. It is a single-page app with the following tabs:

| Tab | Description |
|-----|-------------|
| **Dashboard** | Orchestrator status, live stats grid (targets, credentials, attacks, vulns, ports, data stolen, zombies, level, gold, netKB), and integrated log console with level filters (ALL/INFO/WARN/ERROR), auto-scroll, and incremental log fetching |
| **Network** | Host cards with color-coded status (green=alive, red=dead, gold=pwned) and per-protocol attack badges showing brute force and file steal results for each host |
| **Attacks** | Attack timeline with chronological history. Manual mode toggle with target/port/action dropdowns, execute and stop buttons, running status indicator, and live attack log output |
| **Loot** | Three sub-tabs: Credentials (grouped by protocol), Stolen Files (collapsible tree with download links), and Attack Logs (categorized per-module log files with download links) |
| **Config** | All settings from `shared_config.json` rendered as a form with collapsible sections, toggle switches, and save/restore buttons |
| **Terminal** | Execute commands directly on the device with command history (up/down arrows, persisted in session) |
| **Bjorn** | Live LCD mirror — renders the Pager's raw RGB565 framebuffer in the browser. Scroll-to-zoom on desktop, pinch-to-zoom on mobile |

Only the active tab polls the server — inactive tabs stop polling to conserve device resources.

## Configuration

Edit `config/shared_config.json` to customize Bjorn's behavior:

### General Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `manual_mode` | false | Enable manual attack mode (disables orchestrator) |
| `websrv` | true | Enable the web server |
| `debug_mode` | true | Enable debug mode |
| `retry_success_actions` | false | Retry actions that previously succeeded |
| `retry_failed_actions` | true | Retry actions that previously failed |
| `blacklist_gateway` | true | Automatically blacklist the network gateway |
| `blacklistcheck` | true | Enable blacklist checking |

### Timing Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `scan_interval` | 180 | Seconds between network scans |
| `failed_retry_delay` | 600 | Seconds before retrying failed actions |
| `success_retry_delay` | 900 | Seconds before retrying successful actions |
| `startup_delay` | 10 | Delay before starting orchestrator |
| `web_delay` | 2 | Web server startup delay |
| `screen_delay` | 1 | Screen update interval |
| `livestatus_delay` | 8 | Seconds between livestatus CSV updates |

### Network Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `scan_network_prefix` | 24 | Network prefix for scanning (e.g., /24) |
| `nmap_scan_aggressivity` | -T2 | Nmap timing template (-T0 to -T5) |
| `portlist` | [...] | List of ports to scan (41 ports by default) |
| `mac_scan_blacklist` | [] | MAC addresses to exclude from scanning |
| `ip_scan_blacklist` | [] | IP addresses to exclude from scanning |

### File Stealing Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `steal_max_depth` | 3 | Maximum directory depth to search |
| `steal_max_files` | 500 | Maximum files to discover per host |
| `steal_file_names` | [...] | Specific filenames to steal (e.g., `id_rsa`, `.env`) |
| `steal_file_extensions` | [...] | File extensions to steal (e.g., `.pem`, `.sql`, `.db`) |

### Performance Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `worker_threads` | 5 | Number of concurrent brute force threads |
| `bruteforce_queue_timeout` | 600 | Seconds before a queued brute force task times out |

### Time Wait Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `timewait_ftp` | 0 | Delay between FTP brute force attempts (seconds) |
| `timewait_ssh` | 0 | Delay between SSH brute force attempts (seconds) |
| `timewait_telnet` | 0 | Delay between Telnet brute force attempts (seconds) |
| `timewait_smb` | 0 | Delay between SMB brute force attempts (seconds) |
| `timewait_sql` | 0 | Delay between MySQL brute force attempts (seconds) |
| `timewait_rdp` | 0 | Delay between RDP brute force attempts (seconds) |

### Display Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `screen_brightness` | 80 | Default screen brightness (20-100%) |
| `screen_dim_brightness` | 25 | Brightness when dimmed (20-100%) |
| `screen_dim_timeout` | 60 | Seconds of inactivity before dimming |

### Logging Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `log_debug` | true | Log DEBUG level messages |
| `log_info` | true | Log INFO level messages |
| `log_warning` | true | Log WARNING level messages |
| `log_error` | true | Log ERROR level messages |
| `log_critical` | true | Log CRITICAL level messages |

### Dictionary Files

Customize brute force wordlists in `resources/dictionary/`:
- `users.txt` - Usernames to try
- `passwords.txt` - Passwords to try

## Display Icons

### Stats Grid (top-right)

| Position | Icon | Name | Description |
|----------|------|------|-------------|
| Row 1, Left | Target | `target` | Alive hosts found |
| Row 1, Middle | Folder | `port` | Open ports discovered |
| Row 1, Right | Stack | `vuln` | Vulnerabilities found (TODO - not yet implemented) |
| Row 2, Left | Lock | `cred` | Credentials cracked |
| Row 2, Middle | Skull | `zombie` | Compromised hosts |
| Row 2, Right | File | `data` | Data files stolen |

### Viking Stats (around character)

| Position | Icon | Name | Description |
|----------|------|------|-------------|
| Top-left | Coins | `coins` | Total score |
| Bottom-left | Up arrow | `level` | Bjorn's level |
| Top-right | Network | `networkkb` | Known hosts discovered |
| Bottom-right | Swords | `attacks` | Attacks performed |

## Attack Flow

Bjorn processes hosts one at a time, running all applicable attacks before moving to the next:

1. **Network Scan** - Discover alive hosts and open ports
2. **For each host:**
   - Run all brute force attacks (SSH, FTP, SMB, Telnet, SQL, RDP)
   - Run all file stealing actions for successful brute forces
   - Move to the next host
3. **Repeat** - Continuous scanning for new hosts

### Action Status Messages

| Status | Meaning |
|--------|---------|
| `success` | Credentials found or files stolen |
| `no_creds_found` | Brute force completed, no valid credentials |
| `error` | Exception or connection error occurred |

Guest/anonymous access is automatically detected and saved to credentials files.

## Output Locations

All data is stored in `/mmc/root/loot/bjorn/`:

```
/mmc/root/loot/bjorn/
├── netkb.csv              # Network knowledge base (discovered hosts)
├── livestatus.csv         # Current scan status
├── logs/                  # Application logs
├── archives/              # Archived netkb.csv files
└── output/
    ├── crackedpwd/        # Cracked credentials by protocol
    │   ├── ftp.csv
    │   ├── ssh.csv
    │   ├── smb.csv
    │   ├── sql.csv
    │   ├── telnet.csv
    │   └── rdp.csv
    ├── data_stolen/       # Exfiltrated files by protocol/host
    │   ├── ftp/<mac>_<ip>/
    │   ├── ssh/<mac>_<ip>/
    │   ├── smb/<mac>_<ip>/
    │   ├── sql/<mac>_<ip>/     # Database table dumps
    │   ├── telnet/<mac>_<ip>/
    │   └── recon/file_listings/  # Complete file listings
    ├── scan_results/      # Network scan results
    └── vulnerabilities/   # Nmap vulnerability scan results
```

## Architecture

```
pager_bjorn/
├── payload.sh         # Launcher script (handles exit codes, spinner)
├── bjorn_menu.py      # Graphical startup menu (interface select, clear data)
├── Bjorn.py           # Main entry point
├── display.py         # Pager LCD display (pagerctl, pause menu, payload handoff)
├── launch_pagergotchi.sh  # Handoff launcher for Pagergotchi
├── orchestrator.py    # Task scheduler
├── shared.py          # Shared state & config
├── utils.py           # Web server utilities
├── webapp.py          # HTTP server (web UI + API)
├── pagerctl.py        # Pager hardware interface
├── libpagerctl.so     # Native display library
├── bin/               # Native binaries (MIPS)
│   ├── sfreerdp       # FreeRDP client (auth-only)
│   ├── libssl.so.3    # OpenSSL (sfreerdp dep)
│   └── libcrypto.so.3 # OpenSSL (sfreerdp dep)
├── lib/               # Bundled Python packages
│   ├── paramiko/      # SSH library
│   ├── cryptography/  # Crypto (paramiko dep)
│   ├── getmac/        # MAC address lookup
│   ├── pymysql/       # MySQL client
│   ├── nmap/          # python-nmap
│   ├── smb/           # pysmb
│   └── ...
├── actions/           # Attack modules
│   ├── scanning.py    # Network scanner
│   ├── ftp_connector.py
│   ├── ssh_connector.py
│   ├── telnet_connector.py
│   ├── smb_connector.py
│   ├── rdp_connector.py
│   └── ...
├── config/
│   ├── shared_config.json
│   └── actions.json
├── web/               # Web UI (single-page app)
│   ├── index.html     # SPA shell
│   ├── css/
│   │   └── bjorn.css  # Viking theme
│   ├── scripts/
│   │   ├── app.js     # SPA router & polling manager
│   │   ├── dashboard.js  # Stats + integrated console
│   │   ├── network.js    # Host table + SVG topology
│   │   ├── attacks.js    # Timeline + manual mode
│   │   ├── loot.js       # Credentials, files, logs
│   │   ├── config.js     # Settings editor
│   │   ├── terminal.js   # Device command execution
│   │   └── bjorn.js      # LCD framebuffer mirror
│   └── fonts/
│       └── Viking.TTF
└── resources/
    ├── dictionary/    # Wordlists
    ├── fonts/         # Display fonts
    └── images/        # Viking animations
```

## Clearing Data

Use the **Clear Data** submenu from the graphical startup menu:

| Option | What it clears |
|--------|----------------|
| **Clear Logs** | All log files in `logs/` |
| **Clear Credentials** | Cracked password CSVs in `output/crackedpwd/` |
| **Clear Stolen Data** | Exfiltrated files in `output/data_stolen/` |
| **Clear All** | Everything above plus scan results, vulnerabilities, zombies, archives, netkb, and livestatus |

Each option requires confirmation before proceeding.

## Logging

Logs are stored in `/mmc/root/loot/bjorn/logs/` with one file per module. Default log level is INFO. To enable debug logging, edit the `level=logging.INFO` to `level=logging.DEBUG` in the respective Python files.

View combined logs via the web interface or:
```bash
tail -f /mmc/root/loot/bjorn/logs/*.log
```

---

## Test Targets

A Docker-based vulnerable test environment is provided in `test_targets/`. See [`test_targets/README.md`](test_targets/README.md) for setup and usage.

---

## Troubleshooting

### Bjorn won't start
- Check that the Pager has internet access (required for first run to install dependencies)
- The payload automatically installs Python3 and nmap - check the display for installation progress
- If installation fails, try running the payload again with internet connectivity

### No hosts discovered
- Check that you're connected to an active network
- Verify the target network has hosts
- Check `mac_scan_blacklist` and `ip_scan_blacklist` in config

### Brute force takes too long
- Reduce the dictionary size in `resources/dictionary/`
- Increase `nmap_scan_aggressivity` (e.g., `-T4`)
- Reduce `portlist` to only essential ports

### Web interface not loading
- Verify Bjorn is running (`ps | grep python`)
- Check firewall rules
- Try accessing via the Pager's br-lan IP

---

## TODO / Roadmap

Features planned but not yet implemented:

- **Vulnerability Scanner** - Nmap vuln script integration exists but is disabled. Requires extensive testing before enabling.

---

## Credits

- **Original Bjorn**: [infinition](https://github.com/infinition/Bjorn)
- **Pager Port**: brAinphreAk
- **pagerctl / WiFi Pineapple Pager**: Hak5

## License

MIT License - See [LICENSE](LICENSE)

## Disclaimer

This tool is for authorized security testing and educational purposes only. Only use on networks you own or have explicit permission to test. The authors are not responsible for misuse.
