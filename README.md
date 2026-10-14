# BLUE REFLECTION UNBURGER Mod

**🇫🇷 [Français](#français)** · **🇬🇧 [English](#english)**

| | Français | English |
| --- | --- | --- |
| Présentation / Overview | [Traduction](#traduction) | [Translation](#translation) |
| Installation | [Installation du mod](#installation-du-mod) | [Installation](#installation) |
| Patch français / French patch | [Patch de traduction française](#patch-de-traduction-française) | [French translation patch](#french-translation-patch) |
| État / Status | [État actuel et limites](#état-actuel-et-limites) | [Current status](#current-status-and-limitations) |
| Développement / Development | [Outils du dépôt](#outils-du-dépôt) | [Repository tools](#repository-tools) |

---

# Français

[↑ Haut de page](#blue-reflection-unburger-mod) · [English ➜](#english)

## Sommaire

- [Traduction](#traduction)
  - [Voix des personnages et relations](#voix-des-personnages-et-relations)
  - [État de la traduction](#état-de-la-traduction)
- [Restauration Quartet et uncensor](#restauration-quartet-et-uncensor)
- [Restauration des DLC supprimés dans Quartet](#restauration-des-dlc-supprimés-dans-quartet)
  - [Accès aux sauvegardes pour les DLC restaurés de BLUE REFLECTION](#accès-aux-sauvegardes-pour-les-dlc-restaurés-de-blue-reflection)
- [Installation du mod](#installation-du-mod)
  - [Jeux et modules pris en charge](#jeux-et-modules-pris-en-charge)
  - [Source optionnelle pour les DLC](#source-optionnelle-pour-les-dlc)
- [Patch de traduction française](#patch-de-traduction-française)
  - [Jeux pris en charge par le patch français](#jeux-pris-en-charge-par-le-patch-français)
  - [Installer le patch français](#installer-le-patch-français)
  - [Steam et mises à jour](#steam-et-mises-à-jour)
  - [Méthode de traduction](#méthode-de-traduction)
  - [Limites du patch français](#limites-du-patch-français)
  - [Documentation détaillée du patch français](#documentation-détaillée-du-patch-français)
- [État actuel et limites](#état-actuel-et-limites)
- [À propos du projet](#à-propos-du-projet)
- [Outils du dépôt](#outils-du-dépôt)
  - [Organisation du dépôt](#organisation-du-dépôt)
  - [Bases de traduction](#bases-de-traduction)
  - [Compiler et tester le patcher](#compiler-et-tester-le-patcher)
  - [Travailler avec les modules](#travailler-avec-les-modules)
  - [Construire une release](#construire-une-release)
  - [Validation et état local](#validation-et-état-local)
  - [Règles de distribution](#règles-de-distribution)

Un projet de traduction, d'uncensor et de restauration de contenu pour la série BLUE REFLECTION sur PC. Ce fork s'adresse en priorité aux francophones : toute la documentation est fournie en français, puis en anglais, et un patch de traduction **française** est inclus.

La traduction incluse dans ce mod couvre toutes les éditions PC prises en charge par le projet. Cela comprend les versions PC d'origine de **BLUE REFLECTION** et de **BLUE REFLECTION: Second Light**, ainsi que **BLUE REFLECTION**, **Second Light**, **SUN** et **RAY** tels qu'inclus dans **BLUE REFLECTION Quartet**.

La version Quartet du premier jeu bénéficie aussi d'un travail de restauration visuelle et du retour de contenus retirés de la compilation, notamment les DLC de costumes de la version PC d'origine et Tropical Island.

Le projet est encore en bêta. Le travail de traduction se poursuit sur toute la série, et plusieurs volets de la restauration de Quartet sont encore en cours de recherche et de test.

## Traduction

Les scripts anglais officiels vont souvent plus loin qu'une simple traduction du japonais. Des répliques ordinaires sont étoffées de blagues, de jeux de mots ou de références écrites pour la localisation. Des réactions retenues deviennent plus appuyées. Des informations disparaissent d'autres scènes. Certains changements touchent les motivations, les relations ou la manière dont un personnage est perçu au fil du jeu.

Une ligne qui rend déjà fidèlement le japonais et se lit naturellement est laissée telle quelle. Une ligne n'est modifiée que lorsque la source révèle un vrai problème de sens, de caractérisation, de ton, de terminologie ou de contenu manquant.

Un problème récurrent est l'ajout de blagues là où le japonais présente une phrase parfaitement normale et sans ambiguïté.

Dans **Second Light**, le japonais dit :

> 戦うしかなさそうだね。  
> 伶那大先生にのびのび絵を描いてもらうためにも

Le personnage dit qu'il va falloir se battre pour que la Grande Maîtresse Rena puisse peindre tout son soûl.

L'anglais officiel en fait :

> Looks like I'll have to fight. Rena-rdo da Vinci needs to finish her masterpiece in peace.

Il n'y a aucun jeu de mots « Rena-rdo da Vinci » dans le japonais, et il n'est pas question de chef-d'œuvre. La traduction actuelle donne (en anglais) :

> Looks like we'll have to fight.  
> Great Master Rena needs to draw to her heart's content, after all.

Une autre ligne est simplement :

> 横暴だ……

L'anglais officiel donne :

> You fascist...

Le japonais se plaint de quelque chose de tyrannique ou d'autoritaire. Personne n'est traité de fasciste.

La traduction actuelle donne :

> That's tyranny...

Le même problème apparaît sous des formes moins évidentes. Un avertissement tout simple :

> 油断しないで。  
> そうやっておごってる時が一番危険なんだから

est devenu :

> Don't ever let your guard down. Overconfidence is a slow and insidious killer.

Le japonais dit simplement de ne pas baisser sa garde, car on est le plus vulnérable quand on fait le malin de cette façon. La formulation supplémentaire a été ajoutée par la localisation.

Une autre scène dit :

> 蝶のように舞い、蜂のように刺す！

C'est la version japonaise de la célèbre citation anglophone de Mohamed Ali, **« Float like a butterfly, sting like a bee »** (« Vole comme un papillon, pique comme une abeille »).

L'anglais officiel la remplace par :

> every rose has its thorn

La ligne japonaise contient déjà une transposition directe d'une citation célèbre en anglais. La localisation la remplace pourtant par un proverbe sans rapport.

La traduction actuelle rétablit :

> Float like a butterfly, sting like a bee!

Les changements les plus importants dépassent les blagues isolées. Le premier **BLUE REFLECTION** contient des passages manquants ou réécrits concernant la blessure de Hinako, ses raisons de continuer à se battre, le Common, les Sephira, le passé de Mao, la mort de Yuzu et de Lime, le plan de Daath et les conséquences du combat final. Plusieurs événements de personnages ont vu leurs motivations raccourcies ou réorientées au point de changer le sens de la scène.

Certaines réécritures modifient aussi la façon dont les personnages parlent au fil du temps. Ako reçoit des blagues récurrentes et des étiquettes propres à la localisation. Des réactions discrètes ou hésitantes peuvent devenir des répliques beaucoup plus bruyantes. Les habitudes propres à chaque personnage sont aplaties quand l'anglais officiel les remplace par une voix plus générique.

Le patch rétablit la source au lieu d'essayer de conserver ces réécritures en les contournant.

### Voix des personnages et relations

La manière de parler de chaque personnage fait partie du texte.

Les honorifiques comme *-san*, *-chan*, *-kun*, *-senpai* et *-sama* sont conservés lorsqu'ils apparaissent en japonais et qu'ils portent une information sur la relation ou le personnage.

Les formes d'adresse familiales et habituelles sont traitées selon le contexte. Des formes comme *Onee-chan* restent quand un personnage les emploie réellement ainsi. Une simple référence descriptive devient en revanche un anglais naturel comme *older sister* ou *younger brother*.

Les noms suivent l'ordre japonais, le nom de famille avant le prénom.

Les particularités de langage de chaque personnage sont également préservées : différences de niveau de politesse, formes d'adresse récurrentes, tics de langage individuels et cas où un personnage parle d'elle-même en utilisant son prénom au lieu d'un pronom de première personne ordinaire.

L'anglais suit toujours la structure normale d'une phrase anglaise. Préserver une particularité du japonais ne signifie pas reproduire la grammaire japonaise mot à mot.

Les termes culturels sont conservés lorsque les remplacer ferait perdre une information sur le cadre ou changerait le sujet de la conversation. Il en va de même pour les jeux de mots japonais qui ont un sens. Une blague peut devoir être adaptée pour fonctionner en anglais, mais on n'ajoute pas une nouvelle blague à une ligne qui n'en était pas une.

### État de la traduction

La traduction est actuellement en **bêta**.

Les mauvaises traductions les plus évidentes, les omissions, les ajouts propres à la localisation, les modifications de l'écriture des personnages et les principaux problèmes de terminologie trouvés jusqu'ici ont déjà été corrigés. L'ordre japonais des noms, les honorifiques et les particularités de langage des personnages ont aussi été rétablis dans tous les scripts.

Le travail de traduction continue. Les scripts pris en charge feront l'objet de nouveaux tests en jeu, d'un travail de cohérence entre les titres et d'un polissage ligne par ligne. Certains problèmes n'apparaissent que lorsqu'une ligne est vue dans la scène réelle. D'autres lignes peuvent être exactes mais demander un anglais plus naturel.

Le texte actuel doit donc être considéré comme une traduction de travail et non comme un script final.

## Restauration Quartet et uncensor

**BLUE REFLECTION Quartet** ne contient pas le premier **BLUE REFLECTION** exactement tel qu'il apparaissait dans la version PC de 2017. Certains éléments et comportements de rendu ont été modifiés lors de son intégration à la compilation.

Le travail de restauration compare directement la version PC d'origine à Quartet. La comparaison porte sur les archives concernées, les modèles, les textures, les matériaux, les effets et le comportement à l'exécution. Un changement n'est restauré que s'il peut être rattaché au jeu d'origine.

La restauration de l'eau de la salle de bain est validée à l'exécution et fait partie du module UNCENSOR standard. Quand UNCENSOR est sélectionné, le patcher applique automatiquement la restauration approuvée de `PACK10_03`, protégée par somme de contrôle.

Le `.unburger` public standard embarque aussi les trois vidéos restaurées compatibles Quartet (`CNG_PC00_00.webm`, `CNG_PC01_00.webm`, `CNG_PC02_00.webm`). La restauration des vidéos est un enfant activé par défaut d'UNCENSOR. `BUILD_RELEASE.sh` exige et valide ces fichiers WebM ; ils ne font pas partie de `.unburger-assets`.

Le système de vêtements mouillés est plus compliqué. Des tests contrôlés à l'exécution ont reproduit le composant manquant de surface mouillée et de gouttelettes, et confirmé davantage du chemin de rendu mouillé d'origine. Ces changements expérimentaux ne font pas encore partie du module de restauration standard. La différence d'opacité des vêtements restante dans `ce01_040` a été réduite à une comparaison RenderDoc de la passe principale PBB entre l'Original et Quartet, plutôt qu'à une nouvelle recherche statique large.

Dans le jeu d'origine, l'humidité n'affecte pas que l'uniforme. Les vêtements, la peau et les cheveux participent à l'état mouillé, et le changement d'humidité fait résoudre au jeu un état de rendu du personnage plus large. La différence de transparence restante est donc suivie à travers le chemin natif de l'humidité, au lieu de forcer une modification de texture qui n'a l'air proche que dans une seule scène.

D'autres différences découvertes pendant la comparaison restent à l'étude. Elles ne rejoindront le module de restauration standard qu'après avoir résisté aux tests à l'exécution et pouvoir être reproduites sans abîmer des scènes ou des éléments sans rapport.

## Restauration des DLC supprimés dans Quartet

Quartet a retiré une grande partie des DLC du premier jeu.

La suppression s'est faite à plusieurs niveaux. Des centaines d'éléments source ont disparu de la compilation. Les fiches de costumes qui ont survécu ont été redirigées vers des uniformes ordinaires. Les noms de costumes ont été supprimés. Les données internes de garde-robe ont été réduites à la sélection beaucoup plus petite que Quartet a conservée.

Recopier les modèles manquants dans le jeu laisse donc le contenu inaccessible. Il a fallu reconstruire le chemin complet utilisé par le jeu d'origine.

Les éléments manquants ont été identifiés dans la version PC de 2017 et rattachés à leurs équivalents Quartet. Les fiches de personnages et les tables de texte ont été restaurées. Les données de garde-robe ont été étendues pour que les entrées supplémentaires coexistent avec les costumes déjà présents dans Quartet. Les limites et références côté jeu qui supposaient la garde-robe réduite de Quartet ont aussi dû être mises à jour pour que la liste étendue puisse être utilisée en toute sécurité.

La restauration obtenue ramène **66 costumes issus de la source, pour les 15 personnages**.

Les costumes restaurés apparaissent comme des entrées supplémentaires dans le Dressing Room. Ils conservent les tenues Quartet existantes, affichent leur nom correct et chargent le bon modèle pour chaque personnage. La sélection de costume continue de fonctionner après un retour au jeu normal.

Les 24 autres fiches de costumes supprimées sont volontairement laissées indisponibles. Leurs modèles n'ont jamais été inclus dans la version PC du jeu de 2017. Elles correspondent à des tenues propres à d'autres plateformes, dont les données PC contiennent des références mais pas les éléments de personnage réels. Les exposer créerait des entrées sélectionnables qui retomberaient sur le mauvais modèle.

**Tropical Island** a également été restaurée. Le contenu de carte manquant, les événements et le chemin des dialogues ont été reconstruits et confirmés en jeu.

Les éléments source proviennent normalement de votre propre installation de **BLUE REFLECTION** 2017. Le jeu de base suffit. Il n'est pas nécessaire de posséder séparément ses DLC de costumes, car l'installation PC de base contient déjà les éléments de costumes utilisés par la restauration.

Un paquet source `.unburger-assets` compatible peut être utilisé à la place de la conservation du premier jeu complet. Un tel paquet est créé localement à partir d'une installation vérifiée de **BLUE REFLECTION** 2017 et ne contient que les données source nécessaires à la restauration actuelle, plutôt que les archives complètes du jeu. Si un paquet compatible est placé à côté du `.unburger` normal du patcher, celui-ci peut le détecter et l'utiliser automatiquement.

La version publique du mod ne distribue pas ces éléments de jeu propriétaires. Ils doivent provenir de votre propre copie du jeu, soit directement depuis l'installation, soit via un paquet source compatible créé à partir de celle-ci.

### Accès aux sauvegardes pour les DLC restaurés de BLUE REFLECTION

Pour le chemin DLC restauré de **BLUE REFLECTION (2017)**, restaurer les fichiers du jeu Quartet ne modifie pas rétroactivement l'état d'accès à la garde-robe et à Tropical Island déjà enregistré dans une sauvegarde existante.

Quand la famille source BLUE REFLECTION de la **restauration des DLC** est installée, le patcher gère l'accès aux sauvegardes BR1 dans le même parcours guidé. Une fois les fichiers du jeu préparés, il recherche les sauvegardes Quartet existantes et peut traiter tous les emplacements trouvés dans le dossier de sauvegarde choisi. La mise à jour active l'accès à la garde-robe étendue de 122 entrées et à l'indicateur d'événement de Tropical Island restaurée.

Les emplacements de sauvegarde standard de Windows natif et de Steam/Proton sont détectés automatiquement lorsque c'est possible. L'écran interactif de sélection des sauvegardes propose toujours l'option **Saisir / coller manuellement un dossier de sauvegarde / un `.pcsave` / un préfixe Wine ou Proton**, même quand un ou plusieurs emplacements ont été détectés automatiquement. Pour Heroic, une configuration Wine/Proton personnalisée ou un autre préfixe indépendant, collez la racine du préfixe contenant `drive_c` ; un dossier de sauvegarde ou un fichier `.pcsave` individuel peut aussi être choisi directement.

Les fichiers de sauvegarde sont copiés avant d'être modifiés et le résultat est vérifié ensuite. Les copies de sauvegarde existantes ne sont pas traitées comme des emplacements de sauvegarde actifs.

`SAVE_ACCESS.sh` sous Linux et `SAVE_ACCESS.cmd` sous Windows sont fournis pour les sauvegardes créées plus tard. Une sauvegarde déjà mise à jour conserve ces indicateurs d'accès lorsque son état est écrit dans un autre emplacement. En revanche, une toute nouvelle partie ou une sauvegarde nouvellement créée part de l'état par défaut normal du jeu : l'accès aux sauvegardes doit donc, pour l'instant, être relancé pour cette nouvelle sauvegarde.

Cette étape supplémentaire pour les nouvelles sauvegardes est une limite temporaire de la méthode de restauration actuelle. Une version future pourrait déplacer l'accès aux DLC restaurés dans l'initialisation du jeu à l'exécution, afin que les nouvelles sauvegardes le reçoivent automatiquement.

La partition **Second Light** de Quartet est restaurée par le même module DLC. La restauration comprend les familles de costumes et de contenus supprimées, les cartes et terrains de combat des DLC, les données d'événements, de dialogues et de notifications, le routage des installations et de l'histoire, Resonance Tide et le contenu lié à Ryza couverts par le chantier actuel. Le noyau 0.0.107 a été validé à l'exécution par l'utilisateur avec cette restauration des DLC sous Linux comme sous Windows.

Second Light utilise une stratégie d'accès différente de BR1 : les sauvegardes natives de Second Light dans Quartet **n'exigent pas** de modification des sauvegardes. L'accès aux DLC est restauré par un nouveau verrouillage des données de jeu et de l'histoire. La gestion optionnelle de la parité des droits pour les sauvegardes converties ou externes reste distincte et n'est pas nécessaire pour les sauvegardes Quartet natives normales.

## Installation du mod

Un seul patcher sert pour toutes les installations PC prises en charge.

Utilisez le lanceur de votre système d'exploitation (`RUN.sh` sous Linux ou `RUN.cmd` sous Windows). Les installations prises en charge sont détectées automatiquement quand c'est possible. Dans l'installeur interactif, **Saisir / coller manuellement le dossier du jeu** est toujours proposé à côté des installations détectées, y compris lorsqu'une seule installation a été détectée.

Sous Windows, lancez `RUN.cmd` normalement ou indiquez explicitement le dossier du jeu, par exemple `RUN.cmd --game-dir "D:\Games\BLUE REFLECTION Quartet"`. Un simple chemin sans option, comme `RUN.cmd "D:\Games\BLUE REFLECTION Quartet"`, est aussi accepté en raccourci. Les droits administrateur ne sont pas nécessaires pour la détection.

Si le patcher ne détecte pas le chemin tout seul, placez tous les fichiers de l'archive directement dans le dossier principal du jeu choisi. Le lanceur se place dans son propre dossier de release avant la détection : cela fonctionne donc même si Windows démarre le script avec un autre répertoire courant.

### Jeux et modules pris en charge

| Jeu | Modules disponibles |
| --- | --- |
| **BLUE REFLECTION (2017)** | Traduction |
| **BLUE REFLECTION: Second Light** | Traduction |
| **BLUE REFLECTION Quartet** | Traduction de BLUE REFLECTION, Second Light, SUN et RAY ; UNCENSOR/restauration pour la partition BLUE REFLECTION ; restauration des DLC pour les partitions BLUE REFLECTION et Second Light |

La traduction, UNCENSOR et les DLC restent sélectionnables indépendamment. Le composant des vidéos restaurées est un enfant d'UNCENSOR, activé par défaut.

### Source optionnelle pour les DLC

La restauration des DLC a besoin de données source provenant des jeux autonomes correspondants. Le contenu de BLUE REFLECTION peut venir d'une copie PC installée de 2017 ; celui de Second Light, de l'installation autonome de Second Light. Un paquet `.unburger-assets` combiné et compatible peut à la place porter les sous-ensembles source réduits des deux familles. Pour BLUE REFLECTION, l'installation PC de base suffit ; il n'est pas nécessaire de posséder séparément ses DLC de costumes, car les éléments de costumes PC requis sont déjà présents dans cette installation.

Si un fichier `.unburger-assets` compatible est placé à côté de la charge utile `.unburger` normale de la release, le patcher le détecte automatiquement et utilise les capacités présentes dans le paquet. Les capacités d'une famille source manquantes peuvent se rabattre sur le jeu autonome installé correspondant. Les sous-ensembles source logiques figés actuels sont 1 682 éléments BR1 plus 2 942 éléments Second Light (4 624 éléments logiques au total).

Le paquet source optionnel sert à la restauration des DLC. La traduction et UNCENSOR n'en ont pas besoin. Les trois vidéos WebM restaurées ne sont explicitement **pas** stockées dans `.unburger-assets` ; elles sont fournies dans le `.unburger` public normal.

Dans le cadre de l'installation des DLC de BLUE REFLECTION, le patcher propose aussi l'accès aux sauvegardes BR1, afin que les emplacements Quartet existants puissent utiliser immédiatement les costumes restaurés et Tropical Island. `SAVE_ACCESS.sh` sous Linux et `SAVE_ACCESS.cmd` sous Windows ne sont nécessaires que plus tard, pour une sauvegarde nouvellement créée ou comme solution manuelle quand la détection des sauvegardes ne convient pas.

Avant d'écrire dans les fichiers du jeu, le patcher vérifie l'installation actuelle et les éléments nécessaires aux modules choisis. La compatibilité est déterminée à partir de la structure du jeu et du contenu modifié, et non en exigeant une version exacte du jeu complet.

Le patcher reconstruit les archives nécessaires à partir de vos fichiers actuels. Les entrées d'archive sans rapport sont conservées. Les modifications existantes qui n'entrent pas en conflit avec les opérations choisies peuvent donc rester en place.

Les sauvegardes et l'état de la transaction sont créés avant le remplacement final. Une opération échouée n'est pas considérée comme une installation réussie, et les changements gérés peuvent être annulés via le patcher.

Les grosses opérations utilisent une interface de terminal structurée qui indique l'étape en cours, la progression globale, le fichier ou l'opération actifs et les longs travaux de vérification, d'installation ou d'annulation, au lieu de laisser le terminal sans retour.

Quand plusieurs modules choisis touchent le même contenu, les changements sont composés avant l'écriture des fichiers finaux.

Pour Quartet, l'ordre de composition effectif est :

```text
Restauration des DLC de BLUE REFLECTION, si sélectionnée
Restauration des DLC de Second Light, si sélectionnée
Restauration / UNCENSOR
Contenu enfant des vidéos restaurées
Traduction
```

La traduction est appliquée en dernier. Restaurer les DLC ne remet donc pas l'anglais officiel d'origine par-dessus le texte traduit des DLC.

## Patch de traduction française

Un patch **français** distinct, limité au texte, est disponible pour les jeux PC de la série. Il est indépendant des modules anglais UNBURGER (traduction, uncensor, DLC), s'applique sur **votre propre installation** avec Python et `gust_pak`, et peut être annulé à tout moment. Aucune archive complète des jeux n'est redistribuée.

Ne l'installez pas en même temps que la traduction anglaise sur la même partition : les deux modifient les mêmes fichiers texte.

### Jeux pris en charge par le patch français

| Jeu | Texte français |
| --- | --- |
| **BLUE REFLECTION (2017)** | Traduction fan humaine, nettoyée |
| **BLUE REFLECTION Quartet**, partition b1 (premier jeu) | Même texte que la version 2017 |
| **BLUE REFLECTION Quartet**, partition b4 (Second Light) | Bêta fan pour une partie, **traduction automatique** pour le reste |
| **BLUE REFLECTION: Second Light** (version isolée) | Idem, dialogues seulement (l'interface est déjà en français grâce à la bêta fan) |

### Installer le patch français

Le patch français s'installe avec son propre lanceur, dans le paquet construit par `python Blue_Reflection_Text_Tool/br_french_patch.py build-bundle` :

1. Installez **Python 3.8+** (sous Linux, rendez aussi `gust_pak` disponible ; sous Windows il est fourni).
2. Lancez `RUN.cmd` (Windows) ou `./RUN.sh` (Linux) **sans argument**.
3. Choisissez le jeu détecté (un dossier Quartet apparaît deux fois : « partition b1 » et « partition b4 : Second Light »), puis **Installer la traduction française** ou **Restaurer l'anglais**.

Chaque patch garde ses propres sauvegardes dans le dossier du jeu : vous pouvez revenir à l'anglais puis repasser en français à tout moment.

### Steam et mises à jour

Une mise à jour ou une vérification des fichiers Steam peut remplacer les archives modifiées : le jeu repasse en anglais sans rien casser. Relancez simplement l'installation. Pour Second Light, l'outil reconnaît l'archive remplacée par Steam et renouvelle la sauvegarde. Ne lancez pas « Restaurer l'anglais » après une mise à jour : il remettrait une sauvegarde peut-être plus ancienne.

### Méthode de traduction

- **Premier jeu** : traduction fan *Blue Reflection French Translation* (release 8, v1.1), écrite par des humains, puis nettoyée automatiquement (terminologie, grammaire, repli des accents absents de la police) et alignée par identifiant de message.
- **Second Light** : texte humain de la bêta fan *BRSL fr-FR V1.02 beta 2* pour 61 événements et 12 209 chaînes système ; le reste est une **traduction automatique** anglais → français faite par des agents d'IA à partir de l'anglais officiel, **non relue par un humain**.
- Le texte n'est écrit que s'il tombe à coup sûr sur la bonne ligne ; sinon il reste en anglais.

### Limites du patch français

- La traduction française de Second Light attend une relecture.
- Environ 290 messages d'événements de Second Light restent en anglais (scripts dont la structure diffère du dataset).
- Les textes français, souvent plus longs que l'anglais, peuvent déborder de leur cadre.
- La police du jeu n'a pas tous les caractères accentués : un repli les remplace par leur équivalent ASCII à certains endroits.
- Les images (titres de chapitre, écrans d'aide) restent en anglais.

### Documentation détaillée du patch français

- [Documentation complète (FR + EN)](Blue_Reflection_Text_Tool/french_patch_bundle/README.md)
- [Jeux pris en charge](Blue_Reflection_Text_Tool/french_patch_bundle/README.md#jeux-pris-en-charge)
- [Méthode de traduction détaillée](Blue_Reflection_Text_Tool/french_patch_bundle/README.md#m%C3%A9thode-de-traduction)
- [Installation et mode direct](Blue_Reflection_Text_Tool/french_patch_bundle/README.md#installation)
- [Sauvegardes et retour en anglais](Blue_Reflection_Text_Tool/french_patch_bundle/README.md#sauvegardes-et-retour-en-anglais)
- [Fonctionnement et règles de sécurité](Blue_Reflection_Text_Tool/french_patch_bundle/README.md#fonctionnement)
- Dataset de Second Light à relire : [`titles/second_light/translation_fr/`](titles/second_light/translation_fr/)

## État actuel et limites

La traduction reste en bêta et continuera de faire l'objet de révisions importantes.

La restauration des DLC de Quartet pour le premier **BLUE REFLECTION** est fonctionnelle. L'ensemble de costumes restauré, les noms de costumes, le routage des personnages et Tropical Island ont été confirmés en jeu. La restauration des DLC de Second Light a elle aussi un PASS à l'exécution par l'utilisateur sous Linux et Windows avec le noyau 0.0.107 ; le routage des costumes et contenus restaurés et la composition avec la traduction sont actifs. Des vérifications ponctuelles du contenu restauré peuvent continuer sans que la pile DLC soit considérée comme bloquante au démarrage.

L'uncensor complet de Quartet est encore en développement. La restauration de l'eau de la salle de bain est validée et canonique. Les trois cinématiques restaurées sont du contenu canonique de la release publique. La transparence des vêtements mouillés, les candidats de restauration de caméra/cadrage, les restaurations du sélecteur de couverture UDW et les candidats serviette/occulteur restent des chantiers distincts, soumis à des preuves.

Vingt-quatre fiches de costumes supprimées du premier jeu ne peuvent pas être restaurées à partir de la version PC, car les modèles nécessaires n'ont jamais été livrés avec cette version.

Les mises à jour Steam ou la vérification des fichiers peuvent remplacer des fichiers de jeu modifiés. Dans ce cas, relancez le patcher pour qu'il reconstruise les modules choisis par-dessus la nouvelle installation actuelle.

## À propos du projet

Il s'agit d'un projet de fans non officiel.

La release publique ne contient pas les modèles de costumes, textures, fichiers de Tropical Island ni autres éléments de jeu propriétaires restaurés depuis la version d'origine. Le contenu requis d'un autre jeu est fourni depuis votre propre copie, soit directement depuis un jeu installé, soit depuis un paquet source `.unburger-assets` compatible créé localement.

Le projet vise à préserver les scripts, la présentation et le contenu d'origine des jeux tout en gardant le résultat utilisable sur les versions PC actuelles.

---

## Outils du dépôt

Cette section s'adresse aux contributeurs et au développement local. Elle n'est pas nécessaire pour installer le mod.

### Organisation du dépôt

Les principaux espaces du projet sont :

- `Blue_Reflection_Patcher/` contient le patcher natif et l'outillage de release.
- `titles/` contient les cibles propres à chaque titre, les données de modules et les bases de traduction canoniques.
- `workstreams/core/` gère l'architecture commune du patcher, les transactions, la composition et les contrats de release.
- `workstreams/translation/` gère le texte traduit et l'état de relecture de la traduction.
- `workstreams/translation_tooling/` gère l'outillage d'import, d'export et de validation de la traduction.
- `workstreams/quartet_restoration/` gère le travail de restauration visuelle de Quartet.
- `workstreams/quartet_legacy_dlc/` gère la restauration des DLC du premier jeu pour Quartet.
- `docs/` contient l'architecture du projet et la documentation des formats.
- `.local/` contient les builds générés, les preuves, les rapports, les espaces de travail temporaires et autres états propres à la machine. Ce n'est pas du contenu source suivi ou public. Il contient aussi le cache source « wet-school » canonique validé du développeur, utilisé pour reproduire les releases UNCENSOR sans garder l'installation BR1 autonome.

Chaque chantier actif a un fichier `VERSION`. Ceux qui exposent un état lisible par machine utilisent aussi `STATUS.json`.

### Bases de traduction

Les bases de traduction canoniques se trouvent dans :

```text
titles/blue_reflection/translation/
titles/second_light/translation/
titles/blue_reflection_sun/translation/
titles/blue_reflection_ray/translation/
```

Les fiches de traduction utilisent des identifiants logiques stables, de sorte que le même contenu traduit puisse être rattaché aux fichiers cibles appropriés sans être lié à une version précise d'archive.

Pendant le travail de traduction normal, ne modifiez que le champ `en`. Les champs comme `jp`, `en_original`, `en_auxiliary`, les métadonnées de source, les empreintes et les correspondances de cibles sont des données de référence qu'il ne faut pas modifier à la main.

Les données japonaises restent la source de vérité. `en_original` est l'anglais officiel de ce titre. `en_auxiliary` est un anglais de support issu d'une version liée, lorsqu'il existe et qu'il est utilisable.

Ne renumérotez pas les fiches, ne changez pas les identifiants logiques et ne réécrivez pas les métadonnées de source pour faire passer un import. Une incohérence de source doit être corrigée dans l'importeur ou dans la correspondance.

La base française de Second Light se trouve dans `titles/second_light/translation_fr/` (fichiers XML validés par `Blue_Reflection_Text_Tool/translation_fr.dtd`).

### Compiler et tester le patcher

Le patcher est un projet Go.

Lancez la suite de régression normale depuis son dossier :

```bash
cd Blue_Reflection_Patcher
go test ./...
go vet ./...
```

Compilez le patcher natif pour la plateforme actuelle avec :

```bash
go build ./cmd/brpatcher
```

Une compilation Windows amd64 peut être produite depuis Linux avec :

```bash
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o brpatcher.exe ./cmd/brpatcher
```

Ne considérez pas une compilation réussie comme une validation de release. Les changements qui touchent la matérialisation des archives, les transactions, la restauration ou les DLC doivent aussi passer les tests du chantier concerné et une validation contrôlée à l'exécution avant d'être éligibles à la production.

Pour le patch français (Python), la suite de tests se lance avec :

```bash
python -I -m unittest discover -s Blue_Reflection_Text_Tool/tests
```

### Travailler avec les modules

Les modules publics restent logiquement séparés jusqu'à la composition.

Les principaux identifiants de modules sont :

```text
blue_reflection_translation
second_light_translation
quartet_restoration
quartet_legacy_dlc
```

Le contenu généré d'un module doit rester séparé jusqu'à ce que le patcher effectue une étape de composition explicite. Les fiches de traduction restent dans les bases de traduction canoniques. Les données de restauration et de DLC restent dans leurs propres registres et contrats.

Pour Quartet, l'ordre de composition final est fixe :

```text
quartet_legacy_dlc
quartet_restoration
blue_reflection_translation
```

La traduction doit rester en dernier quand les modules se recouvrent.

La logique de compatibilité doit reposer sur la structure et les capacités réellement nécessaires à une opération. Les empreintes du jeu complet sont de bons diagnostics, mais pas une exigence de production pour installer le patch.

### Construire une release

Le constructeur de release à la racine est :

```bash
./BUILD_RELEASE.sh
```

Utilisez l'aide intégrée du script pour connaître les options prises en charge par la branche actuelle :

```bash
./BUILD_RELEASE.sh --help
```

Une construction de release normale lance la suite de régression Go, prépare le contenu de modules vérifié, construit les binaires du patcher pour Linux et Windows et produit le paquet public `Blue-Reflection-Unburger-Mod_<version>.zip` avec son fichier SHA-256. Le ZIP contient les lanceurs et binaires par plateforme ainsi que la charge utile `.unburger` versionnée.

Le jeu de donneurs UNCENSOR « wet-school » canonique n'est **pas reconstruit à partir d'une copie installée de BLUE REFLECTION (2017) à chaque construction de release**. Un développeur l'importe une fois avec `./IMPORT_CANONICAL_UNCENSOR_SOURCE.sh --source CHEMIN`. L'importeur vérifie le `PACK00_02.PAK` commercial approuvé, extrait uniquement les 30 éléments donneurs `SCL_W` PC00-PC14 éprouvés, et stocke la capacité réduite dans le cache local ignoré du projet `.local/Uncensor/quartet_wet_school_canonical_source_v1/`. Après cet import, les `./BUILD_RELEASE.sh` ordinaires n'utilisent que ce cache local validé ; l'installation BR1 autonome peut être absente. Passer `--canonical-source CHEMIN` à `BUILD_RELEASE.sh` est un rafraîchissement/import explicite de ce cache avant la construction, et non une dépendance normale de la construction.

Pour les tests locaux ou les constructions DLC répétées, `BUILD_RELEASE.sh --assets` produit aussi le paquet source combiné `.unburger-assets` à côté de la release normale. Il **réutilise par défaut un paquet vérifié existant** au lieu de le reconstruire à chaque fois depuis les jeux sources complets. Un paquet réutilisable normal utilise son fichier SHA-256 associé ainsi que les contrôles de contrat actuels (manifeste chiffré, 1 682 éléments BR1 + 2 942 éléments Second Light). Si un ancien paquet compatible précède la création du fichier SHA-256, le constructeur effectue une vérification complète unique (déchiffrement, matérialisation, objets, éléments) et crée seulement alors le fichier manquant ; il ne reconstruit pas à partir des sources commerciales juste pour créer ce fichier. Le dernier chemin de paquet réutilisable est mémorisé dans `.local/release/` du projet. Si aucun paquet compatible n'existe, le constructeur se rabat sur la reconstruction depuis les sources. Sur ce seul chemin de reconstruction, les fichiers d'entrée commerciaux réels de BR1 et de Second Light autonome sont contrôlés en taille et en SHA-256 par rapport au contrat de provenance de production figé ; les chemins source mémorisés ne sont que des indications, et ceux qui sont périmés sont rejetés avant la détection automatique via la configuration locale ou Steam. Quartet reste contrôlé par structure/capacité plutôt que verrouillé sur l'empreinte de fichiers entiers. Utilisez `--assets-bundle CHEMIN` pour choisir explicitement un paquet existant et `--assets-rebuild` pour forcer une reconstruction depuis les sources. Les options de chemins source ne restent disponibles que pour le chemin de reconstruction.

Un paquet `.unburger-assets` compatible placé à côté de la charge utile `.unburger` normale peut être détecté automatiquement par le patcher. Les capacités absentes du paquet peuvent se rabattre sur l'installation autonome appartenant à l'utilisateur.

Le constructeur de release doit échouer par défaut (fail closed) si le contenu de traduction requis est périmé ou incomplet, ou si les données source requises diffèrent de la source propre vérifiée. Les archives commerciales complètes et les paquets source DLC optionnels ne doivent jamais être embarqués dans le ZIP public du mod. Le `.unburger` normal ne contient que les charges utiles de restauration à l'exécution canoniques explicitement approuvées : la capacité source « wet-school » réduite de 30 éléments, les trois cinématiques WebM restaurées, le contenu de traduction et les métadonnées d'exécution rédigées par le projet. Les données source DLC optionnelles de BR1/Second Light restent en dehors du `.unburger` normal et sont fournies par `.unburger-assets` ou par les installations autonomes.

Le paquet du patch français se construit séparément :

```bash
python Blue_Reflection_Text_Tool/br_french_patch.py build-bundle
```

### Validation et état local

Le patcher utilise des écritures transactionnelles. Une transaction préparée enregistre l'état actuel des fichiers, le résultat voulu, les informations de préparation et les données d'annulation avant la validation.

Les données de développement générées appartiennent à `.local/` ou au dossier d'état de la plateforme du patcher, et non aux arbres sources canoniques. Les grosses archives extraites, les reconditionnements temporaires et les preuves d'exécution ne doivent pas être commités dans le dépôt.

Les bases de traduction canoniques, le code source, les schémas, les contrats et les preuves nécessaires pour justifier une règle de restauration en production doivent rester reproductibles sans chemins propres à une machine.

Avant de publier un changement, vérifiez au minimum :

```bash
cd Blue_Reflection_Patcher
go test ./...
go vet ./...
```

Lancez ensuite la validation adaptée au chantier modifié. Les constats uniquement observés à l'exécution ne doivent pas être promus vers les chemins d'installation normaux avant d'avoir été reproduits et enregistrés comme éligibles à la production.

### Règles de distribution

Les releases publiques contiennent le patcher, le contenu de traduction rédigé par le projet, les règles de modules et les métadonnées nécessaires pour reconstruire le résultat choisi.

Ne placez pas de PAK de jeu complets, de modèles, textures ou cartes propriétaires extraits, de paquets source `.unburger-assets` ni d'autres charges utiles de jeux sources dans le dépôt public ou le paquet de release.

La charge utile `.unburger` normale contient des données d'exécution rédigées par le projet, les règles de restauration et la charge utile approuvée des vidéos restaurées. Elle ne contient pas les éléments source bruts de BR1/Second Light utilisés par la restauration des DLC. Ces éléments doivent provenir de vos propres installations autonomes ou d'un paquet `.unburger-assets` compatible créé localement.

---

# English

[↑ Top](#blue-reflection-unburger-mod) · [➜ Français](#français)

An English translation, uncensor and content restoration project for the PC BLUE REFLECTION series.

The translation included with this mod supports every PC edition covered by the project. This includes the original PC releases of **BLUE REFLECTION** and **BLUE REFLECTION: Second Light**, together with **BLUE REFLECTION**, **Second Light**, **SUN** and **RAY** as included in **BLUE REFLECTION Quartet**.

The Quartet version of the first game also receives visual restoration work and the return of content removed from the collection, including the original PC costume DLC and Tropical Island.

The project is still in beta. Translation work continues across the series, while several parts of the Quartet restoration are still being researched and tested.

## Contents

- [Translation](#translation)
  - [Character voices and relationships](#character-voices-and-relationships)
  - [Translation status](#translation-status)
- [Quartet restoration and uncensor](#quartet-restoration-and-uncensor)
- [Restoring removed DLC in Quartet](#restoring-removed-dlc-in-quartet)
  - [Save access for restored BLUE REFLECTION DLC](#save-access-for-restored-blue-reflection-dlc)
- [Installation](#installation)
  - [Supported games and modules](#supported-games-and-modules)
  - [Optional DLC source bundle](#optional-dlc-source-bundle)
- [French translation patch](#french-translation-patch)
- [Current status and limitations](#current-status-and-limitations)
- [About the project](#about-the-project)
- [Repository tools](#repository-tools)
  - [Repository layout](#repository-layout)
  - [Translation databases](#translation-databases)
  - [Building and testing the patcher](#building-and-testing-the-patcher)
  - [Working with modules](#working-with-modules)
  - [Building a release](#building-a-release)
  - [Validation and local state](#validation-and-local-state)
  - [Distribution rules](#distribution-rules)

## Translation

The official English scripts often go further than translating the Japanese. Ordinary lines are expanded into jokes, puns or references written for the localization. Restrained reactions become stronger. Information disappears from other scenes. Some changes affect motives, relationships or the way a character comes across over the course of the game.

A line that already conveys the Japanese accurately and reads naturally is left alone. Lines are changed when the source shows a real problem with meaning, characterization, tone, terminology or missing content.

One recurring problem is the addition of jokes where the Japanese presents a completely normal and unambiguous sentence.

In **Second Light**, the Japanese says:

> 戦うしかなさそうだね。  
> 伶那大先生にのびのび絵を描いてもらうためにも

The speaker says that they will have to fight so Great Master Rena can keep drawing to her heart's content.

The official English turns this into:

> Looks like I'll have to fight. Rena-rdo da Vinci needs to finish her masterpiece in peace.

There is no Rena-rdo da Vinci pun in the Japanese and there is no masterpiece. The current translation reads:

> Looks like we'll have to fight.  
> Great Master Rena needs to draw to her heart's content, after all.

Another line is only:

> 横暴だ……

The official English gives:

> You fascist...

The Japanese is complaining that something is tyrannical or overbearing. Nobody is being called a fascist.

The current translation reads:

> That's tyranny...

The same problem appears in less obvious forms. A straightforward warning:

> 油断しないで。  
> そうやっておごってる時が一番危険なんだから

became:

> Don't ever let your guard down. Overconfidence is a slow and insidious killer.

The Japanese simply says not to let your guard down because you are most vulnerable when you get cocky like that. The extra phrasing was added by the localization.

Another scene says:

> 蝶のように舞い、蜂のように刺す！

This is the Japanese rendering of Muhammad Ali's famous English-language quote, **"Float like a butterfly, sting like a bee."**

The official English replaces it with:

> every rose has its thorn

The Japanese line already contains a direct rendering of a famous English-language quote. The localization still replaces it with an unrelated saying.

The current translation restores:

> Float like a butterfly, sting like a bee!

The larger changes go beyond individual jokes. The first **BLUE REFLECTION** contains missing or rewritten material concerning Hinako's injury, her reasons for continuing to fight, the Common, the Sephira, Mao's history, the deaths of Yuzu and Lime, Daath's plan and the consequences of the final battle. Several character events had motivations shortened or redirected enough to change the point of the scene.

Some rewrites also change how characters sound over time. Ako receives localization-only running jokes and labels. Quiet or uncertain reactions can become much louder dialogue. Character-specific habits are flattened when the official English replaces them with a more generic voice.

The patch restores the source instead of trying to preserve those rewrites around the edges.

### Character voices and relationships

The way each character speaks is treated as part of the text.

Honorifics such as *-san*, *-chan*, *-kun*, *-senpai* and *-sama* are retained where they appear in Japanese and carry relationship or character information.

Family and habitual forms of address are handled from context. Forms such as *Onee-chan* remain when a character genuinely uses them that way. An ordinary descriptive reference still becomes natural English such as *older sister* or *younger brother*.

Names use Japanese order, with the surname before the given name.

Character-specific speech patterns are also preserved. This includes differences in formality, recurring forms of address, individual verbal habits and cases where a character refers to herself by name instead of using an ordinary first-person pronoun.

The English still follows normal English sentence structure. Preserving a Japanese speech pattern does not mean reproducing Japanese grammar word for word.

Cultural terms are kept where replacing them would remove information from the setting or change what the characters are talking about. The same applies to meaningful Japanese wordplay. A joke may need to be adapted to work in English, but a new joke is not added to a line that was never a joke in the first place.

### Translation status

The translation is currently **beta**.

The most obvious mistranslations, omissions, localization-only additions, altered character writing and major terminology problems found so far have already been corrected. Japanese name order, honorifics and character-specific speech patterns have also been restored throughout the scripts.

Translation work is still continuing. The supported scripts will receive further in-game testing, cross-title consistency work and line-by-line polish. Some problems only become apparent when a line is seen inside the actual scene. Other lines may already be accurate but still need more natural English.

The current text should therefore be treated as a working translation rather than a finished final script.

## Quartet restoration and uncensor

**BLUE REFLECTION Quartet** does not contain the first **BLUE REFLECTION** exactly as it appeared in the 2017 PC release. Some assets and rendering behaviour were changed when the game was incorporated into the collection.

The restoration work compares the original PC release directly against Quartet. The comparison covers the relevant archives, models, textures, materials, effects and runtime behaviour. A change is restored only when it can be tied back to the original game.

The bathroom water restoration is runtime validated and is a canonical part of the normal UNCENSOR module. When UNCENSOR is selected, the patcher applies the approved checksum-gated `PACK10_03` restoration automatically.

The normal public `.unburger` also carries the three canonical restored Quartet-compatible movie files (`CNG_PC00_00.webm`, `CNG_PC01_00.webm`, `CNG_PC02_00.webm`). Movie restoration is a default-enabled child of UNCENSOR. `BUILD_RELEASE.sh` requires and validates these WebM files; they are not part of `.unburger-assets`.

The wet-clothing system is more complicated. Controlled runtime testing has reproduced the missing wet-surface and droplet component and confirmed more of the original wet rendering path. Those experimental wet changes are not part of the normal restoration module yet. The remaining `ce01_040` clothing-opacity difference has been narrowed to one main-PBB RenderDoc comparison between Original and Quartet rather than another broad static search.

In the original game, wetness affects more than the uniform. Clothing, skin and hair participate in the wet state, and switching wetness causes the game to resolve a wider character rendering state. The remaining transparency difference is therefore being traced through the native wetness path instead of forcing a texture change that only happens to look close in one scene.

Other differences discovered during comparison remain under investigation. They will only become part of the normal restoration module after they have survived runtime testing and can be reproduced without damaging unrelated scenes or assets.

## Restoring removed DLC in Quartet

Quartet removed a large part of the first game's DLC.

The removal happened at several levels. Hundreds of source assets disappeared from the collection. Costume records that survived were redirected to ordinary uniforms. Costume names were removed. The internal wardrobe data was reduced to the much smaller selection Quartet kept.

Copying the missing models back into the game therefore leaves the content inaccessible. The complete path used by the original game had to be reconstructed.

The missing assets were identified in the 2017 PC release and mapped to their Quartet equivalents. Character records and text tables were restored. The wardrobe data was expanded so the additional entries could coexist with the costumes already present in Quartet. The game-side limits and references that assumed the smaller Quartet wardrobe also had to be updated so the expanded roster could be used safely.

The resulting restore brings back **66 source-backed costumes across all 15 characters**.

The restored costumes appear as additional entries in the Dressing Room. They retain the existing Quartet outfits, display their proper names and load the correct model for each character. The same costume selection continues to work after returning to normal gameplay.

The remaining 24 deleted costume records are deliberately left unavailable. Their models were never included in the PC version of the 2017 game. They correspond to platform-specific outfits for which the PC data contains references but not the actual character assets. Exposing them would create selectable entries that fall back to the wrong model.

**Tropical Island** has also been restored. The missing map content, events and dialogue path have been reconstructed and confirmed in game.

The source assets normally come from the user's own installation of **BLUE REFLECTION** 2017. The base game is enough. Separate ownership of its costume DLC is not required because the PC base installation already contains the costume assets used by the restore.

A compatible `.unburger-assets` source bundle can be used instead of keeping the complete first game available. Such a bundle is created locally from a verified **BLUE REFLECTION** 2017 installation and contains only the source data required by the current restoration, rather than the complete game archives. If a compatible bundle is placed beside the patcher's normal `.unburger` payload, the patcher can detect and use it automatically.

The public mod release does not distribute those proprietary game assets. They must come from the user's own copy of the game, either directly from the installation or through a compatible source bundle created from it.

### Save access for restored BLUE REFLECTION DLC

For the restored **BLUE REFLECTION (2017)** DLC path, restoring the Quartet game files does not retroactively change the wardrobe/Tropical Island access state already stored inside an existing save.

When the BLUE REFLECTION source family of **DLC Restoration** is installed, the patcher handles BR1 Save Access as part of the same guided installation flow. After the game files have been prepared, it looks for existing Quartet saves and can process all current save slots found in the selected save location. The update enables access to the expanded 122-entry wardrobe roster and the restored Tropical Island event flag.

Standard native Windows and Steam/Proton save locations are detected automatically where possible. The interactive save-selection screen always keeps an **Enter / paste save folder / `.pcsave` / Wine or Proton prefix manually** option available, even when one or more save locations were detected automatically. For Heroic, a custom Wine/Proton setup or another loose prefix, paste the prefix root containing `drive_c`; a save directory or an individual `.pcsave` file can also be selected directly.

Save files are backed up before they are changed and the result is verified afterwards. Existing backup copies are not treated as live save slots.

`SAVE_ACCESS.sh` on Linux and `SAVE_ACCESS.cmd` on Windows are provided for saves created later. A save that has already been updated keeps those access flags when that save state is written to another slot. However, a completely new playthrough or newly created save starts from the game's normal default save state, so Save Access must currently be run again for that new save.

This extra step for newly created saves is a temporary limitation of the current restoration method. A future version may move restored DLC access into the game's runtime initialization so new saves receive it automatically.

The Quartet **Second Light** partition is restored by the same DLC module. The restoration includes the removed costume/content families, DLC maps and battle fields, event/dialogue/notification data, facility/story routing, Resonance Tide and Ryza-related content covered by the current workstream. Core 0.0.107 was user-runtime validated with this DLC restoration on both Linux and Windows.

Second Light uses a different access strategy from BR1: native Quartet Second Light saves do **not** require mandatory save modification. DLC access is restored through game-data/story re-gating. Optional entitlement parity handling for converted/external saves remains separate and is not a requirement for normal native Quartet saves.

## Installation

One patcher is used for all supported PC installations.

Use the launcher for your operating system (`RUN.sh` on Linux or `RUN.cmd` on Windows). Supported installations are detected automatically where possible. In the interactive installer, **Enter / paste game folder manually** is always available alongside detected installations, including when exactly one installation was detected.

On Windows, either run `RUN.cmd` normally or pass the game folder explicitly, for example `RUN.cmd --game-dir "D:\Games\BLUE REFLECTION Quartet"`. A single bare path such as `RUN.cmd "D:\Games\BLUE REFLECTION Quartet"` is also accepted as a convenience shorthand. Administrator rights are not required for detection.

If the patcher does not detect the path on its own, place all the files from the archive directly into the main folder of the selected game. The launcher switches to its own release directory before detection, so this works even when Windows starts the command script with a different current working directory.

### Supported games and modules

| Game | Available modules |
| --- | --- |
| **BLUE REFLECTION (2017)** | Translation |
| **BLUE REFLECTION: Second Light** | Translation |
| **BLUE REFLECTION Quartet** | Translation for BLUE REFLECTION, Second Light, SUN and RAY; UNCENSOR/restoration for the BLUE REFLECTION partition; DLC restoration for the BLUE REFLECTION and Second Light partitions |

Translation, UNCENSOR and DLC remain independently selectable. The restored-movie component is a default-enabled child of UNCENSOR.

### Optional DLC source bundle

DLC Restoration needs source data from the corresponding standalone games. BLUE REFLECTION content can come from an installed 2017 PC copy; Second Light content can come from the standalone Second Light installation. A compatible combined `.unburger-assets` bundle can instead carry the reduced source subsets for both families. For BLUE REFLECTION, the base PC installation is enough; separate ownership of its costume DLC is not required because the required PC costume assets are already present in that installation.

If a compatible `.unburger-assets` file is placed beside the release's normal `.unburger` payload, the patcher detects it automatically and uses the capabilities present in the bundle. Missing source-family capabilities can fall back to the corresponding installed standalone game. The current frozen logical source subsets are 1,682 BR1 members plus 2,942 Second Light members (4,624 combined logical members).

The optional source bundle is used by DLC Restoration. Translation and UNCENSOR do not require it. The three restored movie WebMs are explicitly **not** stored in `.unburger-assets`; they are carried in the normal public `.unburger`.

As part of the BLUE REFLECTION DLC installation flow, the patcher also offers BR1 Save Access so existing Quartet save slots can use the restored costumes and Tropical Island immediately. `SAVE_ACCESS.sh` on Linux and `SAVE_ACCESS.cmd` on Windows are only needed later for a newly created save or as a manual fallback when save detection is not suitable.

Before writing game files, the patcher checks the current installation and the inputs needed by the selected modules. Compatibility is determined from the game structure and the contents being changed rather than requiring one exact whole-game version.

The patcher rebuilds the required archives from the user's current files. Unrelated archive entries are preserved. Existing modifications that do not conflict with the selected operations can therefore remain in place.

Backups and transaction state are created before the final replacement. A failed operation is not treated as a successful installation, and managed changes can be rolled back through the patcher.

Large operations use a structured terminal interface that reports the current stage, overall progress, the active file or operation and long-running verification, installation or rollback work instead of leaving the terminal without feedback.

When several selected modules affect the same content, the changes are composed before the final files are written.

For Quartet the effective composition order is:

```text
BLUE REFLECTION DLC restoration, if selected
Second Light DLC restoration, if selected
Restoration / UNCENSOR
Restored movie child content
Translation
```

Translation is applied last. Restoring DLC therefore does not put the original retail English back over translated DLC text.

## French translation patch

A separate, text-only **French** patch is available for the PC games: **BLUE REFLECTION (2017)**, **BLUE REFLECTION Quartet** (first game and **Second Light** partitions) and the standalone **Second Light**. It is independent of the UNBURGER English modules and must not be installed together with the English translation on the same partition. See the [French part](#français) of this README (which comes first) or the [full bilingual documentation](Blue_Reflection_Text_Tool/french_patch_bundle/README.md).

## Current status and limitations

The translation remains beta and will continue to receive substantial revision.

Quartet DLC restoration for the first **BLUE REFLECTION** is functional. The restored costume set, costume names, character routing and Tropical Island have been confirmed in game. The Second Light DLC restoration also has user-runtime PASS on both Linux and Windows with core 0.0.107; restored costumes/content routing and Translation composition are active. Individual restored-content spot checks can continue without treating the DLC stack as a startup blocker.

The complete Quartet uncensor is still in development. Bathroom water restoration is validated and canonical. The three restored movie cutscenes are canonical public-release content. Wet-clothing transparency, camera/framing restoration candidates, UDW coverage selector restorations and towel/occluder candidates remain separate evidence-gated work.

Twenty-four deleted first-game costume records cannot be restored from the PC release because the required models were never shipped with that version.

Steam updates or file verification may replace modified game files. If that happens, run the patcher again so it can rebuild the selected modules against the new current installation.

## About the project

This is an unofficial fan project.

The public release does not contain the proprietary costume models, textures, Tropical Island files or other game assets restored from the original release. Content required from another game is supplied from the user's own copy, either directly from an installed game or from a compatible locally created `.unburger-assets` source bundle.

The project is intended to preserve the original scripts, presentation and content of the games while keeping the result usable on the current PC releases.

---

## Repository tools

This section is for contributors and local development. It is not needed to install the mod.

### Repository layout

The main project areas are:

- `Blue_Reflection_Patcher/` contains the native patcher and release tooling.
- `titles/` contains title-specific targets, module data and canonical translation databases.
- `workstreams/core/` owns the shared patcher architecture, transactions, composition and release contracts.
- `workstreams/translation/` owns translated text and translation review state.
- `workstreams/translation_tooling/` owns translation import, export and validation tooling.
- `workstreams/quartet_restoration/` owns the Quartet visual restoration work.
- `workstreams/quartet_legacy_dlc/` owns the first-game DLC restoration work for Quartet.
- `docs/` contains project-wide architecture and format documentation.
- `.local/` contains generated builds, evidence, reports, temporary workspaces and other machine-local state. It is not tracked/public source content. It also holds the developer's validated canonical wet-school source cache used to reproduce UNCENSOR releases without keeping the standalone BR1 installation present.

Each active workstream has a `VERSION` file. Workstreams that expose a machine-readable state also use `STATUS.json`.

### Translation databases

The canonical translation databases are stored under:

```text
titles/blue_reflection/translation/
titles/second_light/translation/
titles/blue_reflection_sun/translation/
titles/blue_reflection_ray/translation/
```

Translation records use stable logical IDs so the same translated content can be mapped to the appropriate target files without tying the translation to one archive build.

During normal translation work, edit only the `en` field. Fields such as `jp`, `en_original`, `en_auxiliary`, source metadata, hashes and target mappings are reference data and should not be changed by hand.

The Japanese data remains the source of truth. `en_original` is the official English for that title. `en_auxiliary` is supporting English from a mapped related release when one exists and is usable.

Do not renumber records, change logical IDs or rewrite source metadata to make an import pass. A source mismatch should be fixed at the importer or mapping layer.

### Building and testing the patcher

The patcher is a Go project.

Run the normal regression suite from its directory:

```bash
cd Blue_Reflection_Patcher
go test ./...
go vet ./...
```

Build the native patcher for the current platform with:

```bash
go build ./cmd/brpatcher
```

A Windows amd64 build can be produced from Linux with:

```bash
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o brpatcher.exe ./cmd/brpatcher
```

Do not treat a successful compile as release validation. Changes that affect archive materialization, transactions, restoration or DLC should also pass the relevant workstream tests and controlled runtime validation before being made production eligible.

### Working with modules

The public modules are kept logically separate until composition.

The main module IDs are:

```text
blue_reflection_translation
second_light_translation
quartet_restoration
quartet_legacy_dlc
```

Generated module content should remain separated until the patcher performs an explicit composition step. Translation records stay in the canonical translation databases. Restoration and DLC data stay in their own registries and contracts.

For Quartet, the final composition order is fixed:

```text
quartet_legacy_dlc
quartet_restoration
blue_reflection_translation
```

Translation must remain last when the modules overlap.

Compatibility logic should be based on the structure and capabilities actually needed by an operation. Whole-game hashes are useful diagnostics, but they are not a production requirement for installing the patch.

### Building a release

The root release builder is:

```bash
./BUILD_RELEASE.sh
```

Use the script's built-in help for the options supported by the current branch:

```bash
./BUILD_RELEASE.sh --help
```

A normal release build runs the Go regression suite, stages the verified module content, builds Linux and Windows patcher binaries and produces the public `Blue-Reflection-Unburger-Mod_<version>.zip` package together with its SHA-256 sidecar. The ZIP contains the platform launchers/binaries and the versioned `.unburger` runtime payload.

The canonical wet-school UNCENSOR donor set is **not rebuilt from an installed BLUE REFLECTION (2017) copy on every release build**. A developer imports it once with `./IMPORT_CANONICAL_UNCENSOR_SOURCE.sh --source PATH`. The importer verifies the approved retail `PACK00_02.PAK`, extracts only the proven 30 PC00-PC14 `SCL_W` donor members, and stores the reduced capability under the ignored project-local `.local/Uncensor/quartet_wet_school_canonical_source_v1/` cache. After that import, ordinary `./BUILD_RELEASE.sh` runs use only this validated local cache; the standalone BR1 installation can be absent. Passing `--canonical-source PATH` to `BUILD_RELEASE.sh` is an explicit convenience refresh/import of that cache before the build, not a normal build-time dependency.

For local testing or repeated DLC builds, `BUILD_RELEASE.sh --assets` also emits the combined `.unburger-assets` source bundle beside the normal release. It **reuses an existing verified bundle by default** instead of rebuilding it from full source games every time. A normal reusable bundle uses its matching SHA-256 sidecar plus the current encrypted-manifest/1,682 BR1 + 2,942 Second Light contract checks. If a compatible older bundle predates sidecar creation, the builder performs one full decrypt/materialize/object/member verification and only then bootstraps the missing sidecar; it does not rebuild from retail sources just to create that sidecar. The last reusable bundle path is remembered under project-local `.local/release/`. If no compatible bundle exists, the builder falls back to source rebuild. On that rebuild path only, the actual BR1 and standalone Second Light retail input files are size/SHA-256 gated against the frozen production provenance contract; remembered source paths are hints and stale ones are rejected before local-config/Steam autodetection fallback. Quartet remains structure/capability-gated rather than whole-file hash-locked. Use `--assets-bundle PATH` to select an existing bundle explicitly and `--assets-rebuild` to force a source rebuild. Source-path flags remain available only for the rebuild path.

A compatible `.unburger-assets` bundle placed beside the normal `.unburger` payload can be detected by the patcher automatically. Capabilities missing from the bundle can fall back to the corresponding user-owned standalone installation.

The release builder must fail closed if required translation content is stale or incomplete or if required source data differs from the verified clean source. Full retail archives and optional DLC source bundles must never be embedded in the public mod ZIP. The normal `.unburger` contains only the explicitly approved canonical runtime restoration payloads: the reduced 30-member wet-school source capability, the three restored WebM cutscenes, Translation content and authored runtime metadata. Optional BR1/Second Light DLC source data remains outside the normal `.unburger` and is supplied through `.unburger-assets` or standalone installations.

### Validation and local state

The patcher uses transactional writes. A prepared transaction records the current file state, the desired result, staging information and rollback data before commit.

Generated development data belongs under `.local/` or the patcher's platform state directory rather than in canonical source trees. Large extracted archives, temporary repacks and runtime evidence should not be committed to the repository.

Canonical translation databases, source code, schemas, contracts and the evidence required to justify production restoration rules must remain reproducible without machine-specific paths.

Before publishing a change, check at minimum:

```bash
cd Blue_Reflection_Patcher
go test ./...
go vet ./...
```

Then run the validation appropriate to the workstream being changed. Runtime-only findings should not be promoted to normal installation paths until they have been reproduced and recorded as production eligible.

### Distribution rules

Public releases contain the patcher, authored translation content, module rules and the metadata required to rebuild the selected result.

Do not place full game PAKs, extracted proprietary models, textures, maps, `.unburger-assets` source bundles or other source-game payloads in the public repository/release bundle.

The normal `.unburger` payload contains project-authored runtime data, restoration rules and the approved restored-movie payload. It does not contain the raw BR1/Second Light source assets used by DLC Restoration. Those source assets must come from the user's own standalone installations or a compatible locally created `.unburger-assets` bundle.
