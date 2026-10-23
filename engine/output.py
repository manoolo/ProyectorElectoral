"""Convierte la salida del motor en un 'frame' liviano para la página."""
import numpy as np

r4 = lambda v: None if v is None else [round(float(x), 4) for x in v]
pm = lambda x: np.rint(np.asarray(x) * 1000).astype(int).tolist()     # por mil, entero: achica el JSON


def frame(out: dict, ts: str | None = None, geo: dict | None = None) -> dict:
    f = dict(ts=ts, counted=round(out["counted_frac"], 4), units=[out["counted_units"], out["units"]],
             crude=r4(out["crude"]), proj=r4(out["proj"]), lo=r4(out.get("proj_lo")), hi=r4(out.get("proj_hi")),
             margin=out.get("margin"), rule=out.get("rule"), rule_point=out.get("rule_point"),
             regions=dict(counted=r4(out["region_counted"]), proj=[r4(x) for x in out["region_proj"]],
                          crude=[r4(x) for x in out["region_crude"]], votes=[round(v) for v in out["region_votes"]],
                          p_ahead=r4(out.get("region_p_a_ahead"))))
    if geo is not None and "unit_obs" in out:
        f["map"] = map_frame(out, geo)
    return f


def unit_keys(units, unit_key):
    """Clave de mapa de cada unidad del modelo. unit_key: None (la misma), o N para quedarse con
    las primeras N partes separadas por '|' (Argentina: distrito|sección|circuito → distrito|sección)."""
    units = np.asarray(units, str)
    if not unit_key:
        return units
    return np.array(["|".join(u.split("|")[:unit_key]) for u in units])


def geo_index(base, cfg: dict) -> dict | None:
    """Índice unidad del modelo → unidad de mapa, y el resultado de la base por unidad de mapa
    y sus votos válidos (para el mapa de corrimientos y la comparación con la elección anterior). Se arma una vez por corrida."""
    g = cfg.get("geo")
    if not g:
        return None
    keys = unit_keys(base.unit, g.get("unit_key"))
    ids, inv = np.unique(keys, return_inverse=True)
    V = np.zeros((len(ids), len(base.groups)))
    np.add.at(V, inv, base.df[base.groups].to_numpy(float))
    sh = V / np.maximum(V.sum(1, keepdims=True), 1)
    return dict(ids=ids.tolist(), inv=inv, n=len(ids),
                doc=dict(map=g["map"], ids=ids.tolist(), groups=base.groups, base=pm(sh),
                         bv=np.rint(V.sum(1)).astype(int).tolist()))


def map_frame(out: dict, geo: dict) -> dict:
    """Por unidad de mapa con votos contados: fracción escrutada y reparto del voto contado por
    candidato, ambos por mil, y votos contados (n). Sólo van las unidades que cambiaron desde el frame anterior de la
    misma corrida (en una repetición cada unidad aparece pocas veces); la página los acumula.
    El primer frame de cada corrida es completo."""
    inv, n = geo["inv"], geo["n"]
    def agg(T):
        A = np.zeros((n,) + np.shape(T)[1:]); np.add.at(A, inv, T); return A
    O, E = agg(out["unit_obs"]), agg(out["unit_expected"])
    tot = O.sum(1)
    F = np.array(pm(np.clip(tot / np.maximum(E, 1), 0, 1)))
    V = np.array(pm(O / np.maximum(tot[:, None], 1)))
    prev = geo.get("prev")
    ch = tot > 0
    if prev is not None:
        ch &= (F != prev[0]) | (V != prev[1]).any(1)
    geo["prev"] = (F, V)
    i = np.flatnonzero(ch)
    return dict(i=i.tolist(), f=F[i].tolist(), v=V[i].tolist(), n=np.rint(tot[i]).astype(int).tolist())
