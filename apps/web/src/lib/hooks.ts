import { useCallback, useEffect, useRef, useState } from "react";

/** Load something, optionally refreshing every `ms`. Keeps the last good data while refreshing. */
export function useData<T>(load: () => Promise<T>, deps: unknown[], ms?: number | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(load);
  latest.current = load;
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++generation.current;
    try {
      const d = await latest.current();
      if (mine === generation.current) { setData(d); setError(null); }
    } catch (e) {
      if (mine === generation.current) setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      if (mine === generation.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    setData(null);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!ms) return;
    const timer = setInterval(() => void reload(), ms);
    return () => clearInterval(timer);
  }, [ms, reload]);

  return { data, error, loading, reload };
}
