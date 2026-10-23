"""
Análisis del cambio respecto de la elección base, comparando SOLO las unidades ya escrutadas
(idea tomada de El Atlas: "comparando los mismos municipios"). Sirve en vivo y al final.

Todo se mide sobre el margen entre los dos primeros candidatos proyectados (a − b) y sobre el
share de cada candidato contra el de su grupo en la base. En unidades parcialmente escrutadas
se usa lo contado, ponderado por la fracción escrutada.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _bins(V):
    """Cortes de tamaño (votos válidos de la base) en escala logarítmica, redondeados."""
    nice = np.array([1e3, 2.5e3, 5e3, 1e4, 2.5e4, 5e4, 1e5, 2.5e5, 5e5, 1e6, 2.5e6])
    qs = np.quantile(V, [0.2, 0.4, 0.6, 0.8, 0.97])
    cuts = sorted({float(nice[np.argmin(np.abs(np.log(nice / q)))]) for q in qs})
    return cuts


def _fmt(n):
    if n >= 1e6:
        return f"{n / 1e6:g} M".replace(".", ",")
    if n >= 1e3:
        return f"{n / 1e3:g} mil".replace(".", ",")
    return f"{int(n)}"


def analyze(base, current: pd.DataFrame, candidates: dict, out: dict, polls: dict | None = None,
            scatter: int = 0, flips_top: int = 12) -> dict | None:
    C = list(candidates)
    G = base.groups
    gi = np.array([G.index(candidates[c]) for c in C])
    cur = current.copy(); cur["unit"] = cur["unit"].astype(str)
    cur = cur[cur["unit"].isin(base.idx.keys())]
    if len(cur) < 5:
        return None
    ii = cur["unit"].map(base.idx).to_numpy(int)
    O = cur[C].fillna(0).to_numpy(float)
    f = cur["frac"].clip(0, 1).to_numpy(float)
    ok = O.sum(1) > 0
    ii, O, f = ii[ok], O[ok], f[ok]
    S_now = O / O.sum(1, keepdims=True)
    Vb = base.Vb[ii]
    Gb = base.df[G].to_numpy(float)[ii]
    S_base_g = Gb / np.maximum(Gb.sum(1, keepdims=True), 1)
    S_base = S_base_g[:, gi]                 # share base del grupo de cada candidato
    # si varios candidatos comparten grupo (p. ej. nuevos dentro de "otros"), el cambio individual
    # no tiene base propia: se reporta el del grupo, y se marca
    shared = {c: (gi == gi[k]).sum() > 1 for k, c in enumerate(C)}
    w = Vb * f                               # peso: votos de la base de lo efectivamente escrutado

    o = np.argsort(out["proj"])[::-1][:2]
    a, b = int(o[0]), int(o[1])
    m_now = S_now[:, a] - S_now[:, b]
    m_base = S_base[:, a] - S_base[:, b]
    d = m_now - m_base

    def wavg(x, m=None):
        m = np.ones(len(x), bool) if m is None else m
        return float(np.average(x[m], weights=w[m])) if m.any() and w[m].sum() > 0 else None

    # 1) cambio de cada candidato en las mismas unidades (agregado, ponderado por votos)
    sh_now = O.sum(0) / O.sum()
    sh_base = (S_base * (Gb.sum(1) * f)[:, None]).sum(0) / (Gb.sum(1) * f).sum()
    change = {c: dict(now=float(sh_now[k]), base=float(sh_base[k]), delta=float(sh_now[k] - sh_base[k]),
                      shared_group=bool(shared[c])) for k, c in enumerate(C)}
    nat_d = float((sh_now[a] - sh_now[b]) - (sh_base[a] - sh_base[b]))

    # 2) por región
    reg = []
    for r, name in enumerate(base.regions):
        m = base.rid[ii] == r
        if m.sum() == 0:
            continue
        Oa, Ob = O[m].sum(0), (S_base[m] * (Gb[m].sum(1) * f[m])[:, None]).sum(0)
        dn = (Oa[a] - Oa[b]) / Oa.sum() - (Ob[a] - Ob[b]) / Ob.sum()
        reg.append(dict(region=str(name), delta=float(dn), units=int(m.sum()),
                        same_dir=float(np.average(np.sign(d[m]) == np.sign(nat_d), weights=w[m]))))
    reg.sort(key=lambda x: x["delta"])

    # 3) por tamaño de la unidad (votos válidos en la base)
    cuts = _bins(base.Vb)
    edges = [0] + cuts + [np.inf]
    size = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (Vb >= lo) & (Vb < hi)
        if m.sum() < 3:
            continue
        Oa, Ob = O[m].sum(0), (S_base[m] * (Gb[m].sum(1) * f[m])[:, None]).sum(0)
        dn = (Oa[a] - Oa[b]) / Oa.sum() - (Ob[a] - Ob[b]) / Ob.sum()
        label = f"menos de {_fmt(hi)}" if lo == 0 else (f"más de {_fmt(lo)}" if hi == np.inf else f"{_fmt(lo)} a {_fmt(hi)}")
        size.append(dict(label=label, delta=float(dn), units=int(m.sum()),
                         share_votes=float(Vb[m].sum() / Vb.sum())))

    # 4) unidades que cambiaron de ganador (entre los dos primeros)
    full = f >= 0.999
    flip_ab = (m_base < 0) & (m_now > 0) & full      # pasaron a a
    flip_ba = (m_base > 0) & (m_now < 0) & full      # pasaron a b
    names = base.df.get("name")
    def flist(mask):
        idx = np.where(mask)[0]
        idx = idx[np.argsort(-Vb[idx])][:flips_top]
        return [dict(unit=str(base.unit[ii[j]]), name=(str(names.iloc[ii[j]]) if names is not None else str(base.unit[ii[j]])),
                     region=str(base.region[ii[j]]), base=float(m_base[j]), now=float(m_now[j]), votes=float(O[j].sum()))
                for j in idx]
    # "vulnerables": unidades que ganó en la base el que perdió terreno, por menos que el swing nacional
    vul = ((m_base < 0) & (m_base > -nat_d)) if nat_d > 0 else ((m_base > 0) & (m_base < -nat_d))
    flips = dict(to_a=int(flip_ab.sum()), to_b=int(flip_ba.sum()), top_to_a=flist(flip_ab), top_to_b=flist(flip_ba),
                 vulnerable=int((vul & full).sum()),
                 vulnerable_flipped=int((vul & full & (flip_ab | flip_ba)).sum()))

    # 5) uniformidad y persistencia
    same_dir = float(np.average(np.sign(d) == np.sign(nat_d), weights=w))
    rid = base.rid[ii]
    tot_var = np.average((d - np.average(d, weights=w)) ** 2, weights=w)
    reg_mean = pd.Series(d * w).groupby(rid).transform("sum").to_numpy() / pd.Series(w).groupby(rid).transform("sum").to_numpy()
    r2_region = float(1 - np.average((d - reg_mean) ** 2, weights=w) / max(tot_var, 1e-12))
    corr = float(np.corrcoef(m_base, m_now)[0, 1]) if len(m_base) > 2 else None

    res = dict(a=C[a], b=C[b], units=int(len(ii)), change=change, margin_delta=nat_d,
               by_region=reg, by_size=size, flips=flips, same_dir=same_dir, r2_region=r2_region,
               persistence=corr, sd_unit=float(np.sqrt(tot_var)))
    # 6) contra las encuestas (si están cargadas): margen proyectado − margen de las encuestas
    if polls and C[a] in polls and C[b] in polls:
        pm = polls[C[a]] - polls[C[b]]
        res["polls"] = dict(margin=pm, error=float(out["margin"]["mid"] - pm) if out.get("margin") else None,
                            source=polls.get("_source"))
    # 7) muestra para el gráfico de persistencia (margen base vs. actual), ponderada por votos
    if scatter and len(ii) > 0:
        rng = np.random.default_rng(0)
        k = min(scatter, len(ii))
        pick = rng.choice(len(ii), k, replace=False, p=w / w.sum())
        res["scatter"] = [[round(float(m_base[j]), 3), round(float(m_now[j]), 3), round(float(np.log10(Vb[j] + 1)), 2)] for j in pick]
    return res
