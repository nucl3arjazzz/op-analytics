#!/usr/bin/env python3
"""Рахує метрики окремо по кожному проєкту OpenProject.

  python run_all.py --data data/latest.json --config config.json --outdir work [--date РРРР-ММ-ДД]
Результат: work/metrics/<N>.json на кожен проєкт і work/projects.json (список, відсортований за кількістю відкритих задач).
"""
import argparse, json, subprocess, sys
from collections import Counter
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--data", default="data/latest.json")
ap.add_argument("--config")
ap.add_argument("--outdir", required=True)
ap.add_argument("--date")
a = ap.parse_args()

here = Path(__file__).parent
cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config and Path(a.config).exists() else {}
cutoff, excl = cfg.get("ignore_created_before"), set(cfg.get("exclude_projects", []))
inc = cfg.get("include_projects") or []   # якщо задано, у звіт входять лише ці проєкти, у цьому порядку
data = json.loads(Path(a.data).read_text(encoding="utf-8"))
cnt = Counter(w.get("project") or "Без проєкту" for w in data["workPackages"]
              if not (cutoff and (w.get("createdAt") or "")[:10] < cutoff) and w.get("project") not in excl)
out = Path(a.outdir) / "metrics"
out.mkdir(parents=True, exist_ok=True)
items = []
order = [n for n in inc if n in cnt] if inc else [n for n, _ in cnt.most_common()]
for k, name in enumerate(order, 1):
    f = out / f"{k:02d}.json"
    cmd = [sys.executable, str(here / "analyze.py"), "--data", a.data, "--out", str(f), "--project", name]
    if a.config: cmd += ["--config", a.config]
    if a.date: cmd += ["--date", a.date]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    m = json.loads(f.read_text(encoding="utf-8"))
    ov = m["overview"]
    items.append({"name": name, "file": f.name, "tasks": cnt[name], "open": ov["openLeaf"], "doneWeek": ov["doneWeek"],
                  "createdWeek": ov["createdWeek"], "hoursWeek": round(sum(p["hoursWeek"] for p in m["people"]), 1)})
(Path(a.outdir) / "projects.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
for i in items: print(i)
