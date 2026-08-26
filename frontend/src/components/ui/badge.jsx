import { cn } from "@/lib/utils";

export function Badge({ className, variant = "default", ...props }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
        variant === "default" && "border-transparent bg-primary text-primary-foreground",
        variant === "secondary" && "border-transparent bg-secondary text-secondary-foreground",
        variant === "destructive" && "border-transparent bg-destructive text-destructive-foreground",
        variant === "outline" && "border-border text-foreground",
        // статусные чипы (B-028): семантический цвет + мягкий фон, вместо ad-hoc палитры
        variant === "success" && "border-transparent bg-success-soft text-success",
        variant === "warning" && "border-transparent bg-warning-soft text-warning",
        variant === "danger" && "border-transparent bg-danger-soft text-danger",
        variant === "info" && "border-transparent bg-info-soft text-info",
        variant === "neutral" && "border-transparent bg-neutral-soft text-neutral",
        className,
      )}
      {...props}
    />
  );
}
