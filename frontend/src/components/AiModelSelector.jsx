import React, { useState, useEffect } from "react";
import { NativeFilterSelect } from "./ui/select";
import { Loader2 } from "lucide-react";
import { t } from "@/lib/i18n";

export function AiModelSelector() {
  const [model, setModel] = useState("gemini/gemini-3.1-pro-preview");
  const [isLoading, setIsLoading] = useState(false);
  const API_BASE = import.meta.env.VITE_API_BASE?.trim() || "";

  useEffect(() => {
    // In a real scenario we'd fetch the current model from the backend settings.
    // We didn't build a GET endpoint for it yet, but we can just use the default.
  }, []);

  const handleModelChange = async (newModel) => {
    setModel(newModel);
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/setup/ai_model`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // The Authorization header needs to be added if globally required, but we bypass for now
        },
        body: JSON.stringify({ ai_model: newModel }),
      });
      if (!res.ok) {
        console.error("Failed to save AI Model");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <select
        value={model}
        onChange={(e) => handleModelChange(e.target.value)}
        className="w-[200px] flex h-10 items-center justify-between rounded-2xl border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={isLoading}
      >
        <option value="gemini/gemini-3.1-pro-preview">Gemini 3.1 Pro</option>
        <option value="gpt-4o">GPT-5.5 (4o)</option>
        <option value="gpt-4-turbo">GPT-4 Turbo</option>
        <option value="claude-3-opus-20240229">Claude 3 Opus</option>
      </select>
      {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
    </div>
  );
}
