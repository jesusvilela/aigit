import { ChunkGraph } from '../chunk/graph';
import { SemanticChunk, ChunkType } from '../chunk/types';
import { SearchQuery, SearchResult } from './types';

/**
 * Compute the Levenshtein edit distance between two strings.
 * The algorithm runs in O(m*n) time and O(min(m,n)) space.
 */
export function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;

  const shorter = a.length <= b.length ? a : b;
  const longer  = a.length <= b.length ? b : a;

  let prev = Array.from({ length: shorter.length + 1 }, (_, i) => i);
  let curr = new Array<number>(shorter.length + 1);

  for (let i = 1; i <= longer.length; i++) {
    curr[0] = i;
    for (let j = 1; j <= shorter.length; j++) {
      const cost = longer[i - 1] === shorter[j - 1] ? 0 : 1;
      curr[j] = Math.min(
        prev[j] + 1,
        curr[j - 1] + 1,
        prev[j - 1] + cost,
      );
    }
    [prev, curr] = [curr, prev];
  }
  return prev[shorter.length];
}

/**
 * Compute a Jaccard-based token similarity score between two strings.
 * Returns a value in [0, 1] where 1 means identical.
 */
export function tokenSimilarity(a: string, b: string): number {
  const tokenise = (s: string): Set<string> =>
    new Set(s.toLowerCase().split(/[\s,;(){}[\]<>|&+\-*/=!@#^~`?:"'\\]+/).filter(t => t.length > 0));

  const setA = tokenise(a);
  const setB = tokenise(b);
  if (setA.size === 0 && setB.size === 0) return 1;
  if (setA.size === 0 || setB.size === 0) return 0;

  let intersection = 0;
  for (const t of setA) {
    if (setB.has(t)) intersection++;
  }
  return intersection / (setA.size + setB.size - intersection);
}

function matchesType(chunk: SemanticChunk, type: ChunkType | ChunkType[]): boolean {
  if (Array.isArray(type)) return type.includes(chunk.type);
  return chunk.type === type;
}

function matchesMetadata(chunk: SemanticChunk, metadata: Record<string, unknown>): boolean {
  for (const [key, value] of Object.entries(metadata)) {
    if (chunk.metadata[key] !== value) return false;
  }
  return true;
}

/**
 * Search a `ChunkGraph` using a `SearchQuery`.
 *
 * Results are sorted descending by relevance score and optionally capped by
 * `query.limit`. A score of 1.0 indicates a perfect match on all provided
 * criteria; 0.0 indicates the chunk survived hard filters but had no positive
 * scoring signals.
 */
export function search(graph: ChunkGraph, query: SearchQuery): SearchResult[] {
  const results: SearchResult[] = [];

  for (const chunk of graph.chunks.values()) {
    // ── Hard filters (exclusion) ─────────────────────────────────────────────

    if (query.type !== undefined && !matchesType(chunk, query.type)) continue;

    if (query.filePath !== undefined &&
        !chunk.filePath.toLowerCase().includes(query.filePath.toLowerCase())) continue;

    if (query.contentPattern !== undefined &&
        !chunk.content.toLowerCase().includes(query.contentPattern.toLowerCase())) continue;

    if (query.startLineMin !== undefined && chunk.startLine < query.startLineMin) continue;
    if (query.startLineMax !== undefined && chunk.startLine > query.startLineMax) continue;

    if (query.metadata !== undefined && !matchesMetadata(chunk, query.metadata)) continue;

    // ── Fuzzy name filter ────────────────────────────────────────────────────

    if (query.fuzzyDistance !== undefined && query.name !== undefined) {
      const dist = levenshtein(
        chunk.name.toLowerCase(),
        query.name.toLowerCase(),
      );
      if (dist > query.fuzzyDistance) continue;
    } else if (query.name !== undefined) {
      if (!chunk.name.toLowerCase().includes(query.name.toLowerCase())) continue;
    }

    // ── Scoring ──────────────────────────────────────────────────────────────

    let score = 0;
    let signals = 0;

    if (query.name !== undefined) {
      const lower = chunk.name.toLowerCase();
      const qLower = query.name.toLowerCase();

      if (lower === qLower) {
        score += 1.0;
      } else if (lower.startsWith(qLower) || lower.endsWith(qLower)) {
        score += 0.8;
      } else if (query.fuzzyDistance !== undefined) {
        const dist = levenshtein(lower, qLower);
        const maxDist = Math.max(lower.length, qLower.length);
        score += maxDist > 0 ? 1 - dist / maxDist : 1;
      } else {
        score += 0.5;
      }
      signals++;
    }

    if (query.contentPattern !== undefined) {
      // Count occurrences — more occurrences → higher relevance
      const haystack = chunk.content.toLowerCase();
      const needle   = query.contentPattern.toLowerCase();
      let count = 0;
      let pos = -1;
      while ((pos = haystack.indexOf(needle, pos + 1)) !== -1) count++;
      score += Math.min(count / 5, 1.0);
      signals++;
    }

    if (query.filePath !== undefined) {
      score += chunk.filePath.toLowerCase() === query.filePath.toLowerCase() ? 1.0 : 0.5;
      signals++;
    }

    results.push({
      chunk,
      score: signals > 0 ? score / signals : 0,
    });
  }

  results.sort((a, b) => b.score - a.score);

  return query.limit !== undefined ? results.slice(0, query.limit) : results;
}

/**
 * Search across multiple ChunkGraphs simultaneously.
 * Useful for searching across all snapshots or all open files.
 */
export function searchMany(
  graphs: ChunkGraph[],
  query: SearchQuery,
): SearchResult[] {
  const seen = new Set<string>();
  const combined: SearchResult[] = [];

  for (const g of graphs) {
    for (const r of search(g, query)) {
      if (!seen.has(r.chunk.id)) {
        seen.add(r.chunk.id);
        combined.push(r);
      }
    }
  }

  combined.sort((a, b) => b.score - a.score);
  return query.limit !== undefined ? combined.slice(0, query.limit) : combined;
}
