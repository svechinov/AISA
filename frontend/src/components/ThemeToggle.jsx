import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { readStoredTheme, setTheme } from "@/lib/theme";

export function ThemeToggle() {
  const [mode, setMode] = useState(() => readStoredTheme());

  useEffect(() => {
    setMode(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);

  const toggle = () => {
    const next = mode === "dark" ? "light" : "dark";
    setTheme(next);
    setMode(next);
  };

  const isDark = mode === "dark";

  return (
    <Button
      type="button"
      variant="outline"
      className="h-10 w-10 shrink-0 p-0"
      onClick={toggle}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Light theme" : "Dark theme"}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
