"""Arma los mapas de la página: site/geo/<país>.json (país entero) y site/geo/<país>/<región>.json (detalle).

  python build_maps.py            # todos
  python build_maps.py br us      # algunos

Los polígonos se proyectan y simplifican con mapshaper (Node: `npm i -g mapshaper`, o lo baja
`npx` solo) y se guardan como trazos SVG ya proyectados, así el navegador no necesita librerías.
Cada polígono lleva el `id` de la unidad de mapa; config/<país>.json dice cómo se pasa de la
unidad del modelo a esa clave (`geo.unit_key`). Sólo hace falta correrlo si cambia la geometría.

Para sumar un país: un GeoJSON con un polígono por unidad y una función `prep_<país>` que le
ponga a cada feature `id` (clave de unidad), `r` (región, igual que en la base) y `n` (nombre).
"""
import csv, json, os, shutil, subprocess, sys, tempfile, unicodedata, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "site" / "geo"
SIZE = 1000                       # lado mayor del mapa en unidades SVG

US_STATES = {"01": ("AL", "Alabama"), "02": ("AK", "Alaska"), "04": ("AZ", "Arizona"), "05": ("AR", "Arkansas"),
    "06": ("CA", "California"), "08": ("CO", "Colorado"), "09": ("CT", "Connecticut"), "10": ("DE", "Delaware"),
    "11": ("DC", "Distrito de Columbia"), "12": ("FL", "Florida"), "13": ("GA", "Georgia"), "15": ("HI", "Hawái"),
    "16": ("ID", "Idaho"), "17": ("IL", "Illinois"), "18": ("IN", "Indiana"), "19": ("IA", "Iowa"), "20": ("KS", "Kansas"),
    "21": ("KY", "Kentucky"), "22": ("LA", "Luisiana"), "23": ("ME", "Maine"), "24": ("MD", "Maryland"),
    "25": ("MA", "Massachusetts"), "26": ("MI", "Míchigan"), "27": ("MN", "Minnesota"), "28": ("MS", "Misisipi"),
    "29": ("MO", "Misuri"), "30": ("MT", "Montana"), "31": ("NE", "Nebraska"), "32": ("NV", "Nevada"),
    "33": ("NH", "Nuevo Hampshire"), "34": ("NJ", "Nueva Jersey"), "35": ("NM", "Nuevo México"), "36": ("NY", "Nueva York"),
    "37": ("NC", "Carolina del Norte"), "38": ("ND", "Dakota del Norte"), "39": ("OH", "Ohio"), "40": ("OK", "Oklahoma"),
    "41": ("OR", "Oregón"), "42": ("PA", "Pensilvania"), "44": ("RI", "Rhode Island"), "45": ("SC", "Carolina del Sur"),
    "46": ("SD", "Dakota del Sur"), "47": ("TN", "Tennessee"), "48": ("TX", "Texas"), "49": ("UT", "Utah"),
    "50": ("VT", "Vermont"), "51": ("VA", "Virginia"), "53": ("WA", "Washington"), "54": ("WV", "Virginia Occidental"),
    "55": ("WI", "Wisconsin"), "56": ("WY", "Wyoming")}
BR_UF = {"11": ("RO", "Rondônia"), "12": ("AC", "Acre"), "13": ("AM", "Amazonas"), "14": ("RR", "Roraima"),
    "15": ("PA", "Pará"), "16": ("AP", "Amapá"), "17": ("TO", "Tocantins"), "21": ("MA", "Maranhão"), "22": ("PI", "Piauí"),
    "23": ("CE", "Ceará"), "24": ("RN", "Rio Grande do Norte"), "25": ("PB", "Paraíba"), "26": ("PE", "Pernambuco"),
    "27": ("AL", "Alagoas"), "28": ("SE", "Sergipe"), "29": ("BA", "Bahia"), "31": ("MG", "Minas Gerais"),
    "32": ("ES", "Espírito Santo"), "33": ("RJ", "Rio de Janeiro"), "35": ("SP", "São Paulo"), "41": ("PR", "Paraná"),
    "42": ("SC", "Santa Catarina"), "43": ("RS", "Rio Grande do Sul"), "50": ("MS", "Mato Grosso do Sul"),
    "51": ("MT", "Mato Grosso"), "52": ("GO", "Goiás"), "53": ("DF", "Distrito Federal")}
