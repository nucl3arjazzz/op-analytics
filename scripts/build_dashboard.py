#!/usr/bin/env python3
"""Збирає самодостатній HTML-дашборд по всьому OpenProject (для CTO).

  python scripts/build_dashboard.py [--data data/latest.json] [--config config.json]
                                    [--out out/dashboard.html] [--date РРРР-ММ-ДД]

Метрики потоку рахує наявний .claude/skills/weekly-report/scripts/analyze.py:
один раз по всьому ОП (двічі: без тестових проєктів і з ними) та окремо по кожному проєкту.
Години й навантаження по людях рахуються тут напряму з timeEntries.
Тільки стандартна бібліотека Python. Шаблон: scripts/dashboard_template.html.

Налаштування (необов'язково) у config.json, ключ "dashboard":
  test_projects  назви тестових/демо проєктів: за замовчуванням вони не входять у загальні цифри
  weeks_back     скільки тижнів показувати в трендах (за замовчуванням 12)
  top_n          скільки задач показувати у списках «потребує уваги» (за замовчуванням 8)
  status_groups  групи статусів для стеку: backlog / wip / review / blocked
"""
import argparse
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYZE = ROOT / ".claude" / "skills" / "weekly-report" / "scripts" / "analyze.py"
TEMPLATE = Path(__file__).resolve().parent / "dashboard_template.html"

DASH = {
    "test_projects": ["Demo project", "Scrum project", "TEST_&_DEMO", "TEST_25_GIOC_INFO_BOT"],
    "weeks_back": 12,
    "top_n": 8,
    "status_groups": {
        "backlog": ["New", "Grooming", "To Do"],
        "wip": ["In progress"],
        "review": ["Ready for test"],
        "blocked": ["Block", "Pending"],
    },
}


def to_date(s):
    return date.fromisoformat(s[:10]) if s else None


def monday(d):
    return d - timedelta(days=d.weekday())


