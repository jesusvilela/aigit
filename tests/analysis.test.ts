import { ChunkGraph } from '../src/chunk/graph';
import { SemanticChunk, ChunkType, ChunkEdge } from '../src/chunk/types';
import {
  indegree, outdegree,
  findRoots, findLeaves,
  reachableFrom, impactOf,
  bfs, dfs,
  shortestPath, longestPath,
  connectedComponents, computeMetrics,
} from '../src/analysis/index';

function makeChunk(id: string): SemanticChunk {
  return {
    id, name: id, type: ChunkType.Function,
    filePath: 'test.ts', startLine: 1, endLine: 3,
    content: `function ${id}() {}`, contentHash: `h_${id}`, metadata: {},
  };
}

function makeGraph(
  ids: string[],
  edges: Array<[string, string]> = [],
): ChunkGraph {
  const g = new ChunkGraph(ids.map(makeChunk));
  for (const [from, to] of edges) {
    g.addEdge({ from, to, kind: 'calls' });
  }
  return g;
}

describe('indegree / outdegree', () => {
  test('isolated node has degree 0', () => {
    const g = makeGraph(['a']);
    expect(indegree(g, 'a')).toBe(0);
    expect(outdegree(g, 'a')).toBe(0);
  });

  test('correct degrees in a chain', () => {
    const g = makeGraph(['a', 'b', 'c'], [['a', 'b'], ['b', 'c']]);
    expect(outdegree(g, 'a')).toBe(1);
    expect(indegree(g, 'b')).toBe(1);
    expect(outdegree(g, 'b')).toBe(1);
    expect(indegree(g, 'c')).toBe(1);
    expect(outdegree(g, 'c')).toBe(0);
  });
});

describe('findRoots / findLeaves', () => {
  test('finds roots and leaves in a DAG', () => {
    const g = makeGraph(['a', 'b', 'c', 'd'], [['a', 'b'], ['a', 'c'], ['b', 'd'], ['c', 'd']]);
    const roots  = findRoots(g).map(c => c.id);
    const leaves = findLeaves(g).map(c => c.id);
    expect(roots).toContain('a');
    expect(roots).not.toContain('d');
    expect(leaves).toContain('d');
    expect(leaves).not.toContain('a');
  });

  test('isolated node is neither root nor leaf', () => {
    const g = makeGraph(['x']);
    // Root = in-degree=0 AND out-degree>0; Leaf = out-degree=0 AND in-degree>0
    // An isolated node (no edges) satisfies neither condition
    expect(findRoots(g)).toHaveLength(0);
    expect(findLeaves(g)).toHaveLength(0);
  });
});

describe('reachableFrom()', () => {
  test('returns all downstream nodes', () => {
    const g = makeGraph(['a', 'b', 'c', 'd'], [['a', 'b'], ['b', 'c'], ['b', 'd']]);
    const reachable = reachableFrom(g, 'a').map(c => c.id);
    expect(reachable).toContain('b');
    expect(reachable).toContain('c');
    expect(reachable).toContain('d');
    expect(reachable).not.toContain('a'); // start not included
  });

  test('no outgoing edges → empty result', () => {
    const g = makeGraph(['a', 'b']);
    expect(reachableFrom(g, 'a')).toHaveLength(0);
  });
});

describe('impactOf()', () => {
  test('returns all upstream dependents', () => {
    const g = makeGraph(['a', 'b', 'c'], [['a', 'c'], ['b', 'c']]);
    const impact = impactOf(g, 'c').map(x => x.id);
    expect(impact).toContain('a');
    expect(impact).toContain('b');
    expect(impact).not.toContain('c');
  });

  test('isolated node → empty impact', () => {
    const g = makeGraph(['a']);
    expect(impactOf(g, 'a')).toHaveLength(0);
  });
});

describe('bfs()', () => {
  test('traverses in breadth-first order', () => {
    const g = makeGraph(['a', 'b', 'c', 'd'], [['a', 'b'], ['a', 'c'], ['b', 'd']]);
    const order = bfs(g, 'a').map(c => c.id);
    expect(order[0]).toBe('a');
    // b and c must appear before d
    expect(order.indexOf('b')).toBeLessThan(order.indexOf('d'));
    expect(order.indexOf('c')).toBeLessThan(order.indexOf('d'));
  });

  test('returns empty for unknown start id', () => {
    const g = makeGraph(['a']);
    expect(bfs(g, 'x')).toHaveLength(0);
  });
});

describe('dfs()', () => {
  test('traverses in depth-first order from start', () => {
    const g = makeGraph(['a', 'b', 'c'], [['a', 'b'], ['b', 'c']]);
    const order = dfs(g, 'a').map(c => c.id);
    expect(order[0]).toBe('a');
    expect(order).toContain('b');
    expect(order).toContain('c');
  });

  test('returns empty for unknown start id', () => {
    const g = makeGraph(['a']);
    expect(dfs(g, 'z')).toHaveLength(0);
  });
});

