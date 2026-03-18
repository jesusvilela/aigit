import * as crypto from 'crypto';
import { SemanticChunk, ChunkType } from './types';

function sha1(input: string): string {
  return crypto.createHash('sha1').update(input).digest('hex');
}

function makeId(filePath: string, name: string, type: ChunkType): string {
  return sha1(`${filePath}:${name}:${type}`);
}

function makeContentHash(content: string): string {
  return sha1(content);
}

function extractBracedBody(lines: string[], startLineIndex: number): { endLineIndex: number; content: string } {
  let braceDepth = 0;
  let started = false;
  let endLineIndex = startLineIndex;

  for (let i = startLineIndex; i < lines.length; i++) {
    const line = lines[i];
    for (const ch of line) {
      if (ch === '{') {
        braceDepth++;
        started = true;
      } else if (ch === '}') {
        braceDepth--;
        if (started && braceDepth === 0) {
          endLineIndex = i;
          return {
            endLineIndex,
            content: lines.slice(startLineIndex, endLineIndex + 1).join('\n'),
          };
        }
      }
    }
  }
  endLineIndex = lines.length - 1;
  return {
    endLineIndex,
    content: lines.slice(startLineIndex, endLineIndex + 1).join('\n'),
  };
}

function parseJsTs(content: string, filePath: string): SemanticChunk[] {
  const chunks: SemanticChunk[] = [];
  const lines = content.split('\n');

  const consumed = new Set<number>();

  // Multi-line import: starts with `import` and ends with `;` possibly spanning lines
  const importStartRe = /^(?:export\s+)?(?:import\s+)/;
  const singleImportRe = /^(?:export\s+)?(?:import\s+.+?from\s+['"][^'"]+['"]|import\s+['"][^'"]+['"])\s*;?\s*$/;

  function isMultiLineImportStart(trimmed: string): boolean {
    return (
      importStartRe.test(trimmed) &&
      !singleImportRe.test(trimmed) &&
      trimmed.includes('{') &&
      !trimmed.includes('}')
    );
  }
  const functionDeclRe = /^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*(\w+)?\s*[(<]/;
  const arrowFnRe = /^(?:export\s+)?(?:const|let)\s+(\w+)\s*(?::[^=]*)?\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=]+)\s*=>/;
  const classDeclRe = /^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+[\w<>, ]+)?(?:\s+implements\s+[\w<>,\s]+)?\s*\{?/;
  const interfaceDeclRe = /^(?:export\s+)?interface\s+(\w+)(?:\s*<[^>]*>)?(?:\s+extends\s+[\w<>,\s]+)?\s*\{?/;
  const typeAliasDeclRe = /^(?:export\s+)?type\s+(\w+)(?:\s*<[^>]*>)?\s*=/;
  const varDeclRe = /^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::\s*[\w<>[\]|&,\s]+)?\s*=/;
  const methodRe = /^\s{2,}(?:(?:public|private|protected|static|async|readonly|override|abstract)\s+)*(\w+)\s*(?:<[^>]*>)?\s*[(<][^=]*\)\s*(?::\s*[\w<>[\]|&,\s]+)?\s*\{/;

  let i = 0;
  while (i < lines.length) {
    if (consumed.has(i)) { i++; continue; }
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed || trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) {
      i++;
      continue;
    }

    // Multi-line or single-line import
    if (isMultiLineImportStart(trimmed)) {
      // Multi-line import: scan until we find the closing `}`
      let endI = i;
      while (endI < lines.length && !lines[endI].includes('}')) endI++;
      // Keep going until we find the `;`
      while (endI < lines.length && !lines[endI].includes(';')) endI++;
      const chunkContent = lines.slice(i, endI + 1).join('\n');
      const name = `import_${i}`;
      for (let j = i; j <= endI; j++) consumed.add(j);
      chunks.push({
        id: makeId(filePath, name, ChunkType.Import),
        name,
        type: ChunkType.Import,
        filePath,
        startLine: i + 1,
        endLine: endI + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      i = endI + 1;
      continue;
    }

    // Single-line import
    if (singleImportRe.test(trimmed)) {
      const chunkContent = line;
      const name = `import_${i}`;
      chunks.push({
        id: makeId(filePath, name, ChunkType.Import),
        name,
        type: ChunkType.Import,
        filePath,
        startLine: i + 1,
        endLine: i + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      consumed.add(i);
      i++;
      continue;
    }

    // Type alias
    const typeAliasMatch = trimmed.match(typeAliasDeclRe);
    if (typeAliasMatch) {
      const name = typeAliasMatch[1];
      let endI = i;
      // Type aliases end with `;`
      while (endI < lines.length - 1 && !lines[endI].includes(';')) endI++;
      const chunkContent = lines.slice(i, endI + 1).join('\n');
      for (let j = i; j <= endI; j++) consumed.add(j);
      chunks.push({
        id: makeId(filePath, name, ChunkType.Variable),
        name,
        type: ChunkType.Variable,
        filePath,
        startLine: i + 1,
        endLine: endI + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: { isTypeAlias: true },
      });
      i = endI + 1;
      continue;
    }

    // Interface
    const interfaceMatch = trimmed.match(interfaceDeclRe);
    if (interfaceMatch) {
      const name = interfaceMatch[1];
      const { endLineIndex, content: chunkContent } = extractBracedBody(lines, i);
      for (let j = i; j <= endLineIndex; j++) consumed.add(j);
      chunks.push({
        id: makeId(filePath, name, ChunkType.Interface),
        name,
        type: ChunkType.Interface,
        filePath,
        startLine: i + 1,
        endLine: endLineIndex + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      i = endLineIndex + 1;
      continue;
    }

    // Class
    const classMatch = trimmed.match(classDeclRe);
    if (classMatch) {
      const name = classMatch[1] ?? `AnonymousClass_${i}`;
      const { endLineIndex, content: chunkContent } = extractBracedBody(lines, i);
      for (let j = i; j <= endLineIndex; j++) consumed.add(j);

      const classLines = chunkContent.split('\n');
      let mi = 1;
      while (mi < classLines.length - 1) {
        const mLine = classLines[mi];
        const methodMatch = mLine.match(methodRe);
        if (methodMatch) {
          const methodName = methodMatch[1];
          const { endLineIndex: mEnd, content: mContent } = extractBracedBody(classLines, mi);
          chunks.push({
            id: makeId(filePath, `${name}.${methodName}`, ChunkType.Method),
            name: `${name}.${methodName}`,
            type: ChunkType.Method,
            filePath,
            startLine: i + mi + 1,
            endLine: i + mEnd + 1,
            content: mContent,
            contentHash: makeContentHash(mContent),
            metadata: {},
          });
          mi = mEnd + 1;
          continue;
        }
        mi++;
      }

      chunks.push({
        id: makeId(filePath, name, ChunkType.Class),
        name,
        type: ChunkType.Class,
        filePath,
        startLine: i + 1,
        endLine: endLineIndex + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      i = endLineIndex + 1;
      continue;
    }

    // Function declaration (including export default function)
    const funcMatch = trimmed.match(functionDeclRe);
    if (funcMatch) {
      const name = funcMatch[1] ?? `default_${i}`;
      const { endLineIndex, content: chunkContent } = extractBracedBody(lines, i);
      for (let j = i; j <= endLineIndex; j++) consumed.add(j);
      chunks.push({
        id: makeId(filePath, name, ChunkType.Function),
        name,
        type: ChunkType.Function,
        filePath,
        startLine: i + 1,
        endLine: endLineIndex + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      i = endLineIndex + 1;
      continue;
    }

    // Arrow function
    const arrowMatch = trimmed.match(arrowFnRe);
    if (arrowMatch) {
      const name = arrowMatch[1];
      if (trimmed.includes('{')) {
        const { endLineIndex, content: chunkContent } = extractBracedBody(lines, i);
        for (let j = i; j <= endLineIndex; j++) consumed.add(j);
        chunks.push({
          id: makeId(filePath, name, ChunkType.Function),
          name,
          type: ChunkType.Function,
          filePath,
          startLine: i + 1,
          endLine: endLineIndex + 1,
          content: chunkContent,
          contentHash: makeContentHash(chunkContent),
          metadata: {},
        });
        i = endLineIndex + 1;
      } else {
        let endI = i;
        while (endI < lines.length - 1 && !lines[endI].trim().endsWith(';')) {
          endI++;
        }
        const chunkContent = lines.slice(i, endI + 1).join('\n');
        for (let j = i; j <= endI; j++) consumed.add(j);
        chunks.push({
          id: makeId(filePath, name, ChunkType.Function),
          name,
          type: ChunkType.Function,
          filePath,
          startLine: i + 1,
          endLine: endI + 1,
          content: chunkContent,
          contentHash: makeContentHash(chunkContent),
          metadata: {},
        });
        i = endI + 1;
      }
      continue;
    }

    // Variable declaration (non-arrow)
    const varMatch = trimmed.match(varDeclRe);
    if (varMatch) {
      const name = varMatch[1];
      const chunkContent = line;
      consumed.add(i);
      chunks.push({
        id: makeId(filePath, name, ChunkType.Variable),
        name,
        type: ChunkType.Variable,
        filePath,
        startLine: i + 1,
        endLine: i + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      i++;
      continue;
    }

    i++;
  }

  return chunks;
}

function parsePython(content: string, filePath: string): SemanticChunk[] {
  const chunks: SemanticChunk[] = [];
  const lines = content.split('\n');

  const importRe = /^(?:import\s+\S+|from\s+\S+\s+import\s+.+)/;
  const defRe = /^(?:async\s+)?def\s+(\w+)\s*\(/;
  const classRe = /^class\s+(\w+)(?:\s*\([^)]*\))?\s*:/;

  function extractIndentedBlock(startIdx: number): { endIdx: number; content: string } {
    if (startIdx >= lines.length) return { endIdx: startIdx, content: lines[startIdx] || '' };
    const startLine = lines[startIdx];
    const baseIndent = startLine.match(/^(\s*)/)?.[1].length ?? 0;
    let endIdx = startIdx;

    for (let i = startIdx + 1; i < lines.length; i++) {
      const l = lines[i];
      if (l.trim() === '') { endIdx = i; continue; }
      const indent = l.match(/^(\s*)/)?.[1].length ?? 0;
      if (indent > baseIndent) {
        endIdx = i;
      } else {
        break;
      }
    }
    return {
      endIdx,
      content: lines.slice(startIdx, endIdx + 1).join('\n'),
    };
  }

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed || trimmed.startsWith('#')) { i++; continue; }

    if (importRe.test(trimmed) && !line.startsWith(' ') && !line.startsWith('\t')) {
      const name = `import_${i}`;
      chunks.push({
        id: makeId(filePath, name, ChunkType.Import),
        name,
        type: ChunkType.Import,
        filePath,
        startLine: i + 1,
        endLine: i + 1,
        content: line,
        contentHash: makeContentHash(line),
        metadata: {},
      });
      i++;
      continue;
    }

    const defMatch = trimmed.match(defRe);
    if (defMatch && !line.startsWith(' ') && !line.startsWith('\t')) {
      const name = defMatch[1];
      const { endIdx, content: chunkContent } = extractIndentedBlock(i);
      chunks.push({
        id: makeId(filePath, name, ChunkType.Function),
        name,
        type: ChunkType.Function,
        filePath,
        startLine: i + 1,
        endLine: endIdx + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      i = endIdx + 1;
      continue;
    }

    const classMatch = trimmed.match(classRe);
    if (classMatch && !line.startsWith(' ') && !line.startsWith('\t')) {
      const name = classMatch[1];
      const { endIdx, content: chunkContent } = extractIndentedBlock(i);
      chunks.push({
        id: makeId(filePath, name, ChunkType.Class),
        name,
        type: ChunkType.Class,
        filePath,
        startLine: i + 1,
        endLine: endIdx + 1,
        content: chunkContent,
        contentHash: makeContentHash(chunkContent),
        metadata: {},
      });
      i = endIdx + 1;
      continue;
    }

    i++;
  }

  return chunks;
}

export function parse(content: string, filePath: string): SemanticChunk[] {
  if (!content || !content.trim()) return [];
  const ext = filePath.split('.').pop()?.toLowerCase();
  if (ext === 'py') return parsePython(content, filePath);
  if (ext === 'ts' || ext === 'js' || ext === 'tsx' || ext === 'jsx') return parseJsTs(content, filePath);
  return [];
}
