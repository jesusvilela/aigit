import { ChunkGraph } from '../chunk/graph';
import { SemanticChunk } from '../chunk/types';
import { ChunkEdge } from '../chunk/types';

// ─── Metrics ────────────────────────────────────────────────────────────────

export interface GraphMetrics {
  /** Number of chunks (nodes). */
  chunkCount: number;
  /** Number of edges. */
  edgeCount: number;
  /** Average number of outgoing edges per node. */
  avgOutDegree: number;
  /** Average number of incoming edges per node. */
  avgInDegree: number;
  /** Density = edgeCount / (chunkCount * (chunkCount - 1)), 0 for empty graphs. */
  density: number;
  /** Number of isolated chunks (no edges at all). */
  isolatedCount: number;
  /** Number of root chunks (in-degree = 0, out-degree > 0). */
  rootCount: number;
  /** Number of leaf chunks (out-degree = 0, in-degree > 0). */
  leafCount: number;
  /** Whether the graph has at least one cycle. */
  hasCycle: boolean;
}

export interface PathResult {
  path: SemanticChunk[];
  length: number;
}

// ─── Degree helpers ──────────────────────────────────────────────────────────

/**
 * Returns the in-degree (number of incoming edges) of `id`.
 */
export function indegree(graph: ChunkGraph, id: string): number {
  return graph.edges.filter(e => e.to === id).length;
}

/**
 * Returns the out-degree (number of outgoing edges) of `id`.
 */
export function outdegree(graph: ChunkGraph, id: string): number {
  return graph.edges.filter(e => e.from === id).length;
}

// ─── Structure queries ───────────────────────────────────────────────────────

/**
 * Returns all chunks that have no incoming edges AND at least one outgoing edge
 * (potential entry points / sources in the DAG).
 * Note: isolated nodes (no edges at all) are not considered roots.
 */
export function findRoots(graph: ChunkGraph): SemanticChunk[] {
  return [...graph.chunks.values()].filter(
    c => indegree(graph, c.id) === 0 && outdegree(graph, c.id) > 0,
  );
}

/**
 * Returns all chunks that have no outgoing edges AND at least one incoming edge
 * (terminal nodes / sinks in the DAG).
 * Note: isolated nodes (no edges at all) are not considered leaves.
 */
export function findLeaves(graph: ChunkGraph): SemanticChunk[] {
  return [...graph.chunks.values()].filter(
    c => outdegree(graph, c.id) === 0 && indegree(graph, c.id) > 0,
  );
}

/**
 * Returns all chunks reachable from `startId` via outgoing edges (BFS).
 * The starting chunk itself is NOT included.
 */
export function reachableFrom(graph: ChunkGraph, startId: string): SemanticChunk[] {
  const visited = new Set<string>();
  const queue = [startId];

  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const edge of graph.edges) {
      if (edge.from === id && !visited.has(edge.to)) {
        visited.add(edge.to);
        queue.push(edge.to);
      }
    }
  }

  return [...visited]
    .map(id => graph.chunks.get(id))
    .filter((c): c is SemanticChunk => c !== undefined);
}

/**
 * Returns all chunks from which `targetId` is reachable (reverse BFS).
 * Useful for change-impact analysis: "what breaks if I change X?"
 * The target chunk itself is NOT included.
 */
export function impactOf(graph: ChunkGraph, targetId: string): SemanticChunk[] {
  const visited = new Set<string>();
  const queue = [targetId];

  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const edge of graph.edges) {
      if (edge.to === id && !visited.has(edge.from)) {
        visited.add(edge.from);
        queue.push(edge.from);
      }
    }
  }

  return [...visited]
    .map(id => graph.chunks.get(id))
    .filter((c): c is SemanticChunk => c !== undefined);
}

/**
 * BFS from `startId` returning chunks in breadth-first order.
 * The starting chunk IS included (as the first element).
 */
export function bfs(graph: ChunkGraph, startId: string): SemanticChunk[] {
  const start = graph.chunks.get(startId);
  if (!start) return [];

  const visited = new Set<string>([startId]);
  const queue = [startId];
  const result: SemanticChunk[] = [start];

  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const edge of graph.edges) {
      if (edge.from === id && !visited.has(edge.to)) {
        visited.add(edge.to);
        queue.push(edge.to);
        const chunk = graph.chunks.get(edge.to);
        if (chunk) result.push(chunk);
      }
    }
  }
  return result;
}

/**
 * Iterative DFS from `startId` returning chunks in depth-first order.
 * The starting chunk IS included (as the first element).
 */
export function dfs(graph: ChunkGraph, startId: string): SemanticChunk[] {
  const start = graph.chunks.get(startId);
  if (!start) return [];

  const visited = new Set<string>();
  const stack = [startId];
  const result: SemanticChunk[] = [];

  while (stack.length > 0) {
    const id = stack.pop()!;
    if (visited.has(id)) continue;
    visited.add(id);
    const chunk = graph.chunks.get(id);
    if (chunk) result.push(chunk);

    // Push neighbours in reverse order so we process them in natural edge order
    const neighbours = graph.edges
      .filter(e => e.from === id)
      .map(e => e.to)
      .filter(n => !visited.has(n))
      .reverse();
    stack.push(...neighbours);
  }
  return result;
}

/**
 * Finds the shortest path between `fromId` and `toId` using BFS.
 * Returns `undefined` if no path exists.
 */
