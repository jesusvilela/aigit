import { ChunkGraph } from '../chunk/graph';
import { ChunkDiff, DiffKind, EdgeDiff, EdgeDiffKind, SemanticDiffResult, DiffSummary } from './types';
import { tokenSimilarity } from '../search/engine';
import { ChunkEdge } from '../chunk/types';

/** Minimum token-similarity required to treat two different-id chunks as a rename. */
const RENAME_SIMILARITY_THRESHOLD = 0.5;

function buildEdgeKey(e: ChunkEdge): string {
  return `${e.from}→${e.to}:${e.kind}`;
}

function diffEdges(before: ChunkGraph, after: ChunkGraph): EdgeDiff[] {
  const beforeKeys = new Set(before.edges.map(buildEdgeKey));
  const afterKeys  = new Set(after.edges.map(buildEdgeKey));

  const result: EdgeDiff[] = [];

  for (const edge of before.edges) {
    const key = buildEdgeKey(edge);
    result.push({
      kind: afterKeys.has(key) ? EdgeDiffKind.Unchanged : EdgeDiffKind.Removed,
      edge,
    });
  }
  for (const edge of after.edges) {
    const key = buildEdgeKey(edge);
    if (!beforeKeys.has(key)) {
      result.push({ kind: EdgeDiffKind.Added, edge });
    }
  }
  return result;
}

function computeSummary(
  added: number,
  removed: number,
  modified: number,
  renamed: number,
  unchanged: number,
): DiffSummary {
  const changedChunks = added + removed + modified + renamed;
  const totalChunks   = changedChunks + unchanged;
  const changePercentage = totalChunks > 0
    ? Math.round((changedChunks / totalChunks) * 100)
    : 0;

  const counts: Record<DiffKind, number> = {
    [DiffKind.Added]:     added,
    [DiffKind.Removed]:   removed,
    [DiffKind.Modified]:  modified,
    [DiffKind.Renamed]:   renamed,
    [DiffKind.Unchanged]: unchanged,
  };
  const dominantKind = (Object.entries(counts) as [DiffKind, number][])
    .sort(([, a], [, b]) => b - a)[0][0];

  return { changedChunks, totalChunks, changePercentage, dominantKind };
}

export function diff(before: ChunkGraph, after: ChunkGraph): SemanticDiffResult {
  const diffs: ChunkDiff[] = [];

  const unmatchedBefore = new Map(before.chunks);
  const unmatchedAfter  = new Map(after.chunks);

  // ── Pass 1: exact id match ────────────────────────────────────────────────
  for (const [id, beforeChunk] of before.chunks) {
    const afterChunk = after.chunks.get(id);
    if (afterChunk) {
      if (beforeChunk.contentHash === afterChunk.contentHash) {
        diffs.push({ kind: DiffKind.Unchanged, before: beforeChunk, after: afterChunk });
      } else {
        const sim = tokenSimilarity(beforeChunk.content, afterChunk.content);
        diffs.push({ kind: DiffKind.Modified, before: beforeChunk, after: afterChunk, similarity: sim });
      }
      unmatchedBefore.delete(id);
      unmatchedAfter.delete(id);
    }
  }

  // ── Pass 2: exact contentHash rename ─────────────────────────────────────
  const beforeByHash = new Map<string, string>();
  for (const [id, chunk] of unmatchedBefore) {
    beforeByHash.set(chunk.contentHash, id);
  }

  for (const [id, afterChunk] of [...unmatchedAfter]) {
    const beforeId = beforeByHash.get(afterChunk.contentHash);
    if (beforeId) {
      const beforeChunk = unmatchedBefore.get(beforeId)!;
      diffs.push({ kind: DiffKind.Renamed, before: beforeChunk, after: afterChunk, similarity: 1.0 });
      unmatchedBefore.delete(beforeId);
      unmatchedAfter.delete(id);
      beforeByHash.delete(afterChunk.contentHash);
    }
  }

  // ── Pass 3: fuzzy rename — same type, similar content ────────────────────
  for (const [afterId, afterChunk] of [...unmatchedAfter]) {
    let bestBeforeId: string | undefined;
    let bestSim = RENAME_SIMILARITY_THRESHOLD;

    for (const [beforeId, beforeChunk] of unmatchedBefore) {
      if (beforeChunk.type !== afterChunk.type) continue;
      const sim = tokenSimilarity(beforeChunk.content, afterChunk.content);
      if (sim > bestSim) {
        bestSim = sim;
        bestBeforeId = beforeId;
      }
    }

    if (bestBeforeId !== undefined) {
      const beforeChunk = unmatchedBefore.get(bestBeforeId)!;
      diffs.push({ kind: DiffKind.Renamed, before: beforeChunk, after: afterChunk, similarity: bestSim });
      unmatchedBefore.delete(bestBeforeId);
      unmatchedAfter.delete(afterId);
    }
  }

  // ── Remaining ────────────────────────────────────────────────────────────
  for (const [, chunk] of unmatchedBefore) {
    diffs.push({ kind: DiffKind.Removed, before: chunk });
  }
  for (const [, chunk] of unmatchedAfter) {
    diffs.push({ kind: DiffKind.Added, after: chunk });
  }

  const added     = diffs.filter(d => d.kind === DiffKind.Added).length;
  const removed   = diffs.filter(d => d.kind === DiffKind.Removed).length;
  const modified  = diffs.filter(d => d.kind === DiffKind.Modified).length;
  const renamed   = diffs.filter(d => d.kind === DiffKind.Renamed).length;
  const unchanged = diffs.filter(d => d.kind === DiffKind.Unchanged).length;

  return {
    diffs,
    added,
    removed,
    modified,
    renamed,
    unchanged,
    edgeDiffs: diffEdges(before, after),
    summary: computeSummary(added, removed, modified, renamed, unchanged),
  };
}
