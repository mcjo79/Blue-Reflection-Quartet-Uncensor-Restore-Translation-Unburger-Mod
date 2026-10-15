#!/usr/bin/env python3
"""General launcher for the BLUE REFLECTION project.

  python br_launcher.py                 interactive shell: type commands one after another
  python br_launcher.py COMMAND [ARGS]  run a single command and exit

Type `help` in the shell for the command list.
"""
import os
import shlex
import shutil
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
# Two layouts: the repository (tool scripts in Blue_Reflection_Text_Tool/) and the
# standalone release bundle (tool scripts next to this file).
BUNDLE = os.path.isfile(os.path.join(ROOT, "br_french_installer.py"))
TOOL = ROOT if BUNDLE else os.path.join(ROOT, "Blue_Reflection_Text_Tool")
IS_WINDOWS = os.name == "nt"


def py(script, args):
    return [sys.executable, os.path.join(TOOL, script)] + args


def bash(script, args):
    exe = shutil.which("bash")
    if not exe:
        print("ERROR: bash not found. Install Git for Windows or WSL for this step.")
        return None
    return [exe, "./" + script] + args


GUST_VERSION = "v1.58"
GUST_URL = "https://github.com/VitaSmith/gust_tools/releases/download/%s/gust_tools.zip" % GUST_VERSION
GUST_SHA256 = "49a850357b4aa4399a9fc4a1be5ed331d6456d585213792e89527daf75a183ad"
GUST_DIR = os.path.join(ROOT, ".local", "vendor", "gust_tools")


def have_gust_pak():
    if os.environ.get("GUST_PAK") and os.path.isfile(os.environ["GUST_PAK"]):
        return True
    names = ("gust_pak.exe", "gust_pak")
    return any(os.path.isfile(os.path.join(d, n)) for n in names
               for d in (GUST_DIR, TOOL, os.path.join(TOOL, "vendor")))         or any(shutil.which(n) for n in names)


