"""EEUU en vivo: baja el escrutinio por condado y lo pasa al formato canónico.

Fuente: el JSON público de resultados del New York Times (el que alimenta su página de resultados;
forma verificada con el de 2024). Hay un archivo nacional por cargo con el total de cada estado
(.../pages/data/2024-11-05/results-senate.json) y uno por estado con los condados
(.../results-arizona-us-senate.json); la URL de cada estado sale del nacional. La de 2026 se confirma
cuando publiquen la página (el 23/10 todavía daba 404): --url o "live_url" en la config.

  python -m adapters.us_live data/us_senado_actual.csv --config us_senado
  python -m adapters.us_live data/us_senado_actual.csv --config us_senado --archivo resultados.json   # desde un archivo

Respaldo, si el NYT cambia la forma o no responde: cualquier CSV con columnas
state, fips, party (DEM/REP/otro), votes y, opcional, frac (0-1), con --csv. Se agrega igual.

Salida: unit (fips del condado, como en la base), frac, Republicanos, Demócratas, Otros.
Sólo entran las carreras de la config (por estado). Alaska llega por distrito legislativo: se usa el
código del NYT si es el mismo de la base; si no, cae como unidad sin base y suma sólo lo observado.
"""
import argparse, json, re, sys, time, urllib.request
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PARTY = {"DEM": "Demócratas", "D": "Demócratas", "REP": "Republicanos", "GOP": "Republicanos", "R": "Republicanos"}
OFFICE = {"senado": "senate", "gobernador": "governor"}


