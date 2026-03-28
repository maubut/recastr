"""
Recastr Server - Backend local pour l'editeur.
Lance un serveur HTTP qui expose une API REST pour:
  - Analyser des videos + cursor logs
  - Transcrire l'audio (Whisper)
  - Render les videos (FFmpeg)
  - Controler OBS (WebSocket)
  - Servir les fichiers (videos, HTML)

Usage:
  python server.py
  python server.py --port 8888
"""

import http.server
import json
import os
import sys
import signal
import subprocess
import threading
import time
import argparse
import webbrowser
import socketserver
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

# Import des fonctions existantes
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from auto_zoom import (
    get_video_info, load_cursor_log, detect_zoom_events,
    compute_frame_data, render_video, transcribe_video
)


# ============================================================
# GLOBAL STATE
# ============================================================

class ServerState:
    """Etat global du serveur, thread-safe."""
    def __init__(self):
        self.lock = threading.Lock()
        # Render
        self.render_thread = None
        self.render_progress = {
            "state": "idle",  # idle, running, done, error
            "frames_done": 0,
            "total_frames": 0,
            "output_path": None,
            "error": None,
        }
        # OBS
        self.obs_client = None
        self.obs_connected = False
        self.obs_recording = False
        self.cursor_process = None
        self.cursor_log_path = None
        self.last_video_path = None
        # Transcription
        self.transcribe_thread = None
        self.transcribe_result = None
        self.transcribe_state = "idle"  # idle, running, done, error
        # Fichiers connus (glisses par l'utilisateur)
        self.known_dirs = set()
        # Analyzed data cache
        self.last_analysis = None

    def update_render(self, **kwargs):
        with self.lock:
            self.render_progress.update(kwargs)

    def get_render(self):
        with self.lock:
            return dict(self.render_progress)

    def add_dir(self, filepath):
        """Ajoute le dossier parent d'un fichier aux dossiers servis."""
        d = os.path.dirname(os.path.abspath(filepath))
        self.known_dirs.add(d)


state = ServerState()


# ============================================================
# OBS CAPTURE REGION DETECTION
# ============================================================

def detect_obs_capture_region(obs_client):
    """
    Detecte la region de capture OBS (quel moniteur / quelle fenetre).
    Retourne (x, y, w, h) en coordonnees ecran, ou None.
    """
    try:
        scene = obs_client.get_current_program_scene()
        items = obs_client.get_scene_item_list(scene.scene_name)
        print(f"[OBS REGION] Scene: {scene.scene_name}, {len(items.scene_items)} sources")

        for item in items.scene_items:
            source_name = item.get("sourceName", "")
            try:
                settings = obs_client.get_input_settings(source_name)
                kind = settings.input_kind
                s = settings.input_settings
                print(f"[OBS REGION] Source '{source_name}': kind={kind}")
                print(f"[OBS REGION]   Settings keys: {list(s.keys())}")

                if "monitor_capture" in kind or "screen_capture" in kind or "display_capture" in kind:
                    monitor_id = s.get("monitor", s.get("monitor_id", 0))
                    print(f"[OBS REGION]   monitor={monitor_id}")

                    if isinstance(monitor_id, str) and len(monitor_id) > 5:
                        # OBS donne un device path string — matcher via Windows API
                        region = match_monitor_by_device_path(monitor_id)
                        if region:
                            print(f"[OBS REGION]   -> Match device path: {region}")
                            return region
                    elif isinstance(monitor_id, int):
                        monitors = enumerate_monitors()
                        if monitors and monitor_id < len(monitors):
                            print(f"[OBS REGION]   -> Index {monitor_id}: {monitors[monitor_id]}")
                            return monitors[monitor_id]

                    # Fallback: matcher par resolution du canvas OBS
                    video = obs_client.get_video_settings()
                    bw, bh = video.base_width, video.base_height
                    print(f"[OBS REGION]   Fallback: cherche moniteur {bw}x{bh}")
                    monitors = enumerate_monitors()
                    for m in monitors:
                        if m[2] == bw and m[3] == bh:
                            print(f"[OBS REGION]   -> Match resolution: {m}")
                            return m
                    if monitors:
                        print(f"[OBS REGION]   -> Pas de match exact, premier moniteur")
                        return monitors[0]
                    return (0, 0, bw, bh)

                elif "window_capture" in kind or "game_capture" in kind:
                    window_name = s.get("window", "")
                    print(f"[OBS REGION]   window='{window_name}'")
                    if ":" in window_name:
                        title_part = window_name.split(":")[0]
                        if title_part:
                            try:
                                from cursor_logger import find_window_by_title_substring, get_client_rect_screen
                                matches = find_window_by_title_substring(title_part)
                                if matches:
                                    hwnd, title = matches[0]
                                    region = get_client_rect_screen(hwnd)
                                    print(f"[OBS REGION]   -> Window '{title}': {region}")
                                    return region
                            except Exception as we:
                                print(f"[OBS REGION]   Window detection failed: {we}")
            except Exception as src_e:
                print(f"[OBS REGION]   Source '{source_name}' error: {src_e}")
                continue
    except Exception as e:
        import traceback
        print(f"[OBS REGION] Erreur: {e}")
        traceback.print_exc()

    return None


