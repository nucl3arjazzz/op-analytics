#!/usr/bin/env python3
"""Аналіз data/latest.json: метрики потоку, навантаження, години по людях і аномалії.

Звітний період: останній повний тиждень (пн-нд) перед датою запуску.
Використання:
  python analyze.py --data data/latest.json --out /tmp/metrics.json [--date 2026-10-05] [--config config.json]
Тільки стандартна бібліотека Python.
"""
import argparse
import json
import math
import re
import statistics as S
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULTS = {
    "container_types": ["Epic", "Summary task", "Milestone"],
    "completed_statuses": ["Done"],
    "rejected_statuses": ["Rejected"],
    "wip_statuses": ["In progress"],
    "review_statuses": ["Ready for test"],
    "aging_days": 14,            # скільки днів «в роботі» вважаємо застарілим
    "review_aging_days": 14,     # скільки днів у черзі на тест вважаємо застарілим
    "hours_week_flag": 50,       # годин за тиждень вище цього значення позначаємо
    "hours_day_flag": 12,        # годин за один день вище цього значення позначаємо
    "wip_per_person_flag": 4,    # одночасних задач у роботі в однієї людини
    "pingpong_min": 3,           # скільки разів задача поверталась у роботу
    "bulk_close_min": 15,        # закритих за день, з якого починаємо підозрювати «пачкове» закриття
    "weeks_back": 8,
    "top_n": 10,
    "ignore_created_before": None,   # напр. "2026-01-01": відкидає демо- і тестові задачі
    "exclude_projects": [],          # назви проєктів, які не входять у звіт (потрібне поле project у даних)
}


def to_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def to_date(s):
    return date.fromisoformat(s[:10]) if s else None


def monday(d):
    return d - timedelta(days=d.weekday())


def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, math.ceil(q * len(v)) - 1)], 1)