def setup(args):
    """Download gust_pak (gust_tools, Windows build) into .local/vendor/gust_tools."""
    if not IS_WINDOWS:
        print("gust_tools ships Windows binaries only. On Linux, build it from")
        print("  https://github.com/VitaSmith/gust_tools")
        print("then set GUST_PAK=/path/to/gust_pak or copy it to " + GUST_DIR)
        return 1
    os.makedirs(GUST_DIR, exist_ok=True)
    zpath = os.path.join(GUST_DIR, "gust_tools.zip")
    print("Downloading %s ..." % GUST_URL)
    try:
        urllib.request.urlretrieve(GUST_URL, zpath)
    except OSError as exc:
        print("ERROR: download failed:", exc)
        return 1
    with open(zpath, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    if digest != GUST_SHA256:
        os.remove(zpath)
        print("ERROR: unexpected SHA-256 %s (expected %s); file discarded." % (digest, GUST_SHA256))
        return 1
    with zipfile.ZipFile(zpath) as z:
        z.extractall(GUST_DIR)
    os.remove(zpath)
    print("gust_tools %s installed in %s" % (GUST_VERSION, GUST_DIR))
    return 0


def french(args):
    if args and args[0] in ("apply", "revert", "status") or not args:
        if not have_gust_pak():
            print("gust_pak is required but was not found.")
            ans = input("Download it now into .local/vendor/gust_tools? [Y/n] ").strip().lower()                 if sys.stdin.isatty() else "n"
            if ans in ("", "y", "yes", "o", "oui") and setup([]) == 0:
                pass
            else:
                print("Run `setup` later, or pass --gust-pak PATH / set GUST_PAK.")
                return None
    if not args:
        return py("br_french_installer.py", [])
    return py("br_french_patch.py", args)


def extract_built_release():
    """A ZIP produced by `release` (BUILD_RELEASE.sh) is extracted next to it; newest build wins."""
    try:
        zips = [os.path.join(RELEASE_DIR, n) for n in os.listdir(RELEASE_DIR)
                if n.startswith("Blue-Reflection-Unburger-Mod_") and n.endswith(".zip")]
    except OSError:
        return
    if not zips:
        return
    zpath = max(zips, key=os.path.getmtime)
    target = zpath[:-4]
    if find_unburger_release_in(target) and os.path.getmtime(target) >= os.path.getmtime(zpath):
        return
    print("Extraction de la release construite : %s" % os.path.basename(zpath))
    shutil.rmtree(target, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(target)
    os.utime(target)


def find_unburger_release():
    """Return a folder holding an extracted UNBURGER release (RUN.cmd/RUN.sh + bin/), or None."""
    bases = [os.environ.get("UNBURGER_DIR") or "", os.path.join(ROOT, ".local", "release")]
    for base in bases:
        if not base or not os.path.isdir(base):
            continue
        for d in [base] + sorted((os.path.join(base, n) for n in os.listdir(base)), key=os.path.getmtime, reverse=True):
            hit = find_unburger_release_in(d)
            if hit:
                return hit
    return None


RELEASE_REPO = "rsc-pl/Blue-Reflection-Quartet-Uncensor-Restore-Translation-Unburger-Mod"
RELEASE_DIR = os.path.join(ROOT, ".local", "release")


def fetch_release(args):
    """Download the public UNBURGER release ZIP (latest, or a tag given as arg) and extract it."""
    api = "https://api.github.com/repos/%s/releases/%s" % (
        RELEASE_REPO, ("tags/" + args[0]) if args else "latest")
    try:
        with urllib.request.urlopen(api, timeout=60) as resp:
            rel = json.load(resp)
    except OSError as exc:
        print("ERROR: cannot query the release:", exc)
        return 1
    asset = next((a for a in rel.get("assets", []) if a["name"].endswith(".zip")), None)
    if not asset or not (asset.get("digest") or "").startswith("sha256:"):
        print("ERROR: no ZIP asset with a SHA-256 digest in release %s" % rel.get("tag_name"))
        return 1
    expected = asset["digest"].split(":", 1)[1]
    name = asset["name"][:-4]
    target = os.path.join(RELEASE_DIR, name)
    if find_unburger_release_in(target):
        print("Release %s already installed in %s" % (rel["tag_name"], target))
        return 0
    os.makedirs(RELEASE_DIR, exist_ok=True)
    zpath = os.path.join(RELEASE_DIR, asset["name"])
    print("Downloading %s (%.0f MB) ..." % (asset["name"], asset["size"] / 1e6))
    sha = hashlib.sha256()
    try:
        with urllib.request.urlopen(asset["browser_download_url"], timeout=60) as resp,                 open(zpath, "wb") as out:
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                print("\r  %3d%%" % (100 * done // asset["size"]), end="", flush=True)
    except OSError as exc:
        print("\nERROR: download failed:", exc)
        return 1
    print()
    if sha.hexdigest() != expected:
        os.remove(zpath)
        print("ERROR: SHA-256 mismatch (%s, expected %s); file discarded." % (sha.hexdigest(), expected))
        return 1
    print("SHA-256 OK. Extracting to %s ..." % target)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(target)
    os.remove(zpath)
    print("Release %s ready." % rel["tag_name"])
    return 0


def find_unburger_release_in(d):
    exe = os.path.join(d, "bin", "windows-amd64" if IS_WINDOWS else "linux-amd64",
                       "brpatcher.exe" if IS_WINDOWS else "brpatcher")
    return (d, exe) if os.path.isfile(exe) else None


# quartet_movie_restoration is a *default-enabled child* of quartet_restoration:
# requesting both plans the three restored WebM files twice and the patcher stops
# with "duplicate final artifact path: Data/B1/x64/Movie/CNG_PC00_00.webm".
# Only the parent is requested; the child follows on its own.
QUARTET_MODULES = "quartet_restoration,quartet_legacy_dlc"


def release_modules(release_dir):
    """Module ids the release declares (meta/MODULE_VERSIONS.tsv), or None if unreadable."""
    path = os.path.join(release_dir, "meta", "MODULE_VERSIONS.tsv")
    try:
        with open(path, encoding="utf-8") as fh:
            return {line.split("\t", 1)[0].strip() for line in fh if line.strip()}
    except OSError:
        return None


def quartet_modules_for(release_dir):
    """The module list to request, limited to what this release actually ships."""
    requested = [m.strip() for m in QUARTET_MODULES.split(",") if m.strip()]
    declared = release_modules(release_dir)
    if declared is None:
        return ",".join(requested), []
    return (
        ",".join(m for m in requested if m in declared),
        [m for m in requested if m not in declared],
    )


def find_games():
    """Detected game folders by key (2017, quartet, second_light...). Only `quartet` is ever patched."""
    sys.path.insert(0, TOOL)
    try:
        import br_french_installer as inst
        return inst.detect_games()
    except Exception as exc:  # noqa: BLE001
        print("Détection des jeux impossible :", exc)
        return {}
    finally:
        sys.path.remove(TOOL)


#: The patcher reports whether an installation may proceed ("Automatic prepare").
#: When it is false, its recorded baseline no longer matches the game files (Steam
#: verification, an interrupted attempt, the French patch...) and it aborts with
#: "managed target changed before update"; adopting the current files fixes it.
def yes_no(prompt):
    if not sys.stdin.isatty():
        return False
    return input(prompt).strip().lower() in ("o", "oui", "y", "yes")


def patcher_status(exe, release_dir, game_dir):
    """(status, installation_allowed) from the patcher, or (None, None) if unreadable."""
    try:
        proc = subprocess.run(
            [exe, "installation-status", "-game-dir", str(game_dir)],
            cwd=release_dir, capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    status = None
    allowed = None
    for line in proc.stdout.splitlines():
        plain = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        low = plain.lower()
        if low.startswith("status:"):
            status = plain.split(":", 1)[1].strip()
        elif low.startswith("automatic prepare:"):
            allowed = plain.split(":", 1)[1].strip().lower() == "true"
    return status, allowed


def adopt_current_baseline(exe, release_dir, game_dir, assume_yes):
    """Adopt the current game files as the patcher's new baseline (game files untouched).

    ``installation-reset-state --adopt-current`` archives the previous state and
    records what is on disk now, which is exactly what is needed after a Steam
    verification or an interrupted run.
    """
    if not assume_yes and not yes_no("  Adopter les fichiers actuels comme nouvelle base ? [o/N] "):
        return False
    rc = subprocess.call(
        [exe, "installation-reset-state", "-game-dir", str(game_dir), "--adopt-current", "--yes"],
        cwd=release_dir,
    )
    return rc == 0


def quartet_entries(games):
    """(Target, game_dir) for the Quartet partitions, in installer order."""
    sys.path.insert(0, TOOL)
    try:
        import br_french_installer as inst
    except Exception:  # noqa: BLE001
        return []
    finally:
        sys.path.remove(TOOL)
    return [
        (target, games[target.key])
        for target in inst.TARGETS
        if target.key in inst.QUARTET_KEYS and target.key in games
    ]


def revert_french(entries):
    """Restore the original archives the French patch had replaced.

    The composition order is restoration first, translation last, so an already
    installed French patch has to come off before the UNBURGER mods run.
    Returns how many targets were reverted.
    """
    sys.path.insert(0, TOOL)
    try:
        import br_french_installer as inst
    except Exception as exc:  # noqa: BLE001
        print("Revert du français impossible :", exc)
        return 0
    finally:
        sys.path.remove(TOOL)
    reverted = 0
    for target, game_dir in entries:
        if not (game_dir / target.state_dir / "state.json").is_file():
            continue
        print("Français déjà installé sur %s : restauration de l'anglais d'abord." % target.label)
        try:
            # with a human at the keyboard, ask when an archive changed outside the
            # patch (typically a Steam update); otherwise keep the current files,
            # which never destroys anything and lets the flow continue
            inst.run_revert(
                target, game_dir, on_conflict=("ask" if sys.stdin.isatty() else "adopt")
            )
            reverted += 1
        except Exception as exc:  # noqa: BLE001
            print("  Erreur au revert : %s" % exc)
            print("  Si la sauvegarde est inutilisable, l'état peut être vidé :")
            print("  menu du patch, option 3, ou `python br_launcher.py forget-french`.")
    return reverted


def run_all(args):
    """Quartet only: UNBURGER mods (older games are used as asset sources), then French on b1 + b4."""
    found = find_unburger_release()
    if not found and sys.stdin.isatty():
        ans = input("Aucune release UNBURGER locale. La télécharger depuis GitHub (~250 Mo) ? [O/n] ").strip().lower()
        if ans in ("", "o", "oui", "y", "yes") and fetch_release([]) == 0:
            found = find_unburger_release()
    if found:
        d, exe = found
        games = find_games()
        quartet = games.get("quartet")
        if quartet is None:
            print("Quartet introuvable : rien n'est patché. Lancez `french` pour saisir le dossier à la main.")
            return 1
        print("=== 1/2  Mods UNBURGER (%s) ===" % d)
        print("Quartet : %s (seul jeu modifié ; les anciens jeux ne servent que de sources en lecture)" % quartet)
        modules, skipped = quartet_modules_for(d)
        if skipped:
            print("Modules non fournis par cette release (ignorés) : %s" % ", ".join(skipped))
        print("Modules : %s (sans la traduction anglaise)" % modules)
        # restoration first, translation last: take an installed French patch off
        reverted = revert_french(quartet_entries(games))
        status, allowed = patcher_status(exe, d, quartet)
        if status:
            print("État UNBURGER : %s" % status)
        if reverted:
            # our own revert moved the archives away from the recorded baseline, so
            # the patcher must take the current files as their new truth; no need to
            # bother the user with it, nothing in the game is modified
            if adopt_current_baseline(exe, d, quartet, assume_yes=True):
                print("Base UNBURGER réenregistrée après la restauration du français.")
        elif allowed is False:
            print("L'état enregistré par le patcher ne correspond plus aux fichiers du jeu")
            print("(vérification Steam, tentative interrompue, autre outil...).")
            print("Sans remise à zéro il refuse d'installer : \"managed target changed before update\".")
            print("Cette remise à zéro ne modifie aucun fichier du jeu.")
            if adopt_current_baseline(exe, d, quartet, assume_yes=("--yes" in args or not sys.stdin.isatty())):
                print("Base UNBURGER réenregistrée depuis les fichiers actuels.")
            else:
                print("Remise à zéro ignorée : l'étape mods risque d'échouer.")
        cmd = [exe, "start", "--project-root", d, "-game-dir", str(quartet), "-modules", modules]
        sources = []
        if games.get("2017"):
            cmd += ["-legacy-source", str(games["2017"])]
            sources.append("blue_reflection")
        if games.get("second_light"):
            cmd += ["-second-light-source", str(games["second_light"])]
            sources.append("second_light")
        if sources:
            cmd += ["-dlc-sources", ",".join(sources)]
        print("Sources DLC (lecture seule) : %s" % (", ".join(sources) or "aucune détectée"))
        rc = run_cmd(cmd)
        if rc:
            print("UNBURGER a échoué ou a été bloqué (code %s)." % rc)
            print("Commande à relancer si besoin :")
            print("  " + " ".join(cmd))
            answer = input("Continuer quand même avec le français ? [o/N] ") if sys.stdin.isatty() else ""
            if answer.strip().lower() not in ("o", "oui", "y", "yes"):
                return rc
    else:
        print("Aucune release UNBURGER trouvée (.local/release ou variable UNBURGER_DIR) : "
              "étape mods ignorée. Construisez-la avec `release`, ou extrayez le ZIP public.")
    print("=== %s  Patch français Quartet (b1 + b4) ===" % ("2/2" if found else "1/1"))
    return run_cmd(ensure_gust() or py("br_french_installer.py", ["--all", "--yes"] + args))


def ensure_gust():
    """Return an int error code if gust_pak is missing and not installed, else None."""
    if have_gust_pak():
        return None
    print("gust_pak est requis mais introuvable.")
    return setup([]) or None


def package(args):
    """Build the French bundle and zip it as a GitHub release asset in dist/."""
    out = os.path.join(ROOT, "distribution", "french_patch")
    rc = subprocess.call(py("br_french_patch.py", ["build-bundle", "--out", out] + args), cwd=ROOT)
    if rc:
        return rc
    with open(os.path.join(ROOT, "config", "fr_release_version"), encoding="utf-8") as fh:
        version = fh.read().strip()
    name = "Blue-Reflection-Quartet-FR_%s" % version
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    zpath = os.path.join(ROOT, "dist", name + ".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _dirs, files in os.walk(out):
            for f in sorted(files):
                full = os.path.join(folder, f)
                arc = os.path.join(name, os.path.relpath(full, out))
                info = zipfile.ZipInfo.from_file(full, arc)
                if f.endswith(".sh"):
                    info.external_attr = 0o755 << 16
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
    with open(zpath, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    with open(zpath + ".sha256", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%s  %s\n" % (digest, os.path.basename(zpath)))
    print("Release asset: %s (%.1f MB)" % (zpath, os.path.getsize(zpath) / 1e6))
    print("SHA-256: %s" % digest)
    return 0


def forget_french(args):
    """Drop the recorded French state on the Quartet partitions (game files untouched).

    What is in the game right now becomes the new reference: the patch can no longer
    be reverted, but a re-install and the UNBURGER composition start from reality.
    ``--purge`` also deletes the stored backups.
    """
    purge = "--purge" in args
    entries = quartet_entries(find_games())
    if not entries:
        print("Quartet non détecté : lancez `french` pour saisir le dossier à la main.")
        return 1
    sys.path.insert(0, TOOL)
    try:
        import br_french_installer as inst
    except Exception as exc:  # noqa: BLE001
        print("Impossible de charger l'installeur :", exc)
        return 1
    finally:
        sys.path.remove(TOOL)
    for target, game_dir in entries:
        print("--- %s" % target.label)
        try:
            inst.run_forget(target, game_dir, purge)
        except Exception as exc:  # noqa: BLE001
            print("  Erreur : %s" % exc)
    return 0


def build_french(args):
    return py("br_french_patch.py", ["build-bundle"] + args)


COMMANDS = {
    "french": (french, "French patch. No args: interactive installer. "
                       "Else e.g. apply|revert|status|self-check --game-dir PATH"),
    "build-french": (build_french, "Build the standalone French bundle in distribution/french_patch"),
    "validate": (lambda a: ("seq", [bash(s, a) for s in (
        "04_validate_project_base.sh", "06_validate_parallel_workstreams.sh",
        "07_validate_release_hygiene.sh")]), "Run the validation scripts (needs bash)"),
    "release": (lambda a: bash("BUILD_RELEASE.sh", a), "Build the UNBURGER release ZIP [BUILD_RELEASE.sh options]"),
    "all": (run_all, "Quartet only: UNBURGER restoration+DLC (no English translation), then French on b1 + b4 [--yes]"),
    "fetch-release": (fetch_release, "Download the public UNBURGER release ZIP from GitHub into .local/release [TAG]"),
    "package": (package, "Build the release ZIP for GitHub (French patch + launcher) in dist/"),
    "setup": (setup, "Download gust_pak (needed by the French patch) into .local/vendor/gust_tools"),
    "info": (lambda a: bash("START_HERE.sh", a), "Project versions and state"),
    "forget-french": (forget_french,
                      "Forget the recorded French patch state on Quartet "
                      "(game files untouched; --purge deletes the backups)"),
}
if BUNDLE:  # developer-only steps need the repository
    for _name in ("build-french", "validate", "release", "info", "package"):
        COMMANDS.pop(_name, None)
ORDER = list(COMMANDS)
DIRECT = ("apply", "revert", "status", "self-check")  # old bundle syntax: RUN.cmd apply --game-dir ...


def help_text():
    print("\nCommands (an optional number 1-%d works instead of the name):" % len(ORDER))
    for i, name in enumerate(ORDER, 1):
        print("  %d. %-13s %s" % (i, name, COMMANDS[name][1]))
    print("  help, ?       this list")
    print("  quit, exit    leave\n")


def run_cmd(cmd):
    if cmd is None:
        return 1
    if isinstance(cmd, int):
        return cmd
    if isinstance(cmd, tuple):  # sequence, stop at first failure
        for c in cmd[1]:
            rc = run_cmd(c)
            if rc:
                return rc
        return 0
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except KeyboardInterrupt:
        print("\n(interrupted)")
        return 130
    except OSError as exc:
        print("ERROR:", exc)
        return 1


def split(line):
    parts = shlex.split(line, posix=not IS_WINDOWS)
    if IS_WINDOWS:  # non-posix mode keeps the quotes
        parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    return parts


def dispatch(parts):
    name, args = parts[0].lower(), parts[1:]
    if name in DIRECT:
        name, args = "french", parts
    if name.isdigit() and 1 <= int(name) <= len(ORDER):
        name = ORDER[int(name) - 1]
    if name not in COMMANDS:
        print("Unknown command: %s (type help)" % parts[0])
        return 2
    return run_cmd(COMMANDS[name][0](args))


def shell():
    print("BLUE REFLECTION project - interactive launcher")
    help_text()
    while True:
        try:
            line = input("br> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        try:
            parts = split(line)
        except ValueError as exc:
            print("Parse error:", exc)
            continue
        cmd = parts[0].lower()
        if cmd in ("quit", "exit", "q", "0"):
            return 0
        if cmd in ("help", "?", "h"):
            help_text()
        else:
            rc = dispatch(parts)
            if rc:
                print("(exit code %s)" % rc)


def main():
    if len(sys.argv) > 1:
        return dispatch(sys.argv[1:])
    return shell()


if __name__ == "__main__":
    sys.exit(main())