def match_monitor_by_device_path(obs_device_path):
    """
    Matche le device path OBS (ex: \\\\?\\DISPLAY#GWDF9D0#7&c73cee4&...#{...})
    avec les moniteurs Windows en utilisant GetMonitorInfo + EnumDisplayDevices.
    """
    try:
        import ctypes
        import ctypes.wintypes

        # Extraire l'identifiant du moniteur depuis le path OBS
        # Format: \\?\DISPLAY#<model>#<instance>#{<guid>}
        # On extrait "<model>#<instance>" pour matcher
        obs_parts = obs_device_path.replace("\\\\?\\", "").replace("\\?\\", "")
        # obs_parts = "DISPLAY#GWDF9D0#7&c73cee4&0&UID256#{e6f07b5f-...}"
        segments = obs_parts.split("#")
        # ["DISPLAY", "GWDF9D0", "7&c73cee4&0&UID256", "{e6f07b5f-...}"]
        obs_model = segments[1] if len(segments) > 1 else ""
        obs_instance = segments[2] if len(segments) > 2 else ""
        print(f"[OBS REGION]   OBS model='{obs_model}', instance='{obs_instance}'")

        # Enumerer les moniteurs avec GetMonitorInfo pour obtenir le device name
        class MONITORINFOEX(ctypes.Structure):
            _fields_ = [
                ('cbSize', ctypes.wintypes.DWORD),
                ('rcMonitor', ctypes.wintypes.RECT),
                ('rcWork', ctypes.wintypes.RECT),
                ('dwFlags', ctypes.wintypes.DWORD),
                ('szDevice', ctypes.c_wchar * 32),
            ]

        monitor_infos = []

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_longlong
        )

        def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
            info = MONITORINFOEX()
            info.cbSize = ctypes.sizeof(info)
            ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
            r = info.rcMonitor
            monitor_infos.append({
                'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top),
                'device': info.szDevice,  # ex: \\\\.\\DISPLAY1
            })
            return True

        ctypes.windll.user32.EnumDisplayMonitors(
            None, None, MONITORENUMPROC(callback), 0
        )

        print(f"[OBS REGION]   {len(monitor_infos)} moniteurs avec device names:")
        for mi in monitor_infos:
            print(f"[OBS REGION]     {mi['device']}: {mi['rect']}")

        # Pour chaque moniteur, obtenir le device ID via EnumDisplayDevices
        class DISPLAY_DEVICE(ctypes.Structure):
            _fields_ = [
                ('cb', ctypes.wintypes.DWORD),
                ('DeviceName', ctypes.c_wchar * 32),
                ('DeviceString', ctypes.c_wchar * 128),
                ('StateFlags', ctypes.wintypes.DWORD),
                ('DeviceID', ctypes.c_wchar * 128),
                ('DeviceKey', ctypes.c_wchar * 128),
            ]

        for mi in monitor_infos:
            dev_name = mi['device']
            dd = DISPLAY_DEVICE()
            dd.cb = ctypes.sizeof(dd)
            # EnumDisplayDevices avec le device name du moniteur, index 0
            if ctypes.windll.user32.EnumDisplayDevicesW(dev_name, 0, ctypes.byref(dd), 1):
                device_id = dd.DeviceID
                print(f"[OBS REGION]     {dev_name} -> ID: {device_id}")
                # Matcher: le device_id contient le meme model et instance
                if obs_model and obs_model.upper() in device_id.upper():
                    if not obs_instance or obs_instance.upper() in device_id.upper():
                        print(f"[OBS REGION]     MATCH! -> {mi['rect']}")
                        return mi['rect']

        print(f"[OBS REGION]   Pas de match par device ID")
        return None

    except Exception as e:
        print(f"[OBS REGION]   match_monitor error: {e}")
        import traceback
        traceback.print_exc()
        return None


