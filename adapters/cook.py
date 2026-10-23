"""Calificaciones de Cook Political Report desde su API (cookpolitical.com/api/documentation).

La API usa autenticación básica con el mail y la contraseña de una cuenta de Cook con acceso a la API
(se pide desde su página de contacto). Pide no consultarla más de una vez por día.

  set COOK_EMAIL=...  &  set COOK_PASSWORD=...      (Windows; en Linux/Mac: export)
  python -m adapters.cook senado      # actualiza "ratings" y "ratings_source" de config/us_senado.json
  python -m adapters.cook senado --ver   # sólo muestra lo que bajó, sin escribir

Si no hay credenciales o la API falla, no toca nada: quedan las calificaciones que ya estaban.
"""
import base64, datetime as dt, json, os, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.cookpolitical.com/api/race/{kind}"
CONFIG = {"senado": ("senate", "config/us_senado.json"), "gobernador": ("governor", "config/us_gobernador.json")}
ABBR = json.loads('{"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT",'
                  '"Delaware":"DE","Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA",'
                  '"Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI",'
                  '"Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH",'
                  '"New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK",'
                  '"Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN",'
                  '"Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY"}')


def rating_name(x: str):
    """'Lean Democrat', 'Leans R', 'Toss-Up', 'Solid Republican' → la forma de engine/ratings.py."""
    x = x.strip().lower()
    if "toss" in x:
        return "Toss Up"
    lvl = next((l for l in ("solid", "likely", "lean") if x.startswith(l)), None)
    side = "D" if re.search(r"\b(d|dem|democrat|democratic)\b", x) else "R" if re.search(r"\b(r|rep|gop|republican)\b", x) else None
    return f"{lvl.title()} {side}" if lvl and side else None


def fetch(kind, email, password):
    auth = base64.b64encode(f"{email}:{password}".encode()).decode()
    items, page = [], 1
    while page < 20:
        req = urllib.request.Request(URL.format(kind=kind) + f"?page={page}",
                                     headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        rows = data if isinstance(data, list) else data.get("items") or data.get("data") or data.get("results") or []
        if not rows:
            break
        items += rows
        page += 1
    return items


def parse(items):
    """{estado: calificación} y la fecha más reciente. Las especiales (p. ej. Ohio y Florida 2026) van con
    la clave del estado, salvo que el estado tenga también la regular: entonces la especial es <estado>-E."""
    out, dates = {}, []
    get = lambda it, *ks: next((it[k] for k in ks if k in it and it[k] not in (None, "")), None)
    for it in items:
        st = get(it, "State", "state")
        rt = rating_name(str(get(it, "Rating", "rating") or ""))
        if not st or not rt:
            continue
        st = ABBR.get(st, st).upper()
        special = "special" in str(get(it, "Title", "title") or "").lower()
        key = st
        if key in out and special:
            key = st + "-E"
        out[key] = rt
        d = get(it, "Rating_date", "rating_date")
        if d:
            dates.append(str(d)[:10])
    return out, max(dates) if dates else None


def main(which, ver=False):
    kind, path = CONFIG[which]
    email, pw = os.environ.get("COOK_EMAIL"), os.environ.get("COOK_PASSWORD")
    if not email or not pw:
        print("faltan COOK_EMAIL y COOK_PASSWORD: quedan las calificaciones de la config")
        return
    try:
        ratings, date = parse(fetch(kind, email, pw))
    except Exception as e:
        print(f"la API de Cook falló ({e}): quedan las calificaciones de la config")
        return
    cfg = json.loads((ROOT / path).read_text(encoding="utf-8"))
    old = cfg.get("ratings", {})
    falt = sorted(set(old) - set(ratings))
    print(f"{len(ratings)} carreras, al {date}; cambios:",
          {k: f"{old.get(k)} → {v}" for k, v in ratings.items() if old.get(k) != v} or "ninguno")
    if falt:
        print("  sin dato en la API (se mantienen):", falt)
    if ver:
        return
    cfg["ratings"] = {**old, **{k: v for k, v in ratings.items() if k in old or not old}}
    if date:
        d = dt.date.fromisoformat(date)
        cfg["ratings_source"] = f"Cook Political Report, {d.day}/{d.month}/{d.year}"
    (ROOT / path).write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], "--ver" in sys.argv)
