# BLUE REFLECTION — Patch de traduction française / French translation patch

**🇫🇷 [Français](#français)** · **🇬🇧 [English](#english)**

| Français | English |
| --- | --- |
| [Jeux pris en charge](#jeux-pris-en-charge) | [Supported games](#supported-games) |
| [Méthode de traduction](#méthode-de-traduction) | [Translation method](#translation-method) |
| [Prérequis](#prérequis) | [Requirements](#requirements) |
| [Installation](#installation) | [How to install](#how-to-install) |
| [Steam et mises à jour](#steam-et-mises-à-jour) | [Steam and updates](#steam-and-updates) |
| [Sauvegardes et retour en anglais](#sauvegardes-et-retour-en-anglais) | [Backups and reverting to English](#backups-and-reverting-to-english) |
| [Fonctionnement](#fonctionnement) | [How it works](#how-it-works) |
| [Limites connues](#limites-connues) | [Known limitations](#known-limitations) |
| [Crédits et provenance](#crédits-et-provenance) | [Credits and provenance](#credits-and-provenance) |

---

# Français

[↑ Haut de page](#blue-reflection--patch-de-traduction-française--french-translation-patch) · [English ➜](#english)

Ce dossier contient un patch **texte** qui traduit en français les jeux de la
série **BLUE REFLECTION** sur PC. Il s'applique **sur votre propre
installation** : les archives complètes des jeux ne sont jamais redistribuées,
seuls les membres texte concernés sont réécrits.

## Jeux pris en charge

| Jeu | Archives modifiées | Origine du texte |
|---|---|---|
| **BLUE REFLECTION (2017)** | `DATA/PACK01.PAK` (dialogues), `DATA/PACK02_1.PAK` (interface) | Traduction fan « *Blue Reflection French Translation 8 v1.1* », nettoyée |
| **BLUE REFLECTION Quartet — partition b1** (premier jeu) | `Data/PACK11.PAK` (dialogues), `Data/PACK12.PAK` (interface) | Même texte que la version 2017, adapté aux balises de Quartet |
| **BLUE REFLECTION Quartet — partition b4** (Second Light) | `Data/PACK01_03.PAK` (dialogues), `Data/PACK02_03.PAK` (interface, menus, boutons) | Bêta fan pour une partie, **traduction automatique** pour le reste |
| **BLUE REFLECTION: Second Light** (version isolée) | `Data/PACK01.PAK` (dialogues) | Idem ; l'interface est déjà en français grâce à la bêta fan |

Le reste du jeu (scripts, images, modèles, vidéos) n'est pas touché.

> **Qualité de Second Light.** Seuls 61 événements et le texte système de
> départ proviennent d'une traduction humaine ; le reste (≈ 4 300 événements et
> ≈ 5 700 textes système) est une **traduction automatique** qui attend une
> relecture. Le dataset est découpé en `dialogue.xml` + `dialogue_1.xml` …
> `dialogue_16.xml` (dossier `dataset_second_light/`) pour faciliter cette relecture.

## Méthode de traduction

Le patch ne contient **aucune traduction écrite à la main pour ce projet** : il
réutilise des traductions françaises existantes et complète les manques de
façon automatique. L'origine du texte dépend du jeu.

### Premier jeu (2017 et Quartet b1) : traduction humaine

1. Le texte vient de la traduction fan *Blue Reflection French Translation*
   (release 8, v1.1), écrite par des traducteurs humains à partir de l'anglais
   officiel.
2. Il est **extrait**, puis **nettoyé automatiquement** et de façon
   reproductible (`br_french_cleanup.py`) : terminologie unifiée (« Sephira » /
   « Sephirot »), quelques corrections de grammaire, repli des accents absents
   de la police du jeu.
3. Il est **aligné** sur la base canonique du projet par identifiant de message
   (les fichiers japonais de la release sont identiques octet pour octet), puis
   ré-emballé dans un dataset compact (`dataset/`).

### Second Light : traduction mixte, humaine puis automatique

| Partie | Origine | Volume |
|---|---|---|
| Dialogues d'ouverture | Bêta fan *BRSL fr-FR V1.02 beta 2* (humaine, accents corrigés) | 61 événements |
| Texte système (menus, boutons, objets…) | Même bêta, **humaine** | 12 209 chaînes |
| Reste des dialogues | **Traduction automatique** anglais → français | ≈ 4 290 événements |
| Texte système manquant | **Traduction automatique** anglais → français | ≈ 5 700 chaînes |
| Chaînes identiques au premier jeu | Reprise de la traduction française du premier jeu | 499 chaînes |
| Marqueurs et balises techniques | Conservés tels quels | — |

La traduction automatique a été produite par des **agents d'IA (modèles de
langage)**, par lots, à partir de l'**anglais officiel** de Second Light. Les
identifiants de message et de personnage sont conservés ; les emplacements techniques
sans texte réel sont recopiés sans changement. Elle n'a **pas été relue par un
humain** : elle peut contenir des erreurs de sens, de ton, de registre ou de
terminologie.

Traitements automatiques appliqués ensuite :

- correction du **mojibake** de la bêta (caractères accentués mal encodés) ;
- **repli des accents** absents de la police bitmap du jeu (par exemple `ç` →
  `c`), dont `é` est exclu car il existe dans la police ;
- normalisation des retours à la ligne (`<CR>`) et des caractères de contrôle.

### Application au jeu

- Les dialogues sont écrits **par identifiant de message** lorsqu'il est
  unique, ou **par position** quand toute la séquence (identifiant +
  personnage) correspond exactement au fichier du jeu ; sinon la ligne reste en
  anglais plutôt que de risquer un décalage.
- Le texte système est écrit **par numéro de chaîne** (`String_No`) dans la
  table `strcombineall.xml`.
- Seul le texte change : voix, personnages, expressions et durées sont
  réécrits à l'identique.

### Relire et corriger

Le dataset Second Light est composé de fichiers XML lisibles dans
`dataset_second_light/` (`dialogue.xml`, `dialogue_1.xml` … `dialogue_16.xml`,
`names.xml`, `places.xml`, `items.xml`, `messages.xml`, `other.xml`). Modifiez
uniquement le contenu des balises `<message>` / `<string>`, sans toucher aux
identifiants ni aux balises du jeu (`<CR>`, `<CLGR>`, `<IM04>`, `%d`…), puis
relancez l'installation. Dans le dépôt, ces fichiers sont sous
`titles/second_light/translation_fr/`.

## Prérequis

- **Windows** : rien de plus, `gust_pak.exe` est fourni.
- **Linux** : `gust_pak` doit être disponible (variable `GUST_PAK` ou `PATH`),
  voir <https://github.com/VitaSmith/gust_tools/releases>.
- **Python 3.8+** (`py -3` ou `python` sous Windows, `python3` sous Linux).
- Une copie du jeu concerné sur PC (Steam compris).

## Installation

### Mode interactif

Lancez le launcher **sans argument** : il détecte les jeux installés et propose,
pour chacun, d'**installer le français** ou de **restaurer l'anglais**.

```bat
RUN.cmd
```

```bash
./RUN.sh
```

Un dossier **Quartet** apparaît deux fois : « partition b1 » (premier jeu) et
« partition b4 : Second Light ». Les deux s'installent indépendamment. Une
entrée manuelle du dossier du jeu est toujours disponible.

### Mode direct

```bat
RUN.cmd apply  --game-dir "D:\Games\BLUE REFLECTION"      :: 2017 : français
RUN.cmd revert --game-dir "D:\Games\BLUE REFLECTION"      :: 2017 : anglais

python br_quartet_french_patch.py       apply  --game-dir "D:\Games\BLUE REFLECTION Quartet"   :: Quartet b1
python br_quartet_french_patch.py       revert --game-dir "D:\Games\BLUE REFLECTION Quartet"
python br_second_light_french_patch.py  apply  --game-dir "D:\Games\BLUE REFLECTION Quartet"   :: Quartet b4
python br_second_light_french_patch.py  revert --game-dir "D:\Games\BLUE REFLECTION Quartet"
python br_second_light_french_patch.py  apply  --game-dir "D:\Games\BLUE REFLECTION Second Light"

python br_french_installer.py                              :: menu interactif
RUN.cmd status --game-dir "D:\Games\BLUE REFLECTION"       :: vérifier l'état (2017)
RUN.cmd self-check                                         :: tester l'outil
```

### Vidéos françaises

Si le dossier `movies/` est présent à côté de `RUN.cmd` (ou via `--movies-dir`),
`apply --with-movies` installe aussi les 4 vidéos `.wmv` ré-encodées dans
`DATA/x64/Movie/`, avec sauvegarde et restauration. Elles sont volumineuses
(≈ 750 Mo) et fournies séparément (`BR_French_Patch_Movies.zip`).

## Steam et mises à jour

Steam peut remplacer les archives modifiées lors d'une **mise à jour** ou d'une
**vérification de l'intégrité des fichiers** ; le jeu repasse alors en anglais
sans rien casser. Relancez simplement l'installation :

- pour **Second Light**, l'outil reconnaît l'archive remplacée par Steam, la
  prend comme nouvel original et renouvelle la sauvegarde ;
- ne lancez **pas** `revert` après une mise à jour : il remettrait la
  sauvegarde, qui peut être plus ancienne que la version de Steam.

## Sauvegardes et retour en anglais

Chaque patch conserve ses propres sauvegardes dans le dossier du jeu :

| Patch | Dossier d'état |
|---|---|
| 2017 | `.br_french_patch/` |
| Quartet b1 | `.br_french_quartet_patch/` |
| Quartet b4 / Second Light | `.br_french_second_light/` |

`revert` (ou « Restaurer l'anglais » dans le menu) remet les originaux. Vous
pouvez passer du français à l'anglais et revenir autant de fois que voulu. En
cas d'échec en cours d'installation, rien n'est modifié.

## Fonctionnement

1. **Pré-vol** : vérifie l'installation et les membres texte attendus.
2. **Extraction** de vos archives avec `gust_pak` (dossier temporaire court,
   supprimé ensuite, pour éviter la limite de longueur de chemin de Windows).
3. **Patch** des dialogues, alignés par identifiant de message, et de la table
   système `strcombineall.xml`, dont l'enveloppe chiffrée `.e` est régénérée
   (clé « BR1 » pour le premier jeu, clé « Second Light A21 » pour Second Light).
4. **Vérification** : les archives reconstruites sont ré-extraites et comparées.
5. **Installation** : remplacement des archives, état enregistré dans
   `state.json`.

### Règles de sécurité

- Un dialogue n'est écrit que s'il tombe sur la bonne ligne : par identifiant de
  message lorsqu'il est unique, ou par position lorsque toute la séquence
  (identifiant + personnage) correspond exactement au fichier du jeu.
- Une chaîne système dont les jetons dynamiques (`%d`, `<NUM1>`, `<STR1>`,
  `<IM..>`) diffèrent de l'original reste en anglais, tout comme les entrées
  vides et les marqueurs `[[...]]`.

## Limites connues

- **BLUE REFLECTION (2017)** : 8 scripts (`fe08_150/160/170/180`,
  `yy03_060/130/140/150`) ont un nombre de messages différent dans la release
  française ; ils restent en anglais par défaut (`--allow-structural-mismatch`
  pour forcer un alignement partiel).
- **Second Light** : environ 290 messages d'événements, dans des scripts dont la
  structure diffère du dataset, restent en anglais. Sur la version isolée,
  55 scripts à disposition EBM non supportée sont ignorés.
- Les traductions françaises sont souvent plus longues que l'anglais : vérifiez
  les textes qui débordent de leur cadre.
- La police bitmap du jeu n'a pas tous les caractères accentués : un repli
  remplace certains d'entre eux par leur équivalent ASCII (`ça` → `ca`), surtout
  dans la traduction de **BLUE REFLECTION (2017)** et dans la partie
  automatique de Second Light. Voir `br_french_cleanup.py`.
- Les **images** (titres de chapitre, écrans d'aide) restent en anglais.
- Le texte est écrit dans les membres « anglais » du jeu : lancez le jeu en
  configuration anglaise.
- Ce patch touche les mêmes membres que la retraduction anglaise « UNBURGER » :
  n'installez pas les deux sur la même partition.

## Crédits et provenance

- Premier jeu : traduction fan « *Blue Reflection French Translation* »
  (release 8, v1.1). Ses 1 758 fichiers japonais sont octet pour octet
  identiques à la base canonique du projet, ce qui garantit l'alignement.
- Second Light : bêta fan « *BRSL fr-FR V1.02 beta 2* » (texte humain, accents
  corrigés), complétée par une traduction automatique.
- L'outil et le codec d'enveloppe sont une adaptation Python de
  `Blue_Reflection_Patcher` (dépôt *Blue-Reflection-Quartet-Uncensor-Restore-
  Translation-Unburger-Mod*). `gust_pak` provient de
  [gust_tools](https://github.com/VitaSmith/gust_tools) (licence zlib, voir
  `LICENSE.gust_tools.txt`).

---

# English

[↑ Top](#blue-reflection--patch-de-traduction-française--french-translation-patch) · [➜ Français](#français)

This folder contains a **text** patch that translates the PC games of the
**BLUE REFLECTION** series into French. It is applied **to your own
installation**: the full game archives are never redistributed, only the
relevant text members are rewritten.

## Supported games

| Game | Archives modified | Text source |
|---|---|---|
| **BLUE REFLECTION (2017)** | `DATA/PACK01.PAK` (dialogue), `DATA/PACK02_1.PAK` (interface) | Fan translation "*Blue Reflection French Translation 8 v1.1*", cleaned up |
| **BLUE REFLECTION Quartet — b1 partition** (first game) | `Data/PACK11.PAK` (dialogue), `Data/PACK12.PAK` (interface) | Same text as the 2017 version, adapted to Quartet's tokens |
| **BLUE REFLECTION Quartet — b4 partition** (Second Light) | `Data/PACK01_03.PAK` (dialogue), `Data/PACK02_03.PAK` (interface, menus, buttons) | Fan beta for part of it, **machine translation** for the rest |
| **BLUE REFLECTION: Second Light** (standalone) | `Data/PACK01.PAK` (dialogue) | Same; the interface is already French thanks to the fan beta |

Everything else (scripts, images, models, videos) is left untouched.

> **Second Light quality.** Only 61 events and the starting system text come
> from a human translation; the rest (≈ 4,300 events and ≈ 5,700 system
> strings) is **machine translation** awaiting proofreading. The dataset is
> split into `dialogue.xml` + `dialogue_1.xml` … `dialogue_16.xml`
> (`dataset_second_light/` folder) to make proofreading easier.

## Translation method

The patch contains **no hand-written translation made for this project**: it
reuses existing French translations and fills the gaps automatically. Where the
text comes from depends on the game.

### First game (2017 and Quartet b1): human translation

1. The text comes from the fan translation *Blue Reflection French Translation*
   (release 8, v1.1), written by human translators from the official English.
2. It is **extracted**, then **cleaned automatically** and reproducibly
   (`br_french_cleanup.py`): unified terminology ("Sephira" / "Sephirot"), a few
   grammar fixes, and a fallback for the accents missing from the game's font.
3. It is **aligned** with the project's canonical base by message identifier
   (the release's Japanese files are byte-identical), then repacked into a
   compact dataset (`dataset/`).

### Second Light: mixed translation, human then automatic

| Part | Source | Volume |
|---|---|---|
| Opening dialogue | Fan beta *BRSL fr-FR V1.02 beta 2* (human, accents fixed) | 61 events |
| System text (menus, buttons, items…) | Same beta, **human** | 12,209 strings |
| Rest of the dialogue | **Machine translation** English → French | ≈ 4,290 events |
| Missing system text | **Machine translation** English → French | ≈ 5,700 strings |
| Strings identical to the first game | Reused from the first game's French | 499 strings |
| Markers and technical tags | Kept as they are | — |

The machine translation was produced by **AI agents (language models)**, in
batches, from Second Light's **official English**. Message and speaker
identifiers are kept; technical slots with no real text are copied unchanged. It has
**not been proofread by a human**: it may contain errors of meaning, tone,
register or terminology.

Automatic processing applied afterwards:

- fixing the beta's **mojibake** (badly encoded accented characters);
- an **accent fallback** for characters missing from the game's bitmap font
  (for example `ç` → `c`), excluding `é`, which exists in the font;
- normalisation of line breaks (`<CR>`) and control characters.

### Applying it to the game

- Dialogue is written **by message identifier** when it is unique, or **by
  position** when the whole sequence (identifier + speaker) matches the game
  file exactly; otherwise the line stays in English rather than risk a shift.
- System text is written **by string number** (`String_No`) into the
  `strcombineall.xml` table.
- Only the text changes: voices, speakers, expressions and timings are
  written back unchanged.

### Proofreading and fixing

The Second Light dataset is a set of readable XML files in
`dataset_second_light/` (`dialogue.xml`, `dialogue_1.xml` … `dialogue_16.xml`,
`names.xml`, `places.xml`, `items.xml`, `messages.xml`, `other.xml`). Edit only
the content of the `<message>` / `<string>` tags, without touching identifiers
or the game's tags (`<CR>`, `<CLGR>`, `<IM04>`, `%d`…), then run the
installation again. In the repository these files are under
`titles/second_light/translation_fr/`.

## Requirements

- **Windows**: nothing else, `gust_pak.exe` is included.
- **Linux**: `gust_pak` must be available (`GUST_PAK` variable or `PATH`), see
  <https://github.com/VitaSmith/gust_tools/releases>.
- **Python 3.8+** (`py -3` or `python` on Windows, `python3` on Linux).
- A PC copy of the relevant game (Steam included).

## How to install

### Interactive mode

Run the launcher **with no arguments**: it detects installed games and offers,
for each one, to **install French** or **restore English**.

```bat
RUN.cmd
```

```bash
./RUN.sh
```

A **Quartet** folder is listed twice: "b1 partition" (first game) and "b4
partition: Second Light". They install independently. Entering a game folder
manually is always available.

### Direct mode

```bat
RUN.cmd apply  --game-dir "D:\Games\BLUE REFLECTION"      :: 2017: French
RUN.cmd revert --game-dir "D:\Games\BLUE REFLECTION"      :: 2017: English

python br_quartet_french_patch.py       apply  --game-dir "D:\Games\BLUE REFLECTION Quartet"   :: Quartet b1
python br_quartet_french_patch.py       revert --game-dir "D:\Games\BLUE REFLECTION Quartet"
python br_second_light_french_patch.py  apply  --game-dir "D:\Games\BLUE REFLECTION Quartet"   :: Quartet b4
python br_second_light_french_patch.py  revert --game-dir "D:\Games\BLUE REFLECTION Quartet"
python br_second_light_french_patch.py  apply  --game-dir "D:\Games\BLUE REFLECTION Second Light"

python br_french_installer.py                              :: interactive menu
RUN.cmd status --game-dir "D:\Games\BLUE REFLECTION"       :: check the state (2017)
RUN.cmd self-check                                         :: test the tool
```

### French videos

If a `movies/` folder sits next to `RUN.cmd` (or via `--movies-dir`),
`apply --with-movies` also installs the 4 re-encoded `.wmv` videos into
`DATA/x64/Movie/`, with backup and restore. They are large (≈ 750 MB) and
shipped separately (`BR_French_Patch_Movies.zip`).

## Steam and updates

Steam may replace the modified archives during an **update** or a **file
integrity check**; the game then goes back to English without breaking
anything. Simply run the installation again:

- for **Second Light**, the tool recognises an archive replaced by Steam, takes
  it as the new original and refreshes the backup;
- do **not** run `revert` after an update: it would put back the backup, which
  may be older than Steam's version.

## Backups and reverting to English

Each patch keeps its own backups inside the game folder:

| Patch | State folder |
|---|---|
| 2017 | `.br_french_patch/` |
| Quartet b1 | `.br_french_quartet_patch/` |
| Quartet b4 / Second Light | `.br_french_second_light/` |

`revert` (or "Restore English" in the menu) puts the originals back. You can
switch between French and English as often as you like. If an installation
fails part-way, nothing is modified.

## How it works

1. **Pre-flight**: checks the installation and the expected text members.
2. **Extraction** of your archives with `gust_pak` (short temporary folder,
   removed afterwards, to avoid Windows' path-length limit).
3. **Patching** of the dialogue, aligned by message identifier, and of the
   system table `strcombineall.xml`, whose encrypted `.e` envelope is
   regenerated ("BR1" key for the first game, "Second Light A21" key for Second
   Light).
4. **Verification**: the rebuilt archives are re-extracted and compared.
5. **Installation**: the archives are replaced and the state is recorded in
   `state.json`.

### Safety rules

- A dialogue line is only written if it lands on the right line: by message
  identifier when it is unique, or by position when the whole sequence
  (identifier + speaker) matches the game file exactly.
- A system string whose run-time tokens (`%d`, `<NUM1>`, `<STR1>`, `<IM..>`)
  differ from the original stays in English, as do empty entries and `[[...]]`
  markers.

## Known limitations

- **BLUE REFLECTION (2017)**: 8 scripts (`fe08_150/160/170/180`,
  `yy03_060/130/140/150`) have a different message count in the French release;
  they stay in English by default (`--allow-structural-mismatch` forces a
  partial alignment).
- **Second Light**: about 290 event messages, in scripts whose structure differs
  from the dataset, stay in English. On the standalone version, 55 scripts with
  an unsupported EBM layout are skipped.
- French translations are often longer than the English: check for text
  overflowing its box.
- The game's bitmap font lacks some accented characters: a fallback replaces
  some of them with their ASCII equivalent (`ça` → `ca`), mostly in the
  **BLUE REFLECTION (2017)** translation and in the machine-translated part of
  Second Light. See `br_french_cleanup.py`.
- **Images** (chapter titles, help screens) remain in English.
- The text is written into the game's "English" members: run the game with its
  normal English configuration.
- This patch touches the same members as the English "UNBURGER" retranslation:
  do not install both on the same partition.

## Credits and provenance

- First game: fan translation "*Blue Reflection French Translation*" (release 8,
  v1.1). Its 1,758 Japanese files are byte-for-byte identical to the project's
  canonical base, which guarantees alignment.
- Second Light: fan beta "*BRSL fr-FR V1.02 beta 2*" (human text, accents
  fixed), completed with machine translation.
- The tool and the envelope codec are a Python port of `Blue_Reflection_Patcher`
  (repository *Blue-Reflection-Quartet-Uncensor-Restore-Translation-Unburger-
  Mod*). `gust_pak` comes from
  [gust_tools](https://github.com/VitaSmith/gust_tools) (zlib licence, see
  `LICENSE.gust_tools.txt`).
