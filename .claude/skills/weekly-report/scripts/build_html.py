#!/usr/bin/env python3
"""Генерує HTML-звіт з metrics.json (цифри) і narrative.json (висновки).

  python build_html.py --metrics metrics.json --narrative narrative.json --out report.html
Одна самодостатня сторінка без зовнішніх залежностей; світла й темна тема.
"""
import argparse
import html
import json
from datetime import date
from pathlib import Path

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def dm(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[d.month - 1]}"


def dmy(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def e(x):
    return html.escape(str(x if x is not None else "—"))


def num(x, nd=None):
    if x is None:
        return "—"
    if isinstance(x, float):
        x = round(x, nd if nd is not None else 1)
        if x == int(x):
            x = int(x)
    return str(x).replace(".", ",")


def short(s, n=80):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def paras(text):
    return "".join(f"<p>{e(p.strip())}</p>" for p in (text or "").split("\n\n") if p.strip())


def table(head, rows, cls=""):
    th = "".join(f"<th>{e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(c if c.startswith("<td") else f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def num_td(x):
    return f'<td class="n">{e(x)}</td>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--narrative", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    m = json.loads(Path(a.metrics).read_text(encoding="utf-8"))
    n = json.loads(Path(a.narrative).read_text(encoding="utf-8"))
    meta, ov, fl = m["meta"], m["overview"], m["flow"]
    base = (meta.get("baseUrl") or "").rstrip("/")

    def wp_link(i):
        return f'<td class="n"><a href="{e(base)}/work_packages/{i}">{i}</a></td>' if base else num_td(i)

    title = n.get("title", "Звіт по задачах команди")
    period = f"{dm(meta['weekStart'])} – {dmy(meta['weekEnd'])}"
    parts = []

    parts.append("<h2>1. Головне за тиждень</h2><ul>" + "".join(
        f"<li><strong>{e(s['lead'])}</strong> {e(s['text'])}</li>" for s in n.get("summary", [])) + "</ul>")

    # --- ключові цифри
    rows = [
        ["Закрито задач", num_td(ov["doneWeek"]), num_td(ov["donePrev"]), num_td(num(ov["doneAvg4"]))],
        ["Створено нових задач", num_td(ov["createdWeek"]), num_td(ov["createdPrev"]), num_td("—")],
        ["Зараз у роботі", num_td(ov["wip"]), num_td("—"), num_td("—")],
        ["Зараз чекає тестування", num_td(ov["review"]), num_td("—"), num_td("—")],
        ["Зараз у беклозі", num_td(ov["backlog"]), num_td("—"), num_td("—")],
    ]
    parts.append("<h2>2. Ключові цифри</h2>" + table(["Показник", "Тиждень", "Попередній", "Середнє за 4 тижні"], [[r[0]] + r[1:] for r in rows]))
    c, p = fl["current28d"], fl["previous28d"]
    parts.append("<h3>Швидкість виконання, останні 28 днів</h3>" + table(
        ["Показник", "Останні 28 днів", "Попередні 28 днів"],
        [["Cycle time, медіана (діб)", num_td(num(c["cycle"]["median"])), num_td(num(p["cycle"]["median"]))],
         ["Cycle time, 85-й перцентиль (діб)", num_td(num(c["cycle"]["p85"])), num_td(num(p["cycle"]["p85"]))],
         ["Lead time, медіана (діб)", num_td(num(c["lead"]["median"])), num_td(num(p["lead"]["median"]))],
         ["Lead time, 85-й перцентиль (діб)", num_td(num(c["lead"]["p85"])), num_td(num(p["lead"]["p85"]))],
         ["Закрито у день створення", num_td(f'{c["closedWithinDayOfCreation"]["n"]} ({round((c["closedWithinDayOfCreation"]["share"] or 0) * 100)}%)'),
          num_td(f'{p["closedWithinDayOfCreation"]["n"]} ({round((p["closedWithinDayOfCreation"]["share"] or 0) * 100)}%)')],
         ["Задач у вибірці (cycle / lead)", num_td(f'{c["cycle"]["n"]} / {c["lead"]["n"]}'), num_td(f'{p["cycle"]["n"]} / {p["lead"]["n"]}')]]))
    parts.append('<p class="hint">Cycle time рахується від першого переходу в «In progress» до «Done», lead time від створення до «Done».</p>')

    # --- рух роботи
    parts.append("<h2>3. Рух роботи</h2>" + paras(n.get("flow")))
    parts.append(table(["Тиждень з", "Закрито", "Створено"], [[dm(t["weekStart"]), num_td(t["done"]), num_td(t["created"])] for t in m["trend"]]))

    # --- люди
    rel = [x for x in m["people"] if x.get("relevant")]
    rest = len(m["people"]) - len(rel)
    parts.append("<h2>4. Навантаження та години по людях</h2>" + paras(n.get("people")))
    parts.append(table(
        ["Людина", "Годин за тиждень", "Попередній", "Середнє за 4 тижні", "У роботі", "У тесті", "Беклог", "Закрито"],
        [[x["name"], num_td(num(x["hoursWeek"])), num_td(num(x["hoursPrev"])), num_td(num(x["hoursAvg4"])),
          num_td(x["inProgress"]), num_td(x["inReview"]), num_td(x["backlog"]), num_td(x["doneWeek"])] for x in rel]))
    notes = [f"<li><strong>{e(x['name'])}:</strong> {e('; '.join(x['flags']))}.</li>" for x in rel if x["flags"]]
    if notes:
        parts.append('<h3>Що привертає увагу</h3><ul>' + "".join(notes) + "</ul>")
    if rest:
        parts.append(f'<p class="hint">Ще {rest} осіб мають задачі в беклозі, але без активності за період, у таблиці не показані.</p>')

    # --- аномалії
    parts.append("<h2>5. Аномалії та ризики</h2>" + "".join(
        f"<h3>{e(x['title'])}</h3>{paras(x['text'])}" for x in n.get("anomalies", [])))

    # --- задачі
    dl, ag = m["deadlines"], m["aging"]
    parts.append("<h2>6. Задачі, що потребують уваги</h2>")
    if dl["overdue"]:
        parts.append(f"<h3>Прострочені ({dl['overdueCount']}, найстаріші)</h3>" + table(
            ["№", "Задача", "Виконавець", "Статус", "Прострочено, діб"],
            [[wp_link(x["id"]), short(x["subject"]), x["assignee"] or "—", x["status"], num_td(x["overdueDays"])] for x in dl["overdue"]]))
    if dl["dueSoon"]:
        parts.append(f"<h3>Дедлайн у найближчі 7 днів ({dl['dueSoonCount']})</h3>" + table(
            ["№", "Задача", "Виконавець", "Статус", "Дедлайн"],
            [[wp_link(x["id"]), short(x["subject"]), x["assignee"] or "—", x["status"], dm(x["dueDate"])] for x in dl["dueSoon"]]))
    if ag["wipOver"]:
        parts.append(f"<h3>Давно «в роботі» (понад {meta['config']['aging_days']} днів: {ag['wipOverCount']})</h3>" + table(
            ["№", "Задача", "Виконавець", "Днів у статусі"],
            [[wp_link(x["id"]), short(x["subject"]), x["assignee"] or "—", num_td(x["days"])] for x in ag["wipOver"]]))
    b = ag["reviewBuckets"]
    parts.append("<h3>Скільки задач чекає тестування</h3>" + table(
        ["Вік у черзі", "Задач"], [["до 7 днів", num_td(b["0-7"])], ["8–14 днів", num_td(b["8-14"])], ["15–30 днів", num_td(b["15-30"])], ["понад 30 днів", num_td(b["31+"])]]))

    # --- рекомендації
    parts.append("<h2>7. Що рекомендую зробити</h2><ul>" + "".join(
        f"<li><strong>{e(r['when'])}:</strong> {e(r['text'])}</li>" for r in n.get("recommendations", [])) + "</ul>")

    # --- примітки
    dq, hy = m["dataQuality"], m["hygiene"]
    auto = [f"Із розрахунків виключено {meta['excludedWorkPackages']} демонстраційних і тестових задач." if meta.get("excludedWorkPackages") else None,
            f"Цифри за годинами враховують лише записи, які люди внесли в OpenProject до моменту збору даних ({meta['dataGeneratedAt'][:16].replace('T', ' ')} UTC).",
            f"Дати завершення проставлені не в усіх задачах: без дедлайну {hy['openNoDueDate']} із {ov['openLeaf']} відкритих."]
    parts.append("<h2>8. Примітки до даних</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in (auto + n.get("notes", [])) if x) + "</ul>")

    css = """
:root{--bg:#fff;--fg:#1f2328;--mut:#59636e;--line:#d1d9e0;--acc:#1f4e79;--head:#1f4e79;--zebra:#f6f8fa}
:root:not([data-theme=light]){color-scheme:light dark}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--fg:#e6edf3;--mut:#9198a1;--line:#30363d;--acc:#79b8ff;--head:#1f3a5f;--zebra:#161b22}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px;color:var(--acc)}.sub{color:var(--mut);margin:0 0 24px;padding-bottom:12px;border-bottom:2px solid var(--acc)}
h2{font-size:20px;margin:32px 0 10px;color:var(--acc)}h3{font-size:16px;margin:20px 0 6px}
ul{padding-left:22px}li{margin:6px 0}p{margin:8px 0}.hint{color:var(--mut);font-size:14px}
.tw{overflow-x:auto;margin:8px 0 12px}table{border-collapse:collapse;width:100%;font-size:14px}
th{background:var(--head);color:#fff;text-align:left;padding:7px 10px;font-weight:600}
td{padding:6px 10px;border:1px solid var(--line);vertical-align:top}td.n{text-align:center;white-space:nowrap}
tbody tr:nth-child(even){background:var(--zebra)}a{color:var(--acc)}
"""
    doc = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{css}</style></head><body><main>
<h1>{e(title)}</h1><p class="sub">{e(n.get('subtitle', ''))} · тиждень {e(period)}</p>
{''.join(parts)}
</main></body></html>"""
    Path(a.out).write_text(doc, encoding="utf-8")
    print("Готово:", a.out)


if __name__ == "__main__":
    main()
