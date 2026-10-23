"""Corre una proyección con el escrutinio actual y actualiza site/data/<país>.json.

  python run_live.py br data/br_actual.csv            # una vez
  watch -n 120 python run_live.py br data/br_actual.csv   # cada 2 minutos

El escrutinio tiene que estar en formato canónico (ver adapters/canonical.py). Para cada país,
escribí un pequeño script que baje el feed oficial y lo convierta a ese formato.
"""
import sys, json, datetime as dt
from pathlib import Path
import numpy as np
from adapters.canonical import load_base, load_current
from engine.model import Base, DEFAULTS, project
from engine.rules import RULES
from engine.output import frame, geo_index
from engine.analysis import analyze
from engine.polls import poll_shares

ROOT = Path(__file__).resolve().parent


def main(country, current_path):
    cfg = json.loads((ROOT / "config" / f"{country}.json").read_text(encoding="utf-8"))
    pf = ROOT / cfg["params"]
    if not pf.exists():                       # país sin backtest propio todavía: parámetros de EEUU
        print(f"aviso: falta {pf.name}, uso config/params_us.json")
        pf = ROOT / "config" / "params_us.json"
    params = dict(DEFAULTS, **json.loads(pf.read_text(encoding="utf-8")))
    base = Base(load_base(ROOT / cfg["base"], cfg["groups"]), cfg["groups"])
    cur = load_current(current_path, list(cfg["candidates"]))
    # encuestas: lista de encuestas (se promedian estilo Silver) o shares ya promediados
    polls = poll_shares(cfg.get("polls"), list(cfg["candidates"]))
    if polls and isinstance(cfg.get("polls"), dict) and "_source" in cfg["polls"]:
        polls["_source"] = cfg["polls"]["_source"]
    if polls and cfg.get("polls_prior"):
        params["polls"] = polls          # prior opcional: ver engine/polls.py y el README
    out = project(base, cur, cfg["candidates"], params, RULES[cfg["rule"]](**cfg.get("rule_args", {})))
    path = ROOT / "site" / "data" / f"{country}.json"
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if doc.get("mode") != "live":                     # había una repetición: la noche arranca de cero
        doc = {k: v for k, v in doc.items() if k == "backtest"}
    hist = [h for h in doc.get("history", []) if h["counted"] < out["counted_frac"] - 1e-4]
    geo = geo_index(base, cfg)
    fr = frame(out, dt.datetime.now().isoformat(timespec="seconds"), geo)
    fr["analysis"] = analyze(base, cur, cfg["candidates"], out, polls=polls, scatter=500)
    for h in hist:                                   # la muestra del gráfico sólo en el último frame
        if h.get("analysis"):
            h["analysis"].pop("scatter", None)
        h.pop("map", None)                           # y el mapa por municipio, también
    hist.append(fr)
    doc.update(country=country, mode="live", config={k: cfg[k] for k in cfg if k not in ("base", "params", "party_map", "live_names")},
               regions=out["regions"], history=hist, calib=params["calib"])
    if geo:
        doc["geo"] = geo["doc"]
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    p = np.array(out["proj"]) * 100
    print(f"{out['counted_frac']:.1%} escrutado → " + ", ".join(f"{c} {v:.1f}%" for c, v in zip(out["candidates"], p)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
