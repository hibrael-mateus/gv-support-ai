"""Entry point used by the desktop shell (and by PyInstaller)."""
import os
import sys
import threading
from multiprocessing import freeze_support


def _exit_with_parent(pid: int) -> None:
    """If the desktop window dies without a clean shutdown, don't leave the backend running."""
    if sys.platform != "win32":
        return
    import ctypes

    SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return
    ctypes.windll.kernel32.WaitForSingleObject(handle, INFINITE)
    os._exit(0)


if __name__ == "__main__":
    freeze_support()
    # Windowed PyInstaller builds have no console streams; uvicorn's logger would crash on None.
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(os.devnull, "w")
    if os.getenv("GV_PARENT_PID", "").isdigit():
        threading.Thread(target=_exit_with_parent, args=(int(os.environ["GV_PARENT_PID"]),), daemon=True).start()

    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("GV_PORT", "8765")), log_level="warning", access_log=False)
