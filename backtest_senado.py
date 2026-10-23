"""Backtest del Senado: re-escruta el Senado 2022 condado por condado con la presidencial 2020 como base.

  python -m adapters.us_mid senado 2022 carpeta_zips_medsl   # una vez: arma data/us_sen2022.csv
  python backtest_senado.py                                  # tabla por carrera y por corte
  python backtest_senado.py --lam_r 50 100 200               # compara la fuerza del encogimiento por estado

En cada corte se mide, por carrera, el error del margen D-R proyectado y la probabilidad asignada
al ganador real; y si el control del Senado salió bien. El corte es la fracción de votos contados
en todo el país (las carreras avanzan a distinto ritmo, según el orden de llegada simulado).
"""
import argparse, json, time
import numpy as np, pandas as pd
from engine.model import Base, DEFAULTS, project
from engine.backtest import make_order, snapshot
from engine.rules import RULES
from adapters.us_mid import pair

G = ["gop", "dem", "oth"]
CUTS = [0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 0.90]
# carreras disputadas de 2022 (margen final de menos de 10 puntos)
CLAVE = ["AZ", "GA", "NV", "PA", "WI", "NC", "OH", "NH", "CO", "WA", "IA", "FL", "UT"]


def correr(base, t, P, rule, n_orders, seed=7):
    rng = np.random.default_rng(seed)
    T = t.set_index("unit").loc[base.unit, G].to_numpy(float)
    R = np.zeros((len(base.regions), 3)); np.add.at(R, base.rid, T)
    sh = R / R.sum(1, keepdims=True)
    true_m = sh[:, 1] - sh[:, 0]
    true_ctl = rule(R, G, list(base.regions))["control"]
    rows = []
    kinds = ["huso", "sesgado"] * (n_orders // 2) + ["huso"] * (n_orders % 2)
    for oi, kind in enumerate(kinds):
        order = make_order(base, t, kind, rng)
        for cut in CUTS:
            cur = snapshot(base, t, order, cut, G)
            out = project(base, cur, {g: g for g in G}, P, rule)
            rp = np.array(out["region_proj"])
            m = rp[:, 1] - rp[:, 0]
            lo, hi = np.array(out["region_lo"]), np.array(out["region_hi"])
            r = out["rule"]
            cnt = np.array(out["region_counted"])
            for k, reg in enumerate(base.regions):
                w = "dem" if true_m[k] > 0 else "gop"
                rows.append(dict(orden=oi, tipo=kind, corte=cut, carrera=reg, contado=cnt[k],
                                 error=m[k] - true_m[k], abs_error=abs(m[k] - true_m[k]),
                                 p_ganador=r[f"gana_{reg}"].get(w, 0.0),
                                 acierta=(m[k] > 0) == (true_m[k] > 0),
                                 cubre=(lo[k, 1] - hi[k, 0] <= true_m[k] <= hi[k, 1] - lo[k, 0]),
                                 p_control=r["control"].get(true_ctl, 0.0)))
    return pd.DataFrame(rows), dict(zip(base.regions, true_m)), true_ctl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lam_r", type=float, nargs="*", default=[None])
    ap.add_argument("--orders", type=int, default=6)
    a = ap.parse_args()
    t = pd.read_csv("data/us_sen2022.csv", dtype={"unit": str})
    b, t = pair(2020, t)
    base = Base(b, G)
    us = json.load(open("config/params_us.json"))
    rule = RULES["us_senado_2022"]()
    for lr in a.lam_r:
        P = dict(DEFAULTS, **us, n_sims=300)
        if lr is not None:
            P["lam_r"] = lr
        t0 = time.time()
        df, true_m, ctl = correr(base, t, P, rule, a.orders)
        clave = df[df.carrera.isin(CLAVE)]
        print(f"\n=== lam_r={P['lam_r']}  ({round(time.time() - t0)} s, control real: {ctl})")
        print("error medio del margen D-R en carreras clave, en puntos, por corte:")
        print(clave.groupby("corte").abs_error.mean().mul(100).round(2).to_string())
        print("acierto del ganador (clave):", clave.groupby("corte").acierta.mean().round(2).to_dict())
        print("Brier por carrera (clave):", round(float(((1 - clave.p_ganador) ** 2).mean()), 4))
        print("cobertura aprox. del 90% por carrera:", round(float(clave.cubre.mean()), 2))
        print("prob. media del control real:", df.drop_duplicates(["orden", "corte"]).groupby("corte").p_control.mean().round(2).to_dict())
        print("por carrera (todas los cortes):")
        pc = clave.groupby("carrera").agg(mae=("abs_error", "mean"), p=("p_ganador", "mean"), ok=("acierta", "mean"))
        pc["real"] = pd.Series(true_m) * 100
        print(pc.assign(mae=pc.mae * 100).round(2).to_string())
        df.to_csv(f"data/backtest_senado_{P['lam_r']:g}.csv", index=False)


if __name__ == "__main__":
    main()
