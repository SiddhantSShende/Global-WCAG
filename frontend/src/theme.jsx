import { createContext, useContext, useEffect, useState } from "react";

const KEY = "gw-theme";
const ThemeCtx = createContext({ theme: "light", toggle: () => {} });

function systemDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(
    () => localStorage.getItem(KEY) || (systemDark() ? "dark" : "light")
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    localStorage.setItem(KEY, next);
    setTheme(next);
  };

  return <ThemeCtx.Provider value={{ theme, toggle }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
