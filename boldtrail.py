import time
import random
import re
import subprocess
import ssl
from datetime import datetime

# Fix for macOS Python SSL Certificate Verify Failed error during ChromeDriver download
ssl._create_default_https_context = ssl._create_unverified_context
from pathlib import Path
import pandas as pd
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

BOLDTRAIL_URL = "https://boldtrail.exprealty.com/login/?redir=%2Fdashboard"
LEAD_OWNER = "Patrick Goswitz"  # Default lead owner name
SCREENSHOTS_DIR = Path(__file__).with_name("screenshots")


def save_screenshot(driver, label="error"):
    """Save a screenshot with timestamp when something fails."""
    try:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = SCREENSHOTS_DIR / f"{label}_{timestamp}.png"
        driver.save_screenshot(str(filename))
        print(f"📸 Screenshot saved: {filename}")
    except Exception as e:
        print(f"Could not save screenshot: {e}")


class RestartBrowserException(Exception):
    """Exception raised when the browser needs to be restarted due to a recoverable error."""
    pass


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

    required_keys = ["BOLDTRAIL_EMAIL", "BOLDTRAIL_PASSWORD"]
    missing = [k for k in required_keys if k not in creds or not creds[k]]
    if missing:
        raise RuntimeError(f"Missing keys in credentials.txt: {', '.join(missing)}")

    return creds


CREDENTIALS = load_credentials()


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


def is_headless_server():
    """Detect if running on a headless server (no display available)."""
    import os
    import platform
    if platform.system() == "Linux" and not os.environ.get("DISPLAY"):
        return True
    return False


def create_undetectable_driver():
    """Create an undetectable Chrome driver using undetected-chromedriver."""
    import os

    profile_dir = os.path.abspath("./boldtrail_profile_selenium")
    chrome_version = get_chrome_major_version()
    headless_mode = is_headless_server()

    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--lang=en-US,en")

    if headless_mode:
        print("Headless server detected — enabling headless mode with server flags.")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--remote-debugging-port=9222")

    driver = uc.Chrome(options=options, headless=headless_mode, version_main=chrome_version)

    if not headless_mode:
        driver.maximize_window()

    return driver


def visit_google_news_first(driver):
    """Visit Google News first to simulate normal browsing behavior."""
    print("Opening Google News first to simulate normal browsing...")

    # Wait for at least one window handle to be available and stable
    for _ in range(10):
        if driver.window_handles:
            break
        time.sleep(1)
    driver.switch_to.window(driver.window_handles[0])

    driver.get("https://news.google.com")
    
    # Wait for page to load
    time.sleep(2)
    
    # Automatic scrolling for 10 seconds to simulate reading
    print("Scrolling through Google News for 10 seconds...")
    start_time = time.time()
    scroll_pause = 0.5  # Scroll every 0.5 seconds
    
    while time.time() - start_time < 10:
        # Scroll down
        driver.execute_script("window.scrollBy(0, 300);")
        time.sleep(scroll_pause)
        
        # Occasionally scroll back up a bit (more human-like)
        if random.random() < 0.2:  # 20% chance
            driver.execute_script("window.scrollBy(0, -100);")
            time.sleep(scroll_pause)
    
    print("Finished browsing Google News. Opening BoldTrail in new tab...")


def handle_cloudflare(driver):
    """Handle Cloudflare challenge using Selenium syntax."""
    try:
        # Wait a moment for page to load
        time.sleep(2)
        
        # Find Cloudflare iframe
        try:
            iframe = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='cloudflare']"))
            )
            
            # Switch to the iframe
            driver.switch_to.frame(iframe)
            
            # Find and click the checkbox inside the frame
            try:
                checkbox = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='checkbox']"))
                )
                checkbox.click()
                print("Cloudflare checkbox clicked!")
                time.sleep(2)  # Wait for challenge to process
            except Exception:
                # Try alternative selectors for checkbox
                try:
                    checkbox = driver.find_element(By.CSS_SELECTOR, ".cb-lb")
                    checkbox.click()
                    print("Cloudflare checkbox clicked (alternative selector)!")
                    time.sleep(2)
                except Exception:
                    print("Could not find Cloudflare checkbox in iframe.")
            
            # Switch back to default content
            driver.switch_to.default_content()
            
        except Exception:
            # No Cloudflare iframe found, switch back to default content just in case
            driver.switch_to.default_content()
            print("No Cloudflare challenge detected.")
            
    except Exception as e:
        print(f"Cloudflare handling error: {e}")
        # Ensure we're back to default content
        try:
            driver.switch_to.default_content()
        except:
            pass


