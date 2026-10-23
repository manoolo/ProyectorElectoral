"""Calibra el intervalo en 2016→2020 y evalúa fuera de muestra en 2020→2024.
Genera site/data/us.json con el backtest y una repetición de la noche electoral 2024."""
import sys, json, time; sys.path.insert(0, '.')
import numpy as np, pandas as pd
from adapters import us
from engine.model import Base, DEFAULTS, project
from engine.backtest import run, calibrate, make_order, snapshot, CUTS
from engine.rules import RULES

cands = ["dem", "gop", "oth"]
P = dict(DEFAULTS, **json.load(open("config/params_us.json")), n_sims=400)
P["calib"] = 1.0   # la calibración se estima siempre desde intervalos sin escalar
t0 = time.time()

# 1) backtest 2016→2020 y 2) 2020→2024, ambos con intervalos sin escalar (calib=1)
from engine.backtest import coverage
b, t = us.pair(2016, 2020); base = Base(b, us.GROUPS)
cal, info_c = run(base, t, cands, P, rule=RULES["us_ec_2012"](), orders=("sesgado",) * 12 + ("huso",) * 3, cuts=CUTS, seed=21)
b, t = us.pair(2020, 2024); base = Base(b, us.GROUPS)
rule = RULES["us_ec_2024"]()
ev, info = run(base, t, cands, P, rule=rule, orders=("sesgado",) * 12 + ("huso",) * 3, cuts=CUTS, seed=99)
print(round(time.time() - t0), "s")

# calibración cruzada: se calibra con una elección y se mide la cobertura en la otra
c_A, c_B = calibrate(cal, 0), calibrate(ev, 0)
covB, gB = coverage(ev, c_A)
covA, gA = coverage(cal, c_B)
c_pool = calibrate(pd.concat([cal, ev]), 0)
print("calib 2016→20:", c_A); print("calib 2020→24:", c_B); print("calib conjunta:", c_pool)
print(f"cobertura 2024 con calib 2020: {gB:.2f} | cobertura 2020 con calib 2024: {gA:.2f}")
json.dump({**{k: P[k] for k in ["scale", "w_pow", "lam_x", "lam_r", "rho", "k", "h_km", "tau_feat", "t_df"]}, "calib": c_pool},
          open("config/params_us.json", "w"), indent=1)

summ = (ev.groupby(["metodo", "corte"]).agg(mae=("abs_error", "mean"), p90=("abs_error", lambda x: x.quantile(.9)),
                                           regla=("regla_ok", "mean")).reset_index())
summ_c = cal.groupby(["metodo"]).abs_error.mean().mul(100).round(3).to_dict()
print(summ.pivot(index="corte", columns="metodo", values="mae").mul(100).round(2))
print("2016→2020 MAE:", summ_c)
print("regla:", summ.groupby("metodo").regla.mean().round(3).to_dict())
# probabilidades (como evalúa Silver sus pronósticos): Brier de la probabilidad asignada al ganador real
for nm, d in (("2016→20", cal), ("2020→24", ev)):
    x = d[d.metodo == "ensamble"].p_regla.dropna()
    print(f"Brier colegio electoral {nm} (calib=1): {((1 - x) ** 2).mean():.4f}")
P["calib"] = c_A   # la repetición de 2024 usa sólo la calibración de 2020: es fuera de muestra
cov = covB

# 3) repetición de la noche 2024 (orden por husos horarios), en el mismo formato que la página en vivo
from engine.output import frame
cfg = json.load(open("config/us.json"))
inv = {g: c for c, g in cfg["candidates"].items()}
b.to_csv("data/us_base.csv", index=False)
rng = np.random.default_rng(5)
order = make_order(base, t, "huso", rng)
hist = []
for k, cut in enumerate(list(np.arange(0.025, 1.0, 0.025)) + [1.0]):
    cur = snapshot(base, t, order, cut, cands).rename(columns=inv)
    out = project(base, cur, cfg["candidates"], P, rule)
    fr = frame(out, f"paso {k + 1}")
    hist.append(fr)
truth = t.rename(columns=inv)
T = truth[list(cfg["candidates"])].sum()
doc = dict(country="us", mode="replay", config={k: cfg[k] for k in cfg if k not in ("base", "params")},
           regions=out["regions"], history=hist, calib=P["calib"],
           truth=dict(shares=(T / T.sum()).round(4).tolist(), ev={"Trump": 312, "Harris": 226}),
           backtest=dict(cal="2016→2020", eval="2020→2024", cuts=CUTS,
                         methods=["crudo", "swing_reg", "vecinos", "modelo", "ensamble"],
                         mae={m: summ[summ.metodo == m].mae.mul(100).round(3).tolist() for m in ["crudo", "swing_reg", "vecinos", "modelo", "ensamble"]},
                         p90={m: summ[summ.metodo == m].p90.mul(100).round(3).tolist() for m in ["crudo", "swing_reg", "vecinos", "modelo", "ensamble"]},
                         coverage=cov.round(3).tolist(), coverage_global=round(gB, 3), coverage_other=round(gA, 3),
                         mae_2020=summ_c, n_orders=15))
json.dump(doc, open("site/data/us.json", "w"), ensure_ascii=False)
print("listo", round(time.time() - t0), "s")
