"""Genera una versión de la página con los datos incrustados (para publicar sin servidor)."""
import json, sys
from pathlib import Path
s = Path("site/index.html").read_text()
data = {c: json.loads(Path(f"site/data/{c}.json").read_text()) for c in ("us", "ar", "br") if Path(f"site/data/{c}.json").exists()}
s = s.replace("<script>\n// Configuración base", "<script>window.__DATA__=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";</script>\n<script>\n// Configuración base", 1)
out = sys.argv[1] if len(sys.argv) > 1 else "site/demo.html"
Path(out).write_text(s)
print(out, len(s) // 1024, "KB", list(data))
