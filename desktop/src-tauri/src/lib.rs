//! Desktop shell: starts the bundled Python backend on a free localhost port with a per-launch token,
//! hands {url, token} to the UI and stops the backend when the app exits.
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use serde::Serialize;
use tauri::{Manager, RunEvent};

#[derive(Clone, Serialize)]
struct BackendInfo {
    url: String,
    token: String,
}

struct Backend {
    info: BackendInfo,
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn backend_info(state: tauri::State<Backend>) -> BackendInfo {
    state.info.clone()
}

/// Saves generated scripts. PowerShell 5.1 reads BOM-less UTF-8 as ANSI, so .ps1 files get a BOM.
#[tauri::command]
fn write_text_file(path: String, contents: String, bom: bool) -> Result<(), String> {
    let mut data = Vec::with_capacity(contents.len() + 3);
    if bom {
        data.extend_from_slice(&[0xEF, 0xBB, 0xBF]);
    }
    data.extend_from_slice(contents.as_bytes());
    std::fs::write(&path, data).map_err(|e| format!("Não foi possível salvar {path}: {e}"))
}

fn random_token() -> String {
    // ponytail: RandomState is seeded from the OS RNG; enough for a localhost per-launch token. Use `getrandom` if this ever leaves 127.0.0.1.
    let part = || {
        let mut h = RandomState::new().build_hasher();
        h.write_u128(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos());
        h.finish()
    };
    format!("{:016x}{:016x}", part(), part())
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0").and_then(|l| l.local_addr()).map(|a| a.port()).unwrap_or(8765)
}

fn backend_exe(app: &tauri::AppHandle) -> Option<PathBuf> {
    let name = if cfg!(windows) { "gv-support-backend.exe" } else { "gv-support-backend" };
    let path = app.path().resource_dir().ok()?.join("backend").join(name);
    path.exists().then_some(path)
}

fn start_backend(app: &tauri::AppHandle) -> Backend {
    let Some(exe) = backend_exe(app) else {
        // Development: run `python backend/run_backend.py` yourself (port 8765, no token).
        return Backend { info: BackendInfo { url: "http://127.0.0.1:8765".into(), token: String::new() }, child: Mutex::new(None) };
    };
    let port = free_port();
    let token = random_token();
    let mut cmd = Command::new(&exe);
    cmd.env("GV_PORT", port.to_string())
        .env("GV_API_TOKEN", &token)
        .env("GV_PARENT_PID", std::process::id().to_string());
    if let Some(dir) = exe.parent() {
        cmd.current_dir(dir);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let child = cmd.spawn().map_err(|e| eprintln!("backend failed to start: {e}")).ok();
    Backend { info: BackendInfo { url: format!("http://127.0.0.1:{port}"), token }, child: Mutex::new(child) }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let backend = start_backend(app.handle());
            app.manage(backend);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_info, write_text_file])
        .build(tauri::generate_context!())
        .expect("error while building GV Support AI");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Backend>().child.lock().ok().and_then(|mut c| c.take()) {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
