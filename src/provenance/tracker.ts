import { ProvenanceRecord, ProvenanceStore } from './types';

export class ProvenanceTracker {
  constructor(private readonly store: ProvenanceStore) {}

  async record(record: Omit<ProvenanceRecord, 'timestamp'>): Promise<void> {
    await this.store.save({ ...record, timestamp: new Date().toISOString() });
  }

  /** Returns the most recent record for a chunk, or `undefined`. */
  async query(chunkId: string): Promise<ProvenanceRecord | undefined> {
    const records = await this.store.load(chunkId);
    return records.sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0];
  }

  /** Returns all records for a chunk, oldest-first. */
  async history(chunkId: string): Promise<ProvenanceRecord[]> {
    const records = await this.store.load(chunkId);
    return records.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }

  /** Returns all records across all chunks. */
  async listAll(): Promise<ProvenanceRecord[]> {
    return this.store.loadAll();
  }

  /**
   * Return a map of chunkId → most recent ProvenanceRecord for every chunk
   * that has at least one record.  Useful for "blame" views.
   */
  async blame(): Promise<Map<string, ProvenanceRecord>> {
    const all = await this.store.loadAll();
    const latest = new Map<string, ProvenanceRecord>();

    for (const record of all) {
      const existing = latest.get(record.chunkId);
      if (!existing || record.timestamp > existing.timestamp) {
        latest.set(record.chunkId, record);
      }
    }
    return latest;
  }

  /**
   * Return all records created by the given agent id, newest-first.
   */
  async byAgent(agentId: string): Promise<ProvenanceRecord[]> {
    const all = await this.store.loadAll();
    return all
      .filter(r => r.agent.id === agentId)
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  }

  /**
   * Return all records with a timestamp >= `since` (ISO 8601), newest-first.
   */
  async since(since: string): Promise<ProvenanceRecord[]> {
    const all = await this.store.loadAll();
    return all
      .filter(r => r.timestamp >= since)
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  }

  /**
   * Return the full provenance lineage for a chunk — all of its records plus,
   * recursively, all records for any chunk ids referenced in the metadata
   * `derivedFrom` field.
   *
   * The chain is returned oldest-first with duplicates removed.
   */
  async lineage(chunkId: string): Promise<ProvenanceRecord[]> {
    const visited = new Set<string>();
    const result: ProvenanceRecord[] = [];

    const traverse = async (id: string): Promise<void> => {
      if (visited.has(id)) return;
      visited.add(id);

      const records = await this.store.load(id);
      for (const r of records) {
        result.push(r);
        const derived = r.metadata?.['derivedFrom'];
        if (typeof derived === 'string') await traverse(derived);
      }
    };

    await traverse(chunkId);
    return result.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }
}
