import { parse } from '../src/chunk/parser';
import { ChunkGraph } from '../src/chunk/graph';
import { ChunkType, SemanticChunk, ChunkEdge } from '../src/chunk/types';

describe('Parser', () => {
  test('parses TypeScript with function, class, import', () => {
    const content = `
import { foo } from './foo';

function hello(name: string): string {
  return 'hello ' + name;
}

class MyClass {
  method(): void {
    console.log('hi');
  }
}
`;
    const chunks = parse(content, 'test.ts');
    const types = chunks.map(c => c.type);
    expect(types).toContain(ChunkType.Import);
    expect(types).toContain(ChunkType.Function);
    expect(types).toContain(ChunkType.Class);
    const fn = chunks.find(c => c.name === 'hello');
    expect(fn).toBeDefined();
    expect(fn?.type).toBe(ChunkType.Function);
  });

  test('parses Python with def and class', () => {
    const content = `
import os
from sys import argv

def greet(name):
    return f"hello {name}"

class MyClass:
    def method(self):
        pass
`;
    const chunks = parse(content, 'test.py');
    const types = chunks.map(c => c.type);
    expect(types).toContain(ChunkType.Import);
    expect(types).toContain(ChunkType.Function);
    expect(types).toContain(ChunkType.Class);
    const fn = chunks.find(c => c.name === 'greet');
    expect(fn).toBeDefined();
  });

  test('returns empty array for empty content', () => {
    const chunks = parse('', 'empty.ts');
    expect(chunks).toEqual([]);
  });

  test('IDs are deterministic', () => {
    const content = `function foo() { return 1; }`;
    const chunks1 = parse(content, 'file.ts');
    const chunks2 = parse(content, 'file.ts');
    expect(chunks1[0].id).toBe(chunks2[0].id);
    expect(chunks1[0].contentHash).toBe(chunks2[0].contentHash);
  });
});

describe('ChunkGraph', () => {
  function makeChunk(id: string, name: string): SemanticChunk {
    return {
      id,
      name,
      type: ChunkType.Function,
      filePath: 'test.ts',
      startLine: 1,
      endLine: 5,
      content: `function ${name}() {}`,
      contentHash: 'hash_' + id,
      metadata: {},
    };
  }

  test('addChunk and getChunk', () => {
    const graph = new ChunkGraph();
    const chunk = makeChunk('a', 'funcA');
    graph.addChunk(chunk);
    expect(graph.getChunk('a')).toEqual(chunk);
  });

  test('getNeighbors returns correct chunks', () => {
    const graph = new ChunkGraph();
    const a = makeChunk('a', 'funcA');
    const b = makeChunk('b', 'funcB');
    const c = makeChunk('c', 'funcC');
    graph.addChunk(a);
    graph.addChunk(b);
    graph.addChunk(c);
    graph.addEdge({ from: 'a', to: 'b', kind: 'calls' });
    graph.addEdge({ from: 'c', to: 'a', kind: 'calls' });
    
    const outgoing = graph.getNeighbors('a', 'outgoing');
    expect(outgoing.map(n => n.id)).toContain('b');
    
    const incoming = graph.getNeighbors('a', 'incoming');
    expect(incoming.map(n => n.id)).toContain('c');
    
    const both = graph.getNeighbors('a', 'both');
    expect(both.map(n => n.id)).toContain('b');
    expect(both.map(n => n.id)).toContain('c');
  });

  test('topologicalSort', () => {
    const graph = new ChunkGraph();
    const a = makeChunk('a', 'funcA');
    const b = makeChunk('b', 'funcB');
    const c = makeChunk('c', 'funcC');
    graph.addChunk(a);
    graph.addChunk(b);
    graph.addChunk(c);
    graph.addEdge({ from: 'a', to: 'b', kind: 'calls' });
    graph.addEdge({ from: 'b', to: 'c', kind: 'calls' });
    const sorted = graph.topologicalSort();
    const ids = sorted.map(c => c.id);
    expect(ids.indexOf('a')).toBeLessThan(ids.indexOf('b'));
    expect(ids.indexOf('b')).toBeLessThan(ids.indexOf('c'));
  });

  test('toJSON and fromJSON roundtrip', () => {
    const graph = new ChunkGraph();
    const a = makeChunk('a', 'funcA');
    const b = makeChunk('b', 'funcB');
    graph.addChunk(a);
    graph.addChunk(b);
    graph.addEdge({ from: 'a', to: 'b', kind: 'calls' });
    const json = graph.toJSON();
    const restored = ChunkGraph.fromJSON(json);
    expect(restored.getChunk('a')).toEqual(a);
    expect(restored.getChunk('b')).toEqual(b);
    expect(restored.edges).toEqual(graph.edges);
  });
});
