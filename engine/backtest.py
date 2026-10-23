"""
Backtest: se toma una elección ya terminada, se la "re-escruta" revelando unidades en un orden
simulado y en cada corte se compara la proyección con el resultado final real.

Métodos comparados
  crudo     : lo contado hasta el momento
  swing_reg : swing aditivo (puntos) por región aplicado a la base, fallback nacional (tipo Quiroga v2)
  vecinos   : swing aditivo imputado con vecinos geográficos/parecidos ya contados (tipo Schteingart)
  modelo    : el modelo jerárquico solo (log-ratio + efectos regionales + vecinos)
  ensamble  : promedio con pesos iguales de modelo y vecinos (lo que usa la página)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from .model import Base, project, _knn

CUTS = [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]


# ------------------------------------------------------------------ órdenes de llegada
def make_order(base: Base, target: pd.DataFrame, kind: str, rng) -> np.ndarray:
    """Devuelve índices de unidades en orden de llegada.
    aleatorio: sin sesgo (el caso fácil).
    sesgado:   regiones que cierran antes + sesgo por tamaño y por perfil partidario de signo aleatorio
               (a veces llega primero lo urbano, a veces lo rural; a veces una fuerza, a veces la otra).
    huso:      EEUU: por longitud (este primero), dentro de cada estado lo chico primero."""
    n = len(base.unit)
    z = lambda x: (x - x.mean()) / (x.std() + 1e-9)
    if kind == "aleatorio":
        return rng.permutation(n)
    if kind == "huso":
        lon = base.df.lon.values
        st_lon = pd.Series(lon).groupby(base.rid).transform("mean").values
        score = -z(st_lon) * 3 + z(np.log(base.Vb + 1)) * 0.8 + rng.normal(0, 0.6, n)
        return np.argsort(score)
    reg = rng.normal(0, 1, len(base.regions))[base.rid]
    size = z(np.log(base.Vb + 1)) * rng.choice([-1, 1]) * rng.uniform(0.3, 1.2)
    part = z(base.Zb[:, 0]) * rng.choice([-1, 1]) * rng.uniform(0.0, 0.8)
    return np.argsort(reg * 1.5 + size + part + rng.normal(0, 0.7, n))


def snapshot(base: Base, target: pd.DataFrame, order, cut, cands):
    tv = target.set_index("unit").loc[base.unit, cands].sum(1).to_numpy()
    cum = np.cumsum(tv[order]) / tv.sum()
    k = int(np.searchsorted(cum, cut) + 1)
    rev = base.unit[order[:k]]
    cur = target[target.unit.isin(rev)].copy()
    cur["frac"] = 1.0
    return cur


# ------------------------------------------------------------------ métodos simples
def _obs_matrix(base, cur, cands):
    O = np.zeros((len(base.unit), len(cands)))
    ii = cur.unit.map(base.idx).to_numpy(int)
    O[ii] = cur[cands].to_numpy(float)
    return O, np.isin(np.arange(len(base.unit)), ii)


def swing_region(base, cur, cands):
    O, cnt = _obs_matrix(base, cur, cands)
    Pb = base.df[cands].to_numpy(float)
    Sb = Pb / np.maximum(Pb.sum(1, keepdims=True), 1e-9)
    tot = O.copy()
    nat_sw = O[cnt].sum(0) / O[cnt].sum() - Pb[cnt].sum(0) / Pb[cnt].sum()
    nat_to = O[cnt].sum() / Pb[cnt].sum()
    for r in range(len(base.regions)):
        m = base.rid == r
        c = m & cnt
        if c.any() and O[c].sum() > 0 and Pb[c].sum() > 0:
            sw = O[c].sum(0) / O[c].sum() - Pb[c].sum(0) / Pb[c].sum()
            to = O[c].sum() / Pb[c].sum()
        else:
            sw, to = nat_sw, nat_to
        u = m & ~cnt
        s = np.clip(Sb[u] + sw, 0, None)
        tot[u] = s / s.sum(1, keepdims=True) * (Pb[u].sum(1, keepdims=True) * to)
    return tot


def neighbors(base, cur, cands, k=10, h_km=150.0):
    O, cnt = _obs_matrix(base, cur, cands)
    Pb = base.df[cands].to_numpy(float)
    Sb = Pb / np.maximum(Pb.sum(1, keepdims=True), 1e-9)
    sw = O / np.maximum(O.sum(1, keepdims=True), 1) - Sb
    to = O.sum(1) / np.maximum(Pb.sum(1), 1)
    pts = np.c_[base.coords, base.F * 60.0]          # cercanía + parecido
    ci = np.where(cnt)[0]
    d, j = _knn(cKDTree(pts[ci]), pts, min(k, len(ci)))
    a = np.sqrt(Pb.sum(1))[ci[j]] * np.exp(-d / h_km)
    a = a / np.maximum(a.sum(1, keepdims=True), 1e-12)
    s_hat = (a[..., None] * sw[ci[j]]).sum(1)
    t_hat = (a * to[ci[j]]).sum(1)
    tot = O.copy()
    u = ~cnt
    s = np.clip(Sb[u] + s_hat[u], 0, None)
    tot[u] = s / s.sum(1, keepdims=True) * (Pb[u].sum(1) * t_hat[u])[:, None]
    return tot


# ------------------------------------------------------------------ evaluación
def run(base: Base, target: pd.DataFrame, cands, params, rule=None, orders=("sesgado",) * 8,
        cuts=CUTS, seed=0, sims=True, methods=("crudo", "swing_reg", "vecinos", "modelo", "ensamble")):
    rng = np.random.default_rng(seed)
    T = target.set_index("unit").loc[base.unit, cands].to_numpy(float)
    true_sh = T.sum(0) / T.sum()
    a, b = 0, 1                                      # margen entre los dos primeros candidatos de la lista
    true_m = true_sh[a] - true_sh[b]
    R = np.zeros((len(base.regions), len(cands))); np.add.at(R, base.rid, T)
    true_reg_w = R.argmax(1)
    true_rule = rule(R, cands, [str(r) for r in base.regions]) if rule else None
    # resultado "categórico" de la regla (ganador o escenario), para medir la probabilidad asignada
    rule_key = next((k for k in ("ganador", "resultado") if true_rule and k in true_rule), None)
    rows = []
    for oi, kind in enumerate(orders):
        order = make_order(base, target, kind, rng)
        for cut in cuts:
            cur = snapshot(base, target, order, cut, cands)
            for meth in methods:
                if meth in ("modelo", "ensamble"):
                    pp = dict(params, ensemble=(meth == "ensamble"))
                    out = project(base, cur, {c: c for c in cands}, pp, rule, with_sims=sims and meth == "ensamble")
                    sh = np.array(out["proj"]); reg = np.array(out["region_proj"])
                    lo = out.get("margin", {}).get("lo"); hi = out.get("margin", {}).get("hi")
                    if "margin" in out and out["margin"]["a"] != cands[a]:
                        lo, hi = -hi, -lo
                    rp = out.get("rule_point")
                    p_a = out.get("margin", {}).get("p_a_ahead")
                    if p_a is not None and out["margin"]["a"] != cands[a]:
                        p_a = 1 - p_a
                    p_rule = out.get("rule", {}).get(rule_key, {}).get(str(true_rule[rule_key])) if rule_key else None
                    if rule_key and "rule" in out and p_rule is None:
                        p_rule = 0.0
                else:
                    if meth == "crudo":
                        O, _ = _obs_matrix(base, cur, cands); tot = O
                    elif meth == "swing_reg":
                        tot = swing_region(base, cur, cands)
                    else:
                        tot = neighbors(base, cur, cands)
                    sh = tot.sum(0) / tot.sum()
                    Rg = np.zeros_like(R); np.add.at(Rg, base.rid, tot)
                    reg = Rg / np.maximum(Rg.sum(1, keepdims=True), 1)
                    lo = hi = None
                    rp = rule(Rg, cands, [str(r) for r in base.regions]) if rule else None
                    p_a = p_rule = None
                m = sh[a] - sh[b]
                row = dict(orden=oi, tipo=kind, corte=cut, metodo=meth, margen=m, error=m - true_m,
                           abs_error=abs(m - true_m),
                           regiones_ok=float((reg.argmax(1) == true_reg_w).mean()),
                           lo=lo, hi=hi, cubre=(lo <= true_m <= hi) if lo is not None else None,
                           p_a=p_a, p_regla=p_rule)
                if rule and rp is not None:
                    row["regla_ok"] = all(rp.get(k) == true_rule.get(k) for k in true_rule
                                          if isinstance(true_rule[k], (str, bool)))
                rows.append(row)
    return pd.DataFrame(rows), dict(true_margin=float(true_m), true_shares=true_sh.tolist(), true_rule=true_rule)


def calibrate(df: pd.DataFrame, true_m: float, target=0.90) -> float:
    """Factor por el que hay que escalar el error simulado para que el intervalo del 90% cubra el 90%."""
    d = df[(df.metodo == "ensamble") & df.lo.notna()]
    mid = d.margen
    half = np.where(d.error > 0, mid - d.lo, d.hi - mid)
    ratio = np.abs(d.error) / np.maximum(half, 1e-6)
    d = d.assign(ratio=ratio.values if hasattr(ratio, "values") else ratio)
    by = d.groupby("corte").ratio.quantile(target)
    # factor por tramo de escrutinio, suavizado (monótono no hace falta) y nunca menor a 0.2
    sm = by.rolling(3, center=True, min_periods=1).mean().clip(lower=0.2)
    return [[float(k), round(float(v), 3)] for k, v in sm.items()]


def ratios(df):
    """|error| / semiancho del intervalo (con calib=1), por corrida del ensamble."""
    d = df[(df.metodo == "ensamble") & df.lo.notna()].copy()
    half = np.where(d.error > 0, d.margen - d.lo, d.hi - d.margen)
    d["ratio"] = np.abs(d.error) / np.maximum(half, 1e-6)
    return d


def coverage(df, calib):
    """Cobertura que habría tenido el intervalo con una calibración dada (el punto central no cambia)."""
    d = ratios(df)
    xs, ys = zip(*calib)
    d["ok"] = d.ratio <= np.interp(d.corte, xs, ys)
    return d.groupby("corte").ok.mean(), float(d.ok.mean())