BR_URL = "https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-100-mun.json"


# nombres del censo que el escrutinio escribe distinto (normalizados con _norm)
AR_ALIAS = {"adolfo gonzales chaves": "gonzales chaves", "bartolome mitre": "arrecifes",
    "coronel de marina l rosales": "coronel rosales", "general juan madariaga": "general madariaga",
    "9 de julio": "nueve de julio", "antofagasta de la sierra": "na", "presidente roque saenz pena": "roque saenz pena",
    "fray justo santa maria de oro": "fray justo sta maria de oro", "libertador general san martin": "libertador gral san martin",
    "mayor luis j fontana": "mayor l j fontana", "1 de mayo": "primero de mayo", "florentino ameghino": "f ameghino",
    "rio senguer": "rio senger", "dr manuel belgrano": "general belgrano", "chical co": "chical-co",
    "coronel felipe varela": "felipe varela", "general angel v penaloza": "angel vicente penaloza",
    "general juan f quiroga": "juan facundo quiroga", "general ocampo": "general ortiz de ocampo", "lujan de cuyo": "lujan",
    "concepcion": "concepcion de la sierra", "pilnaniyeu": "pilcaniyeu", "san antonio": "san antonio oeste",
    "general jose de san martin": "san martin", "coronel pringles": "pringles", "general pedernera": "pedernera",
    "la capital": "pueyrredon", "general taboada": "taboada", "pelegrini": "pellegrini", "famalla": "famaillá",
    "juan b alberdi": "alberdi"}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = " ".join(s.replace(".", " ").split())
    return "comuna " + s.split()[1].lstrip("0") if s.startswith("comuna ") else s


def prep_us():
    g = json.loads((DATA / "counties.json").read_text(encoding="utf-8"))
    feats = []
    for f in g["features"]:
        p = f["properties"]
        if p["STATE"] not in US_STATES:            # Puerto Rico
            continue
        fips = p["STATE"] + p["COUNTY"]
        fips = {"46113": "46102"}.get(fips, fips)  # Shannon pasó a llamarse Oglala Lakota
        feats.append(dict(f, properties=dict(id=fips, r=US_STATES[p["STATE"]][0], n=p["NAME"])))
    names = {a: n for a, n in US_STATES.values()}
    return feats, names, dict(proj="albersusa", lo=4, hi=12, unit="Condado")


def prep_br():
    src = DATA / "br_municipios.geojson"
    if not src.exists():
        print("  bajando municipios de Brasil…")
        urllib.request.urlretrieve(BR_URL, src)
    g = json.loads(src.read_text(encoding="utf-8"))
    feats = [dict(f, properties=dict(id=f["properties"]["id"], r=BR_UF[f["properties"]["id"][:2]][0],
                                     n=f["properties"]["name"])) for f in g["features"]]
    names = {a: n for a, n in BR_UF.values()}
    return feats, names, dict(proj="+proj=poly +lon_0=-54 +datum=WGS84", lo=1.2, hi=10, unit="Municipio")


