import { useEffect, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { bootstrapSession, startSilentRefresh } from "@/api/client";
import { applyTheme, useUi } from "@/stores/ui";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } },
});

export function AppProviders({ children }: { children: ReactNode }) {
  const theme = useUi((s) => s.theme);
  useEffect(() => {
    applyTheme(theme);
    bootstrapSession();
    // Keep the access token fresh in the background so a long operation never lets it lapse and
    // bounce the person to login. Idempotent, so re-running this effect (a theme change) is harmless.
    startSilentRefresh();
  }, [theme]);
  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  );
}
