"""Regenera la repetición de la noche (site/data/<país>.json) sin volver a correr el backtest.
Usa los parámetros y la calibración guardados en ese mismo archivo y agrega el análisis del cambio.

  python replay.py us
  python replay.py ar
"""
import sys, json
import numpy as np
from engine.model import Base, DEFAULTS, project
from engine.backtest import make_order, snapshot
from engine.rules import RULES
from engine.output import frame, geo_index
from engine.analysis import analyze

SPEC = {
    "us": dict(load=lambda: __import__("adapters.us", fromlist=["x"]).pair(2020, 2024), groups=["gop", "dem", "oth"],
               rule="us_ec_2024", order="huso", seed=5, params="config/params_us.json"),
    "ar": dict(load=lambda: __import__("adapters.ar", fromlist=["x"]).pair(2015, 2019), groups=["peronismo", "jxc", "otros"],
               rule="argentina", order="sesgado", seed=8, params="config/params_us.json"),
    "br": dict(load=lambda: __import__("adapters.br", fromlist=["x"]).pair_turnos(2022), groups=["lula", "bolsonaro"],
               rule="brasil_2t", order="sesgado", seed=8, params="config/params_us.json"),
}


def main(c):
    sp = SPEC[c]
    doc = json.load(open(f"site/data/{c}.json", encoding="utf-8"))
    b, t = sp["load"]()
    base = Base(b, sp["groups"])
    pars = {k: v for k, v in json.load(open(sp["params"])).items() if k != "calib"}
    P = dict(DEFAULTS, **pars, calib=doc["calib"], n_sims=400)
    cand_map = doc["config"]["candidates"]
    inv = {g: n for n, g in cand_map.items()}
    rule = RULES[sp["rule"]]()
    cfg = json.load(open(f"config/{c}.json", encoding="utf-8"))
    geo = geo_index(base, cfg)
    if geo:
        doc["config"]["geo"] = cfg["geo"]
        doc["geo"] = geo["doc"]
    order = make_order(base, t, sp["order"], np.random.default_rng(sp["seed"]))
    cuts = list(np.arange(0.025, 1.0, 0.025)) + [1.0]
    hist = []
    for k, cut in enumerate(cuts):
        cur = snapshot(base, t, order, cut, sp["groups"]).rename(columns=inv)
        out = project(base, cur, cand_map, P, rule)
        fr = frame(out, f"paso {k + 1}", geo)
        fr["analysis"] = analyze(base, cur, cand_map, out, polls=doc["config"].get("polls"),
                                 scatter=500 if (k % 4 == 3 or k == len(cuts) - 1) else 0)
        hist.append(fr)
    doc["history"] = hist
    json.dump(doc, open(f"site/data/{c}.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    a = hist[-1]["analysis"]
    print(c, "margen", a["a"], "−", a["b"], f"cambio {a['margin_delta']*100:+.1f} pts;",
          {k: round(v["delta"] * 100, 1) for k, v in a["change"].items()})
    print("  por tamaño:", [(s["label"], round(s["delta"] * 100, 1)) for s in a["by_size"]])
    print("  regiones extremo:", [(r["region"], round(r["delta"] * 100, 1)) for r in a["by_region"][:3] + a["by_region"][-3:]])
    print("  vueltas:", a["flips"]["to_a"], "hacia", a["a"], "/", a["flips"]["to_b"], "hacia", a["b"],
          "| mismo sentido", round(a["same_dir"], 2), "| R² región", round(a["r2_region"], 2), "| persistencia", round(a["persistence"], 2))


if __name__ == "__main__":
    for c in sys.argv[1:]:
        main(c)
