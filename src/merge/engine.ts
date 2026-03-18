import { ChunkGraph } from '../chunk/graph';
import { MergeConflict, MergeStatus, MergeStrategy, SemanticMergeResult } from './types';
import { SemanticChunk } from '../chunk/types';
import { ChunkEdge } from '../chunk/types';

export interface MergeOptions {
  /** Global conflict-resolution strategy (default: Auto). */
  strategy?: MergeStrategy;
  /** Per-chunk strategy overrides keyed by chunk id. */
  chunkStrategies?: Record<string, MergeStrategy>;
}

function mergeEdges(
  base: ChunkGraph,
  ours: ChunkGraph,
  theirs: ChunkGraph,
  mergedChunkIds: Set<string>,
): ChunkEdge[] {
  const baseKeys  = new Set(base.edges.map(e => `${e.from}→${e.to}:${e.kind}`));
  const oursKeys  = new Set(ours.edges.map(e => `${e.from}→${e.to}:${e.kind}`));

  const seen = new Set<string>();
  const result: ChunkEdge[] = [];

  function addEdge(e: ChunkEdge): void {
    if (!mergedChunkIds.has(e.from) || !mergedChunkIds.has(e.to)) return;
    const key = `${e.from}→${e.to}:${e.kind}`;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(e);
    }
  }

  // Keep base edges that neither branch deleted
  for (const e of base.edges) {
    const key = `${e.from}→${e.to}:${e.kind}`;
    const keptInOurs   = oursKeys.has(key);
    const keptInTheirs = new Set(theirs.edges.map(x => `${x.from}→${x.to}:${x.kind}`)).has(key);
    if (keptInOurs || keptInTheirs) addEdge(e);
  }

  // Add edges introduced in ours
  for (const e of ours.edges) {
    const key = `${e.from}→${e.to}:${e.kind}`;
    if (!baseKeys.has(key)) addEdge(e);
  }

  // Add edges introduced in theirs
  for (const e of theirs.edges) {
    const key = `${e.from}→${e.to}:${e.kind}`;
    if (!baseKeys.has(key)) addEdge(e);
  }

  return result;
}

export function merge(
  base: ChunkGraph,
  ours: ChunkGraph,
  theirs: ChunkGraph,
  options: MergeOptions = {},
): SemanticMergeResult {
  const strategy = options.strategy ?? MergeStrategy.Auto;
  const chunkStrategies = options.chunkStrategies ?? {};

  const conflicts: MergeConflict[] = [];
  const merged = new ChunkGraph();
  let autoResolved = 0;

  const allIds = new Set<string>([
    ...base.chunks.keys(),
    ...ours.chunks.keys(),
    ...theirs.chunks.keys(),
  ]);

  for (const id of allIds) {
    const baseChunk  = base.chunks.get(id);
    const ourChunk   = ours.chunks.get(id);
    const theirChunk = theirs.chunks.get(id);

    const inBase   = baseChunk  !== undefined;
    const inOurs   = ourChunk   !== undefined;
    const inTheirs = theirChunk !== undefined;

    if (!inBase && !inOurs && !inTheirs) continue;

    const effectiveStrategy = chunkStrategies[id] ?? strategy;

    // ── Not in base ──────────────────────────────────────────────────────────
    if (!inBase) {
      if (inOurs && !inTheirs) {
        merged.addChunk(ourChunk!);
      } else if (!inOurs && inTheirs) {
        merged.addChunk(theirChunk!);
      } else if (inOurs && inTheirs) {
        if (ourChunk!.contentHash === theirChunk!.contentHash) {
          merged.addChunk(ourChunk!);
        } else if (effectiveStrategy === MergeStrategy.Ours) {
          merged.addChunk(ourChunk!);
          autoResolved++;
        } else if (effectiveStrategy === MergeStrategy.Theirs) {
          merged.addChunk(theirChunk!);
          autoResolved++;
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

    // ── In base but deleted in both ──────────────────────────────────────────
    if (!inOurs && !inTheirs) {
      continue;
    }

    // ── Deleted in ours, modified or unchanged in theirs ────────────────────
    if (!inOurs && inTheirs) {
      if (theirChunk!.contentHash !== baseChunk!.contentHash) {
        if (effectiveStrategy === MergeStrategy.Theirs) {
          merged.addChunk(theirChunk!);
          autoResolved++;
        } else if (effectiveStrategy === MergeStrategy.Ours) {
          // deleted in ours — keep deletion
          autoResolved++;
        } else {
          conflicts.push({
            chunkId: id,
            base: baseChunk,
            ours: { ...baseChunk!, content: '', contentHash: '' } as SemanticChunk,
            theirs: theirChunk!,
            message: `Chunk '${id}' was deleted in ours but modified in theirs`,
          });
        }
      }
      // unchanged in theirs and deleted in ours → keep deletion (no conflict)
      continue;
    }

    // ── Deleted in theirs, modified or unchanged in ours ────────────────────
    if (inOurs && !inTheirs) {
      if (ourChunk!.contentHash !== baseChunk!.contentHash) {
        if (effectiveStrategy === MergeStrategy.Ours) {
          merged.addChunk(ourChunk!);
          autoResolved++;
        } else if (effectiveStrategy === MergeStrategy.Theirs) {
          // keep deletion
          autoResolved++;
        } else {
          conflicts.push({
            chunkId: id,
            base: baseChunk,
            ours: ourChunk!,
            theirs: { ...baseChunk!, content: '', contentHash: '' } as SemanticChunk,
            message: `Chunk '${id}' was modified in ours but deleted in theirs`,
          });
        }
      }
      // unchanged in ours and deleted in theirs → keep deletion (no conflict)
      continue;
    }

    // ── In all three ─────────────────────────────────────────────────────────
    const oursChanged   = ourChunk!.contentHash   !== baseChunk!.contentHash;
    const theirsChanged = theirChunk!.contentHash !== baseChunk!.contentHash;

    if (!oursChanged && !theirsChanged) {
      merged.addChunk(baseChunk!);
    } else if (oursChanged && !theirsChanged) {
      merged.addChunk(ourChunk!);
    } else if (!oursChanged && theirsChanged) {
      merged.addChunk(theirChunk!);
    } else {
      // Both changed
      if (ourChunk!.contentHash === theirChunk!.contentHash) {
        // Same result — no conflict
        merged.addChunk(ourChunk!);
      } else if (effectiveStrategy === MergeStrategy.Ours) {
        merged.addChunk(ourChunk!);
        autoResolved++;
      } else if (effectiveStrategy === MergeStrategy.Theirs) {
        merged.addChunk(theirChunk!);
        autoResolved++;
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

  // ── Merge edges ───────────────────────────────────────────────────────────
  const mergedChunkIds = new Set(merged.chunks.keys());
  const mergedEdges = mergeEdges(base, ours, theirs, mergedChunkIds);
  for (const edge of mergedEdges) {
    merged.addEdge(edge);
  }

  return {
    status: conflicts.length > 0 ? MergeStatus.Conflict : MergeStatus.Success,
    merged,
    conflicts,
    autoResolved,
    mergedEdgeCount: mergedEdges.length,
  };
}
