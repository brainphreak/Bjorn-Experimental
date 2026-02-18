# nmap_vuln_scanner.py
# This script performs vulnerability scanning using Nmap on specified IP addresses.
# It scans for vulnerabilities on various ports and saves the results and progress.

import os
import csv
import subprocess
import logging
import time
import re
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from shared import SharedData
from logger import Logger

logger = Logger(name="nmap_vuln_scanner.py", level=logging.INFO)

b_class = "NmapVulnScanner"
b_module = "nmap_vuln_scanner"
b_status = "vuln_scan"
b_port = None
b_parent = None

class NmapVulnScanner:
    """
    This class handles the Nmap vulnerability scanning process.
    """
    # HTTP ports get batched scanning to avoid MIPS CPU starvation
    HTTP_PORTS = {'80', '443', '8080', '8443'}

    # HTTP vuln scripts split into batches of ~15-20 for MIPS compatibility.
    # Running all 56 concurrently on MIPS produces zero output; batching works.
    HTTP_VULN_BATCHES = [
        # Batch 1: CVE checks (targeted, fast)
        ("CVE checks",
         "http-vuln-cve2006-3392,http-vuln-cve2009-3960,http-vuln-cve2010-0738,"
         "http-vuln-cve2010-2861,http-vuln-cve2011-3192,http-vuln-cve2011-3368,"
         "http-vuln-cve2012-1823,http-vuln-cve2013-0156,http-vuln-cve2013-6786,"
         "http-vuln-cve2013-7091,http-vuln-cve2014-2126,http-vuln-cve2014-2127,"
         "http-vuln-cve2014-2128,http-vuln-cve2014-2129,http-vuln-cve2014-3704,"
         "http-vuln-cve2014-8877,http-vuln-cve2015-1427,http-vuln-cve2015-1635,"
         "http-vuln-cve2017-1001000,http-vuln-cve2017-5638",
         30),  # script-timeout
        # Batch 2: More CVEs + backdoor/device checks
        ("Backdoor and device checks",
         "http-vuln-cve2017-5689,http-vuln-cve2017-8917,http-vuln-misfortune-cookie,"
         "http-vuln-wnr1000-creds,http-shellshock,http-git,http-passwd,"
         "http-dlink-backdoor,http-huawei-hg5xx-vuln,http-tplink-dir-traversal,"
         "http-vmware-path-vuln,http-phpmyadmin-dir-traversal,http-iis-webdav-vuln,"
         "http-frontpage-login,http-adobe-coldfusion-apsa1301,http-avaya-ipoffice-users,"
         "http-awstatstotals-exec,http-axis2-dir-traversal",
         30),
        # Batch 3: Discovery + config checks
        ("Discovery and config checks",
         "http-enum,http-cookie-flags,http-cross-domain-policy,http-trace,"
         "http-internal-ip-disclosure,http-aspnet-debug,http-jsonp-detection,"
         "http-method-tamper,http-litespeed-sourcecode-download,"
         "http-majordomo2-dir-traversal,http-wordpress-users,http-phpself-xss",
         30),
        # Batch 4: Crawlers (heavier, longer timeout)
        ("Crawler checks",
         "http-csrf,http-dombased-xss,http-stored-xss,http-sql-injection,"
         "http-slowloris-check,http-fileupload-exploiter",
         60),
    ]

    def __init__(self, shared_data):
        self.shared_data = shared_data
        self.scan_results = []
        self.summary_file = self.shared_data.vuln_summary_file
        self.create_summary_file()
        logger.debug("NmapVulnScanner initialized.")

    def create_summary_file(self):
        """
        Creates a summary file for vulnerabilities if it does not exist.
        """
        if not os.path.exists(self.summary_file):
            os.makedirs(self.shared_data.vulnerabilities_dir, exist_ok=True)
            with open(self.summary_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["IP", "Hostname", "MAC Address", "Port", "Vulnerabilities"])

    def update_summary_file(self, ip, hostname, mac, port, vulnerabilities):
        """
        Updates the summary file with the scan results.
        """
        try:
            # Read existing data
            rows = []
            if os.path.exists(self.summary_file):
                with open(self.summary_file, 'r', newline='') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)

            # Add new data
            new_row = {"IP": ip, "Hostname": hostname, "MAC Address": mac, "Port": port, "Vulnerabilities": vulnerabilities}
            rows.append(new_row)

            # Remove duplicates based on IP and MAC Address, keeping the last occurrence
            seen = {}
            for row in rows:
                key = (row.get("IP", ""), row.get("MAC Address", ""))
                seen[key] = row
            rows = list(seen.values())

            # Save the updated data back to the summary file
            with open(self.summary_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["IP", "Hostname", "MAC Address", "Port", "Vulnerabilities"])
                writer.writeheader()
                writer.writerows(rows)
        except Exception as e:
            logger.error(f"Error updating summary file: {e}")


    def _run_nmap_scripts(self, ip, port, scripts, script_timeout, batch_timeout, hostname=None):
        """Run a set of nmap scripts against ip:port. Returns (stdout, success)."""
        try:
            cmd = ["nmap", self.shared_data.nmap_scan_aggressivity,
                 "--script", scripts,
                 "--script-timeout", f"{script_timeout}s"]
            if hostname:
                cmd.extend(["--script-args", f"http.host={hostname}"])
            cmd.extend(["-p", port, ip])
            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                timeout=batch_timeout
            )
            return result.stdout, True
        except subprocess.TimeoutExpired:
            return "", False
        except Exception as e:
            logger.error(f"Error running scripts on {ip}:{port}: {e}")
            return "", False

    def _scan_http_port(self, ip, port, hostname=None):
        """Scan an HTTP port using batched scripts to avoid MIPS CPU starvation."""
        combined = ""
        batches_succeeded = 0
        batch_timeout = getattr(self.shared_data, 'vuln_scan_timeout', 120)

        for batch_name, scripts, script_timeout in self.HTTP_VULN_BATCHES:
            if self.shared_data.orchestrator_should_exit:
                break
            logger.info(f"Vuln scanning {ip}:{port} - {batch_name}..." + (f" (Host: {hostname})" if hostname else ""))
            self.shared_data.bjornstatustext2 = f"{ip}:{port} {batch_name}"
            stdout, ok = self._run_nmap_scripts(ip, port, scripts, script_timeout, batch_timeout, hostname=hostname)
            if ok:
                combined += stdout
                batches_succeeded += 1
            else:
                logger.warning(f"Batch '{batch_name}' timeout on {ip}:{port} after {batch_timeout}s")

        return combined, batches_succeeded > 0

    def _scan_regular_port(self, ip, port):
        """Scan a non-HTTP port with --script vuln in a single call."""
        port_timeout = getattr(self.shared_data, 'vuln_scan_timeout', 120)
        logger.info(f"Vuln scanning {ip} port {port}...")
        stdout, ok = self._run_nmap_scripts(ip, port, "vuln", 30, port_timeout)
        if not ok:
            logger.warning(f"Vuln scan timeout on {ip}:{port} after {port_timeout}s, moving to next port")
        return stdout, ok

    def scan_vulnerabilities(self, ip, hostname, mac, ports):
        combined_result = ""
        all_vulnerabilities = []
        all_details = []
        ports_succeeded = 0

        self.shared_data.bjornstatustext2 = ip
        logger.info(f"Scanning {ip} on {len(ports)} ports for vulnerabilities with aggressivity {self.shared_data.nmap_scan_aggressivity}")

        for port in ports:
            if self.shared_data.orchestrator_should_exit:
                break

            # HTTP ports use batched scanning with optional Host header for vhosts
            if port in self.HTTP_PORTS:
                stdout, ok = self._scan_http_port(ip, port, hostname=hostname if hostname else None)
            else:
                stdout, ok = self._scan_regular_port(ip, port)

            if ok:
                combined_result += stdout
                ports_succeeded += 1

                vulns = self.parse_vulnerabilities(stdout)
                if vulns:
                    all_vulnerabilities.append(vulns)
                    logger.info(f"Vulnerabilities found on {ip}:{port}: {vulns}")

                details = self.parse_vulnerability_details(stdout)
                if details:
                    all_details.extend(details)

        # Save combined results from all ports that completed
        if ports_succeeded > 0:
            merged_vulns = "; ".join(all_vulnerabilities) if all_vulnerabilities else ""
            scanned_ports = ",".join(ports)
            if merged_vulns:
                logger.info(f"All vulnerabilities on {ip}: {merged_vulns}")
            else:
                logger.info(f"No vulnerabilities found on {ip}")
            self.update_summary_file(ip, hostname, mac, scanned_ports, merged_vulns)
            self.save_vulnerability_details(mac, ip, all_details)
            return combined_result
        else:
            logger.warning(f"All ports timed out or failed for {ip}")
            return None

    def execute(self, ip, row, status_key):
        """
        Executes the vulnerability scan for a given IP and row data.
        """
        start_time = time.time()
        logger.lifecycle_start("NmapVulnScanner", ip)
        self.shared_data.bjornorch_status = "NmapVulnScanner"
        ports = row["Ports"].split(";")
        try:
            scan_result = self.scan_vulnerabilities(ip, row["Hostnames"], row["MAC Address"], ports)

            if scan_result is not None:
                self.scan_results.append((ip, row["Hostnames"], row["MAC Address"]))
                self.save_results(row["MAC Address"], ip, scan_result)
                status = 'success'
            else:
                status = 'failed'
        except Exception as e:
            logger.error(f"Error during vulnerability scan for {ip}: {e}")
            status = 'failed'
        finally:
            duration = time.time() - start_time
            logger.lifecycle_end("NmapVulnScanner", status, duration, ip)
        return status

    def parse_vulnerabilities(self, scan_result):
        """
        Parses Nmap --script vuln output to extract confirmed vulnerabilities.
        Output format has NSE script blocks like:
            | smb-vuln-ms17-010:
            |   VULNERABLE:
            |     State: VULNERABLE
            |     IDs:  CVE:CVE-2017-0143
        For each vulnerable script block, stores CVE IDs if present,
        otherwise falls back to the script name.
        """
        vulnerabilities = set()
        current_script = None
        current_cves = set()
        is_vulnerable = False

        def save_block():
            if current_script and is_vulnerable:
                if current_cves:
                    vulnerabilities.update(current_cves)
                else:
                    vulnerabilities.add(current_script)

        for line in scan_result.splitlines():
            # Match NSE script name header: "| script-name:" (require hyphen to
            # avoid matching indented properties like State:, IDs:, Description:)
            m = re.match(r'^\|\s+([\w][\w-]*-[\w][\w-]*)\s*:', line)
            if m:
                save_block()
                current_script = m.group(1)
                current_cves = set()
                is_vulnerable = False

            # "State: VULNERABLE" or "State: LIKELY VULNERABLE" confirms a finding
            if re.search(r'State:\s+(LIKELY\s+)?VULNERABLE', line):
                is_vulnerable = True

            # Collect CVE IDs from confirmed vulnerable sections
            if is_vulnerable:
                for cve in re.findall(r'CVE-\d{4}-\d+', line):
                    current_cves.add(cve)

        save_block()

        return "; ".join(sorted(vulnerabilities))

    def parse_vulnerability_details(self, scan_result):
        """
        Parse structured vulnerability details from nmap --script vuln output.
        Returns list of findings with port, service, title, state, CVEs, description.
        """
        findings = []
        current_port = None
        current_service = None

        # First pass: collect all script blocks with their port context
        lines = scan_result.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]

            # Track current port/service
            port_match = re.match(r'^(\d+/\w+)\s+\w+\s+(\S+)', line)
            if port_match:
                current_port = port_match.group(1)
                current_service = port_match.group(2)
                i += 1
                continue

            if 'Host script results:' in line:
                current_port = 'host'
                current_service = None
                i += 1
                continue

            # Script header
            script_match = re.match(r'^\|\s+([\w][\w-]*-[\w][\w-]*)\s*:', line)
            if script_match:
                script_name = script_match.group(1)
                # Collect block lines until next script or end of NSE output
                block_lines = []
                i += 1
                while i < len(lines):
                    l = lines[i]
                    # Stop at next port line, Host script results, or non-NSE line
                    if re.match(r'^\d+/\w+\s+\w+', l) or 'Host script results:' in l:
                        break
                    # Stop at next script header (but not |_ single-line results)
                    if re.match(r'^\|\s+([\w][\w-]*-[\w][\w-]*)\s*:', l):
                        break
                    if not l.startswith('|'):
                        break
                    block_lines.append(l)
                    i += 1

                finding = self._parse_vuln_block(script_name, block_lines,
                                                  current_port, current_service)
                if finding:
                    findings.append(finding)
                continue

            i += 1

        return findings

    def _parse_vuln_block(self, script_name, block_lines, port, service):
        """Parse a single NSE script block. Returns a finding dict or None."""
        state = ''
        title = ''
        cves = []
        risk = ''
        desc_lines = []
        disclosure = ''
        refs = []
        in_refs = False
        got_title = False

        for line in block_lines:
            # Strip the leading |/|_ and whitespace
            stripped = re.sub(r'^\|[_ ]?\s*', '', line).strip()

            # State line
            state_match = re.search(r'State:\s+((?:LIKELY\s+)?VULNERABLE)', line)
            if state_match:
                state = state_match.group(1)
                in_refs = False
                continue

            # Skip the VULNERABLE: header line itself
            if stripped in ('VULNERABLE:', 'LIKELY VULNERABLE:'):
                continue

            # Skip NOT VULNERABLE
            if 'NOT VULNERABLE' in stripped:
                return None

            # CVE IDs
            found_cves = re.findall(r'CVE-\d{4}-\d+', line)
            if found_cves:
                cves.extend(found_cves)
                continue

            # IDs line without CVE
            if stripped.startswith('IDs:'):
                continue

            # Risk factor
            risk_match = re.match(r'Risk factor:\s*(.+)', stripped)
            if risk_match:
                risk = risk_match.group(1).strip()
                in_refs = False
                continue

            # Disclosure date
            date_match = re.match(r'Disclosure date:\s*(.+)', stripped)
            if date_match:
                disclosure = date_match.group(1).strip()
                in_refs = False
                continue

            # References section
            if stripped == 'References:':
                in_refs = True
                continue

            if in_refs and ('http://' in stripped or 'https://' in stripped):
                refs.append(stripped)
                continue

            # Skip State/property lines we already handled
            if any(stripped.startswith(kw) for kw in ('State:', 'IDs:', 'Risk factor:',
                                                       'Disclosure date:', 'References:')):
                continue

            # Title — first meaningful line
            if not got_title and stripped:
                title = stripped
                got_title = True
                continue

            # Description — lines between title and structured fields
            if got_title and not in_refs and stripped:
                desc_lines.append(stripped)

        if not state:
            return None

        return {
            'port': port or '',
            'service': service or '',
            'script': script_name,
            'title': title,
            'state': state,
            'cves': list(set(cves)),
            'risk': risk,
            'description': ' '.join(desc_lines),
            'disclosure_date': disclosure,
            'references': refs
        }

    def save_vulnerability_details(self, mac_address, ip, details):
        """Save structured vulnerability details as JSON."""
        try:
            sanitized_mac = mac_address.replace(":", "")
            result_dir = self.shared_data.vulnerabilities_dir
            os.makedirs(result_dir, exist_ok=True)
            json_file = os.path.join(result_dir, f"{sanitized_mac}_{ip}_vuln_details.json")
            with open(json_file, 'w') as f:
                json.dump(details, f, indent=2)
            if details:
                logger.info(f"Vulnerability details saved to {json_file}")
        except Exception as e:
            logger.error(f"Error saving vulnerability details for {ip}: {e}")

    def save_results(self, mac_address, ip, scan_result):
        """
        Saves the detailed scan results to a file.
        """
        try:
            sanitized_mac_address = mac_address.replace(":", "")
            result_dir = self.shared_data.vulnerabilities_dir
            os.makedirs(result_dir, exist_ok=True)
            result_file = os.path.join(result_dir, f"{sanitized_mac_address}_{ip}_vuln_scan.txt")

            # Open the file in write mode to clear its contents if it exists, then close it
            if os.path.exists(result_file):
                open(result_file, 'w').close()

            # Write the new scan result to the file
            with open(result_file, 'w') as file:
                file.write(scan_result)

            logger.info(f"Results saved to {result_file}")
        except Exception as e:
            logger.error(f"Error saving scan results for {ip}: {e}")


    def save_summary(self):
        """
        Saves a summary of all scanned vulnerabilities to a final summary file.
        """
        try:
            final_summary_file = os.path.join(self.shared_data.vulnerabilities_dir, "final_vulnerability_summary.csv")

            # Read existing data
            rows = []
            if os.path.exists(self.summary_file):
                with open(self.summary_file, 'r', newline='') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)

            # Group by IP, Hostname, MAC Address and combine vulnerabilities
            grouped = {}
            for row in rows:
                key = (row.get("IP", ""), row.get("Hostname", ""), row.get("MAC Address", ""))
                if key not in grouped:
                    grouped[key] = set()
                vulns = row.get("Vulnerabilities", "")
                if vulns:
                    for v in vulns.split("; "):
                        if v.strip():
                            grouped[key].add(v.strip())

            # Write summary
            with open(final_summary_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["IP", "Hostname", "MAC Address", "Vulnerabilities"])
                for (ip, hostname, mac), vulns in grouped.items():
                    writer.writerow([ip, hostname, mac, "; ".join(vulns)])

            logger.info(f"Summary saved to {final_summary_file}")
        except Exception as e:
            logger.error(f"Error saving summary: {e}")

