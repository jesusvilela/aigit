export interface AgentIdentity {
  id: string;
  name: string;
  type: 'human' | 'ai' | 'system';
  metadata?: Record<string, unknown>;
}

export interface ProvenanceRecord {
  chunkId: string;
  agent: AgentIdentity;
  commitSha?: string;
  action: 'created' | 'modified' | 'deleted' | 'reviewed';
  timestamp: string; // ISO 8601
  metadata?: Record<string, unknown>;
}

export interface ProvenanceStore {
  save(record: ProvenanceRecord): Promise<void>;
  load(chunkId: string): Promise<ProvenanceRecord[]>;
  loadAll(): Promise<ProvenanceRecord[]>;
}
