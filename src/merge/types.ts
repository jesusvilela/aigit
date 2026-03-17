import { SemanticChunk } from '../chunk/types';
import { ChunkGraph } from '../chunk/graph';

export enum MergeStatus {
  Success = 'success',
  Conflict = 'conflict',
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
}
