# BLUE REFLECTION UNBURGER Mod

An English translation, uncensor and content restoration project for the PC BLUE REFLECTION series.

The translation included with this mod supports every PC edition covered by the project. This includes the original PC releases of **BLUE REFLECTION** and **BLUE REFLECTION: Second Light**, together with **BLUE REFLECTION**, **Second Light**, **SUN** and **RAY** as included in **BLUE REFLECTION Quartet**.

The Quartet version of the first game also receives visual restoration work and the return of content removed from the collection, including the original PC costume DLC and Tropical Island.

The project is still in beta. Translation work continues across the series, while several parts of the Quartet restoration are still being researched and tested.

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

Standard native Windows and Steam/Proton save locations are detected automatically where possible. For Heroic, a custom Wine/Proton setup or another loose prefix, the prefix root containing `drive_c` can be selected manually. A save directory or an individual `.pcsave` file can also be selected directly when automatic detection is not suitable.

Save files are backed up before they are changed and the result is verified afterwards. Existing backup copies are not treated as live save slots.

`SAVE_ACCESS.sh` on Linux and `SAVE_ACCESS.cmd` on Windows are provided for saves created later. A save that has already been updated keeps those access flags when that save state is written to another slot. However, a completely new playthrough or newly created save starts from the game's normal default save state, so Save Access must currently be run again for that new save.

This extra step for newly created saves is a temporary limitation of the current restoration method. A future version may move restored DLC access into the game's runtime initialization so new saves receive it automatically.

The Quartet **Second Light** partition is restored by the same DLC module. The restoration includes the removed costume/content families, DLC maps and battle fields, event/dialogue/notification data, facility/story routing, Resonance Tide and Ryza-related content covered by the current workstream. Core 0.0.107 was user-runtime validated with this DLC restoration on both Linux and Windows.

Second Light uses a different access strategy from BR1: native Quartet Second Light saves do **not** require mandatory save modification. DLC access is restored through game-data/story re-gating. Optional entitlement parity handling for converted/external saves remains separate and is not a requirement for normal native Quartet saves.

## Installation

One patcher is used for all supported PC installations.

Use the executable for your operating system and point it at the game you want to patch (.sh for Linux and .cmd for Windows). Supported installations are detected automatically where possible. A game directory can also be selected manually.

If the patcher does not detect the path on its own, place all the files from the archive directly into the main folder of the selected game.

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
- `.local/` contains generated builds, evidence, reports, temporary workspaces and other machine-local state. It is not canonical source content.

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

For local testing or repeated DLC builds, `BUILD_RELEASE.sh --assets` also emits the combined `.unburger-assets` source bundle beside the normal release. It **reuses an existing verified bundle by default** instead of rebuilding it from full source games every time. A normal reusable bundle uses its matching SHA-256 sidecar plus the current encrypted-manifest/1,682 BR1 + 2,942 Second Light contract checks. If a compatible older bundle predates sidecar creation, the builder performs one full decrypt/materialize/object/member verification and only then bootstraps the missing sidecar; it does not rebuild from retail sources just to create that sidecar. The last reusable bundle path is remembered under project-local `.local/release/`. If no compatible bundle exists, the builder falls back to source rebuild. On that rebuild path only, the actual BR1 and standalone Second Light retail input files are size/SHA-256 gated against the frozen production provenance contract; remembered source paths are hints and stale ones are rejected before local-config/Steam autodetection fallback. Quartet remains structure/capability-gated rather than whole-file hash-locked. Use `--assets-bundle PATH` to select an existing bundle explicitly and `--assets-rebuild` to force a source rebuild. Source-path flags remain available only for the rebuild path.

A compatible `.unburger-assets` bundle placed beside the normal `.unburger` payload can be detected by the patcher automatically. Capabilities missing from the bundle can fall back to the corresponding user-owned standalone installation.

The release builder must fail closed if required translation content is stale or incomplete or if required source data differs from the verified clean source. Raw proprietary source-game restoration assets must never be embedded in the public mod ZIP or normal `.unburger` payload. The three canonical restored WebM cutscenes are a separate, approved public UNCENSOR payload and are not source-bundle material.

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
