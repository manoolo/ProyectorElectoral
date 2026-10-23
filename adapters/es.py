"""España: arma la base canónica (Congreso) por municipio con los ficheros del Ministerio del Interior.

Fuente: infoelectoral.interior.gob.es → Área de descargas → Congreso → "Municipios" (zip con
ficheros .DAT de ancho fijo, latin-1). Lo que se usa:
  03xxaamm.DAT  candidaturas: código (pos. 9-14), siglas (15-64), denominación (65-214)
  05xxaamm.DAT  datos comunes por municipio: provincia (12-13), municipio (14-16), distrito (17-18),
                nombre (19-118), votos en blanco (190-197)
  06xxaamm.DAT  votos por candidatura y municipio: provincia (10-11), municipio (12-14),
                distrito (15-16), candidatura (17-22), votos (23-30)
Distrito 99 = total del municipio. Municipio 999 = voto CERA (residentes en el exterior), que se
escruta días después y queda fuera del modelo.

La unidad es el código INE del municipio (provincia + municipio, 5 dígitos), la región la provincia
(código INE de 2 dígitos, la circunscripción del Congreso). Las coordenadas salen de es-atlas (IGN).

  python -m adapters.es 2023                  # baja el zip (correr en tu máquina) y arma data/es_base.csv
  python -m adapters.es data/02202307_MUNI.zip
"""
from pathlib import Path
import io, json, re, tarfile, unicodedata, urllib.request, zipfile
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
GROUPS = ["pp", "psoe", "vox", "sumar", "erc", "junts", "bildu", "pnv", "bng", "cc", "upn", "otros"]
ZIPS = {2023: "02202307", 2019: "02201911", 2016: "02201606"}
URL = "https://infoelectoral.interior.gob.es/estaticos/docxl/apliextr/{c}_MUNI.zip"
ATLAS = "https://registry.npmjs.org/es-atlas/-/es-atlas-0.6.0.tgz"

PROV = {"01": "Araba/Álava", "02": "Albacete", "03": "Alicante/Alacant", "04": "Almería", "05": "Ávila", "06": "Badajoz",
        "07": "Illes Balears", "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón/Castelló",
        "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada",
        "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida",
        "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia", "31": "Navarra", "32": "Ourense",
        "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra", "37": "Salamanca",
        "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla", "42": "Soria", "43": "Tarragona",
        "44": "Teruel", "45": "Toledo", "46": "Valencia/València", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora",
        "50": "Zaragoza", "51": "Ceuta", "52": "Melilla"}


def _norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()


# siglas → grupo. Se prueba en orden; lo que no entra va a "otros" (Cs, CUP, PRC, Teruel Existe, NC…).
PATTERNS = [("psoe", r"PSOE|^PSC\b|^PSE\b"), ("pp", r"^P\.?P\b"), ("vox", r"\bVOX\b"),
            ("sumar", r"SUMAR|PODEMOS|^ECP\b|EN COMU|MAS PAIS|COMPROMIS|^IU\b|MAS MADRID"),
            ("erc", r"\bERC\b"), ("junts", r"JUNTS|JXCAT"), ("bildu", r"BILDU"), ("pnv", r"PNV"),
            ("bng", r"\bB\.?N\.?G\.?\b"), ("cc", r"^CC\b|^CCA\b|^CC-|^CCA-|COALICION CANARIA"), ("upn", r"\bUPN\b|^NA\+")]


def group_of(siglas):
    s = _norm(siglas)
    for g, pat in PATTERNS:
        if re.search(pat, s):
            return g
    return "otros"


def descargar(year: int) -> Path:
    """Baja el zip del Interior. Desde el entorno donde se armó el proyecto el dominio está
    bloqueado: correrlo en tu máquina, o bajarlo a mano y pasar la ruta."""
    dest = DATA / f"{ZIPS[year]}_MUNI.zip"
    if not dest.exists():
        print(f"bajando {URL.format(c=ZIPS[year])} …")
        urllib.request.urlretrieve(URL.format(c=ZIPS[year]), dest)
    return dest


def _dat(z, prefix):
    names = [n for n in z.namelist() if Path(n).name.startswith(prefix) and n.upper().endswith(".DAT")]
    if not names:
        raise ValueError(f"el zip no trae el fichero {prefix}xxxxxx.DAT: {z.namelist()}")
    return z.read(names[0]).decode("latin-1").splitlines()


def read_zip(path):
    """Devuelve (votos por municipio y candidatura, nombres y blancos por municipio, candidaturas)."""
    with zipfile.ZipFile(path) as z:
        c03, c05, c06 = _dat(z, "03"), _dat(z, "05"), _dat(z, "06")
    cand = pd.DataFrame([(l[8:14], l[14:64].strip(), l[64:214].strip()) for l in c03 if len(l) >= 64],
                        columns=["cand", "siglas", "nombre"])
    cand["g"] = cand.siglas.map(group_of)
    v = pd.DataFrame([(l[9:11], l[11:14], l[14:16], l[16:22], l[22:30]) for l in c06 if len(l) >= 30],
                     columns=["prov", "muni", "dist", "cand", "votos"])
    v["votos"] = pd.to_numeric(v.votos, errors="coerce").fillna(0)
    v = v[(v.dist == "99") & (v.muni != "999") & v.prov.isin(PROV)]
    m = pd.DataFrame([(l[11:13], l[13:16], l[16:18], l[18:118].strip(), l[189:197]) for l in c05 if len(l) >= 197],
                     columns=["prov", "muni", "dist", "name", "blancos"])
    m = m[(m.dist == "99") & (m.muni != "999")]
    m["blancos"] = pd.to_numeric(m.blancos, errors="coerce").fillna(0)
    m["unit"] = m.prov + m.muni
    if v.empty or v.cand.isin(cand.cand).mean() < 0.99:
        raise ValueError("no se pudo leer el fichero 06 (¿cambió el formato?)")
    return v.merge(cand[["cand", "siglas", "g"]], on="cand", how="left"), m.set_index("unit"), cand


