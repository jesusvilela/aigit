import { ChunkGraph } from '../src/chunk/graph';
import { SemanticChunk, ChunkType } from '../src/chunk/types';
import { search, searchMany, levenshtein, tokenSimilarity } from '../src/search/engine';
import { SearchQuery } from '../src/search/types';

function makeChunk(
  id: string,
  name: string,
  type: ChunkType = ChunkType.Function,
  content = '',
  filePath = 'test.ts',
  metadata: Record<string, unknown> = {},
): SemanticChunk {
  return {
    id, name, type, filePath,
    startLine: 1, endLine: 5,
    content: content || `function ${name}() {}`,
    contentHash: `hash_${id}`,
    metadata,
  };
}

describe('levenshtein()', () => {
  test('identical strings → 0', () => expect(levenshtein('foo', 'foo')).toBe(0));
  test('empty vs non-empty', () => expect(levenshtein('', 'abc')).toBe(3));
  test('single char substitution', () => expect(levenshtein('a', 'b')).toBe(1));
  test('insertion', () => expect(levenshtein('abc', 'abcd')).toBe(1));
  test('deletion', () => expect(levenshtein('abcd', 'abc')).toBe(1));
  test('kitten → sitting = 3', () => expect(levenshtein('kitten', 'sitting')).toBe(3));
  test('symmetry', () => expect(levenshtein('abc', 'xyz')).toBe(levenshtein('xyz', 'abc')));
});

describe('tokenSimilarity()', () => {
  test('identical strings → 1', () => expect(tokenSimilarity('foo bar', 'foo bar')).toBe(1));
  test('completely different → 0', () => expect(tokenSimilarity('foo', 'bar')).toBe(0));
  test('partial overlap is between 0 and 1', () => {
    const s = tokenSimilarity('function foo(a, b)', 'function bar(a, c)');
    expect(s).toBeGreaterThan(0);
    expect(s).toBeLessThan(1);
  });
  test('empty strings → 1', () => expect(tokenSimilarity('', '')).toBe(1));
});

describe('search()', () => {
  let graph: ChunkGraph;

  beforeEach(() => {
    graph = new ChunkGraph([
      makeChunk('a', 'getUser',    ChunkType.Function, 'return db.find(id)', 'src/user.ts'),
      makeChunk('b', 'createUser', ChunkType.Function, 'db.insert(user)',    'src/user.ts'),
      makeChunk('c', 'UserService',ChunkType.Class,    'class UserService{}','src/user.ts'),
      makeChunk('d', 'IUser',      ChunkType.Interface,'interface IUser {}', 'src/types.ts'),
      makeChunk('e', 'config',     ChunkType.Variable, 'const config = {}',  'src/config.ts'),
    ]);
  });

  test('filter by type', () => {
    const results = search(graph, { type: ChunkType.Function });
    expect(results).toHaveLength(2);
    results.forEach(r => expect(r.chunk.type).toBe(ChunkType.Function));
  });

  test('filter by type array', () => {
    const results = search(graph, { type: [ChunkType.Function, ChunkType.Class] });
    expect(results).toHaveLength(3);
  });

  test('filter by name substring (case-insensitive)', () => {
    const results = search(graph, { name: 'user' });
    expect(results.length).toBeGreaterThan(0);
    results.forEach(r => expect(r.chunk.name.toLowerCase()).toContain('user'));
  });

  test('filter by filePath', () => {
    const results = search(graph, { filePath: 'user.ts' });
    expect(results.length).toBe(3);
    results.forEach(r => expect(r.chunk.filePath).toContain('user'));
  });

  test('filter by contentPattern', () => {
    const results = search(graph, { contentPattern: 'db.' });
    expect(results.length).toBe(2);
  });

  test('filter by startLineMin/Max', () => {
    // All chunks have startLine=1; filtering for >= 2 should return nothing
    expect(search(graph, { startLineMin: 2 })).toHaveLength(0);
    expect(search(graph, { startLineMax: 1 })).toHaveLength(5);
  });

  test('filter by metadata', () => {
    const g = new ChunkGraph([
      makeChunk('x', 'MyEnum', ChunkType.Variable, '', 'f.ts', { isEnum: true }),
      makeChunk('y', 'MyAlias',ChunkType.Variable, '', 'f.ts', { isTypeAlias: true }),
    ]);
    const enums = search(g, { metadata: { isEnum: true } });
    expect(enums).toHaveLength(1);
    expect(enums[0].chunk.name).toBe('MyEnum');
  });

  test('fuzzy name match within distance', () => {
    const results = search(graph, { name: 'getUzer', fuzzyDistance: 2 });
    expect(results.length).toBeGreaterThan(0);
    expect(results[0].chunk.name).toBe('getUser');
  });

  test('fuzzy name match excludes chunks too far away', () => {
    const results = search(graph, { name: 'xyz', fuzzyDistance: 1 });
    expect(results).toHaveLength(0);
  });

  test('limit caps results', () => {
    const results = search(graph, { limit: 2 });
    expect(results).toHaveLength(2);
  });

  test('results sorted by score descending', () => {
    const results = search(graph, { name: 'getUser' });
    for (let i = 1; i < results.length; i++) {
      expect(results[i - 1].score).toBeGreaterThanOrEqual(results[i].score);
    }
  });

  test('exact name match scores 1', () => {
    const results = search(graph, { name: 'getUser' });
    expect(results[0].score).toBe(1.0);
    expect(results[0].chunk.name).toBe('getUser');
  });

  test('empty graph returns empty results', () => {
    const empty = new ChunkGraph();
    expect(search(empty, { name: 'foo' })).toHaveLength(0);
  });

  test('no query filters → all chunks returned', () => {
    const results = search(graph, {});
    expect(results).toHaveLength(5);
  });
});

describe('searchMany()', () => {
  test('searches across multiple graphs, deduplicates by id', () => {
    const chunk = makeChunk('a', 'foo', ChunkType.Function);
    const g1 = new ChunkGraph([chunk]);
    const g2 = new ChunkGraph([chunk, makeChunk('b', 'bar', ChunkType.Function)]);
    const results = searchMany([g1, g2], { type: ChunkType.Function });
    expect(results).toHaveLength(2); // 'a' deduped
  });

  test('respects limit across graphs', () => {
    const g1 = new ChunkGraph([makeChunk('a', 'foo'), makeChunk('b', 'bar')]);
    const g2 = new ChunkGraph([makeChunk('c', 'baz'), makeChunk('d', 'qux')]);
    const results = searchMany([g1, g2], { limit: 2 });
    expect(results).toHaveLength(2);
  });
});
