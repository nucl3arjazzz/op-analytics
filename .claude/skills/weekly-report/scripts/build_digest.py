#!/usr/bin/env python3
"""Компактний HTML для тіла листа: по кожному проєкту заголовок, висновок, пункти «Головне» і рекомендації (без таблиць).
  python build_digest.py --workdir work --narrative narrative.json --out digest.html"""
import argparse, html, json
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument("--workdir", required=True); ap.add_argument("--narrative", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
e = lambda x: html.escape(str(x))
pl = json.loads((Path(a.workdir) / "projects.json").read_text(encoding="utf-8"))
n = json.loads(Path(a.narrative).read_text(encoding="utf-8"))
out = [f"<h1>{e(n.get('title',''))}</h1>",
       "<table border='1' cellpadding='4' style='border-collapse:collapse;font-size:13px'><tr><th>Проєкт</th><th>Відкрито</th><th>Закрито</th><th>Створено</th><th>Годин</th></tr>"
       + "".join(f"<tr><td>{e(p['name'])}</td><td>{p['open']}</td><td>{p['doneWeek']}</td><td>{p['createdWeek']}</td><td>{p['hoursWeek']}</td></tr>" for p in pl if p['name'] in n['projects']) + "</table>"]
for p in pl:
    d = n["projects"].get(p["name"])
    if not d: continue
    out.append(f"<h2>{e(p['name'])}</h2><p><b>{e(d.get('headline',''))}</b></p>")
    if d.get("summary"):
        out.append("<ul>" + "".join(f"<li><b>{e(s['lead'])}</b> {e(s['text'])}</li>" for s in d["summary"]) + "</ul>")
    if d.get("recommendations"):
        out.append("<p><i>Що зробити:</i></p><ul>" + "".join(f"<li><b>{e(r['when'])}:</b> {e(r['text'])}</li>" for r in d["recommendations"]) + "</ul>")
Path(a.out).write_text("".join(out), encoding="utf-8"); print(len(''.join(out)))