def from_zip(path, coords=True):
    v, m, cand = read_zip(path)
    v["unit"] = v.prov + v.muni
    piv = v.pivot_table(index=["unit", "prov"], columns="g", values="votos", aggfunc="sum", fill_value=0).reset_index()
    for g in GROUPS:
        if g not in piv:
            piv[g] = 0
    out = pd.DataFrame({"unit": piv.unit, "region": piv.prov, "name": piv.unit.map(m["name"]).fillna(piv.unit)})
    if coords:
        geo = municipios()
        c = geo.set_index("unit")
        out["lat"], out["lon"] = out.unit.map(c.lat), out.unit.map(c.lon)
        miss = out.lat.isna()
        if miss.any():                  # municipios nuevos o fusionados después del atlas: centro de su provincia
            pc = geo.assign(region=geo.unit.str[:2]).groupby("region")[["lat", "lon"]].mean()
            out.loc[miss, "lat"] = out.loc[miss, "region"].map(pc.lat)
            out.loc[miss, "lon"] = out.loc[miss, "region"].map(pc.lon)
            print(f"aviso: {miss.sum()} municipios sin coordenadas en es-atlas (van al centro de su provincia)")
    for g in GROUPS:
        out[g] = piv[g].astype(int)
    tot = v.votos.sum()
    print("votos por grupo:", {g: f"{out[g].sum() / tot:.1%}" for g in GROUPS},
          f"· blancos {m.blancos.sum() / (tot + m.blancos.sum()):.2%}")
    top = v.groupby(["g", "siglas"]).votos.sum().sort_values(ascending=False)
    print("otros más votados:", top.loc["otros"].head(6).to_dict() if "otros" in top else {})
    return out


# ------------------------------------------------------------------ geometría (es-atlas, IGN)
def atlas() -> dict:
    """TopoJSON de municipios de es-atlas (se baja del registro de npm una vez)."""
    dest = DATA / "es_municipalities.topojson"
    if not dest.exists():
        print(f"bajando {ATLAS} …")
        raw = urllib.request.urlopen(ATLAS).read()
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            dest.write_bytes(t.extractfile("package/es/municipalities.json").read())
    return json.loads(dest.read_text(encoding="utf-8"))


def topo_features(topo, obj):
    """TopoJSON → lista de features GeoJSON (Polygon/MultiPolygon) del objeto `obj`."""
    sx, sy = topo["transform"]["scale"]; tx, ty = topo["transform"]["translate"]
    arcs = []
    for a in topo["arcs"]:
        q = np.cumsum(np.array(a, float), 0)
        arcs.append(np.c_[q[:, 0] * sx + tx, q[:, 1] * sy + ty])
    def arc(i):
        return arcs[i] if i >= 0 else arcs[~i][::-1]
    def ring(ix):
        pts = [arc(ix[0])] + [arc(i)[1:] for i in ix[1:]]
        return np.concatenate(pts).round(6).tolist()
    feats = []
    for g in topo["objects"][obj]["geometries"]:
        if g["type"] == "Polygon":
            coords = [[ring(r) for r in g["arcs"]]]
        elif g["type"] == "MultiPolygon":
            coords = [[ring(r) for r in p] for p in g["arcs"]]
        else:
            continue
        feats.append(dict(type="Feature", properties=dict(id=g.get("id"), **g.get("properties", {})),
                          geometry=dict(type="MultiPolygon", coordinates=coords)))
    return feats


def municipios() -> pd.DataFrame:
    """unit (INE), nombre y centroide (lat, lon) de cada municipio."""
    rows = []
    for f in topo_features(atlas(), "municipalities"):
        best, area = None, 0.0
        for p in f["geometry"]["coordinates"]:
            r = np.array(p[0])
            x, y = r[:, 0], r[:, 1]
            c = x[:-1] * y[1:] - x[1:] * y[:-1]
            a = c.sum() / 2
            if abs(a) > abs(area) and a != 0:
                area, best = a, (((x[:-1] + x[1:]) * c).sum() / (6 * a), ((y[:-1] + y[1:]) * c).sum() / (6 * a))
        if best:
            rows.append((f["properties"]["id"], f["properties"].get("name"), best[1], best[0]))
    return pd.DataFrame(rows, columns=["unit", "name", "lat", "lon"])


def pair(base_year=2019, target_year=2023):
    """Base y resultado final por municipio, para el backtest y la repetición."""
    b, t = from_zip(descargar(base_year)), from_zip(descargar(target_year), coords=False)
    common = set(b.unit) & set(t.unit)
    b, t = b[b.unit.isin(common)].reset_index(drop=True), t[t.unit.isin(common)].reset_index(drop=True)
    t = t[["unit", *GROUPS]].copy(); t["frac"] = 1.0
    return b, t


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "2023"
    base = from_zip(descargar(int(arg)) if arg.isdigit() else Path(arg))
    base.to_csv(DATA / "es_base.csv", index=False)
    print(f"{len(base)} municipios → data/es_base.csv")
