"""
Motor de proyección de escrutinio.

Para cada unidad (condado, municipio, circuito) se modela el CAMBIO respecto de una
elección base, no el nivel. El cambio se mide en escala log-ratio (alr, respecto de la fuerza
más votada de la base): los
shares proyectados quedan en [0,1] y suman 1, y un mismo cambio relativo pesa parecido
en zonas fuertes y débiles de cada fuerza. También se modela el cambio de participación
(log de votos válidos actuales / base), así que los votos esperados no se suponen fijos.

Predicción del cambio en unidades sin escrutar:
    cambio = X·β  (ridge: features de la base + efectos regionales encogidos hacia el nacional)
           + ρ · promedio ponderado de los residuos de vecinos geográficos ya contados

Incertidumbre: simulación con shocks regionales correlacionados + ruido por unidad,
ambos estimados por validación cruzada (k-fold y dejando regiones afuera), y escalados
por un factor de calibración que sale del backtest. Tomado de Silver Bulletin: un shock por
perfil (unidades parecidas se equivocan juntas), colas gruesas (t de Student) y, opcional,
un prior de encuestas que re-pondera las simulaciones (engine/polls.py).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

EPS = 0.5  # pseudo-votos para evitar log(0)

DEFAULTS = dict(lam_x=1.0, lam_r=20.0, k=12, rho=0.8, h_km=150.0,
                phi=0.5, kappa_r=8.0, w_pow=0.5, scale="logratio", ensemble=True, calib=1.0, n_sims=600, seed=7, k_nb=10, tau_nat=1.0, ens=("modelo", "vecinos"),
                t_df=0, tau_feat=0.0, polls=None, poll_sd=0.035, poll_df=4)


# ------------------------------------------------------------------ utilidades
def alr(M, ref):
    """log-ratio respecto de un grupo de referencia: el cociente entre dos fuerzas
    no se contamina con lo que pasa con una tercera (p. ej. 'otros' mal cargado)."""
    L = np.log(M)
    return L - L[:, [ref]]


def clr_inv(Z):
    E = np.exp(Z - Z.max(-1, keepdims=True))
    return E / E.sum(-1, keepdims=True)


def to_space(P, ref, scale):
    """Escala en la que se mide el cambio: 'logratio' (relativo) o 'additive' (puntos de share)."""
    return alr(P, ref) if scale == "logratio" else P.copy()


def from_space(Z, scale):
    if scale == "logratio":
        return clr_inv(Z)
    S = np.clip(Z, 1e-6, None)
    return S / S.sum(-1, keepdims=True)


def _xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.c_[np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)] * 6371.0


def _ridge(X, Y, w, pen):
    A = X.T @ (X * w[:, None]) + np.diag(pen)
    return np.linalg.solve(A, X.T @ (Y * w[:, None]))


def _knn(tree, pts, k):
    k = int(max(1, k))
    d, j = tree.query(pts, k=k)
    if k == 1:
        d, j = d[:, None], j[:, None]
    return d, j


# ------------------------------------------------------------------ elección base
class Base:
    """Una fila por unidad. Columnas: unit, region, lat/lon (opcionales) y una por grupo con votos."""

    def __init__(self, df: pd.DataFrame, groups: list[str]):
        self.df = df.reset_index(drop=True)
        self.groups = list(groups)
        self.unit = self.df["unit"].astype(str).values
        self.idx = {u: i for i, u in enumerate(self.unit)}
        self.region = self.df["region"].astype(str).values
        self.regions = np.unique(self.region)
        self.rid = np.searchsorted(self.regions, self.region)
        V = self.df[self.groups].to_numpy(float)
        self.Vb = V.sum(1)
        self.P = (V + EPS) / (self.Vb[:, None] + EPS * len(self.groups))
        self.ref = int(np.argmax(V.sum(0)))
        self.Zb = alr(self.P, self.ref)
        lv = np.log(self.Vb + 1.0)
        F = np.c_[np.delete(self.Zb, self.ref, 1), lv]
        self.F = (F - F.mean(0)) / (F.std(0) + 1e-9)
        D = np.zeros((len(self.unit), len(self.regions)))
        D[np.arange(len(self.unit)), self.rid] = 1.0
        self.X = np.c_[np.ones(len(self.unit)), self.F, D]
        self.nF = self.F.shape[1]
        geo = {"lat", "lon"} <= set(self.df.columns) and self.df[["lat", "lon"]].notna().all().all()
        # sin coordenadas, los "vecinos" se buscan en el espacio de features (escala ~km)
        self.coords = _xyz(self.df.lat.values, self.df.lon.values) if geo else self.F * 100.0


# ------------------------------------------------------------------ núcleo
def _fit_predict(base: Base, Y, w, train, p):
    """Ajusta con las unidades `train` y predice el cambio para todas. Y = [swing log-ratio (K), swing participación]."""
    pen = np.r_[1e-6, np.full(base.nF, p["lam_x"]), np.full(len(base.regions), p["lam_r"])]
    B = _ridge(base.X[train], Y[train], w[train], pen)
    pred = base.X @ B
    if p["rho"] > 0 and train.sum() > 2:
        tr = np.where(train)[0]
        R = Y[tr] - pred[tr]
        d, j = _knn(cKDTree(base.coords[tr]), base.coords, min(p["k"] + 1, len(tr)))
        not_self = tr[j] != np.arange(len(base.unit))[:, None]
        a = w[tr[j]] * np.exp(-d / p["h_km"]) * not_self
        s = a.sum(1, keepdims=True)
        sm = (a[..., None] * R[j]).sum(1) / np.maximum(s, 1e-12)
        pred = pred + p["rho"] * np.where(s > 0, sm, 0.0)
    return pred


def _targets(base, O, f, counted, scale="logratio"):
    K = len(base.groups)
    Y = np.zeros((len(base.unit), K + 1))
    Q = (O + EPS) / (O.sum(1, keepdims=True) + EPS * K)
    Y[:, :K] = to_space(Q, base.ref, scale) - to_space(base.P, base.ref, scale)
    tot = O.sum(1) / np.maximum(f, 1e-9)
    Y[:, K] = np.log((tot + 1.0) / (base.Vb + 1.0))
    Y[~counted] = 0.0
    # winsorizado robusto: un dato mal cargado no puede arrastrar al resto
    if counted.sum() > 10:
        med = np.median(Y[counted], 0)
        mad = 1.4826 * np.median(np.abs(Y[counted] - med), 0) + 1e-3
        Y[counted] = np.clip(Y[counted], med - 5 * mad, med + 5 * mad)
    return Y


def _psd(S, floor=1e-6):
    ev, V = np.linalg.eigh((S + S.T) / 2)
    return (V * np.maximum(ev, floor)) @ V.T


def _error_model(base, Y, w, counted, p):
    """Covarianzas de error por validación cruzada.
    S_u: error al predecir una unidad cuya región ya tiene datos (k-fold aleatorio).
    S_r: error común de una región sin datos (dejando regiones afuera), neto del ruido por unidad."""
    rng = np.random.default_rng(p["seed"])
    ci = np.where(counted)[0]
    K1 = Y.shape[1]
    if len(ci) < 20:
        return np.eye(K1) * 0.05, np.eye(K1) * 0.05
    fold = rng.integers(0, 5, len(ci))
    E_u = np.zeros((len(ci), K1))
    for k in range(5):
        tr = counted.copy(); tr[ci[fold == k]] = False
        if tr.sum() >= 10:
            E_u[fold == k] = (Y - _fit_predict(base, Y, w, tr, p))[ci[fold == k]]
    ww = w[ci] / w[ci].sum()
    S_u = _psd((E_u * ww[:, None]).T @ E_u)
    regs = np.unique(base.rid[ci])
    if len(regs) < 4:
        return S_u, S_u * 0.5
    perm = rng.permutation(regs)
    rf = {r: i % 8 for i, r in enumerate(perm)}
    fr = np.array([rf[r] for r in base.rid[ci]])
    E_r = np.zeros((len(ci), K1))
    for k in range(min(8, len(regs))):
        tr = counted.copy(); tr[ci[fr == k]] = False
        E_r[fr == k] = (Y - _fit_predict(base, Y, w, tr, p))[ci[fr == k]]
    M, ns = [], []
    for r in regs:
        m = base.rid[ci] == r
        M.append(np.average(E_r[m], axis=0, weights=w[ci][m])); ns.append(m.sum())
    M = np.array(M)
    S_r = M.T @ M / len(regs) - S_u * np.mean(1.0 / np.array(ns))
    return S_u, _psd(S_r)


def _profile_error(base, Y, w, counted, p):
    """Error de extrapolación por perfil (idea de Silver: los errores se correlacionan entre
    unidades parecidas, no sólo entre vecinas). Para cada feature de la base se ajusta con la mitad
    de las unidades contadas de un lado de la mediana y se predice la otra mitad; el error medio,
    dividido por la distancia entre ambas mitades, es un error de pendiente. Devuelve, por feature,
    la covarianza (K+1 × K+1) de ese error de pendiente."""
    ci = np.where(counted)[0]
    K1 = Y.shape[1]
    S = np.zeros((base.nF, K1, K1))
    if len(ci) < 40:
        return S
    for j in range(base.nF):
        x = base.F[ci, j]
        med = np.median(x)
        sl = []
        for side in (x <= med, x > med):
            ho = ci[~side]
            if side.sum() < 10 or len(ho) < 10:
                continue
            tr = np.zeros_like(counted); tr[ci[side]] = True
            e = (Y - _fit_predict(base, Y, w, tr, p))[ho]
            gap = np.average(base.F[ho, j], weights=w[ho]) - np.average(base.F[ci[side], j], weights=w[ci[side]])
            if abs(gap) > 0.2:
                sl.append(np.average(e, axis=0, weights=w[ho]) / gap)
        if sl:
            sl = np.array(sl)
            S[j] = sl.T @ sl / len(sl)
    return S


def _tmix(rng, shape, df):
    """Factor de escala para pasar de normal a t de Student con la misma varianza (colas gruesas)."""
    if not df or df <= 2:
        return np.ones(shape)
    return np.sqrt((df - 2) / rng.chisquare(df, shape))


def _composition(base, Oc, O, gi, counted, p):
    """Fracción de cada candidato dentro de su grupo base (para grupos con varios candidatos)."""
    n, nC = Oc.shape
    comp = np.ones((n, nC))
    for g in np.unique(gi):
        cs = np.where(gi == g)[0]
        if len(cs) == 1:
            continue
        Og = O[:, g]
        ok = counted & (Og > 0)
        if ok.sum() == 0:
            comp[:, cs] = 1.0 / len(cs)
            continue
        oki = np.where(ok)[0]
        nat = Oc[oki][:, cs].sum(0) / Og[oki].sum()
        d, j = _knn(cKDTree(base.coords[oki]), base.coords, min(p["k"], len(oki)))
        idx = oki[j]
        a = Og[idx] * np.exp(-d / p["h_km"])
        frac = Oc[idx][..., cs] / np.maximum(Og[idx], 1e-9)[..., None]
        loc = (a[..., None] * frac).sum(1) / np.maximum(a.sum(1), 1e-12)[:, None]
        own = Oc[:, cs] / np.maximum(Og, 1e-9)[:, None]
        mix = np.where(ok[:, None], own, p["rho"] * loc + (1 - p["rho"]) * nat)
        comp[:, cs] = mix / np.maximum(mix.sum(1, keepdims=True), 1e-12)
    return comp


def _simple_preds(base, O, f, counted, wp, p):
    """Dos métodos simples que entran al ensamble. Devuelven, por unidad, votos totales y shares
    esperados del grupo base (unidad completa).
      swing_reg: swing aditivo por región en las unidades contadas, fallback nacional.
      vecinos  : swing aditivo de vecinos cercanos y parecidos ya contados."""
    n, K = O.shape
    Pv = base.P * base.Vb[:, None]
    Oto = O.sum(1)
    Q = O / np.maximum(Oto, 1)[:, None]
    ci = np.where(counted)[0]
    out = []
    # swing por región (comparando las mismas unidades, ponderadas por lo escrutado)
    def sw_of(m):
        a = O[m].sum(0); b = (Pv[m] * f[m, None]).sum(0)
        if a.sum() <= 0 or b.sum() <= 0:
            return np.zeros(K), 1.0
        return a / a.sum() - b / b.sum(), a.sum() / b.sum()
    nat_sw, nat_to = sw_of(counted)
    SW = np.zeros((n, K)); TO = np.zeros(n)
    for r in range(len(base.regions)):
        m = base.rid == r
        sw, to = sw_of(m & counted) if (m & counted).any() else (nat_sw, nat_to)
        SW[m] = sw; TO[m] = to
    out.append((base.Vb * TO, base.P + SW))
    # vecinos
    sw_i = Q - base.P
    to_i = Oto / np.maximum(f * base.Vb, 1)
    pts = np.c_[base.coords, base.F * 60.0]
    d, j = _knn(cKDTree(pts[ci]), pts, min(p["k_nb"] + 1, len(ci)))
    a = np.sqrt(base.Vb[ci[j]] + 1) * f[ci[j]] * np.exp(-d / p["h_km"]) * (ci[j] != np.arange(n)[:, None])
    a = a / np.maximum(a.sum(1, keepdims=True), 1e-12)
    out.append((base.Vb * (a * to_i[ci[j]]).sum(1), base.P + (a[..., None] * sw_i[ci[j]]).sum(1)))
    res = []
    for V, S in out:
        S = np.clip(S, 1e-6, None); S = S / S.sum(1, keepdims=True)
        V = wp[:, 0] * Oto / np.maximum(f, 1e-9) + (1 - wp[:, 0]) * V   # parciales: mezcla con lo observado
        S = wp * Q + (1 - wp) * S
        res.append(np.nan_to_num(np.maximum(V - Oto, 0)[:, None] * S))
    return res


def project(base: Base, current: pd.DataFrame, candidates: dict, params: dict | None = None,
            rule=None, with_sims: bool = True) -> dict:
    """
    current: columnas `unit`, `frac` (fracción escrutada de la unidad, 0-1) y una por candidato.
    candidates: {candidato: grupo_base}; varios candidatos pueden compartir grupo
                (p. ej. candidatos nuevos que en la base estaban dentro de "otros").
    rule: función(votos_por_region[R, C], candidatos, regiones) -> dict (regla electoral del país).
    """
    p = {**DEFAULTS, **(params or {})}
    G, C = base.groups, list(candidates)
    K, n = len(G), len(base.unit)
    gi = np.array([G.index(candidates[c]) for c in C])

    cur = current.copy()
    cur["unit"] = cur["unit"].astype(str)
    known = cur["unit"].isin(base.idx.keys())
    extra = cur[~known]                       # unidades sin base: sólo suman lo observado
    cur = cur[known]
    f = np.zeros(n)
    Oc = np.zeros((n, len(C)))
    ii = cur["unit"].map(base.idx).to_numpy(int)
    f[ii] = cur["frac"].clip(0, 1).to_numpy(float)
    Oc[ii] = cur[C].fillna(0).to_numpy(float)
    O = np.zeros((n, K))
    for c in range(len(C)):
        O[:, gi[c]] += Oc[:, c]
    counted = (f > 0) & (O.sum(1) > 0)
    full = counted & (f >= 0.999)

    Y = _targets(base, O, f, counted, p["scale"])
    Zb = to_space(base.P, base.ref, p["scale"])
    # peso de cada unidad en el ajuste: votos^w_pow (1 = cada voto pesa igual; 0.5 = compromiso)
    w = (base.Vb + 1.0) ** p["w_pow"] * np.clip(f, 0, 1)
    Yh = _fit_predict(base, Y, w, counted, p) if counted.sum() >= 5 else np.zeros_like(Y)

    # unidades parciales: lo observado pesa según cuánto se escrutó
    wp = np.where(counted, f / (f + p["phi"]), 0.0)
    wp = np.where(full, 1.0, wp)[:, None]
    Zs = Zb + wp * Y[:, :K] + (1 - wp) * Yh[:, :K]
    t = wp[:, 0] * Y[:, K] + (1 - wp[:, 0]) * Yh[:, K]
    Oto = O.sum(1)
    Vhat = np.where(full, Oto, np.maximum((base.Vb + 1.0) * np.exp(t) - 1.0, Oto))
    rem = Vhat - Oto
    comp = _composition(base, Oc, O, gi, counted, p)
    Gm = rem[:, None] * from_space(Zs, p["scale"])           # votos restantes por grupo (modelo)
    delta = np.zeros_like(Gm)
    if p["ensemble"] and counted.sum() >= 5:
        # ensamble con pesos iguales (por defecto modelo + vecinos: el más robusto en EEUU 2020, 2024 y Argentina 2019)
        sw, nb = _simple_preds(base, O, f, counted, wp, p)
        parts = [x for k, x in (("modelo", Gm), ("swing", sw), ("vecinos", nb)) if k in p["ens"]]
        Ge = np.where(full[:, None], 0.0, sum(parts) / len(parts))
        delta = Ge - Gm
        Gm = Ge
        Vhat = Oto + Gm.sum(1)
    unit_tot = Oc + Gm[:, gi] * comp
    obs_extra = extra[C].fillna(0).to_numpy(float).sum(0) if len(extra) else np.zeros(len(C))

    R = len(base.regions)
    def agg(T):
        A = np.zeros((R, len(C))); np.add.at(A, base.rid, T); return A

    reg_obs, reg_proj = agg(Oc), agg(unit_tot)
    nat_obs, nat_proj = reg_obs.sum(0) + obs_extra, reg_proj.sum(0) + obs_extra
    sh = lambda A: A / np.maximum(A.sum(-1, keepdims=True), 1e-9)
    out = dict(
        candidates=C, regions=[str(r) for r in base.regions],
        counted_frac=float((Oto.sum() + obs_extra.sum()) / max(Vhat.sum() + obs_extra.sum(), 1)),
        counted_units=int(counted.sum()), units=int(n),
        crude=sh(nat_obs).tolist(), proj=sh(nat_proj).tolist(),
        votes_proj=nat_proj.tolist(), votes_counted=nat_obs.tolist(),
        region_crude=sh(reg_obs).tolist(), region_proj=sh(reg_proj).tolist(),
        region_counted=(np.bincount(base.rid, Oto, R) / np.maximum(np.bincount(base.rid, Vhat, R), 1)).tolist(),
        region_votes=reg_proj.sum(1).tolist(),
        # por unidad (para los mapas; engine/output.py los agrega a la unidad de mapa)
        unit_obs=Oc, unit_proj=unit_tot, unit_expected=Vhat,
    )
    if rule is not None:
        out["rule_point"] = rule(reg_proj, C, out["regions"])
    if not with_sims or counted.sum() < 20:
        return out

    # ---------------- simulación
    S_u, S_r = _error_model(base, Y, w, counted, p)
    if p["tau_feat"] > 0:
        S_f = _profile_error(base, Y, w, counted, p)
        Lf = np.stack([np.linalg.cholesky(_psd(S) + 1e-9 * np.eye(K + 1)) for S in S_f])
        # distancia de cada unidad al perfil medio de lo ya contado
        dF = base.F - np.average(base.F[counted], axis=0, weights=w[counted])
    rng = np.random.default_rng(p["seed"] + 1)
    Lu = np.linalg.cholesky(S_u + 1e-9 * np.eye(K + 1))
    Lr = np.linalg.cholesky(S_r + 1e-9 * np.eye(K + 1))
    n_r = np.bincount(base.rid[counted], minlength=R)
    frac_c = out["counted_frac"]
    s_r = np.sqrt(p["kappa_r"] / (n_r + p["kappa_r"]))        # regiones con datos: shock menor
    s_u = np.clip((np.median(base.Vb) / (base.Vb + 1)) ** 0.25, 0.5, 2.0)
    cal = p["calib"]
    if isinstance(cal, (list, tuple)):                        # calibración por tramo de escrutinio
        xs, ys = zip(*cal)
        cal = float(np.interp(out["counted_frac"], xs, ys))
    scale = cal * (1 - wp)                                    # lo ya contado no tiene error
    def regional(E):
        """Votos simulados por región y candidato para un lote de errores E[m, n, K+1]."""
        E = E * scale[None]
        Vd = np.maximum((base.Vb + 1.0) * np.exp(t[None] + E[..., K]) - 1.0, Oto[None])
        remd = np.where(full[None], 0.0, Vd - Oto[None])
        Gd = np.maximum(from_space(Zs[None] + E[..., :K], p["scale"]) * remd[..., None] + delta[None], 0.0)
        Sd = Gd[..., gi] * comp[None] + Oc[None]
        A = np.zeros((len(E), R, len(C)))
        for r in range(R):                                    # agregación por región
            A[:, r] = Sd[:, base.rid == r].sum(1)
        return A

    RS, RS0 = [], []
    rng_f = np.random.default_rng(p["seed"] + 2)
    for _ in range(int(np.ceil(p["n_sims"] / 50))):
        m = 50
        er = (rng.standard_normal((m, R, K + 1)) @ Lr.T) * s_r[None, :, None] * _tmix(rng_f, (m, R, 1), p["t_df"])
        # shock nacional común a todo lo que falta: lo contado puede no ser representativo en bloque
        er = er + (rng.standard_normal((m, 1, K + 1)) @ Lr.T) * np.sqrt(p["tau_nat"] * (1 - frac_c)) * _tmix(rng_f, (m, 1, 1), p["t_df"])
        eu = (rng.standard_normal((m, n, K + 1)) @ Lu.T) * s_u[None, :, None]
        E = er[:, base.rid] + eu
        if p["tau_feat"] > 0:
            # error de pendiente por perfil: unidades parecidas entre sí se equivocan juntas
            # generador aparte: las simulaciones sin este shock quedan idénticas a las de siempre
            b = np.einsum("jkl,mjl->mjk", Lf, rng_f.standard_normal((m, base.nF, K + 1))) * _tmix(rng_f, (m, 1, 1), p["t_df"])
            RS0.append(regional(E))
            E = E + np.sqrt(p["tau_feat"]) * np.einsum("nj,mjk->mnk", dF, b)
        RS.append(regional(E))
    RS = np.concatenate(RS)
    if RS0:
        # el shock por perfil sólo ensancha: se re-centra cada región en la mediana sin ese shock,
        # porque por la transformación no lineal corre la mediana (y empeoraba el error al principio)
        sh_ = lambda X: X / np.maximum(X.sum(2, keepdims=True), 1e-9)
        d = np.median(sh_(np.concatenate(RS0)), 0) - np.median(sh_(RS), 0)
        RS = np.maximum(RS + d[None] * RS.sum(2, keepdims=True), 0.0)
    nat = RS.sum(1) + obs_extra
    NS = nat / nat.sum(1, keepdims=True)
    rule_sims = [rule(RS[s], C, out["regions"]) for s in range(len(RS))] if rule is not None else []
    RSh = RS / np.maximum(RS.sum(2, keepdims=True), 1e-9)
    ws = np.full(len(NS), 1.0 / len(NS))
    if p["polls"]:
        # prior de encuestas (estilo Silver): se re-ponderan las simulaciones por la verosimilitud
        # del promedio de encuestas; pesa al principio, cuando lo que falta contar es mucho
        from .polls import reweight
        ws = reweight(NS, C, p["polls"], p["poll_sd"], p["poll_df"])
        out["polls_ess"] = float(1.0 / (ws ** 2).sum())
    from .polls import wquantile
    q = lambda X, a: (np.quantile(X, a, axis=0) if not p["polls"] else wquantile(X, a, ws)).tolist()
    # el punto central pasa a ser la mediana simulada (corrige el sesgo de la transformación no lineal)
    out.update(proj_point=out["proj"], proj=q(NS, .5), proj_lo=q(NS, .05), proj_hi=q(NS, .95),
               region_proj=q(RSh, .5), region_lo=q(RSh, .05), region_hi=q(RSh, .95), n_sims=int(len(NS)))
    o = np.argsort(out["proj"])[::-1][:2]
    mg = NS[:, o[0]] - NS[:, o[1]]
    out["margin"] = dict(a=C[o[0]], b=C[o[1]], mid=q(mg, .5), lo=q(mg, .05), hi=q(mg, .95),
                         p_a_ahead=float(ws @ (mg > 0)))
    rmg = RSh[:, :, o[0]] - RSh[:, :, o[1]]
    out["region_p_a_ahead"] = np.einsum("s,sr->r", ws, (rmg > 0).astype(float)).tolist()
    if rule is not None:
        out["rule"] = summarize(rule_sims, ws if p["polls"] else None)
    return out


def summarize(sims, w=None):
    """Resume las simulaciones de la regla; `w` son pesos por simulación (prior de encuestas)."""
    from .polls import wquantile
    w = np.full(len(sims), 1.0 / len(sims)) if w is None else np.asarray(w)
    out = {}
    for k in sims[0]:
        v = [s[k] for s in sims]
        if isinstance(v[0], (bool, np.bool_)):
            out[k] = float(w @ np.array(v, float))
        elif isinstance(v[0], (int, float, np.integer, np.floating)):
            x = np.array(v, float)
            out[k] = dict(mid=float(wquantile(x, .5, w)), lo=float(wquantile(x, .05, w)), hi=float(wquantile(x, .95, w)))
        elif isinstance(v[0], str):
            v = np.array(v)
            out[k] = {str(x): float(w[v == x].sum()) for x in np.unique(v)}
    return out
