# Mobile Client Master Parity & Implementation Tasklist

## 1. Executive Summary & Current State Audit

A comprehensive audit comparing the AHIA Web Application (`web/app/app/`) against the AHIA Mobile Application (`mobile/app/`) reveals critical feature, visual, and architectural gaps. The initial mobile implementation relied on an oversimplified single-file screen (`mobile/app/home.tsx`) containing ASCII placeholder indicators (e.g. `[H]`, `[S]`, `[L]`, `[T]`, `[M]`), lacked dedicated screens, missed the hierarchical Samsung File Manager-style catalog, omitted the multi-select batch action workflow, and did not expose the complete "Everything / More" navigation system.

This document serves as the master specification and execution plan to bring the mobile application to 100% feature and visual parity with the web platform.

---

## 2. Visual Architecture & Design System Gaps

### 2.1 Native Vector Iconography
- [x] Create `mobile/components/icons.tsx` using `react-native-svg` (matching `web/components/icons.tsx` 24px stroke paths).
- [ ] Replace all text placeholder buttons (`[H]`, `[S]`, `[L]`, `[T]`, `[M]`, `[+ Item]`, `[+ Cat]`) with native SVG icons:
  - Bottom Navigation: `ShopIcon`, `ReceiptIcon`, `BoxIcon`, `ListIcon`, `MoreIcon`, `PersonIcon`.
  - Catalog & Lists: `FolderIcon`, `FolderOpenIcon`, `ItemBoxIcon`, `SearchIcon`, `PlusIcon`, `ChevronRightIcon`, `ChevronDownIcon`.
  - State & Actions: `CheckMarkIcon`, `CannotGetIcon`, `ClockIcon`, `TrashIcon`, `CopyIcon`, `EditIcon`, `CloseIcon`, `ShareIcon`, `SyncIcon`, `PhoneIcon`, `SparklesIcon`.

### 2.2 The "Everything / More" Navigation Sheet
- [ ] Implement the full web-parity More Drawer (`web/components/app-shell.tsx` `Sheet open={moreOpen} title="Everything"`):
  - Destination links to all 7 primary areas: The Shop (`/app`), Sales (`/app/sales`), Catalog (`/app/items`), Lists (`/app/lists`), Prices (`/app/prices`), Team (`/app/team`), You/Profile (`/app/profile`).
  - Pinning management: Allow traders to toggle which 3 destinations are pinned to their bottom bar (`ahia.pinned` persisted in local storage/SQLite).
  - Theme switcher: Toggle between Light Mode and Dark Mode.
  - Active business display with role badge.
  - Sign out with confirmation dialog.

---

## 3. Screen-by-Screen Feature Parity Matrix

### 3.1 Catalog & Shelf (`web/app/app/items/page.tsx` vs `mobile/app/home.tsx [Shelf]`)
- [ ] **Samsung File Manager Hierarchical Navigation**:
  - Unlimited category depth (Root -> Parent -> Child -> Subcategory).
  - Active Breadcrumb trail with one-tap ascension (`Home > Cables > Armoured`).
  - Display folder cards showing nested item counts and child category counts.
  - Category cover image support (`ahia-cat-img`).
- [ ] **Dual View Modes**:
  - Folder View (standard drill-down).
  - Visual Branching Tree View (genuine tree diagram with connecting lines, elbows, and leaves).
  - Expand All / Collapse All tree controls.
- [ ] **Multi-Select & Batch Operations**:
  - Multi-select item checkboxes (`selectedProductIds: Set<string>`).
  - Sticky bottom batch action bar:
    - Select All / Clear Selection.
    - "Copy to..." batch duplicator across categories (items automatically inherit destination category default prices).
    - "Move to..." batch mover across categories.
    - Batch Delete items with confirmation.
- [ ] **Product Details & Dual Pricing**:
  - Dual price badges: Retail Normal Price, Wholesale Price, and Pieces per pack.
  - Visual indicators for Category-inherited prices vs Custom Item price overrides.
  - Stock level counters and low-stock warning pills.
  - Add Item modal with dual pricing inputs, pieces-per-pack, and initial stock.
  - Add Category modal with parent category selector and category-level default pricing.
  - Edit Item modal with price override toggles.
  - Restock (`+ Receive Stock`) quick modal.
  - Instant `Sell 1` rapid-checkout action.
- [ ] **Product Photos**:
  - Product photo gallery viewer.
  - Camera / Gallery image upload (`uploadProductImage`).
  - Set Primary photo toggle and remove photo action.

### 3.2 Customer Lists & Waybill Workbench (`web/app/app/lists/page.tsx` & `web/components/list-builder.tsx`)
- [ ] **Interactive Order Reconciliation**:
  - Group list items by category hierarchy (`Category > Subcategory`).
  - Line status toggles:
    - `have_it`: "On the shelf" (green checkmark).
    - `buy_it`: "Going to the market" (orange cart).
    - `cannot_get`: "Cannot get it" (red circle-slash).
    - `somewhere`: "Not looked at yet" (neutral clock).
- [ ] **Cost vs Price Real-Time Margin Arithmetic**:
  - Trader writes cost paid when buying in the market.
  - Trader writes price charged to customer.
  - App calculates line margin automatically without dictating price rules.
- [ ] **Waybill Dispatch Workflow**:
  - Dispatch modal: Transporter name, transporter phone, waybill number, transport cost, and tracking link.
  - Dispatch status confirmation.
- [ ] **Security PIN Gate (`PinGate`)**:
  - Require device PIN / security PIN before confirming high-stakes payouts or final order confirmation.
