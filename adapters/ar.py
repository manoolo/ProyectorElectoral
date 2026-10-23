"""Argentina. Unidad: circuito electoral. Región: provincia (distrito electoral).

Fuentes:
  * electorAr (PoliticaArgentina/data_warehouse): escrutinio provisorio por mesa, presidente,
    generales 2003-2019. Formato ancho: una columna por código de agrupación.
  * DINE (datos abiertos 2023 en adelante): formato largo, una fila por mesa y agrupación.
    `from_dine` lo convierte. Verificá los nombres de columnas al bajar el archivo.
Coordenadas: centroide del departamento (geoAr, censo 2010), cruzado por nombre dentro de la provincia.
Sólo se usan votos afirmativos (sin blancos ni nulos): es la base de la regla de los arts. 97 y 98.
"""
import json
import unicodedata
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = "https://raw.githubusercontent.com/PoliticaArgentina/data_warehouse/master/electorAr/data/escrutinios_provisorios/arg_presi_gral{y}.csv"

# código de distrito electoral → (nombre, código INDEC de provincia)
DIST = {"01": ("CABA", "02"), "02": ("Buenos Aires", "06"), "03": ("Catamarca", "10"), "04": ("Córdoba", "14"),
        "05": ("Corrientes", "18"), "06": ("Chaco", "22"), "07": ("Chubut", "26"), "08": ("Entre Ríos", "30"),
        "09": ("Formosa", "34"), "10": ("Jujuy", "38"), "11": ("La Pampa", "42"), "12": ("La Rioja", "46"),
        "13": ("Mendoza", "50"), "14": ("Misiones", "54"), "15": ("Neuquén", "58"), "16": ("Río Negro", "62"),
        "17": ("Salta", "66"), "18": ("San Juan", "70"), "19": ("San Luis", "74"), "20": ("Santa Cruz", "78"),
        "21": ("Santa Fe", "82"), "22": ("Santiago del Estero", "86"), "23": ("Tucumán", "90"),
        "24": ("Tierra del Fuego", "94")}

# agrupación → grupo, por elección (códigos de electorAr)
PARTIES = {
    2015: {"0131": "peronismo", "0135": "jxc"},          # Scioli (FPV), Macri (Cambiemos)
    # En el archivo por mesa de 2019 los códigos no son los del listado de agrupaciones; se
    # identificaron por su share nacional: 00005 = 48,3% (Frente de Todos), 00009 = 40,2% (JxC).
    2019: {"00005": "peronismo", "00009": "jxc"},        # Fernández (FdT), Macri (JxC)
}
GROUPS = ["peronismo", "jxc", "otros"]


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = " ".join(s.replace(".", " ").split())
    if s.startswith("comuna "):
        s = "comuna " + s.split()[1].lstrip("0")
    return s


