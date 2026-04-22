# Kienco Odoo Integration — One-Pager for Kienco to Complete & Return

_Please fill this sheet in and return to Joseph at Spider Grills. Expected effort on your side: ~half a day. Full context and setup detail is in the companion document `odoo_kienco_integration_punchlist.md`._

---

## A. Questions to Answer Up Front

1. **Odoo version and edition?** (e.g. 17.0 Enterprise)
   → _______________________________________________

2. **Hosting model?** (Odoo Online / Odoo.sh / self-hosted)
   → _______________________________________________

3. **Which modules are installed?** (tick all that apply)
   - [ ] MRP
   - [ ] Quality
   - [ ] Maintenance
   - [ ] Timesheets
   - [ ] Barcode
   - [ ] PLM
   - [ ] Other: ________________________________

4. **Any other external API integrations currently active?** (so we don't collide with an existing user or key)
   → _______________________________________________

5. **Technical point of contact for this integration**
   - Name: _______________________________________
   - Email: ______________________________________
   - WhatsApp / Zalo: ____________________________
   - Timezone: ___________________________________

6. **Constraints on API call volume or maintenance windows to respect?**
   → _______________________________________________

---

## B. Items to Return to Spider

| # | Item | Value |
|---|---|---|
| 1 | Odoo base URL | |
| 2 | Database name | |
| 3 | Odoo version + edition | |
| 4 | Integration user login | `spider_dashboard_api` (unless you used a different name) |
| 5 | Integration user API key | _deliver via 1Password / Bitwarden Send — not email or Slack_ |
| 6 | Integration user numeric uid | |
| 7 | List of installed modules | attach CSV or screenshot |
| 8 | Custom field map for MRP / Stock / Purchase models | attach table: model → field technical name → type → meaning |
| 9 | Confirmed webhook URLs registered | list each event + target URL |
| 10 | Odoo server public IP(s) | |
| 11 | Spider egress IPs allowlisted on your firewall? | yes / no + date |
| 12 | Sample Manufacturing Order ID (safe to read repeatedly) | |
| 13 | Sample Stock Picking ID (outbound to US) | |
| 14 | Sample Purchase Order ID | |
| 15 | Test product / dummy SKU we can safely message | |
| 16 | Webhook shared secret acknowledgement (received & installed) | yes / no |

---

## C. What Spider Will Send You First

- Two Spider egress IP addresses to allowlist on your side
- Webhook target URLs (one per event) to register in your Automated Actions
- Webhook shared secret (via 1Password or Bitwarden Send)
- A ~10-line Python snippet for the Automated Action body if you're on Community edition

Return this completed sheet and the API key through the secure channel Spider provides. Spider will then run the acceptance tests listed in §7 of the full punch list and confirm back when the integration is live.
