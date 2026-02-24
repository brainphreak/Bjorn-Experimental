#display.py
# Description:
# Pager LCD display module for Bjorn - matches original Bjorn layout.
# Portrait orientation (222x480) scaled from original (122x250).

import threading
import time
import os
import sys
import signal
import logging
import random
import glob
import subprocess
import csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pagerctl import Pager
from init_shared import shared_data
from comment import Commentaireia
from logger import Logger

logger = Logger(name="display.py", level=logging.INFO)

PAYLOAD_DIR = os.path.dirname(os.path.abspath(__file__))


def discover_launchers():
    """Scan PAYLOAD_DIR for launch_*.sh scripts with valid # Requires: paths.
    Returns list of (title, path) tuples. Skips self-launchers (launch_bjorn.sh)."""
    launchers = []
    pattern = os.path.join(PAYLOAD_DIR, 'launch_*.sh')
    matches = sorted(glob.glob(pattern))
    logger.info(f"discover_launchers: PAYLOAD_DIR={PAYLOAD_DIR} pattern={pattern} matches={matches}")
    for path in matches:
        basename = os.path.basename(path)
        if basename == 'launch_bjorn.sh':
            continue
        title = None
        requires = None
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('# Title:'):
                        title = line[len('# Title:'):].strip()
                    elif line.startswith('# Requires:'):
                        requires = line[len('# Requires:'):].strip()
                    if title and requires:
                        break
        except Exception as e:
            logger.error(f"discover_launchers: error reading {path}: {e}")
            continue
        logger.info(f"discover_launchers: {basename} title={title} requires={requires} isdir={os.path.isdir(requires) if requires else 'N/A'}")
        if not title:
            continue
        if requires and not os.path.isdir(requires):
            continue
        launchers.append((title, path))
    logger.info(f"discover_launchers: returning {launchers}")
    return launchers


