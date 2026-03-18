import { ChunkGraph } from '../chunk/graph';

export interface Snapshot {
  /** Unique snapshot identifier (sha1 of timestamp + filePath). */
  id: string;
  /** ISO 8601 creation timestamp. */
  timestamp: string;
  /** The source file this snapshot was taken from. */
  filePath: string;
  /** The commit SHA this snapshot corresponds to (optional). */
  commitSha?: string;
  /** The serialised chunk graph. */
  graph: ReturnType<ChunkGraph['toJSON']>;
  /** Arbitrary additional metadata. */
  metadata?: Record<string, unknown>;
}
