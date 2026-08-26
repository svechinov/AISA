import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lock, Loader2 } from "lucide-react";
import { API_BASE } from "@/lib/apiBase";

export default function LoginGate({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // Check on mount if we already have a valid token
  useEffect(() => {
    const token = localStorage.getItem("aibizos_auth_token");
    if (token) {
      setIsAuthenticated(true);
    }
    setLoading(false);
  }, []);

  // Listen for custom 401 events to trigger logout
  useEffect(() => {
    const handleUnauthorized = () => {
      localStorage.removeItem("aibizos_auth_token");
      setIsAuthenticated(false);
    };
    window.addEventListener("aibizos:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("aibizos:unauthorized", handleUnauthorized);
  }, []);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });

      if (!res.ok) {
        throw new Error("Invalid password");
      }

      const data = await res.json();
      localStorage.setItem("aibizos_auth_token", data.token);
      setIsAuthenticated(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isAuthenticated) {
    return children;
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-background p-4">
      <form
        onSubmit={handleLogin}
        className="w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-lg"
      >
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-4 rounded-full bg-primary/10 p-3">
            <Lock className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-xl font-semibold">AI-Biz-OS Login</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Please enter the global password to access the platform.
          </p>
        </div>

        <div className="space-y-4">
          <Input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />
          {error && <p className="text-sm text-destructive font-medium">{error}</p>}
          <div className="text-[10px] text-muted-foreground text-center opacity-50">
            Auth Path: {API_BASE}/auth/login
          </div>
          <Button type="submit" className="w-full" disabled={loading || !password}>
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Sign In
          </Button>
        </div>
      </form>
    </div>
  );
}
