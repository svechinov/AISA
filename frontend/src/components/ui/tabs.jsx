import { createContext, useContext, useState } from "react";
import { cn } from "@/lib/utils";

const TabsCtx = createContext(null);

/**
 * Tabs with optional controlled `value` / `onValueChange` (Radix-style).
 * If `value` is undefined, the tab is uncontrolled and `defaultValue` seeds state.
 */
export function Tabs({ defaultValue, value: valueProp, onValueChange, children, className }) {
  const [internal, setInternal] = useState(() => defaultValue ?? undefined);
  const isControlled = valueProp !== undefined;
  const tab = isControlled ? valueProp : internal;

  const setTab = (next) => {
    if (!isControlled) {
      setInternal(next);
    }
    onValueChange?.(next);
  };

  return (
    <TabsCtx.Provider value={{ tab, setTab }}>
      <div className={className}>{children}</div>
    </TabsCtx.Provider>
  );
}

export function TabsList({ className, children }) {
  return (
    <div
      className={cn(
        "inline-flex h-10 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({ value, className, children }) {
  const ctx = useContext(TabsCtx);
  const active = ctx.tab === value;
  return (
    <button
      type="button"
      onClick={() => ctx.setTab(value)}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-all",
        active && "bg-background text-foreground shadow",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, className, children }) {
  const ctx = useContext(TabsCtx);
  if (ctx.tab !== value) return null;
  return <div className={className}>{children}</div>;
}
