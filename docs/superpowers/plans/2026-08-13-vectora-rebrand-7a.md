# Vectora Rebrand (Phase 7A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand every display surface from "Frappe CRM" to "Vectora" — logo, icons, splash screens, app metadata, and UI copy — without touching data-layer names.

**Architecture:** Display-layer rename only. `app_name = "crm"`, Python module paths, `CRM *` doctype names, the `useOnboarding('frappecrm')` key, and the workspace `name` field all stay. The brand mark becomes an inline SVG in the existing `CRMLogo.vue` (all five consumers pick it up automatically); raster icons/splashes are generated from `/workspace/vec-logo.png` (512×512 RGBA master) with PIL.

**Tech Stack:** Vue 3 SFCs, vite-plugin-pwa manifest, PIL for raster generation.

**Spec:** `.pi/PLAN.md` § Phase 7A (branding-surface table) + § Product Direction (scope guard).

## Global Constraints

- Brand palette from the logo: sky `#21ABFB` → indigo `#5B5FE8` → magenta `#DF5FEB`. Primary UI color: indigo `#5B5FE8`.
- Do NOT edit: `crm/locale/*.po` (generated), `crm/public/frontend/*` (build output), `useOnboarding('frappecrm')` keys, workspace JSON `"name"` field, `app_name`/`app_publisher`/`app_email`/`app_license` in hooks.py, the AboutModal copyright line (AGPLv3 attribution), the ERPNext-side setting name `<b>Frappe CRM Data Synchronization</b>` (it names a field in ERPNext, not in this app).
- `frappe-bench/` is not provisioned here — no live-site verification possible; unit tests + grep sweeps are the gate.
- Commits: `feat:` prefix, one per coherent change; pre-commit may rewrite files → `git add` and re-commit.

---

### Task 1: Vectora brand assets

