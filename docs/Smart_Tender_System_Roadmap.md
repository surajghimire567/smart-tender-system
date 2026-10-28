# Smart Tender System (Auction-Based Bidding)
## Finalized Project Roadmap — 8-Week Plan
### BSc CSIT, 6th Semester — E-Governance Group Project

---

## 1. Project Summary

**Title:** Smart Tender System with Reverse-Auction Bidding
**Domain:** E-Governance (G2B — Government to Business)
**Team size:** 4 members
**Duration:** 8 weeks
**Case study reference:** Nepal's e-Procurement system (bolpatra.gov.np), operated by the Public Procurement Monitoring Office (PPMO)

**One-line description:** A web-based platform where government departments publish tenders, registered vendors submit competitive bids, and the system automatically ranks bids lowest-to-highest (reverse auction) to support transparent, corruption-resistant contract awarding.

**Evidence-based problem grounding:** This project is grounded in a real, documented case — the 2026 CIB investigation into Nepal's e-GP system, where 313 contracts had bid rates illegally altered by an insider exploiting readable, editable, unmonitored bid data (myRepublica, The Rising Nepal). Your system targets 5 of the 13 documented loopholes from that case (see Section 2).

---

## 2. Finalized MVP Feature List (Locked Scope — Do Not Expand Mid-Project)

### 2.1 Base Functional Features

| # | Feature | Owner Role |
|---|---------|-----------|
| 1 | Admin: create tender (title, description, deadline, base/ceiling price) | Admin module |
| 2 | Admin: publish tender, close manually or auto-close at deadline | Admin module |
| 3 | Vendor: register + login (basic auth, no OTP/2FA) | Vendor module |
| 4 | Vendor: view open tenders list + detail page | Vendor module |
| 5 | Vendor: place a bid on an open tender | Auction engine |
| 6 | Auction engine: reverse-auction ranking — live list of bids sorted lowest-to-highest | Auction engine |
| 7 | Admin: view final ranked list, select/award winner | Admin module |

### 2.2 Loophole-Targeted Features (your project's core differentiator — do not cut these)

Each feature below maps directly to a documented, evidence-backed failure from the Nepal e-GP case brief. This mapping is what makes your problem statement and solution airtight in the report.

| # | Loophole Addressed (from case brief) | Feature You Build | Owner Role |
|---|---|---|---|
| L1 | Bids stored/readable before opening — anyone with DB/server access could read rates pre-opening | **Encrypted bid storage**: bid amounts encrypted at rest (e.g. AES); decryption/display only happens server-side after tender deadline passes | Auction engine |
| L2 | Bids remained editable after submission — a stored rate could simply be overwritten | **Insert-only bids table**: no UPDATE allowed on submitted bids; a "revision" is a new row referencing the old one, never an overwrite. Each bid returns a hash "receipt" to the vendor at submission | Auction engine |
| L6 | No monitored audit trail — the breach was found via outside complaint, not the system itself | **Append-only audit log**: every create/bid/award/view action is logged with timestamp + actor ID, visible to admin as a transparency/audit dashboard | DB/Reporting |
| L9 | Credentials were transferable — username/password alone let anyone act as a bidder, no binding to a person/device | **Session-device binding**: log IP/device fingerprint at login and bid submission; flag in the audit log if the same account submits from unusual/differing devices in a short window | Vendor module |
| L10 | No anti-collusion analytics — repeated narrow undercutting by connected firms produced an obvious pattern nobody watched for | **Rule-based collusion flagging**: flag bids that repeatedly land within 1–2% of another specific vendor's bid across multiple tenders, or vendors winning an unusually high share of tenders entered; surfaced on admin dashboard | Auction engine / DB |

