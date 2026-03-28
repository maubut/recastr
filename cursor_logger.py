"""
AutoZoom - Cursor Logger v4

Fix DPI scaling + calibration pour s'assurer que les coords matchent.

Mode OBS:
  python cursor_logger.py --obs
Mode standalone:
  python cursor_logger.py
"""

import json
import time
import sys
import os
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

# ============================================================
# FIX DPI: Dire a Windows qu'on veut les VRAIS pixels
# Sans ca, GetCursorPos retourne des coords "scaled" qui
# ne matchent pas ce que OBS capture.
# ============================================================
try:
    # Windows 10+ : Per-Monitor DPI aware
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        # Fallback Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            # Fallback vieux Windows
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# --- Windows API ---
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long)
    ]

def get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def get_screen_size():
    # Avec DPI awareness, ca retourne la vraie resolution
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

def get_dpi_scale():
    """Detecte le scaling DPI actif."""
    try:
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except:
        return 1.0

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02

def is_clicking(button=VK_LBUTTON):
    return bool(user32.GetAsyncKeyState(button) & 0x8000)

def is_key_pressed(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)

# Scroll detection via mouse_event hook
# On ne peut pas facilement detecter le scroll wheel avec GetAsyncKeyState
# On va plutot detecter les patterns dans le mouvement du contenu
# (cursor immobile + page qui change = scroll probable)


# --- Detection de fenetre ---

def get_window_rect_real(hwnd):
    """Rect de la fenetre avec le vrai size (DWM, sans ombre)."""
    rect = RECT()
    try:
        dwmapi = ctypes.windll.dwmapi
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect), ctypes.sizeof(rect)
        )
    except:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def get_client_rect_screen(hwnd):
    """Zone client (sans title bar) en coordonnees ecran."""
    client_rect = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client_rect))
    pt_tl = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt_tl))
    w = client_rect.right - client_rect.left
    h = client_rect.bottom - client_rect.top
    return pt_tl.x, pt_tl.y, w, h


def get_window_title(hwnd):
    if not hwnd:
        return "fullscreen"
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def find_window_by_title_substring(substring):
    result = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_callback(hwnd, lparam):
        title = get_window_title(hwnd)
        if substring.lower() in title.lower() and user32.IsWindowVisible(hwnd):
            result.append((hwnd, title))
        return True
    user32.EnumWindows(enum_callback, 0)
    return result


def wait_for_click_on_window():
    """Demande a l'utilisateur de cliquer sur la fenetre cible."""
    print("  >>> Clique sur la FENETRE que OBS capture <<<")
    print("  (la fenetre de ton app/browser/etc)")
    print()

    while is_clicking():
        time.sleep(0.05)
    while not is_clicking():
        time.sleep(0.05)
    time.sleep(0.1)

    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    hwnd = user32.WindowFromPoint(pt)

    parent = user32.GetParent(hwnd)
    while parent:
        hwnd = parent
        parent = user32.GetParent(hwnd)

    return hwnd


# --- Calibration ---

def run_calibration(hwnd):
    """
    Demande a l'utilisateur de cliquer sur le coin haut-gauche
    et bas-droit de la zone visible pour verifier le mapping.
    """
    print()
    print("  === CALIBRATION ===")
    print("  On va verifier que le mapping est correct.")
    print()

    # Obtenir le rect qu'on pense etre bon
    if hwnd:
        cx, cy, cw, ch = get_client_rect_screen(hwnd)
        wx, wy, ww, wh = get_window_rect_real(hwnd)
        print(f"  Rect client detecte: ({cx},{cy}) {cw}x{ch}")
        print(f"  Rect fenetre:        ({wx},{wy}) {ww}x{wh}")
    else:
        sw, sh = get_screen_size()
        print(f"  Plein ecran: {sw}x{sh}")

    print()
    print("  ETAPE 1: Clique dans le coin HAUT-GAUCHE de la zone")
    print("           que OBS capture (le pixel le plus haut-gauche visible)")

    while is_clicking():
        time.sleep(0.05)
    while not is_clicking():
        time.sleep(0.05)
    tl_x, tl_y = get_cursor_pos()
    print(f"  -> Haut-gauche: ({tl_x}, {tl_y})")
    time.sleep(0.5)

    print()
    print("  ETAPE 2: Clique dans le coin BAS-DROIT de la zone")

    while is_clicking():
        time.sleep(0.05)
    while not is_clicking():
        time.sleep(0.05)
    br_x, br_y = get_cursor_pos()
    print(f"  -> Bas-droit: ({br_x}, {br_y})")

    cal_w = br_x - tl_x
    cal_h = br_y - tl_y

    print()
    print(f"  Zone calibree: ({tl_x},{tl_y}) {cal_w}x{cal_h}")

    if hwnd:
        diff_x = abs(tl_x - cx)
        diff_y = abs(tl_y - cy)
        diff_w = abs(cal_w - cw)
        diff_h = abs(cal_h - ch)

        if diff_x < 10 and diff_y < 10 and diff_w < 20 and diff_h < 20:
            print("  -> Detection auto OK! Les coords matchent.")
            return cx, cy, cw, ch
        else:
            print(f"  -> DECALAGE detecte!")
            print(f"     Auto: ({cx},{cy}) {cw}x{ch}")
            print(f"     Reel: ({tl_x},{tl_y}) {cal_w}x{cal_h}")
            print(f"  -> On utilise la calibration manuelle.")
            return tl_x, tl_y, cal_w, cal_h
    else:
        return tl_x, tl_y, cal_w, cal_h