def login_boldtrail(driver):
    """Log in to BoldTrail."""
    email = CREDENTIALS["BOLDTRAIL_EMAIL"]
    password = CREDENTIALS["BOLDTRAIL_PASSWORD"]

    print(f"Navigating to {BOLDTRAIL_URL}...")
    # Open BoldTrail in a new tab
    driver.execute_script("window.open('');")
    driver.switch_to.window(driver.window_handles[-1])
    driver.get(BOLDTRAIL_URL)
    
    # Wait a bit for page to load
    time.sleep(3)
    
    # Check for and handle Cloudflare challenge
    handle_cloudflare(driver)
    
    # Check if already logged in (dashboard is shown)
    print("Checking if already logged in...")
    try:
        # Check for "Add Contact" button or dashboard elements (quick check, 5 seconds)
        add_contact_check = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//span[normalize-space()='Add Contact']"))
        )
        print("Already logged in! Dashboard detected. Skipping login process.")
        
        # Process contacts from Excel
        process_contacts_from_excel(driver)
        
        return  # Exit function since already logged in
        
    except RestartBrowserException:
        raise  # Propagate restart signal up to the main runner
    except Exception:
        # Not logged in, proceed with login
        print("Not logged in. Proceeding with login process...")
        pass
    
    print("Waiting for BoldTrail login form... If Cloudflare or another page is shown, please complete it manually.")
    # Check for and handle Cloudflare challenge
    handle_cloudflare(driver)
    try:
        # Wait for email input field (up to 3 minutes)
        email_input = WebDriverWait(driver, 180).until(
            EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Email']"))
        )
        print("Email input field found!")
        
        # Human-like typing (faster)
        for char in email:
            email_input.send_keys(char)
            time.sleep(random.uniform(0.03, 0.08))
        
        next_button = driver.find_element(By.XPATH, "//button[@class='base-button base-button-primary base-button-full']")
        next_button.click()
        
        try:
            # Sometimes the username field appears again; handle that
            username_again_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@name='identifier' and @autocomplete='username']"))
            )
            print("Secondary username input detected! Completing user field again.")
            # clear the input field
            username_again_input.clear()
            for char in email:
                username_again_input.send_keys(char)
                time.sleep(random.uniform(0.03, 0.08))
            next_again_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Next' and contains(@class, 'button-primary')]")
            next_again_button.click()
            print("Submitted secondary username form.")
        except Exception:
            pass
        # Wait for password field
        password_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='credentials.passcode']"))
        )
        print("Password input field found!")
        
        for char in password:
            password_input.send_keys(char)
            time.sleep(random.uniform(0.03, 0.08))
        
        verify_button = driver.find_element(By.XPATH, "//input[@value='Verify']")
        verify_button.click()
        
        print("Login submitted! Waiting for dashboard...")
        # Wait until dashboard is ready (Add Contact button visible)
        WebDriverWait(driver, 60).until(
            EC.element_to_be_clickable((By.XPATH, "//span[normalize-space()='Add Contact']"))
        )
        
        # Process contacts from Excel
        process_contacts_from_excel(driver)
        
    except RestartBrowserException:
        raise  # Propagate restart signal up to the main runner
    except Exception as e:
        print(f"Email input did not appear within 3 minutes. Checking for 'Add Contact' button...")
        save_screenshot(driver, "boldtrail_login_failed")
        try:
            # Check for "Add Contact" button as a fallback
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//span[normalize-space()='Add Contact']"))
            )
            print("Add Contact button found! We are logged in.")
            process_contacts_from_excel(driver)
            return
        except Exception:
            print("Neither email input nor 'Add Contact' button found. Closing browser.")
            save_screenshot(driver, "boldtrail_no_login_no_dashboard")
            raise e


