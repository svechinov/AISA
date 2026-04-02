import { createContext, useContext, useState } from "react";
import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

const DialogCtx = createContext(null);

export function useDialog() {
  const c = useContext(DialogCtx);
  if (!c) throw new Error("useDialog must be used inside Dialog");
  return c;
}

/**
 * @param {{ children: React.ReactNode, open?: boolean, onOpenChange?: (open: boolean) => void }} props
 */
export function Dialog({ children, open: openProp, onOpenChange }) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : uncontrolledOpen;
  const setOpen = (next) => {
    if (!controlled) {
      setUncontrolledOpen(next);
    }
    onOpenChange?.(next);
  };

  return <DialogCtx.Provider value={{ open, setOpen }}>{children}</DialogCtx.Provider>;
}

export function DialogTrigger({ asChild, children, ...props }) {
  const { setOpen } = useContext(DialogCtx);
  const onClick = () => setOpen(true);
  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children, { onClick, ...props });
  }
  return (
    <button type="button" onClick={onClick} {...props}>
      {children}
    </button>
  );
}

export function DialogContent({ className, children }) {
  const { open, setOpen } = useContext(DialogCtx);
  if (!open) return null;
  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button
        type="button"
        className="fixed inset-0 bg-black/50"
        aria-label="Close"
        onClick={() => setOpen(false)}
      />
      <div
        className={cn(
          "relative z-[101] grid w-full max-w-lg gap-4 border bg-card p-6 shadow-lg sm:rounded-lg",
          className,
        )}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function DialogHeader({ className, ...props }) {
  return <div className={cn("flex flex-col space-y-1.5 text-center sm:text-left", className)} {...props} />;
}

export function DialogTitle({ className, ...props }) {
  return <h2 className={cn("text-lg font-semibold leading-none tracking-tight", className)} {...props} />;
}

export function DialogFooter({ className, ...props }) {
  return (
    <div className={cn("flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2", className)} {...props} />
  );
}
