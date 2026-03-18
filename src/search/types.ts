import { SemanticChunk, ChunkType } from '../chunk/types';

/** Filters for querying chunks from a ChunkGraph. */
export interface SearchQuery {
  /** Exact or partial name match (case-insensitive). */
  name?: string;
  /** Only return chunks of the given type. */
  type?: ChunkType | ChunkType[];
  /** Only return chunks from the given file path (partial match). */
  filePath?: string;
  /** Case-insensitive substring match against chunk content. */
  contentPattern?: string;
  /** Minimum starting line (inclusive). */
  startLineMin?: number;
  /** Maximum starting line (inclusive). */
  startLineMax?: number;
  /** Arbitrary metadata key/value filter. All entries must match. */
  metadata?: Record<string, unknown>;
  /**
   * Maximum Levenshtein distance for name fuzzy-matching.
   * If set, the `name` field is treated as a fuzzy target rather than a
   * substring. Exact matches are always ranked first.
   * Set to 0 to require an exact (case-insensitive) name match.
   */
  fuzzyDistance?: number;
  /** Maximum number of results to return (default: unlimited). */
  limit?: number;
}

/** A chunk returned by a search, ranked by relevance score (0–1). */
export interface SearchResult {
  chunk: SemanticChunk;
  /** Relevance score between 0 (no match signal) and 1 (perfect match). */
  score: number;
}
