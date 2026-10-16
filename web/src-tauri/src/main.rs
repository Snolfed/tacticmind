// TacticMind application window (Tauri 2).
//
// The game, puzzles, coach and engine run in Python (and C); this window only:
//  1. shows a loading screen,
//  2. starts `python main.py --server --port 0` in the background and reads the `TACTICMIND_URL=…` line from it,
//  3. navigates to that address (Python itself serves the TypeScript interface),
//  4. when the window closes, closes Python's standard input — the signal for it to exit.
//
// If Python fails to start or stops running, the loading screen shows an error with the tail of its output.

// In release builds on Windows, no extra console window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::VecDeque;
use std::env;
use std::ffi::OsString;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, Url, WebviewWindow};

/// How long we wait for the server address (the first Python start can be slow: compiling .pyc, loading puzzles).
const START_TIMEOUT: Duration = Duration::from_secs(120);
/// How many lines from the end of Python's output we show on error.
const LOG_LINES: usize = 30;
const URL_PREFIX: &str = "TACTICMIND_URL=";

/// The Python process running in the background.
struct Backend(Mutex<Option<Child>>);

type Log = Arc<Mutex<VecDeque<String>>>;

/// Directory containing `main.py`: `TACTICMIND_ROOT`, the repository directory at compile time, or an ancestor of the executable.
fn project_root() -> Option<PathBuf> {
    let is_root = |dir: &Path| dir.join("main.py").is_file() && dir.join("tacticmind").is_dir();
    if let Some(dir) = env::var_os("TACTICMIND_ROOT").map(PathBuf::from) {
        return is_root(&dir).then_some(dir);
    }
    let compiled = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
    if is_root(&compiled) {
        return compiled.canonicalize().ok().or(Some(compiled));
    }
    let exe = env::current_exe().ok()?;
    exe.ancestors()
        .find(|dir| is_root(dir))
        .map(Path::to_path_buf)
}

/// Python interpreter candidates, best first: `TACTICMIND_PYTHON`, the project venv, then the system one.
fn python_candidates(root: &Path) -> Vec<(OsString, Vec<&'static str>)> {
    let mut list: Vec<(OsString, Vec<&'static str>)> = Vec::new();
    if let Some(custom) = env::var_os("TACTICMIND_PYTHON") {
        list.push((custom, vec![]));
    }
    for venv in [".venv", "venv"] {
        let exe = if cfg!(windows) {
            root.join(venv).join("Scripts").join("python.exe")
        } else {
            root.join(venv).join("bin").join("python")
        };
        if exe.is_file() {
            list.push((exe.into_os_string(), vec![]));
        }
    }
    if cfg!(windows) {
        list.push(("python".into(), vec![]));
        list.push(("py".into(), vec!["-3"]));
        list.push(("python3".into(), vec![]));
    } else {
        list.push(("python3".into(), vec![]));
        list.push(("python".into(), vec![]));
    }
    list
}

fn remember(log: &Log, line: String) {
    let mut log = log.lock().unwrap();
    if log.len() == LOG_LINES {
        log.pop_front();
    }
    log.push_back(line);
}

/// A thread copying a Python stream to ours (console in development mode) and into the `log` buffer.
fn pump(
    stream: impl Read + Send + 'static,
    log: Log,
    url: Option<mpsc::Sender<String>>,
    to_stderr: bool,
) {
    thread::spawn(move || {
        let mut url = url;
        for line in BufReader::new(stream).lines() {
            let Ok(line) = line else { break };
            if let Some(found) = line.strip_prefix(URL_PREFIX) {
                if let Some(tx) = url.take() {
                    let _ = tx.send(found.trim().to_string());
                    continue;
                }
            }
            if to_stderr {
                eprintln!("{line}");
            } else {
                println!("{line}");
            }
            remember(&log, line);
        }
        // End of stream = Python has exited; closing the channel wakes whoever waits for the address.
    });
}

fn spawn_python(root: &Path, exe: &OsString, prefix: &[&str]) -> std::io::Result<Child> {
    let mut command = Command::new(exe);
    command
        .args(prefix)
        .args(["main.py", "--server", "--port", "0"])
        .current_dir(root)
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW: the console of Python (and of the engine processes that inherit it) stays hidden.
        command.creation_flags(0x0800_0000);
    }
    command.spawn()
}

