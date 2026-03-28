"""
Recastr - Video Renderer
Prend ta video OBS + le cursor log et genere une version avec zooms automatiques.

v3:
  - Compatible avec le logger v3 (detection fenetre auto)
  - Preview HTML visuel: ouvre dans ton browser pour voir les zooms
  - Meilleur support des clics hors zone

Usage:
  python auto_zoom.py video.mp4 cursor_log.json
  python auto_zoom.py video.mp4 cursor_log.json --preview
  python auto_zoom.py video.mp4 cursor_log.json --offset -0.5
"""

import json
import subprocess
import sys
import math
import argparse
import shutil
import os
import webbrowser
import threading
from pathlib import Path


def transcribe_video(video_path, model_name="base", language=None):
    """
    Transcrit l'audio d'une video avec Whisper.
    Retourne une liste de segments: [{ start, end, text, words: [{ word, start, end }] }]
    """
    try:
        import whisper
    except ImportError:
        print("  ERREUR: whisper requis. pip install openai-whisper")
        print("  (Aussi besoin de ffmpeg installe)")
        return None

    print(f"  Chargement du modele Whisper ({model_name})...")
    model = whisper.load_model(model_name)

    print(f"  Transcription en cours (ca peut prendre un moment)...")
    opts = {"word_timestamps": True}
    if language:
        opts["language"] = language

    result = model.transcribe(str(video_path), **opts)

    segments = []
    for seg in result.get("segments", []):
        words = []
        for w in seg.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            })
        segments.append({
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"].strip(),
            "words": words,
        })

    detected_lang = result.get("language", "?")
    total_words = sum(len(s["words"]) for s in segments)
    print(f"  Transcription: {len(segments)} segments, {total_words} mots (langue: {detected_lang})")
    return segments


def load_cursor_log(log_path):
    with open(log_path, "r") as f:
        data = json.load(f)

    metadata = data["metadata"]
    events = data["events"]
    version = data.get("version", 1)

    # Convertir v1 (coords absolues) en normalisees
    if version == 1:
        sw = metadata["screen_width"]
        sh = metadata["screen_height"]
        for ev in events:
            if "nx" not in ev:
                ev["nx"] = ev.get("x", 0) / max(sw, 1)
                ev["ny"] = ev.get("y", 0) / max(sh, 1)

    return metadata, events


def get_video_info(video_path):
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERREUR: ffprobe echoue. FFmpeg installe?")
        sys.exit(1)

    info = json.loads(result.stdout)
    for s in info.get("streams", []):
        if s["codec_type"] == "video":
            w = int(s["width"])
            h = int(s["height"])
            d = float(info.get("format", {}).get("duration", 0))
            if d == 0:
                d = float(s.get("duration", 0))
            fps_str = s.get("r_frame_rate", "30/1")
            n, dn = fps_str.split("/")
            fps = float(n) / float(dn)
            return w, h, d, fps

    print("  ERREUR: Pas de video stream.")
    sys.exit(1)


def detect_zoom_events(events, config):
    """
    Detection intelligente v2.
    Strategies:
      1. Clics (+ clusters de clics rapprochés)
      2. Arrivees rapides (curseur bouge vite puis s'arrete = tu pointes qqch)
      3. Pauses avec interaction (curseur immobile + zone active)
      4. Ignore les drags (selection de texte, scroll bars, etc.)
      5. Ignore les 3 dernieres secondes
    """
    if not events:
        return []

    zoom_events = []
    max_time = events[-1]["t"] - 3.0

    # ============================================================
    # STRATEGIE 1: Clics + clusters de clics
    # Un clic seul = zoom normal
    # Plusieurs clics rapprochés dans la meme zone = zoom plus long
    # ============================================================
    click_events = [e for e in events if e.get("click") and e.get("in") is True
                    and e["t"] < max_time]

    # Grouper les clics en clusters (< 2s et < 5% d'ecart)
    clusters = []
    current_cluster = []

    for ev in click_events:
        if current_cluster:
            last = current_cluster[-1]
            dt = ev["t"] - last["t"]
            dist = math.sqrt((ev["nx"] - last["nx"])**2 + (ev["ny"] - last["ny"])**2)
            if dt < 2.0 and dist < 0.08:
                current_cluster.append(ev)
                continue

        if current_cluster:
            clusters.append(current_cluster)
        current_cluster = [ev]

    if current_cluster:
        clusters.append(current_cluster)

    for cluster in clusters:
        # Centre du cluster
        avg_nx = sum(e["nx"] for e in cluster) / len(cluster)
        avg_ny = sum(e["ny"] for e in cluster) / len(cluster)
        start_t = cluster[0]["t"]

        if len(cluster) == 1:
            # Clic simple
            zoom_events.append({
                "time": start_t,
                "nx": avg_nx,
                "ny": avg_ny,
                "zoom": config["zoom_click"],
                "hold": config["hold_click"],
                "type": "click",
                "ease_in": 0.2,
                "ease_out": 0.35,
            })
        else:
            # Cluster de clics = interaction importante, zoom plus long
            cluster_duration = cluster[-1]["t"] - cluster[0]["t"]
            zoom_events.append({
                "time": start_t,
                "nx": avg_nx,
                "ny": avg_ny,
                "zoom": min(config["zoom_click"] + 0.3, 3.5),
                "hold": min(cluster_duration + 1.0, config["hold_click"] * 2),
                "type": "click",
                "ease_in": 0.2,
                "ease_out": 0.4,
            })

    # ============================================================
    # STRATEGIE 2: Arrivees rapides
    # Le curseur bouge vite puis s'arrete brusquement = tu pointes
    # quelque chose d'important. Zoom doux sur la destination.
    # ============================================================
    SPEED_THRESHOLD = 0.015     # vitesse minimum pour "rapide"
    SLOW_THRESHOLD = 0.003      # vitesse pour "arrete"
    ARRIVAL_WINDOW = 8          # frames de lenteur apres le mouvement rapide

    was_fast = False
    fast_end_t = 0
    slow_frames = 0

    for i, ev in enumerate(events):
        if ev["t"] >= max_time:
            break

        speed = ev.get("spd", 0)

        if speed > SPEED_THRESHOLD:
            was_fast = True
            fast_end_t = ev["t"]
            slow_frames = 0
        elif was_fast and speed < SLOW_THRESHOLD:
            slow_frames += 1
            if slow_frames >= ARRIVAL_WINDOW:
                # Le curseur s'est arrete apres un mouvement rapide
                # Verifier qu'il n'y a pas deja un clic nearby
                has_nearby = any(
                    abs(z["time"] - ev["t"]) < 1.0
                    for z in zoom_events
                )
                # Ignorer si c'etait un drag
                is_drag = any(
                    events[j].get("drag")
                    for j in range(max(0, i - ARRIVAL_WINDOW * 2), i)
                )
                if not has_nearby and not is_drag:
                    zoom_events.append({
                        "time": ev["t"] - 0.1,
                        "nx": ev["nx"],
                        "ny": ev["ny"],
                        "zoom": config.get("zoom_arrive", 1.6),
                        "hold": 1.5,
                        "type": "arrive",
                        "ease_in": 0.3,
                        "ease_out": 0.4,
                    })
                was_fast = False
                slow_frames = 0
        else:
            if speed > SLOW_THRESHOLD:
                slow_frames = 0

    # ============================================================
    # STRATEGIE 3: Pauses (curseur immobile longtemps)
    # Seulement si pas de clic ou arrivee deja detecte nearby
    # ============================================================
    STILL_THRESHOLD = 0.012
    STILL_MIN = 1.5

    still_start = None
    still_nx, still_ny = 0, 0
    still_n = 0

    for ev in events:
        if ev["t"] >= max_time:
            break
        if ev.get("drag"):
            still_start = None
            continue

        nx, ny = ev["nx"], ev["ny"]

        if still_start is None:
            still_start = ev["t"]
            still_nx, still_ny = nx, ny
            still_n = 1
            continue

        dist = math.sqrt((nx - still_nx)**2 + (ny - still_ny)**2)

        if dist > STILL_THRESHOLD:
            dur = ev["t"] - still_start
            if dur >= STILL_MIN:
                has_nearby = any(
                    abs(z["time"] - still_start) < 1.2
                    for z in zoom_events
                )
                if not has_nearby:
                    zoom_events.append({
                        "time": still_start + 0.2,
                        "nx": still_nx,
                        "ny": still_ny,
                        "zoom": config["zoom_still"],
                        "hold": min(dur - 0.5, config["hold_still"]),
                        "type": "still",
                        "ease_in": 0.4,
                        "ease_out": 0.4,
                    })
            still_start = ev["t"]
            still_nx, still_ny = nx, ny
            still_n = 1
        else:
            still_n += 1
            still_nx += (nx - still_nx) / still_n
            still_ny += (ny - still_ny) / still_n

    # ============================================================
    # MERGE: trier par temps, fusionner les chevauchements
    # Priorite: click > arrive > still
    # ============================================================
    TYPE_PRIORITY = {"click": 3, "arrive": 2, "still": 1}

    zoom_events.sort(key=lambda e: e["time"])

    merged = []
    for ze in zoom_events:
        if merged:
            prev = merged[-1]
            prev_end = prev["time"] + prev["ease_in"] + prev["hold"] + prev["ease_out"]
            if ze["time"] < prev_end + 0.5:
                # Garder celui avec la priorite la plus haute
                if TYPE_PRIORITY.get(ze["type"], 0) > TYPE_PRIORITY.get(prev["type"], 0):
                    merged[-1] = ze
                elif TYPE_PRIORITY.get(ze["type"], 0) == TYPE_PRIORITY.get(prev["type"], 0):
                    if ze["zoom"] > prev["zoom"]:
                        merged[-1] = ze
                continue
        merged.append(ze)

    return merged


def ease_in_out_cubic(t):
    t = max(0, min(1, t))
    return 4*t*t*t if t < 0.5 else 1 - pow(-2*t + 2, 3) / 2


def ease_out_back(t, overshoot=0.06):
    """Ease-out avec un leger overshoot — feel organique."""
    t = max(0, min(1, t))
    c1 = 1 + overshoot * 10
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_in_smooth(t):
    """Ease-in doux, plus lent que cubic au debut."""
    t = max(0, min(1, t))
    return t * t * (3 - 2 * t)  # smoothstep


def ease_zoom_in(t):
    """Courbe pour le zoom-in: demarre lent, accelere, leger overshoot."""
    t = max(0, min(1, t))
    # Combine smoothstep + overshoot
    base = t * t * (3 - 2 * t)
    overshoot = math.sin(t * math.pi) * 0.04  # bump subtil au milieu
    return min(1.0, base + overshoot)


def ease_zoom_out(t):
    """Courbe pour le zoom-out: depart rapide, fin tres douce."""
    t = max(0, min(1, t))
    # Deceleration progressive
    return 1 - pow(1 - t, 2.5)


def lerp(a, b, t):
    return a + (b - a) * t


def smooth_damp(current, target, velocity, smooth_time, dt):
    """
    Spring-based smooth interpolation (similar to Unity's SmoothDamp).
    Returns (new_value, new_velocity).
    """
    smooth_time = max(0.01, smooth_time)
    omega = 2.0 / smooth_time
    x = omega * dt
    exp_factor = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = current - target
    temp = (velocity + omega * change) * dt
    new_velocity = (velocity - omega * temp) * exp_factor
    new_value = target + (change + temp) * exp_factor
    return new_value, new_velocity


def compute_frame_data(zoom_events, video_duration, output_fps):
    """
    Pre-calcule zoom + position par frame avec:
    - Courbes d'easing organiques (overshoot subtil)
    - Smooth pan (la camera glisse vers la cible)
    - Interpolation entre zooms consecutifs
    """
    total = int(video_duration * output_fps)
    dt = 1.0 / output_fps

    # Phase 1: calculer le zoom "brut" (target) pour chaque frame
    raw_frames = []
    for i in range(total):
        t = i / output_fps
        zoom = 1.0
        cx, cy = 0.5, 0.5
        active = False

        for ze in zoom_events:
            start = ze["time"]
            ei = ze["ease_in"]
            hold = ze["hold"]
            eo = ze["ease_out"]
            end = start + ei + hold + eo

            if t < start or t > end:
                continue

            lt = t - start
            if lt < ei:
                # Zoom in: courbe avec overshoot
                progress = lt / ei
                f = ease_zoom_in(progress)
            elif lt < ei + hold:
                # Hold: valeur stable a 1.0
                f = 1.0
            else:
                # Zoom out: deceleration douce
                progress = (lt - ei - hold) / eo
                f = 1.0 - ease_zoom_out(progress)

            cz = 1.0 + (ze["zoom"] - 1.0) * f
            if cz > zoom:
                zoom = cz
                cx = ze["nx"]
                cy = ze["ny"]
                active = True

        raw_frames.append((zoom, cx, cy, active))

    # Phase 2: smooth pan — la position de la camera glisse vers la cible
    # au lieu de teleporter instantanement
    SMOOTH_TIME = 0.15  # secondes de lissage pour la position
    PAN_SMOOTH = 0.12   # lissage du pan quand on est en zoom

    smooth_cx, smooth_cy = 0.5, 0.5
    vel_cx, vel_cy = 0.0, 0.0
    smooth_zoom = 1.0
    vel_zoom = 0.0

    frames = []
    for i, (target_zoom, target_cx, target_cy, active) in enumerate(raw_frames):
        if active and target_zoom > 1.05:
            # En zoom: smooth damp vers la cible
            smooth_cx, vel_cx = smooth_damp(smooth_cx, target_cx, vel_cx, PAN_SMOOTH, dt)
            smooth_cy, vel_cy = smooth_damp(smooth_cy, target_cy, vel_cy, PAN_SMOOTH, dt)
            smooth_zoom, vel_zoom = smooth_damp(smooth_zoom, target_zoom, vel_zoom, SMOOTH_TIME, dt)
        else:
            # Hors zoom: retour rapide a 1.0
            smooth_zoom, vel_zoom = smooth_damp(smooth_zoom, 1.0, vel_zoom, SMOOTH_TIME * 1.5, dt)
            # Position: relax doucement vers le centre
            smooth_cx, vel_cx = smooth_damp(smooth_cx, 0.5, vel_cx, 0.4, dt)
            smooth_cy, vel_cy = smooth_damp(smooth_cy, 0.5, vel_cy, 0.4, dt)

        # Clamp zoom a minimum 1.0
        final_zoom = max(1.0, smooth_zoom)
        frames.append((final_zoom, smooth_cx, smooth_cy))

    return frames


# --- PREVIEW HTML ---

def generate_editor_html(video_path, zoom_events, video_w, video_h, video_duration, output_html, output_json, cursor_events=None, caption_segments=None, webcam_info=None, webcam_file_url=None):
    """
    Genere un editeur HTML interactif avec preview live du zoom.
    cursor_events: list d'events du cursor_log (optionnel, pour preview du curseur)
    caption_segments: list de segments Whisper (optionnel, pour captions)
    webcam_info: dict avec position webcam du cursor log (optionnel, legacy)
    webcam_file_url: URL du fichier webcam separe servi par le serveur HTTP (optionnel)
    """
    # video_path peut etre une URL HTTP (serveur local) ou un chemin fichier
    if video_path.startswith("http"):
        video_abs = video_path
    else:
        from urllib.parse import quote
        video_abs = "file:///" + quote(os.path.abspath(video_path).replace("\\", "/"), safe="/:")
    json_abs = os.path.abspath(output_json).replace("\\", "/")

    # Downsample cursor events to ~10fps for embedding (lighter)
    cursor_track_json = "[]"
    if cursor_events:
        sampled = []
        last_t = -1
        for ev in cursor_events:
            if ev["t"] - last_t >= 0.1:
                sampled.append({
                    "t": round(ev["t"], 2),
                    "nx": round(ev["nx"], 4),
                    "ny": round(ev["ny"], 4),
                    "c": 1 if ev.get("click") else 0,
                })
                last_t = ev["t"]
        cursor_track_json = json.dumps(sampled)

    # Caption segments for editor
    caption_segments_json = json.dumps(caption_segments or [])

    # Webcam info for editor
    webcam_info_json = json.dumps(webcam_info or {})
    webcam_file_url_json = json.dumps(webcam_file_url or "")

    events_json = json.dumps([{
        "id": i,
        "time": z["time"],
        "nx": z["nx"],
        "ny": z["ny"],
        "zoom": z["zoom"],
        "hold": z["hold"],
        "ease_in": z["ease_in"],
        "ease_out": z["ease_out"],
        "type": z["type"],
        "enabled": True,
    } for i, z in enumerate(zoom_events)])

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Recastr Editor</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #1a1a2e; color: #eee; font-family: system-ui, -apple-system, sans-serif; }}

.layout {{ display: grid; grid-template-columns: 1fr 340px; height: 100vh; }}

