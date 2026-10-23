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
# calificaciones finales de Cook para 2022 (4/11/2022), reconstruidas: Wisconsin a Lean R el 4/11 está
# confirmado; las demás, de memoria de las notas de esos días. Las no listadas, Solid del partido que ganó.
COOK_2022 = {"AZ": "Toss Up", "GA": "Toss Up", "NV": "Toss Up", "PA": "Toss Up", "NH": "Lean D",
             "WI": "Lean R", "NC": "Lean R", "OH": "Lean R", "CO": "Likely D", "WA": "Likely D",
             "FL": "Likely R", "UT": "Likely R", "IA": "Likely R"}


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
                                 cubre=(lo[k, 1] - hi[k, 0] - 1e-6 <= true_m[k] <= hi[k, 1] - lo[k, 0] + 1e-6),
                                 p_control=r["control"].get(true_ctl, 0.0)))
    return pd.DataFrame(rows), dict(zip(base.regions, true_m)), true_ctl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lam_r", type=float, nargs="*", default=[None])
    ap.add_argument("--orders", type=int, default=6)
    ap.add_argument("--cook", type=float, nargs="*", default=[0], help="peso del prior de calificaciones (0 = sin)")
    ap.add_argument("--pvi", action="store_true", help="base 75/25 de 2020 y 2016, como el PVI de Cook")
    a = ap.parse_args()
    t = pd.read_csv("data/us_sen2022.csv", dtype={"unit": str})
    b, t = pair(2020, t, pvi=a.pvi)
    base = Base(b, G)
    us = json.load(open("config/params_us.json"))
    rule = RULES["us_senado_2022"]()
    solid = {r: ("Solid D" if t[t.region == r].dem.sum() > t[t.region == r].gop.sum() else "Solid R") for r in base.regions}
    for lr, ck in [(x, y) for x in a.lam_r for y in a.cook]:
        P = dict(DEFAULTS, **us, n_sims=300)
        if lr is not None:
            P["lam_r"] = lr
        if ck:
            P.update(ratings={**solid, **COOK_2022}, ratings_w=ck)
        t0 = time.time()
        df, true_m, ctl = correr(base, t, P, rule, a.orders)
        clave = df[df.carrera.isin(CLAVE)]
        print(f"\n=== lam_r={P['lam_r']} cook={ck} pvi={a.pvi}  ({round(time.time() - t0)} s, control real: {ctl})")
        print("error medio del margen D-R en carreras clave, en puntos, por corte:")
        print(clave.groupby("corte").abs_error.mean().mul(100).round(2).to_string())
        print("acierto del ganador (clave):", clave.groupby("corte").acierta.mean().round(2).to_dict())
        print("Brier por carrera (clave):", round(float(((1 - clave.p_ganador) ** 2).mean()), 4))
        abiertas = clave[clave.contado < 0.999]
        print("cobertura aprox. del 90% por carrera (sin terminar de contar):", round(float(abiertas.cubre.mean()), 2),
              abiertas.groupby("corte").cubre.mean().round(2).to_dict())
        print("prob. media del control real:", df.drop_duplicates(["orden", "corte"]).groupby("corte").p_control.mean().round(2).to_dict())
        print("por carrera (todas los cortes):")
        pc = clave.groupby("carrera").agg(mae=("abs_error", "mean"), p=("p_ganador", "mean"), ok=("acierta", "mean"))
        pc["real"] = pd.Series(true_m) * 100
        print(pc.assign(mae=pc.mae * 100).round(2).to_string())
        df.to_csv(f"data/backtest_senado_{P['lam_r']:g}_{ck:g}{'_pvi' if a.pvi else ''}.csv", index=False)


if __name__ == "__main__":
    main()
