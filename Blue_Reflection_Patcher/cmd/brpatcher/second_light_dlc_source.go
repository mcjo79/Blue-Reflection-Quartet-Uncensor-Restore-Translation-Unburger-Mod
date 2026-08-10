package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/detect"
	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/quartetdlc"
	"local/blue-reflection-patcher/internal/targets"
)

func parseQuartetDLCFamilies(raw string) ([]quartetDLCFamily, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return selectedQuartetDLCFamilies(defaultQuartetDLCSelection()), nil
	}
	seen := map[quartetDLCFamily]bool{}
	for _, token := range strings.Split(raw, ",") {
		switch strings.ToLower(strings.TrimSpace(token)) {
		case "blue_reflection", "br1", "blue-reflection":
			seen[quartetDLCBlueReflection] = true
		case "second_light", "second-light", "sl":
			seen[quartetDLCSecondLight] = true
		case "":
		default:
			return nil, fmt.Errorf("unsupported --dlc-sources value %q; use blue_reflection and/or second_light", token)
		}
	}
	result := []quartetDLCFamily{}
	for _, choice := range quartetDLCChoices {
		if seen[choice.ID] {
			result = append(result, choice.ID)
		}
	}
	if len(result) == 0 {
		return nil, fmt.Errorf("DLC restoration requires at least one source game")
	}
	return result, nil
}

func hasQuartetDLCFamily(values []quartetDLCFamily, want quartetDLCFamily) bool {
	for _, value := range values {
		if value == want {
			return true
		}
	}
	return false
}

func resolveSecondLightDLCSource(explicit string, prompt bool, in io.Reader, out io.Writer) (string, error) {
	if root := strings.Trim(strings.TrimSpace(explicit), `"`); root != "" {
		if err := quartetdlc.ValidateSecondLightSource(root); err != nil {
			return "", fmt.Errorf("invalid Second Light DLC source %s: %w", root, err)
		}
		abs, _ := filepath.Abs(root)
		return filepath.Clean(abs), nil
	}

	specs, err := targets.Load()
	if err != nil {
		return "", err
	}
	var slSpecs []model.TargetSpec
	for _, spec := range specs {
		if spec.TargetID == "second_light_original" {
			slSpecs = append(slSpecs, spec)
		}
	}
	candidates := steamGameCandidates(steamDetectionAnchors())
	found, err := detect.Detect(slSpecs, candidates)
	if err != nil {
		return "", err
	}
	roots := []string{}
	seen := map[string]bool{}
	for _, item := range found {
		if item.TargetID != "second_light_original" || quartetdlc.ValidateSecondLightSource(item.Root) != nil {
			continue
		}
		key := detectionPathKey(item.Root)
		if !seen[key] {
			seen[key] = true
			roots = append(roots, item.Root)
		}
	}
	sort.Strings(roots)
	if len(roots) == 1 {
		fmt.Fprintf(out, "%sSecond Light source:%s %s (Steam auto-detected)\n", ansiCyan+ansiBold, ansiReset, roots[0])
		return roots[0], nil
	}
	if len(roots) > 1 && !prompt {
		return "", fmt.Errorf("multiple BLUE REFLECTION: Second Light installations detected; pass --second-light-source PATH")
	}
	if len(roots) > 1 {
		fmt.Fprintln(out, "Multiple BLUE REFLECTION: Second Light source installations were detected:")
		for i, root := range roots {
			fmt.Fprintf(out, "  %d) %s\n", i+1, root)
		}
		fmt.Fprint(out, "Choose source number: ")
		reader := bufio.NewReader(in)
		line, er := reader.ReadString('\n')
		if er != nil && line == "" {
			return "", er
		}
		var index int
		if _, er := fmt.Sscanf(strings.TrimSpace(line), "%d", &index); er != nil || index < 1 || index > len(roots) {
			return "", fmt.Errorf("invalid Second Light source selection")
		}
		return roots[index-1], nil
	}
	if !prompt {
		return "", fmt.Errorf("BLUE REFLECTION: Second Light source not found; pass --second-light-source PATH or provide a compatible .unburger-assets bundle")
	}
	fmt.Fprintln(out, "BLUE REFLECTION: Second Light was not detected automatically.")
	fmt.Fprint(out, "Enter the standalone Second Light game directory (leave empty to cancel): ")
	reader := bufio.NewReader(in)
	line, er := reader.ReadString('\n')
	if er != nil && line == "" {
		return "", er
	}
	root := strings.Trim(strings.TrimSpace(line), `"`)
	if root == "" {
		return "", fmt.Errorf("Second Light DLC source selection cancelled")
	}
	if er := quartetdlc.ValidateSecondLightSource(root); er != nil {
		return "", er
	}
	abs, _ := filepath.Abs(root)
	return filepath.Clean(abs), nil
}

func secondLightSourceFromMaterializedBR1Root(root string) string {
	if strings.TrimSpace(root) == "" {
		return ""
	}
	candidate := filepath.Join(root, "SECOND_LIGHT")
	if quartetdlc.ValidateSecondLightSource(candidate) == nil {
		return candidate
	}
	return ""
}

func materializeNearbySecondLightDLCSource(releaseRoot, projectRoot, anchorPath string, progress br1rebuild.BuildProgressFunc) (root, cleanupRoot string, found bool, err error) {
	bundle, found, err := findNearbyLegacyAssetBundle(releaseRoot, projectRoot, anchorPath)
	if err != nil || !found {
		return "", "", false, err
	}
	manifest, err := br1rebuild.ReadSourceAssetManifest(bundle)
	if err != nil {
		return "", "", false, err
	}
	hasSecondLight := false
	for _, supplemental := range manifest.SupplementalSources {
		if supplemental.Capability == br1rebuild.SecondLightSourceAssetsCapability {
			hasSecondLight = true
			break
		}
	}
	if !hasSecondLight {
		return "", "", false, nil
	}
	location, err := br1rebuild.LocateSourceInstall(br1rebuild.SourceLocator{
		AssetRoot: bundle, AnchorPath: anchorPath, Progress: progress,
	})
	if err != nil {
		return "", "", false, err
	}
	candidate := secondLightSourceFromMaterializedBR1Root(location.Root)
	if candidate == "" {
		if location.CleanupRoot != "" {
			_ = os.RemoveAll(location.CleanupRoot)
		}
		return "", "", false, fmt.Errorf("combined source bundle exposes no valid Second Light source namespace")
	}
	return candidate, location.CleanupRoot, true, nil
}
