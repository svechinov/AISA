import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "./ui/dialog";
import { Loader2 } from "lucide-react";
import { t } from "../lib/i18n";

const ENV_API = import.meta.env.VITE_API_BASE?.trim();
const API_BASE = ENV_API ? (ENV_API.endsWith("/") ? ENV_API.slice(0, -1) : ENV_API) : "/api";

export function ManualLeadGenModal({ runId, open, onOpenChange, onContactsAdded }) {
  const [companyName, setCompanyName] = useState("");
  const [website, setWebsite] = useState("");
  const [targetRoles, setTargetRoles] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSearch = async () => {
    if (!companyName.trim()) {
      alert("Company name is required");
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/contacts/run/${runId}/generate-company-leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_name: companyName,
          website: website,
          target_roles: targetRoles,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to generate leads");
      }

      const newContacts = await response.json();
      if (newContacts.length > 0) {
        alert(t("Found contacts") + ": " + newContacts.length + " contacts added.");
        if (onContactsAdded) onContactsAdded(newContacts);
        onOpenChange(false);
      } else {
        alert(t("No contacts found") + " - Try different roles or company name.");
      }
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{t("Find Decision Makers by Company")}</DialogTitle>
          <p className="text-sm text-muted-foreground">
            {t("Searching via Tavily + LLM...")}
          </p>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium">{t("Company Name")}</label>
            <Input 
              placeholder="e.g. Yandex" 
              value={companyName} 
              onChange={(e) => setCompanyName(e.target.value)} 
              disabled={loading}
            />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium">{t("Website (optional)")}</label>
            <Input 
              placeholder="e.g. yandex.ru" 
              value={website} 
              onChange={(e) => setWebsite(e.target.value)} 
              disabled={loading}
            />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium">{t("Target Roles")}</label>
            <Input 
              placeholder={t("e.g., CEO, Founder, HR Director")} 
              value={targetRoles} 
              onChange={(e) => setTargetRoles(e.target.value)} 
              disabled={loading}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSearch} disabled={loading || !companyName.trim()}>
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {t("Start Search")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
