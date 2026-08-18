package br1rebuild

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/workspace"
)

const SecondLightSourceAssetsCapability = "second_light_dlc_source_subset_v1"

var secondLightSourceFieldFamilies = map[string]bool{
	"st110_00": true, "st120_00": true, "st120_01": true, "st120_02": true,
	"bt300": true, "bt305": true, "bt400": true, "bt410": true, "bt420": true,
}

var secondLightSourceEventFamilies = map[string]bool{
	"xf01": true, "xf02": true, "xf03": true, "xf04": true, "xx00": true,
	"dm01": true, "dm02": true, "dm03": true, "dm04": true, "dm05": true,
	"dm08": true, "dm09": true, "dm10": true, "dm11": true, "sd00": true,
	"xs04": true, "xs07": true,
}

var secondLightRequiredSourceDataMembers = map[string]bool{
	strings.ToLower(`\saves\chara\charabase.xml`):      true,
	strings.ToLower(`\saves\costume\costume_body.xml`): true,
	strings.ToLower(`\saves\party\party_skill.xml`):    true,
}

func BuildCombinedSourceAssetBundle(br1Root, secondLightRoot, quartetRoot, outputPath, anchorPath string) (SourceAssetManifest, error) {
	return BuildCombinedSourceAssetBundleWithProgress(br1Root, secondLightRoot, quartetRoot, outputPath, anchorPath, nil)
}

func BuildCombinedSourceAssetBundleWithProgress(br1Root, secondLightRoot, quartetRoot, outputPath, anchorPath string, progress BuildProgressFunc) (SourceAssetManifest, error) {
	stage, err := workspace.MkdirTemp("unburger-dlc-assets-")
	if err != nil {
		return SourceAssetManifest{}, err
	}
	defer os.RemoveAll(stage)
	if progress != nil {
		progress(BuildProgress{Phase: "source_bundle_build_br1", CurrentFile: "BLUE REFLECTION (2017) reduced DLC source"})
	}
	manifest, err := buildBR1SourceAssetStage(br1Root, stage, anchorPath)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	if progress != nil {
		progress(BuildProgress{Phase: "source_bundle_build_sl", CurrentFile: "BLUE REFLECTION: Second Light reduced DLC source"})
	}
	supplement, err := buildSecondLightSourceAssetStage(secondLightRoot, quartetRoot, stage)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	manifest.SupplementalSources = []SupplementalSourceAssetManifest{supplement}
	manifest.ImageFiles, err = inventoryImageFiles(stage)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	if err := validateSourceAssetManifest(manifest); err != nil {
		return SourceAssetManifest{}, err
	}
	if err := packageSourceAssetImageV3WithProgress(stage, outputPath, manifest, progress); err != nil {
		return SourceAssetManifest{}, err
	}
	return manifest, nil
}

func validateSecondLightBundleSource(root string) error {
	for _, rel := range []string{
		"Data/PACK00_02.PAK", "Data/PACK00_03.PAK", "Data/PACK01.PAK", "Data/PACK02.PAK",
		"Data/x64/Sound/Le0000_BGM.ktsl2asbin", "Data/x64/Sound/Le0000_BGM.ktsl2stbin",
	} {
		if info, err := os.Stat(filepath.Join(root, filepath.FromSlash(rel))); err != nil || !info.Mode().IsRegular() {
			return fmt.Errorf("Second Light source missing %s", rel)
		}
	}
	return nil
}

