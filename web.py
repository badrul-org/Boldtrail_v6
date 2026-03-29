"""
BoldTrail Automation Dashboard
Flask web UI with scheduler, persistent browser, and live logs.
Run: python web.py
"""
import json
import os
import queue
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ── Import automation functions from app.py ──
from app import create_driver, run_logins, save_screenshot, SCREENSHOTS_DIR, _kill_stale_chrome

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "automation.db"

app = Flask(__name__)

# ════════════════════════════════════════════════════════════
# Database (SQLite)
# ════════════════════════════════════════════════════════════

def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id TEXT PRIMARY KEY,
            time TEXT NOT NULL,
            timezone TEXT NOT NULL,
            test_mode INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            schedule_id TEXT,
            started_at TEXT,
            finished_at TEXT,
            status TEXT DEFAULT 'running',
            error_message TEXT,
            test_mode INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            message TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ════════════════════════════════════════════════════════════
# Log Capture — intercept print() output and broadcast via SSE
# ════════════════════════════════════════════════════════════

class LogCapture:
    def __init__(self):
        self._original_stdout = sys.stdout
        self._subscribers = []
        self._lock = threading.Lock()
        self._current_run_id = None
        self._run_logs = {}  # run_id -> list of log entries

    def start_run(self, run_id):
        self._current_run_id = run_id
        self._run_logs[run_id] = []

    def end_run(self):
        run_id = self._current_run_id
        self._current_run_id = None
        return run_id

    def write(self, text):
        # Always write to real stdout
        self._original_stdout.write(text)
        self._original_stdout.flush()

        if not text or not text.strip():
            return

        entry = {
            "run_id": self._current_run_id or "system",
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "msg": text.strip(),
        }

        # Store in memory for the current run
        if self._current_run_id and self._current_run_id in self._run_logs:
            self._run_logs[self._current_run_id].append(entry)

        # Broadcast to SSE subscribers
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(entry)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def flush(self):
        self._original_stdout.flush()

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def get_run_logs(self, run_id):
        return self._run_logs.get(run_id, [])

    def flush_to_db(self, run_id):
        """Save in-memory logs to database."""
        logs = self._run_logs.pop(run_id, [])
        if not logs:
            return
        conn = db_conn()
        conn.executemany(
            "INSERT INTO run_logs (run_id, timestamp, message) VALUES (?, ?, ?)",
            [(run_id, e["ts"], e["msg"]) for e in logs],
        )
        conn.commit()
        conn.close()


log_capture = LogCapture()


# ════════════════════════════════════════════════════════════
# Browser Manager — persistent single browser instance
# ════════════════════════════════════════════════════════════

