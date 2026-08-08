package translationbundle

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

func Load(path string) (Bundle, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Bundle{}, err
	}
	var bundle Bundle
	if err := json.Unmarshal(data, &bundle); err != nil {
		return Bundle{}, err
	}
	if bundle.Type != "unburger_translation_records" || bundle.FormatVersion != 1 || strings.TrimSpace(bundle.TranslationVersion) == "" {
		return Bundle{}, fmt.Errorf("unsupported Translation record bundle")
	}
	return bundle, nil
}

func shaBytes(data []byte) string { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }

func shaFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func installationContentTargets(targetID string) ([]string, error) {
	switch targetID {
	case "blue_reflection_original":
		return []string{"blue_reflection_original"}, nil
	case "second_light_original":
		return []string{"second_light_original"}, nil
	case "blue_reflection_quartet":
		return []string{"blue_reflection_quartet", "blue_reflection_ray_quartet", "blue_reflection_sun_quartet", "second_light_quartet"}, nil
	default:
		return nil, fmt.Errorf("unsupported Translation installation target: %s", targetID)
	}
}

func openArchive(targetID, path string) (*br1rebuild.ArchiveReader, string, error) {
	if targetID == "blue_reflection_original" {
		a, e := br1rebuild.OpenA18(path)
		return a, "a18", e
	}
	a, e := br1rebuild.OpenA22(path)
	return a, "a22", e
}

func rewriteArchive(format, src, dst string, replacements map[string]br1rebuild.ArchiveInput, progress br1rebuild.ByteProgressFunc) error {
	var audit br1rebuild.ArchiveAuditResult
	var err error
	switch format {
	case "a18":
		_, err = br1rebuild.RewriteA18(src, dst, br1rebuild.ArchiveEdits{Replacements: replacements}, progress)
		if err == nil {
			audit, err = br1rebuild.AuditA18Rewrite(src, dst, nil, replacements, progress)
		}
	case "a22":
		_, err = br1rebuild.RewriteA22(src, dst, br1rebuild.ArchiveEdits{Replacements: replacements}, progress)
		if err == nil {
			audit, err = br1rebuild.AuditA22Rewrite(src, dst, nil, replacements, progress)
		}
	default:
		return fmt.Errorf("unsupported archive format %q", format)
	}
	if err != nil {
		return err
	}
	if len(audit.Problems) > 0 {
		return fmt.Errorf("Translation archive audit failed: %s", strings.Join(audit.Problems, "; "))
	}
	return nil
}

