# PyInstaller spec: onedir build (faster startup than onefile), no console window.
# Build: pyinstaller gv-support-backend.spec --noconfirm   ->  dist/gv-support-backend/
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("keyring.backends")
    + collect_submodules("googleapiclient")
    + ["win32ctypes.core", "win32timezone"]
)

a = Analysis(
    ["run_backend.py"],
    pathex=["."],
    hiddenimports=hidden,
    datas=collect_data_files("googleapiclient"),  # static Drive discovery documents
    excludes=["tkinter", "pytest", "PyInstaller"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="gv-support-backend", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="gv-support-backend", upx=False)
