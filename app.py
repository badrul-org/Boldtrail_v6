import os
import platform
import random
import re
import ssl
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Fix for macOS/Linux SSL Certificate Verify Failed error during ChromeDriver download
ssl._create_default_https_context = ssl._create_unverified_context

import pandas as pd
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

VULCAN7_URL = "https://www.vulcan7.com/login/"
SCREENSHOTS_DIR = Path(__file__).with_name("screenshots")


def save_screenshot(driver, label="error"):
    """Save a screenshot with timestamp when something fails."""
    try:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = SCREENSHOTS_DIR / f"{label}_{timestamp}.png"
        driver.save_screenshot(str(filename))
        print(f"Screenshot saved: {filename}")
    except Exception as e:
        print(f"Could not save screenshot: {e}")


def load_credentials():
    """Load credentials from a local text file 'credentials.txt'."""
    cred_path = Path(__file__).with_name("credentials.txt")
    creds = {}
    if not cred_path.exists():
        raise RuntimeError(f"credentials.txt not found at {cred_path}.")

    for line in cred_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        creds[key.strip()] = value.strip()

    required_keys = ["VULCAN7_USERNAME", "VULCAN7_PASSWORD"]
    missing = [k for k in required_keys if k not in creds or not creds[k]]
    if missing:
        raise RuntimeError(f"Missing keys in credentials.txt: {', '.join(missing)}")

    return creds


CREDENTIALS = load_credentials()


def is_headless_server():
    """Detect if running on a headless server (no display available)."""
    if platform.system() == "Linux" and not os.environ.get("DISPLAY"):
        return True
    return False


def get_chrome_major_version():
    """Auto-detect the installed Chrome major version."""
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
        "google-chrome",           # Linux
        "google-chrome-stable",    # Linux alt
        "chromium-browser",        # Linux Chromium
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",   # Windows
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in chrome_paths:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True, timeout=5
            )
            match = re.search(r"(\d+)\.", result.stdout)
            if match:
                version = int(match.group(1))
                print(f"Detected Chrome version: {version}")
                return version
        except Exception:
            continue
    print("Could not detect Chrome version, letting uc auto-detect.")
    return None


def create_driver():
    """Create an undetectable Chrome driver (used for both Vulcan7 and BoldTrail)."""
    profile_dir = os.path.abspath(
        str(Path(__file__).with_name("boldtrail_profile_selenium"))
    )
    chrome_version = get_chrome_major_version()

    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--lang=en-US,en")

    headless = is_headless_server()
    if headless:
        print("Headless server detected — enabling headless mode.")
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"Starting browser (attempt {attempt}/{max_attempts})...")
            driver = uc.Chrome(options=options, headless=headless, version_main=chrome_version)
            if not headless:
                try:
                    driver.maximize_window()
                except Exception:
                    pass  # Some servers fail on maximize; window-size flag handles it
            return driver
        except Exception as e:
            print(f"Browser failed to start (attempt {attempt}/{max_attempts}): {e}")
            try:
                driver.quit()
            except Exception:
                pass
            if attempt >= max_attempts:
                raise RuntimeError(f"Could not start browser after {max_attempts} attempts: {e}")
            time.sleep(3)


def _send_keys_slowly(element, text, delay_range=(30, 60)):
    """Send keys with random delay between characters (ms). Faster range for speed."""
    for c in text:
        element.send_keys(c)
        time.sleep(random.randint(*delay_range) / 1000.0)


def login_vulcan7(driver):
    """Log in to Vulcan7."""
    username = CREDENTIALS["VULCAN7_USERNAME"]
    password = CREDENTIALS["VULCAN7_PASSWORD"]

    driver.get(VULCAN7_URL)

    wait = WebDriverWait(driver, 60)
    username_input = wait.until(
        EC.presence_of_element_located((By.XPATH, "(//input[@name='username'])[1]"))
    )
    _send_keys_slowly(username_input, username)
    password_input = driver.find_element(By.XPATH, "(//input[@id='password'])[1]")
    _send_keys_slowly(password_input, password)
    submit_btn = driver.find_element(
        By.XPATH, "(//button[@type='submit'][normalize-space()='Sign in >'])[1]"
    )
    submit_btn.click()

    # Wait for Contacts link then click
    wait = WebDriverWait(driver, 60)
    contacts_link = wait.until(
        EC.element_to_be_clickable((By.XPATH, "(//a[@aria-label='See Contacts'][normalize-space()='Contacts'])[1]"))
    )
    contacts_link.click()

    # Wait for contact grid to be present (contacts page loaded)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#main_contact_grid tbody"))
    )


def _split_name(full_name: str) -> tuple[str, str]:
    """Split full name into first and last name."""
    if not full_name:
        return "", ""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], ""
    first = parts[0]
    last = " ".join(parts[1:])
    return first, last