def run_analyze(data_path, ref, weeks_back, top_n, exclude=(), project=None):
    """Запускає analyze.py з тимчасовим конфігом і повертає його JSON."""
    cfg = {"weeks_back": weeks_back, "top_n": top_n, "ignore_created_before": None,
           "exclude_projects": list(exclude)}
    with tempfile.TemporaryDirectory() as tmp:
        cfg_f, out_f = Path(tmp) / "cfg.json", Path(tmp) / "m.json"
        cfg_f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        cmd = [sys.executable, str(ANALYZE), "--data", str(data_path), "--out", str(out_f),
               "--config", str(cfg_f), "--date", ref.isoformat()]
        if project:
            cmd += ["--project", project]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        return json.loads(out_f.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "latest.json"))
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--out", default=str(ROOT / "out" / "dashboard.html"))
    ap.add_argument("--date", help="опорна дата РРРР-ММ-ДД (за замовчуванням сьогодні)")
    a = ap.parse_args()

    cfg_all = json.loads(Path(a.config).read_text(encoding="utf-8")) if Path(a.config).exists() else {}
    dash = {**DASH, **cfg_all.get("dashboard", {})}
    weeks_back, top_n = dash["weeks_back"], dash["top_n"]
    tests = list(dash["test_projects"])
    groups = dash["status_groups"]
    status_to_group = {s: g for g, names in groups.items() for s in names}

    data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    ref = date.fromisoformat(a.date) if a.date else date.today()
    wps = {w["id"]: w for w in data["workPackages"]}
    base_url = (data.get("baseUrl") or "").rstrip("/")

    def proj(w):
        return w.get("project") or "Без проєкту"

    # ---------- метрики потоку ----------
    scopes_m = {
        "work": run_analyze(a.data, ref, weeks_back, top_n, exclude=tests),
        "all": run_analyze(a.data, ref, weeks_back, top_n),
    }
    wk_start = date.fromisoformat(scopes_m["all"]["meta"]["weekStart"])
    wk_end = date.fromisoformat(scopes_m["all"]["meta"]["weekEnd"])
    weeks = [wk_start - timedelta(days=7 * k) for k in range(weeks_back - 1, -1, -1)]
    win4_from = wk_end - timedelta(days=27)

    # ---------- години (рахуємо напряму) ----------
    te = [t for t in data["timeEntries"] if t.get("wpId") in wps and t.get("user") and t.get("spentOn")]
    first_entry = min((to_date(t["spentOn"]) for t in te), default=None)
    # перший повний тиждень, за який години вже зібрані (ліве вікно історії зазвичай обрізає тиждень)
    cover_from = None
    if first_entry:
        cover_from = first_entry if first_entry.weekday() == 0 else monday(first_entry) + timedelta(days=7)

    def hours_scope(exclude):
        weekly = {w: 0.0 for w in weeks}
        people = defaultdict(lambda: {"hours4w": 0.0, "hoursWeek": 0.0})
        for t in te:
            if proj(wps[t["wpId"]]) in exclude:
                continue
            d, h = to_date(t["spentOn"]), t["hours"] or 0
            if monday(d) in weekly:
                weekly[monday(d)] += h
            if win4_from <= d <= wk_end:
                people[t["user"]]["hours4w"] += h
            if wk_start <= d <= wk_end:
                people[t["user"]]["hoursWeek"] += h
        series = [None if (cover_from and w < cover_from) or not cover_from else round(weekly[w], 1) for w in weeks]
        ppl = sorted(({"name": n, "hours4w": round(v["hours4w"], 1), "hoursWeek": round(v["hoursWeek"], 1)}
                      for n, v in people.items() if v["hours4w"] > 0), key=lambda p: -p["hours4w"])
        return series, ppl

    def with_project(rows):
        return [{**r, "project": proj(wps[r["id"]]), "url": f"{base_url}/work_packages/{r['id']}"} for r in rows]

    scopes = {}
    for key, m in scopes_m.items():
        excl = tests if key == "work" else []
        series, ppl = hours_scope(excl)
        ov, hy = m["overview"], m["hygiene"]
        scopes[key] = {
            "overview": ov,
            "byStatusOpen": ov["byStatusOpen"],
            "flow": m["flow"],
            "trend": m["trend"],
            "overdueCount": m["deadlines"]["overdueCount"],
            "overdue": with_project(m["deadlines"]["overdue"]),
            "dueSoonCount": m["deadlines"]["dueSoonCount"],
            "agingWipCount": m["aging"]["wipOverCount"],
            "agingWip": with_project(m["aging"]["wipOver"]),
            "reviewOverCount": m["aging"]["reviewOverCount"],
            "reopened4w": m["rework"]["reopened4w"],
            "bulkClosing": m["bulkClosing"],
            "reviewBuckets": m["aging"]["reviewBuckets"],
            "openNoDueDate": hy["openNoDueDate"],
            "openNoAssignee": hy["openNoAssignee"],
            "openWithEstimate": hy["openWithEstimate"],
            "hoursWeekly": series,
            "people": ppl,
            "projects": sum(1 for p in {proj(w) for w in data["workPackages"]} if key == "all" or p not in tests),
        }

    # ---------- по проєктах ----------
    last_upd = defaultdict(str)
    for w in data["workPackages"]:
        last_upd[proj(w)] = max(last_upd[proj(w)], w.get("updatedAt") or "")
    hours4w_p = defaultdict(float)
    for t in te:
        if win4_from <= to_date(t["spentOn"]) <= wk_end:
            hours4w_p[proj(wps[t["wpId"]])] += t["hours"] or 0

    rows = []
    for name in sorted({proj(w) for w in data["workPackages"]}):
        m = run_analyze(a.data, ref, weeks_back, top_n, project=name)
        ov, st = m["overview"], m["overview"]["byStatusOpen"]
        g = defaultdict(int)
        for s, n in st.items():
            g[status_to_group.get(s, "backlog")] += n
        done_series = [t["done"] for t in m["trend"]]
        created_series = [t["created"] for t in m["trend"]]
        lu = last_upd[name][:10]
        stale = bool(lu) and ov["openLeaf"] > 0 and (ref - to_date(lu)).days > 28
        reasons = []
        if m["deadlines"]["overdueCount"]:
            reasons.append(f"прострочено: {m['deadlines']['overdueCount']}")
        if m["aging"]["wipOverCount"]:
            reasons.append(f"у роботі понад {m['meta']['config']['aging_days']} дн.: {m['aging']['wipOverCount']}")
        if m["aging"]["reviewOverCount"]:
            reasons.append(f"на тесті понад {m['meta']['config']['review_aging_days']} дн.: {m['aging']['reviewOverCount']}")
        if g["blocked"]:
            reasons.append(f"заблоковано/очікує: {g['blocked']}")
        if stale:
            reasons.append("немає змін понад 28 днів")
        level = "idle" if ov["openLeaf"] == 0 else ("attention" if reasons else "ok")
        od = m["deadlines"]["overdue"]
        rows.append({
            "name": name, "isTest": name in tests,
            "open": ov["openLeaf"], "backlog": g["backlog"], "wip": g["wip"], "review": g["review"],
            "blocked": g["blocked"],
            "done4w": sum(done_series[-4:]), "created4w": sum(created_series[-4:]),
            "doneSeries": done_series,
            "overdue": m["deadlines"]["overdueCount"], "overdueMaxDays": od[0]["overdueDays"] if od else 0,
            "agingWip": m["aging"]["wipOverCount"], "reviewOver": m["aging"]["reviewOverCount"],
            "leadMedian": m["flow"]["current28d"]["lead"]["median"],
            "cycleMedian": m["flow"]["current28d"]["cycle"]["median"],
            "hours4w": round(hours4w_p.get(name, 0.0), 1),
            "lastUpdate": lu or None, "level": level, "reasons": reasons,
        })

    payload = {
        "meta": {
            "generatedAt": data["generatedAt"], "baseUrl": base_url, "refDate": ref.isoformat(),
            "weekStart": wk_start.isoformat(), "weekEnd": wk_end.isoformat(),
            "weeks": [w.isoformat() for w in weeks],
            "hoursCoverFrom": cover_from.isoformat() if cover_from else None,
            "timeLookbackDays": data.get("timeLookbackDays"),
            "statusHistoryUnparsed": data.get("statusHistoryUnparsed"),
            "testProjects": tests,
            "agingDays": scopes_m["all"]["meta"]["config"]["aging_days"],
            "totalWorkPackages": len(data["workPackages"]),
        },
        "groups": list(groups.keys()),
        "scopes": scopes,
        "projects": rows,
    }

    js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", js)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    ow = scopes["work"]["overview"]
    print(f"Готово: {out} ({out.stat().st_size // 1024} КБ). Проєктів: {len(rows)}, "
          f"відкритих (без тестових): {ow['openLeaf']}, закрито за тиждень: {ow['doneWeek']}")


if __name__ == "__main__":
    main()
