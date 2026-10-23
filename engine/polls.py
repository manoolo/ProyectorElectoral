"""
Promedio de encuestas al estilo Silver Bulletin y su uso como prior en la noche electoral.

Promedio (ver natesilver.net/p/silver-bulletin-polling-average-methodology):
  * peso por calidad de la encuestadora (nota o peso directo), por tamaño de muestra con
    rendimientos decrecientes (raíz, con tope) y por recencia (decaimiento exponencial);
  * tope por frecuencia: una encuestadora que publica mucho no puede dominar el promedio;
    su peso total crece como la raíz de la cantidad de encuestas y se reparte entre ellas;
  * house effects: el sesgo persistente de cada firma respecto del promedio se estima en forma
    iterativa y se descuenta en una proporción que crece con la muestra acumulada de la firma
    (casi 100% para las que encuestan mucho, poco para las que encuestaron una o dos veces);
    las encuestas partidarias arrancan con un prior de 1,7 puntos a favor de quien las paga.

Prior en la noche: las simulaciones del escrutinio se re-ponderan por la verosimilitud del
promedio de encuestas dado el margen simulado (actualización bayesiana sobre las simulaciones).
La verosimilitud es una t de Student: si el conteo contradice mucho a las encuestas (Argentina 2019,
EEUU 2020), las encuestas pierden peso solas en lugar de arrastrar la proyección.
"""
from __future__ import annotations
import datetime as dt
import numpy as np

GRADE_W = {"A+": 1.0, "A": 0.95, "A-": 0.9, "B+": 0.8, "B": 0.7, "B-": 0.6, "C+": 0.5, "C": 0.4,
           "C-": 0.3, "D+": 0.2, "D": 0.15, "D-": 0.1, "F": 0.0}
DEFAULTS = dict(half_life=14.0, n_ref=600, n_cap=5000, house_k=3000, partisan_prior=0.017,
                iters=10, poll_sd=0.035, poll_df=4)


def _date(s):
    return dt.date.fromisoformat(str(s)[:10])


def average(polls: list[dict], candidates: list[str], asof=None, params=None) -> dict:
    """polls: [{pollster, date (fin de campo), n, grade|weight, partisan (candidato que la paga, opcional),
               <candidato>: share (0-1 o 0-100)}]. Devuelve shares promedio (normalizados) y house effects."""
    p = {**DEFAULTS, **(params or {})}
    rows = [r for r in polls if all(c in r for c in candidates[:2])]
    if not rows:
        return {}
    asof = _date(asof) if asof else max(_date(r["date"]) for r in rows)
    C = candidates
    X = np.array([[float(r.get(c, 0) or 0) for c in C] for r in rows])
    X = np.where(X.sum(1, keepdims=True) > 1.5, X / 100.0, X)     # admite porcentajes
    X = X / np.maximum(X.sum(1, keepdims=True), 1e-9)                # se reparte el indeciso en proporción
    age = np.array([(asof - _date(r["date"])).days for r in rows], float)
    keep = age >= 0
    n = np.array([float(r.get("n", p["n_ref"]) or p["n_ref"]) for r in rows])
    q = np.array([float(r["weight"]) if "weight" in r else GRADE_W.get(str(r.get("grade", "B")).upper(), 0.5) for r in rows])
    w = q * np.sqrt(np.minimum(n, p["n_cap"]) / p["n_ref"]) * 0.5 ** (np.maximum(age, 0) / p["half_life"]) * keep
    firm = np.array([str(r.get("pollster", "?")) for r in rows])
    for f in np.unique(firm):                                         # tope por frecuencia
        m = firm == f
        k = m.sum()
        if k > 1:
            w[m] *= np.sqrt(k) / k
    # prior partidario: la encuesta paga por un candidato se supone sesgada a su favor
    prior = np.zeros_like(X)
    for i, r in enumerate(rows):
        s = r.get("partisan")
        if s in C:
            j = C.index(s)
            prior[i, j] += p["partisan_prior"] / 2
            others = [k for k in range(len(C)) if k != j]
            prior[i, others] -= p["partisan_prior"] / 2 / len(others)
    house = {f: np.zeros(len(C)) for f in np.unique(firm)}
    H = prior.copy()
    for _ in range(p["iters"]):
        avg = np.average(X - H, axis=0, weights=w) if w.sum() > 0 else X.mean(0)
        newH = prior.copy()
        for f in house:
            m = firm == f
            dev = np.average(X[m] - avg, axis=0, weights=np.maximum(w[m], 1e-12))
            shrink = n[m].sum() / (n[m].sum() + p["house_k"])
            # sin datos la firma se queda con su prior; con muchos, con su desvío observado
            house[f] = shrink * dev + (1 - shrink) * prior[m].mean(0)
            newH[m] = house[f]
        if np.abs(newH - H).max() < 1e-5:
            H = newH
            break
        H = newH
    avg = np.average(X - H, axis=0, weights=w)
    avg = np.clip(avg, 0, None); avg = avg / avg.sum()
    return dict(shares={c: float(v) for c, v in zip(C, avg)}, asof=str(asof), n_polls=int(keep.sum()),
                house={str(f): {c: round(float(v), 4) for c, v in zip(C, h)} for f, h in house.items()},
                eff_n=float(w.sum() ** 2 / max((w ** 2).sum(), 1e-12)))


def poll_shares(cfg_polls, candidates):
    """Acepta `polls` de la config como lista de encuestas (se promedian) o como dict de shares ya promediados."""
    if not cfg_polls:
        return None
    if isinstance(cfg_polls, dict):
        if "list" in cfg_polls:
            return average(cfg_polls["list"], candidates, cfg_polls.get("asof"), cfg_polls.get("params")).get("shares")
        return {c: float(v) for c, v in cfg_polls.items() if c in candidates}
    return average(cfg_polls, candidates).get("shares")


def reweight(NS, cands, shares, sd=None, df=None):
    """Pesos de importancia para las simulaciones NS[s, C] dado el promedio de encuestas.
    Se usa el margen entre los dos primeros de las encuestas (lo que mejor miden)."""
    sd = DEFAULTS["poll_sd"] if sd is None else sd
    df = DEFAULTS["poll_df"] if df is None else df
    o = sorted((c for c in cands if isinstance(shares.get(c), (int, float))), key=lambda c: -shares[c])[:2]
    if len(o) < 2:
        return np.ones(len(NS)) / len(NS)
    a, b = cands.index(o[0]), cands.index(o[1])
    pm = shares[o[0]] - shares[o[1]]
    z = (NS[:, a] - NS[:, b] - pm) / sd
    lw = -(df + 1) / 2 * np.log1p(z * z / df)
    w = np.exp(lw - lw.max())
    return w / w.sum()


def wquantile(x, q, w):
    """Cuantiles ponderados por columna (x[s, ...])."""
    o = np.argsort(x, axis=0)
    xs = np.take_along_axis(x, o, 0)
    cw = np.cumsum(w[o] if x.ndim == 1 else np.take_along_axis(np.broadcast_to(w.reshape(-1, *[1] * (x.ndim - 1)), x.shape), o, 0), 0)
    cw = (cw - 0.5 * (w[o] if x.ndim == 1 else np.take_along_axis(np.broadcast_to(w.reshape(-1, *[1] * (x.ndim - 1)), x.shape), o, 0))) / cw[-1]
    if x.ndim == 1:
        return np.interp(q, cw, xs)
    flat = xs.reshape(len(x), -1); cwf = cw.reshape(len(x), -1)
    return np.array([np.interp(q, cwf[:, i], flat[:, i]) for i in range(flat.shape[1])]).reshape(x.shape[1:])