def parse_vulcan_contacts_html(html: str, current_folder: str) -> list[dict]:
    """
    Parse the Vulcan7 contacts table HTML and return a list of contacts.

    We expect each contact to be represented by two <tr> elements that share
    the same data-itemid. Column IDs use fixed numeric suffixes, so we match
    by those suffixes.
    """
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", id="main_contact_grid")
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    # Group rows by data-itemid
    groups: dict[str, list] = {}
    for tr in tbody.find_all("tr"):
        item_id = tr.get("data-itemid")
        if not item_id:
            continue
        groups.setdefault(item_id, []).append(tr)

    contacts: list[dict] = []

    date_pattern = re.compile(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s*\d{4}",
        re.I
    )

    for item_id, rows in groups.items():
        segment_html = "".join(str(r) for r in rows)
        segment = BeautifulSoup(segment_html, "html.parser")

        name_tag = segment.select_one("span.contact-details-link a")
        name = name_tag.get_text(strip=True) if name_tag else ""

        # Date Added: try fixed ID first, then any div with date-like text
        date_added_tag = segment.select_one("div[id$='-181075']")
        if not date_added_tag:
            for div in segment.select("div[id]"):
                text = div.get_text(strip=True) or ""
                if date_pattern.search(text):
                    date_added_tag = div
                    break
        date_added = date_added_tag.get_text(strip=True) if date_added_tag else ""

        address_tag = segment.select_one("div[id$='-181076']")
        city_tag = segment.select_one("div[id$='-181077']")
        phone_tag = segment.select_one("div[id$='-181079']")
        email_tag = segment.select_one("div[id$='-181080']")
        folder_tag = segment.select_one("div[id$='-181083']")
        address = address_tag.get_text(strip=True) if address_tag else ""
        city = city_tag.get_text(strip=True) if city_tag else ""
        phone = phone_tag.get_text(strip=True) if phone_tag else ""
        email = email_tag.get_text(strip=True) if email_tag else ""
        folder_name = folder_tag.get_text(strip=True) if folder_tag else current_folder

        # Normalize "No Email Address"
        if email.lower().startswith("no email"):
            email = ""

        first_name, last_name = _split_name(name)

        contacts.append(
            {
                "First Name": first_name,
                "Last Name": last_name,
                "Full Name": name,
                "Date Added": date_added,
                "Phone": phone,
                "Address": address,
                "City": city,
                "Email": email,
                "Folder": folder_name,
                "boldtrail": False,  # Track if contact has been added to BoldTrail
            }
        )

    return contacts


def extract_contacts_from_vulcan_page(driver, folder: str) -> list[dict]:
    """Get page HTML for current folder and parse contacts."""
    html = driver.page_source
    return parse_vulcan_contacts_html(html, folder)


