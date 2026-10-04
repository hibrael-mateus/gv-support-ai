"""Writes generated PowerShell scripts to a folder so CI can parse them with the real PowerShell parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agents.powershell import MODULES, build_diagnostic  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "ps-samples")
out.mkdir(parents=True, exist_ok=True)
samples = {"all": list(MODULES), **{m: [m] for m in MODULES}}
for name, mods in samples.items():
    s = build_diagnostic(mods, target="PV990", sql_instance="PV990\\SQL2019", urls=["https://portal.exemplo.edu.br"],
                         log_path="C:\\inetpub\\logs\\LogFiles", hours=24, title=f"Amostra {name}")
    (out / f"{name}.ps1").write_text(s.code, encoding="utf-8-sig")
print(f"{len(samples)} scripts em {out}")
