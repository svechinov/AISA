# AI-BIZ-OS UI/UX Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the AI-BIZ-OS UI into a transparent and controllable tool for Senior SDRs by adding OSINT visualization, manual step execution, and AmoCRM import.

**Architecture:** 
- Extend `AiBizOsHumanUI.jsx` with new functional components and dialogs.
- Use existing `api()` helper for new manual step endpoints.
- Update `renderDraftCard` and Companies table to display AI-generated insights.

**Tech Stack:** React, Tailwind CSS, Lucide Icons, FastAPI (Backend).

---

### Task 1: AI Reasoning Visualization in Drafts

**Files:**
- Modify: `frontend/src/pages/AiBizOsHumanUI.jsx`

- [ ] **Step 1: Extract reasoning from generation_meta_json in `renderDraftCard`**
- [ ] **Step 2: Render the reasoning block**

```javascript
// Inside renderDraftCard
const reasoning = genMeta?.reasoning;

// ... inside return, below the badges
{reasoning && (
  <div className="mt-3 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs">
    <div className="mb-1 font-semibold text-primary">AI Strategy (Reasoning)</div>
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      <div><span className="opacity-70">Hook:</span> {reasoning.hook}</div>
      <div><span className="opacity-70">Angle:</span> {reasoning.angle}</div>
      <div><span className="opacity-70">Key Point:</span> {reasoning.key_point}</div>
    </div>
  </div>
)}
```

---

### Task 2: Manual Step Control Panel

**Files:**
- Modify: `frontend/src/pages/AiBizOsHumanUI.jsx`

- [ ] **Step 1: Define `executeManualStep` function**

```javascript
const executeManualStep = async (runId, stepName) => {
  setError("");
  appendActivityLog(`Manual Step: Starting ${stepName} for Run ${runId}`);
  try {
    await api(`/steps/run/${runId}/execute/${stepName}`, { method: "POST", timeoutMs: 300000 });
    appendActivityLog(`Manual Step: ${stepName} completed.`);
    refreshRunMetricsOnly(runId);
  } catch (e) {
    setUiError(setError, e);
  }
};
```

- [ ] **Step 2: Add the Control Panel UI in the "Runs" section**

```javascript
// Locate the header section of the selected run
<div className="flex flex-wrap gap-2 py-2">
  {["enrich_crm_data", "validate_contacts", "generate_master_email_draft", "generate_emails"].map(step => (
    <Button 
      key={step} 
      size="sm" 
      variant="outline" 
      onClick={() => executeManualStep(selectedRun.id, step)}
    >
      Run {pretty(step)}
    </Button>
  ))}
</div>
```

---

### Task 3: AmoCRM Import UI

**Files:**
- Modify: `frontend/src/pages/AiBizOsHumanUI.jsx`

- [ ] **Step 1: Add state for Import Dialog**
- [ ] **Step 2: Implement `handleAmoCrmImport` function**

```javascript
const handleAmoCrmImport = async (file, runName, projectId) => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("run_name", runName);
  formData.append("project_id", projectId);

  setLoading(true);
  try {
    const res = await fetch(`${API_BASE}/runs/import-amocrm`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${GLOBAL_PASSWORD}` }, // Assuming token is password
      body: formData
    });
    // handle success...
  } catch (e) {
    setUiError(setError, e);
  } finally {
    setLoading(false);
  }
};
```

- [ ] **Step 3: Add "Import AmoCRM" button to the sidebar/header**

---

### Task 4: OSINT Dossier in Companies Table

**Files:**
- Modify: `frontend/src/pages/AiBizOsHumanUI.jsx`

- [ ] **Step 1: Add a "Dossier" column to the companies table**
- [ ] **Step 2: Add a Dialog/Popover to view the full `osint_dossier` text**

---

### Task 5: Variable Highlighting in Editor

**Files:**
- Modify: `frontend/src/components/EmailDraftRichTextEditor.jsx`

- [ ] **Step 1: Update TipTap configuration to use a custom extension for `{{variable}}` highlighting**
