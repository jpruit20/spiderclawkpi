# Kienco ⇄ Spider Dashboard — Odoo Integration Punch List

_Owner: Spider Grills (US) — Joseph Pruitt_
_Counterparty: Kienco (Vietnam) production / IT_
_Purpose: bidirectional integration between Kienco's Odoo ERP and the Spider KPI dashboard so that US-side can read production/inventory/communication state and write responses back into Odoo._

---

## 0. Overview & Recommended Architecture

A bidirectional, secure, least-privilege integration between the Spider KPI dashboard (US) and Kienco's Odoo instance (Vietnam).

- **Reads** = Spider dashboard **pulls** from Odoo on a schedule (every 1–15 min per model) via Odoo's built-in XML-RPC / JSON-RPC API. Stable, requires no custom Odoo development, works on Community or Enterprise.
- **Near-real-time events** = Odoo **pushes webhooks** to the dashboard for high-value events (MO confirmed, MO done, QC failed, delivery done, message posted). Enterprise has native webhooks; Community needs `base_automation` + a small Python server action.
- **Writes** = dashboard calls the same API to post `mail.message` notes, create `mail.activity` tasks, flip custom "US-side approved" fields, upload attachments, etc.
- **Auth** = one **dedicated integration user** (not a human login) with an **API key** (Odoo 14+) and scoped access rights. TLS only. IP-allowlist dashboard egress IPs on Kienco side; IP-allowlist Odoo IPs on Spider side.

Roughly a half-day of setup on Kienco side, no custom module development required.

---

## 1. What Kienco Must Set Up on Their Side