**Files:**
- Modify: `frontend/src/components/Icons/CRMLogo.vue` (replace SVG body)
- Create: `frontend/public/vectora-logo.png` (512×512 master, copied from `/workspace/vec-logo.png`)
- Overwrite: `frontend/public/favicon.png` (256×256, transparent)
- Overwrite: `crm/public/manifest/apple-icon-180.png` (white bg — apple icons can't be transparent)
- Overwrite: `crm/public/manifest/manifest-icon-{192,512}.maskable.png` (white bg, logo at 65% for the maskable safe zone)
- Overwrite: all 35 `crm/public/manifest/apple-splash-*-*.jpg` (white bg, logo at 25% of min dimension, centered)

**Interfaces:**
- Produces: `CRMLogo.vue` renders the Vectora V; consumers (`AppSidebar`, `BrandLogo`, `AboutModal`, `Questionnaire`, `PreferencesSettings`) need no changes.

- [ ] **Step 1: Replace `CRMLogo.vue` SVG** — gradient V matching the master PNG (blue left arm → magenta right arm):

```vue
<template>
  <svg
    width="300"
    height="300"
    viewBox="0 0 300 300"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    <defs>
      <linearGradient
        id="vectora-v-gradient"
        x1="44"
        y1="60"
        x2="256"
        y2="80"
        gradientUnits="userSpaceOnUse"
      >
        <stop offset="0" stop-color="#21ABFB" />
        <stop offset="0.55" stop-color="#5B5FE8" />
        <stop offset="1" stop-color="#DF5FEB" />
      </linearGradient>
    </defs>
    <path
      d="M72 56L150 236L228 56"
      stroke="url(#vectora-v-gradient)"
      stroke-width="52"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>
```

- [ ] **Step 2: Generate raster assets** with a PIL script in the scratchpad (not committed): copy master → `frontend/public/vectora-logo.png`; favicon 256 transparent; apple-icon-180 and maskable 192/512 on white; regenerate every existing `apple-splash-<W>-<H>.jpg` (sizes parsed from filenames) as white with the logo centered at 25% of min(W,H), JPEG quality 85.

- [ ] **Step 3: Verify** — `python3 -c` sanity check: every regenerated file exists, correct dimensions, favicon has alpha, splash JPGs are RGB.

- [ ] **Step 4: Commit** — `feat: replace brand assets with the Vectora mark`

---

### Task 2: Frontend copy & app metadata

**Files:**
- Modify: `frontend/index.html:9,11` — `<title>Vectora</title>`, apple-mobile-web-app-title "Vectora"
- Modify: `frontend/vite.config.js:24-28` — manifest `name: 'Vectora'`, `short_name: 'Vectora'`, `description: 'Vectora — proactive, open-source CRM'`; add `theme_color: '#5B5FE8'`, `background_color: '#ffffff'` (built manifest currently inherits Vue-green `#42b883`)
- Modify: `frontend/src/components/Modals/AboutModal.vue:8` — heading `Vectora` (links & copyright stay)
- Modify: `frontend/src/pages/NotPermitted.vue:13` — "…access Vectora. Please contact…"
- Modify: `frontend/src/pages/PersonaForm.vue:108,132` — "How many people will use Vectora?", "Welcome to Vectora"
- Modify: `frontend/src/components/Layouts/AppSidebar.vue:729` — "Vectora mobile"
- Modify: `frontend/src/components/Settings/ERPNextSettings.vue:436` — "Connect ERPNext to Vectora"

- [ ] **Step 1: Apply the seven edits above** (exact strings in file table).
- [ ] **Step 2: Verify** — `grep -rn -i "frappe crm" frontend/src frontend/index.html frontend/vite.config.js` returns nothing.
- [ ] **Step 3: Run unit tests** — `cd frontend && yarn test:run` → 118 pass.
- [ ] **Step 4: Commit** — `feat: rebrand frontend copy and PWA metadata to Vectora`

---

### Task 3: Backend copy & app metadata

**Files:**
- Modify: `crm/hooks.py:2,4` — `app_title = "Vectora"`, `app_description = "Vectora — proactive, open-source CRM"`
- Modify: `crm/__init__.py:2` — `__title__ = "Vectora"`
- Modify: `crm/www/crm.html:9,11` — title + apple-mobile-web-app-title "Vectora"
- Modify: `crm/www/crm.py:18` — `_("You do not have permission to access Vectora")`
- Modify: `crm/templates/emails/crm_invitation.html:1` — "You have been invited to join Vectora"
- Modify: `crm/fcrm/doctype/crm_invitation/crm_invitation.py:42` — `title = "Vectora"`
- Modify: `crm/fcrm/doctype/crm_twilio_settings/crm_twilio_settings.py:30` — `friendly_resource_name = "Vectora"`
- Modify: `crm/fcrm/doctype/erpnext_crm_settings/erpnext_crm_settings.py:130,140` — custom-field label "Vectora Deal"; `:158` — "Could not create the Vectora custom fields on {0}…" **keeping** `<b>Frappe CRM Data Synchronization</b>` verbatim
- Modify: `crm/fcrm/workspace/frappe_crm/frappe_crm.json` — `"label"` and `"title"` → "Vectora"; `"name"` stays "Frappe CRM"

- [ ] **Step 1: Apply the edits above.**
- [ ] **Step 2: Verify** — `grep -rn "Frappe CRM" crm --include="*.py" --include="*.html"` shows only the ERPNext-side setting name and generated files; `python3 -m compileall` the touched .py files.
- [ ] **Step 3: Commit** — `feat: rebrand backend copy and app metadata to Vectora`

---

### Task 4: Residual sweep

- [ ] **Step 1:** `grep -rn -i "frappe crm" /workspace/crm /workspace/frontend --exclude-dir=node_modules` — every remaining hit must be: locale `.po`, `crm/public/frontend/` build output, or the ERPNext-side setting name.
- [ ] **Step 2:** Full test run `cd frontend && yarn test:run` → 118 pass. Record result.
- [ ] **Step 3:** Note in `.pi/PLAN.md` Phase 7A checklist: assets + copy done; locale regeneration and live-site verification need a provisioned bench (not possible in this container).