def _parse_date_added(date_text: str) -> datetime | None:
    """Parse Vulcan7 date text (e.g. 'Feb 1, 2026 5:16 am', 'Feb 01, 2026') to date. Returns None if unparseable."""
    if not date_text or not date_text.strip():
        return None
    text = date_text.strip()
    # Try common formats
    formats = [
        "%b %d, %Y %I:%M %p",   # Feb 1, 2026 5:16 am
        "%b %d, %Y",            # Feb 1, 2026
        "%b %d, %Y %H:%M",      # Feb 1, 2026 17:16
        "%B %d, %Y",            # February 1, 2026
        "%m/%d/%Y",             # 02/01/2026
        "%m-%d-%Y",             # 02-01-2026
        "%Y-%m-%d",             # 2026-02-01
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text[: len(text)].split(".")[0].strip(), fmt)
        except (ValueError, IndexError):
            continue
    # Fallback: match "Feb 1" or "Feb 01" at start
    match = re.match(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", text, re.I)
    if match:
        month_str, day_str = match.groups()
        try:
            parsed = datetime.strptime(f"{month_str} {int(day_str)} {datetime.today().year}", "%b %d %Y")
            return parsed
        except ValueError:
            pass
    return None


def is_today_date_added(date_text: str) -> bool:
    """Return True if the 'Date Added' text corresponds to today."""
    if not date_text:
        return False
    parsed = _parse_date_added(date_text)
    if parsed is None:
        return False
    return parsed.date() == datetime.today().date()


def is_yesterday_date_added(date_text: str) -> bool:
    """Return True if the 'Date Added' text corresponds to yesterday (for test mode)."""
    if not date_text:
        return False
    parsed = _parse_date_added(date_text)
    if parsed is None:
        return False
    yesterday = datetime.today().date() - timedelta(days=1)
    return parsed.date() == yesterday


def run_logins(test_mode=False, driver=None):
    """Run Vulcan7 scraping + BoldTrail automation in a single undetectable browser.

    Args:
        test_mode: If True, use contacts whose 'Date Added' is yesterday (for testing when none have today's date).
                   If False, only use contacts whose 'Date Added' is today.
        driver: Optional existing browser driver. If provided, it will be reused and NOT closed.
    """
    if test_mode:
        print("TEST MODE: Using contacts with 'Date Added' = yesterday.\n")

    owns_driver = driver is None
    had_contacts_from_vulcan = False
    if owns_driver:
        driver = create_driver()
    print("Undetectable Chrome browser ready!")

    try:
        # ── Step 1: Vulcan7 — login and scrape contacts ──
        print("\n" + "=" * 60)
        print("Step 1: Vulcan7 — Scraping contacts")
        print("=" * 60)

        login_vulcan7(driver)

        folders = ["Off Market", "FSBO", "FRBO (Investors)", "Deal Machine"]
        all_contacts: list[dict] = []

        # Some folders (like FRBO / DealMachine) may be under a "More" dropdown.
        try:
            caret = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//i[@class='icon-caret-down']"))
            )
            caret.click()
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//div[normalize-space()='FSBO']"))
                )
            except Exception:
                pass
            print("Expanded extra folders with caret-down button.")
        except Exception:
            pass  # Caret not visible or not needed; continue with folders

        grid_wait = WebDriverWait(driver, 15)
        for folder in folders:
            try:
                # For "Off Market" we do not click the folder (e.g. it may already be selected)
                if folder != "Off Market":
                    folder_locator = driver.find_elements(
                        By.XPATH, f"//div[normalize-space()='{folder}']"
                    )
                    if not folder_locator:
                        print(f"Could not find folder element for '{folder}', skipping this folder.")
                        continue

                    folder_element = folder_locator[0]
                    driver.execute_script("arguments[0].click();", folder_element)
                    print(f"Clicked folder '{folder}' via JavaScript.")
                else:
                    print("Skipping click for 'Off Market' (using current view).")

                # Wait for grid to have content (data loaded)
                grid_wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "#main_contact_grid tbody tr")
                    )
                )

                folder_contacts = extract_contacts_from_vulcan_page(driver, folder)
                print(f"Found {len(folder_contacts)} total contacts in folder '{folder}'.")

                dates_extracted = [c.get("Date Added", "") for c in folder_contacts if c.get("Date Added")]
                if dates_extracted:
                    unique_dates = list(dict.fromkeys(dates_extracted))[:10]
                    print(f"  Extracted 'Date Added' (sample): {unique_dates}")
                else:
                    print("  Extracted 'Date Added': (none found)")

                if test_mode:
                    contacts_to_add = [
                        c for c in folder_contacts if is_yesterday_date_added(c.get("Date Added", ""))
                    ]
                    print(
                        f"{len(contacts_to_add)} contacts in folder '{folder}' match yesterday's 'Date Added' (test mode)."
                    )
                else:
                    contacts_to_add = [
                        c for c in folder_contacts if is_today_date_added(c.get("Date Added", ""))
                    ]
                    print(
                        f"{len(contacts_to_add)} contacts in folder '{folder}' match today's 'Date Added'."
                    )
                for c in contacts_to_add:
                    print(f"  -> {c.get('Full Name', '')}: Date Added = '{c.get('Date Added', '')}'")

                all_contacts.extend(contacts_to_add)
            except Exception as e:
                print(f"Error while processing folder '{folder}': {e}")
                save_screenshot(driver, f"vulcan7_folder_{folder.replace(' ', '_')}")
                continue

        # Deduplicate by (name, email)
        seen_keys: set[tuple[str, str]] = set()
        unique_contacts: list[dict] = []
        for contact in all_contacts:
            name_key = (contact.get("Full Name") or "").strip().lower()
            email_key = (contact.get("Email") or "").strip().lower()
            key = (name_key, email_key)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_contacts.append(contact)

        # Save to Excel: overwrite file each run (no append)
        output_path = Path(__file__).with_name("vulcan_contacts.xlsx")
        if unique_contacts:
            had_contacts_from_vulcan = True
            df_new = pd.DataFrame(unique_contacts)
            df_new.to_excel(output_path, index=False)
            print(f"Saved {len(df_new)} unique contacts to {output_path} (file overwritten).")
        else:
            # Clean the file: write empty DataFrame with expected columns
            df_empty = pd.DataFrame(
                columns=[
                    "First Name", "Last Name", "Full Name", "Date Added",
                    "Phone", "Address", "City", "Email", "Folder", "boldtrail"
                ]
            )
            df_empty.to_excel(output_path, index=False)
            print("No contacts found; vulcan_contacts.xlsx cleared.")

        print("Vulcan7 scraping completed.")

        # ── Step 2: BoldTrail — add contacts using the SAME browser ──
        if not had_contacts_from_vulcan:
            print("\n" + "=" * 60)
            print("No new contacts from Vulcan7. Skipping BoldTrail.")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("Step 2: BoldTrail — Adding contacts (same browser)")
            print("=" * 60 + "\n")

            from boldtrail import run_boldtrail_with_driver

            # Run BoldTrail in the SAME browser (no new browser)
            run_boldtrail_with_driver(driver)

    except Exception as e:
        print(f"Automation error: {e}")
        save_screenshot(driver, "critical_error")
        raise
    finally:
        if owns_driver:
            print("Closing browser...")
            driver.quit()
        else:
            # Reset browser to blank page for next run (don't close it)
            try:
                driver.get("about:blank")
            except Exception:
                pass

    print("\n" + "=" * 60)
    print("All automation completed!")
    print("=" * 60)


if __name__ == "__main__":
    # Use --test to use yesterday's date instead of today (for testing when no contacts have today's date)
    test_mode = "--test" in sys.argv
    run_logins(test_mode=test_mode)
