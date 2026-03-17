import { SemanticChunk, ChunkEdge } from './types';

export class ChunkGraph {
  chunks: Map<string, SemanticChunk>;
  edges: ChunkEdge[];

  constructor(chunks?: SemanticChunk[], edges?: ChunkEdge[]) {
    this.chunks = new Map();
    this.edges = edges ? [...edges] : [];
    if (chunks) {
      for (const chunk of chunks) {
        this.chunks.set(chunk.id, chunk);
      }
    }
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

  topologicalSort(): SemanticChunk[] {
    const inDegree = new Map<string, number>();
    for (const id of this.chunks.keys()) {
      inDegree.set(id, 0);
    }
    for (const edge of this.edges) {
      inDegree.set(edge.to, (inDegree.get(edge.to) ?? 0) + 1);
    }

    const queue: string[] = [];
    for (const [id, deg] of inDegree) {
      if (deg === 0) queue.push(id);
    }

    const sorted: SemanticChunk[] = [];
    while (queue.length > 0) {
      const id = queue.shift()!;
      const chunk = this.chunks.get(id);
      if (chunk) sorted.push(chunk);
      for (const edge of this.edges) {
        if (edge.from === id) {
          const newDeg = (inDegree.get(edge.to) ?? 0) - 1;
          inDegree.set(edge.to, newDeg);
          if (newDeg === 0) queue.push(edge.to);
        }
      }
    }

    for (const [id, chunk] of this.chunks) {
      if (!sorted.find(c => c.id === id)) {
        sorted.push(chunk);
      }
    }

    return sorted;
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
