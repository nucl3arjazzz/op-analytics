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


def project_html(m, n, wp_link):
    """Розділ одного проєкту. Блоки, яких немає в narrative або в даних, пропускаються."""
    ov, fl, ag, dl, hy = m["overview"], m["flow"], m["aging"], m["deadlines"], m["hygiene"]
    meta = m["meta"]
    out = []
    if n.get("headline"):
        out.append(f'<p class="lead">{e(n["headline"])}</p>')
    if n.get("summary"):
        out.append("<h3>Головне за тиждень</h3><ul>" + "".join(
            f"<li><strong>{e(s['lead'])}</strong> {e(s['text'])}</li>" for s in n["summary"]) + "</ul>")
    rows = [["Закрито задач", num_td(ov["doneWeek"]), num_td(ov["donePrev"]), num_td(num(ov["doneAvg4"]))],
            ["Створено нових задач", num_td(ov["createdWeek"]), num_td(ov["createdPrev"]), num_td("—")],
            ["Відкритих зараз", num_td(ov["openLeaf"]), num_td("—"), num_td("—")]]
    if ov["wip"] or ov["review"]:
        rows.append(["Із них у роботі / чекає тестування", num_td(f'{ov["wip"]} / {ov["review"]}'), num_td("—"), num_td("—")])
    out.append("<h3>Ключові цифри</h3>" + table(["Показник", "Тиждень", "Попередній", "Середнє за 4 тижні"], rows))
    c, p = fl["current28d"], fl["previous28d"]
    if c["cycle"]["n"] or p["cycle"]["n"]:
        out.append(f'<p class="hint">Cycle time (від початку роботи до закриття), медіана: {num(c["cycle"]["median"])} діб за останні 28 днів '
                   f'проти {num(p["cycle"]["median"])} за попередні; 85-й перцентиль {num(c["cycle"]["p85"])} проти {num(p["cycle"]["p85"])} '
                   f'(вибірка {c["cycle"]["n"]} / {p["cycle"]["n"]} задач).</p>')
    if n.get("flow"):
        out.append("<h3>Рух роботи</h3>" + paras(n["flow"]))
        if any(t["done"] or t["created"] for t in m["trend"]):
            out.append(table(["Тиждень з", "Закрито", "Створено"], [[dm(t["weekStart"]), num_td(t["done"]), num_td(t["created"])] for t in m["trend"]]))
    rel = [x for x in m["people"] if x.get("relevant")]
    if rel or n.get("people"):
        out.append("<h3>Люди та години</h3>" + paras(n.get("people")))
    if rel:
        out.append(table(
            ["Людина", "Годин за тиждень", "Попередній", "Середнє за 4 тижні", "У роботі", "У тесті", "Беклог", "Закрито"],
            [[x["name"], num_td(num(x["hoursWeek"])), num_td(num(x["hoursPrev"])), num_td(num(x["hoursAvg4"])),
              num_td(x["inProgress"]), num_td(x["inReview"]), num_td(x["backlog"]), num_td(x["doneWeek"])] for x in rel]))
        out.append('<p class="hint">Години тут лише за задачами цього проєкту.</p>')
    if n.get("anomalies"):
        out.append("<h3>Аномалії та ризики</h3>" + "".join(f"<h4>{e(x['title'])}</h4>{paras(x['text'])}" for x in n["anomalies"]))
    att = []
    if dl["overdue"]:
        att.append(f"<h4>Прострочені ({dl['overdueCount']}, найстаріші)</h4>" + table(
            ["№", "Задача", "Виконавець", "Статус", "Прострочено, діб"],
            [[wp_link(x["id"]), short(x["subject"]), x["assignee"] or "—", x["status"], num_td(x["overdueDays"])] for x in dl["overdue"]]))
    if dl["dueSoon"]:
        att.append(f"<h4>Дедлайн у найближчі 7 днів ({dl['dueSoonCount']})</h4>" + table(
            ["№", "Задача", "Виконавець", "Статус", "Дедлайн"],
            [[wp_link(x["id"]), short(x["subject"]), x["assignee"] or "—", x["status"], dm(x["dueDate"])] for x in dl["dueSoon"]]))
    if ag["wipOver"]:
        att.append(f"<h4>Давно «в роботі» (понад {meta['config']['aging_days']} днів: {ag['wipOverCount']})</h4>" + table(
            ["№", "Задача", "Виконавець", "Днів у статусі"],
            [[wp_link(x["id"]), short(x["subject"]), x["assignee"] or "—", num_td(x["days"])] for x in ag["wipOver"]]))
    b = ag["reviewBuckets"]
    if sum(b.values()) >= 5:
        att.append("<h4>Скільки задач чекає тестування</h4>" + table(
            ["Вік у черзі", "Задач"], [["до 7 днів", num_td(b["0-7"])], ["8–14 днів", num_td(b["8-14"])], ["15–30 днів", num_td(b["15-30"])], ["понад 30 днів", num_td(b["31+"])]]))
    if att:
        out.append("<h3>Задачі, що потребують уваги</h3>" + "".join(att))
    if n.get("recommendations"):
        out.append("<h3>Що рекомендую зробити</h3><ul>" + "".join(
            f"<li><strong>{e(r['when'])}:</strong> {e(r['text'])}</li>" for r in n["recommendations"]) + "</ul>")
    if n.get("notes"):
        out.append('<h3>Примітки</h3><ul>' + "".join(f"<li>{e(x)}</li>" for x in n["notes"]) + "</ul>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, help="папка з projects.json і metrics/ (результат run_all.py)")
    ap.add_argument("--narrative", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    wd = Path(a.workdir)
    plist = json.loads((wd / "projects.json").read_text(encoding="utf-8"))
    n = json.loads(Path(a.narrative).read_text(encoding="utf-8"))
    pn = n.get("projects", {})
    ms = {p["name"]: json.loads((wd / "metrics" / p["file"]).read_text(encoding="utf-8")) for p in plist}
    first = next(iter(ms.values()))["meta"]
    base = (first.get("baseUrl") or "").rstrip("/")

    def wp_link(i):
        return f'<td class="n"><a href="{e(base)}/work_packages/{i}">{i}</a></td>' if base else num_td(i)

    title = n.get("title", "Звіт по задачах по проєктах")
    period = f"{dm(first['weekStart'])} – {dmy(first['weekEnd'])}"
    shown = [p for p in plist if p["name"] in pn]
    parts = ["<h2>Проєкти</h2>" + table(
        ["Проєкт", "Відкрито", "Закрито за тиждень", "Створено за тиждень", "Годин за тиждень"],
        [[f'<td><a href="#p{i}">{e(p["name"])}</a></td>', num_td(p["open"]), num_td(p["doneWeek"]), num_td(p["createdWeek"]), num_td(num(p["hoursWeek"]))]
         for i, p in enumerate(shown, 1)])]
    for i, p in enumerate(shown, 1):
        parts.append(f'<section id="p{i}"><h2>{i}. {e(p["name"])}</h2>{project_html(ms[p["name"]], pn[p["name"]], wp_link)}</section>')
    gen = first["dataGeneratedAt"][:16].replace("T", " ")
    parts.append(f'<p class="hint">Дані OpenProject станом на {e(gen)} UTC. Години враховують лише записи, які люди внесли до цього моменту. '
                 'Із розрахунків виключено задачі, створені до дати відсічення в config.json (демо й тестові дані).</p>')

    css = """
:root{--bg:#fff;--fg:#1f2328;--mut:#59636e;--line:#d1d9e0;--acc:#1f4e79;--head:#1f4e79;--zebra:#f6f8fa}
:root:not([data-theme=light]){color-scheme:light dark}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--fg:#e6edf3;--mut:#9198a1;--line:#30363d;--acc:#79b8ff;--head:#1f3a5f;--zebra:#161b22}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px;color:var(--acc)}.sub{color:var(--mut);margin:0 0 24px;padding-bottom:12px;border-bottom:2px solid var(--acc)}
h2{font-size:22px;margin:40px 0 10px;color:var(--acc);padding-top:12px;border-top:1px solid var(--line)}h3{font-size:17px;margin:22px 0 6px}h4{font-size:15px;margin:16px 0 4px}
ul{padding-left:22px}li{margin:6px 0}p{margin:8px 0}.hint{color:var(--mut);font-size:14px}.lead{font-size:17px;font-weight:600}
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
