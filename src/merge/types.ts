import { SemanticChunk } from '../chunk/types';
import { ChunkGraph } from '../chunk/graph';

export enum MergeStatus {
  Success = 'success',
  Conflict = 'conflict',
}

/**
 * Strategy for resolving a chunk-level conflict.
 * - `Auto`   – aigit chooses the best resolution (default).
 * - `Ours`   – always take our version.
 * - `Theirs` – always take their version.
 * - `Manual` – leave the conflict unresolved (surfaced in `conflicts`).
 */
export enum MergeStrategy {
  Auto   = 'auto',
  Ours   = 'ours',
  Theirs = 'theirs',
  Manual = 'manual',
}

export interface MergeConflict {
  chunkId: string;
  base?: SemanticChunk;
  ours: SemanticChunk;
  theirs: SemanticChunk;
  message: string;
}

export interface SemanticMergeResult {
  status: MergeStatus;
  merged: ChunkGraph;
  conflicts: MergeConflict[];
  /** Number of chunks that were automatically resolved (non-trivial). */
  autoResolved: number;
  /** Number of edges added to the merged graph. */
  mergedEdgeCount: number;
}