func buildSecondLightSourceAssetStage(sourceRoot, quartetRoot, stage string) (SupplementalSourceAssetManifest, error) {
	if err := validateSecondLightBundleSource(sourceRoot); err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	if strings.TrimSpace(quartetRoot) == "" {
		return SupplementalSourceAssetManifest{}, fmt.Errorf("Quartet root is required to minimize the Second Light source subset")
	}
	for _, rel := range []string{"Data/PACK00_02.PAK", "Data/PACK02_03.PAK"} {
		if info, err := os.Stat(filepath.Join(quartetRoot, filepath.FromSlash(rel))); err != nil || !info.Mode().IsRegular() {
			return SupplementalSourceAssetManifest{}, fmt.Errorf("Quartet minimization target missing %s", rel)
		}
	}
	root := filepath.Join(stage, "source", "SECOND_LIGHT")
	dataRoot := filepath.Join(root, "Data")
	if err := os.MkdirAll(filepath.Join(dataRoot, "x64", "Sound"), 0o755); err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	members := []SourceAssetMember{}

	addReduced := func(sourceRel, group string, keep func(string) bool) ([]ArchiveEntry, error) {
		src := filepath.Join(sourceRoot, filepath.FromSlash(sourceRel))
		dst := filepath.Join(root, filepath.FromSlash(sourceRel))
		selected, err := WriteReducedA22SourceImage(src, dst, keep)
		if err != nil {
			return nil, err
		}
		p, err := OpenA22(src)
		if err != nil {
			return nil, err
		}
		defer p.Close()
		for _, chosen := range selected {
			e, ok := p.Find(chosen.Name)
			if !ok {
				return nil, fmt.Errorf("selected Second Light source member disappeared: %s", chosen.Name)
			}
			digest, err := p.PlainDigest(e)
			if err != nil {
				return nil, err
			}
			members = append(members, SourceAssetMember{Group: group, ArchivePath: filepath.ToSlash(sourceRel), MemberPath: e.Name, Size: int64(e.Size), SHA256: digest})
		}
		return selected, nil
	}

	// Costume/model payload: select missing members, not merely missing folders.
	// A modified Quartet installation may already contain only part of a source
	// costume folder. Folder-level filtering would then drop the remaining files
	// and make the reusable source bundle incomplete.
	targetModels, err := OpenA22(filepath.Join(quartetRoot, "Data", "PACK00_02.PAK"))
	if err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	targetModelMembers := map[string]bool{}
	for _, e := range targetModels.Entries {
		targetModelMembers[strings.ToLower(e.Name)] = true
	}
	targetModels.Close()
	missingFolders := map[string]bool{}
	modelEntries, err := addReduced("Data/PACK00_02.PAK", "second_light_costume_payload", func(name string) bool {
		low := strings.ToLower(name)
		const prefix = `\data\x64\character\`
		if !strings.HasPrefix(low, prefix) {
			return false
		}
		rel := name[len(prefix):]
		folder := strings.ToLower(strings.SplitN(rel, `\`, 2)[0])
		if folder == "" {
			return false
		}
		targetName := strings.ToLower(`\data\b4\x64\character\` + rel)
		if targetModelMembers[targetName] {
			return false
		}
		missingFolders[folder] = true
		return true
	})
	if err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	if len(missingFolders) != 132 {
		return SupplementalSourceAssetManifest{}, fmt.Errorf("Second Light missing model folder count=%d, expected 132", len(missingFolders))
	}
	if len(modelEntries) == 0 {
		return SupplementalSourceAssetManifest{}, fmt.Errorf("Second Light reduced model source is empty")
	}

	seenField := map[string]bool{}
	_, err = addReduced("Data/PACK00_03.PAK", "second_light_field_payload", func(name string) bool {
		low := strings.ToLower(name)
		const prefix = `\data\x64\field\`
		if !strings.HasPrefix(low, prefix) {
			return false
		}
		folder := strings.ToLower(strings.SplitN(name[len(prefix):], `\`, 2)[0])
		if secondLightSourceFieldFamilies[folder] {
			seenField[folder] = true
			return true
		}
		return false
	})
	if err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	for folder := range secondLightSourceFieldFamilies {
		if !seenField[folder] {
			return SupplementalSourceAssetManifest{}, fmt.Errorf("Second Light source field family missing: %s", folder)
		}
	}

	// Dialogue source: keep only real standalone members in the 17 proven DLC
	// event families. The standalone archive is rooted at \event\event_*;
	// not every family is populated in every locale, so absence of a particular
	// locale/family pair is not an error. The composer later intersects these
	// members with the actual Quartet b4 targets.
	eventEntries, err := addReduced("Data/PACK01.PAK", "second_light_event_payload", func(name string) bool {
		low := strings.ToLower(name)
		if !strings.HasSuffix(low, ".ebm") {
			return false
		}
		parts := strings.Split(strings.TrimPrefix(low, `\`), `\`)
		if len(parts) < 4 || parts[0] != "event" {
			return false
		}
		lang := parts[1]
		if lang != "event_en" && lang != "event_jp" && lang != "event_sc" && lang != "event_tc" {
			return false
		}
		return secondLightSourceEventFamilies[parts[2]]
	})
	if err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	if len(eventEntries) == 0 {
		return SupplementalSourceAssetManifest{}, fmt.Errorf("Second Light reduced event source is empty")
	}

	// Table source: preserve the three structural sources needed for routing and
	// Resonance restoration, plus only source locale tables that actually have a
	// Quartet b4 counterpart. Quartet contains b4-only text tables, so requiring
	// a standalone counterpart for every target table would reject a valid source.
	targetData, err := OpenA22(filepath.Join(quartetRoot, "Data", "PACK02_03.PAK"))
	if err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	targetTextKeys := map[string]bool{}
	for _, e := range targetData.Entries {
		low := strings.ToLower(e.Name)
		if !strings.HasSuffix(low, ".xml") || !strings.Contains(low, `\b4\text_`) {
			continue
		}
		base := e.Name[strings.LastIndex(e.Name, `\`)+1:]
		parts := strings.Split(strings.TrimPrefix(low, `\`), `\`)
		for _, part := range parts {
			if strings.HasPrefix(part, "text_") {
				targetTextKeys[strings.ToLower(`\saves\`+part+`\`+base)] = true
				break
			}
		}
	}
	targetData.Close()
	seenRequiredData := map[string]bool{}
	_, err = addReduced("Data/PACK02.PAK", "second_light_table_source", func(name string) bool {
		key := strings.ToLower(name)
		if secondLightRequiredSourceDataMembers[key] {
			seenRequiredData[key] = true
			return true
		}
		return targetTextKeys[key]
	})
	if err != nil {
		return SupplementalSourceAssetManifest{}, err
	}
	for key := range secondLightRequiredSourceDataMembers {
		if !seenRequiredData[key] {
			return SupplementalSourceAssetManifest{}, fmt.Errorf("Second Light required source table missing: %s", key)
		}
	}

	for _, name := range []string{"Le0000_BGM.ktsl2asbin", "Le0000_BGM.ktsl2stbin"} {
		rel := filepath.ToSlash(filepath.Join("Data", "x64", "Sound", name))
		src := filepath.Join(sourceRoot, filepath.FromSlash(rel))
		dst := filepath.Join(root, filepath.FromSlash(rel))
		if err := copyFileExact(src, dst); err != nil {
			return SupplementalSourceAssetManifest{}, err
		}
		digest, size, err := hashPath(src)
		if err != nil {
			return SupplementalSourceAssetManifest{}, err
		}
		members = append(members, SourceAssetMember{Group: "second_light_audio_source", ArchivePath: rel, MemberPath: "whole_file", Size: size, SHA256: digest})
	}

	sort.Slice(members, func(i, j int) bool { return sourceMemberKey(members[i]) < sourceMemberKey(members[j]) })
	supplement := SupplementalSourceAssetManifest{Capability: SecondLightSourceAssetsCapability, Root: "SECOND_LIGHT", SourceMembers: members}
	supplement.SourceFingerprint = sourceAssetFingerprint(members)
	if len(members) == 0 {
		return SupplementalSourceAssetManifest{}, fmt.Errorf("Second Light supplemental source is empty")
	}
	return supplement, nil
}

// VerifySecondLightSourceRootAgainstBundle confirms that a standalone Second
// Light installation still contains the exact logical source members preserved
// in a previously verified combined .unburger-assets bundle.  It intentionally
// does not depend on the Quartet minimization target, so it can be used as a
// read-only provenance check before capturing whole-retail-file hashes.
func VerifySecondLightSourceRootAgainstBundle(sourceRoot, bundlePath string) (string, error) {
	if err := validateSecondLightBundleSource(sourceRoot); err != nil {
		return "", err
	}
	manifest, err := ReadSourceAssetManifest(bundlePath)
	if err != nil {
		return "", err
	}
	if err := validateSourceAssetManifest(manifest); err != nil {
		return "", err
	}
	var supplement *SupplementalSourceAssetManifest
	for i := range manifest.SupplementalSources {
		if manifest.SupplementalSources[i].Capability == SecondLightSourceAssetsCapability {
			supplement = &manifest.SupplementalSources[i]
			break
		}
	}
	if supplement == nil {
		return "", fmt.Errorf("source assets bundle has no %s supplement", SecondLightSourceAssetsCapability)
	}
	if len(supplement.SourceMembers) != 2942 {
		return "", fmt.Errorf("Second Light source supplement contains %d members, expected 2942", len(supplement.SourceMembers))
	}
	var currentPath string
	var current *ArchiveReader
	closeCurrent := func() {
		if current != nil {
			_ = current.Close()
			current = nil
			currentPath = ""
		}
	}
	defer closeCurrent()
	for _, item := range supplement.SourceMembers {
		path := filepath.Join(sourceRoot, filepath.FromSlash(item.ArchivePath))
		if item.MemberPath == "whole_file" {
			closeCurrent()
			digest, size, err := hashPath(path)
			if err != nil || size != item.Size || !strings.EqualFold(digest, item.SHA256) {
				return "", fmt.Errorf("Second Light whole-file source mismatch: %s", item.ArchivePath)
			}
			continue
		}
		if current == nil || !strings.EqualFold(currentPath, path) {
			closeCurrent()
			p, err := OpenA22(path)
			if err != nil {
				return "", err
			}
			current, currentPath = p, path
		}
		e, ok := current.Find(item.MemberPath)
		if !ok {
			return "", fmt.Errorf("Second Light source member missing: %s#%s", item.ArchivePath, item.MemberPath)
		}
		digest, err := current.PlainDigest(e)
		if err != nil || int64(e.Size) != item.Size || !strings.EqualFold(digest, item.SHA256) {
			return "", fmt.Errorf("Second Light source member mismatch: %s#%s", item.ArchivePath, item.MemberPath)
		}
	}
	return supplement.SourceFingerprint, nil
}

func copyFileExact(src, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
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
	if _, err := out.ReadFrom(in); err != nil {
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

func validateSupplementalSourceAssets(root string, supplements []SupplementalSourceAssetManifest, progress BuildProgressFunc) error {
	for _, supplement := range supplements {
		if supplement.Capability != SecondLightSourceAssetsCapability {
			return fmt.Errorf("unsupported supplemental source capability %s", supplement.Capability)
		}
		base := filepath.Join(root, filepath.FromSlash(supplement.Root))
		var currentPath string
		var current *ArchiveReader
		closeCurrent := func() {
			if current != nil {
				_ = current.Close()
				current = nil
				currentPath = ""
			}
		}
		defer closeCurrent()
		var total, done int64
		for _, item := range supplement.SourceMembers {
			total += item.Size
		}
		for _, item := range supplement.SourceMembers {
			label := supplement.Capability + ":" + item.ArchivePath + "#" + item.MemberPath
			if progress != nil {
				progress(BuildProgress{Phase: "source_bundle_verify", CurrentFile: label, OverallDone: done, OverallTotal: total})
			}
			path := filepath.Join(base, filepath.FromSlash(item.ArchivePath))
			if item.MemberPath == "whole_file" {
				closeCurrent()
				digest, size, err := hashPath(path)
				if err != nil || size != item.Size || !strings.EqualFold(digest, item.SHA256) {
					return fmt.Errorf("supplemental source file mismatch: %s", item.ArchivePath)
				}
			} else {
				if current == nil || !strings.EqualFold(currentPath, path) {
					closeCurrent()
					p, err := OpenA22(path)
					if err != nil {
						return err
					}
					current, currentPath = p, path
				}
				e, ok := current.Find(item.MemberPath)
				if !ok {
					return fmt.Errorf("supplemental source member missing: %s#%s", item.ArchivePath, item.MemberPath)
				}
				digest, err := current.plainDigestWithProgress(e, func(cur, memberTotal int64) {
					if progress != nil {
						progress(BuildProgress{Phase: "source_bundle_verify", CurrentFile: label, CurrentDone: cur, CurrentTotal: memberTotal, OverallDone: min64(done+cur, total), OverallTotal: total})
					}
				})
				if err != nil || int64(e.Size) != item.Size || !strings.EqualFold(digest, item.SHA256) {
					return fmt.Errorf("supplemental source member mismatch: %s#%s", item.ArchivePath, item.MemberPath)
				}
			}
			done += item.Size
		}
		closeCurrent()
	}
	return nil
}