/// Starts the game server; returns the process, its address and output buffer, or an error description.
fn start_backend() -> Result<(Child, String, Log), String> {
    let root = project_root().ok_or_else(|| {
        "Could not find the game directory (the main.py file). Run the app from the TacticMind repository \
         or set the TACTICMIND_ROOT variable."
            .to_string()
    })?;
    let mut tried = Vec::new();
    let mut last_log = String::new();
    for (exe, prefix) in python_candidates(&root) {
        let name = Path::new(&exe).display().to_string();
        let Ok(mut child) = spawn_python(&root, &exe, &prefix) else {
            tried.push(format!("{name} (not found)"));
            continue;
        };
        let log: Log = Arc::new(Mutex::new(VecDeque::new()));
        let (tx, rx) = mpsc::channel();
        if let Some(stdout) = child.stdout.take() {
            pump(stdout, log.clone(), Some(tx), false);
        }
        if let Some(stderr) = child.stderr.take() {
            pump(stderr, log.clone(), None, true);
        }
        let started = Instant::now();
        loop {
            match rx.recv_timeout(Duration::from_millis(250)) {
                Ok(url) => return Ok((child, url, log)),
                Err(RecvTimeoutError::Timeout) if started.elapsed() < START_TIMEOUT => {
                    if let Ok(Some(_)) = child.try_wait() {
                        // The process has ended; wait a moment to read the rest of its output.
                        thread::sleep(Duration::from_millis(300));
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let _ = child.kill();
        let status = child.wait().map(|s| s.to_string()).unwrap_or_default();
        tried.push(format!("{name} ({status})"));
        last_log = log
            .lock()
            .unwrap()
            .iter()
            .cloned()
            .collect::<Vec<_>>()
            .join("\n");
    }
    let mut message = format!("Tried to start Python: {}", tried.join(", "));
    if !last_log.is_empty() {
        message.push_str("\n\n");
        message.push_str(&last_log);
    }
    Err(message)
}

/// Percent-encodes everything except ASCII letters and digits (for `decodeURIComponent` on the page side).
fn encode(text: &str) -> String {
    text.bytes()
        .map(|b| {
            if b.is_ascii_alphanumeric() {
                (b as char).to_string()
            } else {
                format!("%{b:02X}")
            }
        })
        .collect()
}

/// Returns to the loading screen and shows the error on it (passed in the URL fragment).
fn show_error(window: &WebviewWindow, home: &Url, message: &str) {
    eprintln!("TacticMind: {message}");
    let mut url = home.clone();
    url.set_fragment(Some(&format!("error={}", encode(message))));
    let _ = window.navigate(url);
}

fn launch(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let home = window
        .url()
        .unwrap_or_else(|_| "tauri://localhost/".parse().unwrap());
    match start_backend() {
        Ok((child, address, log)) => {
            let Ok(url) = Url::parse(&address) else {
                show_error(
                    &window,
                    &home,
                    &format!("Python reported an invalid address: {address}"),
                );
                return;
            };
            app.state::<Backend>().0.lock().unwrap().replace(child);
            let _ = window.navigate(url);
            watch(app.clone(), window, home, log);
        }
        Err(message) => show_error(&window, &home, &message),
    }
}

/// If Python stops running during the game (and the window is not closing), show an error instead of a dead page.
fn watch(app: AppHandle, window: WebviewWindow, home: Url, log: Log) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(500));
        let state = app.state::<Backend>();
        let mut guard = state.0.lock().unwrap();
        let Some(child) = guard.as_mut() else { return };
        if let Ok(Some(status)) = child.try_wait() {
            guard.take();
            drop(guard);
            thread::sleep(Duration::from_millis(300));
            let tail = log
                .lock()
                .unwrap()
                .iter()
                .cloned()
                .collect::<Vec<_>>()
                .join("\n");
            show_error(
                &window,
                &home,
                &format!("Python exited ({status}).\n\n{tail}"),
            );
            return;
        }
    });
}

/// Closing standard input ends Python (`--server` mode); after a moment — just in case — kill.
fn stop_backend(app: &AppHandle) {
    let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() else {
        return;
    };
    drop(child.stdin.take());
    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn main() {
    tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            thread::spawn(move || launch(&handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to create the TacticMind window")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_backend(app);
            }
        });
}