**Explicitly out of scope (mention only as "future scope" in report, with reference to which loophole they'd address):**
- Full cryptographic multi-party key-split sealing (L1's ideal real-world fix) — you implement a simplified single-key encryption version instead
- PKI hardware tokens / MFA (L5, L9's ideal fix) — you implement device/session binding as a lighter proxy
- Anti-phishing/portal authenticity protections (L8)
- Server/infra hardening, code-signing, penetration testing (L4)
- Insider background vetting, role rotation policy (L3, L7)
- Document/KYC upload and verification
- Real payment gateway / EMD collection
- SMS notifications
- Anti-sniping auto-extend timer (add back only if ahead of schedule, see Week 6 buffer note)
- Vendor blacklist/rating system
- WebSocket real-time push (use polling/refresh instead)
- Multi-department G2G simulation

**How to state this in your report (use near-verbatim):**
*"Of the 13 loopholes identified across the documented Nepal e-GP incidents, this project targets 5 (L1, L2, L6, L9, L10) that are addressable at the application layer within an academic timeframe. The remaining loopholes require infrastructure-level security hardening, institutional/legal reform, or organizational policy change, and are discussed as future scope."*

---

## 3. Team Role Assignment

| Person | Role | Responsibilities |
|--------|------|------------------|
| Person 1 | Admin Module Lead | Tender creation, publish/close logic, award action, admin dashboard, collusion-flag display (L10) |
| Person 2 | Vendor Module Lead | Registration, login/auth, tender browsing UI, bid submission form, device/session binding (L9) |
| Person 3 | Auction Engine Lead | Bid ranking logic, encrypted bid storage (L1), insert-only bids + hash receipts (L2), collusion-flag logic (L10) |
| Person 4 | Database & Documentation Lead | DB schema, ER/DFD/use-case diagrams, append-only audit log (L6), report compilation |

*Note: all 4 should co-author the report and case-study section — don't let it fall on one person in week 7-8.*

---

## 4. Tech Stack (Finalized — Do Not Change After Week 2)

- **Frontend:** React (with plain `useState`/`useEffect` — no Redux, no extra state libraries)
- **Backend:** FastAPI (Python)
- **Database:** MySQL or PostgreSQL
- **Auth:** Simple session/JWT-based login, bcrypt for password hashing
- **Encryption (for L1):** Python `cryptography` library (Fernet symmetric encryption is sufficient — no need for real multi-party key splitting)
- **Hosting/Demo:** Local demo is fine; optionally deploy free tier (Render/Railway/Vercel) for viva convenience
- **Version control:** Git + GitHub (shared repo, one branch per person, merge into `main` weekly)

**Note on this stack choice:** React + FastAPI is a deliberate learning-oriented choice (per team discussion) over the faster Node/Express + vanilla JS option. This adds real ramp-up time — see the extended Week 1-2 schedule below, and the trimmed scope in Section 2 that compensates for it.

---

## 5. Database Schema Outline (starting point for Person 4 to formalize)

**Users** (id, name, email, password_hash, role[admin/vendor], company_name, registration_number, created_at)

**Tenders** (id, title, description, base_price, ceiling_price, deadline, status[draft/published/closed/awarded], created_by, created_at)

**Bids** (id, tender_id, vendor_id, bid_amount_encrypted, bid_hash, device_fingerprint, ip_address, submitted_at) — insert-only, addresses L1 (encrypted), L2 (no update, hash receipt), L9 (device/IP captured)

**Awards** (id, tender_id, winning_bid_id, awarded_at)

**AuditLog** (id, tender_id, vendor_id, action, timestamp, ip_address) — append-only, addresses L6

**CollusionFlags** (id, tender_id, vendor_id_a, vendor_id_b, flag_reason, flagged_at) — addresses L10, populated by the rule-based check whenever a new bid is submitted

---

## 6. Week-by-Week Roadmap

*(Adjusted for React + FastAPI, which needs a real ramp-up — Week 1 now includes dedicated learning time on top of planning.)*

### Week 1 — Foundation, Case Study Research & Stack Ramp-Up
**Goal:** Everyone aligned on scope and evidence base, and comfortable with basic React/FastAPI syntax before Week 2 design work starts.

- Finalize and lock the MVP feature list above, including the 5 loophole-targeted features (group meeting, 1 session)
- Research Nepal's e-GP case brief in depth — the team already has the 13-loophole breakdown; assign one person to re-read and summarize each of the 3 source incidents (2026 CIB hacking case, myRepublica + Rising Nepal reports, CIJ cartel report) for the report's case-study section
- Map project to E-Governance theory: confirm G2B model, transactional maturity stage
- Draft problem statement (grounded in the 313-contract case), objectives, scope, and limitations section for the report
- Set up shared GitHub repo, decide branching strategy
- Everyone individually: complete a basic FastAPI "Hello World" endpoint + a basic React "Hello World" page fetching from it — this is non-negotiable groundwork, don't skip to feature work without it
- Finalize tech stack (Section 4) — no changes allowed after this week

**Deliverable by end of Week 1:** Locked feature list with loophole mapping, case study notes (2-3 pages covering all 3 source incidents), GitHub repo created with README, everyone has a working FastAPI+React "Hello World" on their machine

---

### Week 2 — Design Phase
**Goal:** All diagrams and schema done before real feature coding starts.

- ER diagram (based on Section 5 schema, including encrypted bid fields, audit log, collusion flags)
- DFD Level 0 and Level 1
- Use case diagram (Actors: Admin, Vendor; Use cases: create tender, place bid, award tender, view audit log, view collusion flags)
- Sequence diagram for the bidding process (vendor submits bid → encrypted + hashed → stored insert-only → audit logged → ranking updates on deadline)
- System architecture diagram (3-tier: React client, FastAPI server, MySQL/PostgreSQL database)
- Set up project folder structure (FastAPI backend + React frontend as separate folders/repos or a monorepo — team's choice), install dependencies, create base auth boilerplate (login/register skeleton in both)

**Deliverable by end of Week 2:** All 5 diagrams finalized, repo has working skeleton (React auth pages render and hit FastAPI auth endpoints, DB connected)

---

### Week 3 — Core Development Start (Parallel Work)
**Goal:** Each module owner starts independently; integrate small pieces early to avoid week-6 surprises.

- Person 1: Tender creation form + admin dashboard (list of tenders with status)
- Person 2: Vendor registration/login, tender listing page for vendors; start device/IP fingerprint capture on login (L9 groundwork)
- Person 3: Bids table setup with encryption at rest (L1) and insert-only design (L2) — this is the most technically involved piece, start early
- Person 4: DB migrations, seed test data, audit log table + basic logging middleware (L6); start drafting report Chapter 1-2

**Deliverable by end of Week 3:** Admin can create a tender, vendor can register/login (with device/IP captured) and see tenders listed

---

### Week 4 — Core Development Continued
**Goal:** Bidding flow functional end-to-end, loophole features taking shape.

- Person 1: Publish/close tender logic, deadline handling
- Person 2: Complete bid submission form with validation; wire device/IP binding into the bid submission itself, not just login (L9)
- Person 3: Bid hash-receipt generation on submission (L2), decrypt-after-deadline logic (L1), ranking logic — sort bids ascending, display ranked list (polling/refresh, not sockets)
- Person 4: Audit log wired into every action (create/bid/award/view) (L6); continue report writing

**Deliverable by end of Week 4:** Vendor can submit an encrypted, hash-receipted bid; audit log captures the action; admin/vendor can see a ranked list after deadline

---

### Week 5 — Feature Completion, Including Collusion Detection
**Goal:** All base + loophole-targeted features working individually before integration week.

- Person 1: Award action (admin selects winner from ranked list, tender status → "awarded"); collusion-flag display on admin dashboard (L10)
- Person 2: Polish vendor dashboard (my bids, my status, my hash receipts)
- Person 3: Build the rule-based collusion check (L10) — triggers on each new bid: check for repeated 1-2% undercutting patterns between the same two vendors across tenders, write result to CollusionFlags table
- Person 4: Finalize audit log completeness and admin-facing audit view; continue report (Chapter 3: System Design with diagrams inserted, including loophole-mapping table)

**Deliverable by end of Week 5:** All base features + all 5 loophole-targeted features individually complete and tested by their owners

---

### Week 6 — Integration Week
**Goal:** Merge everything into one working system. This is the highest-intensity week — plan for it, especially with React+FastAPI's larger surface area for integration bugs.

- Merge all branches into `main`, resolve conflicts
- Full walkthrough: create tender → vendor registers (device/IP captured) → vendor bids (encrypted, hashed, insert-only) → audit logged → collusion check runs → deadline passes → ranking revealed → admin awards → full audit trail visible
- Fix cross-module bugs (budget the whole week — async FastAPI + React state management both introduce more subtle bugs than a simpler stack would)
- **If ahead of schedule:** add back the anti-sniping auto-extend timer — cheapest high-impact feature to re-add
- Person 4: Continue report (Chapter 4: Implementation)

**Deliverable by end of Week 6:** Fully working end-to-end demo, no critical bugs, all 5 loophole features visibly demonstrable

---

### Week 7 — Testing + Report Writing (Parallel)
**Goal:** Don't wait until everything is "perfect" to start writing — do both simultaneously.

- Functional testing: normal flow, edge cases (late bid, duplicate bid, invalid amount, closed-tender bid attempt, concurrent bids from two vendors, attempted bid edit rejected, collusion pattern correctly flagged in a test scenario)
- Basic non-functional check: does ranking stay correct under a handful of simultaneous test bids
- Fix bugs found during testing
- Report writing (split by section, compile together):
  - Introduction & Objectives (from Week 1 notes)
  - Literature review / case study: all 3 source incidents, 13 loopholes, 5 targeted
  - E-Governance theory mapping (model, maturity stage, benefits, challenges)
  - System design (all diagrams + loophole-mapping table)
  - Implementation details + screenshots (highlight each loophole feature explicitly)
  - Testing section (test cases + results table, including loophole-specific test cases)
  - Limitations & future scope (list everything cut in Section 2, mapped back to the 8 unaddressed loopholes)
  - Conclusion

**Deliverable by end of Week 7:** Draft report complete, system stable

---

### Week 8 — Final Polish, Slides, Viva Prep
**Goal:** Presentation-ready.

- Final report proofreading and formatting
- Prepare presentation slides (problem grounded in the 2026 case, objectives, architecture, live demo, loophole-mapping table, limitations, future scope)
- Rehearse live demo at least twice as a group (things break during live demos — practice the exact click-path, including a scripted collusion-flag trigger)
- Prepare answers for likely viva questions:
  - Why reverse auction and not forward auction for tenders?
  - Walk me through exactly how your system would have prevented the 313-contract case — be ready to trace it loophole by loophole
  - Why did you choose these 5 loopholes and not others?
  - What E-Governance model and maturity stage does this represent?
  - How does this compare to Nepal's actual bolpatra system?
  - What would you add with more time? (point to Section 2 future scope list, mapped to the remaining 8 loopholes)
  - How does your encryption/hashing actually work, in your own words? (don't let the "AI helped me write this" gap show — be able to explain it without notes)

**Deliverable by end of Week 8:** Final report submitted, slides ready, demo rehearsed

---

## 7. Weekly Requirements Checklist (quick reference)

| Week | Must be true by end of week |
|------|------------------------------|
| 1 | Feature list + loophole mapping locked, tech stack locked, repo created, case study research done (all 3 source incidents), everyone has React+FastAPI "Hello World" working |
| 2 | All diagrams done, auth skeleton working (React ↔ FastAPI) |
| 3 | Tender creation + vendor signup/login working, device/IP capture started |
| 4 | Bid submission (encrypted, insert-only, hash receipt) + basic ranking display working |
| 5 | All base features + all 5 loophole-targeted features (L1, L2, L6, L9, L10) individually functional |
| 6 | Fully integrated, end-to-end demo works without critical bugs, all loophole features demonstrable |
| 7 | Testing complete (including loophole-specific test cases), report draft complete |
| 8 | Final report, slides, and demo rehearsal complete |

---

## 8. Risk Notes

- **Biggest risk:** Week 1 "let's decide next week" syndrome — the feature list, loophole mapping, and tech stack must be locked by end of Week 1, no exceptions.
- **Second biggest risk:** Week 6 integration always takes longer than expected with a React+FastAPI stack specifically — do not schedule anything else that week if possible.
- **Stack learning curve risk:** since React + FastAPI were chosen for learning value over raw speed, if by end of Week 2 the team is visibly struggling with basic syntax (not just unfamiliar patterns), have an honest checkpoint conversation about whether to simplify scope further rather than the stack itself.
- **Report writing** underestimated every time — start drafting sections from Week 1 onward, not Week 7.
- If any module owner falls behind by more than 3-4 days, redistribute a sub-task rather than letting one person block integration week.
- **Explainability risk:** every loophole feature (especially encryption and hashing) must be something each team member can explain unaided in viva — if AI tools were used to help write it, budget explicit time to understand it afterward, not just get it working.
