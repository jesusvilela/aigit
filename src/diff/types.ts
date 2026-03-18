import { SemanticChunk } from '../chunk/types';
import { ChunkEdge } from '../chunk/types';

export enum DiffKind {
  Added = 'added',
  Removed = 'removed',
  Modified = 'modified',
  Renamed = 'renamed',
  Unchanged = 'unchanged',
}

export interface ChunkDiff {
  kind: DiffKind;
  before?: SemanticChunk;
  after?: SemanticChunk;
  /** Similarity score in [0, 1] for Modified/Renamed entries. */
  similarity?: number;
}

export enum EdgeDiffKind {
  Added = 'added',
  Removed = 'removed',
  Unchanged = 'unchanged',
}

export interface EdgeDiff {
  kind: EdgeDiffKind;
  edge: ChunkEdge;
}

/** Human-readable summary of a diff result. */
export interface DiffSummary {
  /** Total chunks that changed (added + removed + modified + renamed). */
  changedChunks: number;
  /** Total chunks considered. */
  totalChunks: number;
  /** Percentage of chunks that changed (0–100). */
  changePercentage: number;
  /** Most common change kind. */
  dominantKind: DiffKind;
}

export interface SemanticDiffResult {
  diffs: ChunkDiff[];
  added: number;
  removed: number;
  modified: number;
  renamed: number;
  unchanged: number;
  /** Diffs at the edge level. */
  edgeDiffs: EdgeDiff[];
  /** Pre-computed summary statistics. */
  summary: DiffSummary;
}
