"""Publish the website to a Hugging Face Space (run by .github/workflows/deploy-web.yml).

Creates the Space and a private dataset for the database on first run, copies the secrets from
GitHub into the Space's secrets (never into files), and uploads backend + UI + Dockerfile.
"""
import os
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
if not os.getenv("HF_TOKEN"):
    print("Segredo HF_TOKEN não configurado: site não publicado.")
    raise SystemExit(0)
api = HfApi(token=os.environ["HF_TOKEN"])
space = os.getenv("HF_SPACE") or f"{api.whoami()['name']}/gv-support-ai"
dataset = space + "-data"
# Groq when its key exists, otherwise the model runs inside the server (slower, nothing leaves it).
mode = os.getenv("AI_MODE") or ("groq" if os.getenv("GROQ_API_KEY") else "embedded")

if not os.getenv("GV_WEB_PASSWORD"):
    raise SystemExit("Defina o segredo GV_WEB_PASSWORD no GitHub: sem ele o site ficaria sem senha.")
if mode == "groq" and not os.getenv("GROQ_API_KEY"):
    raise SystemExit("AI_MODE=groq exige o segredo GROQ_API_KEY no GitHub (ou use AI_MODE=embedded).")

api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
api.create_repo(dataset, repo_type="dataset", private=True, exist_ok=True)

secrets = {"GV_WEB_PASSWORD": os.getenv("GV_WEB_PASSWORD"), "HF_TOKEN": os.environ["HF_TOKEN"],
           "GV_SECRET_GROQ_API_KEY": os.getenv("GROQ_API_KEY"),
           "GV_SECRET_GOOGLE_SERVICE_ACCOUNT": os.getenv("GOOGLE_SERVICE_ACCOUNT"),
           "GV_SECRET_GOOGLE_OAUTH_TOKEN": os.getenv("GOOGLE_OAUTH_TOKEN")}
for key, value in secrets.items():
    if value:
        api.add_space_secret(space, key, value)
variables = {"GV_HF_DATASET": dataset, "GV_CONFIG_LLM_PROVIDER": mode,
             "GV_CONFIG_EMBEDDED_MODEL": os.getenv("EMBEDDED_MODEL") or "qwen2.5-3b",
             "GV_CONFIG_LLM_MODEL": os.getenv("LLM_MODEL") or "", "GV_CONFIG_INTERNET_ENABLED": "true"}
for key, value in variables.items():
    api.add_space_variable(space, key, value)

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp)
    skip = shutil.ignore_patterns("node_modules", "dist", "src-tauri", "__pycache__", ".pytest_cache", "tests", "*.spec")
    shutil.copytree(ROOT / "backend", out / "backend", ignore=skip)
    shutil.copytree(ROOT / "desktop", out / "desktop", ignore=skip)
    shutil.copy(ROOT / "web" / "Dockerfile", out / "Dockerfile")
    (out / "README.md").write_text(
        "---\ntitle: GV Support AI\nemoji: 🛠️\ncolorFrom: green\ncolorTo: blue\nsdk: docker\napp_port: 7860\n"
        "pinned: false\n---\n\nAssistente de suporte GV Dasa. Acesso restrito à equipe (senha).\n", encoding="utf-8")
    api.upload_folder(repo_id=space, repo_type="space", folder_path=out, commit_message=os.getenv("GITHUB_SHA", "deploy"),
                      delete_patterns=["**"])
print(f"Site publicado: https://huggingface.co/spaces/{space}")
