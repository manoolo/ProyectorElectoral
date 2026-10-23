"""Genera una versión de la página en un solo archivo, con datos y mapas incrustados (para abrir sin servidor).
Los mapas de detalle por región no se incrustan: al entrar a una región se usa el trazo del mapa nacional."""
import json, sys
from pathlib import Path

SITE = Path("site")
rd = lambda p: (SITE / p).read_text(encoding="utf-8")
reg = json.loads(rd("elecciones.json"))
data = {e["id"]: json.loads(rd(e["data"])) for e in reg["elections"] if (SITE / e["data"]).exists()}
geo = {m: json.loads(rd(f"geo/{m}.json")) for m in {e["map"] for e in reg["elections"] if e["id"] in data} if (SITE / f"geo/{m}.json").exists()}
dump = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
s = rd("index.html")
s = s.replace('<link rel="stylesheet" href="app.css">', "<style>\n" + rd("app.css") + "</style>", 1)
s = s.replace('<script src="app.js"></script>',
              f"<script>window.__REG__={dump(reg)};window.__PAISES__={dump(json.loads(rd('paises.json')))};"
              f"window.__DATA__={dump(data)};window.__GEO__={dump(geo)};</script>\n<script>\n" + rd("app.js") + "</script>", 1)
out = Path(sys.argv[1] if len(sys.argv) > 1 else "site/demo.html")
out.write_text(s, encoding="utf-8")
print(out, len(s) // 1024, "KB", list(data))