### 1.1 Baseline info to confirm first
- [ ] **Odoo version** (e.g. 16.0, 17.0, 18.0) and **Community or Enterprise**
- [ ] **Hosting model**: Odoo Online (SaaS), Odoo.sh, or self-hosted
- [ ] **Public base URL** of the instance (e.g. `https://kienco.odoo.com` or `https://erp.kienco.vn`)
- [ ] **Database name** (the `db` parameter — required for API auth)
- [ ] **Timezone** configured on the Odoo server (we'll normalize to UTC)

### 1.2 Create a dedicated integration user
- [ ] Create an Internal User named `spider_dashboard_api`, email `dashboard-api@spidergrills.com` (or preferred convention)
- [ ] User type: **Internal User** (not Portal, not Public)
- [ ] **Do not** share credentials with a human; this account is machine-only
- [ ] Attach the access groups below

### 1.3 Access rights / groups on that user

Read access:
- [ ] Manufacturing (`mrp.group_mrp_user` or read-only equivalent)
- [ ] Inventory / Stock (`stock.group_stock_user`)
- [ ] Purchase (`purchase.group_purchase_user`)
- [ ] Sales (`sales_team.group_sale_salesman` — read)
- [ ] Quality (`quality.group_quality_user`) — if installed
- [ ] Maintenance (`maintenance.group_user`) — if installed
- [ ] HR/Timesheets (`hr_timesheet.group_hr_timesheet_user`) — if we care about labor hours
- [ ] Accounting read (invoices/bills only) — optional; confirm

Write access (for responding back):
- [ ] Post messages/attachments on `mail.thread` records (standard for any internal user)
- [ ] Create `mail.activity` (tasks/to-dos) on records
- [ ] Any custom "US approval" / "US review status" fields — grant write

Explicit denies:
- [ ] No Settings / Administration access
- [ ] No ability to create/delete users
- [ ] No access to HR payroll, contracts, salaries
- [ ] No accounting journal posting

### 1.4 Generate an API key for that user
- [ ] Log in as `spider_dashboard_api` → Preferences → **Account Security** → **New API Key**
- [ ] Label it `Spider KPI Dashboard`
- [ ] Copy the key **once** (Odoo only shows it on creation) and deliver via secure channel (see §5)

### 1.5 Enable / confirm the API endpoints are reachable
Odoo exposes XML-RPC and JSON-RPC by default. Confirm these URLs respond from the public internet:
- [ ] `https://<odoo-base>/xmlrpc/2/common` (login / version probe)
- [ ] `https://<odoo-base>/xmlrpc/2/object` (model calls)
- [ ] `https://<odoo-base>/jsonrpc` (JSON-RPC alternative)
- [ ] `https://<odoo-base>/web/database/list` — confirm whether it's disabled (common hardening); if so, supply the db name explicitly

### 1.6 Webhooks (recommended)

For each event type below, Kienco sets up an **Automated Action** (Settings → Technical → Automation) or an Enterprise native Webhook.

Events to push to Spider dashboard:
- [ ] `mrp.production` — state transitions to `confirmed`, `progress`, `done`, `cancel`
- [ ] `stock.picking` — state becomes `done` (outbound shipment to US)
- [ ] `purchase.order` — state becomes `purchase` (confirmed), `done`
- [ ] `quality.check` — result is `fail`
- [ ] `mail.message` — when a message is posted on any of the above models AND `author_id != spider_dashboard_api` (avoid loops)

Per-event setup:
- [ ] Trigger: "On Update" (state change) or "On Creation"
- [ ] Action: "Execute Python Code" OR (Enterprise 17+) native Webhook
- [ ] Target URL: **Spider will provide** (e.g. `https://kpi.spidergrills.com/api/webhooks/odoo/<event>`)
- [ ] Auth: include header `X-Spider-Signature: <HMAC-SHA256 of body using shared secret>` — Spider supplies the secret
- [ ] Payload JSON: `model`, `record_id`, `event`, `state_before`, `state_after`, `write_date`, `user_id`

If on Community and they'd rather not write Python, Spider will supply a ~10-line `requests.post()` snippet.

### 1.7 Network / firewall
- [ ] Confirm Odoo instance is reachable over HTTPS from US IPs
- [ ] Provide **Odoo public IP(s)** so Spider can allowlist them for inbound webhooks
- [ ] Accept Spider's **dashboard egress IPs** (provided separately) on Kienco firewall if Odoo API is IP-restricted (recommended)
- [ ] Confirm TLS cert is valid (no self-signed) — required for webhook signing

### 1.8 Custom fields, custom modules, Kienco-specific extensions
- [ ] List of **installed custom modules** (Apps → filter "Installed", untick "Apps" filter to see everything)
- [ ] For each model in §3, **technical names** of any custom fields (e.g. `x_kienco_lot_code`, `x_us_approval_status`)
- [ ] Custom `selection` field values (exact keys, not translated labels)
- [ ] Screenshots of the MO, Picking, and PO forms for visual field mapping

### 1.9 Sample data for integration tests
- [ ] 1 real **Manufacturing Order ID** safe to read repeatedly
- [ ] 1 real **Stock Picking ID** for an outbound shipment to the US
- [ ] 1 real **Purchase Order ID**
- [ ] 1 **test product** (dummy SKU) safe for test messages/activities without disturbing real workflow
- [ ] Confirmation that posting `mail.message` as `spider_dashboard_api` notifies the right Kienco followers

---

## 2. What Kienco Hands Back to Spider

| # | Item | Example / Format |
|---|---|---|
| 1 | Odoo base URL | `https://erp.kienco.vn` |
| 2 | Database name | `kienco-prod` |
| 3 | Odoo version + edition | `17.0 Enterprise` |
| 4 | Integration user login | `spider_dashboard_api` |
| 5 | Integration user API key | 40-char token (secure channel) |
| 6 | Integration user numeric uid | e.g. `147` (Spider can self-fetch given creds) |
| 7 | List of installed modules | CSV or screenshot |
| 8 | Custom field map for §3 models | table: model → field name → type → meaning |
| 9 | Confirmed webhook URLs registered | row per event with target URL + trigger |
| 10 | Odoo server public IP(s) | for Spider inbound allowlist |
| 11 | Confirmation Spider egress IPs allowlisted | yes/no + date |
| 12 | Integration contact | name, email, WhatsApp/Zalo, timezone |
| 13 | Sample record IDs per §1.9 | integers |
| 14 | Webhook shared secret acknowledgement | confirm received and installed |

---

## 3. Data Scope — What Spider Will Read

All reads via `execute_kw('<model>', 'search_read', ...)`.

**Manufacturing**
- `mrp.production` (MOs): state, product_id, product_qty, qty_produced, date_planned_start, date_planned_finished, date_start, date_finished, origin, company_id, workorder_ids
- `mrp.workorder`: state, duration, duration_expected, workcenter_id, operator
- `mrp.bom`, `mrp.bom.line` (BOM explosion, cost rollups)
- `mrp.workcenter`: capacity, oee
- Custom "ship-ready", "US-approved", or "lot" fields (§1.8)

**Inventory / Shipping**
- `stock.picking`: state, scheduled_date, date_done, partner_id, origin, carrier_id, carrier_tracking_ref
- `stock.move`, `stock.move.line`: product_id, product_uom_qty, quantity_done, lot_id
- `stock.quant`: on-hand by location and lot
- `stock.lot`: serials/lots, expiration, quality

**Purchasing**
- `purchase.order`, `purchase.order.line`: supplier lead times, open POs, receipts

**Sales / Demand signal from US → Kienco**
- `sale.order`, `sale.order.line` (intercompany or customer orders feeding production)

**Quality**
- `quality.check`, `quality.alert` (if module installed)

**Communication**
- `mail.message` on the above records — internal notes Kienco posts
- `mail.activity` — open to-dos / questions assigned to US or them
- `ir.attachment` — photos, PDFs, QC reports

**Operational**
- `res.users` and `hr.employee` for attribution (read-only, no sensitive HR)

---

## 4. Write-back Scope — What Spider Will Push Into Odoo

All writes go through standard Odoo methods so audit trails are preserved.

- [ ] `mail.message.post` on MO/PO/Picking to reply to Kienco questions — visible in chatter
- [ ] `mail.activity.create` to raise a to-do on a Kienco user ("please confirm lot X before ship")
- [ ] Update custom `x_us_approval_status` / `x_us_ship_release` fields when US clears a shipment
- [ ] Upload `ir.attachment` (e.g. US-side QA sign-off PDF)
- [ ] Mark `mail.activity` done when Spider has answered
- [ ] (Optional, later) create draft `stock.picking` / `sale.order` — **out of scope for v1**, flag explicitly

---

## 5. Security & Secrets Handling

- [ ] API key delivered via **1Password shared vault** or **Bitwarden Send** (one-time link) — **never email or Slack**
- [ ] Webhook shared secret delivered same way, generated by Spider (32 bytes, base64)
- [ ] Rotate both every 12 months, or immediately if any Kienco or Spider operator with access leaves
- [ ] All traffic HTTPS / TLS 1.2+; reject plain HTTP on both sides
- [ ] Spider verifies HMAC on every inbound webhook and drops unsigned calls
- [ ] Rate limit on Spider's inbound webhook endpoint
- [ ] Kienco adds Spider egress IPs to Odoo firewall allowlist
- [ ] Spider stores the API key in its existing secrets store (same place as Shopify/Triple Whale/Freshdesk keys); not in repo

---

## 6. Process / Timeline (suggested)

1. **Day 0** — Spider sends this sheet + Spider egress IPs + webhook secret
2. **Day 1–2 (Kienco)** — complete §1.1–§1.5 and return items 1–8 from §2
3. **Day 3 (Spider)** — stand up read-only connector, validate with sample IDs, surface in source-health page
4. **Day 4 (Kienco)** — complete §1.6 webhooks for the agreed event list
5. **Day 5 (Spider)** — validate webhook receipt + signature verification
6. **Day 6 (Spider)** — enable write-back on the test product from §1.9; Kienco confirms chatter message and activity appear
7. **Day 7** — go live on real records, with an allowlist of models safe to write to
8. **Week 2** — Spider exposes Kienco source-health and first Kienco KPI tiles on the dashboard

---

## 7. Test / Acceptance Checklist (run together)

- [ ] `common.authenticate(db, login, key, {})` returns a numeric uid
- [ ] `search_read` on `mrp.production` returns the sample MO
- [ ] `search_read` on `stock.picking` returns the sample picking
- [ ] A test `mail.message.post` from Spider appears in Kienco chatter within 5s
- [ ] A test `mail.activity.create` raises a task on the named Kienco user
- [ ] A state change on the test MO triggers a webhook to Spider within 30s with valid signature
- [ ] A message posted by Kienco on the test MO appears in the dashboard within the next poll cycle
- [ ] Source-health page shows Kienco as `healthy` with last-success timestamps

---

## 8. Open Questions to Ask Kienco Up Front

1. Which Odoo version and edition are you on?
2. Is the instance Odoo Online, Odoo.sh, or self-hosted?
3. Which of these modules are installed: MRP, Quality, Maintenance, Timesheets, Barcode, PLM?
4. Do you currently have any other external integrations using the API? (avoid collisions with an existing user/key)
5. Who is the technical point of contact and in which timezone / chat channel?
6. Any constraints on API call volume or off-hours maintenance windows to respect?