def fill_contact_form(driver, contact):
    """Fill the BoldTrail contact form with contact data."""
    if "okta" in driver.current_url:
        driver.get("https://boldtrail.exprealty.com/dashboard")
        time.sleep(5)
        
    try:
        
        print(f"Filling form for: {contact.get('First Name', '')} {contact.get('Last Name', '')}")
        
        # Wait for form to load (first field visible)
        first_name_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "(//input[@type='text'])[1]"))
        )
        first_name_input.clear()
        for char in str(contact.get('First Name', '')):
            first_name_input.send_keys(char)
            time.sleep(random.uniform(0.03, 0.06))
        
        last_name_input = driver.find_element(By.XPATH, "(//input[@type='text'])[2]")
        last_name_input.clear()
        for char in str(contact.get('Last Name', '')):
            last_name_input.send_keys(char)
            time.sleep(random.uniform(0.03, 0.06))
        
        # email_input = driver.find_element(By.XPATH, "(//input[@type='text'])[3]")
        # email_input.clear()
        # for char in str(contact.get('Email', '')):
        #     email_input.send_keys(char)
        #     time.sleep(random.uniform(0.03, 0.06))
        
        phone_input = driver.find_element(By.XPATH, "(//input[@type='text'])[4]")
        phone_input.clear()
        for char in str(contact.get('Phone', '')):
            phone_input.send_keys(char)
            time.sleep(random.uniform(0.03, 0.06))
        
        # Permission to contact - Click Yes
        try:
            yes_option = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "(//span[@class='option'][normalize-space()='Yes'])[2]"))
            )
            yes_option.click()
            print("Clicked 'Yes' for Permission to contact")
            time.sleep(0.3)
        except Exception as e:
            print(f"Could not click 'Yes' option: {e}")
        only_address_toggle = driver.find_element(By.XPATH, "//label[@for='address-only-contact']")
        only_address_toggle.click()
        time.sleep(2)
        # Address
        # make a full address if any of the address fields are empty no need to add , 
        address = ""
        if contact.get('Address', ''):
            address += contact.get('Address', '')
        if contact.get('City', ''):
            address += ", " + contact.get('City', '')
        if contact.get('State', ''):
            address += ", " + contact.get('State', '')
        if contact.get('Zip', ''):
            address += ", " + contact.get('Zip', '')
        try:
            # Try to find the input within the container
            address_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'base-input-container')]//input"))
            )
            address_input.clear()
            for char in address:
                address_input.send_keys(char)
                time.sleep(random.uniform(0.03, 0.06))
            time.sleep(1)
            # press arrow down to select the address
            address_input.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.2)
            address_input.send_keys(Keys.ENTER)
        except Exception as e:
            print(f"Could not fill Address: {e}")
            save_screenshot(driver, "boldtrail_address_failed")
            return False
        
        # city_input = driver.find_element(By.XPATH, "(//input[@type='text'])[6]")
        # city_input.clear()
        # for char in str(contact.get('City', '')):
        #     city_input.send_keys(char)
        #     time.sleep(random.uniform(0.03, 0.06))
        
        # try:
        #     seller_option = WebDriverWait(driver, 5).until(
        #         EC.element_to_be_clickable((By.XPATH, "(//span[normalize-space()='Seller'])[1]"))
        #     )
        #     seller_option.click()
        #     print("Clicked 'Seller' option")
        #     time.sleep(0.3)
        # except Exception as e:
        #     print(f"Could not click 'Seller' option: {e}")
        
        # Lead Owner
        seller_button = driver.find_element(By.XPATH, "(//span[normalize-space()='Seller'])[1]")
        seller_button.click()
        time.sleep(0.3)
        try:
            lead_owner_input = driver.find_element(By.XPATH, "(//input[@class='real-input font-figtree'])[3]")
            lead_owner_input.clear()
            for char in LEAD_OWNER:
                lead_owner_input.send_keys(char)
                time.sleep(random.uniform(0.03, 0.06))
            time.sleep(0.3)
            lead_owner_input.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.2)
            lead_owner_input.send_keys(Keys.ENTER)
            print(f"Entered Lead Owner: {LEAD_OWNER}")
        except Exception as e:
            print(f"Could not fill Lead Owner: {e}")
        
        # Smart Campaign (Folder name)
        try:
            smart_campaign_input = driver.find_element(By.XPATH, "//input[@label='Smart Campaign']")
            smart_campaign_input.clear()
            folder_name = str(contact.get('Folder', ''))
            for char in folder_name:
                smart_campaign_input.send_keys(char)
                time.sleep(random.uniform(0.03, 0.06))
            time.sleep(2)
            smart_campaign_input.send_keys(Keys.ENTER)
            time.sleep(1)
            print(f"Entered Smart Campaign: {folder_name}")
        except Exception as e:
            print(f"Could not fill Smart Campaign: {e}")
        
        time.sleep(0.5)
        try:
            try:
                driver.execute_script("""
                    var iframes = document.querySelectorAll('iframe[data-intercom-frame], iframe[name*="intercom"], iframe.intercom-with-namespace');
                    for (var i = 0; i < iframes.length; i++) {
                        iframes[i].style.display = 'none';
                        iframes[i].style.visibility = 'hidden';
                    }
                """)
                time.sleep(0.3)
            except Exception:
                pass

            submit_button = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//button[@data-userpilot='add-contact']"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", submit_button)
            print("Form submitted successfully!")
            # Wait for modal close button or for Add Contact to be available again
            try:
                close_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Close') or contains(text(), 'OK') or contains(@class, 'close')]"))
                )
                driver.execute_script("arguments[0].click();", close_button)
            except Exception:
                pass
            # Ensure Add Contact is clickable before returning (next contact)
            try:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[normalize-space()='Add Contact']"))
                )
            except Exception:
                pass

            return True
        except Exception as e:
            print(f"Error submitting form: {e}")
            save_screenshot(driver, "boldtrail_submit_failed")
            return False

    except Exception as e:
        print(f"Error filling contact form: {e}")
        save_screenshot(driver, "boldtrail_form_failed")
        return False


