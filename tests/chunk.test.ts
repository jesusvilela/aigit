import { parse } from '../src/chunk/parser';
import { ChunkGraph } from '../src/chunk/graph';
import { ChunkType, SemanticChunk, ChunkEdge } from '../src/chunk/types';
import { GraphCycleError } from '../src/errors';

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

  test('returns empty array for whitespace-only content', () => {
    const chunks = parse('   \n\n  ', 'blank.ts');
    expect(chunks).toEqual([]);
  });

  test('returns empty array for unsupported extension', () => {
    const chunks = parse('fn main() {}', 'main.go');
    expect(chunks).toEqual([]);
  });

  test('IDs are deterministic', () => {
    const content = `function foo() { return 1; }`;
    const chunks1 = parse(content, 'file.ts');
    const chunks2 = parse(content, 'file.ts');
    expect(chunks1[0].id).toBe(chunks2[0].id);
    expect(chunks1[0].contentHash).toBe(chunks2[0].contentHash);
  });

  test('same name different file → different id', () => {
    const content = `function foo() { return 1; }`;
    const chunks1 = parse(content, 'a.ts');
    const chunks2 = parse(content, 'b.ts');
    expect(chunks1[0].id).not.toBe(chunks2[0].id);
  });

  test('parses export default function', () => {
    const content = `export default function handler(req, res) { res.send('ok'); }`;
    const chunks = parse(content, 'handler.ts');
    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks[0].type).toBe(ChunkType.Function);
  });

  test('parses TypeScript type alias', () => {
    const content = `export type UserId = string;`;
    const chunks = parse(content, 'types.ts');
    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks[0].type).toBe(ChunkType.Variable);
    expect(chunks[0].metadata?.isTypeAlias).toBe(true);
  });

  test('parses interface with generics', () => {
    const content = `
export interface Repository<T> {
  findById(id: string): Promise<T>;
  save(item: T): Promise<void>;
}
`;
    const chunks = parse(content, 'repo.ts');
    const iface = chunks.find(c => c.type === ChunkType.Interface);
    expect(iface).toBeDefined();
    expect(iface?.name).toBe('Repository');
  });

  test('parses async Python function', () => {
    const content = `
async def fetch_data(url):
    return await http.get(url)
`;
    const chunks = parse(content, 'api.py');
    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks[0].type).toBe(ChunkType.Function);
    expect(chunks[0].name).toBe('fetch_data');
  });

  test('parses multi-line import', () => {
    const content = `
import {
  alpha,
  beta,
  gamma,
} from './module';
`;
    const chunks = parse(content, 'imports.ts');
    const importChunk = chunks.find(c => c.type === ChunkType.Import);
    expect(importChunk).toBeDefined();
    expect(importChunk?.content).toContain('alpha');
  });

  test('parses TypeScript enum', () => {
    const content = `
export enum Status {
  Active = 'active',
  Inactive = 'inactive',
  Pending = 'pending',
}
`;
    const chunks = parse(content, 'status.ts');
    const enumChunk = chunks.find(c => c.name === 'Status');
    expect(enumChunk).toBeDefined();
    expect(enumChunk?.metadata?.isEnum).toBe(true);
  });

  test('parses const enum', () => {
    const content = `export const enum Direction { Up, Down, Left, Right }`;
    const chunks = parse(content, 'dir.ts');
    const enumChunk = chunks.find(c => c.metadata?.isEnum === true);
    expect(enumChunk).toBeDefined();
    expect(enumChunk?.name).toBe('Direction');
  });

  test('parses decorator on class', () => {
    const content = `
@Injectable()
class UserService {
  get(): void {}
}
`;
    const chunks = parse(content, 'user.ts');
    const cls = chunks.find(c => c.type === ChunkType.Class);
    expect(cls).toBeDefined();
    expect(cls?.metadata?.decorators).toBeDefined();
    expect((cls?.metadata?.decorators as string[])).toContain('Injectable');
  });

  test('line ranges are 1-based', () => {
    const content = `function foo() {\n  return 1;\n}`;
    const chunks = parse(content, 'foo.ts');
    expect(chunks[0].startLine).toBeGreaterThanOrEqual(1);
    expect(chunks[0].endLine).toBeGreaterThanOrEqual(chunks[0].startLine);
  });

  test('decorator followed by unrecognised code does not propagate to next class', () => {
    // A decorator followed by something that isn't a class/function
    // should not attach decorators to a later class
    const content = `
@Service()
const config = { value: 42 };

class Plain {
  run() {}
}
`;
    const chunks = parse(content, 'plain.ts');
    const cls = chunks.find(c => c.type === ChunkType.Class);
    // Decorators should have been consumed/cleared by the time we reach Plain
    const decorators = cls?.metadata?.decorators as string[] | undefined;
    expect(decorators).toBeUndefined();
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

  test('size reflects number of chunks', () => {
    const graph = new ChunkGraph([makeChunk('a', 'funcA'), makeChunk('b', 'funcB')]);
    expect(graph.size).toBe(2);
    graph.addChunk(makeChunk('c', 'funcC'));
    expect(graph.size).toBe(3);
  });

  test('hasChunk returns true/false correctly', () => {
    const graph = new ChunkGraph([makeChunk('a', 'funcA')]);
    expect(graph.hasChunk('a')).toBe(true);
    expect(graph.hasChunk('z')).toBe(false);
  });

  test('removeChunk removes chunk and its edges', () => {
    const graph = new ChunkGraph(
      [makeChunk('a', 'funcA'), makeChunk('b', 'funcB')],
      [{ from: 'a', to: 'b', kind: 'calls' }],
    );
    const removed = graph.removeChunk('a');
    expect(removed).toBe(true);
    expect(graph.hasChunk('a')).toBe(false);
    expect(graph.edges.length).toBe(0);
  });

  test('removeChunk returns false for non-existent id', () => {
    const graph = new ChunkGraph();
    expect(graph.removeChunk('nonexistent')).toBe(false);
  });

  test('getEdgesFrom / getEdgesTo', () => {
    const graph = new ChunkGraph(
      [makeChunk('a', 'A'), makeChunk('b', 'B'), makeChunk('c', 'C')],
      [
        { from: 'a', to: 'b', kind: 'calls' },
        { from: 'a', to: 'c', kind: 'calls' },
        { from: 'b', to: 'c', kind: 'uses' },
      ],
    );
    expect(graph.getEdgesFrom('a')).toHaveLength(2);
    expect(graph.getEdgesTo('c')).toHaveLength(2);
    expect(graph.getEdgesFrom('c')).toHaveLength(0);
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

  test('topologicalSort on empty graph returns empty array', () => {
    const graph = new ChunkGraph();
    expect(graph.topologicalSort()).toEqual([]);
  });

  test('topologicalSort includes all chunks even without edges', () => {
    const graph = new ChunkGraph([makeChunk('x', 'X'), makeChunk('y', 'Y')]);
    expect(graph.topologicalSort()).toHaveLength(2);
  });

  test('hasCycle detects cycle', () => {
    const graph = new ChunkGraph(
      [makeChunk('a', 'A'), makeChunk('b', 'B'), makeChunk('c', 'C')],
      [
        { from: 'a', to: 'b', kind: 'calls' },
        { from: 'b', to: 'c', kind: 'calls' },
        { from: 'c', to: 'a', kind: 'calls' }, // cycle
      ],
    );
    expect(graph.hasCycle()).toBe(true);
  });

  test('hasCycle returns false for DAG', () => {
    const graph = new ChunkGraph(
      [makeChunk('a', 'A'), makeChunk('b', 'B'), makeChunk('c', 'C')],
      [
        { from: 'a', to: 'b', kind: 'calls' },
        { from: 'b', to: 'c', kind: 'calls' },
      ],
    );
    expect(graph.hasCycle()).toBe(false);
  });

  test('topologicalSort with strict=true throws GraphCycleError on cycle', () => {
    const graph = new ChunkGraph(
      [makeChunk('a', 'A'), makeChunk('b', 'B')],
      [
        { from: 'a', to: 'b', kind: 'calls' },
        { from: 'b', to: 'a', kind: 'calls' }, // cycle
      ],
    );
    expect(() => graph.topologicalSort(true)).toThrow(GraphCycleError);
  });

  test('topologicalSort without strict degrades gracefully on cycle', () => {
    const graph = new ChunkGraph(
      [makeChunk('a', 'A'), makeChunk('b', 'B')],
      [
        { from: 'a', to: 'b', kind: 'calls' },
        { from: 'b', to: 'a', kind: 'calls' },
      ],
    );
    const sorted = graph.topologicalSort(false);
    expect(sorted).toHaveLength(2);
  });

  test('subgraph contains only specified chunks and their edges', () => {
    const graph = new ChunkGraph(
      [makeChunk('a', 'A'), makeChunk('b', 'B'), makeChunk('c', 'C')],
      [
        { from: 'a', to: 'b', kind: 'calls' },
        { from: 'b', to: 'c', kind: 'calls' },
        { from: 'a', to: 'c', kind: 'uses' },
      ],
    );
    const sub = graph.subgraph(['a', 'b']);
    expect(sub.size).toBe(2);
    expect(sub.hasChunk('c')).toBe(false);
    expect(sub.edges).toHaveLength(1); // only a→b
    expect(sub.edges[0]).toEqual({ from: 'a', to: 'b', kind: 'calls' });
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
