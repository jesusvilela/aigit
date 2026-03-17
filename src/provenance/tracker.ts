import { ProvenanceRecord, ProvenanceStore } from './types';

export class ProvenanceTracker {
  constructor(private store: ProvenanceStore) {}

  async record(record: Omit<ProvenanceRecord, 'timestamp'>): Promise<void> {
    await this.store.save({ ...record, timestamp: new Date().toISOString() });
  }

  async query(chunkId: string): Promise<ProvenanceRecord | undefined> {
    const records = await this.store.load(chunkId);
    return records.sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0];
  }

  async history(chunkId: string): Promise<ProvenanceRecord[]> {
    const records = await this.store.load(chunkId);
    return records.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }

  async listAll(): Promise<ProvenanceRecord[]> {
    return this.store.loadAll();
  }
}
