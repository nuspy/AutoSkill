import { create } from "zustand";

type Theme = "light" | "dark" | "system";

interface UiState {
  theme: Theme;
  sidebarOpen: boolean;
  soundOn: boolean;
  setTheme: (theme: Theme) => void;
  toggleSidebar: () => void;
  toggleSound: () => void;
}

function readTheme(): Theme {
  try {
    return (localStorage.getItem("autoskill.theme") as Theme) || "system";
  } catch {
    return "system";
  }
}

/** On by default: the bell exists for people who walked away, and they cannot ask for it from there. */
function readSound(): boolean {
  try {
    return localStorage.getItem("autoskill.sound") !== "off";
  } catch {
    return true;
  }
}

export function applyTheme(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export const useUi = create<UiState>((set) => ({
  theme: readTheme(),
  sidebarOpen: true,
  soundOn: readSound(),
  setTheme: (theme) => {
    try {
      localStorage.setItem("autoskill.theme", theme);
    } catch {
      /* ignore */
    }
    applyTheme(theme);
    set({ theme });
  },
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  toggleSound: () =>
    set((s) => {
      const soundOn = !s.soundOn;
      try {
        localStorage.setItem("autoskill.sound", soundOn ? "on" : "off");
      } catch {
        /* ignore */
      }
      return { soundOn };
    }),
}));
