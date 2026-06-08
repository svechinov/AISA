import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Badge } from "./ui/badge";
import { Server, Trash2, Plus, Loader2 } from "lucide-react";

export function SmtpFarmModal({ apiBase }) {
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);

  // Form state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [smtpServer, setSmtpServer] = useState("box.yourdomain.com");
  const [smtpPort, setSmtpPort] = useState(465);
  const [dailyLimit, setDailyLimit] = useState(50);

  const fetchAccounts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/smtp-accounts/`);
      if (res.ok) {
        const data = await res.json();
        setAccounts(data);
      }
    } catch (e) {
      console.error("Failed to load SMTP accounts", e);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (open) {
      fetchAccounts();
    }
  }, [open, apiBase]);

  const handleAdd = async (e) => {
    e.preventDefault();
    setAdding(true);
    try {
      const payload = {
        email,
        password,
        smtp_server: smtpServer,
        smtp_port: smtpPort,
        imap_server: smtpServer, // Usually same for mail-in-a-box
        imap_port: 993,
        daily_limit: dailyLimit,
        is_active: true
      };
      const res = await fetch(`${apiBase}/smtp-accounts/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        setEmail("");
        setPassword("");
        fetchAccounts();
      } else {
        alert("Failed to add account. Check if email already exists.");
      }
    } catch (e) {
      console.error(e);
    }
    setAdding(false);
  };

  const handleDelete = async (id) => {
    if (!confirm("Remove this SMTP account?")) return;
    try {
      await fetch(`${apiBase}/smtp-accounts/${id}`, { method: "DELETE" });
      fetchAccounts();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2 shrink-0">
          <Server className="h-4 w-4" />
          SMTP Farm
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>SMTP Farm / Mail-in-a-Box Balancer</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Add multiple sender emails to distribute load and avoid spam limits. The system automatically rotates through active accounts.
          </p>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 flex-1 min-h-0">
          {/* List side */}
          <div className="md:col-span-2 overflow-y-auto pr-2 space-y-3">
            <h3 className="font-semibold text-sm">Active Accounts ({accounts.length})</h3>
            {loading ? (
              <div className="flex justify-center p-4"><Loader2 className="animate-spin h-5 w-5" /></div>
            ) : accounts.length === 0 ? (
              <div className="text-sm text-muted-foreground p-4 border border-dashed rounded-lg text-center">
                No accounts configured. Falling back to global Yandex.
              </div>
            ) : (
              accounts.map((acc) => (
                <div key={acc.id} className="border rounded-lg p-3 flex flex-col gap-2 shadow-sm text-sm">
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="font-medium">{acc.email}</div>
                      <div className="text-xs text-muted-foreground">{acc.smtp_server}:{acc.smtp_port}</div>
                    </div>
                    <Button variant="ghost" size="icon" onClick={() => handleDelete(acc.id)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                  <div className="flex justify-between items-center bg-muted/50 p-2 rounded-md mt-1">
                    <div className="flex flex-col">
                      <span className="text-[10px] uppercase font-semibold text-muted-foreground">Sent Today</span>
                      <span className="font-mono">{acc.sent_today} / {acc.daily_limit}</span>
                    </div>
                    <div className="flex flex-col text-right">
                      <span className="text-[10px] uppercase font-semibold text-muted-foreground">Status</span>
                      <Badge variant={acc.is_active ? "default" : "secondary"}>
                        {acc.is_active ? "Active" : "Disabled"}
                      </Badge>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Form side */}
          <form onSubmit={handleAdd} className="flex flex-col gap-3 bg-muted/30 p-4 rounded-xl border">
            <h3 className="font-semibold text-sm">Add New Box</h3>
            
            <div className="space-y-1">
              <label className="text-xs font-medium">Email Address</label>
              <Input required type="email" placeholder="sales@yourbox.com" value={email} onChange={e => setEmail(e.target.value)} />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium">Password / App Password</label>
              <Input required type="password" value={password} onChange={e => setPassword(e.target.value)} />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium">SMTP Server</label>
              <Input required placeholder="box.yourdomain.com" value={smtpServer} onChange={e => setSmtpServer(e.target.value)} />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium">Port</label>
                <Input required type="number" value={smtpPort} onChange={e => setSmtpPort(Number(e.target.value))} />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Daily Limit</label>
                <Input required type="number" value={dailyLimit} onChange={e => setDailyLimit(Number(e.target.value))} />
              </div>
            </div>

            <Button type="submit" className="mt-2 w-full" disabled={adding}>
              {adding ? <Loader2 className="animate-spin h-4 w-4 mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
              Add Account
            </Button>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  );
}
