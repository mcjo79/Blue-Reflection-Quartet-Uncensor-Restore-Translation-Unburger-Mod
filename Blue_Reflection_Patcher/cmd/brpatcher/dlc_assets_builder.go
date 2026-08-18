package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/runtimebundle"
	"local/blue-reflection-patcher/internal/workspace"
)

const defaultDLCAssetBundleName = "UNBURGER_DLC_ASSETS_v3.unburger-assets"

type dlcAssetBuildOptions struct {
	ProjectRoot     string
	ReleaseRoot     string
	QuartetRoot     string
	BR1Root         string
	BR1SteamRoot    string
	SecondLightRoot string
	OutputPath      string
	Force           bool
	Prompt          bool
}

type dlcAssetBuildReport struct {
	Type                      string `json:"type"`
	FormatVersion             int    `json:"format_version"`
	Status                    string `json:"status"`
	OutputPath                string `json:"output_path"`
	SHA256                    string `json:"sha256"`
	Bytes                     int64  `json:"bytes"`
	BR1SourceRoot             string `json:"br1_source_root"`
	SecondLightSourceRoot     string `json:"second_light_source_root"`
	QuartetReferenceRoot      string `json:"quartet_reference_root"`
	BR1LogicalMembers         int    `json:"br1_logical_members"`
	SecondLightLogicalMembers int    `json:"second_light_logical_members"`
	Encryption                string `json:"encryption"`
	Compression               string `json:"compression"`
	Reusable                  bool   `json:"reusable"`
	GameFilesModified         bool   `json:"game_files_modified"`
}

