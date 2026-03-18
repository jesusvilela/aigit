import { SemanticChunk, ChunkEdge } from './types';
import { GraphCycleError } from '../errors';

export class ChunkGraph {
  readonly chunks: Map<string, SemanticChunk>;
  readonly edges: ChunkEdge[];

  constructor(chunks?: SemanticChunk[], edges?: ChunkEdge[]) {
    this.chunks = new Map();
    this.edges = edges ? [...edges] : [];
    if (chunks) {
      for (const chunk of chunks) {
        this.chunks.set(chunk.id, chunk);
      }
    }
  }

  /** Number of chunks in the graph. */
  get size(): number {
    return this.chunks.size;
  }

  addChunk(chunk: SemanticChunk): void {
    this.chunks.set(chunk.id, chunk);
  }

  addEdge(edge: ChunkEdge): void {
    this.edges.push(edge);
  }

  getChunk(id: string): SemanticChunk | undefined {
    return this.chunks.get(id);
  }

  hasChunk(id: string): boolean {
    return this.chunks.has(id);
  }

  /**
   * Remove a chunk and all edges referencing it.
   * Returns `true` if the chunk existed, `false` otherwise.
   */
  removeChunk(id: string): boolean {
    const existed = this.chunks.delete(id);
    if (existed) {
      const remaining = this.edges.filter(e => e.from !== id && e.to !== id);
      this.edges.length = 0;
      this.edges.push(...remaining);
    }
    return existed;
  }

  /** All edges originating from the given chunk id. */
  getEdgesFrom(id: string): ChunkEdge[] {
    return this.edges.filter(e => e.from === id);
  }

  /** All edges pointing to the given chunk id. */
  getEdgesTo(id: string): ChunkEdge[] {
    return this.edges.filter(e => e.to === id);
  }

  getNeighbors(id: string, direction: 'outgoing' | 'incoming' | 'both' = 'both'): SemanticChunk[] {
    const result: SemanticChunk[] = [];
    const seen = new Set<string>();

    for (const edge of this.edges) {
      if ((direction === 'outgoing' || direction === 'both') && edge.from === id) {
        const chunk = this.chunks.get(edge.to);
        if (chunk && !seen.has(chunk.id)) {
          seen.add(chunk.id);
          result.push(chunk);
        }
      }
      if ((direction === 'incoming' || direction === 'both') && edge.to === id) {
        const chunk = this.chunks.get(edge.from);
        if (chunk && !seen.has(chunk.id)) {
          seen.add(chunk.id);
          result.push(chunk);
        }
      }
    }

    return result;
  }

  /**
   * Detect whether the graph contains at least one cycle.
   * Uses iterative DFS with three-colour marking (white/gray/black).
   */
  hasCycle(): boolean {
    const WHITE = 0, GRAY = 1, BLACK = 2;
    const colour = new Map<string, number>();
    for (const id of this.chunks.keys()) colour.set(id, WHITE);

    // Build adjacency list for efficiency
    const adj = new Map<string, string[]>();
    for (const id of this.chunks.keys()) adj.set(id, []);
    for (const edge of this.edges) {
      const list = adj.get(edge.from);
      if (list) list.push(edge.to);
    }

    for (const startId of this.chunks.keys()) {
      if (colour.get(startId) !== WHITE) continue;

      // Iterative DFS using explicit stack of [nodeId, iterator]
      const stack: Array<[string, IterableIterator<string>]> = [
        [startId, (adj.get(startId) ?? []).values()],
      ];
      colour.set(startId, GRAY);

      while (stack.length > 0) {
        const top = stack[stack.length - 1];
        const { value: neighbourId, done } = top[1].next();

        if (done) {
          colour.set(top[0], BLACK);
          stack.pop();
        } else {
          const c = colour.get(neighbourId);
          if (c === GRAY) return true;
          if (c === WHITE) {
            colour.set(neighbourId, GRAY);
            stack.push([neighbourId, (adj.get(neighbourId) ?? []).values()]);
          }
        }
      }
    }
    return false;
  }

  /**
   * Perform a topological sort (Kahn's algorithm).
   * Nodes unreachable by edges are appended after sorted nodes.
   * @param strict – if `true`, throws `GraphCycleError` when a cycle is detected.
   */
  topologicalSort(strict = false): SemanticChunk[] {
    const inDegree = new Map<string, number>();
    for (const id of this.chunks.keys()) {
      inDegree.set(id, 0);
    }
    for (const edge of this.edges) {
      if (this.chunks.has(edge.to)) {
        inDegree.set(edge.to, (inDegree.get(edge.to) ?? 0) + 1);
      }
    }

    const queue: string[] = [];
    for (const [id, deg] of inDegree) {
      if (deg === 0) queue.push(id);
    }

    const sorted: SemanticChunk[] = [];
    const visited = new Set<string>();

    while (queue.length > 0) {
      const id = queue.shift()!;
      visited.add(id);
      const chunk = this.chunks.get(id);
      if (chunk) sorted.push(chunk);
      for (const edge of this.edges) {
        if (edge.from === id && this.chunks.has(edge.to)) {
          const newDeg = (inDegree.get(edge.to) ?? 0) - 1;
          inDegree.set(edge.to, newDeg);
          if (newDeg === 0) queue.push(edge.to);
        }
      }
    }

    // Detect cycle: some nodes still have positive in-degree
    const cycleNodes = [...inDegree.entries()]
      .filter(([, deg]) => deg > 0)
      .map(([id]) => id);

    if (cycleNodes.length > 0) {
      if (strict) throw new GraphCycleError(cycleNodes);
      // Degrade gracefully: append unvisited nodes in insertion order
      for (const id of this.chunks.keys()) {
        if (!visited.has(id)) {
          sorted.push(this.chunks.get(id)!);
        }
      }
    }

    return sorted;
  }

  /**
   * Return a new ChunkGraph containing only the specified chunk ids and
   * all edges between them.
   */
  subgraph(ids: string[]): ChunkGraph {
    const idSet = new Set(ids);
    const chunks = ids
      .map(id => this.chunks.get(id))
      .filter((c): c is SemanticChunk => c !== undefined);
    const edges = this.edges.filter(e => idSet.has(e.from) && idSet.has(e.to));
    return new ChunkGraph(chunks, edges);
  }

  toJSON(): { chunks: SemanticChunk[]; edges: ChunkEdge[] } {
    return {
      chunks: Array.from(this.chunks.values()),
      edges: [...this.edges],
    };
  }

  static fromJSON(data: { chunks: SemanticChunk[]; edges: ChunkEdge[] }): ChunkGraph {
    return new ChunkGraph(data.chunks, data.edges);
  }
}
