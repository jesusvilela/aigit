import { ChunkGraph } from '../chunk/graph';
import { ChunkDiff, DiffKind, SemanticDiffResult } from './types';

export function diff(before: ChunkGraph, after: ChunkGraph): SemanticDiffResult {
  const diffs: ChunkDiff[] = [];

  const unmatchedBefore = new Map(before.chunks);
  const unmatchedAfter = new Map(after.chunks);

  // Match by id
  for (const [id, beforeChunk] of before.chunks) {
    const afterChunk = after.chunks.get(id);
    if (afterChunk) {
      if (beforeChunk.contentHash === afterChunk.contentHash) {
        diffs.push({ kind: DiffKind.Unchanged, before: beforeChunk, after: afterChunk });
      } else {
        diffs.push({ kind: DiffKind.Modified, before: beforeChunk, after: afterChunk });
      }
      unmatchedBefore.delete(id);
      unmatchedAfter.delete(id);
    }
  }

  // Match unmatched by contentHash (renamed)
  const beforeByHash = new Map<string, string>();
  for (const [id, chunk] of unmatchedBefore) {
    beforeByHash.set(chunk.contentHash, id);
  }

  for (const [id, afterChunk] of [...unmatchedAfter]) {
    const beforeId = beforeByHash.get(afterChunk.contentHash);
    if (beforeId) {
      const beforeChunk = unmatchedBefore.get(beforeId)!;
      diffs.push({ kind: DiffKind.Renamed, before: beforeChunk, after: afterChunk });
      unmatchedBefore.delete(beforeId);
      unmatchedAfter.delete(id);
      beforeByHash.delete(afterChunk.contentHash);
    }
  }

  // Remaining before → Removed
  for (const [, chunk] of unmatchedBefore) {
    diffs.push({ kind: DiffKind.Removed, before: chunk });
  }

  // Remaining after → Added
  for (const [, chunk] of unmatchedAfter) {
    diffs.push({ kind: DiffKind.Added, after: chunk });
  }

  return {
    diffs,
    added: diffs.filter(d => d.kind === DiffKind.Added).length,
    removed: diffs.filter(d => d.kind === DiffKind.Removed).length,
    modified: diffs.filter(d => d.kind === DiffKind.Modified).length,
    renamed: diffs.filter(d => d.kind === DiffKind.Renamed).length,
    unchanged: diffs.filter(d => d.kind === DiffKind.Unchanged).length,
  };
}
