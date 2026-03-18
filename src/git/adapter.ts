import simpleGit, { SimpleGit } from 'simple-git';
import * as fs from 'fs/promises';
import * as path from 'path';

export interface LogEntry {
  hash: string;
  date: string;
  message: string;
  author: string;
  email: string;
}

export class GitAdapter {
  private readonly git: SimpleGit;
  private readonly repoPath: string;

  constructor(repoPath: string) {
    this.repoPath = repoPath;
    this.git = simpleGit(repoPath);
  }

  /** Returns `true` if `repoPath` is inside a Git repository. */
  async isRepo(): Promise<boolean> {
    try {
      await this.git.revparse(['--git-dir']);
      return true;
    } catch {
      return false;
    }
  }

  async getCommitHash(ref: string): Promise<string> {
    const hash = await this.git.revparse([ref]);
    return hash.trim();
  }

  async getBlob(commitSha: string, filePath: string): Promise<string> {
    return this.git.raw(['show', `${commitSha}:${filePath}`]);
  }

  async getStagedFiles(): Promise<string[]> {
    const output = await this.git.diff(['--name-only', '--cached']);
    return output.trim().split('\n').filter((f: string) => f.length > 0);
  }

  async readWorkingFile(filePath: string): Promise<string> {
    return fs.readFile(path.join(this.repoPath, filePath), 'utf-8');
  }

  /** Return the name of the currently checked-out branch. */
  async getCurrentBranch(): Promise<string> {
    const branch = await this.git.revparse(['--abbrev-ref', 'HEAD']);
    return branch.trim();
  }

  /**
   * Return recent commit log entries.
   * @param options.maxCount – maximum number of entries (default 20)
   * @param options.file     – if set, restrict log to commits touching this file
   */
  async getLog(options: { maxCount?: number; file?: string } = {}): Promise<LogEntry[]> {
    const maxCount = options.maxCount ?? 20;
    const format = '%H%x00%ai%x00%s%x00%an%x00%ae';
    const args = ['--pretty=format:' + format, `-n`, String(maxCount)];
    if (options.file) args.push('--', options.file);

    const output = await this.git.raw(['log', ...args]);
    if (!output.trim()) return [];

    return output
      .trim()
      .split('\n')
      .filter(line => line.trim())
      .map(line => {
        const [hash, date, message, author, email] = line.split('\x00');
        return { hash, date, message, author, email };
      });
  }

  /**
   * Return the unified diff between two refs (or staged changes when omitted).
   */
  async getDiff(from?: string, to?: string): Promise<string> {
    if (!from && !to) {
      return this.git.diff(['--cached']);
    }
    if (from && !to) {
      return this.git.diff([from]);
    }
    return this.git.diff([`${from}..${to}`]);
  }

  async writeNote(objectSha: string, message: string): Promise<void> {
    await this.git.raw(['notes', 'add', '-m', message, objectSha]);
  }

  async listNotes(): Promise<Array<{ notesSha: string; objectSha: string }>> {
    const output = await this.git.raw(['notes', 'list']);
    if (!output.trim()) return [];
    return output
      .trim()
      .split('\n')
      .map((line: string) => {
        const [notesSha, objectSha] = line.trim().split(/\s+/);
        return { notesSha, objectSha };
      });
  }
}
