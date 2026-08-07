package br1rebuild

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type TranslationLayerFile struct {
	ArchiveRelativePath string `json:"archive_relative_path"`
	InternalPath        string `json:"internal_path"`
	TemplatePath        string `json:"template_path"`
	TemplateSHA256      string `json:"template_sha256"`
	OutputPath          string `json:"output_path"`
	OutputSHA256        string `json:"output_sha256"`
	OutputBytes         int64  `json:"output_bytes"`
	Changed             bool   `json:"changed"`
}

type translationLayerTarget struct {
	Files []TranslationLayerFile `json:"files"`
}

type translationLayerReport struct {
	Status                    string                            `json:"status"`
	TranslationVersion        string                            `json:"translation_version"`
	TranslationToolingVersion string                            `json:"translation_tooling_version"`
	Targets                   map[string]translationLayerTarget `json:"targets"`
}

type TranslationLayerAudit struct {
	TranslationVersion        string            `json:"translation_version"`
	TranslationToolingVersion string            `json:"translation_tooling_version"`
	ChangedMembers            int               `json:"changed_members"`
	StructuredMerges          int               `json:"structured_merges"`
	EncryptedAggregates       int               `json:"encrypted_aggregates"`
	Archives                  map[string]int    `json:"archives"`
	OutputSHA256              map[string]string `json:"output_sha256"`
}

func projectFile(root, relative string) (string, error) {
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	candidate := relative
	if !filepath.IsAbs(candidate) {
		candidate = filepath.Join(rootAbs, filepath.FromSlash(relative))
	}
	candidate, err = filepath.Abs(candidate)
	if err != nil {
		return "", err
	}
	rel, err := filepath.Rel(rootAbs, candidate)
	if err != nil {
		return "", err
	}
	if rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("path leaves project root: %s", relative)
	}
	return candidate, nil
}

func readVersionFile(path string) (string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	value := strings.TrimSpace(string(b))
	if value == "" {
		return "", fmt.Errorf("empty version file: %s", path)
	}
	return value, nil
}

func loadTranslationLayer(projectRoot, reportPath string) (translationLayerReport, []TranslationLayerFile, error) {
	if strings.TrimSpace(reportPath) == "" {
		reportPath = filepath.Join(projectRoot, ".local", "reports", "translation", "BR_TRANSLATION_LOOSE_BUILD_REPORT.json")
	}
	resolved, err := projectFile(projectRoot, reportPath)
	if err != nil {
		return translationLayerReport{}, nil, err
	}
	data, err := os.ReadFile(resolved)
	if err != nil {
		return translationLayerReport{}, nil, err
	}
	var report translationLayerReport
	if err := json.Unmarshal(data, &report); err != nil {
		return translationLayerReport{}, nil, fmt.Errorf("decode translation build report: %w", err)
	}
	if report.Status != "ok" {
		return report, nil, fmt.Errorf("translation build report status is %q", report.Status)
	}
	currentTranslation, err := readVersionFile(filepath.Join(projectRoot, "workstreams", "translation", "VERSION"))
	if err != nil {
		return report, nil, err
	}
	currentTooling, err := readVersionFile(filepath.Join(projectRoot, "workstreams", "translation_tooling", "VERSION"))
	if err != nil {
		return report, nil, err
	}
	if report.TranslationVersion != currentTranslation || report.TranslationToolingVersion != currentTooling {
		return report, nil, fmt.Errorf("translation build is stale: report=%s/%s project=%s/%s", report.TranslationVersion, report.TranslationToolingVersion, currentTranslation, currentTooling)
	}
	quartetTargets := []string{"blue_reflection_quartet", "blue_reflection_ray_quartet", "blue_reflection_sun_quartet", "second_light_quartet"}
	changed := make([]TranslationLayerFile, 0)
	foundTarget := false
	for _, targetID := range quartetTargets {
		target, ok := report.Targets[targetID]
		if !ok {
			continue
		}
		foundTarget = true
		for _, file := range target.Files {
			if !file.Changed {
				continue
			}
			if file.ArchiveRelativePath == "" || file.InternalPath == "" || file.OutputPath == "" {
				return report, nil, fmt.Errorf("translation changed-file declaration is incomplete for %s", file.InternalPath)
			}
			checks := []struct {
				path string
				hash string
				size int64
				name string
			}{
				{file.OutputPath, file.OutputSHA256, file.OutputBytes, "output"},
			}
			if structuredStringTable(file.InternalPath) {
				if file.TemplatePath == "" || file.TemplateSHA256 == "" {
					return report, nil, fmt.Errorf("structured translation declaration has no template for %s", file.InternalPath)
				}
				checks = append(checks, struct {
					path string
					hash string
					size int64
					name string
				}{file.TemplatePath, file.TemplateSHA256, -1, "template"})
			}
			for _, item := range checks {
				path, err := projectFile(projectRoot, item.path)
				if err != nil {
					return report, nil, err
				}
				hash, size, err := hashPath(path)
				if err != nil {
					return report, nil, fmt.Errorf("translation %s missing for %s: %w", item.name, file.InternalPath, err)
				}
				if !strings.EqualFold(hash, item.hash) || (item.size >= 0 && size != item.size) {
					return report, nil, fmt.Errorf("translation %s fingerprint mismatch for %s", item.name, file.InternalPath)
				}
			}
			changed = append(changed, file)
		}
	}
	if !foundTarget {
		return report, nil, fmt.Errorf("translation build report has no Quartet targets")
	}
	sort.Slice(changed, func(i, j int) bool {
		if changed[i].ArchiveRelativePath != changed[j].ArchiveRelativePath {
			return changed[i].ArchiveRelativePath < changed[j].ArchiveRelativePath
		}
		return changed[i].InternalPath < changed[j].InternalPath
	})
	return report, changed, nil
}

