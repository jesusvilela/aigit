export { ChunkType, SemanticChunk, ChunkEdge } from './chunk/types';
export { parse } from './chunk/parser';
export { ChunkGraph } from './chunk/graph';
export { DiffKind, ChunkDiff, EdgeDiff, EdgeDiffKind, DiffSummary, SemanticDiffResult } from './diff/types';
export { diff } from './diff/engine';
export { MergeStatus, MergeStrategy, MergeConflict, SemanticMergeResult } from './merge/types';
export { merge, MergeOptions } from './merge/engine';
export { AgentIdentity, ProvenanceRecord, ProvenanceStore } from './provenance/types';
export { ProvenanceTracker } from './provenance/tracker';
export { JsonProvenanceStore } from './provenance/store';
export { GitAdapter, LogEntry } from './git/adapter';
export { AigitConfig, readConfig, writeConfig, initConfig } from './config';
export { Snapshot } from './snapshot/types';
export { SnapshotStore } from './snapshot/store';
export { SearchQuery, SearchResult } from './search/types';
export { search, searchMany, levenshtein, tokenSimilarity } from './search/engine';
export {
  GraphMetrics,
  PathResult,
  indegree,
  outdegree,
  findRoots,
  findLeaves,
  reachableFrom,
  impactOf,
  bfs,
  dfs,
  shortestPath,
  longestPath,
  connectedComponents,
  computeMetrics,
} from './analysis/index';
export { AigitPipeline, PipelineOptions, PipelineRunResult, PipelineMergeResult } from './pipeline/index';
export {
  AigitError,
  ParseError,
  GraphCycleError,
  MergeConflictError,
  ConfigError,
} from './errors';