# --- OBS WebSocket ---

def connect_obs(port=4455, password=""):
    try:
        import obsws_python as obs
        cl = obs.ReqClient(host="localhost", port=port, password=password, timeout=5)
        v = cl.get_version()
        print(f"  Connecte a OBS {v.obs_version}")
        return cl
    except ImportError:
        print("  obsws_python manquant. pip install obsws-python")
        return None
    except Exception as e:
        print(f"  Connexion OBS echouee: {e}")
        return None


def detect_obs_capture_window(obs_client):
    try:
        scene = obs_client.get_current_program_scene()
        items = obs_client.get_scene_item_list(scene.scene_name)

        for item in items.scene_items:
            source_name = item.get("sourceName", "")
            try:
                settings = obs_client.get_input_settings(source_name)
                kind = settings.input_kind
                s = settings.input_settings

                if "monitor_capture" in kind or "screen_capture" in kind:
                    print(f"  Source: capture ecran (plein ecran)")
                    return None

                if "window_capture" in kind or "game_capture" in kind:
                    window_name = s.get("window", "")
                    if ":" in window_name:
                        title_part = window_name.split(":")[0]
                        if title_part:
                            matches = find_window_by_title_substring(title_part)
                            if matches:
                                hwnd, title = matches[0]
                                print(f"  Fenetre OBS: {title}")
                                return hwnd
            except:
                continue

        return "ask"
    except Exception as e:
        print(f"  Detection: {e}")
        return "ask"



def disable_obs_cursor(obs_client):
    """
    Desactive la capture du curseur sur toutes les sources de la scene active.
    Retourne une liste de (source_name, cursor_key, old_value) pour restaurer apres.

    Essaie les deux cles de curseur connues sur chaque source:
      - "cursor"          (window_capture)
      - "capture_cursor"  (monitor_capture, game_capture, screen_capture)
    """
    restored = []
    try:
        scene = obs_client.get_current_program_scene()
        print(f"  Scene active: {scene.scene_name}")
        items = obs_client.get_scene_item_list(scene.scene_name)

        if not items.scene_items:
            print("  ATTENTION: aucune source trouvee dans la scene!")
            return restored

        for item in items.scene_items:
            source_name = item.get("sourceName", "")
            try:
                settings = obs_client.get_input_settings(source_name)
                kind = settings.input_kind
                s = settings.input_settings

                print(f"  Source: '{source_name}' (type: {kind})")
                print(f"    Settings: {dict(s)}")

                # Essayer les deux cles de curseur possibles
                cursor_key = None
                for try_key in ["cursor", "capture_cursor"]:
                    if try_key in s:
                        cursor_key = try_key
                        break

                # Si aucune cle trouvee dans les settings, deviner selon le type
                if cursor_key is None:
                    if "window_capture" in kind:
                        cursor_key = "cursor"
                    elif any(k in kind for k in ["game_capture", "monitor_capture",
                                                   "screen_capture", "display_capture"]):
                        cursor_key = "capture_cursor"

                if cursor_key is None:
                    print(f"    -> Pas de setting curseur (type: {kind})")
                    continue

                # Sauvegarder l'etat actuel
                old_value = s.get(cursor_key, True)
                restored.append((source_name, cursor_key, old_value))

                # Desactiver
                print(f"    -> Cle: {cursor_key}, valeur actuelle: {old_value}")
                obs_client.set_input_settings(source_name, {cursor_key: False}, True)

                # Forcer OBS a rafraichir la source (toggle enabled off/on)
                scene_name = scene.scene_name
                item_id = item.get("sceneItemId")
                if item_id is not None:
                    try:
                        obs_client.set_scene_item_enabled(scene_name, item_id, False)
                        import time; time.sleep(0.3)
                        obs_client.set_scene_item_enabled(scene_name, item_id, True)
                        print(f"    -> Source rafraichie (toggle off/on)")
                    except Exception:
                        pass

                # Verifier que ca a marche
                verify = obs_client.get_input_settings(source_name)
                new_val = verify.input_settings.get(cursor_key, "???")
                if new_val == False:
                    print(f"    -> DESACTIVE OK")
                else:
                    print(f"    -> ATTENTION: valeur apres set = {new_val} (attendu: False)")

            except Exception as ex:
                print(f"    -> Erreur: {ex}")
                continue

    except Exception as e:
        print(f"  Desactivation curseur ERREUR: {e}")
        import traceback
        traceback.print_exc()

    return restored