describe('shortestPath()', () => {
  test('finds path in a chain', () => {
    const g = makeGraph(['a', 'b', 'c', 'd'], [['a', 'b'], ['b', 'c'], ['c', 'd']]);
    const result = shortestPath(g, 'a', 'd');
    expect(result).toBeDefined();
    expect(result?.path.map(c => c.id)).toEqual(['a', 'b', 'c', 'd']);
    expect(result?.length).toBe(3);
  });

  test('returns undefined when no path exists', () => {
    const g = makeGraph(['a', 'b']); // no edges
    expect(shortestPath(g, 'a', 'b')).toBeUndefined();
  });

  test('from === to returns path of length 0', () => {
    const g = makeGraph(['a']);
    const result = shortestPath(g, 'a', 'a');
    expect(result?.length).toBe(0);
    expect(result?.path).toHaveLength(1);
  });

  test('finds shorter path when multiple routes exist', () => {
    // a→b→c (length 2) vs a→c (length 1)
    const g = makeGraph(['a', 'b', 'c'], [['a', 'b'], ['b', 'c'], ['a', 'c']]);
    const result = shortestPath(g, 'a', 'c');
    expect(result?.length).toBe(1);
    expect(result?.path.map(x => x.id)).toEqual(['a', 'c']);
  });
});

describe('longestPath()', () => {
  test('returns empty for empty graph', () => {
    const g = makeGraph([]);
    expect(longestPath(g).path).toHaveLength(0);
    expect(longestPath(g).length).toBe(0);
  });

  test('finds longest chain', () => {
    const g = makeGraph(['a', 'b', 'c', 'd'], [['a', 'b'], ['b', 'c'], ['c', 'd']]);
    const result = longestPath(g);
    expect(result.length).toBe(3);
    expect(result.path.map(c => c.id)).toEqual(['a', 'b', 'c', 'd']);
  });

  test('isolated nodes → path of length 0', () => {
    const g = makeGraph(['a', 'b', 'c']);
    const result = longestPath(g);
    expect(result.length).toBe(0);
  });
});

describe('connectedComponents()', () => {
  test('connected graph → one component', () => {
    const g = makeGraph(['a', 'b', 'c'], [['a', 'b'], ['b', 'c']]);
    const comps = connectedComponents(g);
    expect(comps).toHaveLength(1);
    expect(comps[0]).toHaveLength(3);
  });

  test('disconnected graph → multiple components', () => {
    const g = makeGraph(['a', 'b', 'c', 'd'], [['a', 'b']]);
    const comps = connectedComponents(g);
    expect(comps.length).toBeGreaterThanOrEqual(2);
  });

  test('empty graph → empty', () => {
    const g = makeGraph([]);
    expect(connectedComponents(g)).toHaveLength(0);
  });

  test('components sorted largest first', () => {
    const g = makeGraph(['a', 'b', 'c', 'd', 'e'], [['a', 'b'], ['b', 'c']]);
    const comps = connectedComponents(g);
    for (let i = 1; i < comps.length; i++) {
      expect(comps[i - 1].length).toBeGreaterThanOrEqual(comps[i].length);
    }
  });
});

describe('computeMetrics()', () => {
  test('empty graph produces zero metrics', () => {
    const m = computeMetrics(makeGraph([]));
    expect(m.chunkCount).toBe(0);
    expect(m.edgeCount).toBe(0);
    expect(m.density).toBe(0);
    expect(m.hasCycle).toBe(false);
  });

  test('single isolated node', () => {
    const m = computeMetrics(makeGraph(['a']));
    expect(m.chunkCount).toBe(1);
    expect(m.edgeCount).toBe(0);
    expect(m.isolatedCount).toBe(1);
    expect(m.rootCount).toBe(0);
    expect(m.leafCount).toBe(0);
  });

  test('simple chain metrics', () => {
    const m = computeMetrics(makeGraph(['a', 'b', 'c'], [['a', 'b'], ['b', 'c']]));
    expect(m.chunkCount).toBe(3);
    expect(m.edgeCount).toBe(2);
    expect(m.rootCount).toBe(1); // a
    expect(m.leafCount).toBe(1); // c
    expect(m.isolatedCount).toBe(0);
    expect(m.hasCycle).toBe(false);
  });

  test('cycle detected in metrics', () => {
    const m = computeMetrics(makeGraph(['a', 'b'], [['a', 'b'], ['b', 'a']]));
    expect(m.hasCycle).toBe(true);
  });

  test('density is bounded [0, 1] for a complete graph', () => {
    // Complete graph of 3 nodes: 6 edges, density = 6/(3*2) = 1
    const g = makeGraph(['a', 'b', 'c'], [
      ['a', 'b'], ['a', 'c'],
      ['b', 'a'], ['b', 'c'],
      ['c', 'a'], ['c', 'b'],
    ]);
    const m = computeMetrics(g);
    expect(m.density).toBeCloseTo(1.0);
  });
});
