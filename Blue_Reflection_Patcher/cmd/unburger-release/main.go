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
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

type looseFile struct {
	ArchiveRelativePath string `json:"archive_relative_path"`
	InternalPath        string `json:"internal_path"`
	TemplatePath        string `json:"template_path"`
	TemplateSHA256      string `json:"template_sha256"`
	OutputPath          string `json:"output_path"`
	OutputSHA256        string `json:"output_sha256"`
	OutputBytes         int64  `json:"output_bytes"`
	Changed             bool   `json:"changed"`
}

type looseTarget struct {
	Files []looseFile `json:"files"`
}
type looseReport struct {
	Type                      string                 `json:"type"`
	Status                    string                 `json:"status"`
	TranslationVersion        string                 `json:"translation_version"`
	TranslationToolingVersion string                 `json:"translation_tooling_version"`
	Targets                   map[string]looseTarget `json:"targets"`
}

type repackArchive struct {
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
type repackReport struct {
	Type                      string          `json:"type"`
	Status                    string          `json:"status"`
	TranslationVersion        string          `json:"translation_version"`
	TranslationToolingVersion string          `json:"translation_tooling_version"`
	Archives                  []repackArchive `json:"archives"`
}

type releaseManifest struct {
	Type                      string   `json:"type"`
	FormatVersion             int      `json:"format_version"`
	CoreVersion               string   `json:"core_version"`
	TranslationVersion        string   `json:"translation_version"`
	TranslationToolingVersion string   `json:"translation_tooling_version"`
	TranslationTargets        []string `json:"translation_targets"`
	TranslationChangedFiles   int      `json:"translation_changed_files"`
	StandaloneChangedMembers  int      `json:"standalone_changed_members"`
	ModuleOrder               []string `json:"quartet_module_order"`
	LargeGameArchivesIncluded bool     `json:"large_game_archives_included"`
}

func main() {
	fs := flag.NewFlagSet("unburger-release", flag.ExitOnError)
	project := fs.String("project-root", "", "project root")
	stage := fs.String("stage-root", "", "release staging root")
	_ = fs.Parse(os.Args[1:])
	if *project == "" || *stage == "" {
		fatal("--project-root and --stage-root are required")
	}
	if err := stageRelease(*project, *stage); err != nil {
		fatal(err.Error())
	}
}

func fatal(msg string) { fmt.Fprintln(os.Stderr, "ERROR:", msg); os.Exit(1) }
func readText(path string) (string, error) {
	b, e := os.ReadFile(path)
	return strings.TrimSpace(string(b)), e
}
func fileHash(path string) (string, int64, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", 0, e
	}
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return "", 0, e
	}
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", 0, e
	}
	return hex.EncodeToString(h.Sum(nil)), st.Size(), nil
}
func cleanJoin(root, rel string) (string, error) {
	rootAbs, e := filepath.Abs(root)
	if e != nil {
		return "", e
	}
	p := rel
	if !filepath.IsAbs(p) {
		p = filepath.Join(rootAbs, filepath.FromSlash(rel))
	}
	p, e = filepath.Abs(p)
	if e != nil {
		return "", e
	}
	r, e := filepath.Rel(rootAbs, p)
	if e != nil {
		return "", e
	}
	if r == ".." || strings.HasPrefix(r, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("path leaves root: %s", rel)
	}
	return p, nil
}
func copyVerified(root, stage, rel, want string, wantSize int64) (string, error) {
	src, e := cleanJoin(root, rel)
	if e != nil {
		return "", e
	}
	hash, size, e := fileHash(src)
	if e != nil {
		return "", e
	}
	if want != "" && !strings.EqualFold(hash, want) {
		return "", fmt.Errorf("fingerprint mismatch: %s", rel)
	}
	if wantSize >= 0 && size != wantSize {
		return "", fmt.Errorf("size mismatch: %s", rel)
	}
	dst := filepath.Join(stage, filepath.FromSlash(rel))
	if e = os.MkdirAll(filepath.Dir(dst), 0755); e != nil {
		return "", e
	}
	in, e := os.Open(src)
	if e != nil {
		return "", e
	}
	defer in.Close()
	out, e := os.Create(dst)
	if e != nil {
		return "", e
	}
	_, e = io.Copy(out, in)
	ce := out.Close()
	if e != nil {
		return "", e
	}
	if ce != nil {
		return "", ce
	}
	return dst, nil
}
func structured(path string) bool {
	b := strings.ToLower(filepath.Base(strings.ReplaceAll(path, `\`, "/")))
	return b == "strcombineall.xml" || b == "str_costume.xml"
}
func sanitizeMember(path string) string {
	path = strings.TrimLeft(strings.ReplaceAll(path, `\`, "/"), "/")
	parts := strings.Split(path, "/")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p == "" || p == "." || p == ".." {
			continue
		}
		out = append(out, p)
	}
	return filepath.Join(out...)
}

func stageRelease(project, stage string) error {
	project, _ = filepath.Abs(project)
	stage, _ = filepath.Abs(stage)
	if err := os.RemoveAll(stage); err != nil {
		return err
	}
	if err := os.MkdirAll(stage, 0755); err != nil {
		return err
	}
	coreVersion, e := readText(filepath.Join(project, "workstreams/core/VERSION"))
	if e != nil {
		return e
	}
	transVersion, e := readText(filepath.Join(project, "workstreams/translation/VERSION"))
	if e != nil {
		return e
	}
	toolingVersion, e := readText(filepath.Join(project, "workstreams/translation_tooling/VERSION"))
	if e != nil {
		return e
	}
	loosePath := filepath.Join(project, ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json")
	repackPath := filepath.Join(project, ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json")
	var loose looseReport
	b, e := os.ReadFile(loosePath)
	if e != nil {
		return e
	}
	if e = json.Unmarshal(b, &loose); e != nil {
		return e
	}
	if loose.Status != "ok" || loose.TranslationVersion != transVersion || loose.TranslationToolingVersion != toolingVersion {
		return fmt.Errorf("Translation loose build is missing or stale: report=%s/%s current=%s/%s", loose.TranslationVersion, loose.TranslationToolingVersion, transVersion, toolingVersion)
	}
	var repack repackReport
	b, e = os.ReadFile(repackPath)
	if e != nil {
		return e
	}
	if e = json.Unmarshal(b, &repack); e != nil {
		return e
	}
	if repack.Status != "ok" || repack.TranslationVersion != transVersion || repack.TranslationToolingVersion != toolingVersion {
		return fmt.Errorf("Translation archive build is missing or stale")
	}

	for _, rel := range []string{"workstreams/translation/VERSION", "workstreams/translation_tooling/VERSION", ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json", ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"} {
		if _, e := copyVerified(project, stage, rel, "", -1); e != nil {
			return e
		}
	}
	changed := 0
	targets := make([]string, 0, len(loose.Targets))
	for id := range loose.Targets {
		targets = append(targets, id)
	}
	sort.Strings(targets)
	for _, id := range targets {
		files := loose.Targets[id].Files
		for _, f := range files {
			if !f.Changed {
				continue
			}
			changed++
			if _, e := copyVerified(project, stage, f.OutputPath, f.OutputSHA256, f.OutputBytes); e != nil {
				return fmt.Errorf("%s: %w", f.InternalPath, e)
			}
			if structured(f.InternalPath) {
				if f.TemplatePath == "" || f.TemplateSHA256 == "" {
					return fmt.Errorf("structured Translation member lacks template: %s", f.InternalPath)
				}
				if _, e := copyVerified(project, stage, f.TemplatePath, f.TemplateSHA256, -1); e != nil {
					return fmt.Errorf("%s template: %w", f.InternalPath, e)
				}
			}
		}
	}

	slim := br1rebuild.StandaloneTranslationReport{Type: "unburger_translation_standalone_members", FormatVersion: 1, Status: "ok", TranslationVersion: transVersion, TranslationToolingVersion: toolingVersion}
	standaloneCount := 0
	for _, a := range repack.Archives {
		if len(a.ChangedMembers) == 0 {
			continue
		}
		output, e := cleanJoin(project, a.OutputPath)
		if e != nil {
			return e
		}
		hash, size, e := fileHash(output)
		if e != nil {
			return fmt.Errorf("verified Translation archive unavailable for member extraction: %s: %w", a.ArchiveRelativePath, e)
		}
		if !strings.EqualFold(hash, a.OutputSHA256) || size != a.OutputBytes || len(a.Failures) != 0 || !a.FullVerified {
			return fmt.Errorf("verified Translation archive drift: %s", a.ArchiveRelativePath)
		}
		archive, e := br1rebuild.OpenA22(output)
		if e != nil {
			return fmt.Errorf("open Translation archive %s: %w", a.ArchiveRelativePath, e)
		}
		decl := br1rebuild.StandaloneTranslationArchive{ArchiveRelativePath: a.ArchiveRelativePath, SourceSHA256: a.SourceSHA256, SourceBytes: a.SourceBytes}
		for _, member := range a.ChangedMembers {
			name := member
			name = strings.ReplaceAll(name, "/", `\`)
			if !strings.HasPrefix(name, `\`) {
				name = `\` + name
			}
			entry, ok := archive.Find(name)
			if !ok {
				archive.Close()
				return fmt.Errorf("changed member missing from verified Translation archive: %s:%s", a.ArchiveRelativePath, name)
			}
			blob, e := archive.Read(entry)
			if e != nil {
				archive.Close()
				return e
			}
			digest := sha256.Sum256(blob)
			hexhash := hex.EncodeToString(digest[:])
			rel := filepath.ToSlash(filepath.Join(".local", "build", "translation", "release_members", a.TargetID, strings.TrimSuffix(filepath.Base(a.ArchiveRelativePath), filepath.Ext(a.ArchiveRelativePath)), sanitizeMember(name)))
			dst := filepath.Join(stage, filepath.FromSlash(rel))
			if e = os.MkdirAll(filepath.Dir(dst), 0755); e != nil {
				archive.Close()
				return e
			}
			if e = os.WriteFile(dst, blob, 0644); e != nil {
				archive.Close()
				return e
			}
			decl.Members = append(decl.Members, br1rebuild.StandaloneTranslationMember{InternalPath: name, PayloadPath: rel, SHA256: hexhash, Bytes: int64(len(blob))})
			standaloneCount++
		}
		archive.Close()
		sort.Slice(decl.Members, func(i, j int) bool { return decl.Members[i].InternalPath < decl.Members[j].InternalPath })
		slim.Archives = append(slim.Archives, decl)
	}
	sort.Slice(slim.Archives, func(i, j int) bool {
		return slim.Archives[i].ArchiveRelativePath < slim.Archives[j].ArchiveRelativePath
	})
	reportPath := filepath.Join(stage, ".local", "reports", "translation", "BR_TRANSLATION_STANDALONE_MEMBER_REPORT.json")
	if e = os.MkdirAll(filepath.Dir(reportPath), 0755); e != nil {
		return e
	}
	encoded, _ := json.MarshalIndent(slim, "", "  ")
	if e = os.WriteFile(reportPath, append(encoded, '\n'), 0644); e != nil {
		return e
	}

	manifest := releaseManifest{Type: "unburger_release_manifest", FormatVersion: 1, CoreVersion: coreVersion, TranslationVersion: transVersion, TranslationToolingVersion: toolingVersion, TranslationTargets: targets, TranslationChangedFiles: changed, StandaloneChangedMembers: standaloneCount, ModuleOrder: []string{"quartet_legacy_dlc", "quartet_restoration", "blue_reflection_translation"}, LargeGameArchivesIncluded: false}
	mb, _ := json.MarshalIndent(manifest, "", "  ")
	return os.WriteFile(filepath.Join(stage, "RELEASE_MANIFEST.json"), append(mb, '\n'), 0644)
}
