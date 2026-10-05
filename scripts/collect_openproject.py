#!/usr/bin/env python3
"""Збір даних з OpenProject API v3 для тижневої аналітики команди.

Змінні оточення:
  OP_BASE_URL            адреса інстансу, напр. https://openproject.example.com  (обов'язково)
  OP_API_KEY             API-токен користувача (обов'язково; доступ лише на читання)
  OP_PROJECT_ID          id або identifier проєкту; якщо не задано, беруться всі доступні проєкти
  TIME_LOOKBACK_DAYS     скільки днів історії часу забирати (за замовчуванням 90)
  FETCH_ACTIVITIES       "1" (за замовчуванням) тягнути історію статусів по кожній задачі

Результат: data/latest.json і data/snapshots/YYYY-MM-DD.json
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = os.environ.get("OP_BASE_URL", "").rstrip("/")
KEY = os.environ.get("OP_API_KEY", "")
PROJECT = os.environ.get("OP_PROJECT_ID", "").strip()
LOOKBACK = int(os.environ.get("TIME_LOOKBACK_DAYS", "90"))
FETCH_ACTIVITIES = os.environ.get("FETCH_ACTIVITIES", "1") == "1"
PAGE_SIZE = 100

# Тексти змін статусу в журналі залежать від мови користувача, чиїм ключем ми користуємось.
# Додайте свої варіанти, якщо в інтерфейсі інша мова.
STATUS_CHANGE_PATTERNS = [
    re.compile(r"Status changed from\s+(?P<from>.+?)\s+to\s+(?P<to>.+?)\s*$", re.I),
    re.compile(r"Статус\s+змінено\s+з\s+(?P<from>.+?)\s+на\s+(?P<to>.+?)\s*$", re.I),
    re.compile(r"Статус\s+змінен[оа]\s+з\s+(?P<from>.+?)\s+на\s+(?P<to>.+?)\s*$", re.I),
]

_DURATION = re.compile(
    r"^P(?:(?P<d>\d+(?:\.\d+)?)D)?(?:T(?:(?P<h>\d+(?:\.\d+)?)H)?(?:(?P<m>\d+(?:\.\d+)?)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?$"
)


def parse_hours(value):
    """ISO 8601 тривалість (PT2H30M) у години. None, якщо порожньо."""
    if not value:
        return None
    m = _DURATION.match(value)
    if not m:
        return None
    d, h, mi, s = (float(m.group(k) or 0) for k in ("d", "h", "m", "s"))
    return round(d * 24 + h + mi / 60 + s / 3600, 2)


def session():
    if not BASE or not KEY:
        sys.exit("Потрібні змінні оточення OP_BASE_URL і OP_API_KEY")
    s = requests.Session()
    s.auth = ("apikey", KEY)
    s.headers.update({"Accept": "application/json"})
    return s


def get(s, url, params=None, retries=4):
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            time.sleep(2 ** attempt * 2)
            continue
        if r.status_code in (401, 403):
            sys.exit(f"{r.status_code} від {url}: перевірте токен і права на читання")
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def paged(s, url, filters=None, extra=None):
    """Проходить усі сторінки колекції. В OpenProject offset це номер сторінки (з 1)."""
    page = 1
    while True:
        params = {"pageSize": PAGE_SIZE, "offset": page}
        if filters is not None:
            params["filters"] = json.dumps(filters)
        if extra:
            params.update(extra)
        data = get(s, url, params)
        elements = data.get("_embedded", {}).get("elements", [])
        yield from elements
        total = data.get("total", 0)
        if page * PAGE_SIZE >= total or not elements:
            return
        page += 1


def title(el, rel):
    link = (el.get("_links") or {}).get(rel) or {}
    return link.get("title")


def href_id(el, rel):
    link = (el.get("_links") or {}).get(rel) or {}
    h = link.get("href")
    if not h:
        return None
    tail = h.rstrip("/").split("/")[-1]
    return int(tail) if tail.isdigit() else None


def fetch_statuses(s):
    out = {}
    for st in paged(s, f"{BASE}/api/v3/statuses"):
        out[st["name"]] = {"id": st["id"], "name": st["name"], "isClosed": bool(st.get("isClosed"))}
    return out


def fetch_work_packages(s, statuses):
    url = f"{BASE}/api/v3/projects/{PROJECT}/work_packages" if PROJECT else f"{BASE}/api/v3/work_packages"
    # За замовчуванням OpenProject віддає лише відкриті задачі; оператор "*" знімає це обмеження.
    filters = [{"status": {"operator": "*", "values": []}}]
    rows = []
    for wp in paged(s, url, filters=filters, extra={"sortBy": json.dumps([["id", "asc"]])}):
        status = title(wp, "status")
        rows.append({
            "id": wp["id"],
            "subject": wp.get("subject"),
            "type": title(wp, "type"),
            "status": status,
            "isClosed": statuses.get(status, {}).get("isClosed", False),
            "priority": title(wp, "priority"),
            "assignee": title(wp, "assignee"),
            "author": title(wp, "author"),
            "version": title(wp, "version"),
            "parentId": href_id(wp, "parent"),
            "createdAt": wp.get("createdAt"),
            "updatedAt": wp.get("updatedAt"),
            "startDate": wp.get("startDate"),
            "dueDate": wp.get("dueDate"),
            "estimatedHours": parse_hours(wp.get("estimatedTime")),
            "spentHours": parse_hours(wp.get("spentTime")),
            "percentDone": wp.get("percentageDone"),
        })
    return rows


def fetch_status_history(s, wp_ids):
    """Переходи між статусами з журналу змін. Повертає (події, кількість нерозпізнаних записів)."""
    events, unparsed = [], 0
    for wid in wp_ids:
        try:
            data = get(s, f"{BASE}/api/v3/work_packages/{wid}/activities")
        except requests.HTTPError:
            continue
        for act in data.get("_embedded", {}).get("elements", []):
            for d in act.get("details", []) or []:
                raw = (d.get("raw") or "").strip()
                if "status" not in raw.lower() and "статус" not in raw.lower():
                    continue
                for pat in STATUS_CHANGE_PATTERNS:
                    m = pat.search(raw)
                    if m:
                        events.append({
                            "wpId": wid,
                            "at": act.get("createdAt"),
                            "user": title(act, "user"),
                            "from": m.group("from"),
                            "to": m.group("to"),
                        })
                        break
                else:
                    unparsed += 1
    return events, unparsed


def fetch_time_entries(s):
    since = (date.today() - timedelta(days=LOOKBACK)).isoformat()
    filters = [{"spentOn": {"operator": "<>d", "values": [since, date.today().isoformat()]}}]
    if PROJECT:
        filters.append({"project": {"operator": "=", "values": [PROJECT]}})
    rows = []
    for te in paged(s, f"{BASE}/api/v3/time_entries", filters=filters):
        rows.append({
            "id": te["id"],
            "wpId": href_id(te, "workPackage"),
            "user": title(te, "user"),
            "spentOn": te.get("spentOn"),
            "hours": parse_hours(te.get("hours")),
            "activity": title(te, "activity"),
            "comment": ((te.get("comment") or {}).get("raw") or "") or None,
        })
    return rows


def main():
    s = session()
    print("Статуси...")
    statuses = fetch_statuses(s)
    print("Робочі пакети...")
    wps = fetch_work_packages(s, statuses)
    print(f"  отримано {len(wps)}")
    history, unparsed = [], 0
    if FETCH_ACTIVITIES:
        print("Історія статусів...")
        history, unparsed = fetch_status_history(s, [w["id"] for w in wps])
        print(f"  переходів: {len(history)}, нерозпізнаних записів: {unparsed}")
    print("Облік часу...")
    entries = fetch_time_entries(s)
    print(f"  записів: {len(entries)}")

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseUrl": BASE,
        "projectId": PROJECT or None,
        "timeLookbackDays": LOOKBACK,
        "statuses": list(statuses.values()),
        "workPackages": wps,
        "statusHistory": history,
        "statusHistoryUnparsed": unparsed,
        "timeEntries": entries,
    }
    root = Path(__file__).resolve().parent.parent / "data"
    (root / "snapshots").mkdir(parents=True, exist_ok=True)
    payload = json.dumps(out, ensure_ascii=False, indent=1)
    (root / "latest.json").write_text(payload, encoding="utf-8")
    (root / "snapshots" / f"{date.today().isoformat()}.json").write_text(payload, encoding="utf-8")
    print("Готово: data/latest.json")


if __name__ == "__main__":
    main()
