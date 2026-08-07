package br1rebuild

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type GateCheck struct {
	Name   string `json:"name"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail"`
	Fatal  bool   `json:"fatal"`
}

type SurveyReport struct {
	Type          string              `json:"type"`
	FormatVersion int                 `json:"format_version"`
	Status        string              `json:"status"`
	Source        SourceLocation      `json:"source"`
	TargetRoot    string              `json:"target_root"`
	Checks        []GateCheck         `json:"checks"`
	Wardrobe      *WardrobeSurvey     `json:"wardrobe,omitempty"`
	BinaryLayout  *BinaryLayoutReport `json:"binary_layout,omitempty"`
	NoWrites      bool                `json:"no_game_writes"`
	Ready         bool                `json:"ready"`
}

type WardrobeSurvey struct {
	SourceRecords      int `json:"source_records"`
	TargetRecords      int `json:"target_records"`
	MissingRecords     int `json:"missing_records"`
	ImportableRecords  int `json:"importable_records"`
	UnavailableRecords int `json:"unavailable_records"`
	FinalRecords       int `json:"final_records"`
	StringIDs          int `json:"string_ids"`
	BaseTags           int `json:"base_tags"`
}

type SurveyOptions struct {
	SourceLocator    SourceLocator
	TargetRoot       string
	TextTool         EncryptedTextTool
	UseHantForHans   bool
	RequireFreeSpace bool
}

