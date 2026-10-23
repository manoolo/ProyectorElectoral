"""Backtest de un país con los parámetros elegidos en EEUU (fuera de muestra entre países) y
repetición de su última elección para la página.

  python backtest_pais.py ar      # Argentina 2015→2019 (datos de electorAr, se bajan solos)
  python backtest_pais.py br      # Brasil 2018→2022 (baja los zips del TSE; correr en tu máquina)
"""
import sys, json, time
import numpy as np, pandas as pd
from engine.model import Base, DEFAULTS, project
from engine.backtest import run, calibrate, coverage, make_order, snapshot, CUTS
from engine.rules import RULES
from engine.output import frame

PAISES = {
    "ar": dict(load=lambda: __import__("adapters.ar", fromlist=["x"]).pair(2015, 2019),
               groups=["peronismo", "jxc", "otros"], rule="argentina", title="Argentina 2019",
               names={"peronismo": "Fernández", "jxc": "Macri", "otros": "Otros"},
               colors={"Fernández": "#2a8fd6", "Macri": "#e0b21b", "Otros": "#8a8f98"},
               sub="Reproduce el escrutinio provisorio de 2019 circuito por circuito, con la base 2015, en un orden de llegada simulado con sesgo. Mové el control para ver qué decía la proyección en cada momento.",
               truth_text="Resultado real: Fernández ganó en primera vuelta con 48,2%."),
    "br": dict(load=lambda: __import__("adapters.br", fromlist=["x"]).pair(2018, 2022),
               groups=["lula", "bolsonaro", "otros"], rule="brasil", title="Brasil 2022",
               names={"lula": "Lula", "bolsonaro": "Bolsonaro", "otros": "Otros"},
               colors={"Lula": "#c8323a", "Bolsonaro": "#1f4e9c", "Otros": "#8a8f98"},
               sub="Reproduce la primera vuelta de 2022 municipio por municipio, con la base 2018 (Haddad como base de Lula), en un orden de llegada simulado con sesgo.",
               truth_text="Resultado real: Lula 48,4%, Bolsonaro 43,2%; hubo segunda vuelta."),
}


def main(c):
    t0 = time.time()
    spec = PAISES[c]
    G = spec["groups"]
    b, t = spec["load"]()
    base = Base(b, G)
    us = json.load(open("config/params_us.json"))
    P = dict(DEFAULTS, **{k: v for k, v in us.items() if k != "calib"}, calib=1.0, n_sims=400)
    rule = RULES[spec["rule"]]()
    cands = list(G)  # en el backtest los candidatos son los grupos
    df, info = run(base, t, cands, P, rule=rule, orders=("sesgado",) * 12 + ("aleatorio",) * 3, cuts=CUTS, seed=31)
    print(f"backtest listo en {round(time.time() - t0)} s")
    cov_us, g_us = coverage(df, us["calib"])            # calibración de EEUU aplicada a otro país
    c_own = calibrate(df, 0)
    # calibración para uso en vivo: promedio de la conjunta de EEUU y la propia del país
    xs = [x for x, _ in us["calib"]]
    c_mix = [[x, round((np.interp(x, *zip(*us["calib"])) + np.interp(x, *zip(*c_own))) / 2, 3)] for x in xs]
    json.dump({**{k: P[k] for k in ["scale", "w_pow", "lam_x", "lam_r", "rho", "k", "h_km", "tau_feat", "t_df"]}, "calib": c_mix},
              open(f"config/params_{c}.json", "w"), indent=1)
    summ = df.groupby(["metodo", "corte"]).agg(mae=("abs_error", "mean"), regla=("regla_ok", "mean")).reset_index()
    methods = ["crudo", "swing_reg", "vecinos", "modelo", "ensamble"]
    print(summ.pivot(index="corte", columns="metodo", values="mae").mul(100).round(2))
    print("MAE medio:", df.groupby("metodo").abs_error.mean().mul(100).round(3).to_dict())
    print("regla ok:", df.groupby("metodo").regla_ok.mean().round(3).to_dict())
    print(f"cobertura con la calibración de EEUU: {g_us:.2f}", cov_us.round(2).to_dict())

    # repetición para la página
    names = spec["names"]
    cand_map = {names[g]: g for g in G}
    P["calib"] = us["calib"]
    rng = np.random.default_rng(8)
    order = make_order(base, t, "sesgado", rng)
    hist = []
    for k, cut in enumerate(list(np.arange(0.025, 1.0, 0.025)) + [1.0]):
        cur = snapshot(base, t, order, cut, G).rename(columns=names)
        out = project(base, cur, cand_map, P, rule)
        hist.append(frame(out, f"paso {k + 1}"))
    T = t[G].sum()
    cfg = json.load(open(f"config/{c}.json"))
    doc = dict(country=c, mode="replay",
               config=dict(cfg, candidates=cand_map, colors=spec["colors"], title=spec["title"]),
               regions=out["regions"], history=hist, calib=us["calib"], replay_sub=spec["sub"],
               truth=dict(shares=(T / T.sum()).round(4).tolist(), text=spec["truth_text"]),
               backtest=dict(cal="EEUU", eval=spec["title"], cuts=CUTS, methods=methods,
                             mae={m: summ[summ.metodo == m].mae.mul(100).round(3).tolist() for m in methods},
                             mae_all={m: round(float(df[df.metodo == m].abs_error.mean() * 100), 3) for m in methods},
                             regla={m: round(float(df[df.metodo == m].regla_ok.mean()), 3) for m in methods},
                             coverage=cov_us.round(3).tolist(), coverage_global=round(g_us, 3),
                             n_orders=15, units=len(base.unit)))
    for k in ("base", "params", "party_map", "setup", "live_names"):
        doc["config"].pop(k, None)
    doc["config"]["note"] = doc["config"]["note"].split(". Base")[0] + "."
    json.dump(doc, open(f"site/data/{c}.json", "w"), ensure_ascii=False)
    print(f"listo en {round(time.time() - t0)} s → site/data/{c}.json, config/params_{c}.json")
    import replay; replay.main(c)        # agrega el análisis del corrimiento a la repetición


if __name__ == "__main__":
    main(sys.argv[1])
