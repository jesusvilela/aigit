export enum ChunkType {
  Function = 'function',
  Class = 'class',
  Method = 'method',
  Interface = 'interface',
  Variable = 'variable',
  Import = 'import',
  Block = 'block',
  Unknown = 'unknown',
}

export interface SemanticChunk {
  id: string;           // sha1 of (filePath + ':' + name + ':' + type)
  name: string;
  type: ChunkType;
  filePath: string;
  startLine: number;
  endLine: number;
  content: string;
  contentHash: string;  // sha1 of content
  metadata: Record<string, unknown>;
}

export interface ChunkEdge {
  from: string;   // chunk id
  to: string;     // chunk id
  kind: 'calls' | 'imports' | 'extends' | 'implements' | 'uses';
}
