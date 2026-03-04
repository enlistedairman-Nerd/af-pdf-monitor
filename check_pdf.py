import json
import hashlib
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import timezone, datetime
import requests

PDF_URL = "https://static.e-publishing.af.mil/production/1/af_a1/publication/dafi36-2903/dafi36-2903.pdf"
STATE_FILE = Path("state.json")
OUT_FILE = Path("latest_result.json")


def parse_http_date(value):
    if not value:
        return None, None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.isoformat(), dt_utc
    except Exception:
        return None, None


def sha256_bytes(data):
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_age_visual(days_since):
    if days_since is None:
        return {
            "visual_status": "⚪ Unknown",
            "visual_bar": "□□□□□□□□□□",
            "status_color": "unknown",
        }

    # Thresholds (edit if you want)
    if days_since <= 30:
        status = "🟢 Fresh"
        color = "green"
    elif days_since <= 90:
        status = "🟡 Aging"
        color = "yellow"
    else:
        status = "🔴 Old"
        color = "red"

    # Cap at 180 days for bar display
    cap = 180
    filled = max(0, min(10, round((min(days_since, cap) / cap) * 10)))
    bar = "■" * filled + "□" * (10 - filled)

    return {
        "visual_status": status,
        "visual_bar": bar,
        "status_color": color,
    }


def main():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    now_utc = datetime.now(timezone.utc)

    result = {
        "url": PDF_URL,
        "checked_ok": False,
        "http_status": None,
        "method_used": None,
        "final_url": None,
        "content_type": None,
        "content_length": None,
        "etag": None,
        "last_modified_raw": None,
        "last_modified_utc": None,
        "today_utc": now_utc.isoformat(),
        "today_date_utc": now_utc.strftime("%Y-%m-%d"),
        "days_since_last_update": None,
        "visual_status": None,
        "visual_bar": None,
        "status_color": None,
        "sha256": None,
        "hash_check_skipped": False,
        "hash_check_reason": None,
        "changed": False,
        "change_reasons": [],
    }

    # HEAD request for metadata
    r = requests.head(PDF_URL, headers=headers, allow_redirects=True, timeout=30)
    result["method_used"] = "HEAD"
    result["http_status"] = r.status_code
    result["final_url"] = r.url
    result["content_type"] = r.headers.get("Content-Type")
    result["content_length"] = r.headers.get("Content-Length")
    result["etag"] = r.headers.get("ETag")
    result["last_modified_raw"] = r.headers.get("Last-Modified")
    last_modified_iso, last_modified_dt = parse_http_date(result["last_modified_raw"])
    result["last_modified_utc"] = last_modified_iso

    # Compute age (days since last update)
    if last_modified_dt is not None:
        delta = now_utc - last_modified_dt
        result["days_since_last_update"] = max(0, delta.days)

    visual = build_age_visual(result["days_since_last_update"])
    result.update(visual)

    # Try GET for hash, but don't fail if blocked
    try:
        g = requests.get(PDF_URL, headers=headers, allow_redirects=True, timeout=60)
        if g.status_code < 400:
            result["sha256"] = sha256_bytes(g.content)
            result["method_used"] = "HEAD + GET"
        else:
            result["hash_check_skipped"] = True
            result["hash_check_reason"] = "GET blocked with status {}".format(g.status_code)
    except Exception as e:
        result["hash_check_skipped"] = True
        result["hash_check_reason"] = "GET failed: {}".format(str(e))

    if r.status_code < 400:
        result["checked_ok"] = True

    prev = load_state()

    keys_to_compare = ["etag", "last_modified_raw", "content_length", "sha256"]
    for k in keys_to_compare:
        prev_val = prev.get(k)
        curr_val = result.get(k)

        # Skip hash compare if no hash this run
        if k == "sha256" and curr_val is None:
            continue

        if prev_val != curr_val:
            result["change_reasons"].append("{}: {} -> {}".format(k, prev_val, curr_val))

    result["changed"] = len(result["change_reasons"]) > 0

    save_json(OUT_FILE, result)

    new_state = {
        "url": result["url"],
        "etag": result["etag"],
        "last_modified_raw": result["last_modified_raw"],
        "content_length": result["content_length"],
        "sha256": result["sha256"],
    }
    save_json(STATE_FILE, new_state)

    # Visual console output for GitHub Actions logs
    print("")
    print("=== PDF Update Age Summary ===")
    print("Today (UTC):           {}".format(result["today_date_utc"]))
    print("Last Modified (UTC):   {}".format(result["last_modified_utc"]))
    print("Days Since Update:     {}".format(result["days_since_last_update"]))
    print("Status:                {}".format(result["visual_status"]))
    print("Age Bar:               {}".format(result["visual_bar"]))
    if result["hash_check_skipped"]:
        print("Hash Check:            Skipped ({})".format(result["hash_check_reason"]))
    else:
        print("Hash Check:            Completed")
    print("Changed This Run:      {}".format(result["changed"]))
    print("==============================")
    print("")

    print(json.dumps(result, indent=2))
    if result["changed"]:
        print("UPDATED: Change detected.")
    else:
        print("No change detected.")


main()