- [ ] **Direct WhatsApp Quoting**:
  - Generate formatted WhatsApp quote text with itemized prices, total, and bank transfer payment details.
  - Deep-link directly into WhatsApp DM (`https://wa.me/<phone>?text=...`).
- [ ] **Waybill PDF Generation**:
  - Generate printable/shareable Waybill PDF document directly on mobile.
- [ ] **Customer List Builder / Past Lists**:
  - In-app list creation with search across catalog.
  - Quick-paste multi-line order parser (`2x 2.5mm cable\n5x 16A breaker`).
  - Past customer lists lookup.

### 3.3 Sales & Ledger (`web/app/app/sales/page.tsx`)
- [ ] **Dedicated Sales Screen**:
  - Filterable sales list, newest first.
  - Receipt number, timestamp, and payment status badges.
  - Total revenue calculation across period.
  - Sale cancellation with PIN gate.
- [ ] **Record Sale Modal**:
  - Product picker with live catalog search.
  - Quantity selector and custom price override.
  - Payment method selector: Cash, Bank Transfer, Other.
  - Instant receipt generation.
- [ ] **Expenses & Trading Ledger**:
  - Daily expense logging modal: Amount (NGN), Expense Category picker, Description notes, Date.
  - Net profit estimation (Revenue minus Expenses).

### 3.4 Team & Staff Management (`web/app/app/team/page.tsx`)
- [ ] **Staff Member Roster**:
  - Member cards with names, phone numbers, role badges (Owner, Manager, Clerk, Apprentice), and status (Active/Working, Invited, Suspended, Removed).
  - Staff nickname support saved per member.
- [ ] **Role & Status Controls**:
  - Change member role dropdown.
  - Suspend / Re-activate member.
  - Remove member with PIN gate protection.
- [ ] **Invitation Dispatch**:
  - Issue invitation modal: Role selector, phone number, staff name.
  - WhatsApp invite message generator with one-tap link dispatch.
  - Issued invitations list with revoke action.
  - User's pending invitations list with 1-tap Accept action.

### 3.5 Storefront Studio & Profile Settings (`web/app/app/profile/page.tsx`)
- [ ] **Storefront Studio Customizer**:
  - Headline and description editors.
  - Contact phone (WhatsApp) number.
  - Theme brand color picker (`#084a2f`, custom hex).
  - Theme background color picker (`#fbf7f0`, custom hex).
  - Theme background banner image URL / upload.
  - Closing statement note.
  - Live preview toggle.
  - Publish / Unpublish storefront toggle.
  - Share public storefront link.
- [ ] **Business Profile & Stall Settings**:
  - Stall name, market stall address, city, state, official phone.
  - Currency settings.
- [ ] **User Profile**:
  - First name, last name, phone number, email.
- [ ] **Security Credentials**:
  - Password change with strength meter and validation checklist.
  - PIN setup and reset.
- [ ] **Multi-Shop Switcher**:
  - Modal displaying all active businesses with user's specific role in each stall.
  - Join business with invite code / link.

---

## 4. Offline Sync Architecture & SQLite Storage

### 4.1 Local SQLite Schema & Durability
- [x] Product catalog local table (`cached_products`).
- [x] Offline sales outbox table (`pending_sales`).
- [ ] Extend SQLite tables for complete offline operation:
  - `cached_categories` (hierarchical categories with parent_id).
  - `cached_customer_lists` and `cached_customer_list_lines`.
  - `cached_expenses` and `cached_expense_categories`.
  - `cached_inventory` (stock levels and adjustments).
  - `sync_outbox` (generalized mutation queue for offline creates, updates, and deletes).

### 4.2 Conflict Resolution Implementation
- [x] **Append-Only Event Sourcing**: Sales transactions and expense entries are strictly append-only.
- [x] **Additive Deltas**: Stock decrement/increment delta logs avoid race conditions.
- [x] **Last-Write-Wins (LWW) with Timestamps**: Catalog edits, prices, and storefront metadata resolve via ISO timestamps.
- [x] **Interactive User Resolution**: Customer list availability toggling allows trader to review discrepancies.
- [ ] Automatic sync trigger on network reconnection (`NetInfo` listener) and app foregrounding.
- [ ] Visual sync status indicator with itemized outbox count.

---

## 5. Phased Implementation Roadmap

1. **Phase 1: Visual Iconography & Shell Navigation (Immediate)**
   - Integrate `mobile/components/icons.tsx` across `mobile/app/home.tsx`.
   - Eliminate all ASCII `[H]`, `[S]`, `[L]`, `[T]`, `[M]` text placeholders.
   - Expand More tab into the full "Everything" sheet with theme toggling and destination access.

2. **Phase 2: Samsung File Manager Hierarchical Catalog**
   - Implement breadcrumbs, folder cards, and visual tree diagram.
   - Implement multi-select checkboxes and sticky bottom action bar (Copy to..., Move to..., Delete).
   - Implement category-level dual pricing inheritance.

3. **Phase 3: Customer Lists, Waybills & Workbench**
   - Implement line-by-line status toggling (`have_it`, `buy_it`, `cannot_get`).
   - Implement cost vs price margin calculations.
   - Implement dispatch modal and formatted WhatsApp quoting.
   - Implement PIN Gate for high-stakes actions.

4. **Phase 4: Sales Ledger & Team Administration**
   - Implement dedicated sales feed and record sale modal.
   - Implement team invitations, role changes, and nickname management.
   - Implement complete Storefront Studio customization with appearance controls.

5. **Phase 5: Extended Offline SQLite Sync Engine**
   - Extend SQLite schema for categories, lists, and expenses.
   - Implement generalized mutation outbox and auto-sync on network reconnect.
