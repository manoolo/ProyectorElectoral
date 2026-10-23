"""Brasil en vivo: baja el resultado por municipio del servidor de divulgación del TSE y lo
escribe en formato canónico (unit = código IBGE, frac, un candidato por columna).

  python -m adapters.br_live data/br_actual.csv && python run_live.py br data/br_actual.csv

Estructura de archivos según las instrucciones de descarga del TSE 2026 (la misma que usa el
proyecto juliosaulo/como-meus-vizinhos-votam):
  oficial/comum/config/ele-c.json                                       eleições disponíveis
  oficial/<ciclo>/arquivo-urna/<pleito>/config/<uf>/<uf>-p<pleito>-cs.json   municípios y seções (EA16)
  oficial/<ciclo>/<eleição>/dados/<uf>/<uf><mun>-c0001-e<eleição>-u.json     resultado agregado (EA20)
Reglas del TSE: máximo 100 pedidos por segundo por IP, y pedir direcciones inexistentes (404)
puede bloquear la IP por 10 minutos. Por eso no se inventa ninguna URL: todo sale de los
archivos de configuración, y el cliente se limita a 50 pedidos por segundo.
NO PROBADO contra el servidor real (inaccesible desde donde se escribió): probalo primero con
`--uf RR` antes de la noche electoral.
"""
from __future__ import annotations
import argparse, json, threading, time, urllib.request, urllib.error
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE, AMB = "https://resultados.tse.jus.br", "oficial"
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb", "pe",
       "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to"]


class Cliente:
    def __init__(self, por_segundo=50):
        self.ps, self.marcas, self.lock = por_segundo, deque(), threading.Lock()

    def _esperar(self):
        while True:
            with self.lock:
                now = time.monotonic()
                while self.marcas and now - self.marcas[0] >= 1:
                    self.marcas.popleft()
                if len(self.marcas) < self.ps:
                    self.marcas.append(now); return
                wait = 1 - (now - self.marcas[0])
            time.sleep(max(wait, 0.005))

    def json(self, path, opcional=False):
        espera = 1.0
        for intento in range(5):
            self._esperar()
            try:
                req = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": "proyector-electoral/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 404 and opcional:
                    return None
                if e.code in (403, 429, 500, 502, 503) and intento < 4:
                    time.sleep(espera); espera *= 2; continue
                raise
            except (urllib.error.URLError, TimeoutError):
                if intento == 4: raise
                time.sleep(espera); espera *= 2


def descubrir(cli, ano=2026, turno=1):
    cfg = cli.json(f"{AMB}/comum/config/ele-c.json")
    cand = [(p["c"], str(p["cd"]), str(e["cd"]), e["nm"]) for p in cfg["pl"] for e in p.get("e", [])
            if p["c"] == f"ele{ano}" and str(e["t"]) == str(turno)
            and "federal" in e["nm"].lower() and "ordin" in e["nm"].lower()]
    if len(cand) != 1:
        raise LookupError(f"no pude identificar la elección federal {ano}/{turno}: {cand}")
    ciclo, pleito, eleicao, nome = cand[0]
    print(f"{nome}: eleição {eleicao}, pleito {pleito}, ciclo {ciclo}")
    return ciclo, pleito, eleicao


def municipios(cli, ciclo, pleito, ufs):
    """Lista (uf, código TSE) de cada municipio, desde la configuración de secciones. Se guarda en caché."""
    cache = ROOT / "data" / f"br_municipios_{ciclo}.json"
    if cache.exists():
        mus = json.loads(cache.read_text())
    else:
        mus = []
        for uf in UFS:
            c = cli.json(f"{AMB}/{ciclo}/arquivo-urna/{pleito}/config/{uf}/{uf}-p{int(pleito):06d}-cs.json")
            for ab in c.get("abr", []):
                for mu in ab.get("mu", []):
                    mus.append([uf, str(mu["cd"])])
            print(f"  {uf.upper()}: {len(mus)} municipios acumulados")
        cache.write_text(json.dumps(mus))
    return [m for m in mus if m[0] in ufs]


def resultado(cli, ciclo, eleicao, uf, mu):
    e = int(eleicao)
    d = cli.json(f"{AMB}/{ciclo}/{eleicao}/dados/{uf}/{uf}{mu}-c0001-e{e:06d}-u.json", opcional=True)
    if d is None:
        return None
    votos = {}
    for cargo in d.get("carg", []):
        for agr in cargo.get("agr", []):
            for par in agr.get("par", []):
                for c in par.get("cand", []):
                    votos[str(c.get("nmu", "")).upper()] = float(c.get("vap") or 0)
    pst = float(str(d.get("s", {}).get("pst", "0")).replace(",", "."))
    return uf, mu, pst / 100, votos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("salida"); ap.add_argument("--uf", nargs="+"); ap.add_argument("--turno", type=int, default=1)
    ap.add_argument("--config", default="br", help="config/<nombre>.json (br = la elección configurada; br_1t = la 1ª vuelta)")
    a = ap.parse_args()
    cfg = json.loads((ROOT / "config" / f"{a.config}.json").read_text(encoding="utf-8"))
    cli = Cliente()
    ciclo, pleito, eleicao = descubrir(cli, 2026, a.turno)
    mus = municipios(cli, ciclo, pleito, [u.lower() for u in (a.uf or UFS)])
    with ThreadPoolExecutor(16) as ex:
        res = [r for r in ex.map(lambda m: resultado(cli, ciclo, eleicao, *m), mus) if r]
    xw = pd.read_csv(ROOT / "data" / "br_tse_ibge.csv", dtype=str)
    tse2ibge = dict(zip(xw.codigo_tse.str.lstrip("0"), xw.codigo_ibge))
    cands = list(cfg["candidates"])
    rows = []
    for uf, mu, frac, votos in res:
        row = dict(unit=tse2ibge.get(mu.lstrip("0"), "tse" + mu.lstrip("0")), frac=frac, **{c: 0.0 for c in cands})
        for nome, v in votos.items():
            dest = next((c for k, c in cfg["live_names"].items() if k in nome), "Otros")
            if dest in row:                      # en el balotaje no hay "Otros"
                row[dest] += v
        rows.append(row)
    pd.DataFrame(rows).to_csv(a.salida, index=False)
    tot = sum(sum(r[c] for c in cands) for r in rows)
    print(f"{len(rows)} municipios, {tot:,.0f} votos válidos → {a.salida}")


if __name__ == "__main__":
    main()