type dlcSourceArchiveHashFile struct {
	Path   string `json:"path"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type dlcSourceArchiveHashGame struct {
	ID    string                     `json:"id"`
	Files []dlcSourceArchiveHashFile `json:"files"`
}

type dlcSourceArchiveHashContract struct {
	Type          string                     `json:"type"`
	FormatVersion int                        `json:"format_version"`
	Games         []dlcSourceArchiveHashGame `json:"games"`
}

func commandCreateDLCAssets(args []string) error {
	flags := flag.NewFlagSet("create-dlc-assets", flag.ContinueOnError)
	var projectRoot, quartetRoot, br1Root, br1Steam, secondLightRoot, output string
	var force, noPrompt bool
	flags.StringVar(&projectRoot, "project-root", "", "release/project root containing the runtime contracts and clean-source anchors")
	flags.StringVar(&quartetRoot, "quartet-root", "", "BLUE REFLECTION Quartet installation used only as the Second Light minimization reference")
	flags.StringVar(&br1Root, "source-root", "", "BLUE REFLECTION (2017) installation")
	flags.StringVar(&br1Steam, "legacy-steam", "", "Steam installation/library root used to locate BLUE REFLECTION (2017)")
	flags.StringVar(&secondLightRoot, "second-light-source", "", "BLUE REFLECTION: Second Light installation")
	flags.StringVar(&output, "output", "", "output .unburger-assets path; default is beside the patcher release")
	flags.BoolVar(&force, "force", false, "replace an existing output bundle after the new bundle passes full verification")
	flags.BoolVar(&noPrompt, "no-prompt", false, "disable interactive source-path prompts")
	if err := flags.Parse(args); err != nil {
		return err
	}

	releaseRoot := strings.TrimSpace(projectRoot)
	resolvedProject, cleanup, err := runtimebundle.ResolveProjectRootTransient(projectRoot)
	if err != nil {
		return fmt.Errorf("resolve runtime bundle: %w", err)
	}
	defer cleanup()
	if strings.TrimSpace(resolvedProject) == "" {
		return fmt.Errorf("--project-root is required when create-dlc-assets is invoked directly")
	}
	projectRoot = resolvedProject

	if strings.TrimSpace(quartetRoot) == "" {
		return fmt.Errorf("--quartet-root is required when create-dlc-assets is invoked directly")
	}
	return runLocalDLCAssetBundleBuild(dlcAssetBuildOptions{
		ProjectRoot: projectRoot, ReleaseRoot: releaseRoot, QuartetRoot: quartetRoot,
		BR1Root: br1Root, BR1SteamRoot: br1Steam, SecondLightRoot: secondLightRoot,
		OutputPath: output, Force: force, Prompt: !noPrompt && stdinIsInteractive(),
	}, os.Stdin, os.Stdout)
}

func runLocalDLCAssetBundleBuild(opts dlcAssetBuildOptions, in io.Reader, out io.Writer) error {
	anchorPath := legacyAssetAnchorPath(opts.ProjectRoot)
	if info, err := os.Stat(anchorPath); err != nil || !info.Mode().IsRegular() {
		return fmt.Errorf("DLC bundle clean-source anchors are unavailable: %s", anchorPath)
	}

	outputPath, err := resolveDLCAssetOutputPath(opts.ReleaseRoot, opts.ProjectRoot, opts.OutputPath)
	if err != nil {
		return err
	}
	if existing, err := os.Stat(outputPath); err == nil && existing.Mode().IsRegular() && !opts.Force {
		compatible, reason := existingCombinedDLCAssetBundleStatus(outputPath, anchorPath)
		if opts.Prompt {
			if compatible {
				choice, chooseErr := chooseSimpleMenu("Reusable DLC source bundle already exists and is compatible", []string{
					"Keep existing verified-compatible bundle and return",
					"Rebuild and replace it after full verification",
					"Cancel",
				}, in, out)
				if chooseErr != nil {
					return chooseErr
				}
				if choice == 0 || choice == 2 {
					if choice == 0 {
						fmt.Fprintf(out, "Existing compatible DLC source bundle kept: %s\n", outputPath)
					}
					return nil
				}
				opts.Force = true
			} else {
				fmt.Fprintf(out, "%sExisting bundle is not compatible with the current combined DLC contract:%s %s\n", ansiYellow+ansiBold, ansiReset, reason)
				choice, chooseErr := chooseSimpleMenu("Replace incompatible DLC source bundle", []string{
					"Rebuild and replace it after full verification",
					"Cancel",
				}, in, out)
				if chooseErr != nil {
					return chooseErr
				}
				if choice == 1 {
					return nil
				}
				opts.Force = true
			}
		} else {
			if compatible {
				return fmt.Errorf("output already exists and is compatible: %s (use --force to rebuild)", outputPath)
			}
			return fmt.Errorf("output already exists but is not compatible (%s): %s (use --force to rebuild)", reason, outputPath)
		}
	}

	fmt.Fprintf(out, "\n%sCreate reusable encrypted DLC source bundle%s\n", ansiCyan+ansiBold, ansiReset)
	fmt.Fprintln(out, "This does not modify any game files. It creates one reusable DLC-only .unburger-assets file from your installed source games.")
	fmt.Fprintln(out, "Translation and UNCENSOR do not depend on this file.")

	br1Root, err := resolveBR1RootForLocalBundle(opts.BR1Root, opts.BR1SteamRoot, opts.Prompt, in, out)
	if err != nil {
		return err
	}
	secondLightRoot, err := resolveSecondLightDLCSource(opts.SecondLightRoot, opts.Prompt, in, out)
	if err != nil {
		return err
	}
	renderer := newBR1BuildProgressRenderer(out)
	renderer.Status("source_bundle_source_hashes", "Verifying canonical BR1 and Second Light source archives")
	if err := verifyDLCSourceArchiveHashes(opts.ProjectRoot, br1Root, secondLightRoot, renderer.Callback); err != nil {
		renderer.Finish()
		return err
	}
	renderer.Finish()
	quartetReference, cleanupReference, err := prepareQuartetBundleReference(opts.QuartetRoot)
	if err != nil {
		return err
	}
	defer cleanupReference()

	fmt.Fprintf(out, "%sBLUE REFLECTION source:%s %s\n", ansiCyan+ansiBold, ansiReset, br1Root)
	fmt.Fprintf(out, "%sSecond Light source:%s %s\n", ansiCyan+ansiBold, ansiReset, secondLightRoot)
	if filepath.Clean(quartetReference) != filepath.Clean(opts.QuartetRoot) {
		fmt.Fprintf(out, "%sQuartet reference:%s preserved pre-management baseline\n", ansiCyan+ansiBold, ansiReset)
	} else {
		fmt.Fprintf(out, "%sQuartet reference:%s current installation (read-only minimization reference)\n", ansiCyan+ansiBold, ansiReset)
	}
	fmt.Fprintf(out, "%sOutput:%s %s\n\n", ansiCyan+ansiBold, ansiReset, outputPath)

	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil {
		return fmt.Errorf("create output directory: %w", err)
	}
	workRoot, err := workspace.MkdirTemp("unburger-local-dlc-assets-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(workRoot)
	tmpBundle := filepath.Join(workRoot, defaultDLCAssetBundleName)

	renderer = newBR1BuildProgressRenderer(out)
	renderer.Status("source_bundle_build_br1", "Preparing reduced BLUE REFLECTION DLC source")
	_, err = br1rebuild.BuildCombinedSourceAssetBundleWithProgress(br1Root, secondLightRoot, quartetReference, tmpBundle, anchorPath, renderer.Callback)
	if err != nil {
		renderer.Finish()
		return fmt.Errorf("build encrypted DLC source bundle: %w", err)
	}
	renderer.Status("source_bundle_verify", "Full decrypt/materialize/member verification")
	verified, err := br1rebuild.VerifySourceAssetBundleWithProgress(tmpBundle, anchorPath, renderer.Callback)
	renderer.Finish()
	if err != nil {
		return fmt.Errorf("verify newly built DLC source bundle: %w", err)
	}
	if _, err := br1rebuild.VerifySecondLightSourceRootAgainstBundle(secondLightRoot, tmpBundle); err != nil {
		return fmt.Errorf("verify Second Light provenance against new bundle: %w", err)
	}
	br1Count, slCount, err := validateCombinedDLCAssetManifest(verified)
	if err != nil {
		return err
	}

	if err := replaceVerifiedBundle(tmpBundle, outputPath, opts.Force); err != nil {
		return err
	}
	digest, size, err := hashFileForDLCAssets(outputPath)
	if err != nil {
		return err
	}
	if err := writeDLCAssetSHA256Sidecar(outputPath, digest); err != nil {
		return fmt.Errorf("write DLC bundle SHA-256 sidecar: %w", err)
	}
	report := dlcAssetBuildReport{
		Type: "unburger_local_dlc_assets_build", FormatVersion: 1, Status: "complete",
		OutputPath: outputPath, SHA256: digest, Bytes: size, BR1SourceRoot: br1Root,
		SecondLightSourceRoot: secondLightRoot, QuartetReferenceRoot: quartetReference,
		BR1LogicalMembers: br1Count, SecondLightLogicalMembers: slCount,
		Encryption: "AES-256-GCM chunked", Compression: "zstd-19 when available; DEFLATE fallback without external dependencies",
		Reusable: true, GameFilesModified: false,
	}
	if blob, marshalErr := json.MarshalIndent(report, "", "  "); marshalErr == nil {
		reportPath := outputPath + ".build.json"
		_ = os.WriteFile(reportPath, append(blob, '\n'), 0o644)
	}
	fmt.Fprintf(out, "\n%sDLC source bundle created and fully verified.%s\n", ansiGreen+ansiBold, ansiReset)
	fmt.Fprintf(out, "Bundle: %s\nSHA-256: %s\nSize: %d bytes\n", outputPath, digest, size)
	fmt.Fprintf(out, "Logical source members: BR1=%d, Second Light=%d\n", br1Count, slCount)
	fmt.Fprintln(out, "Future DLC installs can use this bundle without keeping the source games installed.")
	fmt.Fprintln(out, "No game files were modified.")
	return nil
}

func resolveBR1RootForLocalBundle(explicit, steamRoot string, prompt bool, in io.Reader, out io.Writer) (string, error) {
	locator := br1rebuild.SourceLocator{LooseRoot: strings.TrimSpace(explicit), SteamRoot: strings.TrimSpace(steamRoot), AutoSteam: strings.TrimSpace(explicit) == "" && strings.TrimSpace(steamRoot) == ""}
	location, err := br1rebuild.LocateSourceInstall(locator)
	if err == nil {
		return location.Root, nil
	}
	if !prompt {
		return "", err
	}
	fmt.Fprintln(out, "BLUE REFLECTION (2017) was not detected automatically.")
	chosen, chooseErr := chooseLegacySourceLocation(in, out)
	if chooseErr != nil {
		return "", chooseErr
	}
	chosen.AssetRoot = ""
	location, err = br1rebuild.LocateSourceInstall(chosen)
	if err != nil {
		return "", err
	}
	return location.Root, nil
}

func resolveDLCAssetOutputPath(releaseRoot, projectRoot, explicit string) (string, error) {
	if raw := strings.Trim(strings.TrimSpace(explicit), `"`); raw != "" {
		abs, err := filepath.Abs(raw)
		if err != nil {
			return "", err
		}
		if strings.HasSuffix(strings.ToLower(abs), ".unburger-assets") {
			return filepath.Clean(abs), nil
		}
		return filepath.Join(filepath.Clean(abs), defaultDLCAssetBundleName), nil
	}
	for _, root := range []string{releaseRoot, projectRoot} {
		root = strings.TrimSpace(root)
		if root == "" {
			continue
		}
		abs, err := filepath.Abs(root)
		if err == nil {
			return filepath.Join(filepath.Clean(abs), defaultDLCAssetBundleName), nil
		}
	}
	if exe, err := os.Executable(); err == nil {
		return filepath.Join(filepath.Dir(exe), defaultDLCAssetBundleName), nil
	}
	return "", fmt.Errorf("cannot determine output directory for %s", defaultDLCAssetBundleName)
}

