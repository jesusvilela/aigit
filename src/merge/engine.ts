import { ChunkGraph } from '../chunk/graph';
import { MergeConflict, MergeStatus, SemanticMergeResult } from './types';
import { SemanticChunk } from '../chunk/types';

export function merge(base: ChunkGraph, ours: ChunkGraph, theirs: ChunkGraph): SemanticMergeResult {
  const conflicts: MergeConflict[] = [];
  const merged = new ChunkGraph();

  const allIds = new Set<string>([
    ...base.chunks.keys(),
    ...ours.chunks.keys(),
    ...theirs.chunks.keys(),
  ]);

  for (const id of allIds) {
    const baseChunk = base.chunks.get(id);
    const ourChunk = ours.chunks.get(id);
    const theirChunk = theirs.chunks.get(id);

    const inBase = baseChunk !== undefined;
    const inOurs = ourChunk !== undefined;
    const inTheirs = theirChunk !== undefined;

    if (!inBase && !inOurs && !inTheirs) continue;

    if (!inBase) {
      if (inOurs && !inTheirs) {
        merged.addChunk(ourChunk!);
      } else if (!inOurs && inTheirs) {
        merged.addChunk(theirChunk!);
      } else if (inOurs && inTheirs) {
        if (ourChunk!.contentHash === theirChunk!.contentHash) {
          merged.addChunk(ourChunk!);
        } else {
          conflicts.push({
            chunkId: id,
            base: undefined,
            ours: ourChunk!,
            theirs: theirChunk!,
            message: `Both branches added chunk '${id}' with different content`,
          });
        }
      }
      continue;
    }

    if (!inOurs && !inTheirs) {
      continue;
    }

    if (!inOurs && inTheirs) {
      if (theirChunk!.contentHash !== baseChunk!.contentHash) {
        conflicts.push({
          chunkId: id,
          base: baseChunk,
          ours: { ...baseChunk!, content: '', contentHash: '' } as SemanticChunk,
          theirs: theirChunk!,
          message: `Chunk '${id}' was deleted in ours but modified in theirs`,
        });
      }
      continue;
    }

    if (inOurs && !inTheirs) {
      if (ourChunk!.contentHash !== baseChunk!.contentHash) {
        conflicts.push({
          chunkId: id,
          base: baseChunk,
          ours: ourChunk!,
          theirs: { ...baseChunk!, content: '', contentHash: '' } as SemanticChunk,
          message: `Chunk '${id}' was modified in ours but deleted in theirs`,
        });
      }
      continue;
    }

    // In all three
    const oursChanged = ourChunk!.contentHash !== baseChunk!.contentHash;
    const theirsChanged = theirChunk!.contentHash !== baseChunk!.contentHash;

    if (!oursChanged && !theirsChanged) {
      merged.addChunk(baseChunk!);
    } else if (oursChanged && !theirsChanged) {
      merged.addChunk(ourChunk!);
    } else if (!oursChanged && theirsChanged) {
      merged.addChunk(theirChunk!);
    } else {
      if (ourChunk!.contentHash === theirChunk!.contentHash) {
        merged.addChunk(ourChunk!);
      } else {
        conflicts.push({
          chunkId: id,
          base: baseChunk,
          ours: ourChunk!,
          theirs: theirChunk!,
          message: `Chunk '${id}' was modified differently in ours and theirs`,
        });
      }
    }
  }

  return {
    status: conflicts.length > 0 ? MergeStatus.Conflict : MergeStatus.Success,
    merged,
    conflicts,
  };
}
