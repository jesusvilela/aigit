/**
 * Base error class for all aigit errors.
 */
export class AigitError extends Error {
  constructor(message: string, public readonly code: string) {
    super(message);
    this.name = 'AigitError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when source code cannot be parsed into semantic chunks.
 */
export class ParseError extends AigitError {
  constructor(
    message: string,
    public readonly filePath: string,
    public readonly line?: number,
  ) {
    super(message, 'PARSE_ERROR');
    this.name = 'ParseError';
  }
}

/**
 * Raised when a cycle is detected in a ChunkGraph.
 */
export class GraphCycleError extends AigitError {
  constructor(public readonly cycleIds: string[]) {
    super(
      `Cycle detected in chunk graph: ${cycleIds.join(' → ')}`,
      'GRAPH_CYCLE',
    );
    this.name = 'GraphCycleError';
  }
}

/**
 * Raised when a semantic merge produces unresolvable conflicts and the caller
 * has requested strict (non-conflict-tolerant) behaviour.
 */
export class MergeConflictError extends AigitError {
  constructor(public readonly conflictIds: string[]) {
    super(
      `Merge conflict in ${conflictIds.length} chunk(s): ${conflictIds.join(', ')}`,
      'MERGE_CONFLICT',
    );
    this.name = 'MergeConflictError';
  }
}

/**
 * Raised when a required aigit config or snapshot file is missing or corrupt.
 */
export class ConfigError extends AigitError {
  constructor(message: string) {
    super(message, 'CONFIG_ERROR');
    this.name = 'ConfigError';
  }
}