func prepareQuartetBundleReference(quartetRoot string) (string, func(), error) {
	quartetRoot = filepath.Clean(strings.Trim(strings.TrimSpace(quartetRoot), `"`))
	if quartetRoot == "." || quartetRoot == "" {
		return "", func() {}, fmt.Errorf("Quartet installation is required to build the reusable DLC bundle")
	}
	for _, rel := range []string{"Data/PACK00_02.PAK", "Data/PACK02_03.PAK"} {
		if info, err := os.Stat(filepath.Join(quartetRoot, filepath.FromSlash(rel))); err != nil || !info.Mode().IsRegular() {
			return "", func() {}, fmt.Errorf("Quartet minimization reference is missing %s", rel)
		}
	}

	base, err := stateRoot()
	if err != nil {
		return "", func() {}, err
	}
	stateDir := installationStateDirectory(base, "blue_reflection_quartet", quartetRoot)
	overrides, active, err := activeManagedBaselineBuildSources(stateDir, "blue_reflection_quartet", quartetRoot)
	if err != nil {
		return "", func() {}, fmt.Errorf("resolve pre-management Quartet reference: %w", err)
	}
	if !active {
		return quartetRoot, func() {}, nil
	}

	root, err := workspace.MkdirTemp("unburger-quartet-dlc-reference-")
	if err != nil {
		return "", func() {}, err
	}
	cleanup := func() { _ = os.RemoveAll(root) }
	for _, rel := range []string{"Data/PACK00_02.PAK", "Data/PACK02_03.PAK"} {
		src := filepath.Join(quartetRoot, filepath.FromSlash(rel))
		for recorded, path := range overrides {
			if strings.EqualFold(filepath.ToSlash(recorded), rel) {
				src = path
				break
			}
		}
		dst := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			cleanup()
			return "", func() {}, err
		}
		if err := linkOrCopyDLCReference(src, dst); err != nil {
			cleanup()
			return "", func() {}, err
		}
	}
	return root, cleanup, nil
}