if __name__ == "__main__":
    shared_data = SharedData()
    try:
        nmap_vuln_scanner = NmapVulnScanner(shared_data)
        logger.info("Starting vulnerability scans...")

        # Load the netkbfile and get the IPs to scan
        ips_to_scan = shared_data.read_data()  # Use your existing method to read the data

        # Execute the scan on each IP with concurrency
        total = len(ips_to_scan)
        completed = 0
        futures = []
        with ThreadPoolExecutor(max_workers=2) as executor:  # Adjust the number of workers for RPi Zero
            for row in ips_to_scan:
                if row["Alive"] == '1':  # Check if the host is alive
                    ip = row["IPs"]
                    futures.append(executor.submit(nmap_vuln_scanner.execute, ip, row, b_status))

            # Use timeout on as_completed to prevent infinite blocking
            for future in as_completed(futures, timeout=1800):  # 30 minute total timeout
                try:
                    future.result(timeout=600)  # 10 minute timeout per scan
                except FuturesTimeoutError:
                    logger.warning("Scan timed out")
                except Exception as e:
                    logger.error(f"Scan error: {e}")
                completed += 1
                logger.info(f"Scanning vulnerabilities... {completed}/{len(futures)}")

        nmap_vuln_scanner.save_summary()
        logger.info(f"Total scans performed: {len(nmap_vuln_scanner.scan_results)}")
        exit(len(nmap_vuln_scanner.scan_results))
    except FuturesTimeoutError:
        logger.error("Overall vulnerability scanning timed out after 30 minutes")
    except Exception as e:
        logger.error(f"Error: {e}")
