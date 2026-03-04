import json
import hashlib
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import timezone
import requests

PDF_URL = "https://static.e-publishing.af.mil/production/1/af_a1/publication/dafi36-2903/dafi36-2903.pdf"
STATE_FILE = Path("state.json")
OUT_FILE = Path("latest_result.json")


def parse_http_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def sha256_bytes(data: bytes) -> str:
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


def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    headers = {"User-Agent": "AF-PDF-Monitor/1.0 (+GitHub Actions)"}

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
        "sha256": None,
        "changed": False,
        "change_reasons": [],
    }

    # Fast metadata check first (HEAD)
    r = requests.head(PDF_URL, headers=headers, allow_redirects=True, timeout=30)
    result["method_used"] = "HEAD"
    result["http_status"] = r.status_code
    result["final_url"] = r.url
    result["content_type"] = r.headers.get("Content-Type")
    result["content_length"] = r.headers.get("Content-Length")
    result["etag"] = r.headers.get("ETag")
    result["last_modified_raw"] = r.headers.get("Last-Modified")
    result["last_modified_utc"] = parse_http_date(result["last_modified_raw"])

    # Download file to compute hash (most reliable change detection)
    g = requests.get(PDF_URL, headers=headers, allow_redirects=True, timeout=60)
    result["http_status"] = g.status_code
    if g.status_code >= 400:
        raise RuntimeError(f"GET failed with status {g.status_code}")
    result["sha256"] = sha256_bytes(g.content)
    result["checked_ok"] = True
    result["method_used"] = "HEAD + GET"

    prev = load_state()

    keys_to_compare = ["etag", "last_modified_raw", "content_length", "sha256"]
    for k in keys_to_compare:
        if prev.get(k) != result.get(k):
            result["change_reasons"].append(
                f"{k}: {prev.get(k)} -> {result.get(k)}"
            )

    result["changed"] = len(result["change_reasons"]) > 0

    save_json(OUT_FILE, result)

    # Save compact state for next run
    new_state = {
        "url": result["url"],
        "etag": result["etag"],
        "last_modified_raw": result["last_modified_raw"],
        "content_length": result["content_length"],
        "sha256": result["sha256"],
    }
    save_json(STATE_FILE, new_state)

    print(json.dumps(result, indent=2))
    if result["changed"]:
        print("UPDATED: Change detected.")
    else:
        print("No change detected.")


if __name__ == "__main__":
    main()