func archiveMemberName(path string) string {
	path = strings.TrimSpace(strings.ReplaceAll(path, "/", `\`))
	if !strings.HasPrefix(path, `\`) {
		path = `\` + path
	}
	return path
}

func structuredStringTable(path string) bool {
	base := strings.ToLower(filepath.Base(strings.ReplaceAll(path, `\`, "/")))
	return base == "strcombineall.xml" || base == "str_costume.xml"
}

type stringTableLine struct {
	id   string
	line []byte
}

func splitTextLines(blob []byte) ([][]byte, []byte) {
	sep := []byte("\r\n")
	if !bytes.Contains(blob, sep) {
		sep = []byte("\n")
	}
	return bytes.Split(blob, sep), sep
}

func stringID(line []byte) string {
	match := stringNoRE.FindSubmatch(line)
	if match == nil {
		return ""
	}
	return string(match[1])
}

func mergeTranslatedStringRows(base, template, translated []byte) ([]byte, int, error) {
	baseLines, sep := splitTextLines(base)
	templateLines, _ := splitTextLines(template)
	translatedLines, _ := splitTextLines(translated)
	templateByID := map[string][]byte{}
	for _, line := range templateLines {
		if id := stringID(line); id != "" {
			if _, exists := templateByID[id]; exists {
				return nil, 0, fmt.Errorf("duplicate String_No %s in translation template", id)
			}
			templateByID[id] = line
		}
	}
	changedRows := map[string][]byte{}
	for _, line := range translatedLines {
		id := stringID(line)
		if id == "" {
			continue
		}
		baseline, exists := templateByID[id]
		if !exists || !bytes.Equal(baseline, line) {
			changedRows[id] = line
		}
	}
	if len(changedRows) == 0 {
		return append([]byte(nil), base...), 0, nil
	}
	seen := map[string]bool{}
	merged := make([][]byte, 0, len(baseLines)+len(changedRows))
	closingAt := -1
	for _, line := range baseLines {
		trimmed := bytes.TrimSpace(line)
		if len(trimmed) > 2 && bytes.HasPrefix(trimmed, []byte("</")) && closingAt < 0 {
			closingAt = len(merged)
		}
		id := stringID(line)
		if replacement, ok := changedRows[id]; ok {
			merged = append(merged, append([]byte(nil), replacement...))
			seen[id] = true
		} else {
			merged = append(merged, append([]byte(nil), line...))
		}
	}
	var additions [][]byte
	ids := make([]string, 0, len(changedRows))
	for id := range changedRows {
		if !seen[id] {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	for _, id := range ids {
		additions = append(additions, append([]byte(nil), changedRows[id]...))
	}
	if len(additions) > 0 {
		if closingAt < 0 {
			return nil, 0, fmt.Errorf("cannot append translated String_No rows: closing element not found")
		}
		out := make([][]byte, 0, len(merged)+len(additions))
		out = append(out, merged[:closingAt]...)
		out = append(out, additions...)
		out = append(out, merged[closingAt:]...)
		merged = out
	}
	return bytes.Join(merged, sep), len(changedRows), nil
}

func TranslationChangedArchives(projectRoot, reportPath string) ([]string, error) {
	_, changed, err := loadTranslationLayer(projectRoot, reportPath)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	var out []string
	for _, file := range changed {
		relative := filepath.ToSlash(file.ArchiveRelativePath)
		key := strings.ToLower(relative)
		if !seen[key] {
			seen[key] = true
			out = append(out, relative)
		}
	}
	sort.Strings(out)
	return out, nil
}

func ApplyTranslationLast(projectRoot, reportPath, workDir string, candidates map[string]string, enc EncryptedTextTool, progress BuildProgressFunc) (TranslationLayerAudit, map[string]string, error) {
	report, changed, err := loadTranslationLayer(projectRoot, reportPath)
	if err != nil {
		return TranslationLayerAudit{}, nil, err
	}
	audit := TranslationLayerAudit{
		TranslationVersion: report.TranslationVersion, TranslationToolingVersion: report.TranslationToolingVersion,
		Archives: map[string]int{}, OutputSHA256: map[string]string{},
	}
	result := map[string]string{}
	for k, v := range candidates {
		result[k] = v
	}
	groups := map[string][]TranslationLayerFile{}
	for _, file := range changed {
		groups[filepath.ToSlash(file.ArchiveRelativePath)] = append(groups[filepath.ToSlash(file.ArchiveRelativePath)], file)
	}
	for archiveRelative, files := range groups {
		source, ok := result[archiveRelative]
		if !ok {
			continue
		}
		archive, err := OpenA22(source)
		if err != nil {
			return audit, nil, err
		}
		replacements := map[string]ArchiveInput{}
		additions := map[string]ArchiveInput{}
		for _, file := range files {
			member := archiveMemberName(file.InternalPath)
			outputPath, err := projectFile(projectRoot, file.OutputPath)
			if err != nil {
				archive.Close()
				return audit, nil, err
			}
			var input ArchiveInput
			if structuredStringTable(member) {
				entry, exists := archive.Find(member)
				if !exists {
					archive.Close()
					return audit, nil, fmt.Errorf("structured translation target missing from candidate: %s", member)
				}
				base, err := archive.Read(entry)
				if err != nil {
					archive.Close()
					return audit, nil, err
				}
				templatePath, err := projectFile(projectRoot, file.TemplatePath)
				if err != nil {
					archive.Close()
					return audit, nil, err
				}
				template, err := os.ReadFile(templatePath)
				if err != nil {
					archive.Close()
					return audit, nil, err
				}
				translated, err := os.ReadFile(outputPath)
				if err != nil {
					archive.Close()
					return audit, nil, err
				}
				merged, rows, err := mergeTranslatedStringRows(base, template, translated)
				if err != nil {
					archive.Close()
					return audit, nil, fmt.Errorf("merge %s: %w", member, err)
				}
				input = MemoryEntry{Data: merged}
				audit.StructuredMerges += rows
				if strings.EqualFold(filepath.Base(strings.ReplaceAll(member, `\`, "/")), "strcombineall.xml") {
					encrypted, err := enc.EncryptBR(merged, "final_strcombineall.xml")
					if err != nil {
						archive.Close()
						return audit, nil, err
					}
					if err := enc.VerifyBRRoundTrip(merged, encrypted, "final_strcombineall.xml"); err != nil {
						archive.Close()
						return audit, nil, err
					}
					encodedName := member + ".e"
					if _, exists := archive.Find(encodedName); !exists {
						archive.Close()
						return audit, nil, fmt.Errorf("encrypted aggregate target missing: %s", encodedName)
					}
					replacements[encodedName] = MemoryEntry{Data: encrypted}
					audit.EncryptedAggregates++
				}
			} else {
				fileInput, err := NewFileEntry(outputPath)
				if err != nil {
					archive.Close()
					return audit, nil, err
				}
				input = fileInput
			}
			if _, exists := archive.Find(member); exists {
				replacements[member] = input
			} else {
				additions[member] = input
			}
			audit.ChangedMembers++
			audit.Archives[archiveRelative]++
		}
		archive.Close()
		if len(replacements) == 0 && len(additions) == 0 {
			continue
		}
		if err := os.MkdirAll(workDir, 0o755); err != nil {
			return audit, nil, err
		}
		out := filepath.Join(workDir, "translation-last-"+strings.NewReplacer("/", "_", `\\`, "_").Replace(archiveRelative))
		progressFn := byteProgress(nil)
		if progress != nil {
			progressFn = func(phase, name string, done, total int64) {
				progress(BuildProgress{Phase: "translation_" + phase, CurrentFile: archiveRelative + ": " + name, CurrentDone: done, CurrentTotal: total})
			}
		}
		if _, err := RewriteA22(source, out, ArchiveEdits{Replacements: replacements, Additions: additions}, progressFn); err != nil {
			return audit, nil, err
		}
		expectedAdded := map[string]string{}
		for name, input := range additions {
			digest, digestErr := input.PlainSHA256()
			if digestErr != nil {
				return audit, nil, digestErr
			}
			expectedAdded[name] = digest
		}
		verify, err := AuditA22Rewrite(source, out, expectedAdded, replacements, progressFn)
		if err != nil {
			return audit, nil, err
		}
		if len(verify.Problems) > 0 {
			return audit, nil, fmt.Errorf("translation-last archive audit failed for %s: %s", archiveRelative, strings.Join(verify.Problems, "; "))
		}
		result[archiveRelative] = out
		hash, _, err := hashPath(out)
		if err != nil {
			return audit, nil, err
		}
		audit.OutputSHA256[archiveRelative] = hash
	}
	return audit, result, nil
}

func sha256Bytes(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

type translationRepackArchive struct {
	TargetID            string   `json:"target_id"`
	ArchiveRelativePath string   `json:"archive_relative_path"`
	OutputPath          string   `json:"output_path"`
	OutputSHA256        string   `json:"output_sha256"`
	OutputBytes         int64    `json:"output_bytes"`
	SourceSHA256        string   `json:"source_archive_sha256"`
	SourceBytes         int64    `json:"source_archive_bytes"`
	ChangedMembers      []string `json:"changed_members"`
	Failures            []string `json:"failures"`
	FullVerified        bool     `json:"full_reextract_verified"`
}

type translationRepackReport struct {
	Status                    string                     `json:"status"`
	TranslationVersion        string                     `json:"translation_version"`
	TranslationToolingVersion string                     `json:"translation_tooling_version"`
	Archives                  []translationRepackArchive `json:"archives"`
}

type StandaloneTranslationMember struct {
	InternalPath string `json:"internal_path"`
	PayloadPath  string `json:"payload_path"`
	SHA256       string `json:"sha256"`
	Bytes        int64  `json:"bytes"`
}

type StandaloneTranslationArchive struct {
	ArchiveRelativePath string                        `json:"archive_relative_path"`
	SourceSHA256        string                        `json:"source_sha256"`
	SourceBytes         int64                         `json:"source_bytes"`
	Members             []StandaloneTranslationMember `json:"members"`
}

type StandaloneTranslationReport struct {
	Type                      string                         `json:"type"`
	FormatVersion             int                            `json:"format_version"`
	Status                    string                         `json:"status"`
	TranslationVersion        string                         `json:"translation_version"`
	TranslationToolingVersion string                         `json:"translation_tooling_version"`
	Archives                  []StandaloneTranslationArchive `json:"archives"`
}

func loadTranslationRepackReport(projectRoot, reportPath string) (translationRepackReport, error) {
	if strings.TrimSpace(reportPath) == "" {
		reportPath = filepath.Join(projectRoot, ".local", "reports", "translation", "BR_TRANSLATION_PAK_REPACK_REPORT.json")
	}
	path, err := projectFile(projectRoot, reportPath)
	if err != nil {
		return translationRepackReport{}, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return translationRepackReport{}, err
	}
	var report translationRepackReport
	if err := json.Unmarshal(data, &report); err != nil {
		return report, fmt.Errorf("decode translation archive report: %w", err)
	}
	if report.Status != "ok" {
		return report, fmt.Errorf("translation archive report status is %q", report.Status)
	}
	translationVersion, err := readVersionFile(filepath.Join(projectRoot, "workstreams", "translation", "VERSION"))
	if err != nil {
		return report, err
	}
	toolingVersion, err := readVersionFile(filepath.Join(projectRoot, "workstreams", "translation_tooling", "VERSION"))
	if err != nil {
		return report, err
	}
	if report.TranslationVersion != translationVersion || report.TranslationToolingVersion != toolingVersion {
		return report, fmt.Errorf("translation archive build is stale: report=%s/%s project=%s/%s", report.TranslationVersion, report.TranslationToolingVersion, translationVersion, toolingVersion)
	}
	return report, nil
}

func loadStandaloneTranslationReport(projectRoot string) (StandaloneTranslationReport, bool, error) {
	path := filepath.Join(projectRoot, ".local", "reports", "translation", "BR_TRANSLATION_STANDALONE_MEMBER_REPORT.json")
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return StandaloneTranslationReport{}, false, nil
	}
	if err != nil {
		return StandaloneTranslationReport{}, false, err
	}
	var report StandaloneTranslationReport
	if err := json.Unmarshal(data, &report); err != nil {
		return report, false, fmt.Errorf("decode standalone Translation report: %w", err)
	}
	if report.Type != "unburger_translation_standalone_members" || report.FormatVersion != 1 || report.Status != "ok" {
		return report, false, fmt.Errorf("unsupported standalone Translation report")
	}
	translationVersion, err := readVersionFile(filepath.Join(projectRoot, "workstreams", "translation", "VERSION"))
	if err != nil {
		return report, false, err
	}
	toolingVersion, err := readVersionFile(filepath.Join(projectRoot, "workstreams", "translation_tooling", "VERSION"))
	if err != nil {
		return report, false, err
	}
	if report.TranslationVersion != translationVersion || report.TranslationToolingVersion != toolingVersion {
		return report, false, fmt.Errorf("standalone Translation members are stale")
	}
	return report, true, nil
}

func TranslationStandaloneArtifacts(projectRoot, reportPath, targetRoot, workDir string, excluded map[string]bool, progress BuildProgressFunc) ([]OutputArtifact, error) {
	report, err := loadTranslationRepackReport(projectRoot, reportPath)
	if err != nil {
		return nil, err
	}
	slim, slimOK, err := loadStandaloneTranslationReport(projectRoot)
	if err != nil {
		return nil, err
	}
	slimByArchive := map[string]StandaloneTranslationArchive{}
	if slimOK {
		for _, archive := range slim.Archives {
			slimByArchive[strings.ToLower(filepath.ToSlash(archive.ArchiveRelativePath))] = archive
		}
	}
	var out []OutputArtifact
	seen := map[string]bool{}
	for _, archive := range report.Archives {
		if archive.TargetID != "blue_reflection_quartet" {
			continue
		}
		relative := filepath.ToSlash(archive.ArchiveRelativePath)
		if excluded[relative] {
			continue
		}
		key := strings.ToLower(relative)
		if seen[key] {
			return nil, fmt.Errorf("duplicate translation archive output: %s", relative)
		}
		seen[key] = true
		if len(archive.Failures) != 0 || !archive.FullVerified {
			return nil, fmt.Errorf("translation archive is not fully verified: %s", relative)
		}
		if len(archive.ChangedMembers) == 0 {
			continue
		}
		source := filepath.Join(targetRoot, filepath.FromSlash(relative))
		if archive.SourceSHA256 != "" {
			hash, size, hashErr := hashPath(source)
			if hashErr != nil {
				return nil, hashErr
			}
			if !strings.EqualFold(hash, archive.SourceSHA256) || (archive.SourceBytes != 0 && size != archive.SourceBytes) {
				return nil, fmt.Errorf("translation baseline fingerprint mismatch: %s", relative)
			}
		}
		replacements := map[string]ArchiveInput{}
		fullOutput, fullErr := projectFile(projectRoot, archive.OutputPath)
		fullReady := fullErr == nil
		if fullReady {
			hash, size, hashErr := hashPath(fullOutput)
			fullReady = hashErr == nil && strings.EqualFold(hash, archive.OutputSHA256) && size == archive.OutputBytes
		}
		if fullReady {
			built, openErr := OpenA22(fullOutput)
			if openErr != nil {
				return nil, fmt.Errorf("open verified Translation archive %s: %w", relative, openErr)
			}
			for _, member := range archive.ChangedMembers {
				name := archiveMemberName(member)
				entry, ok := built.Find(name)
				if !ok {
					built.Close()
					return nil, fmt.Errorf("verified Translation archive lost changed member %s:%s", relative, name)
				}
				blob, readErr := built.Read(entry)
				if readErr != nil {
					built.Close()
					return nil, readErr
				}
				replacements[name] = MemoryEntry{Data: blob}
			}
			built.Close()
		} else {
			declaration, ok := slimByArchive[key]
			if !ok {
				return nil, fmt.Errorf("standalone Translation payload unavailable for %s", relative)
			}
			if archive.SourceSHA256 != "" && !strings.EqualFold(declaration.SourceSHA256, archive.SourceSHA256) {
				return nil, fmt.Errorf("standalone Translation baseline mismatch for %s", relative)
			}
			declared := map[string]StandaloneTranslationMember{}
			for _, member := range declaration.Members {
				declared[strings.ToLower(archiveMemberName(member.InternalPath))] = member
			}
			for _, changed := range archive.ChangedMembers {
				name := archiveMemberName(changed)
				member, ok := declared[strings.ToLower(name)]
				if !ok {
					return nil, fmt.Errorf("standalone Translation member missing: %s:%s", relative, name)
				}
				payload, pathErr := projectFile(projectRoot, member.PayloadPath)
				if pathErr != nil {
					return nil, pathErr
				}
				hash, size, hashErr := hashPath(payload)
				if hashErr != nil || !strings.EqualFold(hash, member.SHA256) || size != member.Bytes {
					return nil, fmt.Errorf("standalone Translation member fingerprint mismatch: %s:%s", relative, name)
				}
				input, inputErr := NewFileEntry(payload)
				if inputErr != nil {
					return nil, inputErr
				}
				replacements[name] = input
			}
		}
		if err := os.MkdirAll(workDir, 0o755); err != nil {
			return nil, err
		}
		candidate := filepath.Join(workDir, "translation-standalone-"+strings.NewReplacer("/", "_", `\\`, "_").Replace(relative))
		progressFn := byteProgress(nil)
		if progress != nil {
			progressFn = func(phase, name string, done, total int64) {
				progress(BuildProgress{Phase: "translation_" + phase, CurrentFile: relative + ": " + name, CurrentDone: done, CurrentTotal: total})
			}
		}
		if _, err := RewriteA22(source, candidate, ArchiveEdits{Replacements: replacements}, progressFn); err != nil {
			return nil, err
		}
		verify, err := AuditA22Rewrite(source, candidate, nil, replacements, progressFn)
		if err != nil {
			return nil, err
		}
		if len(verify.Problems) != 0 {
			return nil, fmt.Errorf("standalone Translation archive audit failed for %s: %s", relative, strings.Join(verify.Problems, "; "))
		}
		hash, size, err := hashPath(candidate)
		if err != nil {
			return nil, err
		}
		out = append(out, OutputArtifact{RelativePath: relative, Path: candidate, Size: size, SHA256: hash})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].RelativePath < out[j].RelativePath })
	return out, nil
}
