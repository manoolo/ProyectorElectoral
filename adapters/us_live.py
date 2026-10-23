"""EEUU en vivo: baja el escrutinio por condado y lo pasa al formato canónico.

Fuente: el JSON público de resultados del New York Times (el que alimenta su página de resultados;
lo usaron en 2022 y 2024 con esta forma). La URL de 2026 se confirma cuando publiquen la página:
se pasa con --url o se deja en config/us_senado.json como "live_url".

  python -m adapters.us_live data/us_senado_actual.csv --config us_senado
  python -m adapters.us_live data/us_senado_actual.csv --config us_senado --archivo resultados.json   # desde un archivo

Respaldo, si el NYT cambia la forma o no responde: cualquier CSV con columnas
state, fips, party (DEM/REP/otro), votes y, opcional, frac (0-1), con --csv. Se agrega igual.

Salida: unit (fips del condado, como en la base), frac, Republicanos, Demócratas, Otros.
Sólo entran las carreras de la config (por estado). Alaska llega por distrito legislativo: se usa el
código del NYT si es el mismo de la base; si no, cae como unidad sin base y suma sólo lo observado.
"""
import argparse, json, sys, time, urllib.request
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PARTY = {"DEM": "Demócratas", "D": "Demócratas", "REP": "Republicanos", "GOP": "Republicanos", "R": "Republicanos"}


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


def parse_nyt(doc, office, races, indep=None):
    """Filas (state, fips, group, votes, frac) de las carreras pedidas. office: 'senate', 'governor'.
    indep: {estado: True} si el lugar del demócrata lo ocupa un independiente (Nebraska)."""
    indep = indep or {}
    rows = []
    for race in doc.get("races", []):
        off = str(_g(race, "office", "race_type", "type", default="")).lower()
        if office not in off.replace(" ", ""):
            continue
        st = _g(race, "state.postal_code", "state_postal", "state.abbreviation", "state_id")
        st = str(st).upper() if st else None
        special = bool(_g(race, "special", "is_special", default=False)) or "special" in str(_g(race, "race_name", "title", default="")).lower()
        key = st + "-E" if special and (st + "-E") in races else st
        if key not in races:
            continue
        meta = _g(race, "candidate_metadata", default={}) or {}
        def group(c):
            m = meta.get(c.get("nyt_id") or c.get("candidate_id"), {}) if isinstance(meta, dict) else {}
            p = str(_g(c, "party.abbreviation", "party", default="") or _g(m, "party.abbreviation", "party", default="")).upper()
            g = PARTY.get(p[:3], PARTY.get(p, "Otros"))
            if g == "Otros" and indep.get(key):               # Osborn: el no republicano principal
                g = "Demócratas" if c is top_other else "Otros"
            return g
        for ru in _g(race, "reporting_units", default=[]):
            lvl = str(_g(ru, "level", default="")).lower()
            if lvl not in ("county", "township", "district", "state-house", "subunit") and not _g(ru, "fips_county"):
                continue
            fips = str(_g(ru, "fips_state", default="")) + str(_g(ru, "fips_county", default=""))
            fips = fips if len(fips) == 5 else str(_g(ru, "fips", "geo_id", "reporting_unit_id", default=fips)).zfill(5)
            cands = _g(ru, "candidates", default=[])
            others = [c for c in cands if PARTY.get(str(_g(c, "party.abbreviation", "party", default="")).upper()[:3]) is None]
            top_other = max(others, key=lambda c: _g(c, "votes.total", "votes", default=0) or 0) if others else None
            exp = _g(ru, "total_expected_vote", "expected_votes", default=None)
            tot = _g(ru, "total_votes", default=None) or sum((_g(c, "votes.total", "votes", default=0) or 0) for c in cands)
            frac = _g(ru, "eevp", "expected_vote_pct", default=None)
            if frac is not None:
                frac = float(frac) / (100.0 if float(frac) > 1.0 else 1.0)
            elif exp:
                frac = min(tot / exp, 1.0)
            else:
                pr, pt = _g(ru, "precincts_reporting", default=None), _g(ru, "precincts_total", "total_precincts", default=None)
                frac = pr / pt if pr is not None and pt else (1.0 if tot else 0.0)
            for c in cands:
                v = _g(c, "votes.total", "votes", default=0) or 0
                rows.append((key, fips, group(c), float(v), frac))
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
        df = parse_nyt(doc, office, races, indep)
    out = canonical(df, special_suffix=True)
    base_units = set(pd.read_csv(ROOT / cfg["base"], dtype={"unit": str}).unit)
    sin_base = (~out.unit.isin(base_units)).sum()
    out.to_csv(a.salida, index=False)
    tot = out[["Republicanos", "Demócratas", "Otros"]].sum()
    print(f"{len(out)} unidades con votos en {df.region.nunique() if len(df) else 0} carreras "
          f"({sin_base} sin base); R {tot.Republicanos:,.0f} · D {tot.Demócratas:,.0f}")


if __name__ == "__main__":
    main()