func memberName(v string) string {
	v = strings.ReplaceAll(v, "/", `\`)
	if !strings.HasPrefix(v, `\`) {
		v = `\` + v
	}
	return v
}

// ApplyInstallation materializes the canonical Translation record bundle on top
// of the current compatible installation/candidate archives. Whole-archive
// hashes are intentionally not used as compatibility gates.
func ApplyInstallation(bundle Bundle, installationTargetID, gameRoot, workDir string, candidates map[string]string, enc br1rebuild.EncryptedTextTool, progress br1rebuild.BuildProgressFunc) (ApplyAudit, map[string]string, error) {
	targetIDs, err := installationContentTargets(installationTargetID)
	if err != nil {
		return ApplyAudit{}, nil, err
	}
	wanted := map[string]bool{}
	for _, id := range targetIDs {
		wanted[id] = true
	}
	audit := ApplyAudit{TranslationVersion: bundle.TranslationVersion, TargetID: installationTargetID, Archives: map[string]int{}, OutputSHA256: map[string]string{}}
	result := map[string]string{}
	for k, v := range candidates {
		result[filepath.ToSlash(k)] = v
	}
	groups := map[string][]Member{}
	for _, target := range bundle.Targets {
		if !wanted[target.TargetID] {
			continue
		}
		for _, member := range target.Members {
			groups[filepath.ToSlash(member.ArchiveRelativePath)] = append(groups[filepath.ToSlash(member.ArchiveRelativePath)], member)
		}
	}
	archives := make([]string, 0, len(groups))
	for a := range groups {
		archives = append(archives, a)
	}
	sort.Strings(archives)
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return audit, nil, err
	}
	for _, relative := range archives {
		source := result[relative]
		if source == "" {
			source = filepath.Join(gameRoot, filepath.FromSlash(relative))
		}
		reader, format, err := openArchive(installationTargetID, source)
		if err != nil {
			return audit, nil, fmt.Errorf("open Translation source %s: %w", relative, err)
		}
		replacements := map[string]br1rebuild.ArchiveInput{}
		for _, decl := range groups[relative] {
			name := memberName(decl.InternalPath)
			entry, ok := reader.Find(name)
			if !ok {
				reader.Close()
				return audit, nil, fmt.Errorf("compatible Translation member missing: %s:%s", relative, name)
			}
			base, err := reader.Read(entry)
			if err != nil {
				reader.Close()
				return audit, nil, err
			}
			var out []byte
			var already, rebase int
			switch decl.Kind {
			case "ebm":
				out, already, rebase, err = applyEBM(base, decl.Records)
			case "xml":
				out, already, rebase, err = applyXML(base, decl.Records)
			default:
				err = fmt.Errorf("unsupported Translation member kind %q", decl.Kind)
			}
			if err != nil {
				reader.Close()
				return audit, nil, fmt.Errorf("apply %s:%s: %w", relative, name, err)
			}
			audit.AlreadyDesired += already
			audit.StructuralRebases += rebase
			audit.Records += len(decl.Records)
			audit.Members++
			audit.Archives[relative]++
			replacements[name] = br1rebuild.MemoryEntry{Data: out}
			baseName := strings.ToLower(filepath.Base(strings.ReplaceAll(name, `\`, "/")))
			if decl.Kind == "xml" && baseName == "strcombineall.xml" {
				encodedName := name + ".e"
				if _, ok := reader.Find(encodedName); ok {
					encrypted, encErr := enc.EncryptBR(out, "translation_strcombineall.xml")
					if encErr != nil {
						reader.Close()
						return audit, nil, encErr
					}
					if encErr = enc.VerifyBRRoundTrip(out, encrypted, "translation_strcombineall.xml"); encErr != nil {
						reader.Close()
						return audit, nil, encErr
					}
					replacements[encodedName] = br1rebuild.MemoryEntry{Data: encrypted}
					audit.EncryptedAggregates++
				}
			}
		}
		reader.Close()
		outPath := filepath.Join(workDir, "translation-records-"+strings.NewReplacer("/", "_", `\`, "_").Replace(relative))
		progressFn := br1rebuild.ByteProgressFunc(nil)
		if progress != nil {
			progressFn = func(phase, name string, done, total int64) {
				progress(br1rebuild.BuildProgress{Phase: "translation_" + phase, CurrentFile: relative + ": " + name, CurrentDone: done, CurrentTotal: total})
			}
		}
		if err := rewriteArchive(format, source, outPath, replacements, progressFn); err != nil {
			return audit, nil, fmt.Errorf("rewrite %s: %w", relative, err)
		}
		outSHA, err := shaFile(outPath)
		if err != nil {
			return audit, nil, err
		}
		audit.OutputSHA256[relative] = outSHA
		result[relative] = outPath
	}
	return audit, result, nil
}

func ChangedArchives(bundle Bundle, installationTargetID string) ([]string, error) {
	targetIDs, err := installationContentTargets(installationTargetID)
	if err != nil {
		return nil, err
	}
	wanted := map[string]bool{}
	for _, id := range targetIDs {
		wanted[id] = true
	}
	seen := map[string]bool{}
	var out []string
	for _, target := range bundle.Targets {
		if !wanted[target.TargetID] {
			continue
		}
		for _, member := range target.Members {
			rel := filepath.ToSlash(member.ArchiveRelativePath)
			key := strings.ToLower(rel)
			if !seen[key] {
				seen[key] = true
				out = append(out, rel)
			}
		}
	}
	sort.Strings(out)
	return out, nil
}
