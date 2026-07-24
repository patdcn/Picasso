-- ============================================================
--  DCN CALCULATION MODULE - calc.db - Schema Rev 7
--  Base currency: USD. All consolidated totals normalised to USD
--  via the fx snapshot embedded in each revision.
--  PRAGMA user_version marks the schema revision for migrations.
-- ============================================================

PRAGMA user_version = 7;

-- ---------------- dimensions ----------------

CREATE TABLE IF NOT EXISTS divisions (
    code TEXT PRIMARY KEY, name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regions (
    code TEXT PRIMARY KEY, name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS currencies (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, symbol TEXT
);

-- ---------------- rate sets (library versioning) ----------------

CREATE TABLE IF NOT EXISTS rate_sets (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,                 -- '2026-H1'
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','active','archived')),
    effective_from TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    id INTEGER PRIMARY KEY,
    rate_set_id INTEGER NOT NULL REFERENCES rate_sets(id) ON DELETE CASCADE,
    currency TEXT NOT NULL REFERENCES currencies(code),
    rate_to_usd REAL NOT NULL,                  -- 1 unit of currency = X USD
    UNIQUE (rate_set_id, currency)
);

-- ---------------- libraries ----------------
-- Items are division-scoped (separate ERP numbers per division);
-- rates vary by region x rate set only.

CREATE TABLE IF NOT EXISTS equipment_items (
    uuid TEXT PRIMARY KEY,
    erp_no TEXT UNIQUE,
    code TEXT NOT NULL UNIQUE,                  -- 'EQ-OFF-0042'
    division TEXT NOT NULL REFERENCES divisions(code),
    description TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'day',
    ownership TEXT NOT NULL DEFAULT 'internal'
        CHECK (ownership IN ('internal','external')),
    region TEXT NOT NULL DEFAULT 'ALL' REFERENCES regions(code),
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS equipment_rates (
    id INTEGER PRIMARY KEY,
    item_uuid TEXT NOT NULL REFERENCES equipment_items(uuid) ON DELETE CASCADE,
    rate_set_id INTEGER NOT NULL REFERENCES rate_sets(id) ON DELETE CASCADE,
    currency TEXT NOT NULL REFERENCES currencies(code),
    rate REAL NOT NULL,
    UNIQUE (item_uuid, rate_set_id)
);

CREATE TABLE IF NOT EXISTS personnel_items (
    uuid TEXT PRIMARY KEY,
    erp_no TEXT UNIQUE,
    code TEXT NOT NULL UNIQUE,                  -- 'PER-OFF-0007'
    division TEXT NOT NULL REFERENCES divisions(code),
    function TEXT NOT NULL,
    ownership TEXT NOT NULL DEFAULT 'internal'
        CHECK (ownership IN ('internal','external')),
    unit TEXT NOT NULL DEFAULT 'day',
    region TEXT NOT NULL DEFAULT 'ALL' REFERENCES regions(code),
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS personnel_rates (
    id INTEGER PRIMARY KEY,
    item_uuid TEXT NOT NULL REFERENCES personnel_items(uuid) ON DELETE CASCADE,
    rate_set_id INTEGER NOT NULL REFERENCES rate_sets(id) ON DELETE CASCADE,
    currency TEXT NOT NULL REFERENCES currencies(code),
    office_rate REAL, yard_rate REAL, offshore_rate REAL,
    UNIQUE (item_uuid, rate_set_id)
);

-- Misc sub-categories: admin-manageable; each maps to one of the two
-- non-labor/non-equipment elements so library picks prefill correctly.
CREATE TABLE IF NOT EXISTS misc_categories (
    name TEXT PRIMARY KEY,
    element TEXT NOT NULL CHECK (element IN ('materials','subcontracting')),
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS misc_items (
    uuid TEXT PRIMARY KEY,
    erp_no TEXT UNIQUE,
    code TEXT NOT NULL UNIQUE,                  -- 'MSC-OFF-0013'
    division TEXT NOT NULL REFERENCES divisions(code),
    category TEXT NOT NULL,                     -- travel/fuel/gas/accommodation/service
    description TEXT NOT NULL,
    unit TEXT NOT NULL,
    ownership TEXT NOT NULL DEFAULT 'internal'
        CHECK (ownership IN ('internal','external')),
    region TEXT NOT NULL DEFAULT 'ALL' REFERENCES regions(code),
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS misc_rates (
    id INTEGER PRIMARY KEY,
    item_uuid TEXT NOT NULL REFERENCES misc_items(uuid) ON DELETE CASCADE,
    rate_set_id INTEGER NOT NULL REFERENCES rate_sets(id) ON DELETE CASCADE,
    currency TEXT NOT NULL REFERENCES currencies(code),
    rate REAL NOT NULL,
    UNIQUE (item_uuid, rate_set_id)
);

-- Markups: division x region per rate set. Percentages as fractions.
CREATE TABLE IF NOT EXISTS markup_sets (
    id INTEGER PRIMARY KEY,
    rate_set_id INTEGER NOT NULL REFERENCES rate_sets(id) ON DELETE CASCADE,
    division TEXT NOT NULL REFERENCES divisions(code),
    region TEXT NOT NULL REFERENCES regions(code),
    levy_local_pct REAL NOT NULL DEFAULT 0,
    levy_expat_pct REAL NOT NULL DEFAULT 0,
    profit_pct REAL NOT NULL DEFAULT 0,
    risk_pct REAL NOT NULL DEFAULT 0,
    overhead_pct REAL NOT NULL DEFAULT 0,
    margin_pct REAL NOT NULL DEFAULT 0,
    labor_pct REAL NOT NULL DEFAULT 0,          -- element markups (grid col O)
    equipment_pct REAL NOT NULL DEFAULT 0,
    materials_pct REAL NOT NULL DEFAULT 0,
    subcon_pct REAL NOT NULL DEFAULT 0,
    UNIQUE (rate_set_id, division, region)
);

-- Curated building-block templates (division-scoped; land here ONLY via an
-- approved check-in request). payload_json = serialized block subtree with
-- library uuids, structure, qty/duration/basis/origin per line.
CREATE TABLE IF NOT EXISTS block_templates (
    uuid TEXT PRIMARY KEY,
    division TEXT NOT NULL REFERENCES divisions(code),
    name TEXT NOT NULL,
    unit_label TEXT NOT NULL DEFAULT 'day',
    payload_json TEXT NOT NULL,
    source_qnumber TEXT,
    created_by TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (division, name)
);

-- ---------------- moderation (check-in requests) ----------------
-- Estimators submit; lib_admin approves; approval writes to the library.

CREATE TABLE IF NOT EXISTS library_requests (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN
        ('equipment_item','personnel_item','misc_item','materials_item',
         'subcontracting_item','rate_change','block_template')),
    division TEXT NOT NULL REFERENCES divisions(code),
    payload_json TEXT NOT NULL,                 -- proposed item / rates / block
    note TEXT,
    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted','approved','rejected')),
    submitted_by TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_by TEXT, reviewed_at TEXT, review_note TEXT
);

-- ---------------- calculations & revisions ----------------

CREATE TABLE IF NOT EXISTS calculations (
    qnumber TEXT PRIMARY KEY
        -- EUR/SEA tenders: Q0XXXX - WAF/UAE tenders: UQ0XXXX
        CHECK (qnumber GLOB 'Q0[0-9][0-9][0-9][0-9]'
               OR qnumber GLOB 'UQ0[0-9][0-9][0-9][0-9]'),
    title TEXT NOT NULL,
    client TEXT,
    division TEXT NOT NULL REFERENCES divisions(code),
    region TEXT NOT NULL REFERENCES regions(code),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY,
    qnumber TEXT NOT NULL REFERENCES calculations(qnumber) ON DELETE CASCADE,
    rev_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'working'
        CHECK (status IN ('working','issued')),
    remark TEXT,
    rate_set_label TEXT,                        -- provenance of the snapshot
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    issued_by TEXT, issued_at TEXT,
    UNIQUE (qnumber, rev_no)
);

-- Issued = immutable, hard rule. The single permitted transition is the act
-- of issuing itself (working -> issued); after that nothing may change.
CREATE TRIGGER IF NOT EXISTS trg_revision_issued_lock
BEFORE UPDATE ON revisions
WHEN OLD.status = 'issued'
BEGIN
    SELECT RAISE(ABORT, 'Issued revision is immutable');
END;

-- ---------------- embedded snapshots ----------------

CREATE TABLE IF NOT EXISTS snap_fx (
    id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    currency TEXT NOT NULL,
    rate_to_usd REAL NOT NULL,
    UNIQUE (revision_id, currency)
);

CREATE TABLE IF NOT EXISTS snap_markups (
    id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    levy_local_pct REAL NOT NULL DEFAULT 0, levy_expat_pct REAL NOT NULL DEFAULT 0,
    profit_pct REAL NOT NULL DEFAULT 0, risk_pct REAL NOT NULL DEFAULT 0,
    overhead_pct REAL NOT NULL DEFAULT 0, margin_pct REAL NOT NULL DEFAULT 0,
    labor_pct REAL NOT NULL DEFAULT 0,
    equipment_pct REAL NOT NULL DEFAULT 0,
    materials_pct REAL NOT NULL DEFAULT 0,
    subcon_pct REAL NOT NULL DEFAULT 0,
    UNIQUE (revision_id)
);

CREATE TABLE IF NOT EXISTS snap_items (
    id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    lib TEXT NOT NULL CHECK (lib IN ('equipment','personnel','misc')),
    item_uuid TEXT NOT NULL,                    -- source library uuid (refresh diff)
    erp_no TEXT, code TEXT NOT NULL, description TEXT NOT NULL,
    unit TEXT, ownership TEXT,
    currency TEXT NOT NULL,
    rate REAL,                                  -- equipment / misc
    office_rate REAL, yard_rate REAL, offshore_rate REAL,   -- personnel
    rate_set_label TEXT,                        -- provenance: '2026-H1'
    imported_from TEXT,                         -- Q-number if merged in via block import
    UNIQUE (revision_id, item_uuid)
);

-- ---------------- block tree ----------------
-- kind master  : exactly one per revision (tender total)
-- kind package : structural node (Platform A, Mobilisation, ...)
-- kind block   : reusable sub-calculation with a UNIT price; a reference
--                to it multiplies ALL its element subtotals by qty.

CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES blocks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('master','package','block')),
    name TEXT NOT NULL,
    unit_label TEXT NOT NULL DEFAULT 'day',     -- 'day','lump','per platform',...
    qty REAL NOT NULL DEFAULT 1,                -- level multiplier (Excel col I)
    sort_order INTEGER NOT NULL DEFAULT 0,
    start_date TEXT, end_date TEXT,             -- cash-flow phasing (later phase)
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_blocks_rev ON blocks(revision_id, parent_id);

CREATE TABLE IF NOT EXISTS block_lines (
    id INTEGER PRIMARY KEY,
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    element TEXT NOT NULL CHECK (element IN
        ('labor','subcontracting','materials','equipment')),
    snap_item_id INTEGER REFERENCES snap_items(id) ON DELETE SET NULL,
    description TEXT,                           -- free text / override
    qty REAL NOT NULL DEFAULT 1,
    duration REAL NOT NULL DEFAULT 1,
    rate_basis TEXT NOT NULL DEFAULT 'unit'
        CHECK (rate_basis IN ('office','yard','offshore','unit')),
    unit_rate_override REAL,                    -- NULL = snapshot rate
    ownership TEXT CHECK (ownership IN ('internal','external')),  -- labor/equipment split
    origin TEXT NOT NULL DEFAULT 'local'
        CHECK (origin IN ('local','expat')),
    subcat TEXT,                                -- materials/subcon sub-category
    unit TEXT,                                  -- free-line unit (library lines
                                                -- take the snapshot's unit)
    remarks TEXT,
    markup_override REAL,                       -- NULL = element default applies
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lines_block ON block_lines(block_id);

CREATE TABLE IF NOT EXISTS block_refs (
    id INTEGER PRIMARY KEY,
    host_block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    ref_block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    qty REAL NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    CHECK (host_block_id <> ref_block_id)
);
CREATE INDEX IF NOT EXISTS idx_refs_host ON block_refs(host_block_id);

-- ---------------- edit journal (undo/audit/autosave/live view) ----------------

CREATE TABLE IF NOT EXISTS edit_journal (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id INTEGER NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    user TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    delta_json TEXT NOT NULL,                   -- {'table','pk','before','after'}
    undone INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_journal_rev ON edit_journal(revision_id, seq);

-- ---------------- locks (one estimator per Q number) ----------------

CREATE TABLE IF NOT EXISTS locks (
    qnumber TEXT PRIMARY KEY REFERENCES calculations(qnumber) ON DELETE CASCADE,
    user TEXT NOT NULL,
    acquired_at TEXT NOT NULL DEFAULT (datetime('now')),
    heartbeat_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------- module roles ------------------------------------------
-- Two calc roles on top of the portal's per-page access grants:
--   user  : may create/edit calculations
--   super : moderator/super-user - everything a user can, plus the check-in
--           queue, currencies & FX, rate sets, sub-categories, backups
-- Portal admins have super rights implicitly. Page access without a role =
-- read-only. Lives in calc.db; auth.db stays untouched.

CREATE TABLE IF NOT EXISTS calc_roles (
    user TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('user','super'))
);