class Display:
    """Pager display - matches original Bjorn layout."""

    def __init__(self, shared_data):
        self.shared_data = shared_data
        self.config = self.shared_data.config
        self.shared_data.bjornstatustext2 = "Awakening..."
        self.commentaire_ia = Commentaireia()
        self.semaphore = threading.Semaphore(10)

        # Initialize pagerctl
        try:
            logger.info("Initializing pagerctl display...")
            self.pager = Pager()
            self.pager.init()
            self.pager.set_rotation(0)  # Portrait 222x480

            self.width = self.pager.width    # 222
            self.height = self.pager.height  # 480
            logger.info(f"Pager display initialized: {self.width}x{self.height}")

            self.shared_data.width = self.width
            self.shared_data.height = self.height

        except Exception as e:
            logger.error(f"Error initializing pagerctl: {e}")
            raise

        # Colors from theme (bg, text, accent) with hardcoded fallbacks
        bg = self.shared_data.theme_bg_color
        txt = self.shared_data.theme_text_color
        acc = self.shared_data.theme_accent_color
        self.BG_COLOR = self.pager.rgb(bg[0], bg[1], bg[2])
        self.TEXT_COLOR = self.pager.rgb(txt[0], txt[1], txt[2])
        self.ACCENT_COLOR = self.pager.rgb(acc[0], acc[1], acc[2])
        # Keep BLACK/WHITE for menu dialogs (always white-on-black)
        self.BLACK = self.pager.BLACK
        self.WHITE = self.pager.WHITE

        # Fonts
        self.font_arial = self.shared_data.font_arial_path
        self.font_viking = self.shared_data.font_viking_path

        # Scale factors (original 122x250 -> pager 222x480)
        self.sx = self.width / 122.0   # ~1.82
        self.sy = self.height / 250.0  # ~1.92

        # Current animation frame
        self.main_image_path = None
        self.manual_mode_txt = "M" if self.shared_data.manual_mode else "A"
        self.last_led_status = None
        self.dialog_showing = False  # Flag to pause display updates during dialogs

        # Brightness/dim settings
        self.screen_brightness = getattr(self.shared_data, 'screen_brightness', 80)
        self.screen_dim_brightness = getattr(self.shared_data, 'screen_dim_brightness', 20)
        self.screen_dim_timeout = getattr(self.shared_data, 'screen_dim_timeout', 60)
        self.last_activity_time = time.time()
        self.is_dimmed = False

        # Set initial brightness
        try:
            self.pager.set_brightness(self.screen_brightness)
            logger.info(f"Screen brightness set to {self.screen_brightness}%")
        except Exception as e:
            logger.debug(f"Could not set brightness: {e}")

        self.start_threads()
        logger.info("Display initialization complete.")

    def start_threads(self):
        threading.Thread(target=self.update_main_image, daemon=True).start()
        threading.Thread(target=self.schedule_update_shared_data, daemon=True).start()
        threading.Thread(target=self.schedule_update_vuln_count, daemon=True).start()
        threading.Thread(target=self.handle_input_loop, daemon=True).start()

    def update_main_image(self):
        while not self.shared_data.display_should_exit:
            try:
                self.shared_data.update_image_randomizer()
                if self.shared_data.current_image_path:
                    self.main_image_path = self.shared_data.current_image_path
                delay = random.uniform(
                    self.shared_data.image_display_delaymin,
                    self.shared_data.image_display_delaymax
                )
                time.sleep(delay)
            except Exception as e:
                logger.error(f"Error in update_main_image: {e}")
                time.sleep(1)

    def schedule_update_shared_data(self):
        while not self.shared_data.display_should_exit:
            self.update_shared_data()
            time.sleep(25)

    def schedule_update_vuln_count(self):
        while not self.shared_data.display_should_exit:
            self.update_vuln_count()
            time.sleep(30)

    def wake_screen(self):
        """Wake screen from dim state."""
        if self.is_dimmed:
            try:
                self.pager.set_brightness(self.screen_brightness)
                self.is_dimmed = False
                logger.debug("Screen woken from dim")
            except Exception as e:
                logger.debug(f"Could not wake screen: {e}")
        self.last_activity_time = time.time()

    def dim_screen(self):
        """Dim the screen to save battery."""
        if not self.is_dimmed:
            try:
                self.pager.set_brightness(self.screen_dim_brightness)
                self.is_dimmed = True
                logger.debug("Screen dimmed")
            except Exception as e:
                logger.debug(f"Could not dim screen: {e}")

    def check_dim_timeout(self):
        """Check if screen should be dimmed due to inactivity."""
        if self.screen_dim_timeout > 0 and not self.is_dimmed:
            if time.time() - self.last_activity_time > self.screen_dim_timeout:
                self.dim_screen()

    def handle_input_loop(self):
        """Handle button input - Red button shows pause menu."""
        logger.info("Input handler: Monitoring for button presses")
        while not self.shared_data.display_should_exit:
            try:
                # Wait for button press (blocking)
                button = self.pager.wait_button()

                # Any button press wakes the screen and resets activity timer
                self.wake_screen()

                # Red button (B) - show pause menu
                if button & self.pager.BTN_B:
                    logger.info("Red button pressed - showing pause menu")
                    action = self.show_exit_confirmation()
                    if action is None:
                        logger.info("Back to scanning")
                        continue
                    logger.info(f"Menu action: exit code {action}")
                    self.shared_data.should_exit = True
                    self.shared_data.display_should_exit = True
                    self.shared_data.orchestrator_should_exit = True
                    if action == 42:
                        # Write .next_payload for handoff
                        data_dir = os.path.join(PAYLOAD_DIR, 'data')
                        os.makedirs(data_dir, exist_ok=True)
                        next_payload_path = os.path.join(data_dir, '.next_payload')
                        with open(next_payload_path, 'w') as f:
                            f.write(self._handoff_launcher_path)
                        logger.info(f"Wrote .next_payload: {self._handoff_launcher_path}")
                    self.cleanup()
                    # Kill any running nmap subprocesses before exit
                    try:
                        subprocess.run(['killall', 'nmap'], capture_output=True, timeout=5)
                    except Exception:
                        pass
                    os._exit(action)
            except Exception as e:
                logger.error(f"Error in input handler: {e}")
                time.sleep(1.0)

    def show_exit_confirmation(self):
        """Show pause menu with brightness control and exit options.
        Returns: None=back, 99=main menu, 42=launcher handoff, 0=exit bjorn."""
        # Pause display updates while dialog is showing
        self.dialog_showing = True
        time.sleep(0.2)  # Let current render finish

        # Get current brightness
        current_brightness = self.pager.get_brightness()
        if current_brightness < 0:
            current_brightness = self.screen_brightness

        # Build options list: BACK + Main Menu + launchers + Exit Bjorn
        # Each option: (label, color, action)
        green_color = self.pager.rgb(0, 150, 0)
        yellow_color = self.pager.rgb(180, 150, 0)
        blue_color = self.pager.rgb(50, 100, 220)
        red_color = self.pager.rgb(200, 0, 0)

        options = [
            ("BACK", green_color, None),
            ("Main Menu", yellow_color, 99),
        ]

        launchers = discover_launchers()
        for title, path in launchers:
            options.append((f"> {title}", blue_color, (42, path)))

        options.append((f"Exit {self.shared_data.display_name}", red_color, 0))

        num_options = len(options)
        selected = 0

        def draw_menu():
            self.pager.fill_rect(0, 0, self.width, self.height, self.BG_COLOR)

            # Draw dialog box
            box_y = int(self.height * 0.10)
            box_h = int(self.height * 0.80)
            self.pager.fill_rect(10, box_y, self.width - 20, box_h, self.BG_COLOR)
            self.pager.rect(10, box_y, self.width - 20, box_h, self.TEXT_COLOR)
            self.pager.rect(12, box_y + 2, self.width - 24, box_h - 4, self.TEXT_COLOR)

            # Title
            title_y = box_y + 15
            self.pager.draw_ttf_centered(title_y, "MENU", self.TEXT_COLOR, self.font_viking, int(12 * self.sy))

            # Brightness section
            bright_y = box_y + int(30 * self.sy)
            self.pager.draw_ttf_centered(bright_y, "BRIGHTNESS", self.TEXT_COLOR, self.font_arial, int(9 * self.sy))

            # Brightness bar
            bar_y = bright_y + int(22 * self.sy)
            bar_x = 30
            bar_w = self.width - 60
            bar_h = int(12 * self.sy)

            # Bar background
            self.pager.fill_rect(bar_x, bar_y, bar_w, bar_h, self.ACCENT_COLOR)
            # Bar fill
            fill_w = int(bar_w * current_brightness / 100)
            self.pager.fill_rect(bar_x, bar_y, fill_w, bar_h, self.TEXT_COLOR)
            # Bar outline
            self.pager.rect(bar_x, bar_y, bar_w, bar_h, self.TEXT_COLOR)

            # Brightness percentage
            pct_y = bar_y + bar_h + 5
            self.pager.draw_ttf_centered(pct_y, f"{current_brightness}%", self.TEXT_COLOR, self.font_arial, int(10 * self.sy))

            # Menu buttons - stack vertically
            btn_w = 120
            btn_h = 28
            btn_x = (self.width - btn_w) // 2
            btn_gap = 8
            font_size = int(8 * self.sy)

            # Start buttons below the brightness percentage
            first_btn_y = pct_y + int(18 * self.sy)

            for i, (label, color, _action) in enumerate(options):
                btn_y = first_btn_y + i * (btn_h + btn_gap)

                if i == selected:
                    # Draw selection highlight
                    self.pager.fill_rect(btn_x - 4, btn_y - 4, btn_w + 8, btn_h + 8, self.TEXT_COLOR)

                self.pager.fill_rect(btn_x, btn_y, btn_w, btn_h, color)

                # Center text in button
                text_w = self.pager.ttf_width(label, self.font_arial, font_size)
                text_x = btn_x + (btn_w - text_w) // 2
                text_y = btn_y + (btn_h - font_size) // 2
                self.pager.draw_ttf(text_x, text_y, label, self.BG_COLOR, self.font_arial, font_size)

            self.pager.flip()

        draw_menu()

        # Handle input
        while True:
            button = self.pager.wait_button()

            if button & self.pager.BTN_DOWN:
                # Physical DOWN = Visual LEFT = Decrease brightness
                current_brightness = max(20, current_brightness - 10)
                self.pager.set_brightness(current_brightness)
                self.screen_brightness = current_brightness
                draw_menu()
            elif button & self.pager.BTN_UP:
                # Physical UP = Visual RIGHT = Increase brightness
                current_brightness = min(100, current_brightness + 10)
                self.pager.set_brightness(current_brightness)
                self.screen_brightness = current_brightness
                draw_menu()
            elif button & self.pager.BTN_LEFT:
                # Physical LEFT = Visual UP = Move selection up
                selected = (selected - 1) % num_options
                draw_menu()
            elif button & self.pager.BTN_RIGHT:
                # Physical RIGHT = Visual DOWN = Move selection down
                selected = (selected + 1) % num_options
                draw_menu()
            elif button & self.pager.BTN_A:  # Green = confirm selection
                self.dialog_showing = False
                action = options[selected][2]
                if action is None:
                    return None  # BACK
                elif isinstance(action, tuple):
                    # Launcher handoff: (42, path)
                    self._handoff_launcher_path = action[1]
                    return 42
                else:
                    return action  # 99 or 0
            elif button & self.pager.BTN_B:  # Red = always go back
                self.dialog_showing = False
                return None

    def update_vuln_count(self):
        with self.semaphore:
            try:
                if not os.path.exists(self.shared_data.vuln_summary_file):
                    with open(self.shared_data.vuln_summary_file, 'w', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(["IP", "Hostname", "MAC Address", "Port", "Vulnerabilities"])
                    self.shared_data.vulnnbr = 0
                else:
                    with open(self.shared_data.vuln_summary_file, 'r') as file:
                        reader = csv.DictReader(file)
                        total_vulns = 0
                        for row in reader:
                            vulnerabilities = row.get("Vulnerabilities", "").strip()
                            if vulnerabilities:
                                total_vulns += len([v for v in vulnerabilities.split("; ") if v.strip()])
                        self.shared_data.vulnnbr = total_vulns
            except Exception as e:
                logger.error(f"Error in update_vuln_count: {e}")

    def update_shared_data(self):
        with self.semaphore:
            try:
                if os.path.exists(self.shared_data.livestatusfile):
                    with open(self.shared_data.livestatusfile, 'r') as file:
                        reader = csv.DictReader(file)
                        for row in reader:
                            self.shared_data.portnbr = int(row.get('Total Open Ports', 0) or 0)
                            self.shared_data.targetnbr = int(row.get('Alive Hosts Count', 0) or 0)
                            self.shared_data.networkkbnbr = int(row.get('All Known Hosts Count', 0) or 0)
                            break

                crackedpw_files = glob.glob(f"{self.shared_data.crackedpwddir}/*.csv")
                total_passwords = 0
                for filepath in crackedpw_files:
                    try:
                        with open(filepath, 'r') as f:
                            reader = csv.reader(f)
                            next(reader, None)
                            total_passwords += sum(1 for _ in reader)
                    except:
                        pass
                self.shared_data.crednbr = total_passwords

                total_data = sum([len(files) for r, d, files in os.walk(self.shared_data.datastolendir)])
                self.shared_data.datanbr = total_data

                total_zombies = sum([len(files) for r, d, files in os.walk(self.shared_data.zombiesdir)])
                self.shared_data.zombiesnbr = total_zombies

                # attacksnbr is incremented by orchestrator when attacks are performed
                # Don't count action module files here - that's not attacks performed

                self.shared_data.update_stats()
                self.shared_data.manual_mode = self.is_manual_mode()
                self.manual_mode_txt = "M" if self.shared_data.manual_mode else "A"
                self.shared_data.wifi_connected = self.is_wifi_connected()

            except FileNotFoundError as e:
                logger.debug(f"Data file not ready: {e}")
            except Exception as e:
                logger.error(f"Error updating shared data: {e}")

    def display_comment(self, status):
        comment = self.commentaire_ia.get_commentaire(status)
        if comment:
            self.shared_data.bjornsay = comment
            self.shared_data.bjornstatustext = self.shared_data.bjornorch_status

    def is_wifi_connected(self):
        try:
            result = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, timeout=5)
            return bool(result.stdout.strip())
        except:
            return False

    def is_manual_mode(self):
        return self.shared_data.manual_mode

    def update_leds(self, status):
        if status == self.last_led_status:
            return
        self.last_led_status = status
        try:
            if status == "IDLE":
                self.pager.led_dpad("up", 0x000033)
                self.pager.led_dpad("down", 0x000033)
                self.pager.led_dpad("left", 0x000033)
                self.pager.led_dpad("right", 0x000033)
            elif "Scanner" in status or "Scan" in status:
                self.pager.led_dpad("up", 0x00FFFF)
                self.pager.led_dpad("down", 0x003333)
                self.pager.led_dpad("left", 0x003333)
                self.pager.led_dpad("right", 0x00FFFF)
            elif "Bruteforce" in status:
                self.pager.led_dpad("up", 0xFF0000)
                self.pager.led_dpad("down", 0xFF0000)
                self.pager.led_dpad("left", 0x330000)
                self.pager.led_dpad("right", 0x330000)
            elif "Steal" in status:
                self.pager.led_dpad("up", 0xFFFF00)
                self.pager.led_dpad("down", 0x333300)
                self.pager.led_dpad("left", 0xFFFF00)
                self.pager.led_dpad("right", 0x333300)
            else:
                self.pager.led_dpad("up", 0x00FF00)
                self.pager.led_dpad("down", 0x003300)
                self.pager.led_dpad("left", 0x003300)
                self.pager.led_dpad("right", 0x00FF00)
        except Exception as e:
            logger.debug(f"LED update error: {e}")

    def _wrap_text_pixel(self, text, font_path, font_size, max_width):
        """Wrap text based on actual pixel width using ttf_width."""
        words = text.split()
        lines = []
        line = ''
        for word in words:
            test = line + (' ' if line else '') + word
            if self.pager.ttf_width(test, font_path, font_size) <= max_width:
                line = test
            else:
                if line:
                    lines.append(line)
                # If a single word is wider than max, just add it anyway
                line = word
        if line:
            lines.append(line)
        return lines

    def sanitize_text(self, text):
        """Fix encoding issues with special characters."""
        if not text:
            return text
        # Replace smart quotes and apostrophes with ASCII equivalents
        replacements = {
            '\u2018': "'",  # Left single quote
            '\u2019': "'",  # Right single quote (apostrophe)
            '\u201c': '"',  # Left double quote
            '\u201d': '"',  # Right double quote
            '\u2013': '-',  # En dash
            '\u2014': '-',  # Em dash
            '\u2026': '...', # Ellipsis
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def draw_icon(self, x, y, icon_name):
        """Draw icon from static images."""
        icon_path = self.shared_data.static_images.get(icon_name)
        if icon_path and os.path.exists(icon_path):
            try:
                self.pager.draw_image_file(x, y, icon_path)
                return True
            except Exception as e:
                logger.debug(f"Could not draw icon {icon_name}: {e}")
        return False

    def draw_icon_scaled(self, x, y, w, h, icon_name):
        """Draw icon scaled to size."""
        icon_path = self.shared_data.static_images.get(icon_name)
        if icon_path and os.path.exists(icon_path):
            try:
                self.pager.draw_image_file_scaled(x, y, w, h, icon_path)
                return True
            except Exception as e:
                logger.debug(f"Could not draw scaled icon {icon_name}: {e}")
        return False

    def draw_header(self):
        """Header: centered theme title."""
        y = 0
        h = int(20 * self.sy)  # ~38px

        self.pager.fill_rect(0, y, self.width, h, self.BG_COLOR)
        self.pager.hline(0, h - 1, self.width, self.TEXT_COLOR)

        # Center: theme title
        title_font_size = int(14 * self.sy)
        self.pager.draw_ttf_centered(int(5 * self.sy), self.shared_data.display_name, self.TEXT_COLOR, self.font_viking, title_font_size)

    def draw_stats_grid(self):
        """3x2 stats grid with icons and BIG numbers."""
        y_start = int(22 * self.sy)
        h = int(40 * self.sy)

        self.pager.fill_rect(0, y_start, self.width, h, self.BG_COLOR)
        self.pager.rect(0, y_start, self.width, h, self.TEXT_COLOR)

        col_w = self.width // 3
        row_h = h // 2

        # Stats: (icon, value)
        stats = [
            [('target', self.shared_data.targetnbr),
             ('port', self.shared_data.portnbr),
             ('vuln', self.shared_data.vulnnbr)],
            [('cred', self.shared_data.crednbr),
             ('zombie', self.shared_data.zombiesnbr),
             ('data', self.shared_data.datanbr)],
        ]

        icon_size = int(16 * self.sy)
        font_size = int(12 * self.sy)  # Big numbers

        for row_idx, row in enumerate(stats):
            for col_idx, (icon_name, value) in enumerate(row):
                cx = col_idx * col_w
                cy = y_start + row_idx * row_h

                # Icon
                icon_x = cx + 4
                icon_y = cy + (row_h - icon_size) // 2
                self.draw_icon_scaled(icon_x, icon_y, icon_size, icon_size, icon_name)

                # Number (big)
                text_x = icon_x + icon_size + 4
                text_y = cy + (row_h - font_size) // 2
                self.pager.draw_ttf(text_x, text_y, str(value), self.TEXT_COLOR, self.font_arial, font_size)

        # Grid lines
        for i in range(1, 3):
            self.pager.vline(i * col_w, y_start, h, self.TEXT_COLOR)
        self.pager.hline(0, y_start + row_h, self.width, self.TEXT_COLOR)

    def draw_status_area(self):
        """Status: action icon + status text (LARGE)."""
        y_start = int(62 * self.sy)
        h = int(28 * self.sy)

        self.pager.fill_rect(0, y_start, self.width, h, self.BG_COLOR)
        self.pager.rect(0, y_start, self.width, h, self.TEXT_COLOR)

        # Status icon (larger)
        icon_size = int(24 * self.sy)
        icon_x = 6
        icon_y = y_start + (h - icon_size) // 2

        if self.shared_data.bjornstatusimage_path and os.path.exists(self.shared_data.bjornstatusimage_path):
            try:
                self.pager.draw_image_file_scaled(icon_x, icon_y, icon_size, icon_size,
                                                   self.shared_data.bjornstatusimage_path)
            except:
                pass

        # Status text (auto-sized to fit available width)
        text_x = icon_x + icon_size + 8
        max_text_w = self.width - text_x - 4
        main_font = int(12 * self.sy)
        sub_font = int(10 * self.sy)

        status_text = self.shared_data.bjornstatustext
        # Shrink font until text fits
        font_size = main_font
        while font_size > 10 and self.pager.ttf_width(status_text, self.font_arial, font_size) > max_text_w:
            font_size -= 1
        self.pager.draw_ttf(text_x, y_start + 4, status_text, self.TEXT_COLOR, self.font_arial, font_size)

        status_text2 = self.shared_data.bjornstatustext2
        font_size2 = sub_font
        while font_size2 > 8 and self.pager.ttf_width(status_text2, self.font_arial, font_size2) > max_text_w:
            font_size2 -= 1
        self.pager.draw_ttf(text_x, y_start + 4 + main_font + 2, status_text2, self.ACCENT_COLOR, self.font_arial, font_size2)

    def draw_dialogue_zone(self):
        """Viking speech - VERY LARGE text."""
        y_start = int(90 * self.sy)
        h = int(70 * self.sy)

        self.pager.fill_rect(0, y_start, self.width, h, self.BG_COLOR)
        self.pager.rect(0, y_start, self.width, h, self.TEXT_COLOR)

        # Dialogue text - pixel-based wrapping for proportional fonts
        font_size = int(12 * self.sy)
        line_height = int(14 * self.sy)
        text_x = 8
        max_w = self.width - text_x * 2  # margins on both sides

        text_y = y_start + 8
        if hasattr(self.shared_data, 'bjornsay') and self.shared_data.bjornsay:
            clean_text = self.sanitize_text(self.shared_data.bjornsay)
            lines = self._wrap_text_pixel(clean_text, self.font_arial, font_size, max_w)
            for i, line in enumerate(lines[:4]):  # Max 4 lines
                self.pager.draw_ttf(text_x, text_y + i * line_height, line, self.TEXT_COLOR, self.font_arial, font_size)

    def draw_frise(self):
        """Celtic knot ribbon - BELOW dialogue, FULL WIDTH."""
        # Position below dialogue zone - moved up a few pixels
        y = int(155 * self.sy)

        frise_path = self.shared_data.static_images.get('frise')
        if frise_path and os.path.exists(frise_path):
            try:
                # Scale to full width
                frise_h = int(12 * self.sy)
                self.pager.draw_image_file_scaled(0, y, self.width, frise_h, frise_path)
            except:
                # Fallback: draw a decorative line
                self.pager.hline(0, y + 5, self.width, self.TEXT_COLOR)
                self.pager.hline(0, y + 7, self.width, self.TEXT_COLOR)

    def draw_character_and_corner_stats(self):
        """Viking character in center with stats in corners around it."""
        # Character area starts after frise - moved up to prevent bottom cutoff
        char_top = int(175 * self.sy)
        char_bottom = self.height - 25  # More margin from bottom

        # Character dimensions and position (centered) - made smaller to not overlap frise
        char_w = int(70 * self.sx)  # Reduced from 80
        char_h = int(80 * self.sy)  # Reduced from 90
        char_x = (self.width - char_w) // 2
        char_y = char_top + (char_bottom - char_top - char_h) // 2

        # Draw character
        if self.main_image_path and os.path.exists(self.main_image_path):
            try:
                self.pager.draw_image_file_scaled(char_x, char_y, char_w, char_h, self.main_image_path)
            except Exception as e:
                logger.debug(f"Could not draw character: {e}")
                self.pager.draw_ttf(char_x + 20, char_y + 30, "?", self.TEXT_COLOR, self.font_viking, 36)

        # Corner stats around the viking
        # Icon size and font for corner stats
        icon_size = int(18 * self.sy)
        num_font = int(16 * self.sy)  # BIG numbers

        # TOP-LEFT: Coins - adjusted position
        x = 4
        y = char_y + 15  # Moved up from 25 to 15
        self.draw_icon_scaled(x, y, icon_size, icon_size, 'gold')
        self.pager.draw_ttf(x, y + icon_size + 2, str(self.shared_data.coinnbr), self.TEXT_COLOR, self.font_arial, num_font)

        # BOTTOM-LEFT: Level
        x = 4
        y = char_y + char_h - icon_size - num_font - 4
        self.draw_icon_scaled(x, y, icon_size, icon_size, 'level')
        self.pager.draw_ttf(x, y + icon_size + 2, str(self.shared_data.levelnbr), self.TEXT_COLOR, self.font_arial, num_font)

        # TOP-RIGHT: Network KB (known hosts) - adjusted position
        x = self.width - icon_size - 4
        y = char_y + 15  # Moved up from 25 to 15
        self.draw_icon_scaled(x, y, icon_size, icon_size, 'networkkb')
        # Number below icon, right-aligned
        num_text = str(self.shared_data.networkkbnbr)
        self.pager.draw_ttf(x, y + icon_size + 2, num_text, self.TEXT_COLOR, self.font_arial, num_font)

        # BOTTOM-RIGHT: Attacks
        x = self.width - icon_size - 4
        y = char_y + char_h - icon_size - num_font - 4
        self.draw_icon_scaled(x, y, icon_size, icon_size, 'attacks')
        num_text = str(self.shared_data.attacksnbr)
        self.pager.draw_ttf(x, y + icon_size + 2, num_text, self.TEXT_COLOR, self.font_arial, num_font)

    def render_frame(self):
        """Render complete frame matching original Bjorn."""
        # Skip if dialog is showing (avoids overwriting exit confirmation)
        if self.dialog_showing:
            return

        self.pager.clear(self.BG_COLOR)

        self.draw_header()
        self.draw_stats_grid()
        self.draw_status_area()
        self.draw_dialogue_zone()
        self.draw_frise()
        self.draw_character_and_corner_stats()

        # Double-check dialog isn't showing before flip (race condition protection)
        if not self.dialog_showing:
            self.pager.flip()

    def run(self):
        """Main display loop."""
        logger.info("Starting display main loop...")

        while not self.shared_data.display_should_exit:
            try:
                # Skip rendering if a dialog is being shown
                if self.dialog_showing:
                    time.sleep(0.1)
                    continue

                # Check for auto-dim
                self.check_dim_timeout()

                self.display_comment(self.shared_data.bjornorch_status)
                self.shared_data.update_bjornstatus()
                self.update_leds(self.shared_data.bjornorch_status)
                self.render_frame()
                time.sleep(0.05)
            except Exception as e:
                logger.error(f"Error in display loop: {e}")
                time.sleep(0.1)

        logger.info("Display loop exiting...")
        self.cleanup()

    def cleanup(self):
        try:
            logger.info("Cleaning up display...")
            self.pager.led_all_off()
            self.pager.clear(self.BLACK)
            self.pager.flip()
            self.pager.cleanup()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


def handle_exit_display(signum, frame, display_instance):
    logger.info("Exit signal received...")
    shared_data.display_should_exit = True
    shared_data.should_exit = True
    if display_instance:
        display_instance.cleanup()
    sys.exit(0)


display_instance = None


if __name__ == "__main__":
    try:
        logger.info("Starting Bjorn display...")
        display_instance = Display(shared_data)

        signal.signal(signal.SIGINT, lambda s, f: handle_exit_display(s, f, display_instance))
        signal.signal(signal.SIGTERM, lambda s, f: handle_exit_display(s, f, display_instance))

        display_instance.run()

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if display_instance:
            display_instance.cleanup()
        sys.exit(1)
