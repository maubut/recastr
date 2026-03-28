"""
AutoZoom GUI - Interface graphique pour AutoZoom
Double-clic pour lancer. Pas de dependance extra (tkinter est inclus dans Python).
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import os
import sys
import json
import glob
from pathlib import Path
from datetime import datetime


# Couleurs
BG = "#1a1a2e"
BG2 = "#16213e"
BG3 = "#0f3460"
RED = "#e94560"
GREEN = "#00b894"
PURPLE = "#6c5ce7"
YELLOW = "#f0c040"
TEXT = "#eeeeee"
TEXT2 = "#aaaaaa"
TEXT3 = "#666666"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class AutoZoomApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoZoom")
        self.root.configure(bg=BG)
        self.root.geometry("680x780")
        self.root.minsize(600, 700)

        # State
        self.video_path = tk.StringVar()
        self.log_path = tk.StringVar()
        self.edited_path = tk.StringVar()
        self.logging_process = None

        # Options
        self.opt_captions = tk.BooleanVar(value=False)
        self.opt_webcam = tk.BooleanVar(value=False)
        self.opt_bg = tk.BooleanVar(value=False)
        self.bg_style = tk.StringVar(value="carbon")
        self.caption_style = tk.StringVar(value="tiktok")
        self.caption_model = tk.StringVar(value="base")
        self.webcam_shape = tk.StringVar(value="circle")
        self.webcam_pos = tk.StringVar(value="bottom-right")
        self.webcam_file_path = tk.StringVar()

        self.build_ui()
        self.auto_detect_files()

    def build_ui(self):
        # --- Header ---
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 0))

        tk.Label(header, text="AutoZoom", font=("Segoe UI", 22, "bold"),
                 fg=RED, bg=BG).pack(side="left")
        tk.Label(header, text="v4", font=("Segoe UI", 12),
                 fg=TEXT3, bg=BG).pack(side="left", padx=(8, 0), pady=(10, 0))

        # --- Status bar ---
        self.status_var = tk.StringVar(value="Pret.")
        self.status_label = tk.Label(self.root, textvariable=self.status_var,
                                     font=("Segoe UI", 9), fg=TEXT2, bg=BG, anchor="w")
        self.status_label.pack(fill="x", padx=24, pady=(2, 8))

        # --- Main scrollable area ---
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        # === STEP 1: Logging ===
        self.section(main, "1. Enregistrer", RED)
        log_frame = tk.Frame(main, bg=BG2, highlightbackground="#2a2a4a",
                             highlightthickness=1)
        log_frame.pack(fill="x", pady=(0, 16))

        log_inner = tk.Frame(log_frame, bg=BG2)
        log_inner.pack(fill="x", padx=16, pady=12)

        tk.Label(log_inner, text="Lance le logging avant d'enregistrer dans OBS.",
                 font=("Segoe UI", 9), fg=TEXT2, bg=BG2).pack(anchor="w")

        log_btns = tk.Frame(log_inner, bg=BG2)
        log_btns.pack(fill="x", pady=(8, 0))

        self.btn_start_log = self.make_btn(log_btns, "▶  Start Logging (OBS)", GREEN,
                                           self.start_logging)
        self.btn_start_log.pack(side="left")

        self.btn_stop_log = self.make_btn(log_btns, "■  Stop", RED,
                                          self.stop_logging, state="disabled")
        self.btn_stop_log.pack(side="left", padx=(8, 0))

        self.log_status = tk.Label(log_inner, text="", font=("Segoe UI", 8),
                                   fg=YELLOW, bg=BG2)
        self.log_status.pack(anchor="w", pady=(4, 0))

        # OBS output folder
        obs_folder_row = tk.Frame(log_inner, bg=BG2)
        obs_folder_row.pack(fill="x", pady=(6, 0))
        tk.Label(obs_folder_row, text="Dossier sortie OBS:", font=("Segoe UI", 8),
                 fg=TEXT3, bg=BG2).pack(side="left")
        self.obs_output_var = tk.StringVar()
        self.obs_output_entry = tk.Entry(obs_folder_row, textvariable=self.obs_output_var,
                                         font=("Consolas", 8), bg="#0d1117", fg=TEXT2,
                                         insertbackground=TEXT2, relief="flat", borderwidth=0,
                                         highlightthickness=1, highlightbackground="#333")
        self.obs_output_entry.pack(side="left", fill="x", expand=True, padx=(6, 4))
        tk.Button(obs_folder_row, text="...", font=("Segoe UI", 7),
                  fg=TEXT2, bg=BG3, activebackground=BG3, relief="flat", padx=6,
                  cursor="hand2", command=self.pick_obs_output, borderwidth=0).pack(side="right")
        tk.Button(obs_folder_row, text="Appliquer", font=("Segoe UI", 7, "bold"),
                  fg=PURPLE, bg=BG3, activebackground=BG3, relief="flat", padx=6,
                  cursor="hand2", command=self.set_obs_output_dir, borderwidth=0).pack(side="right", padx=(0, 4))

        # === STEP 2: Fichiers ===
        self.section(main, "2. Fichiers", RED)
        files_frame = tk.Frame(main, bg=BG2, highlightbackground="#2a2a4a",
                               highlightthickness=1)
        files_frame.pack(fill="x", pady=(0, 16))

        files_inner = tk.Frame(files_frame, bg=BG2)
        files_inner.pack(fill="x", padx=16, pady=12)

        self.file_row(files_inner, "Video OBS:", self.video_path, self.pick_video,
                      filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov *.webm")])
        self.file_row(files_inner, "Cursor log:", self.log_path, self.pick_log,
                      filetypes=[("JSON", "*.json")])
        self.file_row(files_inner, "JSON edite (optionnel):", self.edited_path, self.pick_edited,
                      filetypes=[("JSON", "*.json")])

        detect_btn = tk.Label(files_inner, text="↻ Auto-detecter les derniers fichiers",
                              font=("Segoe UI", 8, "underline"), fg=PURPLE, bg=BG2, cursor="hand2")
        detect_btn.pack(anchor="w", pady=(4, 0))
        detect_btn.bind("<Button-1>", lambda e: self.auto_detect_files())

        # === STEP 3: Options ===
        self.section(main, "3. Options", RED)
        opts_frame = tk.Frame(main, bg=BG2, highlightbackground="#2a2a4a",
                              highlightthickness=1)
        opts_frame.pack(fill="x", pady=(0, 16))

        opts_inner = tk.Frame(opts_frame, bg=BG2)
        opts_inner.pack(fill="x", padx=16, pady=12)

        # Background
        bg_row = tk.Frame(opts_inner, bg=BG2)
        bg_row.pack(fill="x", pady=2)
        tk.Checkbutton(bg_row, text="Background", variable=self.opt_bg,
                       font=("Segoe UI", 10), fg=TEXT, bg=BG2, selectcolor=BG,
                       activebackground=BG2, activeforeground=TEXT).pack(side="left")
        for val, label in [("carbon", "Carbon"), ("gradient", "Gradient"), ("mesh", "Mesh")]:
            tk.Radiobutton(bg_row, text=label, variable=self.bg_style, value=val,
                           font=("Segoe UI", 8), fg=TEXT2, bg=BG2, selectcolor=BG3,
                           activebackground=BG2, activeforeground=TEXT).pack(side="left", padx=(8, 0))

        # Captions
        cap_row = tk.Frame(opts_inner, bg=BG2)
        cap_row.pack(fill="x", pady=2)
        tk.Checkbutton(cap_row, text="Captions (Whisper)", variable=self.opt_captions,
                       font=("Segoe UI", 10), fg=TEXT, bg=BG2, selectcolor=BG,
                       activebackground=BG2, activeforeground=TEXT).pack(side="left")
        for val, label in [("tiktok", "TikTok"), ("classic", "Classique")]:
            tk.Radiobutton(cap_row, text=label, variable=self.caption_style, value=val,
                           font=("Segoe UI", 8), fg=TEXT2, bg=BG2, selectcolor=BG3,
                           activebackground=BG2, activeforeground=TEXT).pack(side="left", padx=(8, 0))

        cap_model_row = tk.Frame(opts_inner, bg=BG2)
        cap_model_row.pack(fill="x", pady=(0, 2), padx=(24, 0))
        tk.Label(cap_model_row, text="Modele:", font=("Segoe UI", 8), fg=TEXT3, bg=BG2).pack(side="left")
        for val, label in [("tiny", "tiny"), ("base", "base"), ("small", "small"), ("medium", "medium")]:
            tk.Radiobutton(cap_model_row, text=label, variable=self.caption_model, value=val,
                           font=("Segoe UI", 8), fg=TEXT2, bg=BG2, selectcolor=BG3,
                           activebackground=BG2, activeforeground=TEXT).pack(side="left", padx=(6, 0))

        # Webcam
        cam_row = tk.Frame(opts_inner, bg=BG2)
        cam_row.pack(fill="x", pady=2)
        tk.Checkbutton(cam_row, text="Webcam overlay", variable=self.opt_webcam,
                       font=("Segoe UI", 10), fg=TEXT, bg=BG2, selectcolor=BG,
                       activebackground=BG2, activeforeground=TEXT).pack(side="left")
        for val, label in [("circle", "Cercle"), ("rounded", "Arrondi"), ("rectangle", "Rect")]:
            tk.Radiobutton(cam_row, text=label, variable=self.webcam_shape, value=val,
                           font=("Segoe UI", 8), fg=TEXT2, bg=BG2, selectcolor=BG3,
                           activebackground=BG2, activeforeground=TEXT).pack(side="left", padx=(8, 0))

        cam_file_row = tk.Frame(opts_inner, bg=BG2)
        cam_file_row.pack(fill="x", pady=(0, 2), padx=(24, 0))
        tk.Label(cam_file_row, text="Fichier cam:", font=("Segoe UI", 8), fg=TEXT3, bg=BG2).pack(side="left")
        tk.Entry(cam_file_row, textvariable=self.webcam_file_path, font=("Segoe UI", 8),
                 bg=BG, fg=TEXT, insertbackground=TEXT, width=30).pack(side="left", padx=(4, 0))
        self.make_btn(cam_file_row, "...", TEXT3, self.pick_webcam_file, small=True).pack(side="left", padx=(4, 0))

        cam_pos_row = tk.Frame(opts_inner, bg=BG2)
        cam_pos_row.pack(fill="x", pady=(0, 2), padx=(24, 0))
        tk.Label(cam_pos_row, text="Position:", font=("Segoe UI", 8), fg=TEXT3, bg=BG2).pack(side="left")
        for val, label in [("bottom-right", "Bas-D"), ("bottom-left", "Bas-G"),
                           ("top-right", "Haut-D"), ("top-left", "Haut-G")]:
            tk.Radiobutton(cam_pos_row, text=label, variable=self.webcam_pos, value=val,
                           font=("Segoe UI", 8), fg=TEXT2, bg=BG2, selectcolor=BG3,
                           activebackground=BG2, activeforeground=TEXT).pack(side="left", padx=(6, 0))

        # === STEP 4: Lancer ===
        self.section(main, "4. Lancer", RED)
        launch_frame = tk.Frame(main, bg=BG2, highlightbackground="#2a2a4a",
                                highlightthickness=1)
        launch_frame.pack(fill="x", pady=(0, 8))

        launch_inner = tk.Frame(launch_frame, bg=BG2)
        launch_inner.pack(fill="x", padx=16, pady=12)

        launch_btns = tk.Frame(launch_inner, bg=BG2)
        launch_btns.pack(fill="x")

        self.make_btn(launch_btns, "🎬  Ouvrir l'editeur", RED,
                      self.launch_editor).pack(side="left")
        self.make_btn(launch_btns, "⚡  Render direct", PURPLE,
                      self.launch_render).pack(side="left", padx=(8, 0))

        # Output log
        self.output_text = tk.Text(main, height=6, bg="#0d1117", fg="#8b949e",
                                   font=("Consolas", 9), borderwidth=0,
                                   highlightthickness=1, highlightbackground="#2a2a4a",
                                   insertbackground="#8b949e")
        self.output_text.pack(fill="x", pady=(8, 0))
        self.output_text.insert("1.0", "Pret. Choisis tes fichiers et lance!\n")
        self.output_text.configure(state="disabled")

    def section(self, parent, text, color):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(8, 4))
        tk.Label(f, text=text, font=("Segoe UI", 11, "bold"),
                 fg=color, bg=BG).pack(anchor="w")

    def make_btn(self, parent, text, color, command, state="normal", small=False):
        font = ("Segoe UI", 8) if small else ("Segoe UI", 10, "bold")
        px = 6 if small else 16
        py = 2 if small else 6
        btn = tk.Button(parent, text=text, font=font,
                        fg="white", bg=color, activebackground=color,
                        activeforeground="white", relief="flat", padx=px, pady=py,
                        cursor="hand2", command=command, state=state,
                        borderwidth=0)
        return btn

    def file_row(self, parent, label, var, command, filetypes=None):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=label, font=("Segoe UI", 9), fg=TEXT2, bg=BG2,
                 width=22, anchor="w").pack(side="left")

        entry = tk.Entry(row, textvariable=var, font=("Consolas", 9),
                         bg="#0d1117", fg=TEXT, insertbackground=TEXT,
                         relief="flat", borderwidth=0, highlightthickness=1,
                         highlightbackground="#333")
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        browse = tk.Button(row, text="...", font=("Segoe UI", 8),
                           fg=TEXT2, bg=BG3, activebackground=BG3,
                           relief="flat", padx=8, cursor="hand2",
                           command=command, borderwidth=0)
        browse.pack(side="right")

    def pick_video(self):
        f = filedialog.askopenfilename(
            title="Choisis ta video",
            filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov *.webm"), ("Tous", "*.*")]
        )
        if f:
            self.video_path.set(f)

    def pick_log(self):
        f = filedialog.askopenfilename(
            title="Choisis ton cursor log",
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")]
        )
        if f:
            self.log_path.set(f)

    def pick_edited(self):
        f = filedialog.askopenfilename(
            title="Choisis le JSON edite (optionnel)",
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")]
        )
        if f:
            self.edited_path.set(f)

    def pick_webcam_file(self):
        f = filedialog.askopenfilename(
            title="Choisis ta video webcam (fichier separe)",
            filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov *.webm"), ("Tous", "*.*")]
        )
        if f:
            self.webcam_file_path.set(f)
            self.opt_webcam.set(True)

    def auto_detect_files(self):
        """Auto-detecte le dernier fichier video et cursor log."""
        # Chercher dans le dossier du script ET le dossier courant
        search_dirs = [SCRIPT_DIR, os.getcwd()]

        # Trouver le dernier cursor_log
        logs = []
        for d in search_dirs:
            logs.extend(glob.glob(os.path.join(d, "cursor_log_*.json")))
        if logs:
            latest_log = max(logs, key=os.path.getmtime)
            self.log_path.set(latest_log)

            # Lire le log pour trouver le chemin video OBS
            try:
                with open(latest_log) as f:
                    data = json.load(f)
                video_file = data.get("metadata", {}).get("video_file")
                if video_file:
                    # Normaliser le chemin
                    vf = video_file.replace("/", os.sep)
                    if os.path.exists(vf):
                        self.video_path.set(vf)
            except:
                pass

        # Si pas de video trouvee dans le log, chercher la derniere video
        if not self.video_path.get():
            videos = []
            for d in search_dirs:
                for ext in ["*.mp4", "*.mkv", "*.avi", "*.mov"]:
                    videos.extend(glob.glob(os.path.join(d, ext)))
            # Aussi chercher dans le dossier Documents/Videos communs
            home = os.path.expanduser("~")
            for extra_dir in [os.path.join(home, "Videos"),
                              os.path.join(home, "Documents"),
                              os.path.join(home, "Desktop")]:
                if os.path.isdir(extra_dir):
                    for ext in ["*.mp4", "*.mkv"]:
                        videos.extend(glob.glob(os.path.join(extra_dir, ext)))
            if videos:
                # Prendre la plus recente des 5 dernieres minutes
                now = datetime.now().timestamp()
                recent = [v for v in videos if now - os.path.getmtime(v) < 300]
                if recent:
                    latest_vid = max(recent, key=os.path.getmtime)
                    self.video_path.set(latest_vid)
                elif videos:
                    latest_vid = max(videos, key=os.path.getmtime)
                    self.video_path.set(latest_vid)

        if self.log_path.get() or self.video_path.get():
            self.set_status("Fichiers auto-detectes.", GREEN)

    def pick_obs_output(self):
        d = filedialog.askdirectory(title="Dossier de sortie OBS")
        if d:
            self.obs_output_var.set(d)

    def set_obs_output_dir(self):
        """Change le dossier de sortie OBS via WebSocket."""
        folder = self.obs_output_var.get()
        if not folder:
            messagebox.showinfo("Dossier vide", "Choisis un dossier d'abord.")
            return
        if not os.path.isdir(folder):
            messagebox.showwarning("Dossier invalide", f"Le dossier n'existe pas:\n{folder}")
            return

        try:
            import obsws_python as obs
            client = obs.ReqClient(host="localhost", port=4455, password="")
            client.set_profile_parameter("Output", "FilePath", folder)
            self.set_status(f"Dossier OBS change: {folder}", GREEN)
            self.log_output(f"Dossier de sortie OBS change: {folder}\n")
        except ImportError:
            messagebox.showwarning("obsws-python manquant",
                                   "pip install obsws-python pour changer le dossier OBS.")
        except Exception as e:
            # Fallback: essayer set_record_directory si dispo
            try:
                client.set_record_directory(folder)
                self.set_status(f"Dossier OBS change: {folder}", GREEN)
                self.log_output(f"Dossier de sortie OBS change: {folder}\n")
            except:
                self.set_status(f"Erreur OBS: {e}", RED)
                self.log_output(f"Erreur changement dossier OBS: {e}\n"
                                f"Tu peux le changer manuellement dans OBS:\n"
                                f"  Settings > Output > Recording Path\n")

    def set_status(self, msg, color=TEXT2):
        self.status_var.set(msg)
        self.status_label.configure(fg=color)

    def log_output(self, text):
        self.output_text.configure(state="normal")
        self.output_text.insert("end", text)
        self.output_text.see("end")
        self.output_text.configure(state="disabled")

    def clear_output(self):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    # --- Logging ---
    def start_logging(self):
        self.clear_output()
        self.set_status("Logging en cours... Ctrl+C dans le terminal pour arreter.", YELLOW)
        self.log_status.configure(text="● LOGGING EN COURS", fg=YELLOW)
        self.btn_start_log.configure(state="disabled")
        self.btn_stop_log.configure(state="normal")

        cmd = [sys.executable, os.path.join(SCRIPT_DIR, "cursor_logger.py"), "--obs"]
        self.log_output(f"$ {' '.join(cmd)}\n\n")

        def run():
            try:
                self.logging_process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, cwd=SCRIPT_DIR
                )
                for line in self.logging_process.stdout:
                    self.root.after(0, self.log_output, line)
                self.logging_process.wait()
            except Exception as e:
                self.root.after(0, self.log_output, f"\nErreur: {e}\n")
            finally:
                self.root.after(0, self._logging_done)

        threading.Thread(target=run, daemon=True).start()

    def stop_logging(self):
        if self.logging_process:
            try:
                import signal
                self.logging_process.send_signal(signal.CTRL_C_EVENT if sys.platform == "win32"
                                                 else signal.SIGINT)
            except:
                self.logging_process.terminate()

    def _logging_done(self):
        self.logging_process = None
        self.btn_start_log.configure(state="normal")
        self.btn_stop_log.configure(state="disabled")
        self.log_status.configure(text="● TERMINE", fg=GREEN)
        self.set_status("Logging termine. Fichiers mis a jour.", GREEN)
        self.auto_detect_files()

    # --- Editor ---
    def launch_editor(self):
        if not self.video_path.get() or not self.log_path.get():
            messagebox.showwarning("Fichiers manquants",
                                   "Choisis une video ET un cursor log d'abord.")
            return

        self.clear_output()
        cmd = self._build_cmd(edit=True)
        self.log_output(f"$ {' '.join(cmd)}\n\n")
        self.set_status("Lancement de l'editeur...", YELLOW)
        self._run_cmd(cmd)

    def launch_render(self):
        if not self.video_path.get() or not self.log_path.get():
            messagebox.showwarning("Fichiers manquants",
                                   "Choisis une video ET un cursor log d'abord.")
            return

        self.clear_output()
        cmd = self._build_cmd(edit=False)
        self.log_output(f"$ {' '.join(cmd)}\n\n")
        self.set_status("Render en cours...", YELLOW)
        self._run_cmd(cmd)

    def _build_cmd(self, edit=True):
        cmd = [sys.executable, os.path.join(SCRIPT_DIR, "auto_zoom.py"),
               self.video_path.get(), self.log_path.get()]

        if self.edited_path.get():
            cmd += ["--use-edited", self.edited_path.get()]

        if edit:
            cmd.append("--edit")

        if self.opt_bg.get():
            cmd += ["--background", self.bg_style.get()]

        if self.opt_captions.get():
            cmd += ["--captions", "--caption-style", self.caption_style.get(),
                    "--caption-model", self.caption_model.get()]

        if self.opt_webcam.get():
            cmd += ["--webcam", "--webcam-shape", self.webcam_shape.get(),
                    "--webcam-pos", self.webcam_pos.get()]
            if self.webcam_file_path.get():
                cmd += ["--webcam-file", self.webcam_file_path.get()]

        return cmd

    def _run_cmd(self, cmd):
        def run():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, cwd=SCRIPT_DIR
                )
                for line in proc.stdout:
                    self.root.after(0, self.log_output, line)
                proc.wait()
                if proc.returncode == 0:
                    self.root.after(0, self.set_status, "Termine avec succes!", GREEN)
                else:
                    self.root.after(0, self.set_status, f"Termine (code: {proc.returncode})", RED)
            except Exception as e:
                self.root.after(0, self.log_output, f"\nErreur: {e}\n")
                self.root.after(0, self.set_status, f"Erreur: {e}", RED)

        threading.Thread(target=run, daemon=True).start()


def main():
    root = tk.Tk()

    # Icon (optionnel - on essaie, si ca marche pas c'est pas grave)
    try:
        root.iconbitmap(default="")
    except:
        pass

    # Style sombre pour les widgets ttk
    style = ttk.Style()
    style.theme_use("clam")

    app = AutoZoomApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