def restore_obs_cursor(obs_client, restored_list):
    """Restaure les settings de curseur sauvegardes."""
    for source_name, cursor_key, old_value in restored_list:
        try:
            obs_client.set_input_settings(source_name, {cursor_key: old_value}, True)
            state = "active" if old_value else "off"
            print(f"  Curseur restaure: {source_name} -> {state}")
        except Exception as e:
            print(f"  Restauration {source_name}: {e}")


def detect_obs_webcam(obs_client):
    """
    Detecte la source webcam dans la scene OBS active.
    Retourne un dict { name, x, y, w, h, scene_w, scene_h } avec les coords normalisees,
    ou None si pas de webcam trouvee.
    """
    try:
        scene = obs_client.get_current_program_scene()
        items = obs_client.get_scene_item_list(scene.scene_name)

        # Obtenir la resolution du canvas OBS
        video_settings = obs_client.get_video_settings()
        canvas_w = video_settings.base_width
        canvas_h = video_settings.base_height

        webcam_types = ["dshow_input", "v4l2_input", "av_capture_input",
                        "coreaudio_input_capture", "video_capture_device"]

        for item in items.scene_items:
            source_name = item.get("sourceName", "")
            item_id = item.get("sceneItemId", 0)
            try:
                settings = obs_client.get_input_settings(source_name)
                kind = settings.input_kind

                is_webcam = any(wt in kind for wt in webcam_types)
                # Aussi detecter par nom commun
                name_lower = source_name.lower()
                if not is_webcam:
                    is_webcam = any(kw in name_lower for kw in ["webcam", "camera", "cam", "facecam"])

                if is_webcam:
                    # Obtenir la transform (position, taille) de la source dans la scene
                    transform = obs_client.get_scene_item_transform(scene.scene_name, item_id)
                    t = transform.scene_item_transform

                    pos_x = t.get("positionX", 0)
                    pos_y = t.get("positionY", 0)
                    width = t.get("width", 0)
                    height = t.get("height", 0)
                    # Si width/height sont 0, essayer sourceWidth * scaleX
                    if width == 0 or height == 0:
                        src_w = t.get("sourceWidth", 0)
                        src_h = t.get("sourceHeight", 0)
                        scale_x = t.get("scaleX", 1)
                        scale_y = t.get("scaleY", 1)
                        width = src_w * scale_x
                        height = src_h * scale_y

                    if width > 0 and height > 0:
                        webcam_info = {
                            "name": source_name,
                            "x": pos_x,
                            "y": pos_y,
                            "w": width,
                            "h": height,
                            "nx": round(pos_x / canvas_w, 4),
                            "ny": round(pos_y / canvas_h, 4),
                            "nw": round(width / canvas_w, 4),
                            "nh": round(height / canvas_h, 4),
                            "canvas_w": canvas_w,
                            "canvas_h": canvas_h,
                        }
                        print(f"  Webcam detectee: '{source_name}'")
                        print(f"    Position: ({pos_x:.0f}, {pos_y:.0f}) Taille: {width:.0f}x{height:.0f}")
                        print(f"    Normalise: ({webcam_info['nx']}, {webcam_info['ny']}) {webcam_info['nw']}x{webcam_info['nh']}")
                        return webcam_info
            except Exception:
                continue

        print("  Aucune webcam detectee dans la scene OBS")
        return None
    except Exception as e:
        print(f"  Detection webcam: {e}")
        return None


# --- Logging ---

