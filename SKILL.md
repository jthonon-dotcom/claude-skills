---
name: regarde
description: Regarder et décortiquer n'importe quelle vidéo (lien YouTube, Instagram, TikTok, X, Pinterest, Vimeo… ou fichier local) seconde par seconde. Télécharge la vidéo, récupère les sous-titres ou transcrit l'audio en local, extrait des images horodatées (régulières et à chaque coupe) en planches 5x4, puis livre l'analyse complète - accroche, coupes, texte à l'écran, B-rolls, ce qui est montré pendant chaque phrase, call to action. À utiliser dès que l'utilisateur dit « regarde cette vidéo », « analyse cette vidéo », « décortique », « qu'est-ce qui se passe dans cette vidéo », « inspire-toi de cette vidéo », ou envoie un lien ou un fichier vidéo.
---

# regarde

Tu ne peux pas lire une vidéo directement. Ce skill la transforme en ce que tu
sais lire : des planches d'images horodatées et une transcription. Tout est
gratuit et local (yt-dlp, ffmpeg, whisper.cpp). **Jamais d'API payante.**

## 1. Préparer la vidéo (une seule commande)

```bash
python3 ~/.claude/skills/regarde/regarde.py "<lien ou chemin du fichier>"
```

Sous Windows : `python "%USERPROFILE%\.claude\skills\regarde\regarde.py" "<lien ou fichier>"`.
Ajoute `--force` pour tout refaire, `--root <dossier>` pour changer de dossier.

Le script fait, dans l'ordre :

1. **Outils** : vérifie `yt-dlp --version` et `ffmpeg -version`. S'il en manque
   un, il l'installe (Homebrew sur Mac, winget sur Windows, apt sur Linux).
   Si yt-dlp a plus d'un mois (sa version est une date), il le met à jour.
2. **Téléchargement** en mp4 avec yt-dlp dans `~/regarde/<nom-de-la-video>/video.mp4`
   (nom tiré du titre). Si Instagram ou TikTok refuse, il réessaie avec
   `--cookies-from-browser chrome`. Un fichier local est copié (ou converti en mp4).
3. **Transcription** : d'abord les sous-titres de la plateforme
   (`--write-subs --write-auto-subs --skip-download`). S'il n'y en a pas,
   transcription locale avec whisper.cpp, modèle `base` (installé la première
   fois, environ 140 Mo). Résultat : `transcript.srt` et `transcript.txt`
   (une ligne par réplique, `[mm:ss.s] texte`).
4. **Images** avec ffmpeg : une par seconde si la vidéo dure moins de 2 min,
   une toutes les 2 s jusqu'à 10 min, une toutes les 10 s au-delà, **plus une à
   chaque changement de plan** (`select='gt(scene,0.3)'`, marquée « COUPE »).
   L'horodatage est écrit sur chaque image (drawtext). La liste est dans
   `frames.tsv` (temps, type, fichier).
5. **Planches** : les images, dans l'ordre du temps, assemblées en planches
   de 5x4 vignettes (`sheets/planche_001.jpg`, …), soit 20 images par lecture.
6. **`resume.md`** : durée, résolution, source de la transcription, nombre
   d'images, temps de chaque coupe, liste des planches.

La dernière ligne affichée est `DOSSIER=<chemin>`.

Si le script échoue :
- « yt-dlp n'arrive pas à lire ce lien » : vérifie le lien, mets yt-dlp à jour
  (`yt-dlp -U`) ; pour Instagram ou TikTok, l'utilisateur doit être connecté
  au site dans Chrome. Dans un environnement cloud, le réseau peut bloquer le
  site : nomme l'hôte refusé à l'utilisateur.
- Pas de son ou vidéo muette : la transcription l'indique, analyse l'image seule.

## 2. Regarder

1. Lis `resume.md` puis `transcript.txt` en entier.
2. Lis **toutes** les planches, dans l'ordre, avec l'outil Read (une planche
   par appel). Chaque vignette porte son temps en haut à gauche ; « COUPE »
   marque une image prise à un changement de plan.
3. Ouvre une image de `frames/` en taille réelle quand un détail est trop
   petit (un texte à l'écran, un logo, un prix).
4. Croise image et texte : pour chaque phrase de la transcription, regarde
   les vignettes de la même seconde.

## 3. Rendre l'analyse

Réponds dans la langue de l'utilisateur, avec ces parties, toujours avec des
temps précis (`0:07`) :

1. **Fiche** : titre, auteur, durée, format (vertical ou horizontal), nombre de
   coupes et rythme moyen (une coupe toutes les N s).
2. **L'accroche (0:00 à 0:03)** : exactement ce qu'on voit et entend, et
   pourquoi ça retient (ou pas).
3. **Décorticage seconde par seconde** : un tableau

   | temps | plan / coupe | à l'écran (image) | texte à l'écran | voix / son | B-roll ou A-roll |
   |---|---|---|---|---|---|

   Une ligne par coupe ou par phrase, sans trou dans la chronologie. Recopie le
   texte à l'écran mot pour mot. Le A-roll est la personne qui parle face
   caméra ; le B-roll, les plans d'illustration (produit, lieux, écrans,
   archives, stock).
4. **Ce qui est montré pendant chaque phrase** : la phrase, puis l'image qui
   l'illustre, et si l'image dit la même chose, autre chose, ou rien.
5. **Les coupes** : la liste des temps, et les techniques de transition
   (coupe franche, zoom, fouetté, morph, fondu, J-cut ou L-cut).
6. **Le call to action** : le texte exact, quand il arrive, comment il est montré.
7. **Ce qu'on peut reprendre** : 3 à 5 idées concrètes (structure, rythme,
   procédés visuels), sans copier le contenu ni la marque.

Ne décris jamais ce que tu n'as pas vu sur une planche ou lu dans la
transcription. Si une partie est incertaine (image floue, son inaudible),
dis-le.

## Dossier produit

```
~/regarde/<nom-de-la-video>/
  video.mp4  info.json  transcript.srt  transcript.txt
  frames/  frames.tsv  sheets/planche_NNN.jpg  resume.md
```
