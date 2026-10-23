"""Noche electoral: baja el escrutinio, proyecta y publica la página, en un bucle.

  python en_vivo.py br                 # Brasil, cada 2 minutos
  python en_vivo.py ar parcial.csv     # Argentina: el CSV del escrutinio provisorio que vas bajando
  python en_vivo.py br --cada 180      # otro intervalo, en segundos
  python en_vivo.py br --sin-subir     # sólo actualiza site/data, sin git (para probar)

Cada vuelta actualiza site/data/<país>.json y lo sube a GitHub. GitHub Pages publica el
cambio en uno o dos minutos y la página abierta se refresca sola cada 2 minutos.
Para cortar: Ctrl+C.
"""
import argparse, datetime as dt, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def sh(*cmd):
    print("  $", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(list(map(str, cmd)), cwd=ROOT).returncode == 0


def vuelta(pais, parcial, subir):
    actual = ROOT / "data" / f"{pais}_actual.csv"
    if pais == "br":
        ok = sh(PY, "-m", "adapters.br_live", actual)
    elif pais == "ar":
        ok = sh(PY, "-m", "adapters.ar_live", parcial, actual)
    else:
        raise SystemExit(f"país sin feed en vivo: {pais}")
    if not ok or not sh(PY, "run_live.py", pais, actual):
        print("  falló esta vuelta; reintento en la próxima", flush=True)
        return
    if subir:
        sh("git", "add", f"site/data/{pais}.json")
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
            sh("git", "commit", "-q", "-m", f"{pais}: escrutinio {dt.datetime.now():%H:%M}")
            for espera in (2, 4, 8, 16):           # la red puede fallar esa noche
                if sh("git", "push", "-q"):
                    break
                time.sleep(espera)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pais", choices=["br", "ar"])
    ap.add_argument("parcial", nargs="?", help="Argentina: CSV del escrutinio provisorio")
    ap.add_argument("--cada", type=int, default=120, help="segundos entre vueltas")
    ap.add_argument("--sin-subir", action="store_true")
    a = ap.parse_args()
    if a.pais == "ar" and not a.parcial:
        ap.error("para Argentina pasá el CSV del escrutinio provisorio")
    while True:
        t0 = time.time()
        print(f"[{dt.datetime.now():%H:%M:%S}] vuelta {a.pais}", flush=True)
        vuelta(a.pais, a.parcial, not a.sin_subir)
        time.sleep(max(5, a.cada - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nlisto")
