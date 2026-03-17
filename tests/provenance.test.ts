import { ProvenanceTracker } from '../src/provenance/tracker';
import { ProvenanceRecord, ProvenanceStore, AgentIdentity } from '../src/provenance/types';

class MemoryProvenanceStore implements ProvenanceStore {
  private records: ProvenanceRecord[] = [];

  async save(record: ProvenanceRecord): Promise<void> {
    this.records.push(record);
  }

  async load(chunkId: string): Promise<ProvenanceRecord[]> {
    return this.records.filter(r => r.chunkId === chunkId);
  }

  async loadAll(): Promise<ProvenanceRecord[]> {
    return [...this.records];
  }
}

const agent: AgentIdentity = {
  id: 'agent-1',
  name: 'Test Agent',
  type: 'ai',
};

describe('ProvenanceTracker', () => {
  test('record and query returns most recent', async () => {
    const store = new MemoryProvenanceStore();
    const tracker = new ProvenanceTracker(store);
    
    await tracker.record({ chunkId: 'chunk-1', agent, action: 'created' });
    const record = await tracker.query('chunk-1');
    
    expect(record).toBeDefined();
    expect(record?.chunkId).toBe('chunk-1');
    expect(record?.action).toBe('created');
    expect(record?.timestamp).toBeDefined();
  });

  test('history returns all records sorted by timestamp', async () => {
    const store = new MemoryProvenanceStore();
    const tracker = new ProvenanceTracker(store);
    
    await tracker.record({ chunkId: 'chunk-1', agent, action: 'created' });
    await new Promise(r => setTimeout(r, 10));
    await tracker.record({ chunkId: 'chunk-1', agent, action: 'modified' });
    
    const history = await tracker.history('chunk-1');
    expect(history).toHaveLength(2);
    expect(history[0].action).toBe('created');
    expect(history[1].action).toBe('modified');
  });

  test('listAll returns all records', async () => {
    const store = new MemoryProvenanceStore();
    const tracker = new ProvenanceTracker(store);
    
    await tracker.record({ chunkId: 'chunk-1', agent, action: 'created' });
    await tracker.record({ chunkId: 'chunk-2', agent, action: 'created' });
    
    const all = await tracker.listAll();
    expect(all).toHaveLength(2);
  });
});
