package main

import (
	"fmt"
	"sort"
	"strings"
)

const (
	quartetTranslationModule = "blue_reflection_translation"
	quartetRestorationModule = "quartet_restoration"
	quartetLegacyDLCModule   = "quartet_legacy_dlc"
)

const (
	restorationProfilePolicyRuntimeValidated         = "runtime-validated"
	restorationProfilePolicyAllCandidatesRuntimeTest = "all-current-candidates-for-runtime-test"
)

func normalizeRestorationProfilePolicy(raw string) (string, error) {
	policy := strings.TrimSpace(raw)
	if policy == "" {
		policy = restorationProfilePolicyRuntimeValidated
	}
	switch policy {
	case restorationProfilePolicyRuntimeValidated, restorationProfilePolicyAllCandidatesRuntimeTest:
		return policy, nil
	default:
		return "", fmt.Errorf("unsupported Restoration profile policy: %s", policy)
	}
}

func validateRestorationProfilePolicyForModules(policy string, modules []string) error {
	if policy != restorationProfilePolicyAllCandidatesRuntimeTest {
		return nil
	}
	if !sameQuartetCompositionModules(modules, []string{quartetRestorationModule}) {
		return fmt.Errorf("all-current-candidates-for-runtime-test is allowed only for isolated Restoration-only composition")
	}
	return nil
}

var quartetCompositionModuleOrder = []string{
	quartetTranslationModule,
	quartetRestorationModule,
	quartetLegacyDLCModule,
}

func normalizeQuartetCompositionModules(values []string) ([]string, error) {
	selected := map[string]bool{}
	for _, raw := range values {
		for _, item := range strings.Split(raw, ",") {
			module := strings.TrimSpace(item)
			if module == "" {
				continue
			}
			switch module {
			case quartetTranslationModule, quartetRestorationModule, quartetLegacyDLCModule:
				selected[module] = true
			default:
				return nil, fmt.Errorf("unsupported Quartet composition module: %s", module)
			}
		}
	}
	if len(selected) == 0 {
		selected[quartetTranslationModule] = true
		selected[quartetRestorationModule] = true
	}
	result := make([]string, 0, len(selected))
	for _, module := range quartetCompositionModuleOrder {
		if selected[module] {
			result = append(result, module)
		}
	}
	return result, nil
}

func quartetCompositionModuleSet(values []string) map[string]bool {
	result := map[string]bool{}
	for _, value := range values {
		result[value] = true
	}
	return result
}

func sameQuartetCompositionModules(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	leftCopy := append([]string{}, left...)
	rightCopy := append([]string{}, right...)
	sort.Strings(leftCopy)
	sort.Strings(rightCopy)
	for index := range leftCopy {
		if leftCopy[index] != rightCopy[index] {
			return false
		}
	}
	return true
}

func quartetSelectionNeedsComposition(selected map[string]bool) bool {
	if selected[quartetRestorationModule] {
		return true
	}
	return selected[quartetTranslationModule] && selected[quartetLegacyDLCModule]
}
