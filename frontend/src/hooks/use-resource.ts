import { useEffect, useState } from "react";

export type Resource<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "success"; data: T; error: null }
  | { status: "error"; data: null; error: unknown };

export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  refreshKey: number,
): Resource<T> {
  const [stored, setStored] = useState<{ key: number; resource: Resource<T> }>(() => ({
    key: refreshKey,
    resource: { status: "loading", data: null, error: null },
  }));

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) {
          setStored({ key: refreshKey, resource: { status: "success", data, error: null } });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setStored({ key: refreshKey, resource: { status: "error", data: null, error } });
        }
      },
    );
    return () => controller.abort();
  }, [load, refreshKey]);

  return stored.key === refreshKey
    ? stored.resource
    : { status: "loading", data: null, error: null };
}
