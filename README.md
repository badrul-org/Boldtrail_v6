# Vulcan7 → BoldTrail Automation

Automates moving contacts from **Vulcan7** to **BoldTrail CRM**: scrape contacts by folder and date, save to Excel, then add them to BoldTrail one by one.

## What it does

1. **Vulcan7** – Logs in (Selenium), scrapes contacts from folders (Off Market, FSBO, FRBO, DealMachine), filters by today’s date, saves to `vulcan_contacts.xlsx` with a `boldtrail` flag.
2. **BoldTrail** – Logs in, reads Excel, adds each contact with `boldtrail = False`, then sets `boldtrail = True` after success so no duplicates are added.

## Prerequisites

- **Python 3.10+**
- **Google Chrome** (for Selenium; ChromeDriver is usually managed automatically by Selenium 4)
- Project folder with `credentials.txt` (see below)

---

## Setup (Mac and Windows)

### 1. Create a virtual environment

**macOS / Linux (Terminal):**

```bash
cd /path/to/vulcan7_to_boldtrail_codebase_V2
python3 -m venv env
```

**Windows (Command Prompt or PowerShell):**

```cmd
cd C:\path\to\vulcan7_to_boldtrail_codebase_V2
python -m venv env
```

### 2. Activate the virtual environment

**macOS / Linux (Terminal):**

```bash
source env/bin/activate
```

You should see `(env)` at the start of your prompt.

**Windows (Command Prompt):**

```cmd
env\Scripts\activate.bat
```

**Windows (PowerShell):**

```powershell
env\Scripts\Activate.ps1
```

If you get an execution policy error, run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once, then try again.

You should see `(env)` at the start of your prompt.

### 3. Install requirements

With the virtual environment **activated** (same on Mac and Windows):

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Credentials

Create a file named `credentials.txt` in the project folder (same folder as `app.py`):

```
VULCAN7_USERNAME=your@email.com
VULCAN7_PASSWORD=your_password
BOLDTRAIL_EMAIL=your@boldtrail.email
BOLDTRAIL_PASSWORD=your_password
```

Do not commit this file to version control.

---

## How to run

Run all commands from the project folder with the virtual environment **activated**.

### Full flow (Vulcan7 + BoldTrail)

**Mac / Linux:**

```bash
python app.py
```

**Windows:**

```cmd
python app.py
```

This runs Vulcan7 scraping, saves contacts to Excel, then automatically runs BoldTrail to add them.

### Test mode (use yesterday’s contacts)

When you have no contacts with today’s date, use test mode so contacts from **yesterday** are used:

```bash
python app.py --test
```

(Use `python3` on Mac/Linux if that’s how you run Python.)

### BoldTrail only

If you already have `vulcan_contacts.xlsx` and only want to add contacts to BoldTrail:

```bash
python boldtrail.py
```

---

## Files

| File                     | Role                                                                  |
| ------------------------ | --------------------------------------------------------------------- |
| `app.py`               | Vulcan7 scraping (Selenium) + Excel save; then runs `boldtrail.py`. |
| `boldtrail.py`         | BoldTrail login and add-contact flow (Selenium).                      |
| `vulcan_contacts.xlsx` | Output from Vulcan7; input for BoldTrail.                             |
| `credentials.txt`      | Login credentials (do not commit).                                    |
| `env/`                 | Virtual environment (do not commit).                                  |

---

## Notes

- Excel column **boldtrail**: `False` = not yet in BoldTrail; `True` = already added (skipped next run).
- Duplicates in Excel are avoided by (Full Name + Email).
- Run from the project folder so paths to `credentials.txt` and `vulcan_contacts.xlsx` are correct.
- Browser profiles (e.g. `vulcan_profile_selenium`, `boldtrail_profile_selenium`) store login state so you don’t have to log in every time; you can add them to `.gitignore`.
