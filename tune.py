"""Elige hiperparámetros en una elección de calibración (sin mirar la de evaluación)."""
import sys, itertools, json, time; sys.path.insert(0, '.')
import numpy as np, pandas as pd
from adapters import us
from engine.model import Base, DEFAULTS
from engine.backtest import run

b, t = us.pair(2016, 2020)
base = Base(b, us.GROUPS)
cands = ["dem", "gop", "oth"]
grid = dict(scale=['logratio'], lam_r=[20, 80, 200], lam_x=[30, 100], rho=[0.0, 0.4], k=[20], h_km=[150, 300])
res = []
t0 = time.time()
for vals in itertools.product(*grid.values()):
    p = dict(DEFAULTS, **dict(zip(grid, vals)))
    df, _ = run(base, t, cands, p, orders=("sesgado",) * 5 + ("huso",), cuts=[.05, .1, .2, .3, .5, .7],
                sims=False, methods=("ensamble",), seed=11)
    res.append(dict(zip(grid, vals), mae=df.abs_error.mean() * 100, mae_early=df[df.corte <= .2].abs_error.mean() * 100,
                    reg=df.regiones_ok.mean()))
r = pd.DataFrame(res).sort_values("mae")
print(r.head(10).to_string()); print(r.tail(3).to_string()); print(round(time.time() - t0), "s")
best = r.iloc[0][list(grid)].to_dict(); best["k"] = int(best["k"])
best = {k: (v.item() if hasattr(v, "item") else v) for k, v in best.items()}
json.dump(best, open("config/params_us.json", "w"), indent=1); print(best)
