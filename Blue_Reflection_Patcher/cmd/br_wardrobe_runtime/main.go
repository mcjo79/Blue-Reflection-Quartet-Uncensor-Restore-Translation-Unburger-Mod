package main

import (
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"local/blue-reflection-patcher/internal/runtime/wardrobe"
	"os"
	"strconv"
)

func fatalf(f string, a ...any) { fmt.Fprintf(os.Stderr, "ERROR: "+f+"\n", a...); os.Exit(2) }
func emit(v any) {
	e := json.NewEncoder(os.Stdout)
	e.SetIndent("", "  ")
	if err := e.Encode(v); err != nil {
		fatalf("encode JSON: %v", err)
	}
}
func parseAddress(s string) uint64 {
	if s == "" {
		return 0
	}
	v, err := strconv.ParseUint(s, 0, 64)
	if err != nil {
		fatalf("invalid address %q: %v", s, err)
	}
	return v
}
func loadInputs(pp, rp string) (wardrobe.TargetProfile, wardrobe.RecordSet) {
	p, err := wardrobe.LoadProfile(pp)
	if err != nil {
		fatalf("load profile: %v", err)
	}
	r, err := wardrobe.LoadRecords(rp)
	if err != nil {
		fatalf("load records: %v", err)
	}
	if err := r.Validate(p); err != nil {
		fatalf("validate records: %v", err)
	}
	return p, r
}
func usage() {
	fmt.Fprintln(os.Stderr, "br_wardrobe_runtime - generic bounded runtime wardrobe registry + cache virtualization")
	fmt.Fprintln(os.Stderr, "commands: capabilities | validate-module | stub-audit | seen-stub-audit | plan | attach")
}
func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "capabilities":
		emit(map[string]any{
			"type": "br_runtime_capabilities", "format_version": 1,
			"capabilities":                []string{wardrobe.CapabilityIDV1, wardrobe.CapabilityIDV2, wardrobe.CapabilityIDV3, wardrobe.CapabilityID},
			"wardrobe_registry_append_v1": map[string]any{"memory_only": true, "global_show_all": false, "max_append_records": 8, "on_disk_game_binary_patch": false, "save_mutation": false, "superseded_by": wardrobe.CapabilityID},
			"wardrobe_registry_append_v2": map[string]any{"memory_only": true, "global_show_all": false, "max_append_records": 8, "on_disk_game_binary_patch": false, "save_mutation": false, "superseded_by": wardrobe.CapabilityID, "known_runtime_native_preservation_bug": true},
			"wardrobe_registry_append_v3": map[string]any{"memory_only": true, "global_show_all": false, "max_append_records": 8, "on_disk_game_binary_patch": false, "save_mutation": false, "registry_virtualization": true, "external_shadow_cache": true, "per_object_synthetic_cache": true, "context_slot_count": 4096, "preserve_embedded_cache_0_55": true, "embedded_cache_in_place_extension": false, "object_writes_past_original_cache": false, "record_input_v1_compatible": true, "native_pointer_formula_exact": true, "native_branch_target_verified": true, "hook_register_transparent": true, "rdx_preserved": true, "superseded_by": wardrobe.CapabilityID},
			"wardrobe_registry_append_v4": map[string]any{"memory_only": true, "global_show_all": false, "max_append_records": 8, "on_disk_game_binary_patch": false, "save_mutation": false, "registry_virtualization": true, "external_shadow_cache": true, "per_object_synthetic_cache": true, "context_slot_count": 4096, "preserve_embedded_cache_0_55": true, "embedded_cache_in_place_extension": false, "object_writes_past_original_cache": false, "record_input_v1_compatible": true, "native_pointer_formula_exact": true, "native_branch_target_verified": true, "hook_register_transparent": true, "rdx_preserved": true, "process_local_synthetic_seen_state": true, "synthetic_seen_survives_cache_rebuild": true, "native_seen_behavior_preserved": true, "native_seen_backing_widened": false},
		})
	case "stub-audit":
		fs := flag.NewFlagSet("stub-audit", flag.ExitOnError)
		profile := fs.String("profile", "", "target profile JSON")
		template := fs.String("template-address", "0x1111111122222222", "hypothetical immutable template address")
		contexts := fs.String("context-table-address", "0x3333333344444444", "hypothetical per-object context table")
		overflow := fs.String("overflow-context-address", "0x5555555566666666", "hypothetical safe overflow context")
		_ = fs.Parse(os.Args[2:])
		if *profile == "" {
			fatalf("--profile required")
		}
		p, err := wardrobe.LoadProfile(*profile)
		if err != nil {
			fatalf("load profile: %v", err)
		}
		b, audit, err := wardrobe.BuildCachePointerStub(p, parseAddress(*template), parseAddress(*contexts), parseAddress(*overflow))
		if err != nil {
			fatalf("build stub: %v", err)
		}
		emit(map[string]any{"status": "pass", "audit": audit, "stub_hex": hex.EncodeToString(b)})
	case "seen-stub-audit":
		fs := flag.NewFlagSet("seen-stub-audit", flag.ExitOnError)
		profile := fs.String("profile", "", "target profile JSON")
		template := fs.String("template-address", "0x1111111122222222", "hypothetical process-local synthetic template address")
		nativeSetter := fs.String("native-setter-address", "", "optional absolute native setter address; defaults to preferred image base + profile RVA")
		_ = fs.Parse(os.Args[2:])
		if *profile == "" {
			fatalf("--profile required")
		}
		p, err := wardrobe.LoadProfile(*profile)
		if err != nil {
			fatalf("load profile: %v", err)
		}
		ns := parseAddress(*nativeSetter)
		if ns == 0 {
			ns = p.PreferredImageBase + uint64(p.SeenState.NativeSetterRVA)
		}
		b, audit, err := wardrobe.BuildSeenStateStub(p, parseAddress(*template), ns)
		if err != nil {
			fatalf("build seen-state stub: %v", err)
		}
		emit(map[string]any{"status": "pass", "audit": audit, "stub_hex": hex.EncodeToString(b)})
	case "validate-module":
		fs := flag.NewFlagSet("validate-module", flag.ExitOnError)
		module := fs.String("module", "", "path to B1.dll")
		profile := fs.String("profile", "", "target profile JSON")
		_ = fs.Parse(os.Args[2:])
		if *module == "" || *profile == "" {
			fatalf("--module and --profile required")
		}
		p, err := wardrobe.LoadProfile(*profile)
		if err != nil {
			fatalf("load profile: %v", err)
		}
		r, err := wardrobe.ValidateModule(*module, p)
		if err != nil {
			fatalf("validate module: %v", err)
		}
		emit(r)
		if r.Status != "pass" {
			os.Exit(1)
		}
	case "plan":
		fs := flag.NewFlagSet("plan", flag.ExitOnError)
		module := fs.String("module", "", "path")
		profile := fs.String("profile", "", "profile")
		records := fs.String("records", "", "records")
		table := fs.String("new-table-address", "", "hypothetical table")
		cache := fs.String("shadow-cache-address", "", "hypothetical synthetic cache template")
		contexts := fs.String("context-table-address", "", "hypothetical per-object context table")
		overflow := fs.String("overflow-context-address", "", "hypothetical safe overflow context")
		stub := fs.String("hook-stub-address", "", "hypothetical pointer stub")
		seenStub := fs.String("seen-stub-address", "", "hypothetical seen-state stub")
		_ = fs.Parse(os.Args[2:])
		if *module == "" || *profile == "" || *records == "" {
			fatalf("--module --profile --records required")
		}
		p, r := loadInputs(*profile, *records)
		v, err := wardrobe.ValidateModule(*module, p)
		if err != nil {
			fatalf("validate module: %v", err)
		}
		if v.Status != "pass" {
			emit(map[string]any{"status": "failed", "module_validation": v})
			os.Exit(1)
		}
		base := validationImageBase(v)
		t := parseAddress(*table)
		if t == 0 {
			t = base + 0x40000000
		}
		c := parseAddress(*cache)
		if c == 0 {
			c = t + 0x10000
		}
		cx := parseAddress(*contexts)
		if cx == 0 {
			cx = c + 0x10000
		}
		o := parseAddress(*overflow)
		if o == 0 {
			o = cx + 0x100000
		}
		s := parseAddress(*stub)
		if s == 0 {
			s = base + 0x50000000
		}
		ss := parseAddress(*seenStub)
		if ss == 0 {
			ss = base + 0x50010000
		}
		pl, err := wardrobe.BuildPlan(p, r, base, t, c, cx, o, s, ss)
		if err != nil {
			fatalf("build plan: %v", err)
		}
		emit(map[string]any{"status": pl.Status, "module_validation": v, "plan": pl})
		if pl.Status != "pass" {
			os.Exit(1)
		}
	case "attach":
		fs := flag.NewFlagSet("attach", flag.ExitOnError)
		pid := fs.Uint("pid", 0, "PID")
		name := fs.String("process-name", "", "process name")
		profile := fs.String("profile", "", "profile")
		records := fs.String("records", "", "records")
		_ = fs.Parse(os.Args[2:])
		if *profile == "" || *records == "" {
			fatalf("--profile and --records required")
		}
		if (*pid == 0) == (*name == "") {
			fatalf("specify exactly one of --pid or --process-name")
		}
		p, r := loadInputs(*profile, *records)
		target := uint32(*pid)
		if target == 0 {
			f, err := wardrobe.FindProcessByName(*name)
			if err != nil {
				fatalf("find process: %v", err)
			}
			target = f
		}
		rep, err := wardrobe.ApplyToProcess(target, p, r)
		if err != nil {
			fatalf("runtime apply: %v", err)
		}
		emit(rep)
		if rep.Status != "applied" {
			os.Exit(1)
		}
	default:
		usage()
		os.Exit(2)
	}
}
func validationImageBase(r wardrobe.ModuleValidationReport) uint64 {
	v, err := strconv.ParseUint(r.ImageBase, 0, 64)
	if err != nil {
		fatalf("invalid image base %q", r.ImageBase)
	}
	return v
}
