import { create } from "zustand";
import type { User } from "@/api/types";

interface SessionState {
  accessToken: string | null;
  user: User | null;
  ready: boolean;
  setSession: (token: string, user: User) => void;
  setUser: (user: User) => void;
  clear: () => void;
  setReady: () => void;
}

export const useSession = create<SessionState>((set) => ({
  accessToken: null,
  user: null,
  ready: false,
  setSession: (accessToken, user) => set({ accessToken, user }),
  setUser: (user) => set({ user }),
  clear: () => set({ accessToken: null, user: null }),
  setReady: () => set({ ready: true }),
}));
