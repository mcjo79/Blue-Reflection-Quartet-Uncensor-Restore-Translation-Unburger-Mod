package main

import (
	"path/filepath"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/managedstate"
	"local/blue-reflection-patcher/internal/translationbundle"
)

func appendTranslationManagedStateArtifact(targetID, workDir string, audit translationbundle.ApplyAudit, artifacts []br1rebuild.OutputArtifact) ([]br1rebuild.OutputArtifact, error) {
	if len(audit.ManagedMembers) == 0 {
		return artifacts, nil
	}
	path := filepath.Join(workDir, "managed-state", managedstate.FileName)
	if err := managedstate.Write(path, targetID, audit.TranslationVersion, audit.ManagedMembers); err != nil {
		return nil, err
	}
	return append(artifacts, br1rebuild.OutputArtifact{RelativePath: managedstate.FileName, Path: path}), nil
}