def load_electorar(year: int) -> pd.DataFrame:
    f = DATA / f"ar_presi_gral{year}.csv"
    df = pd.read_csv(f if f.exists() else RAW.format(y=year), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    meta = {"codprov", "depto", "coddepto", "circuito", "mesa", "electores", "blancos", "nulos"}
    parties = [c for c in df.columns if c not in meta]
    for c in parties:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    out = pd.DataFrame({"codprov": df.codprov.str.strip().str.zfill(2),
                        "coddepto": df.coddepto.str.strip().str.zfill(3),
                        "depto": df.depto.str.strip(),
                        "circuito": df.circuito.str.strip().str.lstrip("0").replace("", "0")})
    mp = PARTIES[year]
    for g in GROUPS:
        cols = [c for c in parties if mp.get(c, "otros") == g]
        out[g] = df[cols].sum(1) if cols else 0.0
    out["unit"] = out.codprov + "|" + out.coddepto + "|" + out.circuito
    return out.groupby(["unit", "codprov", "coddepto", "depto"], as_index=False)[GROUPS].sum()


def _coords(df: pd.DataFrame) -> pd.DataFrame:
    g = json.loads((DATA / "ar_deptos.geojson").read_text())
    rows = []
    for ft in g["features"]:
        geom = ft.get("geometry") or {}
        geoms = geom.get("geometries", [geom])
        polys = []
        for gg in geoms:
            if gg.get("type") == "MultiPolygon":
                polys += gg["coordinates"]
            elif gg.get("type") == "Polygon":
                polys.append(gg["coordinates"])
        if not polys:
            continue
        pts = np.concatenate([np.asarray(p[0], float) for p in polys])
        rows.append((ft["properties"]["prov_cod"], _norm(ft["properties"]["depto"]), pts[:, 1].mean(), pts[:, 0].mean()))
    geo = pd.DataFrame(rows, columns=["indec", "dn", "lat", "lon"]).drop_duplicates(["indec", "dn"])
    df = df.copy()
    df["indec"] = df.codprov.map(lambda c: DIST[c][1])
    df["dn"] = df.depto.map(_norm)
    df = df.merge(geo, on=["indec", "dn"], how="left")
    prov = geo.groupby("indec")[["lat", "lon"]].mean()
    miss = df.lat.isna()
    df.loc[miss, ["lat", "lon"]] = prov.loc[df.loc[miss, "indec"]].to_numpy()
    df.attrs["geo_match"] = float(1 - miss.mean())
    return df


def pair(base_year: int, target_year: int):
    """Base y resultado final alineados por circuito. Los circuitos que no existen en ambas
    elecciones se juntan en un 'resto' por departamento."""
    b, t = load_electorar(base_year), load_electorar(target_year)
    common = set(b.unit) & set(t.unit)
    for d in (b, t):
        m = ~d.unit.isin(common)
        d.loc[m, "unit"] = d.codprov + "|" + d.coddepto + "|resto"
    agg = {"codprov": "first", "coddepto": "first", "depto": "first", **{g: "sum" for g in GROUPS}}
    b, t = b.groupby("unit", as_index=False).agg(agg), t.groupby("unit", as_index=False).agg(agg)
    b, t = b[b.unit.isin(t.unit)], t[t.unit.isin(b.unit)]
    ok = set(b.unit[b[GROUPS].sum(1) > 0]) & set(t.unit[t[GROUPS].sum(1) > 0])   # sin unidades vacías
    b, t = b[b.unit.isin(ok)], t[t.unit.isin(ok)]
    b = _coords(b)
    b["region"] = b.codprov.map(lambda c: DIST[c][0])
    t = t.copy(); t["frac"] = 1.0
    circ = b.unit.str.split("|").str[2]
    b["name"] = np.where(circ == "resto", b.depto + " (resto)", b.depto + ", circuito " + circ)
    out_b = b[["unit", "region", "name", "lat", "lon", *GROUPS]].reset_index(drop=True)
    out_b.attrs["geo_match"] = b.attrs.get("geo_match")
    return out_b, t[["unit", "frac", *GROUPS]].reset_index(drop=True)


def from_dine(path, cargo="PRESIDENTE", party_map=None, **cols):
    """CSV de la DINE (formato largo) → base canónica por circuito.
    party_map: {"texto en el nombre de la agrupación": "grupo"}; el resto va a 'otros'."""
    c = dict(dist="distrito_id", sec="seccion_id", circ="circuito_id", cargo="cargo_nombre",
             party="agrupacion_nombre", tipo="votos_tipo", votes="votos_cantidad", depto="seccion_nombre", **cols)
    party_map = party_map or json.loads((ROOT / "config" / "ar.json").read_text())["party_map"]
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df = df[df[c["cargo"]].str.upper().str.contains(cargo) & (df[c["tipo"]].str.upper() == "POSITIVO")]
    df[c["votes"]] = pd.to_numeric(df[c["votes"]], errors="coerce").fillna(0)
    groups = list(dict.fromkeys(list(party_map.values()) + ["otros"]))
    df["g"] = "otros"
    for key, g in party_map.items():
        df.loc[df[c["party"]].str.upper().str.contains(key.upper(), regex=False), "g"] = g
    df["codprov"] = df[c["dist"]].str.zfill(2)
    df["coddepto"] = df[c["sec"]].str.zfill(3)
    df["circuito"] = df[c["circ"]].str.strip().str.lstrip("0").replace("", "0")
    df["unit"] = df.codprov + "|" + df.coddepto + "|" + df.circuito
    piv = df.pivot_table(index=["unit", "codprov", "coddepto", c["depto"]], columns="g", values=c["votes"],
                         aggfunc="sum", fill_value=0).reset_index().rename(columns={c["depto"]: "depto"})
    mesa = cols.get("mesa", "mesa_id")
    if mesa in df:                       # cantidad de mesas por circuito: sirve para medir el avance en vivo
        piv = piv.merge(df.groupby("unit")[mesa].nunique().rename("mesas").reset_index(), on="unit", how="left")
    for g in groups:
        if g not in piv:
            piv[g] = 0
    piv = _coords(piv)
    piv["region"] = piv.codprov.map(lambda x: DIST.get(x, (x,))[0])
    keep = ["unit", "region", "lat", "lon", *groups] + (["mesas"] if "mesas" in piv else [])
    return piv[keep]


if __name__ == "__main__":
    import sys
    base = from_dine(sys.argv[1])
    base.to_csv(DATA / "ar_base.csv", index=False)
    print(f"{len(base)} circuitos → data/ar_base.csv")
