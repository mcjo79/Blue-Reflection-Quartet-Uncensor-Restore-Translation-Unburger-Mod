package br1rebuild

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const wetSchoolTargetArchiveRelative = "Data/PACK10_02.PAK"

type WetSchoolRestorationMemberAudit struct {
	Character    string `json:"character"`
	SourceMember string `json:"source_member"`
	TargetMember string `json:"target_member"`
	Size         int64  `json:"size"`
	SHA256       string `json:"sha256"`
}

type WetSchoolRestorationAudit struct {
	ArchiveRelativePath string                            `json:"archive_relative_path"`
	Capability          string                            `json:"capability"`
	Characters          int                               `json:"characters"`
	ReplacedMembers     int                               `json:"replaced_members"`
	Members             []WetSchoolRestorationMemberAudit `json:"members"`
	OutputSHA256        string                            `json:"output_sha256"`
}

func ApplyWetSchoolRestoration(workDir, sourceRoot string, candidates map[string]string, progress BuildProgressFunc) (WetSchoolRestorationAudit, map[string]string, error) {
	audit := WetSchoolRestorationAudit{ArchiveRelativePath: wetSchoolTargetArchiveRelative, Capability: WetSchoolCanonicalSourceCapability}
	if err := validateWetSchoolSourceRoot(sourceRoot); err != nil {
		return audit, nil, err
	}
	targetSource, ok := candidates[wetSchoolTargetArchiveRelative]
	if !ok || strings.TrimSpace(targetSource) == "" {
		return audit, nil, fmt.Errorf("wet-school restoration base candidate missing: %s", wetSchoolTargetArchiveRelative)
	}

	sourceArchivePath := filepath.Join(sourceRoot, "DATA", "PACK00_02.PAK")
	sourceArchive, err := OpenA18(sourceArchivePath)
	if err != nil {
		return audit, nil, err
	}
	defer sourceArchive.Close()

	targetArchive, err := OpenA22(targetSource)
	if err != nil {
		return audit, nil, err
	}
	defer targetArchive.Close()

	replacements := map[string]ArchiveInput{}
	for i := 0; i < 15; i++ {
		pc := fmt.Sprintf("pc%02d", i)
		for _, suffix := range []string{".elixir.gz", ".g1t"} {
			sourceName := `\data\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			targetName := `\data\b1\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			srcEntry, ok := sourceArchive.Find(sourceName)
			if !ok {
				return audit, nil, fmt.Errorf("wet-school donor member missing: %s", sourceName)
			}
			if _, ok := targetArchive.Find(targetName); !ok {
				return audit, nil, fmt.Errorf("Quartet wet-school target member missing: %s", targetName)
			}
			donor := CrossFormatEntry{Pak: sourceArchive, Entry: srcEntry}
			digest, err := donor.PlainSHA256()
			if err != nil {
				return audit, nil, err
			}
			replacements[targetName] = donor
			audit.Members = append(audit.Members, WetSchoolRestorationMemberAudit{
				Character: pc, SourceMember: sourceName, TargetMember: targetName, Size: int64(srcEntry.Size), SHA256: digest,
			})
		}
	}
	sort.Slice(audit.Members, func(i, j int) bool { return audit.Members[i].TargetMember < audit.Members[j].TargetMember })
	audit.Characters = 15
	audit.ReplacedMembers = len(replacements)
	if audit.ReplacedMembers != expectedWetSchoolSourceMembers {
		return audit, nil, fmt.Errorf("wet-school restoration prepared %d replacements, expected %d", audit.ReplacedMembers, expectedWetSchoolSourceMembers)
	}

	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return audit, nil, err
	}
	output := filepath.Join(workDir, "PACK10_02.wet-school.PAK")
	progressFn := byteProgress(nil)
	if progress != nil {
		progressFn = func(phase, name string, done, total int64) {
			progress(BuildProgress{Phase: "wet_school_" + phase, CurrentFile: wetSchoolTargetArchiveRelative + ": " + name, CurrentDone: done, CurrentTotal: total})
		}
	}
	if _, err := RewriteA22(targetSource, output, ArchiveEdits{Replacements: replacements}, progressFn); err != nil {
		return audit, nil, err
	}
	verify, err := AuditA22Rewrite(targetSource, output, nil, replacements, progressFn)
	if err != nil {
		return audit, nil, err
	}
	if len(verify.Problems) > 0 {
		return audit, nil, fmt.Errorf("wet-school restoration archive audit failed: %s", strings.Join(verify.Problems, "; "))
	}
	if verify.Changed != expectedWetSchoolSourceMembers {
		return audit, nil, fmt.Errorf("wet-school restoration changed %d members, expected %d", verify.Changed, expectedWetSchoolSourceMembers)
	}
	digest, _, err := hashPath(output)
	if err != nil {
		return audit, nil, err
	}
	audit.OutputSHA256 = digest
	result := make(map[string]string, len(candidates))
	for k, v := range candidates {
		result[k] = v
	}
	result[wetSchoolTargetArchiveRelative] = output
	return audit, result, nil
}
