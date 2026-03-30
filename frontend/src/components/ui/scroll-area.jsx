import { cn } from "@/lib/utils";

export function ScrollArea({ className, children, ...props }) {
  return (
    <div className={cn("overflow-auto", className)} {...props}>
      {children}
    </div>
  );
}