.main {{ padding: 16px; overflow: auto; }}
.sidebar {{ background: #16213e; border-left: 1px solid #2a2a4a; overflow-y: auto; padding: 0; display: flex; flex-direction: column; }}

h1 {{ color: #e94560; font-size: 1.3em; margin-bottom: 4px; }}
.subtitle {{ color: #666; font-size: 0.82em; margin-bottom: 12px; }}

/* Video views */
.views {{ display: flex; gap: 12px; align-items: flex-start; }}
.view-col {{ flex: 1; min-width: 0; }}
.view-label {{
    font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.08em;
    color: #666; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;
}}
.view-label .badge {{
    background: #e94560; color: #fff; padding: 1px 8px; border-radius: 10px;
    font-size: 0.9em;
}}

.video-wrap {{ position: relative; display: block; max-width: 100%; }}
video {{ display: block; width: 100%; background: #000; border-radius: 6px; }}
.overlay {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }}

canvas#previewCanvas {{
    display: block; width: 100%; background: #000; border-radius: 6px;
    border: 2px solid #e94560;
}}

.zoom-rect {{
    position: absolute; border: 3px solid #e94560; border-radius: 4px;
    background: rgba(233, 69, 96, 0.1);
    pointer-events: auto; cursor: move;
}}
.zoom-rect:hover {{ background: rgba(233, 69, 96, 0.25); }}
.zoom-rect.still {{ border-color: #0f3460; border-style: dashed; background: rgba(15, 52, 96, 0.1); }}
.zoom-rect.still:hover {{ background: rgba(15, 52, 96, 0.25); }}
.zoom-rect.dragging {{ border-width: 4px; filter: brightness(1.3); }}

/* Corner resize handles on zoom rects */
.zoom-resize-handle {{
    position: absolute; width: 12px; height: 12px; background: #fff;
    border: 2px solid #e94560; border-radius: 2px; pointer-events: auto; z-index: 5;
}}
.zoom-resize-handle.tl {{ top: -6px; left: -6px; cursor: nw-resize; }}
.zoom-resize-handle.tr {{ top: -6px; right: -6px; cursor: ne-resize; }}
.zoom-resize-handle.bl {{ bottom: -6px; left: -6px; cursor: sw-resize; }}
.zoom-resize-handle.br {{ bottom: -6px; right: -6px; cursor: se-resize; }}

.zoom-dot {{
    position: absolute; width: 14px; height: 14px; border-radius: 50%;
    background: #e94560; transform: translate(-50%, -50%);
    pointer-events: auto; cursor: grab; z-index: 4;
    border: 2px solid #fff; box-shadow: 0 0 6px rgba(0,0,0,0.5);
}}
.zoom-dot:hover {{ transform: translate(-50%, -50%) scale(1.3); }}
.zoom-dot.still {{ background: #0f3460; }}
.zoom-dot.dragging {{ cursor: grabbing; transform: translate(-50%, -50%) scale(1.4); }}

.timeline {{
    width: 100%; height: 54px; background: #0f3460; margin-top: 10px;
    border-radius: 6px; position: relative; cursor: pointer; overflow: hidden;
    user-select: none;
}}
.tl-marker {{
    position: absolute; top: 4px; height: calc(100% - 8px); min-width: 6px; border-radius: 3px;
    cursor: grab; transition: filter 0.1s; z-index: 2;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.65em; color: rgba(255,255,255,0.7); overflow: hidden; white-space: nowrap;
}}
.tl-marker.click {{ background: #e94560; }}
.tl-marker.still {{ background: #533483; }}
.tl-marker.arrive {{ background: #0f9b58; }}
.tl-marker.disabled {{ background: #333; opacity: 0.3; }}
.tl-marker:hover {{ filter: brightness(1.3); z-index: 3; }}
.tl-marker.dragging {{ cursor: grabbing; filter: brightness(1.4); z-index: 10; }}

.tl-handle {{
    position: absolute; top: 0; width: 8px; height: 100%; cursor: ew-resize; z-index: 4;
}}
.tl-handle.left {{ left: -2px; }}
.tl-handle.right {{ right: -2px; }}
.tl-handle:hover, .tl-handle.active {{
    background: rgba(255,255,255,0.3); border-radius: 2px;
}}

.tl-playhead {{ position: absolute; top: 0; width: 2px; height: 100%; background: #fff; z-index: 15; pointer-events: none; }}
.tl-time-labels {{ position: absolute; bottom: 0; left: 0; right: 0; height: 14px; pointer-events: none; }}
.tl-time-label {{ position: absolute; bottom: 1px; color: rgba(255,255,255,0.25); font-size: 0.6em; transform: translateX(-50%); }}

.status-bar {{
    margin-top: 8px; display: flex; gap: 16px; align-items: center; font-size: 0.8em; color: #888;
}}
.status-bar span {{ color: #ccc; }}

/* Sidebar */
.sb-header {{
    padding: 14px 16px; border-bottom: 1px solid #2a2a4a;
    display: flex; justify-content: space-between; align-items: center;
    flex-shrink: 0;
}}
.sb-header h2 {{ font-size: 1.1em; color: #e94560; }}
.sb-count {{ color: #666; font-size: 0.85em; }}

.zoom-list {{ list-style: none; overflow-y: auto; flex: 1; }}

.zoom-item {{
    padding: 10px 16px; border-bottom: 1px solid #1a1a2e;
    cursor: pointer; transition: background 0.15s;
}}
.zoom-item:hover {{ background: #1a2744; }}
.zoom-item.active {{ background: #1a2744; border-left: 3px solid #e94560; }}
.zoom-item.disabled {{ opacity: 0.4; }}

.zi-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }}
.zi-type {{ font-size: 0.72em; text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 8px; border-radius: 10px; }}
.zi-type.click {{ background: #e94560; color: #fff; }}
.zi-type.still {{ background: #533483; color: #fff; }}
.zi-time {{ color: #888; font-size: 0.82em; font-variant-numeric: tabular-nums; }}

.zi-controls {{ display: flex; gap: 6px; align-items: center; margin-top: 5px; }}
.zi-controls label {{ color: #666; font-size: 0.75em; min-width: 38px; }}
.zi-controls input[type=range] {{ flex: 1; accent-color: #e94560; height: 16px; }}
.zi-controls .val {{ color: #ccc; font-size: 0.8em; min-width: 35px; text-align: right; }}

.zi-actions {{ display: flex; gap: 6px; margin-top: 6px; }}

.btn {{
    border: none; border-radius: 4px; padding: 4px 10px; font-size: 0.75em;
    cursor: pointer; transition: background 0.15s;
}}
.btn-delete {{ background: #e94560; color: #fff; }}
.btn-delete:hover {{ background: #ff6b81; }}
.btn-toggle {{ background: #2a2a4a; color: #ccc; }}
.btn-toggle:hover {{ background: #3a3a5a; }}
.btn-export {{
    background: #00b894; color: #fff; padding: 10px 20px; font-size: 0.95em;
    border: none; border-radius: 6px; cursor: pointer; width: 100%;
}}
.btn-export:hover {{ background: #00d9a7; }}

.export-section {{ padding: 14px 16px; border-top: 1px solid #2a2a4a; flex-shrink: 0; }}
.export-note {{ color: #666; font-size: 0.75em; margin-top: 6px; text-align: center; }}

.toast {{
    position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
    background: #00b894; color: #fff; padding: 12px 24px; border-radius: 8px;
    font-size: 0.9em; display: none; z-index: 999; box-shadow: 0 4px 20px rgba(0,0,0,0.4);
}}

.shortcut-hint {{
    font-size: 0.72em; color: #444; margin-top: 6px; text-align: center;
}}

/* Batch controls */
.batch-panel {{
    padding: 12px 16px; border-bottom: 1px solid #2a2a4a; flex-shrink: 0;
    background: #1a2744;
}}
.batch-panel summary {{
    cursor: pointer; color: #888; font-size: 0.8em; user-select: none;
}}
.batch-panel summary:hover {{ color: #ccc; }}
.batch-panel[open] summary {{ color: #e94560; margin-bottom: 10px; }}

.batch-row {{
    display: flex; gap: 6px; align-items: center; margin-top: 8px;
}}
.batch-row label {{ color: #888; font-size: 0.75em; min-width: 70px; }}
.batch-row input[type=range] {{ flex: 1; accent-color: #e94560; height: 16px; }}
.batch-row .val {{ color: #ccc; font-size: 0.8em; min-width: 40px; text-align: right; }}

.batch-buttons {{
    display: flex; gap: 4px; flex-wrap: wrap; margin-top: 8px;
}}
.batch-btn {{
    border: 1px solid #333; background: #16213e; color: #aaa; padding: 3px 8px;
    font-size: 0.7em; border-radius: 3px; cursor: pointer;
}}
.batch-btn:hover {{ background: #2a2a4a; color: #fff; }}
.batch-btn.danger {{ border-color: #e94560; color: #e94560; }}
.batch-btn.danger:hover {{ background: #e94560; color: #fff; }}

/* Add zoom button */
.add-zoom-hint {{
    font-size: 0.7em; color: #444; text-align: center; padding: 4px;
    border-bottom: 1px solid #1a1a2e;
}}

/* Speed control */
.speed-control {{
    display: flex; gap: 4px; align-items: center; margin-left: auto;
}}
.speed-btn {{
    background: none; border: 1px solid #333; color: #888; padding: 2px 6px;
    font-size: 0.75em; border-radius: 3px; cursor: pointer;
}}
.speed-btn:hover, .speed-btn.active {{ border-color: #e94560; color: #e94560; }}

/* Background toggle */
.bg-panel {{
    padding: 10px 16px; border-bottom: 1px solid #2a2a4a; flex-shrink: 0;
}}
.bg-panel summary {{
    cursor: pointer; color: #888; font-size: 0.8em; user-select: none;
}}
.bg-panel summary:hover {{ color: #ccc; }}
.bg-panel[open] summary {{ color: #00b894; margin-bottom: 8px; }}
.bg-toggle {{
    display: flex; gap: 6px; align-items: center; margin-bottom: 6px;
}}
.bg-toggle label {{ color: #aaa; font-size: 0.8em; }}
.bg-toggle input {{ accent-color: #00b894; }}
.bg-style-btns {{
    display: flex; gap: 4px; margin-bottom: 8px;
}}
.bg-style-btn {{
    border: 1px solid #333; background: #16213e; color: #aaa; padding: 3px 10px;
    font-size: 0.72em; border-radius: 3px; cursor: pointer;
}}
.bg-style-btn:hover {{ background: #2a2a4a; color: #fff; }}
.bg-style-btn.active {{ border-color: #00b894; color: #00b894; background: rgba(0,184,148,0.1); }}
.bg-row {{
    display: flex; gap: 6px; align-items: center; margin-top: 6px;
}}
.bg-row label {{ color: #888; font-size: 0.72em; min-width: 55px; }}
.bg-row input[type=range] {{ flex: 1; accent-color: #00b894; height: 14px; }}
.bg-row .val {{ color: #ccc; font-size: 0.75em; min-width: 35px; text-align: right; }}

/* Caption panel */
.caption-panel {{
    padding: 10px 16px; border-bottom: 1px solid #2a2a4a; flex-shrink: 0;
}}
.caption-panel summary {{
    cursor: pointer; color: #888; font-size: 0.8em; user-select: none;
}}
.caption-panel summary:hover {{ color: #ccc; }}
.caption-panel[open] summary {{ color: #f0c040; margin-bottom: 8px; }}
.caption-toggle {{
    display: flex; gap: 6px; align-items: center; margin-bottom: 6px;
}}
.caption-toggle label {{ color: #aaa; font-size: 0.8em; }}
.caption-toggle input {{ accent-color: #f0c040; }}
.caption-style-btns {{
    display: flex; gap: 4px; margin-bottom: 8px;
}}
.caption-style-btn {{
    border: 1px solid #333; background: #16213e; color: #aaa; padding: 3px 10px;
    font-size: 0.72em; border-radius: 3px; cursor: pointer;
}}
.caption-style-btn:hover {{ background: #2a2a4a; color: #fff; }}
.caption-style-btn.active {{ border-color: #f0c040; color: #f0c040; background: rgba(240,192,64,0.1); }}
.caption-segments {{
    max-height: 200px; overflow-y: auto; margin-top: 8px;
}}
.caption-seg {{
    padding: 4px 6px; font-size: 0.72em; border-bottom: 1px solid #1a1a2e;
    cursor: pointer; transition: background 0.15s;
}}
.caption-seg:hover {{ background: rgba(240,192,64,0.1); }}
.caption-seg.active {{ background: rgba(240,192,64,0.15); border-left: 2px solid #f0c040; }}
.caption-seg-time {{ color: #666; font-size: 0.9em; }}
.caption-seg-text {{
    color: #ccc; margin-top: 2px;
}}
.caption-seg-text[contenteditable=true]:focus {{
    outline: 1px solid #f0c040; background: rgba(240,192,64,0.05); border-radius: 2px;
    color: #fff;
}}
.caption-hint {{ color: #666; font-size: 0.7em; margin-top: 4px; font-style: italic; }}

/* Webcam panel */
.webcam-panel {{
    padding: 10px 16px; border-bottom: 1px solid #2a2a4a; flex-shrink: 0;
}}
.webcam-panel summary {{
    cursor: pointer; color: #888; font-size: 0.8em; user-select: none;
}}
.webcam-panel summary:hover {{ color: #ccc; }}
.webcam-panel[open] summary {{ color: #6c5ce7; margin-bottom: 8px; }}
.webcam-toggle {{
    display: flex; gap: 6px; align-items: center; margin-bottom: 6px;
}}
.webcam-toggle label {{ color: #aaa; font-size: 0.8em; }}
.webcam-toggle input {{ accent-color: #6c5ce7; }}
.webcam-row {{
    display: flex; gap: 6px; align-items: center; margin-top: 6px;
}}
.webcam-row label {{ color: #888; font-size: 0.72em; min-width: 55px; }}
.webcam-row input[type=range] {{ flex: 1; accent-color: #6c5ce7; height: 14px; }}
.webcam-row .val {{ color: #ccc; font-size: 0.75em; min-width: 35px; text-align: right; }}
.webcam-style-btns {{
    display: flex; gap: 4px; margin-bottom: 8px;
}}
.webcam-style-btn {{
    border: 1px solid #333; background: #16213e; color: #aaa; padding: 3px 10px;
    font-size: 0.72em; border-radius: 3px; cursor: pointer;
}}
.webcam-style-btn:hover {{ background: #2a2a4a; color: #fff; }}
.webcam-style-btn.active {{ border-color: #6c5ce7; color: #6c5ce7; background: rgba(108,92,231,0.1); }}
.webcam-pos-btns {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-bottom: 8px;
}}
.webcam-pos-btn {{
    border: 1px solid #333; background: #16213e; color: #aaa; padding: 4px 8px;
    font-size: 0.7em; border-radius: 3px; cursor: pointer; text-align: center;
}}
.webcam-pos-btn:hover {{ background: #2a2a4a; color: #fff; }}
.webcam-pos-btn.active {{ border-color: #6c5ce7; color: #6c5ce7; background: rgba(108,92,231,0.1); }}
.webcam-no-detect {{ color: #666; font-size: 0.72em; font-style: italic; padding: 4px 0; }}

</style>
</head>
<body>
<div class="layout">
<div class="main">
    <h1>Recastr Editor</h1>
    <div class="subtitle">Valide, supprime ou ajuste chaque zoom. Le preview live montre le resultat final.</div>

    <div class="views">
        <div class="view-col">
            <div class="view-label">Original (avec zones de zoom)</div>
            <div class="video-wrap" id="videoWrap">
                <video id="video" src="file:///{video_abs}" controls></video>
                <video id="webcamVideo" style="display:none;"></video>
                <div class="overlay" id="overlay"></div>
            </div>
        </div>
        <div class="view-col">
            <div class="view-label">Preview Live <span class="badge" id="previewBadge">1.0x</span></div>
            <canvas id="previewCanvas" width="{video_w}" height="{video_h}"></canvas>
        </div>
    </div>

    <div class="timeline" id="timeline">
        <div class="tl-playhead" id="playhead"></div>
    </div>

    <div class="status-bar">
        <div>Zoom: <span id="infoZoom">1.0x</span></div>
        <div>Temps: <span id="infoTime">0:00.0</span></div>
        <div>Actifs: <span id="infoCount">{len(zoom_events)}</span> / {len(zoom_events)}</div>
        <div class="speed-control">
            <span style="color:#666; font-size:0.9em;">Vitesse:</span>
            <button class="speed-btn" data-speed="0.5">0.5x</button>
            <button class="speed-btn active" data-speed="1">1x</button>
            <button class="speed-btn" data-speed="1.5">1.5x</button>
            <button class="speed-btn" data-speed="2">2x</button>
        </div>
    </div>
</div>

<div class="sidebar">
    <div class="sb-header">
        <h2>Zooms</h2>
        <span class="sb-count" id="sbCount">{len(zoom_events)} detectes</span>
    </div>
    <details class="bg-panel" open>
        <summary>Background</summary>
        <div class="bg-toggle">
            <input type="checkbox" id="bgEnabled">
            <label for="bgEnabled">Activer le background</label>
        </div>
        <div class="bg-style-btns">
            <button class="bg-style-btn active" data-style="carbon">Carbon</button>
            <button class="bg-style-btn" data-style="gradient">Gradient</button>
            <button class="bg-style-btn" data-style="mesh">Mesh</button>
        </div>
        <div class="bg-row">
            <label>Padding</label>
            <input type="range" id="bgPadding" min="2" max="15" step="1" value="6">
            <span class="val" id="bgPaddingVal">6%</span>
        </div>
        <div class="bg-row">
            <label>Radius</label>
            <input type="range" id="bgRadius" min="0" max="30" step="2" value="12">
            <span class="val" id="bgRadiusVal">12px</span>
        </div>
        <div class="bg-row">
            <label>Ombre</label>
            <input type="range" id="bgShadow" min="0" max="40" step="2" value="20">
            <span class="val" id="bgShadowVal">20</span>
        </div>
    </details>
    <details class="caption-panel" id="captionPanel">
        <summary>Captions (Whisper)</summary>
        <div class="caption-toggle">
            <input type="checkbox" id="captionEnabled">
            <label for="captionEnabled">Activer les captions</label>
        </div>
        <div class="caption-style-btns" id="captionStyleBtns">
            <button class="caption-style-btn active" data-style="tiktok">TikTok</button>
            <button class="caption-style-btn" data-style="classic">Classique</button>
        </div>
        <div class="caption-hint">Clique sur le texte pour l'editer</div>
        <div class="caption-segments" id="captionSegments"></div>
    </details>
    <details class="webcam-panel" id="webcamPanel">
        <summary>Webcam overlay</summary>
        <div id="webcamControls">
        <div class="webcam-toggle">
            <input type="checkbox" id="webcamEnabled">
            <label for="webcamEnabled">Activer la webcam overlay</label>
        </div>
        <div class="webcam-style-btns">
            <button class="webcam-style-btn active" data-shape="circle">Cercle</button>
            <button class="webcam-style-btn" data-shape="rounded">Arrondi</button>
            <button class="webcam-style-btn" data-shape="rectangle">Rectangle</button>
        </div>
        <div class="webcam-pos-btns">
            <button class="webcam-pos-btn" data-pos="top-left">Haut gauche</button>
            <button class="webcam-pos-btn" data-pos="top-right">Haut droit</button>
            <button class="webcam-pos-btn active" data-pos="bottom-left">Bas gauche</button>
            <button class="webcam-pos-btn" data-pos="bottom-right">Bas droit</button>
        </div>
        <div class="webcam-row">
            <label>Taille</label>
            <input type="range" id="webcamSize" min="5" max="40" step="1" value="18">
            <span class="val" id="webcamSizeVal">18%</span>
        </div>
        <div class="webcam-row">
            <label>Bordure</label>
            <input type="range" id="webcamBorder" min="0" max="8" step="1" value="3">
            <span class="val" id="webcamBorderVal">3px</span>
        </div>
        </div>
        <div class="webcam-no-detect" id="webcamNoDetect" style="display:none;">
            Aucune webcam detectee dans le cursor log. Enregistre avec OBS + WebSocket pour activer.
        </div>
    </details>
    <details class="batch-panel">
        <summary>Controles batch</summary>
        <div class="batch-row">
            <label>Zoom global</label>
            <input type="range" id="batchZoom" min="0.5" max="2" step="0.05" value="1">
            <span class="val" id="batchZoomVal">1.0x</span>
        </div>
        <div class="batch-buttons">
            <button class="batch-btn" id="batchEnableAll">Activer tout</button>
            <button class="batch-btn" id="batchDisableAll">Desactiver tout</button>
            <button class="batch-btn" id="batchEnableClicks">Clics seulement</button>
            <button class="batch-btn" id="batchEnableStills">Pauses seulement</button>
            <button class="batch-btn" id="batchEnableArrives">Arrivees seulement</button>
            <button class="batch-btn danger" id="batchDeleteDisabled">Supprimer desactives</button>
        </div>
    </details>
    <div class="add-zoom-hint">Double-clic sur la timeline = ajouter un zoom</div>
    <ul class="zoom-list" id="zoomList"></ul>
    <div class="export-section">
        <button class="btn-export" id="btnExport">Exporter et Render</button>
        <div class="export-note">Sauvegarde les zooms valides en JSON</div>
        <div class="shortcut-hint">Espace = play/pause | Fleches = +/- 2s | Ctrl+Z / Ctrl+Y = undo/redo</div>
    </div>
</div>
</div>

<div class="toast" id="toast"></div>

<script>
let zoomEvents = {events_json};
const cursorTrack = {cursor_track_json};
const videoDuration = {video_duration};
const videoW = {video_w};
const videoH = {video_h};

// --- Caption data ---
let captionSegments = {caption_segments_json};
let captionEnabled = captionSegments.length > 0;
let captionStyle = 'tiktok';

// --- Webcam data ---
const webcamInfo = {webcam_info_json};
const webcamFileUrl = {webcam_file_url_json};
let webcamEnabled = !!(webcamFileUrl || (webcamInfo && webcamInfo.nx !== undefined));
let webcamShape = 'circle';
let webcamPos = 'bottom-left';
let webcamSizePct = 20;
let webcamBorder = 3;
let webcamHasFile = !!webcamFileUrl;

const video = document.getElementById('video');
const webcamVideo = document.getElementById('webcamVideo');

// Charger le fichier webcam separe si dispo
if (webcamFileUrl) {{
    webcamVideo.src = webcamFileUrl;
    webcamVideo.muted = true;
    webcamVideo.load();
}}
const overlay = document.getElementById('overlay');
const timeline = document.getElementById('timeline');
const playhead = document.getElementById('playhead');
const zoomList = document.getElementById('zoomList');
const previewCanvas = document.getElementById('previewCanvas');
const previewCtx = previewCanvas.getContext('2d');
const previewBadge = document.getElementById('previewBadge');

function fmt(t) {{
    const m = Math.floor(t / 60);
    const s = (t % 60).toFixed(1);
    return m + ':' + s.padStart(4, '0');
}}

function showToast(msg) {{
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 2500);
}}

// --- Sidebar list ---
function renderList() {{
    zoomList.innerHTML = '';
    zoomEvents.forEach((ze, i) => {{
        const li = document.createElement('li');
        li.className = 'zoom-item' + (ze.enabled ? '' : ' disabled');
        li.dataset.idx = i;

        const dur = (ze.ease_in + ze.hold + ze.ease_out).toFixed(1);

        li.innerHTML = `
            <div class="zi-top">
                <span class="zi-type ${{ze.type}}">${{ze.type}}</span>
                <span class="zi-time">${{fmt(ze.time)}} (${{dur}}s)</span>
            </div>
            <div class="zi-controls">
                <label>Zoom</label>
                <input type="range" min="1.2" max="4" step="0.1" value="${{ze.zoom}}"
                    data-idx="${{i}}" data-field="zoom" ${{ze.enabled ? '' : 'disabled'}}>
                <span class="val">${{ze.zoom.toFixed(1)}}x</span>
            </div>
            <div class="zi-controls">
                <label>Duree</label>
                <input type="range" min="0.5" max="5" step="0.1" value="${{ze.hold}}"
                    data-idx="${{i}}" data-field="hold" ${{ze.enabled ? '' : 'disabled'}}>
                <span class="val">${{ze.hold.toFixed(1)}}s</span>
            </div>
            <div class="zi-actions">
                <button class="btn btn-toggle" data-idx="${{i}}">${{ze.enabled ? 'Desactiver' : 'Reactiver'}}</button>
                <button class="btn btn-delete" data-idx="${{i}}">Supprimer</button>
            </div>
        `;

        li.addEventListener('click', (e) => {{
            if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT') return;
            video.currentTime = ze.time;
        }});

        zoomList.appendChild(li);
    }});

    zoomList.querySelectorAll('input[type=range]').forEach(inp => {{
        inp.addEventListener('input', (e) => {{
            const idx = parseInt(e.target.dataset.idx);
            const field = e.target.dataset.field;
            const val = parseFloat(e.target.value);
            zoomEvents[idx][field] = val;
            e.target.nextElementSibling.textContent = val.toFixed(1) + (field === 'zoom' ? 'x' : 's');
            renderTimeline();
        }});
    }});

    zoomList.querySelectorAll('.btn-toggle').forEach(btn => {{
        btn.addEventListener('click', () => {{
            const idx = parseInt(btn.dataset.idx);
            zoomEvents[idx].enabled = !zoomEvents[idx].enabled;
            renderList();
            renderTimeline();
        }});
    }});
    zoomList.querySelectorAll('.btn-delete').forEach(btn => {{
        btn.addEventListener('click', () => {{
            const idx = parseInt(btn.dataset.idx);
            zoomEvents.splice(idx, 1);
            renderList();
            renderTimeline();
            showToast('Zoom supprime');
        }});
    }});

    updateCount();
}}

function updateCount() {{
    const active = zoomEvents.filter(z => z.enabled).length;
    document.getElementById('infoCount').textContent = active;
    document.getElementById('sbCount').textContent = active + ' actifs / ' + zoomEvents.length + ' total';
}}

// --- Timeline with drag, resize, scrub ---
let tlDrag = null; // {{ type: 'scrub'|'move'|'resize-left'|'resize-right', idx, startX, startTime, startHold, startEaseIn }}

function pxToTime(px) {{
    const rect = timeline.getBoundingClientRect();
    return Math.max(0, Math.min(videoDuration, (px - rect.left) / rect.width * videoDuration));
}}

function renderTimeline() {{
    // Remove old markers but keep playhead and time labels
    timeline.querySelectorAll('.tl-marker, .tl-time-label').forEach(m => m.remove());

    // Time labels
    const step = videoDuration > 120 ? 30 : videoDuration > 30 ? 10 : 5;
    for (let t = step; t < videoDuration; t += step) {{
        const lbl = document.createElement('div');
        lbl.className = 'tl-time-label';
        lbl.style.left = (t / videoDuration * 100) + '%';
        lbl.textContent = Math.floor(t/60) + ':' + String(Math.floor(t%60)).padStart(2,'0');
        timeline.appendChild(lbl);
    }}

    // Markers
    zoomEvents.forEach((ze, i) => {{
        const dur = ze.ease_in + ze.hold + ze.ease_out;
        const m = document.createElement('div');
        m.className = 'tl-marker ' + ze.type + (ze.enabled ? '' : ' disabled');
        m.style.left = (ze.time / videoDuration * 100) + '%';
        m.style.width = Math.max(6, dur / videoDuration * 100) + '%';
        m.title = ze.type + ' ' + ze.zoom.toFixed(1) + 'x @ ' + fmt(ze.time);
        m.dataset.idx = i;
        m.textContent = ze.zoom.toFixed(1) + 'x';

        // Resize handles
        const handleL = document.createElement('div');
        handleL.className = 'tl-handle left';
        handleL.dataset.idx = i;
        handleL.dataset.side = 'left';
        m.appendChild(handleL);

        const handleR = document.createElement('div');
        handleR.className = 'tl-handle right';
        handleR.dataset.idx = i;
        handleR.dataset.side = 'right';
        m.appendChild(handleR);

        // Mouse down on marker = move
        m.addEventListener('mousedown', (e) => {{
            if (e.target.classList.contains('tl-handle')) return;
            e.stopPropagation();
            e.preventDefault();
            m.classList.add('dragging');
            tlDrag = {{
                type: 'move',
                idx: i,
                startX: e.clientX,
                origTime: ze.time,
                marker: m,
            }};
            video.currentTime = ze.time;
            highlightSidebar(i);
        }});

        // Mouse down on handles = resize
        handleL.addEventListener('mousedown', (e) => {{
            e.stopPropagation();
            e.preventDefault();
            tlDrag = {{
                type: 'resize-left',
                idx: i,
                startX: e.clientX,
                origTime: ze.time,
                origEaseIn: ze.ease_in,
                marker: m,
            }};
        }});
        handleR.addEventListener('mousedown', (e) => {{
            e.stopPropagation();
            e.preventDefault();
            tlDrag = {{
                type: 'resize-right',
                idx: i,
                startX: e.clientX,
                origHold: ze.hold,
                origEaseOut: ze.ease_out,
                marker: m,
            }};
        }});

        timeline.appendChild(m);
    }});
}}

function highlightSidebar(idx) {{
    document.querySelectorAll('.zoom-item').forEach(el => el.classList.remove('active'));
    const item = document.querySelector(`.zoom-item[data-idx="${{idx}}"]`);
    if (item) {{ item.classList.add('active'); item.scrollIntoView({{ block: 'nearest' }}); }}
}}

// Scrub: mousedown on timeline background
timeline.addEventListener('mousedown', (e) => {{
    if (e.target.classList.contains('tl-marker') || e.target.classList.contains('tl-handle')) return;
    e.preventDefault();
    const t = pxToTime(e.clientX);
    video.currentTime = t;
    tlDrag = {{ type: 'scrub' }};
}});

// Global mouse move/up for all drag operations
document.addEventListener('mousemove', (e) => {{
    if (!tlDrag) return;
    const rect = timeline.getBoundingClientRect();
    const tlWidth = rect.width;

    if (tlDrag.type === 'scrub') {{
        video.currentTime = pxToTime(e.clientX);
    }}
    else if (tlDrag.type === 'move') {{
        const dx = e.clientX - tlDrag.startX;
        const dt = (dx / tlWidth) * videoDuration;
        const newTime = Math.max(0, Math.min(videoDuration - 1, tlDrag.origTime + dt));
        zoomEvents[tlDrag.idx].time = Math.round(newTime * 100) / 100;
        video.currentTime = newTime;

        // Update marker position live
        const ze = zoomEvents[tlDrag.idx];
        const dur = ze.ease_in + ze.hold + ze.ease_out;
        tlDrag.marker.style.left = (ze.time / videoDuration * 100) + '%';
    }}
    else if (tlDrag.type === 'resize-left') {{
        const dx = e.clientX - tlDrag.startX;
        const dt = (dx / tlWidth) * videoDuration;
        // Moving left edge: change time and ease_in
        const newTime = Math.max(0, tlDrag.origTime + dt);
        const newEaseIn = Math.max(0.1, tlDrag.origEaseIn - dt);
        zoomEvents[tlDrag.idx].time = Math.round(newTime * 100) / 100;
        zoomEvents[tlDrag.idx].ease_in = Math.round(newEaseIn * 100) / 100;

        const ze = zoomEvents[tlDrag.idx];
        const dur = ze.ease_in + ze.hold + ze.ease_out;
        tlDrag.marker.style.left = (ze.time / videoDuration * 100) + '%';
        tlDrag.marker.style.width = Math.max(6, dur / videoDuration * 100) + '%';
    }}
    else if (tlDrag.type === 'resize-right') {{
        const dx = e.clientX - tlDrag.startX;
        const dt = (dx / tlWidth) * videoDuration;
        // Moving right edge: change hold
        const newHold = Math.max(0.2, tlDrag.origHold + dt);
        zoomEvents[tlDrag.idx].hold = Math.round(newHold * 100) / 100;

        const ze = zoomEvents[tlDrag.idx];
        const dur = ze.ease_in + ze.hold + ze.ease_out;
        tlDrag.marker.style.width = Math.max(6, dur / videoDuration * 100) + '%';
    }}
}});

document.addEventListener('mouseup', (e) => {{
    if (!tlDrag) return;
    if (tlDrag.marker) tlDrag.marker.classList.remove('dragging');
    if (tlDrag.type !== 'scrub') {{
        // Re-render pour synchroniser la sidebar
        renderList();
        renderTimeline();
    }}
    tlDrag = null;
}});

// --- Easing (smooth, organic) ---
function easeZoomIn(t) {{
    t = Math.max(0, Math.min(1, t));
    const base = t * t * (3 - 2 * t);
    const overshoot = Math.sin(t * Math.PI) * 0.04;
    return Math.min(1.0, base + overshoot);
}}
function easeZoomOut(t) {{
    t = Math.max(0, Math.min(1, t));
    return 1 - Math.pow(1 - t, 2.5);
}}

// Smooth damp (spring-based interpolation)
const _smoothState = {{ cx: 0.5, cy: 0.5, zoom: 1.0, vcx: 0, vcy: 0, vz: 0, lastT: -1 }};
function smoothDamp(current, target, vel, smoothTime, dt) {{
    smoothTime = Math.max(0.01, smoothTime);
    const omega = 2.0 / smoothTime;
    const x = omega * dt;
    const exp = 1.0 / (1 + x + 0.48*x*x + 0.235*x*x*x);
    const change = current - target;
    const temp = (vel + omega * change) * dt;
    const newVel = (vel - omega * temp) * exp;
    const newVal = target + (change + temp) * exp;
    return [newVal, newVel];
}}

function getZoomState(t) {{
    // Get raw target
    let zoom = 1.0, nx = 0.5, ny = 0.5;
    let active = false;

    for (const ze of zoomEvents) {{
        if (!ze.enabled) continue;
        const start = ze.time;
        const end = start + ze.ease_in + ze.hold + ze.ease_out;
        if (t < start || t > end) continue;

        const lt = t - start;
        let f;
        if (lt < ze.ease_in) f = easeZoomIn(lt / ze.ease_in);
        else if (lt < ze.ease_in + ze.hold) f = 1.0;
        else f = 1.0 - easeZoomOut((lt - ze.ease_in - ze.hold) / ze.ease_out);

        const z = 1 + (ze.zoom - 1) * f;
        if (z > zoom) {{
            zoom = z;
            nx = ze.nx;
            ny = ze.ny;
            active = true;
        }}
    }}

    // Apply smooth damping for preview
    const dt = _smoothState.lastT < 0 ? 1/30 : Math.min(0.1, Math.abs(t - _smoothState.lastT));
    _smoothState.lastT = t;

    if (dt > 0.05) {{
        // Big jump (scrubbing) - snap immediately
        _smoothState.cx = active ? nx : 0.5;
        _smoothState.cy = active ? ny : 0.5;
        _smoothState.zoom = zoom;
        _smoothState.vcx = 0; _smoothState.vcy = 0; _smoothState.vz = 0;
    }} else {{
        if (active && zoom > 1.05) {{
            [_smoothState.cx, _smoothState.vcx] = smoothDamp(_smoothState.cx, nx, _smoothState.vcx, 0.12, dt);
            [_smoothState.cy, _smoothState.vcy] = smoothDamp(_smoothState.cy, ny, _smoothState.vcy, 0.12, dt);
            [_smoothState.zoom, _smoothState.vz] = smoothDamp(_smoothState.zoom, zoom, _smoothState.vz, 0.15, dt);
        }} else {{
            [_smoothState.zoom, _smoothState.vz] = smoothDamp(_smoothState.zoom, 1.0, _smoothState.vz, 0.2, dt);
            [_smoothState.cx, _smoothState.vcx] = smoothDamp(_smoothState.cx, 0.5, _smoothState.vcx, 0.4, dt);
            [_smoothState.cy, _smoothState.vcy] = smoothDamp(_smoothState.cy, 0.5, _smoothState.vcy, 0.4, dt);
        }}
    }}

    return {{ zoom: Math.max(1.0, _smoothState.zoom), nx: _smoothState.cx, ny: _smoothState.cy }};
}}

// --- Live preview canvas ---
// --- Cursor state ---

// --- Background state ---
let bgEnabled = false;
let bgStyle = 'carbon';
let bgPadding = 6;
let bgRadius = 12;
let bgShadow = 20;

// Pre-render background gradients
let bgCache = null;
function generateBgGradient(style) {{
    const c = document.createElement('canvas');
    c.width = videoW; c.height = videoH;
    const ctx = c.getContext('2d');

    if (style === 'carbon') {{
        const g = ctx.createRadialGradient(videoW/2, videoH/2, 0, videoW/2, videoH/2, Math.max(videoW, videoH)*0.7);
        g.addColorStop(0, '#22242a');
        g.addColorStop(1, '#0e0e12');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, videoW, videoH);
        // Subtle noise texture
        const id = ctx.getImageData(0, 0, videoW, videoH);
        for (let i = 0; i < id.data.length; i += 4) {{
            const n = (Math.random() - 0.5) * 6;
            id.data[i] = Math.max(0, Math.min(255, id.data[i] + n));
            id.data[i+1] = Math.max(0, Math.min(255, id.data[i+1] + n));
            id.data[i+2] = Math.max(0, Math.min(255, id.data[i+2] + n));
        }}
        ctx.putImageData(id, 0, 0);
    }}
    else if (style === 'gradient') {{
        const g = ctx.createLinearGradient(0, 0, videoW, videoH);
        g.addColorStop(0, '#12142a');
        g.addColorStop(1, '#241220');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, videoW, videoH);
    }}
    else if (style === 'mesh') {{
        ctx.fillStyle = '#14161c';
        ctx.fillRect(0, 0, videoW, videoH);
        ctx.strokeStyle = '#1a1c22';
        ctx.lineWidth = 1;
        for (let y = 0; y < videoH; y += 24) {{
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(videoW, y); ctx.stroke();
        }}
        for (let x = 0; x < videoW; x += 24) {{
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, videoH); ctx.stroke();
        }}
    }}
    return c;
}}

function roundRect(ctx, x, y, w, h, r) {{
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r);
    ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + h - r, r);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
}}

function drawPreview() {{
    const t = video.currentTime;
    const state = getZoomState(t);

    // Draw the cropped/zoomed portion of the video onto the canvas
    const sw = videoW / state.zoom;
    const sh = videoH / state.zoom;
    const sx = Math.max(0, Math.min(state.nx * videoW - sw/2, videoW - sw));
    const sy = Math.max(0, Math.min(state.ny * videoH - sh/2, videoH - sh));

    if (bgEnabled) {{
        // Draw background
        if (!bgCache || bgCache._style !== bgStyle) {{
            bgCache = generateBgGradient(bgStyle);
            bgCache._style = bgStyle;
        }}
        previewCtx.drawImage(bgCache, 0, 0);

        // Compute inner video rect with padding
        const padX = videoW * bgPadding / 100;
        const padY = videoH * bgPadding / 100;
        const maxW = videoW - 2 * padX;
        const maxH = videoH - 2 * padY;
        const aspect = videoW / videoH;
        let innerW, innerH;
        if (maxW / maxH > aspect) {{
            innerH = maxH; innerW = innerH * aspect;
        }} else {{
            innerW = maxW; innerH = innerW / aspect;
        }}
        const ix = (videoW - innerW) / 2;
        const iy = (videoH - innerH) / 2;

        // Shadow
        if (bgShadow > 0) {{
            previewCtx.save();
            previewCtx.shadowColor = 'rgba(0,0,0,0.6)';
            previewCtx.shadowBlur = bgShadow;
            previewCtx.shadowOffsetX = bgShadow * 0.3;
            previewCtx.shadowOffsetY = bgShadow * 0.3;
            previewCtx.fillStyle = '#000';
            roundRect(previewCtx, ix, iy, innerW, innerH, bgRadius);
            previewCtx.fill();
            previewCtx.restore();
        }}

        // Clip to rounded rect and draw video
        previewCtx.save();
        roundRect(previewCtx, ix, iy, innerW, innerH, bgRadius);
        previewCtx.clip();
        previewCtx.drawImage(video, sx, sy, sw, sh, ix, iy, innerW, innerH);
        previewCtx.restore();

        // Subtle border
        previewCtx.strokeStyle = 'rgba(255,255,255,0.08)';
        previewCtx.lineWidth = 1;
        roundRect(previewCtx, ix, iy, innerW, innerH, bgRadius);
        previewCtx.stroke();
    }}
    else {{
        // No background — full frame
        previewCtx.drawImage(video, sx, sy, sw, sh, 0, 0, videoW, videoH);
    }}

    // --- Click highlight on preview ---
    if (cursorTrack.length > 0 && !video.paused) {{
        const ct = video.currentTime;
        let lo = 0, hi = cursorTrack.length - 1;
        while (lo < hi) {{
            const mid = (lo + hi + 1) >> 1;
            if (cursorTrack[mid].t <= ct) lo = mid; else hi = mid - 1;
        }}
        const cp = cursorTrack[lo];
        if (cp && cp.c) {{
            let cpx = cp.nx * videoW;
            let cpy = cp.ny * videoH;
            if (state.zoom > 1.05) {{
                cpx = (cp.nx * videoW - sx) / sw * videoW;
                cpy = (cp.ny * videoH - sy) / sh * videoH;
            }}
            if (cpx >= 0 && cpx <= videoW && cpy >= 0 && cpy <= videoH) {{
                if (bgEnabled) {{
                    const padX = videoW * bgPadding / 100;
                    const padY = videoH * bgPadding / 100;
                    const maxW = videoW - 2 * padX, maxH = videoH - 2 * padY;
                    const vAspect = videoW / videoH;
                    let iW, iH;
                    if (maxW / maxH > vAspect) {{ iH = maxH; iW = iH * vAspect; }}
                    else {{ iW = maxW; iH = iW / vAspect; }}
                    const bix = (videoW - iW) / 2, biy = (videoH - iH) / 2;
                    cpx = bix + (cpx / videoW) * iW;
                    cpy = biy + (cpy / videoH) * iH;
                }}
                // Ripple click effect
                previewCtx.save();
                const r1 = 30, r2 = 18;
                previewCtx.strokeStyle = 'rgba(233,69,96,0.7)';
                previewCtx.lineWidth = 3;
                previewCtx.beginPath(); previewCtx.arc(cpx, cpy, r1, 0, Math.PI*2); previewCtx.stroke();
                previewCtx.lineWidth = 2;
                previewCtx.beginPath(); previewCtx.arc(cpx, cpy, r2, 0, Math.PI*2); previewCtx.stroke();
                previewCtx.restore();
            }}
        }}
    }}

    // --- Caption preview ---
    if (captionEnabled && captionSegments.length > 0) {{
        const ct = video.currentTime;
        let activeSeg = null;
        let activeWordIdx = -1;
        for (const seg of captionSegments) {{
            if (seg.start <= ct && ct <= seg.end) {{
                activeSeg = seg;
                if (seg.words) {{
                    for (let wi = 0; wi < seg.words.length; wi++) {{
                        if (seg.words[wi].start <= ct && ct <= seg.words[wi].end) {{
                            activeWordIdx = wi;
                            break;
                        }}
                    }}
                }}
                break;
            }}
        }}
        if (activeSeg) {{
            previewCtx.save();
            if (captionStyle === 'tiktok') {{
                // TikTok: gros texte centre, mot actif en rouge
                const words = activeSeg.words || [];
                if (words.length > 0) {{
                    const maxPerLine = Math.max(3, Math.min(6, Math.ceil(words.length / 2)));
                    const lines = [];
                    let cur = [];
                    words.forEach((w, i) => {{
                        cur.push({{ idx: i, word: w.word }});
                        if (cur.length >= maxPerLine) {{ lines.push(cur); cur = []; }}
                    }});
                    if (cur.length) lines.push(cur);

                    // Find line with active word
                    let activeLine = 0;
                    for (let li = 0; li < lines.length; li++) {{
                        for (const ww of lines[li]) {{
                            if (ww.idx === activeWordIdx) activeLine = li;
                        }}
                    }}

                    const fontSize = Math.max(28, Math.round(videoH * 0.05));
                    previewCtx.font = 'bold ' + fontSize + 'px system-ui, sans-serif';
                    previewCtx.textBaseline = 'top';

                    const line = lines[activeLine] || lines[0];
                    const fullText = line.map(w => w.word).join(' ');
                    const tw = previewCtx.measureText(fullText).width;
                    const lh = fontSize * 1.3;
                    const yPos = Math.round(videoH * 0.72);
                    const xStart = (videoW - tw) / 2;

                    // Background
                    const pad = fontSize * 0.35;
                    previewCtx.fillStyle = 'rgba(0,0,0,0.7)';
                    const bgR = fontSize * 0.25;
                    previewCtx.beginPath();
                    roundRect(previewCtx, xStart - pad, yPos - pad * 0.5, tw + pad * 2, lh + pad, bgR);
                    previewCtx.fill();

                    // Words
                    let x = xStart;
                    for (const ww of line) {{
                        previewCtx.fillStyle = (ww.idx === activeWordIdx) ? '#e94560' : '#ffffff';
                        previewCtx.fillText(ww.word, x, yPos);
                        x += previewCtx.measureText(ww.word + ' ').width;
                    }}
                }}
            }} else {{
                // Classic: texte en bas, fond noir
                const text = activeSeg.text;
                const fontSize = Math.max(20, Math.round(videoH * 0.032));
                previewCtx.font = fontSize + 'px system-ui, sans-serif';
                previewCtx.textBaseline = 'top';

                const maxW = videoW * 0.8;
                const textWords = text.split(' ');
                const lines = [];
                let cur = '';
                for (const w of textWords) {{
                    const test = cur ? cur + ' ' + w : w;
                    if (previewCtx.measureText(test).width > maxW && cur) {{
                        lines.push(cur); cur = w;
                    }} else cur = test;
                }}
                if (cur) lines.push(cur);

                const lh = fontSize * 1.3;
                const totalH = lh * lines.length;
                const yStart = videoH - totalH - videoH * 0.05;
                const pad = fontSize * 0.45;

                let maxLineW = 0;
                for (const l of lines) maxLineW = Math.max(maxLineW, previewCtx.measureText(l).width);
                const bgX = (videoW - maxLineW) / 2;
                previewCtx.fillStyle = 'rgba(0,0,0,0.75)';
                previewCtx.beginPath();
                roundRect(previewCtx, bgX - pad, yStart - pad, maxLineW + pad * 2, totalH + pad * 2, 6);
                previewCtx.fill();

                previewCtx.fillStyle = '#ffffff';
                for (let i = 0; i < lines.length; i++) {{
                    const lw = previewCtx.measureText(lines[i]).width;
                    previewCtx.fillText(lines[i], (videoW - lw) / 2, yStart + i * lh);
                }}
            }}
            previewCtx.restore();
        }}

        // Highlight active segment in sidebar
        document.querySelectorAll('.caption-seg').forEach(el => {{
            const idx = parseInt(el.dataset.idx);
            const seg = captionSegments[idx];
            el.classList.toggle('active', seg && seg.start <= ct && ct <= seg.end);
        }});
    }}

    // --- Webcam preview ---
    const hasWebcamSource = webcamHasFile || (webcamInfo && webcamInfo.nx !== undefined);
    if (webcamEnabled && hasWebcamSource) {{
        // Source: fichier separe ou region du video principal
        const camSrc = webcamHasFile ? webcamVideo : video;
        let srcX, srcY, srcW, srcH;
        if (webcamHasFile) {{
            srcX = 0; srcY = 0;
            srcW = webcamVideo.videoWidth || 640;
            srcH = webcamVideo.videoHeight || 480;
        }} else {{
            srcX = webcamInfo.nx * videoW;
            srcY = webcamInfo.ny * videoH;
            srcW = webcamInfo.nw * videoW;
            srcH = webcamInfo.nh * videoH;
        }}

        // Destination: compute based on position preset and size
        const size = webcamSizePct / 100;
        const camAspect = srcW / Math.max(srcH, 1);
        const dstW = videoW * size;
        const dstH = dstW / camAspect;
        const margin = videoW * 0.02;

        let dstX, dstY;
        if (webcamPos === 'top-left') {{ dstX = margin; dstY = margin; }}
        else if (webcamPos === 'top-right') {{ dstX = videoW - dstW - margin; dstY = margin; }}
        else if (webcamPos === 'bottom-right') {{ dstX = videoW - dstW - margin; dstY = videoH - dstH - margin; }}
        else {{ dstX = margin; dstY = videoH - dstH - margin; }} // bottom-left

        previewCtx.save();

        if (webcamShape === 'circle') {{
            const cx = dstX + dstW / 2;
            const cy = dstY + dstH / 2;
            const r = Math.min(dstW, dstH) / 2;
            previewCtx.beginPath();
            previewCtx.arc(cx, cy, r, 0, Math.PI * 2);
            previewCtx.clip();
            try {{ previewCtx.drawImage(camSrc, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH); }} catch(e) {{}}
            previewCtx.restore();
            if (webcamBorder > 0) {{
                previewCtx.save();
                previewCtx.strokeStyle = '#fff';
                previewCtx.lineWidth = webcamBorder;
                previewCtx.beginPath();
                previewCtx.arc(cx, cy, r, 0, Math.PI * 2);
                previewCtx.stroke();
                previewCtx.restore();
            }}
        }} else if (webcamShape === 'rounded') {{
            const r = Math.min(dstW, dstH) / 6;
            roundRect(previewCtx, dstX, dstY, dstW, dstH, r);
            previewCtx.clip();
            try {{ previewCtx.drawImage(camSrc, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH); }} catch(e) {{}}
            previewCtx.restore();
            if (webcamBorder > 0) {{
                previewCtx.save();
                previewCtx.strokeStyle = '#fff';
                previewCtx.lineWidth = webcamBorder;
                roundRect(previewCtx, dstX, dstY, dstW, dstH, r);
                previewCtx.stroke();
                previewCtx.restore();
            }}
        }} else {{
            try {{ previewCtx.drawImage(camSrc, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH); }} catch(e) {{}}
            previewCtx.restore();
            if (webcamBorder > 0) {{
                previewCtx.save();
                previewCtx.strokeStyle = '#fff';
                previewCtx.lineWidth = webcamBorder;
                previewCtx.strokeRect(dstX, dstY, dstW, dstH);
                previewCtx.restore();
            }}
        }}
    }}

    // Badge
    previewBadge.textContent = state.zoom.toFixed(1) + 'x';
    previewBadge.style.background = state.zoom > 1.05 ? '#e94560' : (bgEnabled ? '#00b894' : '#333');

    requestAnimationFrame(drawPreview);
}}

// --- Video overlay drag state ---
let overlayDrag = null; // {{ type: 'dot'|'rect'|'resize', idx, startNx, startNy, startZoom, ... }}

function getOverlayLayout() {{
    const vRect = video.getBoundingClientRect();
    const aspect = videoW / videoH;
    const elAspect = vRect.width / vRect.height;
    let dw, dh, ox, oy;
    if (elAspect > aspect) {{ dh = vRect.height; dw = dh * aspect; ox = (vRect.width - dw) / 2; oy = 0; }}
    else {{ dw = vRect.width; dh = dw / aspect; ox = 0; oy = (vRect.height - dh) / 2; }}
    return {{ dw, dh, ox, oy, vRect }};
}}

function pxToNorm(clientX, clientY) {{
    const {{ dw, dh, ox, oy, vRect }} = getOverlayLayout();
    const nx = Math.max(0, Math.min(1, (clientX - vRect.left - ox) / dw));
    const ny = Math.max(0, Math.min(1, (clientY - vRect.top - oy) / dh));
    return {{ nx, ny }};
}}

// --- Video overlay (zones on original) ---
function updateOverlay() {{
    const t = video.currentTime;
    const {{ dw, dh, ox, oy }} = getOverlayLayout();

    playhead.style.left = (t / videoDuration * 100) + '%';

    // Don't rebuild overlay while dragging (would destroy the dragged element)
    if (overlayDrag) {{
        requestAnimationFrame(updateOverlay);
        // Still update info
        const state = getZoomState(t);
        document.getElementById('infoZoom').textContent = state.zoom.toFixed(1) + 'x';
        const m = Math.floor(t / 60), s = (t % 60).toFixed(1);
        document.getElementById('infoTime').textContent = m + ':' + s.padStart(4, '0');
        return;
    }}

    overlay.innerHTML = '';

    zoomEvents.forEach((ze, i) => {{
        if (!ze.enabled) return;
        const start = ze.time;
        const end = start + ze.ease_in + ze.hold + ze.ease_out;
        if (t < start || t > end) return;

        const lt = t - start;
        let f;
        if (lt < ze.ease_in) f = easeZoomIn(lt / ze.ease_in);
        else if (lt < ze.ease_in + ze.hold) f = 1.0;
        else f = 1.0 - easeZoomOut((lt - ze.ease_in - ze.hold) / ze.ease_out);

        const zoom = 1 + (ze.zoom - 1) * f;
        const cw = 1 / zoom, ch = 1 / zoom;
        const cx = Math.max(0, Math.min(ze.nx - cw/2, 1 - cw));
        const cy = Math.max(0, Math.min(ze.ny - ch/2, 1 - ch));

        // Zoom rectangle (draggable to move position)
        const rect = document.createElement('div');
        rect.className = 'zoom-rect ' + ze.type;
        rect.style.left = (ox + cx * dw) + 'px';
        rect.style.top = (oy + cy * dh) + 'px';
        rect.style.width = (cw * dw) + 'px';
        rect.style.height = (ch * dh) + 'px';
        rect.dataset.idx = i;

        // Resize handles (corners)
        ['tl','tr','bl','br'].forEach(corner => {{
            const h = document.createElement('div');
            h.className = 'zoom-resize-handle ' + corner;
            h.dataset.idx = i;
            h.dataset.corner = corner;
            h.addEventListener('mousedown', (e) => {{
                e.stopPropagation();
                e.preventDefault();
                saveState();
                overlayDrag = {{
                    type: 'resize',
                    idx: i,
                    corner: corner,
                    startZoom: ze.zoom,
                    startClientX: e.clientX,
                    startClientY: e.clientY,
                }};
            }});
            rect.appendChild(h);
        }});

        // Drag rect = move zoom position
        rect.addEventListener('mousedown', (e) => {{
            if (e.target.classList.contains('zoom-resize-handle')) return;
            e.stopPropagation();
            e.preventDefault();
            saveState();
            const nPos = pxToNorm(e.clientX, e.clientY);
            overlayDrag = {{
                type: 'rect',
                idx: i,
                offsetNx: ze.nx - nPos.nx,
                offsetNy: ze.ny - nPos.ny,
            }};
            rect.classList.add('dragging');
            highlightSidebar(i);
        }});
        overlay.appendChild(rect);

        // Center dot (draggable)
        const dot = document.createElement('div');
        dot.className = 'zoom-dot ' + ze.type;
        dot.style.left = (ox + ze.nx * dw) + 'px';
        dot.style.top = (oy + ze.ny * dh) + 'px';
        dot.dataset.idx = i;

        dot.addEventListener('mousedown', (e) => {{
            e.stopPropagation();
            e.preventDefault();
            saveState();
            overlayDrag = {{
                type: 'dot',
                idx: i,
            }};
            dot.classList.add('dragging');
            highlightSidebar(i);
        }});
        overlay.appendChild(dot);

        const item = document.querySelector(`.zoom-item[data-idx="${{i}}"]`);
        if (item) item.classList.add('active');
    }});

    document.querySelectorAll('.zoom-item').forEach(el => {{
        const idx = parseInt(el.dataset.idx);
        const ze = zoomEvents[idx];
        if (!ze) return;
        const end = ze.time + ze.ease_in + ze.hold + ze.ease_out;
        if (t < ze.time || t > end) el.classList.remove('active');
    }});

    const state = getZoomState(t);
    document.getElementById('infoZoom').textContent = state.zoom.toFixed(1) + 'x';
    const m = Math.floor(t / 60), s = (t % 60).toFixed(1);
    document.getElementById('infoTime').textContent = m + ':' + s.padStart(4, '0');

    requestAnimationFrame(updateOverlay);
}}

// --- Overlay drag: mousemove + mouseup ---
document.addEventListener('mousemove', (e) => {{
    if (!overlayDrag) return;
    const ze = zoomEvents[overlayDrag.idx];
    if (!ze) return;

    if (overlayDrag.type === 'dot' || overlayDrag.type === 'rect') {{
        const nPos = pxToNorm(e.clientX, e.clientY);
        let newNx, newNy;
        if (overlayDrag.type === 'dot') {{
            newNx = nPos.nx;
            newNy = nPos.ny;
        }} else {{
            newNx = nPos.nx + overlayDrag.offsetNx;
            newNy = nPos.ny + overlayDrag.offsetNy;
        }}
        ze.nx = Math.max(0.05, Math.min(0.95, newNx));
        ze.ny = Math.max(0.05, Math.min(0.95, newNy));

        // Live update the dot and rect positions
        const {{ dw, dh, ox, oy }} = getOverlayLayout();
        const dot = overlay.querySelector(`.zoom-dot[data-idx="${{overlayDrag.idx}}"]`);
        if (dot) {{
            dot.style.left = (ox + ze.nx * dw) + 'px';
            dot.style.top = (oy + ze.ny * dh) + 'px';
        }}
        const rect = overlay.querySelector(`.zoom-rect[data-idx="${{overlayDrag.idx}}"]`);
        if (rect) {{
            const zoom = ze.zoom; // approximate with full zoom for visual feedback
            const cw = 1 / zoom, ch = 1 / zoom;
            const cx = Math.max(0, Math.min(ze.nx - cw/2, 1 - cw));
            const cy = Math.max(0, Math.min(ze.ny - ch/2, 1 - ch));
            rect.style.left = (ox + cx * dw) + 'px';
            rect.style.top = (oy + cy * dh) + 'px';
        }}
    }}
    else if (overlayDrag.type === 'resize') {{
        // Dragging a corner handle = change zoom level
        const dy = overlayDrag.startClientY - e.clientY; // up = more zoom
        const dx = e.clientX - overlayDrag.startClientX;
        const delta = (dy + Math.abs(dx) * 0.3) * 0.01;
        ze.zoom = Math.max(1.2, Math.min(4.0, overlayDrag.startZoom + delta));

        // Live update rect size
        const {{ dw, dh, ox, oy }} = getOverlayLayout();
        const rect = overlay.querySelector(`.zoom-rect[data-idx="${{overlayDrag.idx}}"]`);
        if (rect) {{
            const cw = 1 / ze.zoom, ch = 1 / ze.zoom;
            const cx = Math.max(0, Math.min(ze.nx - cw/2, 1 - cw));
            const cy = Math.max(0, Math.min(ze.ny - ch/2, 1 - ch));
            rect.style.left = (ox + cx * dw) + 'px';
            rect.style.top = (oy + cy * dh) + 'px';
            rect.style.width = (cw * dw) + 'px';
            rect.style.height = (ch * dh) + 'px';
        }}
    }}
}});

document.addEventListener('mouseup', (e) => {{
    if (!overlayDrag) return;
    const wasOverlay = overlayDrag;
    overlayDrag = null;
    // Refresh sidebar + timeline + base zoom levels
    baseZoomLevels = zoomEvents.map(z => z.zoom);
    renderList();
    renderTimeline();
}});

// --- Captions UI ---
function renderCaptionSegments() {{
    const container = document.getElementById('captionSegments');
    if (!container) return;
    container.innerHTML = '';
    captionSegments.forEach((seg, i) => {{
        const div = document.createElement('div');
        div.className = 'caption-seg';
        div.dataset.idx = i;
        div.innerHTML = `<span class="caption-seg-time">${{fmt(seg.start)}} - ${{fmt(seg.end)}}</span>
            <div class="caption-seg-text" contenteditable="true">${{seg.text}}</div>`;
        // Click to seek
        div.querySelector('.caption-seg-time').addEventListener('click', () => {{
            video.currentTime = seg.start;
        }});
        // Edit text
        div.querySelector('.caption-seg-text').addEventListener('blur', (e) => {{
            captionSegments[i].text = e.target.textContent.trim();
            // Update words from edited text
            const newWords = e.target.textContent.trim().split(/\s+/);
            if (seg.words && seg.words.length > 0) {{
                const segDur = seg.end - seg.start;
                const wordDur = segDur / Math.max(newWords.length, 1);
                captionSegments[i].words = newWords.map((w, wi) => ({{
                    word: w,
                    start: Math.round((seg.start + wi * wordDur) * 1000) / 1000,
                    end: Math.round((seg.start + (wi + 1) * wordDur) * 1000) / 1000,
                }}));
            }}
        }});
        container.appendChild(div);
    }});
}}

document.getElementById('captionEnabled').addEventListener('change', (e) => {{
    captionEnabled = e.target.checked;
}});

document.querySelectorAll('.caption-style-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        document.querySelectorAll('.caption-style-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        captionStyle = btn.dataset.style;
    }});
}});

// Init captions
if (captionSegments.length > 0) {{
    document.getElementById('captionEnabled').checked = true;
    document.getElementById('captionPanel').open = true;
    renderCaptionSegments();
}}

// --- Webcam UI ---
function getWebcamExportConfig() {{
    if (!webcamEnabled) return null;
    const hasSource = webcamHasFile || (webcamInfo && webcamInfo.nx !== undefined);
    if (!hasSource) return null;
    const size = webcamSizePct / 100;
    // Aspect ratio: from webcam file or from OBS info
    let camAspect;
    if (webcamHasFile && webcamVideo.videoWidth > 0) {{
        camAspect = webcamVideo.videoWidth / webcamVideo.videoHeight;
    }} else if (webcamInfo && webcamInfo.nh > 0) {{
        camAspect = webcamInfo.nw / webcamInfo.nh;
    }} else {{
        camAspect = 16/9;
    }}
    const out_nh = size / camAspect;
    const margin = 0.02;
    let out_nx, out_ny;
    if (webcamPos === 'top-left') {{ out_nx = margin; out_ny = margin; }}
    else if (webcamPos === 'top-right') {{ out_nx = 1 - size - margin; out_ny = margin; }}
    else if (webcamPos === 'bottom-right') {{ out_nx = 1 - size - margin; out_ny = 1 - out_nh - margin; }}
    else {{ out_nx = margin; out_ny = 1 - out_nh - margin; }}
    const config = {{
        out_nx: out_nx, out_ny: out_ny,
        out_nw: size, out_nh: out_nh,
        shape: webcamShape, border: webcamBorder,
        border_color: [255, 255, 255],
    }};
    // Legacy: include source coords if using extraction mode
    if (!webcamHasFile && webcamInfo && webcamInfo.nx !== undefined) {{
        config.nx = webcamInfo.nx;
        config.ny = webcamInfo.ny;
        config.nw = webcamInfo.nw;
        config.nh = webcamInfo.nh;
    }}
    return config;
}}

document.getElementById('webcamEnabled').addEventListener('change', (e) => {{
    webcamEnabled = e.target.checked;
}});

document.querySelectorAll('.webcam-style-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        document.querySelectorAll('.webcam-style-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        webcamShape = btn.dataset.shape;
    }});
}});

document.querySelectorAll('.webcam-pos-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        document.querySelectorAll('.webcam-pos-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        webcamPos = btn.dataset.pos;
    }});
}});

document.getElementById('webcamSize').addEventListener('input', (e) => {{
    webcamSizePct = parseInt(e.target.value);
    document.getElementById('webcamSizeVal').textContent = webcamSizePct + '%';
}});

document.getElementById('webcamBorder').addEventListener('input', (e) => {{
    webcamBorder = parseInt(e.target.value);
    document.getElementById('webcamBorderVal').textContent = webcamBorder + 'px';
}});

// Init webcam panel
if (webcamHasFile || (webcamInfo && webcamInfo.nx !== undefined)) {{
    document.getElementById('webcamEnabled').checked = true;
    document.getElementById('webcamPanel').open = true;
    webcamSizePct = 20;
    document.getElementById('webcamSize').value = 20;
    document.getElementById('webcamSizeVal').textContent = '20%';
    if (!webcamHasFile && webcamInfo) {{
        // Legacy: init size from OBS webcam size
        const initSize = Math.round(webcamInfo.nw * 100);
        if (initSize > 0 && initSize <= 40) {{
            webcamSizePct = initSize;
            document.getElementById('webcamSize').value = initSize;
            document.getElementById('webcamSizeVal').textContent = initSize + '%';
        }}
    }}
}} else {{
    document.getElementById('webcamControls').style.display = 'none';
    document.getElementById('webcamNoDetect').style.display = 'block';
}}

// --- Export ---
document.getElementById('btnExport').addEventListener('click', () => {{
    const active = zoomEvents.filter(z => z.enabled).map(z => ({{
        time: z.time, nx: z.nx, ny: z.ny, zoom: z.zoom,
        hold: z.hold, ease_in: z.ease_in, ease_out: z.ease_out, type: z.type
    }}));

    const exportData = {{
        zooms: active,
        background: bgEnabled ? {{
            style: bgStyle,
            padding: bgPadding / 100,
            shadow: bgShadow,
            corner_radius: bgRadius,
        }} : null,
        captions: captionEnabled ? {{
            style: captionStyle,
            segments: captionSegments,
        }} : null,
        webcam: getWebcamExportConfig(),
        webcam_file: webcamHasFile ? webcamFileUrl : null,
    }};

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {{ type: 'application/json' }});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'zoom_events_edited.json';
    a.click();

    let extras = '';
    if (bgEnabled) extras += ' + background';
    if (captionEnabled) extras += ' + captions';
    if (webcamEnabled) extras += ' + webcam';
    showToast('JSON exporte! (' + active.length + ' zooms' + extras + ')');
}});

// --- Keyboard ---
document.addEventListener('keydown', (e) => {{
    if (e.target.tagName === 'INPUT') return;
    if (e.key === ' ') {{ e.preventDefault(); video.paused ? video.play() : video.pause(); }}
    if (e.key === 'ArrowLeft') {{ e.preventDefault(); video.currentTime = Math.max(0, video.currentTime - 2); }}
    if (e.key === 'ArrowRight') {{ e.preventDefault(); video.currentTime = Math.min(videoDuration, video.currentTime + 2); }}
}});

// --- Undo / Redo ---
let undoStack = [];
let redoStack = [];
function saveState() {{
    undoStack.push(JSON.stringify(zoomEvents));
    if (undoStack.length > 50) undoStack.shift();
    redoStack = [];
}}
function undo() {{
    if (undoStack.length === 0) return;
    redoStack.push(JSON.stringify(zoomEvents));
    zoomEvents = JSON.parse(undoStack.pop());
    renderList(); renderTimeline();
    showToast('Undo');
}}
function redo() {{
    if (redoStack.length === 0) return;
    undoStack.push(JSON.stringify(zoomEvents));
    zoomEvents = JSON.parse(redoStack.pop());
    renderList(); renderTimeline();
    showToast('Redo');
}}

// Wrap existing delete/toggle to save state
const _origRenderList = renderList;
renderList = function() {{
    _origRenderList();

    // Re-bind with undo support
    zoomList.querySelectorAll('.btn-toggle').forEach(btn => {{
        const newBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(newBtn, btn);
        newBtn.addEventListener('click', () => {{
            saveState();
            const idx = parseInt(newBtn.dataset.idx);
            zoomEvents[idx].enabled = !zoomEvents[idx].enabled;
            renderList(); renderTimeline();
        }});
    }});
    zoomList.querySelectorAll('.btn-delete').forEach(btn => {{
        const newBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(newBtn, btn);
        newBtn.addEventListener('click', () => {{
            saveState();
            const idx = parseInt(newBtn.dataset.idx);
            zoomEvents.splice(idx, 1);
            renderList(); renderTimeline();
            showToast('Zoom supprime');
        }});
    }});
}};

// --- Batch controls ---
const batchZoomSlider = document.getElementById('batchZoom');
const batchZoomVal = document.getElementById('batchZoomVal');
let baseZoomLevels = zoomEvents.map(z => z.zoom);

batchZoomSlider.addEventListener('input', () => {{
    const mult = parseFloat(batchZoomSlider.value);
    batchZoomVal.textContent = mult.toFixed(2) + 'x';
    zoomEvents.forEach((ze, i) => {{
        if (ze.enabled) {{
            ze.zoom = Math.max(1.2, Math.min(4.0, baseZoomLevels[i] * mult));
        }}
    }});
    renderList(); renderTimeline();
}});
// Update base levels when individual zoom changes
const _origSliderHandler = true;
zoomList.addEventListener('input', (e) => {{
    if (e.target.type === 'range' && e.target.dataset.field === 'zoom') {{
        const idx = parseInt(e.target.dataset.idx);
        baseZoomLevels[idx] = parseFloat(e.target.value);
    }}
}});

document.getElementById('batchEnableAll').addEventListener('click', () => {{
    saveState();
    zoomEvents.forEach(z => z.enabled = true);
    renderList(); renderTimeline();
    showToast('Tous actives');
}});
document.getElementById('batchDisableAll').addEventListener('click', () => {{
    saveState();
    zoomEvents.forEach(z => z.enabled = false);
    renderList(); renderTimeline();
    showToast('Tous desactives');
}});
document.getElementById('batchEnableClicks').addEventListener('click', () => {{
    saveState();
    zoomEvents.forEach(z => z.enabled = (z.type === 'click'));
    renderList(); renderTimeline();
    showToast('Clics seulement');
}});
document.getElementById('batchEnableStills').addEventListener('click', () => {{
    saveState();
    zoomEvents.forEach(z => z.enabled = (z.type === 'still'));
    renderList(); renderTimeline();
    showToast('Pauses seulement');
}});
document.getElementById('batchEnableArrives').addEventListener('click', () => {{
    saveState();
    zoomEvents.forEach(z => z.enabled = (z.type === 'arrive'));
    renderList(); renderTimeline();
    showToast('Arrivees seulement');
}});
document.getElementById('batchDeleteDisabled').addEventListener('click', () => {{
    const count = zoomEvents.filter(z => !z.enabled).length;
    if (count === 0) {{ showToast('Rien a supprimer'); return; }}
    saveState();
    zoomEvents = zoomEvents.filter(z => z.enabled);
    baseZoomLevels = zoomEvents.map(z => z.zoom);
    batchZoomSlider.value = 1; batchZoomVal.textContent = '1.0x';
    renderList(); renderTimeline();
    showToast(count + ' zooms supprimes');
}});

// --- Speed control ---
document.querySelectorAll('.speed-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        const speed = parseFloat(btn.dataset.speed);
        video.playbackRate = speed;
        document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    }});
}});

// --- Double-click on timeline = add manual zoom ---
timeline.addEventListener('dblclick', (e) => {{
    if (e.target.classList.contains('tl-marker') || e.target.classList.contains('tl-handle')) return;
    const t = pxToTime(e.clientX);

    // Get cursor position at that time from the video (center if unknown)
    let nx = 0.5, ny = 0.5;

    saveState();
    const newZoom = {{
        id: zoomEvents.length,
        time: Math.round(t * 100) / 100,
        nx: nx,
        ny: ny,
        zoom: 2.0,
        hold: 1.5,
        ease_in: 0.2,
        ease_out: 0.35,
        type: 'click',
        enabled: true,
    }};
    zoomEvents.push(newZoom);
    zoomEvents.sort((a, b) => a.time - b.time);
    baseZoomLevels = zoomEvents.map(z => z.zoom);
    renderList(); renderTimeline();
    video.currentTime = t;
    showToast('Zoom ajoute a ' + fmt(t));
}});

// --- Keyboard: undo/redo ---
const _origKeyHandler = document.onkeydown;
document.addEventListener('keydown', (e) => {{
    if (e.target.tagName === 'INPUT') return;
    if ((e.ctrlKey || e.metaKey) && e.key === 'z') {{
        e.preventDefault();
        if (e.shiftKey) redo(); else undo();
    }}
    if ((e.ctrlKey || e.metaKey) && e.key === 'y') {{
        e.preventDefault();
        redo();
    }}
}});


// --- Background controls ---
document.getElementById('bgEnabled').addEventListener('change', (e) => {{
    bgEnabled = e.target.checked;
    bgCache = null; // force regenerate
}});
document.querySelectorAll('.bg-style-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        bgStyle = btn.dataset.style;
        bgCache = null;
        document.querySelectorAll('.bg-style-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    }});
}});
document.getElementById('bgPadding').addEventListener('input', (e) => {{
    bgPadding = parseInt(e.target.value);
    document.getElementById('bgPaddingVal').textContent = bgPadding + '%';
}});
document.getElementById('bgRadius').addEventListener('input', (e) => {{
    bgRadius = parseInt(e.target.value);
    document.getElementById('bgRadiusVal').textContent = bgRadius + 'px';
}});
document.getElementById('bgShadow').addEventListener('input', (e) => {{
    bgShadow = parseInt(e.target.value);
    document.getElementById('bgShadowVal').textContent = bgShadow;
}});

// --- Video ended: auto-rewind pour pouvoir relancer ---
video.addEventListener('ended', () => {{
    video.currentTime = 0;
    _smoothState.lastT = -1;
    _smoothState.cx = 0.5; _smoothState.cy = 0.5; _smoothState.zoom = 1.0;
    _smoothState.vcx = 0; _smoothState.vcy = 0; _smoothState.vz = 0;
    cursorLastClick = -100;
}});

// Click on preview canvas = play/pause
previewCanvas.addEventListener('click', () => {{
    video.paused ? video.play() : video.pause();
}});

// --- Sync webcam video with main video ---
if (webcamFileUrl) {{
    function syncWebcam() {{
        webcamVideo.currentTime = video.currentTime;
    }}
    video.addEventListener('play', () => {{
        webcamVideo.currentTime = video.currentTime;
        webcamVideo.play().catch(() => {{}});
    }});
    video.addEventListener('pause', () => {{
        webcamVideo.pause();
        webcamVideo.currentTime = video.currentTime;
    }});
    video.addEventListener('seeked', syncWebcam);
    video.addEventListener('ratechange', () => {{
        webcamVideo.playbackRate = video.playbackRate;
    }});
}}


// Init
renderList();
renderTimeline();
drawPreview();
updateOverlay();
</script>
</body>
</html>"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)

    return output_html


# --- BACKGROUND ---

def create_background_template(out_w, out_h, style="carbon"):
    """
    Pre-genere le background une seule fois (c'est le meme pour chaque frame).
    Retourne un numpy array RGB (out_h, out_w, 3).
    Styles: carbon, gradient, mesh
    """
    import numpy as np

    bg = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    # Gradient radial du centre vers les bords
    cy, cx = out_h / 2, out_w / 2
    Y, X = np.ogrid[:out_h, :out_w]
    dist = np.sqrt(((X - cx) / out_w) ** 2 + ((Y - cy) / out_h) ** 2)
    dist = dist / dist.max()  # normaliser 0-1

    if style == "carbon":
        # Gris carbone fonce avec leger gradient radial
        center_color = np.array([32, 34, 38], dtype=np.float64)
        edge_color = np.array([14, 14, 18], dtype=np.float64)

        for c in range(3):
            bg[:, :, c] = (center_color[c] + (edge_color[c] - center_color[c]) * dist).astype(np.uint8)

        # Texture subtile: micro-noise
        noise = np.random.randint(0, 6, (out_h, out_w), dtype=np.uint8)
        for c in range(3):
            bg[:, :, c] = np.clip(bg[:, :, c].astype(np.int16) + noise - 3, 0, 255).astype(np.uint8)

    elif style == "gradient":
        # Gradient lineaire diagonal: bleu sombre -> violet sombre
        tl = np.array([18, 20, 42], dtype=np.float64)  # top-left
        br = np.array([36, 18, 32], dtype=np.float64)   # bottom-right

        for y in range(out_h):
            for x in range(out_w):
                t = (x / out_w * 0.5 + y / out_h * 0.5)
                bg[y, x] = (tl + (br - tl) * t).astype(np.uint8)

    elif style == "mesh":
        # Dark with subtle mesh/grid lines
        bg[:] = [20, 22, 28]
        # Horizontal lines every 24px
        for y in range(0, out_h, 24):
            bg[y:y+1, :] = [26, 28, 34]
        # Vertical lines every 24px
        for x in range(0, out_w, 24):
            bg[:, x:x+1] = [26, 28, 34]

    return bg


def apply_background_frame(frame, bg_template, video_w, video_h, out_w, out_h,
                            padding_pct=0.06, corner_radius=12, shadow_size=20):
    """
    Place le frame video sur le background avec padding, coins arrondis et ombre.
    """
    import numpy as np

    try:
        import cv2
        has_cv2 = True
    except ImportError:
        has_cv2 = False

    result = bg_template.copy()

    # Taille de la video dans le canvas (avec padding)
    pad_x = int(out_w * padding_pct)
    pad_y = int(out_h * padding_pct)
    inner_w = out_w - 2 * pad_x
    inner_h = out_h - 2 * pad_y

    # Garder le ratio
    aspect = video_w / video_h
    if inner_w / inner_h > aspect:
        # Trop large, ajuster par hauteur
        inner_h_final = inner_h
        inner_w_final = int(inner_h * aspect)
    else:
        inner_w_final = inner_w
        inner_h_final = int(inner_w / aspect)

    # Centrer
    x_off = (out_w - inner_w_final) // 2
    y_off = (out_h - inner_h_final) // 2

    # Resize video frame
    if has_cv2:
        resized = cv2.resize(frame, (inner_w_final, inner_h_final), interpolation=cv2.INTER_LINEAR)
    else:
        ri = (np.arange(inner_h_final) * video_h / inner_h_final).astype(int)
        ci = (np.arange(inner_w_final) * video_w / inner_w_final).astype(int)
        ri = np.clip(ri, 0, video_h - 1)
        ci = np.clip(ci, 0, video_w - 1)
        resized = frame[ri][:, ci]

    # Ombre portee (blur rectangle sombre derriere la video)
    if has_cv2 and shadow_size > 0:
        sx, sy = x_off + shadow_size // 2, y_off + shadow_size // 2
        # Dessiner rectangle noir semi-transparent pour l'ombre
        shadow_region = result[max(0,sy):min(out_h, sy+inner_h_final+shadow_size),
                               max(0,sx):min(out_w, sx+inner_w_final+shadow_size)]
        shadow_layer = np.zeros_like(shadow_region)
        blended = (shadow_region.astype(np.float32) * 0.4 + shadow_layer.astype(np.float32) * 0.6).astype(np.uint8)
        result[max(0,sy):min(out_h, sy+inner_h_final+shadow_size),
               max(0,sx):min(out_w, sx+inner_w_final+shadow_size)] = blended

        # Blur l'ombre pour un effet doux
        shadow_area = result[max(0,sy-shadow_size):min(out_h, sy+inner_h_final+shadow_size*2),
                             max(0,sx-shadow_size):min(out_w, sx+inner_w_final+shadow_size*2)]
        if shadow_area.size > 0:
            ks = shadow_size * 2 + 1
            blurred = cv2.GaussianBlur(shadow_area, (ks, ks), 0)
            result[max(0,sy-shadow_size):min(out_h, sy+inner_h_final+shadow_size*2),
                   max(0,sx-shadow_size):min(out_w, sx+inner_w_final+shadow_size*2)] = blurred

    # Coins arrondis via masque
    if has_cv2 and corner_radius > 0:
        mask = np.zeros((inner_h_final, inner_w_final), dtype=np.uint8)
        r = corner_radius
        # Remplir le rectangle avec coins arrondis
        cv2.rectangle(mask, (r, 0), (inner_w_final - r, inner_h_final), 255, -1)
        cv2.rectangle(mask, (0, r), (inner_w_final, inner_h_final - r), 255, -1)
        cv2.circle(mask, (r, r), r, 255, -1)
        cv2.circle(mask, (inner_w_final - r, r), r, 255, -1)
        cv2.circle(mask, (r, inner_h_final - r), r, 255, -1)
        cv2.circle(mask, (inner_w_final - r, inner_h_final - r), r, 255, -1)

        # Appliquer masque
        mask_3ch = mask[:, :, np.newaxis].astype(np.float32) / 255.0
        bg_section = result[y_off:y_off+inner_h_final, x_off:x_off+inner_w_final].astype(np.float32)
        vid_section = resized.astype(np.float32)
        composite = vid_section * mask_3ch + bg_section * (1 - mask_3ch)
        result[y_off:y_off+inner_h_final, x_off:x_off+inner_w_final] = composite.astype(np.uint8)
    else:
        # Sans cv2: pas de coins arrondis
        result[y_off:y_off+inner_h_final, x_off:x_off+inner_w_final] = resized

    return result


def get_cursor_at_time(events, t, event_idx_hint=0):
    """
    Retrouve la position du curseur au temps t.
    Retourne (nx, ny, is_click, event_idx).
    """
    idx = event_idx_hint
    while idx < len(events) - 1 and events[idx + 1]["t"] <= t:
        idx += 1
    if idx < len(events):
        ev = events[idx]
        return ev["nx"], ev["ny"], ev.get("click", False), idx
    return 0.5, 0.5, False, idx


# --- CAPTIONS ---

def get_caption_at_time(captions, t):
    """
    Retourne le segment de caption actif au temps t, et l'index du mot actif.
    captions: { style, segments: [{ start, end, text, words: [{ word, start, end }] }] }
    """
    if not captions or not captions.get("segments"):
        return None, None, -1

    for seg in captions["segments"]:
        if seg["start"] <= t <= seg["end"]:
            active_word_idx = -1
            for wi, w in enumerate(seg.get("words", [])):
                if w["start"] <= t <= w["end"]:
                    active_word_idx = wi
                    break
            return seg, seg.get("words", []), active_word_idx
    return None, None, -1


def draw_captions_on_frame(frame, seg, words, active_word_idx, video_w, video_h, style="tiktok"):
    """
    Dessine les captions sur un frame numpy (RGB).
    style: 'tiktok' (gros centre, mot highlight) ou 'classic' (bas, fond noir)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        # Fallback: cv2 text (moche mais fonctionnel)
        return _draw_captions_cv2(frame, seg, words, active_word_idx, video_w, video_h, style)

    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img)

    # Taille de police adaptive a la resolution
    if style == "tiktok":
        font_size = max(32, int(video_h * 0.055))
    else:
        font_size = max(24, int(video_h * 0.035))

    # Essayer de charger une police bold, sinon default
    font = None
    font_bold = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]:
        try:
            font_bold = ImageFont.truetype(font_path, font_size)
            font = ImageFont.truetype(font_path.replace("Bold", "Regular").replace("bd.", ".").replace("arialbd", "arial"), font_size)
            if font is None:
                font = font_bold
            break
        except:
            continue
    if font is None:
        font = ImageFont.load_default()
        font_bold = font

    if style == "tiktok":
        _draw_tiktok_caption(draw, words, active_word_idx, video_w, video_h, font, font_bold, font_size)
    else:
        _draw_classic_caption(draw, seg, words, active_word_idx, video_w, video_h, font, font_bold, font_size)

    import numpy as np
    return np.array(img)


def _draw_tiktok_caption(draw, words, active_word_idx, video_w, video_h, font, font_bold, font_size):
    """Style TikTok: gros texte centre, mot actif en couleur"""
    if not words:
        return

    # Regrouper les mots en lignes de ~4-6 mots max
    lines = []
    current_line = []
    max_words_per_line = max(3, min(6, len(words) // 2 + 1))
    for wi, w in enumerate(words):
        current_line.append((wi, w["word"]))
        if len(current_line) >= max_words_per_line:
            lines.append(current_line)
            current_line = []
    if current_line:
        lines.append(current_line)

    # Trouver la ligne qui contient le mot actif
    active_line_idx = 0
    for li, line in enumerate(lines):
        for wi, _ in line:
            if wi == active_word_idx:
                active_line_idx = li

    # N'afficher que la ligne active (+ eventuellement la suivante)
    display_lines = [lines[active_line_idx]] if active_line_idx < len(lines) else [lines[-1]]

    # Position: centre vertical, un peu en dessous du milieu
    y_center = int(video_h * 0.72)

    for li, line in enumerate(display_lines):
        # Calculer la largeur totale de la ligne
        full_text = " ".join(w for _, w in line)
        bbox = draw.textbbox((0, 0), full_text, font=font_bold)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]

        x_start = (video_w - line_w) // 2
        y_pos = y_center + li * int(font_size * 1.4)

        # Fond semi-transparent (arrondi)
        pad = int(font_size * 0.4)
        bg_box = [x_start - pad, y_pos - pad // 2, x_start + line_w + pad, y_pos + line_h + pad]
        draw.rounded_rectangle(bg_box, radius=int(font_size * 0.3), fill=(0, 0, 0, 180))

        # Dessiner mot par mot
        x = x_start
        for wi, word in line:
            f = font_bold
            if wi == active_word_idx:
                color = (233, 69, 96)  # Rouge Recastr
            else:
                color = (255, 255, 255)

            draw.text((x, y_pos), word, font=f, fill=color)
            wbbox = draw.textbbox((0, 0), word + " ", font=f)
            x += wbbox[2] - wbbox[0]


def _draw_classic_caption(draw, seg, words, active_word_idx, video_w, video_h, font, font_bold, font_size):
    """Style classique: texte en bas, fond noir semi-transparent"""
    text = seg["text"] if seg else ""
    if not text:
        return

    # Word wrap: couper en lignes qui rentrent dans ~80% de la largeur
    max_w = int(video_w * 0.8)
    text_words = text.split()
    lines = []
    current = ""
    for w in text_words:
        test = current + (" " if current else "") + w
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_w and current:
            lines.append(current)
            current = w
        else:
            current = test
    if current:
        lines.append(current)

    if not lines:
        return

    line_h = int(font_size * 1.4)
    total_h = line_h * len(lines)
    y_start = video_h - total_h - int(video_h * 0.06)

    # Fond noir semi-transparent
    pad = int(font_size * 0.5)
    max_line_w = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        max_line_w = max(max_line_w, bbox[2] - bbox[0])

    bg_x = (video_w - max_line_w) // 2
    draw.rounded_rectangle(
        [bg_x - pad, y_start - pad, bg_x + max_line_w + pad, y_start + total_h + pad],
        radius=8, fill=(0, 0, 0, 180)
    )

    # Texte
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (video_w - lw) // 2
        y = y_start + i * line_h
        draw.text((x, y), line, font=font, fill=(255, 255, 255))


def _draw_captions_cv2(frame, seg, words, active_word_idx, video_w, video_h, style):
    """Fallback cv2 si PIL pas disponible"""
    try:
        import cv2
    except ImportError:
        return frame

    text = seg["text"] if seg else ""
    if not text:
        return frame

    font_scale = max(0.8, video_h / 1000)
    thickness = max(1, int(font_scale * 2))

    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)

    if style == "tiktok":
        y = int(video_h * 0.72)
    else:
        y = video_h - int(video_h * 0.06)

    x = (video_w - tw) // 2

    # Fond
    cv2.rectangle(frame, (x - 10, y - th - 10), (x + tw + 10, y + 10), (0, 0, 0), -1)
    # Texte
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), thickness)

    return frame


# --- WEBCAM OVERLAY ---

def overlay_webcam(frame, cam_frame, out_w, out_h, webcam_config):
    """
    Composite la webcam sur le frame de sortie.
    cam_frame: frame de la webcam (fichier separe) OU crop du frame original (legacy).
               Si None, on skip.
    webcam_config: { out_nx, out_ny, out_nw, out_nh, shape, border, border_color }
    """
    import numpy as np
    if cam_frame is None:
        return frame

    try:
        import cv2
        has_cv2 = True
    except ImportError:
        has_cv2 = False

    cam_h, cam_w = cam_frame.shape[:2]
    if cam_w < 10 or cam_h < 10:
        return frame

    dst_x = int(webcam_config.get("out_nx", 0.78) * out_w)
    dst_y = int(webcam_config.get("out_ny", 0.78) * out_h)
    dst_w = int(webcam_config.get("out_nw", 0.2) * out_w)
    dst_h = int(webcam_config.get("out_nh", 0.2) * out_h)

    # Clamp to frame bounds
    if dst_x + dst_w > out_w:
        dst_w = out_w - dst_x
    if dst_y + dst_h > out_h:
        dst_h = out_h - dst_y
    if dst_w < 10 or dst_h < 10:
        return frame

    # Center-crop source to match destination aspect ratio (prevents distortion)
    dst_aspect = dst_w / max(dst_h, 1)
    cam_aspect = cam_w / max(cam_h, 1)
    if abs(cam_aspect - dst_aspect) > 0.05:
        if cam_aspect > dst_aspect:
            # Source is wider — crop sides
            new_w = int(cam_h * dst_aspect)
            x_off = (cam_w - new_w) // 2
            cam_frame = cam_frame[:, x_off:x_off+new_w]
        else:
            # Source is taller — crop top/bottom
            new_h = int(cam_w / dst_aspect)
            y_off = (cam_h - new_h) // 2
            cam_frame = cam_frame[y_off:y_off+new_h, :]
        cam_h, cam_w = cam_frame.shape[:2]

    if has_cv2:
        cam_resized = cv2.resize(cam_frame, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)
    else:
        ri = (np.arange(dst_h) * cam_h / dst_h).astype(int)
        ci = (np.arange(dst_w) * cam_w / dst_w).astype(int)
        ri = np.clip(ri, 0, cam_h - 1)
        ci = np.clip(ci, 0, cam_w - 1)
        cam_resized = cam_frame[ri][:, ci]

    shape = webcam_config.get("shape", "circle")
    border = webcam_config.get("border", 3)
    border_color = webcam_config.get("border_color", (255, 255, 255))

    if shape == "circle" and has_cv2:
        mask = np.zeros((dst_h, dst_w), dtype=np.uint8)
        center = (dst_w // 2, dst_h // 2)
        radius = min(dst_w, dst_h) // 2
        cv2.circle(mask, center, radius, 255, -1)

        roi = frame[dst_y:dst_y+dst_h, dst_x:dst_x+dst_w]
        mask_3d = mask[:, :, np.newaxis] > 0
        roi[:] = np.where(mask_3d, cam_resized, roi)

        if border > 0:
            cv2.circle(frame, (dst_x + center[0], dst_y + center[1]), radius, border_color, border)

    elif shape == "rounded" and has_cv2:
        r = min(dst_w, dst_h) // 6
        mask = np.zeros((dst_h, dst_w), dtype=np.uint8)
        cv2.rectangle(mask, (r, 0), (dst_w - r, dst_h), 255, -1)
        cv2.rectangle(mask, (0, r), (dst_w, dst_h - r), 255, -1)
        cv2.circle(mask, (r, r), r, 255, -1)
        cv2.circle(mask, (dst_w - r, r), r, 255, -1)
        cv2.circle(mask, (r, dst_h - r), r, 255, -1)
        cv2.circle(mask, (dst_w - r, dst_h - r), r, 255, -1)

        roi = frame[dst_y:dst_y+dst_h, dst_x:dst_x+dst_w]
        mask_3d = mask[:, :, np.newaxis] > 0
        roi[:] = np.where(mask_3d, cam_resized, roi)

        if border > 0:
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            offset_contours = [cnt + np.array([dst_x, dst_y]) for cnt in contours]
            cv2.drawContours(frame, offset_contours, -1, border_color, border)
    else:
        frame[dst_y:dst_y+dst_h, dst_x:dst_x+dst_w] = cam_resized
        if border > 0 and has_cv2:
            cv2.rectangle(frame, (dst_x, dst_y), (dst_x+dst_w, dst_y+dst_h), border_color, border)

    return frame


# --- RENDER ---

def render_video(input_path, output_path, frame_data, fps, video_w, video_h,
                 background=None, captions=None, webcam=None, webcam_file=None):
    """
    background: None ou dict { style, padding, shadow, corner_radius }
    captions: None ou dict { style: 'tiktok'|'classic', segments: [...] }
    webcam: None ou dict { out_nx, out_ny, out_nw, out_nh, shape, border }
    webcam_file: None ou chemin vers un fichier video webcam separe
    """
    print(f"\n  Rendering {len(frame_data)} frames...")
    if background:
        print(f"  Background: {background['style']} (padding {background['padding']:.0%})")
    if captions and captions.get("segments"):
        print(f"  Captions: {captions.get('style', 'tiktok')} ({len(captions['segments'])} segments)")
    if webcam:
        print(f"  Webcam: {webcam.get('shape', 'circle')} @ ({webcam.get('out_nx', webcam.get('nx', 0.7)):.2f}, {webcam.get('out_ny', webcam.get('ny', 0.7)):.2f})")
    print(f"  Sortie: {output_path}\n")

    frame_size = video_w * video_h * 3

    # Output resolution: same as input (background fits within)
    out_w = video_w
    out_h = video_h

    decode_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", f"fps={fps}",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"
    ]
    encode_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{out_w}x{out_h}", "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(input_path),
        "-map", "0:v", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-shortest",
        str(output_path)
    ]

    try:
        import numpy as np
    except ImportError:
        print("  ERREUR: numpy requis. pip install numpy")
        sys.exit(1)

    try:
        import cv2
        has_cv2 = True
    except ImportError:
        has_cv2 = False
        print("  Note: opencv absent, qualite reduite. pip install opencv-python")

    # Pre-generer le background
    bg_template = None
    if background:
        print("  Generation du background template...")
        bg_template = create_background_template(
            out_w, out_h, style=background.get("style", "carbon")
        )

    decoder = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    # Webcam decoder (fichier separe)
    cam_decoder = None
    cam_frame_size = 0
    cam_w_px, cam_h_px = 0, 0
    if webcam and webcam_file:
        # Get webcam video dimensions
        try:
            cam_w_px, cam_h_px, _, _ = get_video_info(str(webcam_file))
            cam_frame_size = cam_w_px * cam_h_px * 3
            cam_decode_cmd = [
                "ffmpeg", "-y", "-i", str(webcam_file),
                "-vf", f"fps={fps}",
                "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"
            ]
            cam_decoder = subprocess.Popen(cam_decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            print(f"  Webcam file: {webcam_file} ({cam_w_px}x{cam_h_px})")
        except Exception as e:
            print(f"  ATTENTION: Impossible de lire le fichier webcam: {e}")
            cam_decoder = None

    frame_num = 0
    zoomed = 0
    # Variables for zoom crop coords used by cursor positioning
    x1, y1, cw, ch = 0, 0, video_w, video_h

    try:
        while True:
            raw = decoder.stdout.read(frame_size)
            if len(raw) < frame_size:
                break

            if frame_num < len(frame_data):
                zoom, cx_n, cy_n = frame_data[frame_num]
            else:
                zoom = 1.0

            frame = np.frombuffer(raw, dtype=np.uint8).reshape((video_h, video_w, 3)).copy()

            # Lire le frame webcam (fichier separe)
            cam_frame = None
            if cam_decoder:
                cam_raw = cam_decoder.stdout.read(cam_frame_size)
                if len(cam_raw) == cam_frame_size:
                    cam_frame = np.frombuffer(cam_raw, dtype=np.uint8).reshape((cam_h_px, cam_w_px, 3)).copy()

            # Legacy: extraire webcam du frame original (si pas de fichier separe)
            original_frame = None
            if webcam and not webcam_file and webcam.get("nx") is not None:
                original_frame = frame.copy()

            if zoom > 1.02:
                cw = int(video_w / zoom)
                ch = int(video_h / zoom)
                cx = int(cx_n * video_w)
                cy = int(cy_n * video_h)

                x1 = max(0, min(cx - cw//2, video_w - cw))
                y1 = max(0, min(cy - ch//2, video_h - ch))

                cropped = frame[y1:y1+ch, x1:x1+cw]

                if has_cv2:
                    frame = cv2.resize(cropped, (video_w, video_h), interpolation=cv2.INTER_LINEAR)
                else:
                    ri = (np.arange(video_h) * ch / video_h).astype(int)
                    ci = (np.arange(video_w) * cw / video_w).astype(int)
                    ri = np.clip(ri, 0, ch-1)
                    ci = np.clip(ci, 0, cw-1)
                    frame = cropped[ri][:, ci]

                zoomed += 1

            if bg_template is not None:
                frame = apply_background_frame(
                    frame, bg_template, video_w, video_h, out_w, out_h,
                    padding_pct=background.get("padding", 0.06),
                    corner_radius=background.get("border_radius", 12),
                    shadow_size=20 if background.get("inset_shadow", True) else 0,
                )

            # Webcam overlay
            if webcam:
                if cam_frame is not None:
                    # Fichier webcam separe (haute qualite)
                    frame = overlay_webcam(frame, cam_frame, out_w, out_h, webcam)
                elif original_frame is not None:
                    # Legacy: extraire du frame original (avant zoom)
                    src_x = int(webcam.get("nx", 0) * video_w)
                    src_y = int(webcam.get("ny", 0) * video_h)
                    src_w = int(webcam.get("nw", 0.2) * video_w)
                    src_h = int(webcam.get("nh", 0.2) * video_h)
                    src_x = max(0, min(src_x, video_w - 1))
                    src_y = max(0, min(src_y, video_h - 1))
                    src_w = min(src_w, video_w - src_x)
                    src_h = min(src_h, video_h - src_y)
                    if src_w >= 10 and src_h >= 10:
                        cam_crop = original_frame[src_y:src_y+src_h, src_x:src_x+src_w]
                        frame = overlay_webcam(frame, cam_crop, out_w, out_h, webcam)

            # Captions overlay
            if captions and captions.get("segments"):
                t = frame_num / fps
                cap_style = captions.get("style", "tiktok")
                seg, words, active_idx = get_caption_at_time(captions, t)
                if seg:
                    frame = draw_captions_on_frame(frame, seg, words, active_idx, out_w, out_h, cap_style)

            encoder.stdin.write(frame.tobytes())

            frame_num += 1
            if frame_num % (fps * 3) == 0:
                pct = frame_num / max(len(frame_data), 1) * 100
                print(f"  {frame_num/fps:.0f}s ({pct:.0f}%) - {zoomed} frames zoomees")

    finally:
        decoder.stdout.close()
        encoder.stdin.close()
        decoder.wait()
        encoder.wait()
        if cam_decoder:
            cam_decoder.stdout.close()
            cam_decoder.wait()

    print(f"\n  Done! {zoomed}/{frame_num} frames zoomees")


# --- DEBUG: dessiner le curseur sur la video ---

def render_debug_video(input_path, output_path, events, fps, video_w, video_h, video_duration):
    """
    Genere une video de debug: la video originale avec un point vert
    qui suit le curseur + cercles rouges sur les clics.
    Permet de voir si le mapping des coordonnees est correct.
    """
    print(f"\n  DEBUG: rendering cursor trail sur la video...")
    print(f"  Point vert = position curseur")
    print(f"  Cercle rouge = clic")
    print(f"  Si le point suit bien ta souris dans la video, les coords sont bonnes!\n")

    frame_size = video_w * video_h * 3

    try:
        import numpy as np
    except ImportError:
        print("  ERREUR: numpy requis"); sys.exit(1)

    try:
        import cv2
        has_cv2 = True
    except ImportError:
        has_cv2 = False

    decode_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", f"fps={fps}",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"
    ]
    encode_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{video_w}x{video_h}", "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(input_path),
        "-map", "0:v", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-shortest",
        str(output_path)
    ]

    # Pre-indexer les events par temps
    # Pour chaque frame, trouver la position du curseur
    event_idx = 0

    # Collecter les clics recents pour dessiner des cercles qui fade
    recent_clicks = []  # (frame_num, px, py)

    decoder = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    frame_num = 0

    try:
        while True:
            raw = decoder.stdout.read(frame_size)
            if len(raw) < frame_size:
                break

            frame = np.frombuffer(raw, dtype=np.uint8).reshape((video_h, video_w, 3)).copy()
            t = frame_num / fps

            # Trouver l'event le plus proche de ce timestamp
            while event_idx < len(events) - 1 and events[event_idx + 1]["t"] <= t:
                event_idx += 1

            if event_idx < len(events):
                ev = events[event_idx]
                px = int(ev["nx"] * video_w)
                py = int(ev["ny"] * video_h)

                # Dessiner le curseur (point vert)
                if has_cv2:
                    cv2.circle(frame, (px, py), 8, (0, 255, 100), -1)  # filled
                    cv2.circle(frame, (px, py), 10, (255, 255, 255), 2)  # border
                else:
                    # Fallback sans cv2: carre
                    r = 8
                    y1, y2 = max(0, py-r), min(video_h, py+r)
                    x1, x2 = max(0, px-r), min(video_w, px+r)
                    frame[y1:y2, x1:x2] = [0, 255, 100]

                # Si clic, ajouter au recent_clicks
                if ev.get("click") and ev.get("in", True):
                    recent_clicks.append((frame_num, px, py))

            # Dessiner les clics recents (cercle rouge qui s'agrandit et fade)
            new_recent = []
            for (cf, cx, cy) in recent_clicks:
                age = frame_num - cf
                if age < fps * 1.5:  # visible 1.5 sec
                    radius = 15 + age // 2
                    alpha = max(0, 1.0 - age / (fps * 1.5))
                    color = (int(255 * alpha), int(50 * alpha), int(50 * alpha))
                    thickness = max(1, int(3 * alpha))

                    if has_cv2:
                        cv2.circle(frame, (cx, cy), radius, color, thickness)
                        if age < 5:
                            cv2.putText(frame, "CLICK", (cx + 15, cy - 15),
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 80, 80), 2)
                    new_recent.append((cf, cx, cy))
            recent_clicks = new_recent

            # Label en haut a gauche
            if has_cv2 and event_idx < len(events):
                ev = events[event_idx]
                label = f"cursor: ({ev['nx']:.3f}, {ev['ny']:.3f}) -> px({px},{py})"
                cv2.putText(frame, label, (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 100), 2)
                cv2.putText(frame, f"t={t:.2f}s", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

            encoder.stdin.write(frame.tobytes())
            frame_num += 1

            if frame_num % (fps * 3) == 0:
                print(f"  {frame_num/fps:.0f}s processed")

    finally:
        decoder.stdout.close()
        encoder.stdin.close()
        decoder.wait()
        encoder.wait()

    print(f"\n  Video debug: {output_path}")
    print(f"  Regarde si le point vert suit bien ta souris!")


def main():
    parser = argparse.ArgumentParser(description="Recastr")
    parser.add_argument("video", help="Video (ex: recording.mp4)")
    parser.add_argument("cursor_log", help="Cursor log JSON")
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--offset", type=float, default=0.0,
                        help="Offset timing en secondes")
    parser.add_argument("--zoom-click", type=float, default=2.0)
    parser.add_argument("--zoom-still", type=float, default=1.5)
    parser.add_argument("--hold-click", type=float, default=1.5)
    parser.add_argument("--hold-still", type=float, default=3.0)
    parser.add_argument("--edit", action="store_true",
                        help="Ouvrir l'editeur visuel dans le browser")
    parser.add_argument("--preview", action="store_true",
                        help="Alias pour --edit")
    parser.add_argument("--debug", action="store_true",
                        help="Genere une video debug avec curseur dessine")
    parser.add_argument("--use-edited", default=None,
                        help="Utiliser un JSON de zooms edite (export de l'editeur)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--background", "--bg", default=None,
                        choices=["carbon", "gradient", "mesh"],
                        help="Ajouter un background sombre (carbon/gradient/mesh)")
    parser.add_argument("--bg-padding", type=float, default=0.06,
                        help="Padding du background (0.04=4%% a 0.15=15%%)")
    parser.add_argument("--bg-shadow", type=int, default=20,
                        help="Taille de l'ombre (0=aucune, 20=normal, 40=fort)")
    parser.add_argument("--bg-radius", type=int, default=12,
                        help="Rayon des coins arrondis (0=carres, 12=normal)")
    parser.add_argument("--captions", action="store_true",
                        help="Transcrire l'audio avec Whisper et ajouter des captions")
    parser.add_argument("--caption-model", default="base",
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Modele Whisper (tiny=rapide, large=precis)")
    parser.add_argument("--caption-lang", default=None,
                        help="Langue pour Whisper (ex: fr, en). Auto-detect si omis")
    parser.add_argument("--caption-style", default="tiktok",
                        choices=["tiktok", "classic"],
                        help="Style des captions (tiktok=gros centre, classic=bas)")
    parser.add_argument("--webcam", action="store_true",
                        help="Activer la webcam overlay")
    parser.add_argument("--webcam-file", default=None,
                        help="Fichier video webcam separe (ex: camera.mp4). Meilleure qualite qu'extraire du recording.")
    parser.add_argument("--webcam-shape", default="circle",
                        choices=["circle", "rounded", "rectangle"],
                        help="Forme de la webcam overlay (circle/rounded/rectangle)")
    parser.add_argument("--webcam-pos", default="bottom-right",
                        help="Position de la webcam: 'bottom-right', 'bottom-left', 'top-right', 'top-left'")
    parser.add_argument("--webcam-size", type=float, default=0.2,
                        help="Taille de la webcam (fraction de la largeur video, ex: 0.2 = 20%%)")
    args = parser.parse_args()

    video_path = Path(args.video)
    log_path = Path(args.cursor_log)

    if not video_path.exists():
        print(f"  ERREUR: {video_path} introuvable"); sys.exit(1)
    if not log_path.exists():
        print(f"  ERREUR: {log_path} introuvable"); sys.exit(1)
    if not shutil.which("ffmpeg"):
        print("  ERREUR: FFmpeg manquant. winget install FFmpeg"); sys.exit(1)

    if args.output is None:
        args.output = str(video_path.stem) + "_zoomed.mp4"

    print("=" * 50)
    print("  RECASTR")
    print("=" * 50)

    # Charger
    print("\n  Chargement log...")
    metadata, events = load_cursor_log(log_path)
    print(f"  {len(events)} samples, {metadata.get('duration', 0):.1f}s")

    if "capture_window" in metadata:
        print(f"  Fenetre capturee: {metadata['capture_window']}")

    # Webcam info from cursor log
    webcam_from_log = metadata.get("webcam")
    if webcam_from_log:
        print(f"  Webcam detectee: {webcam_from_log.get('name', '?')} ({webcam_from_log['nw']:.0%} x {webcam_from_log['nh']:.0%})")

    # Offset
    if args.offset != 0:
        print(f"  Offset: {args.offset:+.2f}s")
        for ev in events:
            ev["t"] += args.offset
        events = [e for e in events if e["t"] >= 0]

    # Video
    print("  Analyse video...")
    video_w, video_h, video_duration, video_fps = get_video_info(str(video_path))
    print(f"  {video_w}x{video_h}, {video_duration:.1f}s, {video_fps:.0f}fps")

    # Detect zooms
    config = {
        "zoom_click": args.zoom_click,
        "zoom_still": args.zoom_still,
        "hold_click": args.hold_click,
        "hold_still": args.hold_still,
    }
    print("\n  Detection des zooms...")
    zoom_events = detect_zoom_events(events, config)

    clicks = sum(1 for z in zoom_events if z["type"] == "click")
    stills = sum(1 for z in zoom_events if z["type"] == "still")
    print(f"  {clicks} clics + {stills} pauses = {len(zoom_events)} zooms")

    if not zoom_events:
        print("\n  Aucun zoom detecte!")
        sys.exit(0)

    # Afficher les zooms
    print(f"\n  {'TIME':>8}  {'TYPE':>6}  {'ZOOM':>5}  {'POS':>12}  {'DUR':>5}")
    for ze in zoom_events:
        t = ze["time"]
        dur = ze["ease_in"] + ze["hold"] + ze["ease_out"]
        print(f"  {int(t//60):02d}:{t%60:05.2f}  {ze['type']:>6}  {ze['zoom']:.1f}x  ({ze['nx']:.2f},{ze['ny']:.2f})  {dur:.1f}s")

    # Captions (Whisper)
    caption_segments = None
    if args.captions:
        print("\n  Transcription audio (Whisper)...")
        caption_segments = transcribe_video(str(video_path), model_name=args.caption_model, language=args.caption_lang)
        if caption_segments:
            print(f"  {len(caption_segments)} segments de captions prets")
        else:
            print("  Transcription echouee, captions desactivees")

    # Debug mode: dessiner le curseur sur la video
    if args.debug:
        debug_output = str(video_path.stem) + "_debug.mp4"
        render_debug_video(str(video_path), debug_output, events, args.fps, video_w, video_h, video_duration)
        print(f"\n  Ouvre {debug_output} et verifie que le point vert suit ta souris.")
        print("  Si le point est decale, le probleme est dans le mapping coords.")
        print("  Si le point est bon, le probleme est dans le zoom rendering.")
        sys.exit(0)

    # Editeur HTML
    if args.preview or args.edit:
        editor_path = str(video_path.stem) + "_editor.html"
        edited_json_path = str(video_path.stem) + "_zoom_events_edited.json"
        print(f"\n  Generation de l'editeur...")

        # Serveur HTTP local pour que le browser puisse charger la video
        import http.server
        import socketserver
        import functools

        # Trouver les dossiers a servir (dossier video + dossier courant + webcam)
        video_dir = os.path.dirname(os.path.abspath(str(video_path)))
        cwd = os.getcwd()
        extra_dirs = [video_dir]

        # Webcam file?
        webcam_file_for_editor = args.webcam_file
        webcam_filename = None
        if webcam_file_for_editor:
            wf_abs = os.path.abspath(webcam_file_for_editor)
            wf_dir = os.path.dirname(wf_abs)
            webcam_filename = os.path.basename(wf_abs)
            if wf_dir not in extra_dirs and wf_dir != cwd:
                extra_dirs.append(wf_dir)

        # Generer l'editeur avec un chemin relatif via le serveur HTTP
        server_port = 0  # Port auto
        video_filename = os.path.basename(str(video_path))

        class MultiDirHandler(http.server.SimpleHTTPRequestHandler):
            """Handler qui sert les fichiers du CWD et des dossiers extra."""
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=cwd, **kw)

            def translate_path(self, path):
                # D'abord chercher dans le CWD
                local = super().translate_path(path)
                if os.path.exists(local):
                    return local
                # Sinon chercher dans les dossiers extra
                rel = path.lstrip("/")
                for d in extra_dirs:
                    candidate = os.path.join(d, rel)
                    if os.path.exists(candidate):
                        return candidate
                return local

            def log_message(self, format, *a):
                pass  # Silencieux

        server = socketserver.TCPServer(("127.0.0.1", 0), MultiDirHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        print(f"  Serveur local: http://127.0.0.1:{server_port}")

        webcam_file_url = None
        if webcam_filename:
            webcam_file_url = f"http://127.0.0.1:{server_port}/{webcam_filename}"
            print(f"  Webcam file: {webcam_file_url}")

        # Generer l'editeur avec l'URL du serveur local pour la video
        generate_editor_html(
            f"http://127.0.0.1:{server_port}/{video_filename}",
            zoom_events, video_w, video_h, video_duration,
            editor_path, edited_json_path,
            cursor_events=events, caption_segments=caption_segments,
            webcam_info=webcam_from_log,
            webcam_file_url=webcam_file_url
        )
        print(f"  Ouverture: {editor_path}")

        editor_url = f"http://127.0.0.1:{server_port}/{editor_path}"
        try:
            webbrowser.open(editor_url)
        except:
            print(f"  Ouvre manuellement: {editor_url}")

        print("\n  Dans l'editeur:")
        print("    - Supprime les zooms inutiles")
        print("    - Ajuste le niveau de zoom et la duree avec les sliders")
        print("    - Clique 'Exporter et Render' quand t'es content")
        print("    - Puis relance avec --use-edited zoom_events_edited.json")
        # Garder le serveur ouvert
        if sys.stdin.isatty():
            # Mode terminal: attendre que l'utilisateur appuie Enter
            print("\n  >>> Le serveur tourne. Appuie ENTER pour fermer. <<<")
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                pass
            finally:
                server.shutdown()
        else:
            # Mode GUI/pipe: garder le serveur ouvert longtemps (le GUI gere la fermeture)
            print("\n  Editeur ouvert. Le serveur reste actif en arriere-plan.")
            try:
                server_thread.join()
            except (KeyboardInterrupt, EOFError):
                server.shutdown()
        sys.exit(0)

    # Render config
    bg_config = None
    if args.background:
        bg_config = {
            "style": args.background,
            "padding": args.bg_padding,
            "shadow": args.bg_shadow,
            "corner_radius": args.bg_radius,
        }

    # Init pour le webcam file (peut etre set par --webcam-file ou par le JSON edite)
    webcam_file_path = None

    # Charger les zooms edites si fournis
    if args.use_edited:
        edited_path = Path(args.use_edited)
        if not edited_path.exists():
            print(f"  ERREUR: {edited_path} introuvable")
            sys.exit(1)
        with open(edited_path) as f:
            edited = json.load(f)

        # Support both old format (list) and new format (dict with zooms + background + captions)
        if isinstance(edited, dict):
            zoom_events = edited.get("zooms", [])
            if edited.get("background") and not bg_config:
                bg_info = edited["background"]
                bg_config = {
                    "style": bg_info.get("style", "carbon"),
                    "padding": bg_info.get("padding", 0.06),
                    "shadow": bg_info.get("shadow", 20),
                    "corner_radius": bg_info.get("corner_radius", 12),
                }
                print(f"  Background du JSON: {bg_config['style']}")
            if edited.get("captions"):
                cap_info = edited["captions"]
                caption_segments = cap_info.get("segments", [])
                caption_config = {
                    "style": cap_info.get("style", args.caption_style),
                    "segments": caption_segments,
                }
                print(f"  Captions du JSON: {cap_info.get('style', 'tiktok')} ({len(caption_segments)} segments)")
            if edited.get("webcam"):
                webcam_config = edited["webcam"]
                if edited.get("webcam_file"):
                    webcam_file_path = edited["webcam_file"]
                    print(f"  Webcam du JSON: {webcam_config.get('shape', 'circle')} (fichier: {webcam_file_path})")
                else:
                    print(f"  Webcam du JSON: {webcam_config.get('shape', 'circle')}")
        else:
            zoom_events = edited

        print(f"\n  Zooms edites charges: {len(zoom_events)} zooms")

    # Build caption config for render
    try:
        caption_config
    except NameError:
        # Not set by edited JSON — build from transcription if available
        caption_config = None
        if caption_segments:
            caption_config = {
                "style": args.caption_style,
                "segments": caption_segments,
            }

    # Build webcam config
    webcam_config = None
    webcam_file_path = None
    try:
        webcam_config  # may have been set by edited JSON
    except NameError:
        webcam_config = None

    if webcam_config is None and (args.webcam or args.webcam_file):
        # Fichier webcam separe (nouvelle methode, meilleure qualite)
        if args.webcam_file:
            wf = Path(args.webcam_file)
            if not wf.exists():
                print(f"  ERREUR: Fichier webcam introuvable: {wf}")
                sys.exit(1)
            webcam_file_path = str(wf)
            print(f"  Webcam: fichier separe ({wf.name})")

        # Calculer position et taille
        size = args.webcam_size or 0.2
        # Aspect ratio: si on a un fichier webcam, calculer depuis le fichier
        if webcam_file_path:
            try:
                cw_, ch_, _, _ = get_video_info(webcam_file_path)
                aspect = cw_ / max(ch_, 1)
            except:
                aspect = 16/9
        elif webcam_from_log:
            aspect = webcam_from_log["nw"] / max(webcam_from_log["nh"], 0.01)
        else:
            aspect = 16/9

        out_nh = size / aspect
        margin = 0.02

        webcam_config = {
            "shape": args.webcam_shape,
            "border": 3,
            "border_color": (255, 255, 255),
            "out_nw": size,
            "out_nh": out_nh,
        }

        # Legacy: garder les coords source pour le mode extraction
        if not webcam_file_path and webcam_from_log:
            webcam_config["nx"] = webcam_from_log["nx"]
            webcam_config["ny"] = webcam_from_log["ny"]
            webcam_config["nw"] = webcam_from_log["nw"]
            webcam_config["nh"] = webcam_from_log["nh"]

        pos = args.webcam_pos or "bottom-right"
        if pos == "bottom-right":
            webcam_config["out_nx"] = 1.0 - size - margin
            webcam_config["out_ny"] = 1.0 - out_nh - margin
        elif pos == "bottom-left":
            webcam_config["out_nx"] = margin
            webcam_config["out_ny"] = 1.0 - out_nh - margin
        elif pos == "top-right":
            webcam_config["out_nx"] = 1.0 - size - margin
            webcam_config["out_ny"] = margin
        elif pos == "top-left":
            webcam_config["out_nx"] = margin
            webcam_config["out_ny"] = margin
        else:
            webcam_config["out_nx"] = 1.0 - size - margin
            webcam_config["out_ny"] = 1.0 - out_nh - margin

        src_label = "fichier separe" if webcam_file_path else "extraction OBS"
        print(f"  Webcam overlay: {args.webcam_shape} @ {pos} ({src_label})")

    elif not (args.webcam or args.webcam_file) and webcam_config:
        # From edited JSON
        pass

    print("\n  Calcul keyframes...")
    frame_data = compute_frame_data(zoom_events, video_duration, args.fps)
    render_video(str(video_path), args.output, frame_data, args.fps, video_w, video_h,
                 background=bg_config, captions=caption_config, webcam=webcam_config,
                 webcam_file=webcam_file_path)

    print()
    print("=" * 50)
    print(f"  Video: {args.output}")
    print("=" * 50)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n  === ERREUR ===")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print(f"\n  Appuie Enter pour fermer...")
        input()
