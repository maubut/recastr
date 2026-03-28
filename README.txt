============================================
  AUTOZOOM v4 - Screen Recording Zoom Tool
  Alternative gratuite a Focusee / Canvid
============================================

WHAT IT DOES
------------
AutoZoom ajoute automatiquement des effets de zoom a tes
screen recordings OBS. Il suit ta souris et zoome quand:
  - Tu cliques quelque part (zoom 2x pendant 2 sec)
  - Ta souris reste immobile (zoom 1.6x = tu focus sur qqch)

Le tout avec des transitions smooth (ease in/out).

Nouveau en v4: captions automatiques avec Whisper (sous-titres
mot par mot, style TikTok ou classique).

Nouveau en v5: webcam overlay avec fichier video separe.
Enregistre ta cam dans un fichier a part pour un overlay
propre qui reste fixe pendant les zooms (comme Tella/Loom).


INSTALLATION (une seule fois)
-----------------------------
1. Installe Python: https://www.python.org/downloads/
   >>> COCHE "Add Python to PATH" pendant l'installation! <<<

2. Installe FFmpeg:
   - Ouvre un terminal (Win+R, tape "cmd", Enter)
   - Tape: winget install FFmpeg
   - OU telecharge-le: https://ffmpeg.org/download.html

3. Double-clic sur INSTALL.bat
   (ca installe numpy, opencv, whisper, pillow automatiquement)


UTILISATION
-----------
Etape 1: AVANT d'enregistrer
  - Double-clic sur START_LOGGING.bat
  - Un terminal s'ouvre et dit "Lance ton enregistrement OBS"

Etape 2: ENREGISTRER
  - Lance ton enregistrement dans OBS normalement
  - Fais ta demo / tuto comme d'habitude
  - Le logger track ta souris en background

Etape 3: ARRETER
  - Arrete ton enregistrement OBS
  - Va dans le terminal du logger et fais Ctrl+C
  - Un fichier cursor_log_XXXXX.json est cree

Etape 4: RENDER
  - Double-clic sur RENDER_FINAL.bat
  - Glisse ta video OBS dans le terminal, Enter
  - Glisse le fichier cursor_log.json, Enter
  - Choisis si tu veux un background (optionnel)
  - Choisis si tu veux des captions (optionnel)
  - Attends le render (quelques minutes)
  - Ta video zoomee est creee: video_zoomed.mp4


EDITEUR VISUEL (recommande)
---------------------------
Au lieu de render direct, ouvre l'editeur pour ajuster:

  python auto_zoom.py video.mp4 log.json --edit

Avec captions:

  python auto_zoom.py video.mp4 log.json --edit --captions

L'editeur s'ouvre dans ton browser. Tu peux:
  - Supprimer/desactiver des zooms
  - Ajuster le niveau de zoom et la duree
  - Choisir un background (carbon/gradient/mesh)
  - Activer les captions et corriger le texte
  - Choisir le style TikTok ou classique
  - Voir le preview live
  - Exporter le JSON, puis render avec --use-edited


CAPTIONS (SOUS-TITRES AUTO)
----------------------------
AutoZoom utilise Whisper (OpenAI) pour transcrire ta voix
automatiquement. Deux styles disponibles:

  TikTok: Gros texte centre, le mot actif change de couleur
          Parfait pour les reels, shorts, demos courtes

  Classique: Texte en bas de l'ecran, fond noir semi-transparent
             Parfait pour les tutos, presentations, screencasts

Options:
  --captions               Activer la transcription
  --caption-model base     Modele Whisper (tiny/base/small/medium/large)
  --caption-lang fr        Forcer la langue (sinon auto-detect)
  --caption-style tiktok   Style des captions (tiktok/classic)

Exemples:
  python auto_zoom.py video.mp4 log.json --captions
  python auto_zoom.py video.mp4 log.json --captions --caption-model small --caption-lang fr
  python auto_zoom.py video.mp4 log.json --edit --captions --caption-style classic

Note: La premiere execution telecharge le modele Whisper (~150 MB
pour base, ~500 MB pour small). Apres c'est en cache.


WEBCAM OVERLAY
--------------
AutoZoom peut superposer ta webcam sur la video zoomee.
La cam reste fixe pendant les zooms, comme Tella ou Loom.

Methode recommandee: fichier webcam separe
  1. Dans OBS, installe le plugin "Source Record"
     https://obsproject.com/forum/resources/source-record.1285/
  2. Clic droit sur ta source webcam > Filtres > + Source Record
  3. Configure pour enregistrer dans un fichier separe (camera.mp4)
  4. Lance ton enregistrement normalement (2 fichiers sont crees)
  5. Au render, utilise --webcam-file:

  python auto_zoom.py video.mp4 log.json --webcam --webcam-file camera.mp4

Options:
  --webcam                   Activer la webcam overlay
  --webcam-file camera.mp4   Fichier video de la webcam (separe)
  --webcam-shape circle      Forme (circle/rounded/rectangle)
  --webcam-pos bottom-right  Position (bottom-right/bottom-left/top-right/top-left)
  --webcam-size 0.2          Taille (fraction de la largeur, 0.2 = 20%)

Exemples:
  python auto_zoom.py video.mp4 log.json --webcam --webcam-file cam.mp4
  python auto_zoom.py video.mp4 log.json --webcam --webcam-file cam.mp4 --webcam-shape rounded --webcam-pos top-right
  python auto_zoom.py video.mp4 log.json --edit --webcam --webcam-file cam.mp4

Alternative (legacy): si ta webcam est visible dans ton recording OBS
et detectee via WebSocket, AutoZoom peut l'extraire du frame. Moins
beau mais fonctionne sans plugin.


OPTIONS AVANCEES (optionnel)
----------------------------
Tu peux ajuster les zooms en ligne de commande:

  python auto_zoom.py video.mp4 log.json --zoom-click 2.5 --zoom-still 1.8

  --zoom-click 2.0   Niveau de zoom sur les clics (default: 2x)
  --zoom-still 1.6   Niveau de zoom sur les pauses (default: 1.6x)
  --output nom.mp4   Nom du fichier de sortie
  --background carbon   Background sombre (carbon/gradient/mesh)


TIPS
----
- Plus tu cliques de facon intentionnelle, meilleur le resultat
- Les pauses naturelles de ta souris = zoom automatique
- Commence par un test court (30 sec) pour voir le resultat
- La qualite de sortie est haute (CRF 18, x264)
- Pour les captions: parle clairement, Whisper est bon mais pas parfait
- Utilise l'editeur (--edit) pour corriger le texte avant le render
- Le modele "small" est un bon compromis vitesse/qualite pour les captions


STRUCTURE DES FICHIERS
----------------------
  autozoom/
    INSTALL.bat          <- Lance en premier (une seule fois)
    START_LOGGING.bat    <- Lance avant chaque enregistrement
    RENDER_FINAL.bat     <- Lance apres pour generer la video
    RENDER_ZOOM.bat      <- Render rapide (sans options)
    EDIT_ZOOMS.bat       <- Ouvrir l'editeur visuel
    cursor_logger.py     <- Script de logging souris
    auto_zoom.py         <- Script de rendering zoom + captions + webcam
    autozoom_app.py      <- Interface graphique (tkinter)
    README.txt           <- Ce fichier
    TODO_CURSOR_MASKING.md <- Notes sur le masquage du curseur

============================================
  Fait avec amour par un solo founder
  pour les solo founders
============================================
