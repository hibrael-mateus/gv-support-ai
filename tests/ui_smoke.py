"""UI smoke test: seeds a temp data dir, starts the backend and the built frontend, drives the main screens.

Run from the repo root after `npm run build` in desktop/:
    python tests/ui_smoke.py [screenshot_dir]
Requires `pip install playwright` and a Chromium (PLAYWRIGHT_CHROMIUM or `playwright install chromium`).
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="gv-ui-"))
OUT.mkdir(parents=True, exist_ok=True)
os.environ["GV_SUPPORT_DATA_DIR"] = tempfile.mkdtemp(prefix="gv-ui-data-")
os.environ.pop("GV_API_TOKEN", None)
sys.path.insert(0, str(ROOT / "backend"))

from app import cases, db, rag  # noqa: E402
from app.settings import ALLOWED_GOOGLE_DRIVE_FOLDER_ID as ALLOWED, save_config  # noqa: E402

db.init_db()
graph = {"ki-1": ["sub"], "sub": [ALLOWED]}
rag.index_document(drive_file_id="ki-1", name="KI 1234 - GVcollege Rematrícula bloqueada.pdf",
                   pages=[(1, "Sintoma: a rematrícula exibe 'Rematrícula bloqueada'. Causa: parâmetro de bloqueio por pendência financeira ativo.")],
                   parents_lookup=lambda i: graph.get(i, []), path="/Fontes/GVcollege/KIs", modified_time="2026-09-01T10:00:00Z")
case = cases.create_case({"title": "Portal do Professor com timeout", "customer": "Faculdade Exemplo", "product": "GVcollege",
                          "server": "PV990", "error_message": "Timeout expired.", "already_validated": "DNS PV990 = OK"})
save_config({"setup_completed": True, "internet_enabled": False})  # deterministic: no live web lookups


def wait(url: str, seconds: int = 40) -> None:
    for _ in range(seconds * 4):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.25)
    raise SystemExit(f"timeout waiting for {url}")


# The backend serves the built UI itself (same origin, as on the website).
procs = [subprocess.Popen([sys.executable, "run_backend.py"], cwd=ROOT / "backend",
                          env={**os.environ, "GV_WEB_DIR": str(ROOT / "desktop" / "dist")})]
errors: list[str] = []
try:
    wait("http://127.0.0.1:8765/health")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("PLAYWRIGHT_CHROMIUM") or None)
        pg = browser.new_page(viewport={"width": 1366, "height": 768})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto("http://127.0.0.1:8765")
        pg.wait_for_selector("text=Visão geral", timeout=20000)
        pg.screenshot(path=OUT / "dashboard.png")

        pg.get_by_role("button", name="Chamados").first.click()
        pg.get_by_text("Portal do Professor com timeout").first.click()
        pg.wait_for_selector("text=Memória do chamado")
        assert pg.get_by_text("DNS PV990 = OK").count() > 0, "case memory not shown"
        pg.get_by_role("button", name="Iniciar investigação").click()
        pg.wait_for_selector("text=Analisando", state="detached", timeout=60000)
        try:
            pg.get_by_role("button", name="Gerar PowerShell").click(timeout=120000)  # enabled once the investigation ends
        except Exception:
            print("PAGE TEXT:\n" + pg.inner_text("body")[-3000:])  # CI artifacts are not always reachable
            log = Path(os.environ["GV_SUPPORT_DATA_DIR"]) / "Logs" / "backend.log"
            print("BACKEND LOG:\n" + (log.read_text(encoding="utf-8")[-4000:] if log.exists() else "(none)"))
            raise
        pg.wait_for_selector("text=Salvar .ps1", timeout=30000)
        pg.screenshot(path=OUT / "case.png")

        pg.keyboard.press("Control+k")
        pg.keyboard.type("rematrícula")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("text=KI 1234", timeout=15000)
        pg.get_by_text("KI 1234").first.click()
        pg.wait_for_selector("text=Trecho utilizado como evidência")
        pg.screenshot(path=OUT / "evidence.png")
        pg.keyboard.press("Escape")

        pg.keyboard.press("Control+,")
        pg.wait_for_selector("text=Banco vetorial")
        pg.get_by_role("button", name="IA", exact=True).click()
        pg.wait_for_selector("text=Baixar modelo")  # embedded AI is the default provider
        pg.screenshot(path=OUT / "settings-ai.png")
        pg.locator("header button").last.click()  # dark theme
        pg.wait_for_timeout(500)
        pg.set_viewport_size({"width": 910, "height": 512})  # 1366x768 at 150% scaling
        pg.keyboard.press("Control+n")
        pg.wait_for_selector("text=Iniciar investigação")
        pg.screenshot(path=OUT / "new-case-dark-150.png")
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "horizontal overflow at 150% scaling"
        browser.close()
finally:
    for proc in procs:
        proc.terminate()

assert not errors, f"page errors: {errors}"
print(f"UI smoke OK, screenshots in {OUT}")
