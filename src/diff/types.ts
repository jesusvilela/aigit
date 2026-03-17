import { SemanticChunk } from '../chunk/types';

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
}

export interface SemanticDiffResult {
  diffs: ChunkDiff[];
  added: number;
  removed: number;
  modified: number;
  renamed: number;
  unchanged: number;
}
