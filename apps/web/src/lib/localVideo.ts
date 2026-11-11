// The backend deletes every video after processing. To replay a recording, the file is kept in this browser only
// (IndexedDB), under the recording's id. It never leaves this device.

const DB = "mnemo_videos";
const STORE = "videos";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const req = fn(db.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export const saveVideo = (id: string, file: Blob) => run("readwrite", (s) => s.put(file, id)).catch(() => undefined);
export const loadVideo = (id: string) => run<Blob | undefined>("readonly", (s) => s.get(id)).catch(() => undefined);
export const forgetVideo = (id: string) => run("readwrite", (s) => s.delete(id)).catch(() => undefined);