class BrowserManager:
    def __init__(self):
        self.driver = None
        self._lock = threading.Lock()
        self._busy = False

    def start(self):
        """Create the browser (called once at startup)."""
        print("[BrowserManager] Starting persistent browser...")
        self.driver = create_driver()
        print("[BrowserManager] Browser started and ready.")

    def is_alive(self):
        if self.driver is None:
            return False
        try:
            # Do a real check — title alone can succeed on a stale session
            _ = self.driver.current_url
            self.driver.execute_script("return 1")
            return True
        except Exception:
            return False

    def get_driver(self):
        """Get the driver, restarting it if it crashed."""
        if not self.is_alive():
            print("[BrowserManager] Browser not alive, restarting...")
            self._kill_driver()
            self.driver = create_driver()
            print("[BrowserManager] Browser restarted.")
        return self.driver

    def force_restart(self):
        """Force kill and recreate the browser."""
        print("[BrowserManager] Force restarting browser...")
        self._kill_driver()
        self.driver = create_driver()
        print("[BrowserManager] Browser force-restarted.")
        return self.driver

    def _kill_driver(self):
        """Safely kill the current driver and any leftover Chrome processes."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        # Kill any orphaned chrome/chromedriver processes
        _kill_stale_chrome()
        time.sleep(2)  # Wait for processes to fully exit

    def acquire(self):
        self._lock.acquire()
        self._busy = True
        return self.get_driver()

    def release(self):
        self._busy = False
        self._lock.release()

    @property
    def is_busy(self):
        return self._busy

    def shutdown(self):
        self._kill_driver()


browser_mgr = BrowserManager()


# ════════════════════════════════════════════════════════════
# Scheduler
# ════════════════════════════════════════════════════════════

scheduler = BackgroundScheduler()


def execute_run(schedule_id=None, test_mode=False):
    """Execute automation run using the persistent browser. Retries once with a fresh browser on failure."""
    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Record run in DB
    conn = db_conn()
    conn.execute(
        "INSERT INTO runs (id, schedule_id, started_at, status, test_mode) VALUES (?, ?, ?, 'running', ?)",
        (run_id, schedule_id, started_at, int(test_mode)),
    )
    conn.commit()
    conn.close()

    # Start log capture
    log_capture.start_run(run_id)

    # Redirect stdout to capture prints
    old_stdout = sys.stdout
    sys.stdout = log_capture

    screenshots_before = set()
    if SCREENSHOTS_DIR.exists():
        screenshots_before = set(os.listdir(SCREENSHOTS_DIR))

    status = "success"
    error_msg = None
    max_attempts = 2  # Try once, retry once with fresh browser

    driver = browser_mgr.acquire()
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    print(f"[Run {run_id}] Retrying with fresh browser (attempt {attempt}/{max_attempts})...")
                    driver = browser_mgr.force_restart()
                    time.sleep(3)

                print(f"[Run {run_id}] Starting automation...")
                run_logins(test_mode=test_mode, driver=driver)
                print(f"[Run {run_id}] Automation completed successfully!")
                break  # Success — exit retry loop

            except Exception as e:
                error_msg = str(e)
                print(f"[Run {run_id}] ERROR (attempt {attempt}/{max_attempts}): {e}")

                if attempt < max_attempts:
                    # Check if it's a stale browser error worth retrying
                    err_lower = error_msg.lower()
                    if any(k in err_lower for k in [
                        "session", "chrome not reachable", "no such window",
                        "unable to evaluate", "target window already closed",
                        "handleverifier", "disconnected", "not connected",
                    ]):
                        print(f"[Run {run_id}] Browser appears stale, will restart and retry...")
                        continue
                    else:
                        # Non-browser error, don't retry
                        status = "error"
                        break
                else:
                    status = "error"
    finally:
        browser_mgr.release()
        sys.stdout = old_stdout

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update run status in DB
        conn = db_conn()
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, error_message=? WHERE id=?",
            (finished_at, status, error_msg, run_id),
        )
        conn.commit()
        conn.close()

        # Flush logs to DB
        log_capture.flush_to_db(run_id)
        log_capture.end_run()

        print(f"Run {run_id} finished with status: {status}")


def add_schedule_to_scheduler(schedule):
    """Register a schedule with APScheduler."""
    tz = pytz.timezone(schedule["timezone"])
    hour, minute = schedule["time"].split(":")
    trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)
    scheduler.add_job(
        execute_run,
        trigger=trigger,
        id=f"schedule_{schedule['id']}",
        args=[schedule["id"], bool(schedule["test_mode"])],
        replace_existing=True,
    )


def load_schedules_from_db():
    """Load all saved schedules into APScheduler on startup."""
    conn = db_conn()
    rows = conn.execute("SELECT * FROM schedules WHERE enabled=1").fetchall()
    conn.close()
    for row in rows:
        try:
            add_schedule_to_scheduler(dict(row))
        except Exception as e:
            print(f"Failed to load schedule {row['id']}: {e}")


# ════════════════════════════════════════════════════════════
# Flask Routes
# ════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/schedules", methods=["GET"])
def get_schedules():
    conn = db_conn()
    rows = conn.execute("SELECT * FROM schedules ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/schedules", methods=["POST"])
def create_schedule():
    data = request.json
    sched_id = str(uuid.uuid4())[:8]
    sched = {
        "id": sched_id,
        "time": data["time"],
        "timezone": data["timezone"],
        "test_mode": int(data.get("test_mode", False)),
        "enabled": 1,
    }
    conn = db_conn()
    conn.execute(
        "INSERT INTO schedules (id, time, timezone, test_mode, enabled) VALUES (?, ?, ?, ?, ?)",
        (sched["id"], sched["time"], sched["timezone"], sched["test_mode"], sched["enabled"]),
    )
    conn.commit()
    conn.close()

    add_schedule_to_scheduler(sched)
    return jsonify(sched), 201


@app.route("/api/schedules/<sched_id>", methods=["DELETE"])
def delete_schedule(sched_id):
    conn = db_conn()
    conn.execute("DELETE FROM schedules WHERE id=?", (sched_id,))
    conn.commit()
    conn.close()
    try:
        scheduler.remove_job(f"schedule_{sched_id}")
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/run-now", methods=["POST"])
def run_now():
    if browser_mgr.is_busy:
        return jsonify({"error": "A run is already in progress. Please wait."}), 409
    data = request.json or {}
    test_mode = data.get("test_mode", False)
    t = threading.Thread(target=execute_run, args=(None, test_mode), daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Run started!"})


@app.route("/api/runs", methods=["GET"])
def get_runs():
    conn = db_conn()
    rows = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/runs/<run_id>/logs", methods=["GET"])
def get_run_logs(run_id):
    # First check in-memory logs (for runs still in progress)
    mem_logs = log_capture.get_run_logs(run_id)
    if mem_logs:
        return jsonify([{"timestamp": e["ts"], "message": e["msg"]} for e in mem_logs])

    # Fall back to database (for completed runs)
    conn = db_conn()
    rows = conn.execute(
        "SELECT timestamp, message FROM run_logs WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify({
        "browser_alive": browser_mgr.is_alive(),
        "browser_busy": browser_mgr.is_busy,
    })


@app.route("/api/logs/stream")
def log_stream():
    """Server-Sent Events endpoint for real-time logs."""
    def generate():
        q = log_capture.subscribe()
        try:
            while True:
                try:
                    entry = q.get(timeout=30)
                    yield f"data: {json.dumps(entry)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            log_capture.unsubscribe(q)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/screenshots/<filename>")
def serve_screenshot(filename):
    return send_from_directory(str(SCREENSHOTS_DIR), filename)


@app.route("/api/screenshots", methods=["GET"])
def list_screenshots():
    """List all screenshots."""
    if not SCREENSHOTS_DIR.exists():
        return jsonify([])
    files = sorted(SCREENSHOTS_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    return jsonify([
        {"name": f.name, "url": f"/screenshots/{f.name}", "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
        for f in files if f.suffix == ".png"
    ][:20])


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()

    # Start persistent browser in background
    print("Initializing persistent browser...")
    browser_thread = threading.Thread(target=browser_mgr.start, daemon=True)
    browser_thread.start()

    # Load saved schedules
    load_schedules_from_db()

    # Start scheduler
    scheduler.start()

    print("\n" + "=" * 60)
    print("  BoldTrail Automation Dashboard")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 60 + "\n")

    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    finally:
        scheduler.shutdown()
        browser_mgr.shutdown()