def process_contacts_from_excel(driver):
    """Read Excel file and add contacts to BoldTrail one by one."""
    excel_path = Path(__file__).with_name("vulcan_contacts.xlsx")
    
    if not excel_path.exists():
        print(f"Excel file not found: {excel_path}")
        return
    
    try:
        # Read Excel file
        df = pd.read_excel(excel_path)
        
        # Ensure boldtrail column exists
        if "boldtrail" not in df.columns:
            df["boldtrail"] = False
        
        # Filter contacts where boldtrail = False
        contacts_pending = df[df["boldtrail"] == False].copy()
        contacts_to_add = contacts_pending
        
        if len(contacts_to_add) == 0:
            print("No contacts to add. All contacts have already been added to BoldTrail.")
            return
        
        print(f"Found {len(contacts_to_add)} contacts to add to BoldTrail. Will process all of them one by one.")
        
        # Process each contact (all 10, 20, or however many have boldtrail=False)
        for count, (idx, contact_row) in enumerate(contacts_to_add.iterrows(), start=1):
            contact = contact_row.to_dict()
            
            print(f"\n--- Processing contact {count}/{len(contacts_to_add)} ---")
            
            # Click "Add Contact" button for each new contact
            try:
                add_contact_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[normalize-space()='Add Contact']"))
                )
                add_contact_button.click()
                # Wait for form first field to be visible
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "(//input[@type='text'])[1]"))
                )
            except Exception:
                print("Could not click 'Add Contact' button. Form might already be open.")
            
            # Fill the form
            success = fill_contact_form(driver, contact)
            
            if success:
                # Update Excel: set boldtrail = True for this contact
                df.at[idx, "boldtrail"] = True
                df.to_excel(excel_path, index=False)
                print(f"✓ Contact added successfully! Updated Excel file.")
                print(f"✓ Contact added successfully! Updated Excel file.")
            else:
                print(f"✗ Failed to add contact. Initiating browser restart...")
                save_screenshot(driver, "boldtrail_contact_failed")
                raise RestartBrowserException("Contact form submission failed.")
            
            # Go back to dashboard and wait for Add Contact to be ready
            try:
                driver.get(BOLDTRAIL_URL)
                WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[normalize-space()='Add Contact']"))
                )
            except Exception:
                pass
        
        print(f"\nCompleted processing {len(contacts_to_add)} contacts.")
        
    except RestartBrowserException:
        raise  # Propagate restart signal up to the main runner
    except Exception as e:
        print(f"Error processing contacts from Excel: {e}")
        save_screenshot(driver, "boldtrail_excel_processing_failed")


def run_boldtrail_login():
    """Run BoldTrail login automation using undetectable Selenium."""
    restart_count = 0
    max_restarts = 5
    
    while True:
        driver = None
        try:
            print("Starting undetectable Chrome browser...")
            driver = create_undetectable_driver()
            
            print("Browser started successfully!")
            
            # First, visit Google News and scroll for 10 seconds
            visit_google_news_first(driver)
            
            # Then open BoldTrail in a new tab and login
            login_boldtrail(driver)
            
            print("BoldTrail automation completed. Keeping browser open for 10 seconds.")
            time.sleep(10)
            break  # Exit loop if successful
            
        except RestartBrowserException as e:
            restart_count += 1
            print(f"\n!!! RESTARTING BROWSER DUE TO ERROR: {e} (Attempt {restart_count}/{max_restarts}) !!!\n")
            if driver:
                save_screenshot(driver, f"boldtrail_restart_{restart_count}")

            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            driver = None
            
            if restart_count >= max_restarts:
                print(f"Max restarts ({max_restarts}) reached. Stopping automation.")
                break
                
            time.sleep(5)  # Wait a bit before restarting
            continue  # Restart the loop
            
        except Exception as e:
            print(f"Critical error occurred: {e}")
            if driver:
                save_screenshot(driver, "boldtrail_critical")
            break  # Exit loop on critical error
        finally:
            if driver:
                print("Closing browser...")
                driver.quit()


if __name__ == "__main__":
    run_boldtrail_login()