func SurveyInstallPair(opts SurveyOptions) (SurveyReport, error) {
	report := SurveyReport{Type: "br1_reconstruction_survey", FormatVersion: 1, TargetRoot: opts.TargetRoot, NoWrites: true}
	add := func(name string, ok bool, detail string) {
		report.Checks = append(report.Checks, GateCheck{Name: name, OK: ok, Detail: detail, Fatal: true})
	}

	source, err := LocateSourceInstall(opts.SourceLocator)
	if err != nil {
		add("BLUE REFLECTION 2017 source", false, err.Error())
		return finalizeSurvey(report), nil
	}
	report.Source = source
	add("BLUE REFLECTION 2017 source", true, source.Root+" ("+source.Origin+")")

	_, catalogLocation, catalogErr := readSourceCharacterCatalog(source.Root)
	if catalogErr != nil {
		add("2017 character catalog", false, catalogErr.Error())
	} else {
		add("2017 character catalog", true, describeSourceCatalogLocation(catalogLocation))
	}

	targetRoot, err := normalizeExistingDir(opts.TargetRoot)
	if err != nil {
		add("Quartet target", false, err.Error())
		return finalizeSurvey(report), nil
	}
	report.TargetRoot = targetRoot
	targetMarkers := []string{
		"BLUE REFLECTION Quartet.exe",
		"B1.dll",
		"Data/PACK10_02.PAK",
		"Data/PACK10_03.PAK",
		"Data/PACK11.PAK",
		"Data/PACK12.PAK",
	}
	if missing := missingFiles(targetRoot, targetMarkers); len(missing) != 0 {
		add("Quartet target", false, "missing: "+strings.Join(missing, ", "))
		return finalizeSurvey(report), nil
	}
	add("Quartet target", true, targetRoot)

	sourceFiles, targetFiles := ResolveContentFiles(source.Root, targetRoot)
	sourceCount, sourceBytes, err := MeasureWardrobeArchive(sourceFiles["pack00_02"])
	add(
		"2017 wardrobe asset inventory",
		err == nil && sourceCount == expectedWardrobeSourceFiles && sourceBytes == expectedWardrobeSourceBytes,
		fmt.Sprintf("files=%d bytes=%d expected=%d/%d%s", sourceCount, sourceBytes, expectedWardrobeSourceFiles, expectedWardrobeSourceBytes, errDetail(err)),
	)

	importCount, importBytes, err := inspectWardrobeImportDelta(sourceFiles["pack00_02"], targetFiles["pack10_02"])
	add(
		"Quartet wardrobe archive delta",
		err == nil && importCount == expectedWardrobeImports && importBytes == expectedWardrobeImportBytes,
		fmt.Sprintf("new_files=%d bytes=%d expected=%d/%d%s", importCount, importBytes, expectedWardrobeImports, expectedWardrobeImportBytes, errDetail(err)),
	)

	mapCount, mapBytes, err := inspectIslandMapDelta(sourceFiles["pack00_03"], targetFiles["pack10_03"])
	add("Tropical Island map delta", err == nil && mapCount == 3, fmt.Sprintf("new_files=%d bytes=%d%s", mapCount, mapBytes, errDetail(err)))

	eventCounts, err := inspectIslandEventSources(sourceFiles["pack01"])
	eventsOK := err == nil
	for _, locale := range []string{"event_en", "event_jp", "event_ch"} {
		if eventCounts[locale] < 470 {
			eventsOK = false
		}
	}
	add("Tropical Island event inventory", eventsOK, fmt.Sprintf("event_en=%d event_jp=%d event_ch=%d%s", eventCounts["event_en"], eventCounts["event_jp"], eventCounts["event_ch"], errDetail(err)))

	for _, item := range []struct {
		label string
		path  string
	}{
		{"PACK10_02", targetFiles["pack10_02"]},
		{"PACK10_03", targetFiles["pack10_03"]},
		{"PACK11", targetFiles["pack11"]},
		{"PACK12", targetFiles["pack12"]},
	} {
		archive, openErr := OpenA22(item.path)
		if openErr != nil {
			add(item.label+" archive", false, openErr.Error())
			continue
		}
		add(item.label+" archive", true, fmt.Sprintf("entries=%d master=%s", len(archive.Entries), archive.MasterLabel))
		archive.Close()
	}

	wardrobePlan, err := DeriveWardrobePlan(source.Root, targetRoot, targetFiles["pack12"])
	if err != nil {
		add("wardrobe reconstruction model", false, err.Error())
	} else {
		summary := &WardrobeSurvey{
			SourceRecords:      len(wardrobePlan.SourceRoster),
			TargetRecords:      len(wardrobePlan.TargetRoster),
			MissingRecords:     len(wardrobePlan.Missing),
			ImportableRecords:  len(wardrobePlan.Importable),
			UnavailableRecords: len(wardrobePlan.Unavailable),
			FinalRecords:       len(wardrobePlan.TargetRoster) + len(wardrobePlan.Importable),
			StringIDs:          len(wardrobePlan.ImportableStringIDs()),
			BaseTags:           len(wardrobePlan.ImportableBaseTags()),
		}
		report.Wardrobe = summary
		modelOK := summary.SourceRecords == 120 && summary.TargetRecords == 56 && summary.MissingRecords == 90 && summary.ImportableRecords == 66 && summary.UnavailableRecords == 24 && summary.FinalRecords == 122
		add("wardrobe reconstruction model", modelOK, fmt.Sprintf("source=%d target=%d missing=%d importable=%d unavailable=%d final=%d", summary.SourceRecords, summary.TargetRecords, summary.MissingRecords, summary.ImportableRecords, summary.UnavailableRecords, summary.FinalRecords))

		moduleBytes, readErr := os.ReadFile(targetFiles["dll"])
		if readErr != nil {
			add("B1 module layout survey", false, readErr.Error())
		} else {
			_, layout, layoutErr := RewriteBR1Module(moduleBytes, wardrobePlan)
			if layoutErr != nil {
				add("B1 module layout survey", false, layoutErr.Error())
			} else {
				report.BinaryLayout = layout
				layoutOK := layout.RosterRefs == 10 && layout.ScopedBounds == 36 && layout.ExtraBounds == 18 && layout.RosterAfter == 122
				add("B1 module layout survey", layoutOK, fmt.Sprintf("records=56->%d refs=%d/10 scoped=%d/36 field_party=%d/18; survey-only", layout.RosterAfter, layout.RosterRefs, layout.ScopedBounds, layout.ExtraBounds))
			}
		}
	}

	running, detail := gameRunning(targetRoot)
	add("Quartet is closed", !running, detail)

	if opts.RequireFreeSpace {
		need := estimatedBuildSpace(targetFiles["pack10_02"])
		free, freeErr := freeBytes(filepath.Dir(targetFiles["pack10_02"]))
		if freeErr != nil {
			add("candidate workspace capacity", false, freeErr.Error())
		} else {
			add("candidate workspace capacity", free >= need, fmt.Sprintf("free=%d estimated_need=%d", free, need))
		}
	}
	return finalizeSurvey(report), nil
}