def med(values):
    return round(S.median(values), 1) if values else None


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", (s or "").lower())).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/latest.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--date", help="опорна дата (РРРР-ММ-ДД), за замовчуванням сьогодні")
    ap.add_argument("--config", help="JSON з перевизначенням порогів і назв статусів")
    ap.add_argument("--project", help="назва проєкту OpenProject: рахувати лише його задачі, години й історію")
    a = ap.parse_args()

    cfg = dict(DEFAULTS)
    if a.config and Path(a.config).exists():
        cfg.update(json.loads(Path(a.config).read_text(encoding="utf-8")))

    data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    n_all = len(data["workPackages"])
    cutoff = cfg["ignore_created_before"]
    data["workPackages"] = [
        w for w in data["workPackages"]
        if not (cutoff and (w.get("createdAt") or "")[:10] < cutoff)
        and w.get("project") not in cfg["exclude_projects"]
    ]
    if a.project:
        data["workPackages"] = [w for w in data["workPackages"] if w.get("project") == a.project]
    n_excluded = n_all - len(data["workPackages"])
    ids = {w["id"] for w in data["workPackages"]}
    data["statusHistory"] = [e for e in data["statusHistory"] if e["wpId"] in ids]
    data["timeEntries"] = [t for t in data["timeEntries"] if t.get("wpId") in ids]
    ref = date.fromisoformat(a.date) if a.date else date.today()
    wk_start = monday(ref) - timedelta(days=7)
    wk_end = wk_start + timedelta(days=6)
    prev_start = wk_start - timedelta(days=7)
    top = cfg["top_n"]

    closed_names = {s["name"] for s in data["statuses"] if s["isClosed"]}
    completed = set(cfg["completed_statuses"])
    wip_st, review_st = set(cfg["wip_statuses"]), set(cfg["review_statuses"])

    wps = {w["id"]: w for w in data["workPackages"]}
    leaf = {i: w for i, w in wps.items() if w["type"] not in cfg["container_types"]}
    open_leaf = {i: w for i, w in leaf.items() if not w["isClosed"]}

    ev = defaultdict(list)
    for e in data["statusHistory"]:
        ev[e["wpId"]].append(e)
    for l in ev.values():
        l.sort(key=lambda e: e["at"])

    def done_date(i):
        l = [to_date(e["at"]) for e in ev.get(i, []) if e["to"] in completed]
        return l[-1] if l else None

    def entered_status(i):
        w = wps[i]
        l = [to_date(e["at"]) for e in ev.get(i, []) if e["to"] == w["status"]]
        return l[-1] if l else to_date(w["createdAt"])

    def in_week(d, start):
        return d is not None and start <= d <= start + timedelta(days=6)

    # ---------- тижні ----------
    weeks = [wk_start - timedelta(days=7 * k) for k in range(cfg["weeks_back"] - 1, -1, -1)]
    done_by_week, created_by_week = Counter(), Counter()
    for i, w in leaf.items():
        d = done_date(i) if w["status"] in completed else None
        if d:
            done_by_week[monday(d)] += 1
        cd = to_date(w["createdAt"])
        if cd:
            created_by_week[monday(cd)] += 1
    trend = [{"weekStart": s.isoformat(), "done": done_by_week[s], "created": created_by_week[s]} for s in weeks]
    done_w, done_p = done_by_week[wk_start], done_by_week[prev_start]
    last4 = [done_by_week[wk_start - timedelta(days=7 * k)] for k in range(1, 5)]

    # ---------- час виконання (cycle / lead) ----------
    def flow_stats(d_from, d_to):
        cyc, lead = [], []
        for i, w in leaf.items():
            if w["status"] not in completed:
                continue
            dd = done_date(i)
            if not dd or not (d_from <= dd <= d_to):
                continue
            lead.append(max(0, (dd - to_date(w["createdAt"])).days))
            st = next((to_date(e["at"]) for e in ev.get(i, []) if e["to"] in wip_st), None)
            if st and st <= dd:
                cyc.append((dd - st).days)
        quick = sum(1 for x in lead if x <= 1)
        return {"cycle": {"n": len(cyc), "median": med(cyc), "p85": pct(cyc, 0.85)},
                "lead": {"n": len(lead), "median": med(lead), "p85": pct(lead, 0.85)},
                "closedWithinDayOfCreation": {"n": quick, "share": round(quick / len(lead), 2) if lead else None}}

    flow_cur = flow_stats(wk_end - timedelta(days=27), wk_end)
    flow_prev = flow_stats(wk_end - timedelta(days=55), wk_end - timedelta(days=28))

    # ---------- «пачкове» закриття ----------
    per_day = Counter()
    for i, w in leaf.items():
        if w["status"] in completed:
            d = done_date(i)
            if d and d >= weeks[0]:
                per_day[d] += 1
    nz = [c for c in per_day.values() if c]
    bulk_days = [{"date": d.isoformat(), "count": c} for d, c in sorted(per_day.items(), key=lambda x: -x[1])[:5]]
    wk_days = {d: c for d, c in per_day.items() if in_week(d, wk_start)}
    wk_top_day = max(wk_days.items(), key=lambda x: x[1]) if wk_days else None
    bulk = {
        "weekTopDay": {"date": wk_top_day[0].isoformat(), "count": wk_top_day[1],
                       "shareOfWeek": round(wk_top_day[1] / max(1, sum(wk_days.values())), 2)} if wk_top_day else None,
        "typicalDayMedian": med(nz),
        "topDays": bulk_days,
        "suspected": bool(wk_top_day and wk_top_day[1] >= cfg["bulk_close_min"]
                          and wk_top_day[1] >= 2.5 * (S.median(nz) if nz else 1)),
    }

    def last_done_event(i):
        l = [e for e in ev.get(i, []) if e["to"] in completed]
        return l[-1] if l else None

    breakdown = Counter()
    for i, w in leaf.items():
        if w["status"] in completed and in_week(done_date(i), wk_start):
            fr = (last_done_event(i) or {}).get("from")
            key = ("createdAlreadyDone" if fr is None else "acceptedFromReview" if fr in review_st
                   else "directFromWip" if fr in wip_st else "fromBacklog")
            breakdown[key] += 1
    if wk_top_day:
        stamps = sorted(e["at"] for i, w in leaf.items() if w["status"] in completed
                        for e in [last_done_event(i)] if e and to_date(e["at"]) == wk_top_day[0])
        bulk["weekTopDay"]["firstAt"], bulk["weekTopDay"]["lastAt"] = stamps[0][11:16], stamps[-1][11:16]

    # ---------- відкриті задачі: статуси, вік ----------
    by_status = Counter(w["status"] for w in open_leaf.values())
    ages = {i: (ref - entered_status(i)).days for i in open_leaf}

    def rowof(i, extra=None):
        w = wps[i]
        r = {"id": i, "subject": w["subject"], "type": w["type"], "status": w["status"],
             "assignee": w["assignee"], "project": w.get("project"), "days": ages.get(i)}
        if extra:
            r.update(extra)
        return r

    aging_wip = sorted([i for i, w in open_leaf.items() if w["status"] in wip_st and ages[i] > cfg["aging_days"]],
                       key=lambda i: -ages[i])
    review_ids = [i for i, w in open_leaf.items() if w["status"] in review_st]
    buckets = {"0-7": 0, "8-14": 0, "15-30": 0, "31+": 0}
    for i in review_ids:
        d = ages[i]
        buckets["0-7" if d <= 7 else "8-14" if d <= 14 else "15-30" if d <= 30 else "31+"] += 1
    review_old = sorted([i for i in review_ids if ages[i] > cfg["review_aging_days"]], key=lambda i: -ages[i])

    # ---------- повернення та пінг-понг ----------
    reopened_w, reopened_4 = [], []
    for i in leaf:
        for e in ev.get(i, []):
            if e["from"] in closed_names and e["to"] not in closed_names:
                d = to_date(e["at"])
                if in_week(d, wk_start):
                    reopened_w.append(i)
                if wk_end - timedelta(days=27) <= d <= wk_end:
                    reopened_4.append(i)
    pingpong = []
    for i, w in open_leaf.items():
        n = sum(1 for e in ev.get(i, []) if e["to"] in wip_st)
        if n >= cfg["pingpong_min"]:
            pingpong.append((n, i))
    pingpong.sort(reverse=True)

    # ---------- люди ----------
    te = defaultdict(list)
    for t in data["timeEntries"]:
        if t["user"]:
            te[t["user"]].append(t)
    people_names = set(te) | {w["assignee"] for w in open_leaf.values() if w["assignee"]}
    people_names |= {w["assignee"] for i, w in leaf.items()
                     if w["assignee"] and w["status"] in completed and in_week(done_date(i), wk_start)}
    people = []
    for n in sorted(people_names):
        entries = te.get(n, [])
        def hrs(start):
            return round(sum(t["hours"] or 0 for t in entries if in_week(to_date(t["spentOn"]), start)), 1)
        daily = Counter()
        for t in entries:
            d = to_date(t["spentOn"])
            if in_week(d, wk_start):
                daily[d] += t["hours"] or 0
        prior = [hrs(wk_start - timedelta(days=7 * k)) for k in range(1, 5)]
        mine = [w for w in open_leaf.values() if w["assignee"] == n]
        wip_n = sum(1 for w in mine if w["status"] in wip_st)
        h = hrs(wk_start)
        flags = []
        if h > cfg["hours_week_flag"]:
            flags.append(f"понад {cfg['hours_week_flag']} год за тиждень")
        if daily and max(daily.values()) > cfg["hours_day_flag"]:
            flags.append(f"понад {cfg['hours_day_flag']} год за один день")
        if h == 0 and wip_n > 0:
            flags.append("є задачі в роботі, але годин не списано")
        if wip_n >= cfg["wip_per_person_flag"]:
            flags.append(f"{wip_n} задач у роботі одночасно")
        people.append({
            "name": n, "hoursWeek": h, "hoursPrev": hrs(prev_start),
            "hoursAvg4": round(sum(prior) / 4, 1), "daysLogged": len(daily),
            "maxDayHours": round(max(daily.values()), 1) if daily else 0,
            "openAssigned": len(mine), "inProgress": wip_n,
            "inReview": sum(1 for w in mine if w["status"] in review_st),
            "backlog": sum(1 for w in mine if w["status"] not in wip_st | review_st),
            "doneWeek": sum(1 for i, w in leaf.items() if w["assignee"] == n and w["status"] in completed
                            and in_week(done_date(i), wk_start)),
            "flags": flags,
        })
        p = people[-1]
        p["relevant"] = bool(h > 0 or p["inProgress"] or p["inReview"] or p["doneWeek"] or p["hoursAvg4"] > 0)
    people.sort(key=lambda p: -(p["hoursWeek"] + p["openAssigned"] / 1000))
    share_top = None
    if open_leaf:
        c = Counter(w["assignee"] for w in open_leaf.values() if w["assignee"])
        if c:
            nm, k = c.most_common(1)[0]
            share_top = {"name": nm, "open": k, "shareOfAssignedOpen": round(k / sum(c.values()), 2)}

    # ---------- гігієна даних ----------
    groups = defaultdict(list)
    for i, w in open_leaf.items():
        groups[norm(w["subject"])].append(i)
    dups = sorted([g for g in groups.values() if len(g) > 1], key=lambda g: -len(g))
    no_assignee = [i for i, w in open_leaf.items() if not w["assignee"]]
    done_week_ids = [i for i, w in leaf.items() if w["status"] in completed and in_week(done_date(i), wk_start)]
    overspent = sorted(
        [(w["spentHours"] / w["estimatedHours"], i) for i, w in leaf.items()
         if w["estimatedHours"] and w["spentHours"] and w["spentHours"] > 2 * w["estimatedHours"]
         and (not w["isClosed"] or in_week(done_date(i), wk_start))], reverse=True)

    # ---------- дедлайни ----------
    overdue = sorted([i for i, w in open_leaf.items() if w["dueDate"] and to_date(w["dueDate"]) < ref],
                     key=lambda i: to_date(wps[i]["dueDate"]))
    soon = sorted([i for i, w in open_leaf.items()
                   if w["dueDate"] and ref <= to_date(w["dueDate"]) <= ref + timedelta(days=7)],
                  key=lambda i: to_date(wps[i]["dueDate"]))

    def withdue(i):
        return rowof(i, {"dueDate": wps[i]["dueDate"],
                         "overdueDays": (ref - to_date(wps[i]["dueDate"])).days})

    # ---------- типи ----------
    c4 = [w for w in leaf.values() if to_date(w["createdAt"]) and wk_end - timedelta(days=27) <= to_date(w["createdAt"]) <= wk_end]
    bug_share = round(sum(1 for w in c4 if w["type"] == "Bug") / len(c4), 2) if c4 else None

    # ---------- покриття даних ----------
    th = Counter()
    for t in data["timeEntries"]:
        th[monday(to_date(t["spentOn"]))] += 1
    out = {
        "meta": {
            "refDate": ref.isoformat(), "project": a.project,
            "weekStart": wk_start.isoformat(), "weekEnd": wk_end.isoformat(),
            "prevWeekStart": prev_start.isoformat(),
            "dataGeneratedAt": data["generatedAt"], "baseUrl": data.get("baseUrl"),
            "excludedWorkPackages": n_excluded,
            "config": {k: cfg[k] for k in ("aging_days", "review_aging_days", "hours_week_flag", "hours_day_flag", "wip_per_person_flag")},
        },
        "overview": {
            "totalLeaf": len(leaf), "openLeaf": len(open_leaf),
            "byStatusOpen": dict(by_status.most_common()),
            "wip": sum(v for k, v in by_status.items() if k in wip_st),
            "review": sum(v for k, v in by_status.items() if k in review_st),
            "backlog": sum(v for k, v in by_status.items() if k not in wip_st | review_st),
            "doneWeek": done_w, "donePrev": done_p,
            "doneAvg4": round(sum(last4) / 4, 1),
            "createdWeek": created_by_week[wk_start], "createdPrev": created_by_week[prev_start],
            "netFlowWeek": created_by_week[wk_start] - done_w,
            "closedBreakdownWeek": {k: breakdown.get(k, 0) for k in ("acceptedFromReview", "directFromWip", "createdAlreadyDone", "fromBacklog")},
            "createdWeekAlreadyClosed": sum(1 for w in leaf.values() if in_week(to_date(w["createdAt"]), wk_start) and w["isClosed"]),
            "rejectedOrClosedOther": sum(1 for w in leaf.values() if w["isClosed"] and w["status"] not in completed),
            "bugShare4w": bug_share,
        },
        "trend": trend,
        "flow": {"current28d": flow_cur, "previous28d": flow_prev},
        "bulkClosing": bulk,
        "aging": {
            "wipOver": [rowof(i) for i in aging_wip[:top]], "wipOverCount": len(aging_wip),
            "reviewBuckets": buckets, "reviewOverCount": len(review_old),
            "reviewOldest": [rowof(i) for i in review_old[:5]],
        },
        "rework": {
            "reopenedWeek": len(set(reopened_w)), "reopened4w": len(set(reopened_4)),
            "pingpong": [rowof(i, {"timesInProgress": n}) for n, i in pingpong[:top]],
            "pingpongCount": len(pingpong),
        },
        "people": people, "topAssignee": share_top,
        "hygiene": {
            "openNoAssignee": len(no_assignee),
            "wipNoAssignee": [rowof(i) for i in no_assignee if wps[i]["status"] in wip_st][:top],
            "openNoDueDate": sum(1 for w in open_leaf.values() if not w["dueDate"]),
            "openWithEstimate": sum(1 for w in open_leaf.values() if w["estimatedHours"]),
            "duplicateGroups": len(dups), "duplicateTasks": sum(len(g) for g in dups),
            "topDuplicates": [{"subject": wps[g[0]]["subject"], "count": len(g),
                               "ids": g[:6]} for g in dups[:5]],
            "doneWeekNoTime": sum(1 for i in done_week_ids if not wps[i]["spentHours"]),
            "doneWeekTotal": len(done_week_ids),
            "overspent": [rowof(i, {"estimatedHours": wps[i]["estimatedHours"],
                                    "spentHours": wps[i]["spentHours"], "ratio": round(r, 1)})
                          for r, i in overspent[:top]],
            "overspentCount": len(overspent),
        },
        "deadlines": {
            "overdueCount": len(overdue), "overdue": [withdue(i) for i in overdue[:top]],
            "dueSoonCount": len(soon), "dueSoon": [withdue(i) for i in soon[:top]],
        },
        "dataQuality": {
            "statusHistoryUnparsed": data.get("statusHistoryUnparsed"),
            "timeEntryWeeks": {k.isoformat(): v for k, v in sorted(th.items())[-8:]},
            "timeLookbackDays": data.get("timeLookbackDays"),
            "peopleWithHoursWeek": sum(1 for p in people if p["hoursWeek"] > 0),
        },
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Готово: {a.out} (тиждень {wk_start}..{wk_end}, закрито {done_w}, відкритих {len(open_leaf)})")


if __name__ == "__main__":
    main()