def prep_ar():
    """Departamentos del censo (INDEC). La clave es la del escrutinio: distrito|sección, cruzada por
    nombre dentro de la provincia con los resultados por mesa de 2019."""
    sys.path.insert(0, str(ROOT))
    from adapters.ar import DIST
    indec = {v[1]: k for k, v in DIST.items()}
    secs = {}
    with open(DATA / "ar_presi_gral2019.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cp, cd = row["codprov"].strip().zfill(2), row["coddepto"].strip().zfill(3)
            secs.setdefault((cp, _norm(row["depto"])), f"{cp}|{cd}")
    g = json.loads((DATA / "ar_deptos.geojson").read_text(encoding="utf-8"))
    feats, miss = [], []
    for f in g["features"]:
        p = f["properties"]
        cp = indec[p["prov_cod"]]
        dn = _norm(p["depto"])
        key = (secs.get((cp, dn)) or secs.get((cp, _norm(AR_ALIAS.get(dn, dn))))
               or secs.get((cp, dn.replace("libertador general ", ""))))
        if not key:
            miss.append(f"{DIST[cp][0]}: {p['depto']}")
            key = "x" + p["link"]
        feats.append(dict(f, properties=dict(id=key, r=DIST[cp][0], n=p["depto"])))
    if miss:
        print(f"  {len(miss)} departamentos sin cruce con el escrutinio (quedan con el color de su provincia):", "; ".join(miss[:8]), "…" if len(miss) > 8 else "")
    names = {v[0]: v[0] for v in DIST.values()}
    return feats, names, dict(proj="+proj=tmerc +lon_0=-65 +datum=WGS84", lo=6, hi=20, unit="Departamento")


def prep_es():
    """Municipios de es-atlas (IGN, códigos INE). Canarias se acerca a la península (como en los
    mapas electorales españoles) y Ceuta y Melilla se agrandan. Quedan afuera los territorios compartidos (53xxx, 54xxx) sin votantes."""
    sys.path.insert(0, str(ROOT))
    from adapters.es import PROV, atlas, topo_features
    feats = []
    for f in topo_features(atlas(), "municipalities"):
        u = f["properties"]["id"]
        if u[:2] not in PROV:
            continue
        if u[:2] in ("35", "38"):                 # Canarias: +7,5° de longitud, +6,8° de latitud (debajo de Andalucía)
            f["geometry"]["coordinates"] = [[[[x + 7.5, y + 6.8] for x, y in r] for r in p] for p in f["geometry"]["coordinates"]]
        if u[:2] in ("51", "52"):                 # Ceuta y Melilla, agrandadas 5 veces para poder tocarlas
            r0 = f["geometry"]["coordinates"][0][0]
            cx, cy = sum(x for x, _ in r0) / len(r0), sum(y for _, y in r0) / len(r0)
            f["geometry"]["coordinates"] = [[[[cx + 5 * (x - cx), cy + 5 * (y - cy)] for x, y in r] for r in p] for p in f["geometry"]["coordinates"]]
        feats.append(dict(f, properties=dict(id=u, r=u[:2], n=f["properties"].get("name") or u)))
    return feats, dict(PROV), dict(proj="+proj=lcc +lat_1=37 +lat_2=43 +lon_0=-3.5 +datum=WGS84", lo=3, hi=14, unit="Municipio")


PREP = dict(us=prep_us, br=prep_br, ar=prep_ar, es=prep_es)


def mapshaper(args):
    exe = os.environ.get("MAPSHAPER") or shutil.which("mapshaper")
    cmd = [exe] if exe else ["npx", "-y", "mapshaper@0.6.102"]
    subprocess.run(cmd + args, check=True, shell=os.name == "nt" and not exe)


def rings(geom):
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        return [r for p in geom["coordinates"] for r in p]
    if geom["type"] == "GeometryCollection":
        return [r for g in geom["geometries"] for r in rings(g)]
    return []


class Fit:
    """Lleva coordenadas proyectadas a la caja SVG (y hacia abajo)."""
    def __init__(self, feats):
        xs = [x for f in feats for r in rings(f["geometry"]) for x, _ in r]
        ys = [y for f in feats for r in rings(f["geometry"]) for _, y in r]
        self.x0, self.y1 = min(xs), max(ys)
        self.k = SIZE / max(max(xs) - self.x0, self.y1 - min(ys))
        self.w, self.h = (max(xs) - self.x0) * self.k, (self.y1 - min(ys)) * self.k

    def path(self, geom, dec):
        out, f = [], 10 ** dec
        for r in rings(geom):
            pts = [(round((x - self.x0) * self.k * f), round((self.y1 - y) * self.k * f)) for x, y in r]
            # relativo y entero sobre 10^dec: mucho más corto que coordenadas absolutas
            s, (px, py) = [f"M{pts[0][0] / f:g} {pts[0][1] / f:g}"], pts[0]
            rel = []
            for x, y in pts[1:]:
                if (x, y) != (px, py):
                    rel.append(f"{(x - px) / f:g} {(y - py) / f:g}")
                    px, py = x, y
            if len(rel) >= 2:
                out.append(s[0] + "l" + " ".join(rel).replace(" -", "-") + "z")
        return "".join(out)

    def bbox(self, geoms):
        xs, ys = [], []
        for g in geoms:
            for r in rings(g):
                for x, y in r:
                    xs.append((x - self.x0) * self.k); ys.append((self.y1 - y) * self.k)
        return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


def centroid(geom):
    best, area = None, 0
    for r in rings(geom):
        a = cx = cy = 0
        for (x0, y0), (x1, y1) in zip(r, r[1:]):
            c = x0 * y1 - x1 * y0
            a += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c
        if abs(a) > abs(area):
            area, best = a, (cx / (3 * a), cy / (3 * a))
    return best


def build(country):
    print(f"[{country}]")
    feats, names, o = PREP[country]()
    for f in feats:                               # todo a MultiPolygon: mapshaper separa capas por tipo
        g = f["geometry"] or {}
        polys = [p for gg in g.get("geometries", [g]) for p in
                 ([gg["coordinates"]] if gg.get("type") == "Polygon" else gg.get("coordinates", []) if gg.get("type") == "MultiPolygon" else [])]
        f["geometry"] = dict(type="MultiPolygon", coordinates=polys) if polys else None
    feats = [f for f in feats if f["geometry"]]
    tmp = Path(tempfile.mkdtemp())
    (tmp / "in.json").write_text(json.dumps(dict(type="FeatureCollection", features=feats)), encoding="utf-8")
    mapshaper(["-i", str(tmp / "in.json"), "-proj", o["proj"],
               "-simplify", f"{o['hi']}%", "keep-shapes", "-o", str(tmp / "hi.json"), "format=geojson",
               "-simplify", f"{o['lo']}%", "keep-shapes", "-o", str(tmp / "lo.json"), "format=geojson",
               "-dissolve", "r", "-o", str(tmp / "reg.json"), "format=geojson"])
    hi, lo, reg = (json.loads((tmp / f"{n}.json").read_text(encoding="utf-8"))["features"] for n in ("hi", "lo", "reg"))
    shutil.rmtree(tmp)
    fit = Fit(reg)
    dst = OUT / country
    dst.mkdir(parents=True, exist_ok=True)
    xy = lambda c: [round((c[0] - fit.x0) * fit.k, 1), round((fit.y1 - c[1]) * fit.k, 1)] if c else None
    regions = []
    for f in sorted(reg, key=lambda f: f["properties"]["r"]):
        r = f["properties"]["r"]
        c = centroid(f["geometry"])
        regions.append(dict(id=r, n=names.get(r, r), d=fit.path(f["geometry"], 1), bb=fit.bbox([f["geometry"]]),
                            c=xy(c)))
    units = [dict(id=f["properties"]["id"], r=f["properties"]["r"], n=f["properties"]["n"], d=fit.path(f["geometry"], 1),
                  c=xy(centroid(f["geometry"]))) for f in lo if f["geometry"]]
    doc = dict(w=round(fit.w), h=round(fit.h), unit=o["unit"], regions=regions, units=units)
    (OUT / f"{country}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    by = {}
    for f in hi:
        if f["geometry"]:
            by.setdefault(f["properties"]["r"], []).append(f)
    for r, fs in by.items():
        det = dict(units=[dict(id=f["properties"]["id"], n=f["properties"]["n"], d=fit.path(f["geometry"], 2),
                              c=xy(centroid(f["geometry"]))) for f in fs])
        (dst / f"{r}.json").write_text(json.dumps(det, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kb = (OUT / f"{country}.json").stat().st_size / 1024
    print(f"  {len(regions)} regiones, {len(units)} unidades; mapa nacional {kb:.0f} KB")


if __name__ == "__main__":
    for c in sys.argv[1:] or list(PREP):
        build(c)
