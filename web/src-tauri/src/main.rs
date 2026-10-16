// Okno aplikacji TacticMind (Tauri 2).
//
// Gra, zadania, trener i silnik działają w Pythonie (i C); to okno tylko:
//  1. pokazuje ekran ładowania,
//  2. uruchamia w tle `python main.py --server --port 0` i czyta z niego linię `TACTICMIND_URL=…`,
//  3. przechodzi pod ten adres (interfejs w TypeScript serwuje sam Python),
//  4. przy zamknięciu okna zamyka standardowe wejście Pythona — to dla niego sygnał do wyjścia.
//
// Jeśli Python się nie uruchomi albo przestanie działać, ekran ładowania pokazuje błąd z końcówką jego wyjścia.

// W wersji release na Windows bez dodatkowego okna konsoli.
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

/// Tyle czekamy na adres serwera (pierwsze uruchomienie Pythona bywa wolne: kompilacja .pyc, wczytanie zadań).
const START_TIMEOUT: Duration = Duration::from_secs(120);
/// Tyle linii z końca wyjścia Pythona pokazujemy przy błędzie.
const LOG_LINES: usize = 30;
const URL_PREFIX: &str = "TACTICMIND_URL=";

/// Proces Pythona działający w tle.
struct Backend(Mutex<Option<Child>>);

type Log = Arc<Mutex<VecDeque<String>>>;

/// Katalog z `main.py`: `TACTICMIND_ROOT`, katalog repozytorium z czasu kompilacji albo przodek pliku wykonywalnego.
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

/// Kandydaci na interpreter Pythona, od najlepszego: `TACTICMIND_PYTHON`, venv w projekcie, potem systemowy.
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

/// Wątek przepisujący strumień Pythona na nasz (konsola w trybie deweloperskim) i do bufora `log`.
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
        // Koniec strumienia = Python zakończył pracę; zamknięcie kanału budzi czekającego na adres.
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
        // CREATE_NO_WINDOW: konsola Pythona (i procesów silnika, które ją dziedziczą) pozostaje niewidoczna.
        command.creation_flags(0x0800_0000);
    }
    command.spawn()
}

/// Uruchamia serwer gry; zwraca proces, jego adres i bufor wyjścia albo opis błędu.
fn start_backend() -> Result<(Child, String, Log), String> {
    let root = project_root().ok_or_else(|| {
        "Nie znalazłem katalogu gry (pliku main.py). Uruchom aplikację z repozytorium TacticMind \
         albo ustaw zmienną TACTICMIND_ROOT."
            .to_string()
    })?;
    let mut tried = Vec::new();
    let mut last_log = String::new();
    for (exe, prefix) in python_candidates(&root) {
        let name = Path::new(&exe).display().to_string();
        let Ok(mut child) = spawn_python(&root, &exe, &prefix) else {
            tried.push(format!("{name} (nie znaleziono)"));
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
                        // Proces się skończył; jeszcze chwila na doczytanie jego wyjścia.
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
    let mut message = format!("Próbowałem uruchomić Pythona: {}", tried.join(", "));
    if !last_log.is_empty() {
        message.push_str("\n\n");
        message.push_str(&last_log);
    }
    Err(message)
}

/// Kodowanie procentowe wszystkiego poza literami i cyframi ASCII (dla `decodeURIComponent` po stronie strony).
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

/// Wraca na ekran ładowania i pokazuje na nim błąd (przekazany we fragmencie adresu).
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
                    &format!("Python podał niepoprawny adres: {address}"),
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

/// Jeśli Python przestanie działać w trakcie gry (a okno nie jest zamykane), pokazujemy błąd zamiast martwej strony.
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
                &format!("Python zakończył działanie ({status}).\n\n{tail}"),
            );
            return;
        }
    });
}

/// Zamknięcie standardowego wejścia kończy Pythona (tryb `--server`); po chwili — na wszelki wypadek — kill.
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
        .expect("nie udało się utworzyć okna TacticMind")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_backend(app);
            }
        });
}
