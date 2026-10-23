"""Senado de EEUU: la previa (antes de que haya votos) y la repetición de 2022 para la página.

  python senado.py previa        # site/data/us_senado.json con el pronóstico según las calificaciones de Cook
  python senado.py repeticion    # site/data/us_senado_2022.json: el Senado 2022 re-escrutado condado por condado

La noche del 3/11, run_live.py (vía en_vivo.py us_senado) reemplaza la previa por el conteo.
"""
import sys, json
import numpy as np, pandas as pd
from engine.model import Base, DEFAULTS, project, summarize
from engine.backtest import make_order, snapshot
from engine.rules import RULES
from engine.ratings import prior
from engine.output import frame, geo_index
from engine.analysis import analyze

G = ["gop", "dem", "oth"]
# error nacional común a todas las carreras (puntos de margen D-R): los handicappers fallan juntos,
# como en 2022 (casi todos los Toss Up los ganaron los demócratas)
SD_NAC = 0.03


def previa():
    """Pronóstico de antes de la noche: cada carrera con la normal de su calificación de Cook,
    con un error nacional común (la varianza de la calificación se reparte entre nacional y propia)."""
    cfg = json.load(open("config/us_senado.json", encoding="utf-8"))
    base = Base(pd.read_csv(cfg["base"], dtype={"unit": str, "region": str}), cfg["groups"])
    C = list(cfg["candidates"])
    regions = [str(r) for r in base.regions]
    rule = RULES[cfg["rule"]]()
    rng = np.random.default_rng(11)
    S = 4000
    nat = rng.standard_t(5, S) * np.sqrt(3 / 5) * SD_NAC
    V = np.zeros((S, len(regions), len(C)))
    mid = np.zeros((len(regions), len(C)))
    for r, reg in enumerate(regions):
        mu, sd = prior(cfg["ratings"][reg])
        own = np.sqrt(max(sd ** 2 - SD_NAC ** 2, 0.01 ** 2))
        m = mu + nat + rng.standard_t(5, S) * np.sqrt(3 / 5) * own
        sb = base.df[base.region == reg][G].sum().to_numpy(float)
        oth = sb[2] / sb.sum()
        V[:, r, C.index("Demócratas")] = (1 - oth + m) / 2
        V[:, r, C.index("Republicanos")] = (1 - oth - m) / 2
        V[:, r, C.index("Otros")] = oth
        mid[r] = np.median(V[:, r], 0)
    V = np.clip(V, 0, None) * base.df.groupby("region")[G].sum().sum(axis=1).to_numpy()[None, :, None]
    sims = [rule(V[s], C, regions) for s in range(S)]
    R = summarize(sims)
    sh = V / V.sum(2, keepdims=True)
    p_d = (sh[..., C.index("Demócratas")] > sh[..., C.index("Republicanos")]).mean(0)
    tot = V.sum(1); nsh = np.median(tot / tot.sum(1, keepdims=True), 0)
    a_is_dem = nsh[C.index("Demócratas")] >= nsh[C.index("Republicanos")]   # p_ahead es del primero proyectado
    fr = dict(ts=None, counted=0.0, units=[0, len(base.unit)], crude=[0.0] * len(C), proj=nsh.round(4).tolist(),
              lo=None, hi=None, margin=None, rule=R, rule_point=rule(mid, C, regions),
              regions=dict(counted=[0.0] * len(regions), proj=mid.round(4).tolist(), crude=[[0.0] * len(C)] * len(regions),
                           votes=V.mean(0).sum(1).round().tolist(),
                           p_ahead=(p_d if a_is_dem else 1 - p_d).round(4).tolist()))
    geo = geo_index(base, cfg)
    doc = dict(country="us_senado", mode="previa", config={k: v for k, v in cfg.items() if k not in ("base", "params")},
               regions=regions, history=[fr], calib=None)
    if geo:
        doc["geo"] = geo["doc"]
    json.dump(doc, open("site/data/us_senado.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    ctl = {k: round(v, 3) for k, v in R["control"].items()}
    print("previa:", ctl, "bancas D", R["bancas_Demócratas"], "R", R["bancas_Republicanos"])


def repeticion():
    """El Senado 2022 re-escrutado en el orden de cierre por huso horario, con la base 2020 y las
    calificaciones finales de Cook como prior (las mismas del backtest)."""
    from adapters.us_mid import pair
    from backtest_senado import COOK_2022
    t = pd.read_csv("data/us_sen2022.csv", dtype={"unit": str})
    b, t = pair(2020, t)
    base = Base(b, G)
    names = {"gop": "Republicanos", "dem": "Demócratas", "oth": "Otros"}
    cand = {v: k for k, v in names.items()}
    solid = {r: ("Solid D" if t[t.region == r].dem.sum() > t[t.region == r].gop.sum() else "Solid R") for r in base.regions}
    ratings = {**solid, **COOK_2022}
    us = json.load(open("config/params_us.json"))
    P = dict(DEFAULTS, **us, n_sims=400, ratings=ratings, ratings_w=1.0)
    rule = RULES["us_senado_2022"]()
    def rule_named(V, C, regs):                       # misma regla, con los nombres de la página
        out = rule(V, [cand[c] for c in C], regs)
        return {k.replace("bancas_gop", "bancas_Republicanos").replace("bancas_dem", "bancas_Demócratas").replace("bancas_oth", "bancas_Otros"):
                (names.get(v, v) if isinstance(v, str) else v) for k, v in out.items()}
    cfg = json.load(open("config/us_senado.json", encoding="utf-8"))
    cfg = dict(cfg, title="Senado 2022", ratings=ratings, ratings_source="Cook Political Report, 4/11/2022 (reconstruidas)",
               race_names=race_names_2022(), seats={"total": 100, "fijas": {"Republicanos": 30, "Demócratas": 37},
               "desempate": "Demócratas", "para_controlar": {"Republicanos": 51, "Demócratas": 50}},
               note="Se eligieron 35 bancas. Faltan California (MEDSL no publicó su Senado 2022) y Alaska (dos republicanos con voto por ranking): se cuentan como fijas. Con 50 bancas desempataba la vicepresidenta Harris, demócrata. Base: presidencial 2020 por condado.")
    geo = geo_index(base, cfg)
    order = make_order(base, t, "huso", np.random.default_rng(5))
    cuts = list(np.arange(0.025, 1.0, 0.025)) + [1.0]
    hist = []
    for k, cut in enumerate(cuts):
        cur = snapshot(base, t, order, cut, G).rename(columns=names)
        out = project(base, cur, {names[g]: g for g in G}, P, rule_named)
        fr = frame(out, f"paso {k + 1}", geo)
        fr["analysis"] = analyze(base, cur, {names[g]: g for g in G}, out,
                                 scatter=500 if (k % 4 == 3 or k == len(cuts) - 1) else 0)
        hist.append(fr)
    T = t.groupby("region")[G].sum()
    doc = dict(country="us_senado_2022", mode="replay", config={k: v for k, v in cfg.items() if k not in ("base", "params")},
               regions=[str(r) for r in base.regions], history=hist, calib=us["calib"],
               replay_sub="Reproduce el escrutinio del Senado 2022 condado por condado, con la presidencial 2020 como base y las calificaciones finales de Cook como punto de partida, en el orden aproximado de cierre por huso horario.",
               truth=dict(shares=(t[["gop", "dem", "oth"]].sum() / t[["gop", "dem", "oth"]].sum().sum()).round(4).tolist(),
                          text="Resultado real: los demócratas ganaron Pensilvania, retuvieron Arizona, Nevada y Georgia (en segunda vuelta) y quedaron con 51 bancas.",
                          winners={r: ("Demócratas" if x.dem > x.gop else "Republicanos") for r, x in T.iterrows()}))
    if geo:
        doc["geo"] = geo["doc"]
    json.dump(doc, open("site/data/us_senado_2022.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("repetición:", len(hist), "cortes; último control:", hist[-1]["rule"]["control"] if hist[-1].get("rule") else None)


def race_names_2022():
    c = pd.read_csv("data/us_sen2022_candidatos.csv")
    out = {}
    for r, g, n in c.itertuples(index=False):
        if g in ("gop", "dem"):
            out.setdefault(r, {})["Republicanos" if g == "gop" else "Demócratas"] = n.split()[-1].title() if n.split()[-1] not in ("JR", "Jr") else n.split()[-2].title()
    return out


if __name__ == "__main__":
    {"previa": previa, "repeticion": repeticion}[sys.argv[1]]()