def enumerate_monitors():
    """Enumere tous les moniteurs et retourne [(x, y, w, h), ...] tries par position."""
    try:
        import ctypes
        import ctypes.wintypes

        monitors = []

        # Callback type pour EnumDisplayMonitors
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,   # hMonitor
            ctypes.c_void_p,   # hdcMonitor
            ctypes.POINTER(ctypes.wintypes.RECT),  # lprcMonitor
            ctypes.c_longlong  # dwData (LPARAM)
        )

        def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
            r = lprcMonitor.contents
            monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(
            None, None, MONITORENUMPROC(callback), 0
        )

        # Trier par position X (gauche a droite)
        monitors.sort(key=lambda m: (m[0], m[1]))
        print(f"[MONITORS] {len(monitors)} moniteurs: {monitors}")
        return monitors

    except Exception as e:
        print(f"[MONITORS] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return []


# ============================================================
# API HANDLERS
# ============================================================

def handle_analyze(data):
    """Analyse une video + cursor log, retourne les zoom events."""
    video_path = data.get("video_path", "")
    log_path = data.get("cursor_log_path", "")

    if not video_path or not os.path.exists(video_path):
        return 400, {"error": f"Video introuvable: {video_path}"}
    if not log_path or not os.path.exists(log_path):
        return 400, {"error": f"Cursor log introuvable: {log_path}"}

    state.add_dir(video_path)
    state.add_dir(log_path)

    try:
        video_w, video_h, video_duration, video_fps = get_video_info(video_path)
        metadata, events = load_cursor_log(log_path)

        config = {
            "zoom_click": data.get("zoom_click", 2.0),
            "zoom_still": data.get("zoom_still", 1.5),
            "hold_click": data.get("hold_click", 1.5),
            "hold_still": data.get("hold_still", 3.0),
        }
        zoom_events = detect_zoom_events(events, config)

        # Webcam info from log
        webcam_info = metadata.get("webcam")

        result = {
            "success": True,
            "video_info": {
                "width": video_w,
                "height": video_h,
                "duration": video_duration,
                "fps": video_fps,
            },
            "zoom_events": zoom_events,
            "cursor_events": events,
            "webcam_info": webcam_info,
            "metadata": {k: v for k, v in metadata.items() if k != "webcam"},
        }
        state.last_analysis = result
        return 200, result

    except Exception as e:
        return 500, {"error": str(e)}


def handle_transcribe(data):
    """Lance la transcription Whisper en arriere-plan."""
    video_path = data.get("video_path", "")
    model = data.get("model", "base")
    language = data.get("language")

    if not video_path or not os.path.exists(video_path):
        return 400, {"error": f"Video introuvable: {video_path}"}

    if state.transcribe_state == "running":
        return 409, {"error": "Transcription deja en cours"}

    state.transcribe_state = "running"
    state.transcribe_result = None

    def run_transcribe():
        try:
            segments = transcribe_video(video_path, model_name=model, language=language)
            state.transcribe_result = segments or []
            state.transcribe_state = "done"
        except Exception as e:
            state.transcribe_result = str(e)
            state.transcribe_state = "error"

    t = threading.Thread(target=run_transcribe, daemon=True)
    t.start()
    state.transcribe_thread = t

    return 200, {"success": True, "message": "Transcription lancee"}


def handle_transcribe_status(data=None):
    """Retourne le status de la transcription."""
    result = {
        "state": state.transcribe_state,
    }
    if state.transcribe_state == "done":
        result["segments"] = state.transcribe_result
    elif state.transcribe_state == "error":
        result["error"] = state.transcribe_result
    return 200, result


def handle_render(data):
    """Lance le render FFmpeg en arriere-plan."""
    import traceback as _tb
    print(f"\n[RENDER] Received data keys: {list(data.keys())}")
    video_path = data.get("video_path", "")
    output_path = data.get("output_path", "")
    zoom_events = data.get("zoom_events", [])
    fps = data.get("fps", 30)
    print(f"[RENDER] {len(zoom_events)} zoom events, video: {video_path}")
    if zoom_events:
        print(f"[RENDER] First zoom event keys: {list(zoom_events[0].keys())}")
        print(f"[RENDER] First zoom event: {zoom_events[0]}")
    captions = data.get("captions")
    background = data.get("background")
    webcam = data.get("webcam")
    webcam_file = data.get("webcam_file")

    if not video_path or not os.path.exists(video_path):
        return 400, {"error": f"Video introuvable: {video_path}"}

    if state.render_progress.get("state") == "running":
        return 409, {"error": "Render deja en cours"}

    if not output_path:
        stem = Path(video_path).stem
        output_path = str(Path(video_path).parent / f"{stem}_zoomed.mp4")

    try:
        video_w, video_h, video_duration, video_fps = get_video_info(video_path)
    except Exception as e:
        return 500, {"error": f"Impossible de lire la video: {e}"}

    # S'assurer que chaque zoom event a nx/ny (valeurs par defaut si absentes)
    for ze in zoom_events:
        ze.setdefault("nx", 0.5)
        ze.setdefault("ny", 0.5)
        ze.setdefault("ease_in", 0.3)
        ze.setdefault("ease_out", 0.5)
        ze.setdefault("hold", 1.5)

    try:
        frame_data = compute_frame_data(zoom_events, video_duration, fps)
    except Exception as e:
        return 500, {"error": f"Erreur compute_frame_data: {e}"}
    total_frames = len(frame_data)

    state.update_render(
        state="running", frames_done=0, total_frames=total_frames,
        output_path=output_path, error=None
    )

    def run_render():
        try:
            # On modifie render_video pour supporter un callback de progression
            # Pour l'instant, on lance directement
            render_video(
                video_path, output_path, frame_data, fps, video_w, video_h,
                background=background, captions=captions, webcam=webcam,
                webcam_file=webcam_file
            )
            state.update_render(state="done", frames_done=total_frames)
        except Exception as e:
            state.update_render(state="error", error=str(e))

    t = threading.Thread(target=run_render, daemon=True)
    t.start()
    state.render_thread = t

    return 200, {
        "success": True,
        "message": "Render lance",
        "output_path": output_path,
        "total_frames": total_frames,
    }


def handle_render_status(data=None):
    """Retourne la progression du render."""
    return 200, state.get_render()


def handle_obs_connect(data):
    """Connecte a OBS via WebSocket."""
    host = data.get("host", "localhost")
    port = data.get("port", 4455)
    password = data.get("password", "")

    try:
        import obsws_python as obs
        client = obs.ReqClient(host=host, port=port, password=password)
        version = client.get_version()
        state.obs_client = client
        state.obs_connected = True
        return 200, {
            "success": True,
            "obs_version": version.obs_version,
            "message": f"Connecte a OBS {version.obs_version}",
        }
    except ImportError:
        return 503, {"error": "obsws-python non installe. pip install obsws-python"}
    except Exception as e:
        state.obs_connected = False
        return 500, {"error": f"Connexion OBS echouee: {e}"}


def handle_obs_start(data):
    """Demarre l'enregistrement OBS + cursor logger."""
    if not state.obs_connected or not state.obs_client:
        return 400, {"error": "OBS non connecte"}

    try:
        import time as _t

        # ---- Phase 1: Detections AVANT de demarrer (pas de delai) ----
        webcam_info = None
        try:
            from cursor_logger import detect_obs_webcam
            webcam_info = detect_obs_webcam(state.obs_client)
            if webcam_info:
                state.webcam_info = webcam_info
                print(f"[OBS START] Webcam detectee: {webcam_info.get('name', '?')}")
        except Exception as e:
            print(f"[OBS START] Webcam detection: {e}")

        capture_region = None
        try:
            print("[OBS START] Detection de la region de capture...")
            capture_region = detect_obs_capture_region(state.obs_client)
            if capture_region:
                print(f"[OBS START] Region capture detectee: {capture_region}")
            else:
                print("[OBS START] ATTENTION: region non detectee, fallback fullscreen")
        except Exception as e:
            print(f"[OBS START] Detection region ERREUR: {e}")
            import traceback
            traceback.print_exc()

        # ---- Phase 2: Preparer la commande cursor logger ----
        logger_script = os.path.join(SCRIPT_DIR, "cursor_logger.py")
        if capture_region:
            region_str = f"{capture_region[0]},{capture_region[1]},{capture_region[2]},{capture_region[3]}"
            cmd = [sys.executable, logger_script, "--region", region_str, "--no-calibration", "--auto-start"]
        else:
            cmd = [sys.executable, logger_script, "--fullscreen", "--no-calibration", "--auto-start"]
        print(f"[OBS START] Commande: {' '.join(cmd)}")

        # ---- Phase 3: Lancer cursor logger + OBS quasi-simultanement ----
        log_file_path = os.path.join(SCRIPT_DIR, "cursor_logger_debug.log")
        state._cursor_log_file = open(log_file_path, "w")

        # Lancer cursor logger en premier (demarre instantanement grace a --auto-start)
        state.cursor_process = subprocess.Popen(
            cmd, stdout=state._cursor_log_file, stderr=subprocess.STDOUT,
            cwd=SCRIPT_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        print(f"[OBS START] Cursor logger PID: {state.cursor_process.pid}")

        # Demarrer OBS recording immediatement apres
        print("[OBS START] Demarrage enregistrement OBS...")
        state.obs_client.start_record()
        state.obs_recording = True
        state.obs_start_time = _t.time()
        print(f"[OBS START] OBS enregistre! (t={state.obs_start_time:.3f})")

        # Verifier que le cursor logger n'a pas crashe
        _t.sleep(0.5)
        poll = state.cursor_process.poll()
        if poll is not None:
            print(f"[OBS START] ERREUR: cursor logger a crashe immediatement (code: {poll})")
            return 500, {
                "error": f"Cursor logger a crashe (code: {poll})",
            }

        print(f"[OBS START] Cursor logger tourne (PID {state.cursor_process.pid})")
        return 200, {
            "success": True,
            "message": "Enregistrement OBS + cursor logger demarres",
            "cursor_log_dir": SCRIPT_DIR,
            "cursor_pid": state.cursor_process.pid,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return 500, {"error": f"Erreur demarrage: {e}"}


def handle_obs_stop(data=None):
    """Arrete l'enregistrement OBS + cursor logger."""
    import glob
    import time as _time
    messages = []

    print("\n[OBS STOP] === Arret en cours ===")

    # Stop OBS recording FIRST
    if state.obs_connected and state.obs_client:
        try:
            print("[OBS STOP] Arret OBS recording...")
            result = state.obs_client.stop_record()
            video_path = getattr(result, "output_path", None)
            if video_path:
                state.last_video_path = video_path.replace("\\", "/")
                state.add_dir(video_path)
            state.obs_recording = False
            print(f"[OBS STOP] OBS arrete. Video: {video_path}")
            messages.append(f"OBS arrete. Video: {video_path}")
        except Exception as e:
            print(f"[OBS STOP] OBS stop erreur: {e}")
            messages.append(f"OBS stop: {e}")
    else:
        print("[OBS STOP] OBS non connecte ou pas de client")

    # Stop cursor logger
    if state.cursor_process:
        poll = state.cursor_process.poll()
        print(f"[OBS STOP] Cursor logger PID: {state.cursor_process.pid}, poll: {poll}")

        if poll is not None:
            print(f"[OBS STOP] Cursor logger deja termine (code: {poll})")
            messages.append(f"Cursor logger deja termine (code: {poll})")
        else:
            # Encore en cours — envoyer le stop signal
            try:
                stop_file = os.path.join(SCRIPT_DIR, ".recastr_stop")
                print(f"[OBS STOP] Creation stop file: {stop_file}")
                with open(stop_file, "w") as f:
                    f.write("stop")
                messages.append("Signal d'arret envoye")

                print("[OBS STOP] Attente du cursor logger (max 15s)...")
                state.cursor_process.wait(timeout=15)
                exit_code = state.cursor_process.returncode
                print(f"[OBS STOP] Cursor logger termine (code: {exit_code})")
                messages.append(f"Cursor logger arrete (code: {exit_code})")
            except subprocess.TimeoutExpired:
                print("[OBS STOP] TIMEOUT! Force kill...")
                messages.append("Cursor logger: timeout, force kill")
                try:
                    state.cursor_process.terminate()
                    state.cursor_process.wait(timeout=5)
                except:
                    state.cursor_process.kill()
            except Exception as e:
                print(f"[OBS STOP] Erreur: {e}")
                import traceback
                traceback.print_exc()
                messages.append(f"Cursor logger: {e}")
                try:
                    state.cursor_process.kill()
                except:
                    pass

        # Fermer le fichier log du cursor logger
        try:
            if hasattr(state, '_cursor_log_file') and state._cursor_log_file:
                state._cursor_log_file.close()
                state._cursor_log_file = None
        except:
            pass

        # Nettoyer le stop file
        try:
            sf = os.path.join(SCRIPT_DIR, ".recastr_stop")
            if os.path.exists(sf):
                os.remove(sf)
        except:
            pass
    else:
        print("[OBS STOP] Pas de cursor process!")
        messages.append("Pas de cursor logger en cours")

    # Delai
    _time.sleep(1.0)

    # ---- Chercher le cursor_log le plus recent ----
    cursor_log_path = None
    search_dirs = [SCRIPT_DIR, os.getcwd()]
    if state.last_video_path:
        search_dirs.append(os.path.dirname(os.path.abspath(state.last_video_path)))
    home = os.path.expanduser("~")
    for sub in ["Desktop", "Videos", "Documents", "obs-record"]:
        p = os.path.join(home, sub)
        if os.path.isdir(p):
            search_dirs.append(p)
        p2 = os.path.join(home, "Desktop", sub)
        if os.path.isdir(p2):
            search_dirs.append(p2)

    print(f"[OBS STOP] Recherche cursor_log dans: {list(set(search_dirs))}")
    all_logs = []
    for d in set(search_dirs):
        found = glob.glob(os.path.join(d, "cursor_log_*.json"))
        if found:
            print(f"[OBS STOP]   {d}: {[os.path.basename(f) for f in found]}")
        all_logs.extend(found)

    if all_logs:
        all_logs.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        cursor_log_path = all_logs[0].replace("\\", "/")
        state.cursor_log_path = cursor_log_path
        state.add_dir(cursor_log_path)
        print(f"[OBS STOP] Cursor log trouve: {cursor_log_path}")
        messages.append(f"Cursor log: {cursor_log_path}")
    else:
        print("[OBS STOP] AUCUN cursor_log_*.json trouve!")

    # ---- Chercher le fichier webcam/camera (Source Record) ----
    # Source Record cree souvent un fichier avec "camera", "cam", "webcam" dans le nom
    webcam_file_path = None
    if state.last_video_path:
        video_dir = os.path.dirname(os.path.abspath(state.last_video_path))
        video_mtime = os.path.getmtime(state.last_video_path) if os.path.exists(state.last_video_path) else 0
        cam_patterns = ["*camera*", "*cam*", "*webcam*", "*facecam*", "*face*"]
        cam_extensions = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts"]
        candidates = []
        for pattern in cam_patterns:
            for ext in cam_extensions:
                candidates.extend(glob.glob(os.path.join(video_dir, pattern + ext)))
        # Aussi chercher dans SCRIPT_DIR
        for pattern in cam_patterns:
            for ext in cam_extensions:
                candidates.extend(glob.glob(os.path.join(SCRIPT_DIR, pattern + ext)))

        if candidates:
            # Garder seulement les fichiers recents (crees dans les 2 dernieres minutes)
            recent = [f for f in candidates if abs(os.path.getmtime(f) - video_mtime) < 120]
            if recent:
                recent.sort(key=lambda f: os.path.getmtime(f), reverse=True)
                webcam_file_path = recent[0].replace("\\", "/")
                state.add_dir(webcam_file_path)
                messages.append(f"Webcam file: {webcam_file_path}")

    # ---- Lire le contenu du cursor log pour le renvoyer directement ----
    cursor_log_data = None
    if cursor_log_path and os.path.exists(cursor_log_path):
        try:
            with open(cursor_log_path, "r") as f:
                cursor_log_data = json.load(f)
        except:
            pass

    return 200, {
        "success": True,
        "messages": messages,
        "video_path": state.last_video_path,
        "cursor_log_path": cursor_log_path,
        "cursor_log_data": cursor_log_data,
        "webcam_file_path": webcam_file_path,
    }


def handle_obs_status(data=None):
    """Retourne le status OBS."""
    return 200, {
        "connected": state.obs_connected,
        "recording": state.obs_recording,
        "cursor_logging": state.cursor_process is not None and state.cursor_process.poll() is None,
        "last_video_path": state.last_video_path,
        "cursor_log_path": state.cursor_log_path,
    }


def handle_file_info(data):
    """Retourne les infos d'un fichier video."""
    path = data.get("path", "")
    if not path or not os.path.exists(path):
        return 400, {"error": f"Fichier introuvable: {path}"}

    state.add_dir(path)

    try:
        w, h, d, fps = get_video_info(path)
        return 200, {
            "success": True,
            "path": path,
            "filename": os.path.basename(path),
            "width": w, "height": h,
            "duration": d, "fps": fps,
        }
    except Exception as e:
        return 500, {"error": str(e)}


# ============================================================
# HTTP SERVER
# ============================================================

# Route table
ROUTES = {
    ("POST", "/api/analyze"): handle_analyze,
    ("POST", "/api/transcribe"): handle_transcribe,
    ("GET",  "/api/transcribe/status"): handle_transcribe_status,
    ("POST", "/api/render"): handle_render,
    ("GET",  "/api/render/status"): handle_render_status,
    ("POST", "/api/obs/connect"): handle_obs_connect,
    ("POST", "/api/obs/start"): handle_obs_start,
    ("POST", "/api/obs/stop"): handle_obs_stop,
    ("GET",  "/api/obs/status"): handle_obs_status,
    ("POST", "/api/file-info"): handle_file_info,
}


class RecastrHandler(http.server.SimpleHTTPRequestHandler):
    """Handler HTTP qui route les API et sert les fichiers statiques."""

    def __init__(self, *args, static_dir=None, **kwargs):
        self._static_dir = static_dir or SCRIPT_DIR
        super().__init__(*args, directory=self._static_dir, **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path

        # API routes
        handler = ROUTES.get(("GET", path))
        if handler:
            code, data = handler()
            self._send_json(code, data)
            return

        # SPA: redirect / to index.html
        if path == '/' or path == '/app.html':
            self.path = '/index.html'

        # Try to serve from static dir first (dist/), then fallback to SCRIPT_DIR for videos etc.
        # Check if file exists in static dir
        translated = self.translate_path(self.path)
        if not os.path.exists(translated):
            # Fallback: try serving from SCRIPT_DIR (for video files, cursor logs, etc.)
            basename = unquote(path.lstrip('/'))
            fallback = os.path.join(SCRIPT_DIR, basename)
            if os.path.isfile(fallback):
                self.path = self.path  # keep path, temporarily change directory
                old_dir = self.directory
                self.directory = SCRIPT_DIR
                super().do_GET()
                self.directory = old_dir
                return

        # Serve files
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        handler = ROUTES.get(("POST", path))
        if not handler:
            self._send_json(404, {"error": f"Route non trouvee: {path}"})
            return

        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "JSON invalide"})
            return

        code, result = handler(data)
        self._send_json(code, result)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def translate_path(self, path):
        """Sert les fichiers du dossier statique + dossiers des videos."""
        # D'abord le dossier statique
        local = super().translate_path(path)
        if os.path.exists(local):
            return local

        # Chercher dans les dossiers connus (videos glissees)
        rel = unquote(path.lstrip("/"))
        for d in state.known_dirs:
            candidate = os.path.join(d, rel)
            if os.path.exists(candidate):
                return candidate
            # Aussi chercher juste par nom de fichier
            candidate2 = os.path.join(d, os.path.basename(rel))
            if os.path.exists(candidate2):
                return candidate2

        return local

    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        # Silencieux sauf erreurs
        if args and str(args[0]).startswith("4") or str(args[0]).startswith("5"):
            super().log_message(format, *args)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Recastr Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--no-open", action="store_true", help="Ne pas ouvrir le browser")
    args = parser.parse_args()

    # Serve from dist/ if it exists (Svelte build), otherwise serve from script dir
    dist_dir = os.path.join(SCRIPT_DIR, "dist")
    static_dir = dist_dir if os.path.isdir(dist_dir) else SCRIPT_DIR
    print(f"  Static: {static_dir}")

    # Handler factory
    def handler_factory(*a, **kw):
        return RecastrHandler(*a, static_dir=static_dir, **kw)

    server = ThreadedHTTPServer((args.host, args.port), handler_factory)
    port = server.server_address[1]

    url = f"http://{args.host}:{port}"
    print("=" * 50)
    print("  RECASTR SERVER")
    print("=" * 50)
    print(f"\n  URL: {url}")
    print(f"  API: {url}/api/...")
    print(f"\n  Ctrl+C pour arreter.\n")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Fermeture du serveur...")
        server.shutdown()


if __name__ == "__main__":
    main()
