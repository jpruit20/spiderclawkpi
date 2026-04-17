# ClickUp task-tagging taxonomy — setup runbook

The Spider KPI dashboard grades every task on whether it carries three
**Custom Fields** and flags any closed task that's missing them. Consistent
tagging lets every overlay chart, division filter, and compliance digest
be precise instead of keyword-guessing.

## The taxonomy (create in ClickUp)

ClickUp's API does not expose custom-field *creation* — these need to be
made once in the ClickUp UI. Once they exist, the dashboard finds them by
name and starts grading automatically.

| Field name | Type | Values |
|---|---|---|
| **Division** | Dropdown | `CX` · `Ops` · `Marketing` · `Product/Engineering` · `Finance` · `GA` |
| **Customer Impact** | Dropdown | `Direct` · `Indirect` · `Internal only` |
| **Category** | Dropdown | `Firmware` · `Hardware` · `Website` · `Campaign` · `Fulfillment` · `Returns` · `Support` · `Other` |

Use these **exact** names (case matters for the dashboard match).

## Step 1 — Create the fields workspace-wide

1. ClickUp → **Settings** (top-left avatar) → **ClickApps** → enable **Custom Fields** if not already on.
2. Go to any space → **Space settings** → **Custom Fields** tab → **+ New Custom Field**.
3. Create `Division` as **Dropdown**, add the 6 values above. Scope: **All Spaces** (or Workspace level if your plan supports it).
4. Repeat for `Customer Impact` and `Category`.

Tip: create them once on the *highest* level your plan allows so they cascade
to every list/folder/task. If you only have Space-level scope, repeat the
creation in the second space — the dashboard matches on **name**, not ID, so
two fields with identical names in two spaces still count as the same field.

## Step 2 — Make them required

In ClickUp there are two required modes:

- **Required when task is created** — hard gate, blocks creation.
- **Required when task is closed** — soft friction, only blocks completion.

**Use "required when closed"** for all three fields. It lets people start
a task quickly but forces them to categorize before marking done.

How: on each Custom Field's settings → toggle **"Required when closing"**.

## Step 3 — Pre-fill via task templates (optional but recommended)

For each list (Marketing Calendar, Firmware, NPD, etc.) create a task
template that defaults the Division + Category fields. Saves the team from
picking them manually every time.

Example templates:

- `Marketing Calendar` list → template defaults `Division=Marketing`, `Category=Campaign`
- `Firmware` list → `Division=Product/Engineering`, `Category=Firmware`
- `Continuous Improvement` list → `Division=Product/Engineering`
- `Website Tracker` list → `Division=Marketing`, `Category=Website`
- `Warehouse Questions` channel-sourced → `Division=Ops`, `Category=Fulfillment`

## Step 4 — Backfill existing open tasks

Existing tasks don't have the new fields filled. Two options:

- **Manual sweep** — fastest for <100 tasks. Assign a 30-min block, review open tasks, pick values.
- **Bulk-edit via ClickUp UI** — filter by list, select all, set field in one batch. Good for lists with a natural single Division (e.g. all Firmware tasks → Product/Engineering).

Closed tasks can be left alone; the compliance report grades forward from
the moment fields exist.

## Step 5 — Verify in the dashboard

Once the fields exist, reload any division page → the **Tagging Compliance**
card populates. If it says *"Taxonomy not yet detected"*, the fields either
don't exist yet or aren't named exactly as above. Check spelling / casing.

## Ongoing discipline

- The **Friday AI report** emails a compliance digest: per-person %, top
  offenders, top compliers, trend vs last week.
- Team members who close tasks without required fields are surfaced in
  the dashboard — no auto-DM today (can enable later if discipline slips).
- Dashboard overlay charts swap from keyword-match to field-match
  automatically once fields propagate, making correlation charts much
  cleaner.