def get_json(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (proyector electoral)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if k == tries - 1:
                raise
            time.sleep(2 ** (k + 1))


def _g(d, *ks, default=None):
    """Primer campo presente, con nombres alternativos y anidados ('a.b')."""
    for k in ks:
        x = d
        for p in k.split("."):
            x = x.get(p) if isinstance(x, dict) else None
        if x not in (None, ""):
            return x
    return default


def race_key(race, races):
    """Clave de la carrera en la config: el estado (del nyt_id, 'PA-G-S-2024-11-05'), con -E si es especial
    y el estado tiene también la regular."""
    st = str(_g(race, "top_reporting_unit.state_postal", default="") or str(race.get("nyt_id", ""))[:2]).upper()
    special = "special" in (str(race.get("type", "")) + str(race.get("nyt_id", ""))).lower()
    return st + "-E" if special and (st + "-E") in races else st


def state_urls(doc, office, races):
    """URL del JSON por estado (el que trae los condados), sacada de la página de cada carrera:
    nytimes.com/interactive/2024/11/05/us/elections/results-arizona-us-senate.html →
    static01.nyt.com/elections-assets/pages/data/2024-11-05/results-arizona-us-senate.json"""
    out = {}
    for race in doc.get("races", []):
        if office not in str(race.get("office", "")).lower().replace(" ", "").replace(".", ""):
            continue
        k = race_key(race, races)
        u = race.get("url") or ""
        m = re.search(r"/interactive/(\d{4})/(\d{2})/(\d{2})/us/elections/(results-[^/]+)\.html", u)
        if k in races and m:
            y, mo, d, name = m.groups()
            out[k] = f"https://static01.nyt.com/elections-assets/pages/data/{y}-{mo}-{d}/{name}.json"
    return out


def parse_nyt(doc, office, races, indep=None):
    """Filas (region, unit, group, votes, frac) de las carreras pedidas, desde un JSON del NYT
    (nacional o de un estado). office: 'senate', 'governor', 'president'. El partido sale de
    candidate_metadata (party.nyt_id: DEM, GOP, ...). indep: {estado: True} si el lugar del
    demócrata lo ocupa un independiente (Nebraska): el no republicano más votado va como Demócratas."""
    indep = indep or {}
    rows = []
    for race in doc.get("races", []):
        if office not in str(race.get("office", "")).lower().replace(" ", "").replace(".", ""):
            continue
        key = race_key(race, races)
        if key not in races:
            continue
        meta = race.get("candidate_metadata") or {}
        def party(c):
            m = meta.get(c.get("nyt_id"), {})
            p = str(_g(m, "party.nyt_id", "party.abbreviation", default="") or "").upper().strip(".")
            return PARTY.get(p, PARTY.get(p[:3], "Otros"))
        units = [u for u in race.get("reporting_units", []) if str(u.get("level")) != "state"]
        for ru in units:
            fips = str(_g(ru, "fips_state", default="")) + str(_g(ru, "fips_county", default=""))
            if len(fips) != 5:
                fips = str(_g(ru, "nyt_id", default=fips))
            cands = ru.get("candidates", [])
            votes = [float(_g(c, "votes.total", default=None) or (c.get("votes") if isinstance(c.get("votes"), (int, float)) else 0) or 0) for c in cands]
            groups = [party(c) for c in cands]
            if indep.get(key):
                oth = [i for i, g in enumerate(groups) if g == "Otros"]
                if oth and "Demócratas" not in groups:
                    groups[max(oth, key=lambda i: votes[i])] = "Demócratas"
            tot = _g(ru, "total_votes", default=None) or sum(votes)
            frac = _g(ru, "eevp", default=None)
            if frac is not None:
                frac = min(float(frac) / 100.0, 1.0)
            elif _g(ru, "total_expected_vote"):
                frac = min(tot / ru["total_expected_vote"], 1.0)
            else:
                pr, pt = ru.get("precincts_reporting"), ru.get("precincts_total")
                frac = pr / pt if pr is not None and pt else (1.0 if tot else 0.0)
            for g, v in zip(groups, votes):
                rows.append((key, fips, g, v, frac))
    return pd.DataFrame(rows, columns=["region", "unit", "group", "votes", "frac"])


def canonical(df, special_suffix):
    if df.empty:
        return pd.DataFrame(columns=["unit", "frac", "Republicanos", "Demócratas", "Otros"])
    df = df.copy()
    df["unit"] = df.unit + df.region.map(lambda r: "e" if r.endswith("-E") and special_suffix else "")
    out = df.pivot_table(index="unit", columns="group", values="votes", aggfunc="sum", fill_value=0)
    for c in ("Republicanos", "Demócratas", "Otros"):
        if c not in out:
            out[c] = 0.0
    out["frac"] = df.groupby("unit").frac.max()
    out = out.reset_index()
    out = out[(out[["Republicanos", "Demócratas", "Otros"]].sum(axis=1) > 0)]
    return out[["unit", "frac", "Republicanos", "Demócratas", "Otros"]]


def from_csv(path, races):
    d = pd.read_csv(path, dtype={"fips": str, "state": str})
    d["region"] = d.state.str.upper()
    d = d[d.region.isin(races)]
    d["group"] = d.party.str.upper().str[:3].map(PARTY).fillna("Otros")
    d["unit"] = d.fips.str.zfill(5)
    if "frac" not in d:
        d["frac"] = 1.0
    return d[["region", "unit", "group", "votes", "frac"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("salida")
    ap.add_argument("--config", default="us_senado")
    ap.add_argument("--url")
    ap.add_argument("--archivo", help="JSON del NYT ya bajado")
    ap.add_argument("--csv", help="respaldo: CSV state,fips,party,votes[,frac]")
    a = ap.parse_args()
    cfg = json.loads((ROOT / "config" / f"{a.config}.json").read_text(encoding="utf-8"))
    races = set(cfg["ratings"]) if "ratings" in cfg else set(pd.read_csv(ROOT / cfg["base"]).region)
    office = cfg.get("live_office", "senate")
    indep = {r: True for r in cfg.get("independientes", {"NE": "Osborn"} if office == "senate" else {})}
    if a.csv:
        df = from_csv(a.csv, races)
    else:
        url = a.url or cfg.get("live_url")
        if not (url or a.archivo):
            sys.exit("falta la URL del feed: --url o \"live_url\" en la config")
        doc = json.loads(Path(a.archivo).read_text(encoding="utf-8")) if a.archivo else get_json(url)
        # el archivo nacional sólo trae el total de cada estado: los condados están en el de cada estado
        per_state = state_urls(doc, office, races) if not a.archivo else {}
        parts = []
        for k, u in sorted(per_state.items()):
            try:
                parts.append(parse_nyt(get_json(u, tries=2), office, races, indep))
            except Exception as e:
                print(f"  {k}: no se pudo bajar {u} ({e})")
        df = pd.concat(parts, ignore_index=True) if parts else parse_nyt(doc, office, races, indep)
    out = canonical(df, special_suffix=True)
    base_units = set(pd.read_csv(ROOT / cfg["base"], dtype={"unit": str}).unit)
    sin_base = (~out.unit.isin(base_units)).sum()
    out.to_csv(a.salida, index=False)
    tot = out[["Republicanos", "Demócratas", "Otros"]].sum()
    print(f"{len(out)} unidades con votos en {df.region.nunique() if len(df) else 0} carreras "
          f"({sin_base} sin base); R {tot.Republicanos:,.0f} · D {tot.Demócratas:,.0f}")


if __name__ == "__main__":
    main()