func linkOrCopyDLCReference(src, dst string) error {
	if err := os.Link(src, dst); err == nil {
		return nil
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(dst)
		}
	}()
	buf := make([]byte, 8<<20)
	if _, err := io.CopyBuffer(out, in, buf); err != nil {
		return err
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	ok = true
	return nil
}

func validateCombinedDLCAssetManifest(manifest br1rebuild.SourceAssetManifest) (int, int, error) {
	if len(manifest.SourceMembers) != 1682 {
		return 0, 0, fmt.Errorf("new DLC source bundle contains %d BR1 logical members, expected 1682", len(manifest.SourceMembers))
	}
	slCount := 0
	for _, supplement := range manifest.SupplementalSources {
		if supplement.Capability == br1rebuild.SecondLightSourceAssetsCapability {
			if slCount != 0 {
				return 0, 0, fmt.Errorf("new DLC source bundle contains duplicate Second Light supplements")
			}
			slCount = len(supplement.SourceMembers)
		}
	}
	if slCount != 2942 {
		return 0, 0, fmt.Errorf("new DLC source bundle contains %d Second Light logical members, expected 2942", slCount)
	}
	return len(manifest.SourceMembers), slCount, nil
}

func dlcSourceArchiveHashContractPath(projectRoot string) string {
	candidates := []string{
		filepath.Join(projectRoot, "contracts", "DLC_SOURCE_ARCHIVE_HASHES_V1.json"),
		filepath.Join(projectRoot, "workstreams", "core", "contracts", "release", "DLC_SOURCE_ARCHIVE_HASHES_V1.json"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && info.Mode().IsRegular() {
			return candidate
		}
	}
	return candidates[0]
}

func verifyDLCSourceArchiveHashes(projectRoot, br1Root, secondLightRoot string, progress br1rebuild.BuildProgressFunc) error {
	contractPath := dlcSourceArchiveHashContractPath(projectRoot)
	blob, err := os.ReadFile(contractPath)
	if err != nil {
		return fmt.Errorf("DLC source archive hash contract is unavailable: %s: %w", contractPath, err)
	}
	var contract dlcSourceArchiveHashContract
	if err := json.Unmarshal(blob, &contract); err != nil {
		return fmt.Errorf("parse DLC source archive hash contract: %w", err)
	}
	if contract.Type != "unburger_dlc_source_archive_hashes" || contract.FormatVersion != 1 {
		return fmt.Errorf("unsupported DLC source archive hash contract")
	}
	roots := map[string]string{
		"blue_reflection_2017":         br1Root,
		"blue_reflection_second_light": secondLightRoot,
	}
	expectedCounts := map[string]int{"blue_reflection_2017": 7, "blue_reflection_second_light": 6}
	seen := map[string]bool{}
	for _, game := range contract.Games {
		root, ok := roots[game.ID]
		if !ok || seen[game.ID] {
			return fmt.Errorf("invalid DLC source archive hash contract game %q", game.ID)
		}
		seen[game.ID] = true
		if len(game.Files) != expectedCounts[game.ID] {
			return fmt.Errorf("DLC source archive hash contract for %s has %d files, expected %d", game.ID, len(game.Files), expectedCounts[game.ID])
		}
		for _, row := range game.Files {
			if row.Size <= 0 || len(strings.TrimSpace(row.SHA256)) != 64 || strings.TrimSpace(row.Path) == "" {
				return fmt.Errorf("invalid DLC source archive hash row for %s", game.ID)
			}
			path := filepath.Join(root, filepath.FromSlash(row.Path))
			info, err := os.Stat(path)
			if err != nil || !info.Mode().IsRegular() {
				return fmt.Errorf("canonical %s source file missing: %s", game.ID, path)
			}
			if info.Size() != row.Size {
				return fmt.Errorf("canonical %s source size drift for %s: got %d, expected %d", game.ID, row.Path, info.Size(), row.Size)
			}
			if progress != nil {
				progress(br1rebuild.BuildProgress{Phase: "source_bundle_source_hashes", CurrentFile: game.ID + "/" + filepath.ToSlash(row.Path), CurrentDone: 0, CurrentTotal: row.Size})
			}
			got, err := hashDLCSourceFile(path, row.Size, func(done int64) {
				if progress != nil {
					progress(br1rebuild.BuildProgress{Phase: "source_bundle_source_hashes", CurrentFile: game.ID + "/" + filepath.ToSlash(row.Path), CurrentDone: done, CurrentTotal: row.Size})
				}
			})
			if err != nil {
				return err
			}
			if !strings.EqualFold(got, strings.TrimSpace(row.SHA256)) {
				return fmt.Errorf("canonical %s source SHA-256 drift for %s: got %s, expected %s", game.ID, row.Path, got, strings.ToLower(strings.TrimSpace(row.SHA256)))
			}
		}
	}
	for id := range roots {
		if !seen[id] {
			return fmt.Errorf("DLC source archive hash contract is missing %s", id)
		}
	}
	return nil
}

func hashDLCSourceFile(path string, expectedSize int64, report func(done int64)) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	buf := make([]byte, 8<<20)
	var done int64
	for {
		n, readErr := f.Read(buf)
		if n > 0 {
			_, _ = h.Write(buf[:n])
			done += int64(n)
			if report != nil {
				report(done)
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return "", readErr
		}
	}
	if done != expectedSize {
		return "", fmt.Errorf("source file changed while hashing: %s: got %d bytes, expected %d", path, done, expectedSize)
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func existingCombinedDLCAssetBundleStatus(path, anchorPath string) (bool, string) {
	resolved, ok, err := br1rebuild.FindCompatibleSourceAssetBundle(path, anchorPath)
	if err != nil {
		return false, err.Error()
	}
	if !ok || strings.TrimSpace(resolved) == "" {
		return false, "encrypted manifest / BR1 clean-anchor binding is invalid or unsupported"
	}
	manifest, err := br1rebuild.ReadSourceAssetManifest(resolved)
	if err != nil {
		return false, err.Error()
	}
	if _, _, err := validateCombinedDLCAssetManifest(manifest); err != nil {
		return false, err.Error()
	}
	return true, "compatible"
}

func writeDLCAssetSHA256Sidecar(bundlePath, digest string) error {
	digest = strings.ToLower(strings.TrimSpace(digest))
	if len(digest) != 64 {
		return fmt.Errorf("invalid bundle SHA-256 digest")
	}
	sidecar := bundlePath + ".sha256"
	tmp := sidecar + ".tmp"
	_ = os.Remove(tmp)
	content := []byte(fmt.Sprintf("%s  %s\n", digest, filepath.Base(bundlePath)))
	if err := os.WriteFile(tmp, content, 0o644); err != nil {
		return err
	}
	if err := os.Rename(tmp, sidecar); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return nil
}

func replaceVerifiedBundle(tmpPath, outputPath string, force bool) error {
	if info, err := os.Stat(outputPath); err == nil && info.Mode().IsRegular() {
		if !force {
			return fmt.Errorf("output already exists: %s", outputPath)
		}
		backup := outputPath + ".replace-backup"
		_ = os.Remove(backup)
		if err := os.Rename(outputPath, backup); err != nil {
			return fmt.Errorf("preserve existing bundle before replacement: %w", err)
		}
		if err := moveOrCopyDLCBundle(tmpPath, outputPath); err != nil {
			_ = os.Rename(backup, outputPath)
			return err
		}
		_ = os.Remove(backup)
		return nil
	}
	return moveOrCopyDLCBundle(tmpPath, outputPath)
}

func moveOrCopyDLCBundle(src, dst string) error {
	if err := os.Rename(src, dst); err == nil {
		return nil
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	tmp := dst + ".tmp"
	_ = os.Remove(tmp)
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(tmp)
		}
	}()
	if _, err := io.CopyBuffer(out, in, make([]byte, 8<<20)); err != nil {
		return err
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, dst); err != nil {
		return err
	}
	ok = true
	return nil
}

func hashFileForDLCAssets(path string) (string, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return "", 0, err
	}
	h := sha256.New()
	if _, err := io.CopyBuffer(h, f, make([]byte, 8<<20)); err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(h.Sum(nil)), info.Size(), nil
}

func chooseCreateDLCAssetsFromStartup(detection model.Detection, projectRoot, releaseRoot, br1Root, br1Steam, secondLightRoot string, in io.Reader, out io.Writer) error {
	return runLocalDLCAssetBundleBuild(dlcAssetBuildOptions{
		ProjectRoot: projectRoot, ReleaseRoot: releaseRoot, QuartetRoot: detection.Root,
		BR1Root: br1Root, BR1SteamRoot: br1Steam, SecondLightRoot: secondLightRoot,
		Prompt: true,
	}, in, out)
}
