# TODO: Cursor Masking / Custom Cursor Feature

## Probleme

On veut cacher le curseur original dans la video OBS pour le remplacer par un custom cursor
(rond, crosshair, etc.) ou simplement le rendre invisible. Aucune approche testee ne fonctionne
de facon fiable.

## Approches testees

### 1. OBS WebSocket API (`capture_cursor = False`)
- `set_input_settings()` via obsws-python pour toggler `cursor` / `capture_cursor`
- **Resultat**: L'API retourne succes mais le curseur reste visible sur certaines configs
- **Cause**: Windows Display Capture (methode DXGI) ignore completement le setting `capture_cursor`
- Meme decocher manuellement "Capture Cursor" dans les proprietes OBS ne marche pas avec DXGI

### 2. cv2.inpaint (masquage par inpainting)
- Detecter la position du curseur, peindre par-dessus avec `cv2.inpaint(INPAINT_TELEA)`
- **Resultat**: Artefacts visibles, surtout quand le curseur est sur du texte ou des bords nets
- Le mask_size doit scaler avec le zoom, sinon le curseur apparait plus gros que le masque

### 3. Win32 API (`SetSystemCursor` / `SystemParametersInfoW SPI_SETCURSORS`)
- Remplacer tous les curseurs systeme par un curseur transparent 1x1
- **Resultat**: Fonctionne techniquement mais trop invasif
  - Rend le curseur invisible partout dans Windows, pas juste dans OBS
  - Si le script crash, les curseurs restent invisibles (mauvaise UX)
  - L'utilisateur ne peut plus naviguer normalement pendant l'enregistrement

### 4. Custom cursor overlay dans le preview HTML
- Dessiner un curseur custom (rond, crosshair) sur le canvas de preview
- **Resultat**: Le preview fonctionne visuellement mais ne resout pas le probleme du curseur
  original visible dans la video source

## Conclusion

Le probleme fondamental est que Windows Display Capture (DXGI) bake le curseur directement
dans le frame capture. Il n'y a pas de moyen propre de le retirer apres coup sans artefacts.

## Pistes pour le futur

1. **Window Capture au lieu de Display Capture**: Capturer une fenetre specifique plutot que
   l'ecran entier — le setting `capture_cursor` marche peut-etre mieux dans ce mode
2. **Game Capture**: Si applicable, pourrait offrir un meilleur controle du curseur
3. **OBS plugin custom**: Un plugin OBS qui masque le curseur au niveau du compositor
4. **Post-processing ML**: Utiliser un modele de ML (inpainting neural) pour retirer le curseur
   proprement sans artefacts — plus lourd mais meilleur resultat que cv2.inpaint
5. **Electron/overlay approach**: Une fenetre overlay transparente qui couvre le curseur
   a sa position exacte (hacky mais potentiellement viable)

## Ce qui est garde

- **Click highlight**: Les cercles rouges aux positions de clic fonctionnent bien et ajoutent
  de la valeur sans avoir besoin de masquer quoi que ce soit
- **Cursor tracking**: Le logging des positions reste utile pour le click highlight et pour
  un eventuel custom cursor futur
- **OBS cursor disable**: On tente quand meme de desactiver via l'API — ca marche sur certaines
  configs (Window Capture, etc.)
