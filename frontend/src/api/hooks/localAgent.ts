import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { extensionVersion, runLocal, type MachineState } from "@/lib/localAgent";

/**
 * Whether a local helper is here, and what it says about this machine.
 *
 * The marker is set by a content script at `document_start`, which usually beats React — but not
 * always, and an extension enabled while the tab is open sets it later still. So this watches rather
 * than reading once: a button that never appears because of a race is indistinguishable, to the
 * person, from an extension that does not work.
 */
export function useLocalAgent() {
  const [version, setVersion] = useState(extensionVersion);

  useEffect(() => {
    if (version) return;
    const observer = new MutationObserver(() => {
      const found = extensionVersion();
      if (found) setVersion(found);
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-autoskill-extension"] });
    return () => observer.disconnect();
  }, [version]);

  return { available: !!version, version };
}

/** What the helper reports about this machine: the agents it found, and where. */
export function useMachineState(enabled = true) {
  const { available } = useLocalAgent();
  return useQuery({
    queryKey: ["localAgent", "state"],
    queryFn: () => runLocal<MachineState>("state"),
    enabled: enabled && available,
    // The answer describes a filesystem, which changes without telling anybody: an agent installed
    // in another window is exactly the case this is meant to notice.
    staleTime: 15_000,
    retry: false,
  });
}