export function shortestPath(
  graph: ChunkGraph,
  fromId: string,
  toId: string,
): PathResult | undefined {
  if (fromId === toId) {
    const chunk = graph.chunks.get(fromId);
    return chunk ? { path: [chunk], length: 0 } : undefined;
  }

  const visited = new Set<string>([fromId]);
  const queue: Array<string[]> = [[fromId]];

  while (queue.length > 0) {
    const pathSoFar = queue.shift()!;
    const current = pathSoFar[pathSoFar.length - 1];

    for (const edge of graph.edges) {
      if (edge.from !== current) continue;
      if (visited.has(edge.to)) continue;

      const newPath = [...pathSoFar, edge.to];

      if (edge.to === toId) {
        const chunks = newPath
          .map(id => graph.chunks.get(id))
          .filter((c): c is SemanticChunk => c !== undefined);
        return { path: chunks, length: chunks.length - 1 };
      }

      visited.add(edge.to);
      queue.push(newPath);
    }
  }
  return undefined;
}

/**
 * Finds the longest dependency chain in the graph (DAG only).
 * Falls back to the topological sort for cycle detection.
 * Returns the chain as a `PathResult`.
 */
export function longestPath(graph: ChunkGraph): PathResult {
  if (graph.size === 0) return { path: [], length: 0 };

  // Build adjacency list
  const adj = new Map<string, string[]>();
  for (const id of graph.chunks.keys()) adj.set(id, []);
  for (const edge of graph.edges) {
    if (graph.chunks.has(edge.from) && graph.chunks.has(edge.to)) {
      adj.get(edge.from)!.push(edge.to);
    }
  }

  const dist = new Map<string, number>();
  const prev = new Map<string, string>();
  for (const id of graph.chunks.keys()) dist.set(id, 0);

  // Process in topological order (skip cycles gracefully)
  const sorted = graph.topologicalSort(false);

  for (const chunk of sorted) {
    const d = dist.get(chunk.id) ?? 0;
    for (const neighbour of adj.get(chunk.id) ?? []) {
      if ((dist.get(neighbour) ?? 0) < d + 1) {
        dist.set(neighbour, d + 1);
        prev.set(neighbour, chunk.id);
      }
    }
  }

  // Find the node with max distance
  let maxDist = 0;
  let endId = sorted[0]?.id ?? '';
  for (const [id, d] of dist) {
    if (d > maxDist) { maxDist = d; endId = id; }
  }

  // Reconstruct path
  const path: SemanticChunk[] = [];
  let cur: string | undefined = endId;
  while (cur !== undefined) {
    const chunk = graph.chunks.get(cur);
    if (chunk) path.unshift(chunk);
    cur = prev.get(cur);
  }

  return { path, length: maxDist };
}

/**
 * Compute weakly connected components using Union-Find.
 * Two chunks are in the same component if there is any undirected path between them.
 * Returns an array of components, each being an array of chunks, sorted largest-first.
 */
export function connectedComponents(graph: ChunkGraph): SemanticChunk[][] {
  const parent = new Map<string, string>();
  for (const id of graph.chunks.keys()) parent.set(id, id);

  function find(id: string): string {
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root)!;
    // Path compression
    let cur = id;
    while (cur !== root) {
      const next = parent.get(cur)!;
      parent.set(cur, root);
      cur = next;
    }
    return root;
  }

  function union(a: string, b: string): void {
    parent.set(find(a), find(b));
  }

  for (const edge of graph.edges) {
    if (graph.chunks.has(edge.from) && graph.chunks.has(edge.to)) {
      union(edge.from, edge.to);
    }
  }

  const componentMap = new Map<string, SemanticChunk[]>();
  for (const chunk of graph.chunks.values()) {
    const root = find(chunk.id);
    if (!componentMap.has(root)) componentMap.set(root, []);
    componentMap.get(root)!.push(chunk);
  }

  return [...componentMap.values()].sort((a, b) => b.length - a.length);
}

// ─── Metrics ────────────────────────────────────────────────────────────────

/**
 * Compute aggregate metrics for a ChunkGraph.
 */
export function computeMetrics(graph: ChunkGraph): GraphMetrics {
  const n = graph.size;

  if (n === 0) {
    return {
      chunkCount: 0,
      edgeCount: 0,
      avgOutDegree: 0,
      avgInDegree: 0,
      density: 0,
      isolatedCount: 0,
      rootCount: 0,
      leafCount: 0,
      hasCycle: false,
    };
  }

  const inDegrees  = new Map<string, number>();
  const outDegrees = new Map<string, number>();
  for (const id of graph.chunks.keys()) {
    inDegrees.set(id, 0);
    outDegrees.set(id, 0);
  }
  for (const edge of graph.edges) {
    if (graph.chunks.has(edge.from) && graph.chunks.has(edge.to)) {
      outDegrees.set(edge.from, (outDegrees.get(edge.from) ?? 0) + 1);
      inDegrees.set(edge.to,    (inDegrees.get(edge.to)  ?? 0) + 1);
    }
  }

  let totalOut = 0, totalIn = 0, isolated = 0, roots = 0, leaves = 0;
  for (const id of graph.chunks.keys()) {
    const out   = outDegrees.get(id) ?? 0;
    const inDeg = inDegrees.get(id)  ?? 0;
    totalOut += out;
    totalIn  += inDeg;
    if (out === 0 && inDeg === 0) isolated++;
    if (out > 0 && inDeg === 0)   roots++;
    if (out === 0 && inDeg > 0)   leaves++;
  }

  const edgeCount = graph.edges.filter(
    e => graph.chunks.has(e.from) && graph.chunks.has(e.to),
  ).length;

  return {
    chunkCount: n,
    edgeCount,
    avgOutDegree: totalOut / n,
    avgInDegree:  totalIn  / n,
    density: n > 1 ? edgeCount / (n * (n - 1)) : 0,
    isolatedCount: isolated,
    rootCount: roots,
    leafCount: leaves,
    hasCycle: graph.hasCycle(),
  };
}

/** Re-export edge type for convenience. */
export type { ChunkEdge };
