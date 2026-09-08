/**
 * A place for the app to answer one question: is anything still unsaved?
 *
 * The semester map saves itself on a short debounce, which is right for editing
 * — but it means navigation a moment after a change could discard
 * the API before the save request ever left the browser, and the edit would be
 * gone with no warning. Shutting down has to be able to wait for the save.
 *
 * Editors register how to report dirtiness and how to flush; the shutdown
 * control asks. Nothing here holds plan data, so there is one owner of the state
 * and no copy to fall out of sync.
 */

export interface PendingSave {
  /** True when this editor holds changes that are not on disk yet. */
  isDirty: () => boolean;
  /** Write them now. Must reject if the write failed. */
  flush: () => Promise<void>;
}

const registered = new Set<PendingSave>();

/** Register an editor. Returns the unregister function for effect cleanup. */
export function registerPendingSave(entry: PendingSave): () => void {
  registered.add(entry);
  return () => {
    registered.delete(entry);
  };
}

export function hasUnsavedChanges(): boolean {
  return [...registered].some((entry) => entry.isDirty());
}

/**
 * Flush every editor holding changes.
 *
 * Rejects if any flush fails, so a caller about to do something destructive —
 * stopping the server, closing the tab — can stop and say so rather than
 * discarding work.
 */
export async function flushPendingSaves(): Promise<void> {
  const dirty = [...registered].filter((entry) => entry.isDirty());
  if (dirty.length === 0) return;
  await Promise.all(dirty.map((entry) => entry.flush()));
}