def log_cursor(region, fps, output_path, obs_client=None, cursor_restored=None, webcam_info=None, auto_start=False):
    """
    region = (x, y, w, h) en pixels reels de la zone de capture
    cursor_restored = liste de (source_name, cursor_key, old_value) pour restaurer le curseur OBS
    webcam_info = dict avec position/taille de la webcam (optionnel)
    """
    screen_w, screen_h = get_screen_size()
    dpi_scale = get_dpi_scale()
    interval = 1.0 / fps

    reg_x, reg_y, reg_w, reg_h = region

    print()
    print(f"  Ecran (reel): {screen_w}x{screen_h}")
    print(f"  DPI scale: {dpi_scale:.0%}")
    print(f"  Zone capture: ({reg_x},{reg_y}) {reg_w}x{reg_h}")
    print(f"  Sampling: {fps} fps")
    print()

    # Demarrer OBS
    if obs_client:
        print("  Demarrage OBS...")
        try:
            obs_client.start_record()
            time.sleep(0.5)
            print("  >>> OBS ENREGISTRE! <<<\n")
        except Exception as e:
            print(f"  Erreur: {e}")
            obs_client = None

    if not obs_client and not auto_start:
        print("  >>> Appuie ENTER pour commencer <<<")
        input()

    print("  LOGGING... Ctrl+C pour arreter\n")

    events = []
    metadata = {
        "version": 4,
        "screen_width": screen_w,
        "screen_height": screen_h,
        "dpi_scale": dpi_scale,
        "capture_region": {"x": reg_x, "y": reg_y, "w": reg_w, "h": reg_h},
        "fps": fps,
        "start_time": time.time(),
        "start_datetime": datetime.now().isoformat(),
    }
    if webcam_info:
        metadata["webcam"] = webcam_info

    was_clicking = False
    was_holding = False
    prev_nx, prev_ny = 0.5, 0.5
    start_time = time.time()
    sample_count = 0

    try:
        while True:
            now = time.time()
            elapsed = now - start_time

            abs_x, abs_y = get_cursor_pos()
            clicking = is_clicking()
            holding = is_clicking()  # button held down

            # Coordonnees relatives a la zone de capture
            rel_x = abs_x - reg_x
            rel_y = abs_y - reg_y

            # Normaliser 0-1
            norm_x = max(0.0, min(1.0, rel_x / max(reg_w, 1)))
            norm_y = max(0.0, min(1.0, rel_y / max(reg_h, 1)))

            in_region = 0 <= rel_x <= reg_w and 0 <= rel_y <= reg_h

            # Calculer la vitesse du curseur (distance normalisee par frame)
            dx = norm_x - prev_nx
            dy = norm_y - prev_ny
            speed = round((dx*dx + dy*dy) ** 0.5, 6)

            event = {
                "t": round(elapsed, 4),
                "nx": round(norm_x, 5),
                "ny": round(norm_y, 5),
            }

            # On n'enregistre speed que si non-zero (save space)
            if speed > 0.001:
                event["spd"] = speed

            if clicking and not was_clicking:
                event["click"] = True
                if in_region:
                    event["in"] = True

            # Drag: bouton maintenu + mouvement
            if holding and was_holding and speed > 0.002:
                event["drag"] = True

            # Release du bouton
            if was_holding and not holding:
                event["release"] = True

            was_clicking = clicking
            was_holding = holding
            prev_nx, prev_ny = norm_x, norm_y
            events.append(event)
            sample_count += 1

            if sample_count % (fps * 5) == 0:
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                zone = "OK" if in_region else "HORS"
                print(f"  {mins:02d}:{secs:02d} | ({norm_x:.2f}, {norm_y:.2f}) | {zone}")

            # Check for stop signal file (utilise par le serveur pour arreter proprement)
            stop_file = os.path.join(os.path.dirname(os.path.abspath(output_path)), ".autozoom_stop")
            if os.path.exists(stop_file):
                print("\n  Signal d'arret recu (stop file)")
                try:
                    os.remove(stop_file)
                except:
                    pass
                break

            sleep_time = interval - (time.time() - now)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass

    # Arreter OBS + restaurer curseur
    if obs_client:
        print("\n  Arret OBS...")
        try:
            result = obs_client.stop_record()
            op = getattr(result, 'output_path', None)
            if op:
                print(f"  Video: {op}")
                metadata["video_file"] = str(op).replace("\\", "/")
        except:
            pass

        # Restaurer le curseur OBS
        if cursor_restored:
            print("  Restauration du curseur OBS...")
            restore_obs_cursor(obs_client, cursor_restored)


    end_time = time.time()
    duration = end_time - start_time
    metadata["end_time"] = end_time
    metadata["duration"] = round(duration, 2)
    metadata["total_samples"] = len(events)

    with open(output_path, "w") as f:
        json.dump({"version": 5, "metadata": metadata, "events": events}, f)

    clicks_in = sum(1 for e in events if e.get("click") and e.get("in"))
    clicks_out = sum(1 for e in events if e.get("click") and not e.get("in"))

    print()
    print("=" * 50)
    print(f"  {len(events)} samples, {duration:.1f}s")
    print(f"  Clics dans zone: {clicks_in}")
    if clicks_out:
        print(f"  Clics hors zone: {clicks_out}")
    print(f"  Fichier: {output_path}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="AutoZoom Cursor Logger v4")
    parser.add_argument("--obs", action="store_true")
    parser.add_argument("--obs-port", type=int, default=4455)
    parser.add_argument("--obs-password", default="")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--no-calibration", action="store_true",
                        help="Skip la calibration (si tu sais que ca marche)")
    parser.add_argument("--hide-cursor", action="store_true", default=True,
                        help="Tente de desactiver le curseur dans OBS (par defaut: oui, pas garanti sur toutes les configs)")
    parser.add_argument("--keep-cursor", action="store_true",
                        help="Garder le curseur OBS visible (ne pas tenter de le cacher)")
    parser.add_argument("--auto-start", action="store_true",
                        help="Demarre immediatement sans attendre Enter (utilise par le serveur)")
    parser.add_argument("--region", default=None,
                        help="Zone de capture explicite: x,y,w,h (ex: 3840,0,1920,1080)")
    args = parser.parse_args()

    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"cursor_log_{timestamp}.json"

    dpi = get_dpi_scale()
    sw, sh = get_screen_size()

    print("=" * 50)
    print("  AUTOZOOM v4 - Cursor Logger")
    print("=" * 50)
    print(f"\n  Ecran: {sw}x{sh} @ {dpi:.0%} DPI")

    obs_client = None
    capture_hwnd = None
    cursor_restored = None
    webcam_info = None

    if args.region:
        # Region explicite passee par le serveur (x,y,w,h)
        parts = [int(x.strip()) for x in args.region.split(",")]
        region = (parts[0], parts[1], parts[2], parts[3])
        print(f"  Mode: region explicite ({parts[0]},{parts[1]}) {parts[2]}x{parts[3]}")

    elif args.fullscreen:
        region = (0, 0, sw, sh)
        print("  Mode: plein ecran")

    elif args.obs:
        print("\n  Connexion OBS...")
        obs_client = connect_obs(args.obs_port, args.obs_password)

        if obs_client:
            detected = detect_obs_capture_window(obs_client)
            if detected == "ask":
                print("\n  Detection auto impossible.")
                capture_hwnd = wait_for_click_on_window()
                print(f"  Fenetre: {get_window_title(capture_hwnd)}")
            elif detected is None:
                capture_hwnd = None
            else:
                capture_hwnd = detected

            # Desactiver le curseur dans OBS (marche sur certaines configs)
            if not args.keep_cursor:
                print("\n  Desactivation du curseur OBS...")
                cursor_restored = disable_obs_cursor(obs_client)
                if cursor_restored:
                    print(f"  {len(cursor_restored)} source(s) OBS modifiee(s)")
                else:
                    print("  Aucune source OBS modifiee.")
                    print("  Tu peux desactiver le curseur manuellement dans OBS:")
                    print("    Clic droit sur ta source > Proprietes > decocher 'Capture Cursor'")
                    print()
                    input("  Appuie Enter quand c'est fait...")

        # Detecter la webcam dans la scene OBS
        print("\n  Detection webcam...")
        webcam_info = detect_obs_webcam(obs_client)

        if capture_hwnd:
            region = get_client_rect_screen(capture_hwnd)
        else:
            region = (0, 0, sw, sh)

    else:
        print("\n  Mode standalone.")
        print("  On doit savoir quelle fenetre OBS capture.\n")
        capture_hwnd = wait_for_click_on_window()
        print(f"\n  Fenetre: {get_window_title(capture_hwnd)}")
        region = get_client_rect_screen(capture_hwnd)

    # Calibration
    if not args.no_calibration and not args.fullscreen:
        cal_region = run_calibration(capture_hwnd)
        if cal_region:
            region = cal_region

    log_cursor(region, args.fps, args.output, obs_client, cursor_restored=cursor_restored, webcam_info=webcam_info, auto_start=args.auto_start)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n  === ERREUR ===")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Seulement demander Enter si on est dans un terminal interactif
        if sys.stdin.isatty():
            print(f"\n  Appuie Enter pour fermer...")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