func finalizeSurvey(report SurveyReport) SurveyReport {
	ready := true
	for _, check := range report.Checks {
		if check.Fatal && !check.OK {
			ready = false
			break
		}
	}
	report.Ready = ready
	if ready {
		report.Status = "ready_for_br1_content_build"
	} else {
		report.Status = "blocked"
	}
	return report
}

func missingFiles(root string, relative []string) []string {
	var missing []string
	for _, rel := range relative {
		if info, err := os.Stat(filepath.Join(root, filepath.FromSlash(rel))); err != nil || info.IsDir() {
			missing = append(missing, rel)
		}
	}
	return missing
}

func errDetail(err error) string {
	if err == nil {
		return ""
	}
	return "; error=" + err.Error()
}

func inspectWardrobeImportDelta(sourcePath, targetPath string) (int, int64, error) {
	sourceArchive, err := OpenA18(sourcePath)
	if err != nil {
		return 0, 0, err
	}
	defer sourceArchive.Close()
	targetArchive, err := OpenA22(targetPath)
	if err != nil {
		return 0, 0, err
	}
	defer targetArchive.Close()

	existing := map[string]bool{}
	for _, entry := range targetArchive.Entries {
		existing[strings.ToLower(entry.Name)] = true
	}
	count := 0
	var bytes int64
	for _, entry := range sourceArchive.Entries {
		if !isWardrobeAssetPath(entry.Name) {
			continue
		}
		targetName := targetCharacterPrefix + entry.Name[len(sourceCharacterPrefix):]
		if existing[strings.ToLower(targetName)] {
			continue
		}
		count++
		bytes += int64(entry.Size)
	}
	return count, bytes, nil
}

func inspectIslandMapDelta(sourcePath, targetPath string) (int, int64, error) {
	sourceArchive, err := OpenA18(sourcePath)
	if err != nil {
		return 0, 0, err
	}
	defer sourceArchive.Close()
	targetArchive, err := OpenA22(targetPath)
	if err != nil {
		return 0, 0, err
	}
	defer targetArchive.Close()

	existing := map[string]bool{}
	for _, entry := range targetArchive.Entries {
		existing[strings.ToLower(entry.Name)] = true
	}
	needle := `\field\` + islandFieldKey + `\`
	count := 0
	var bytes int64
	for _, entry := range sourceArchive.Entries {
		if !strings.Contains(strings.ToLower(entry.Name), needle) {
			continue
		}
		targetName := strings.Replace(entry.Name, `\data\x64\`, `\data\b1\x64\`, 1)
		if existing[strings.ToLower(targetName)] {
			continue
		}
		count++
		bytes += int64(entry.Size)
	}
	return count, bytes, nil
}

func islandEventFolder(folder string) bool {
	folder = strings.ToLower(folder)
	if len(folder) != 4 {
		return false
	}
	if strings.HasPrefix(folder, "yy") {
		return folder >= "yy01" && folder <= "yy04"
	}
	if strings.HasPrefix(folder, "fe") {
		return folder == "fe01" || (folder >= "fe03" && folder <= "fe14")
	}
	return false
}

func inspectIslandEventSources(sourcePath string) (map[string]int, error) {
	archive, err := OpenA18(sourcePath)
	if err != nil {
		return nil, err
	}
	defer archive.Close()
	counts := map[string]int{"event_en": 0, "event_jp": 0, "event_ch": 0}
	for _, entry := range archive.Entries {
		lower := strings.ToLower(entry.Name)
		if !strings.HasSuffix(lower, ".ebm") {
			continue
		}
		for locale := range counts {
			marker := `\` + locale + `\`
			position := strings.Index(lower, marker)
			if position < 0 {
				continue
			}
			remainder := lower[position+len(marker):]
			folder := strings.SplitN(remainder, `\`, 2)[0]
			if islandEventFolder(folder) {
				counts[locale]++
			}
		}
	}
	return counts, nil
}

func estimatedBuildSpace(pack10Path string) uint64 {
	info, err := os.Stat(pack10Path)
	if err != nil {
		return 16 << 30
	}
	return uint64(float64(info.Size()+expectedWardrobeImportBytes)*1.15) + 3<<30
}

func sortedKeys[K ~string, V any](values map[K]V) []string {
	out := make([]string, 0, len(values))
	for key := range values {
		out = append(out, string(key))
	}
	sort.Strings(out)
	return out
}
