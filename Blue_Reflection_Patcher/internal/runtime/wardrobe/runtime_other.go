//go:build !windows

package wardrobe

func ApplyToProcess(pid uint32, profile TargetProfile, records RecordSet) (ApplyReport, error) {
	return ApplyReport{}, ErrRuntimeUnsupported
}

func FindProcessByName(name string) (uint32, error) {
	return 0, ErrRuntimeUnsupported
}
