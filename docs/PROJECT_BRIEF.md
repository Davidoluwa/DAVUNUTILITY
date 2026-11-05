# Project Brief: Academic Vault (working name)

> **Who this is for:** an engineer or AI coding agent who will build V1 from scratch.
> It distills a product brainstorm into a buildable spec. Everything here is decided
> unless it's listed under **Open decisions**. When something isn't covered, pick the
> simplest option that fits the principles below and write down what you chose.

---

## 1. The problem

In Nigerian universities (first target: **LASU, Lagos State University**), course
materials get passed around in class **WhatsApp groups**, and it's a mess:

- PDFs dumped with no structure, and lost under hundreds of messages
- Lecture slides and notes shared as **blurry phone photos and screenshots**
- Course outlines, timetables, and test dates buried in chat history
- Every new class starts again from zero, even though last year's students already
  collected the same materials

Students keep asking "who has the CSC 205 note?" over and over again.

## 2. The product in one sentence

**An AI-powered academic vault where students can open shared course materials,
organize their own resources, ask questions about them, and add to a growing
university knowledge base.**

Mental model: **GitHub for course materials.** Each university, department, level,
and semester has a shared **central vault**. Students can **fork** a vault into a
personal workspace, change it freely, pull upstream updates, and **contribute back**.

## 3. Core principles (follow these in every design decision)

1. **The course is the basic unit, not the student.** A course exists across academic
   sessions, and each session has its own version of the outline and materials. A
   semester vault is a collection of courses. A personal vault is a fork or overlay of
   those collections.
2. **Shared first, private optional.** A new student should **inherit** an organized
   vault right away instead of building their own. Onboarding is: pick school →
   department → level → materials appear.
3. **Process once, reuse forever.** Expensive AI work (OCR, extraction, classification,
   summaries, embeddings) runs **once per unique file** and is reused across every
   fork. Never re-run AI work just because someone forked a vault.
4. **Never duplicate blobs.** Use content-addressed storage (hash the file contents)
   plus copy-on-write overlays. 2,000 forks of a 300 MB vault must **not** use 600 GB.
5. **Provenance on everything.** Each item shows who submitted it, when, whether it's
   verified, and its type: *official*, *student notes*, or *AI-generated*. AI output
   must cite its sources.
6. **Works without installing anything.** Ship as a mobile-first **PWA**, so a link
   pasted into WhatsApp opens directly in the browser.
7. **Low-data friendly.** Students are on expensive or patchy mobile data. Keep pages
   light, lazy-load documents, and let users choose what to cache offline.
8. **The product is the knowledge network, not the chatbot.** AI exists to make
   filling and using the network easier.

## 4. Users

| User | What they do |
|---|---|
| **Regular student** | Opens a shared course link, browses, reads, searches, asks the AI, forks for personal use |
| **Class rep / material distributor** (the most important early user) | Uploads and organizes a semester's materials, then posts **one link** to a 300-person WhatsApp group |
| **Contributor** | Adds missing documents, outlines, and corrections |
| **Moderator / trusted contributor** | Reviews contributions before they're published to a central vault |

Growth strategy: a handful of class reps fill the vaults, and their WhatsApp links
bring everyone else in. **Traction comes before monetization.** Don't build
payments, ads, or paywalls.

## 5. V1 scope (freeze this)

### Must have

1. **Academic hierarchy**
   `University → Faculty → Department → Level → Semester → Academic Session → Course`
   Keep stable reference material (things that stay true across sessions) separate
   from session-specific info (this session's lecturer, outline, test dates).

2. **Central course vaults.** Each course has organized lecture notes, PDFs, the
   course outline, references, and important dates.

3. **AI material ingestion**
   - Upload several PDFs, photos, screenshots, or pasted text at once
   - Extract text (PDF parsing, plus OCR for images)
   - **Combine related lecture photos into one clean PDF or note**
   - Classify each item (lecture note / outline / past question / timetable /
     announcement / other) and **suggest which course it belongs to**
   - Detect duplicates (exact match by content hash, near-duplicates by text
     similarity)
   - **The student reviews and confirms** before anything is saved. AI suggests, the
     human decides.

4. **Forkable personal vaults**
   - Fork any central vault, or individual courses, into a personal workspace
   - Add private notes, highlights, extra files, and AI explanations without touching
     the public version
   - **Upstream sync:** "3 new materials in your CSC 205 vault. Pull them?" Pulling
     **never overwrites the student's own changes without permission**.

5. **Source-grounded AI assistant**
   - Ask questions, get explanations, and summarize a document or a whole course
   - Answers **cite the exact document and page**
   - Clearly separate (a) uploaded material, (b) external references, and (c) the
     model's own explanation
   - If the answer isn't in the materials, say so. Don't make things up.

6. **Community contributions.** When someone uploads a file the central vault doesn't
   have, prompt them: *"This material isn't in your department's shared vault. Would
   you like to contribute it?"* Contributions go into a **moderation queue** before
   they're published.

7. **Instant share links.** Course and vault URLs that look clean when pasted in
   WhatsApp (good OpenGraph preview). Visitors can preview without an account. They
   only need to sign up to fork, upload, or use the AI.

8. **Universal search** across filenames, outlines, extracted document text, and
   topics. Searching "deadlock prevention" should find the right lecture **page**.

9. **Request missing materials.** Students post requests ("CSC 213 Lecture 5 notes")
   and others fill them. This gives people a natural reason to contribute.

10. **Provenance and permissions.** Show the provenance badge on every item. Uploads
    are **private by default**. Publishing to a shared vault needs an explicit action
    plus a confirmation that the uploader has the right to share it (respect copyright
    and lecturers' restricted materials, and never expose students' personal
    information).

### Explicitly out of V1 (don't build these)

Campus navigation and maps · timetable management and reminders · YouTube or video
recommendation engine · quizzes and practice-exam generation · full tutoring mode ·
social feed, chat, or DMs · marketplace · payments · native mobile apps · reading
WhatsApp groups automatically (not possible or allowed; users upload deliberately).

*Allowed shortcut:* a topic can have a simple **manually added external link** (for
example, a YouTube URL). That's just a link field, not a recommendation system.

## 6. Main screens

About five main views:

1. **Onboarding:** pick university → faculty/department → level → current session.
   Lands on the matching shared vault.
2. **Course library (home):** this semester's courses as cards (e.g. `CSC 205 ·
   Operating Systems · 18 materials`), with a search bar at the top.
3. **Course page / document reader:** materials grouped by type, a PDF or image
   viewer, provenance badges, and an "Ask AI about this" button.
4. **AI workspace:** chat that's limited to a course (or the whole vault), with
   citations you can click to jump to the document page.
5. **Personal vault:** the user's forks, private notes, pending upstream updates,
   and offline cache controls.

Supporting subviews: the upload and review flow, the contribution moderation queue,
the missing-material requests board, and the profile.

Bottom nav (mobile): **Home · Courses · AI · Profile**.

## 7. Recommended architecture

These are defaults. Change them only for a concrete reason, and document why.

| Concern | Choice |
|---|---|
| Frontend | React + TypeScript PWA, mobile-first (Vite). Service worker for offline caching |
| Backend | Python **FastAPI** |
| Database | **PostgreSQL** |
| File storage | S3-compatible object storage, **keyed by content hash** (SHA-256) |
| Auth | Supabase Auth or similar (email/phone OTP and Google; phone matters in Nigeria) |
| Background jobs | Async job queue (e.g. Celery/RQ/Arq + Redis, or Postgres-backed) for extraction, OCR, classification, summaries, embeddings |
| Search | Postgres full-text search first; add semantic search (pgvector) when needed |
| AI | Claude API via the Anthropic SDK. Use a cheaper/faster model for classification and extraction and a stronger one for explanations. Put the provider behind an interface |
| OCR | The vision model for photos of slides and notes, with a classic OCR fallback if cost is a problem |
| Forking | Versioned vault manifests + copy-on-write overlay metadata (see §8) |
| Offline | Cache vault indexes plus documents the user selects, in IndexedDB / Cache Storage |

**Cost rule:** AI artifacts (extracted text, page splits, classifications, summaries,
embeddings) belong to the **blob** (content hash), not to a user or a fork.

## 8. Data model sketch

Tables below are rough. Rename or refine them as needed.

```
university(id, name, slug)
faculty(id, university_id, name)
department(id, faculty_id, name, slug)
academic_session(id, university_id, label)          -- e.g. "2025/2026"
course(id, department_id, code, title, level, semester)   -- stable identity
course_offering(id, course_id, session_id, lecturer, outline_material_id, ...)  -- session-specific

blob(sha256 PK, size, mime, storage_key, created_at)
blob_artifact(blob_sha256, kind, data/json, model, created_at)
    -- kind: extracted_text | page_texts | ocr | summary | embedding | classification

material(id, blob_sha256, title, type, course_id, offering_id NULL,
         provenance: official|student|ai_generated,
         verified bool, submitted_by, created_at,
         visibility: private|shared)

vault(id, kind: central|personal, owner_user_id NULL, scope (dept/level/semester/session),
      parent_vault_id NULL, parent_version_id NULL)
vault_version(id, vault_id, created_at, created_by, message)
vault_entry(version_id, material_id, path/grouping, op: add|remove|modify)
      -- central vault = sequence of versions (manifest)
      -- personal vault = reference to a parent version + overlay of entries

personal_note(id, user_id, vault_id, material_id NULL, page NULL, body, created_at)
contribution(id, from_vault_id, to_vault_id, material_ids[], status: pending|approved|rejected,
             reviewer_id, note)
material_request(id, course_id, requested_by, description, status, fulfilled_by_material_id)
ai_conversation / ai_message (scoped to user + vault/course, with citations json)
```

**How forking works:** a personal vault stores `parent_version_id` plus its own
overlay entries. Its contents are `parent manifest ⊕ overlay`. "Updates available"
means the central vault has versions newer than `parent_version_id`. Pulling moves the
pointer forward. When the overlay modified or removed something upstream changed,
show a **conflict** and let the user choose. No blobs are ever copied.

## 9. Ingestion pipeline (per upload batch)

1. Client uploads files → server hashes them → if the blob already exists, reuse it
   along with all its artifacts (zero AI cost).
2. New blobs → job: extract text (PDF) or OCR (images) → split into pages.
3. Group photos from the same batch that look like one lecture → offer to merge them
   into a single PDF.
4. Classify (type, likely course code, title, topics) → near-duplicate check against
   the target course.
5. Show the user a **review screen**: suggested course, type, and title, plus duplicate
   warnings. The user confirms or edits.
6. Save materials into the user's personal vault. If the material isn't in the central
   vault → offer **Contribute**.
7. Index for search (full-text now, embeddings later).

## 10. Build order

1. Repo setup, hierarchy models, auth, roles/permissions, seed data for **LASU →
   Computer Science → 200L** with 3–5 real course codes
2. Blob storage + material upload/view/download + course library UI
3. AI ingestion pipeline (extract, OCR, classify, dedupe, review screen)
4. Search + grounded AI chat with citations
5. Vault versioning, personal forks, overlays, upstream sync
6. Share links + OpenGraph, contribution moderation, missing-material requests
7. PWA polish: offline cache, installability, low-data checks

Each step should leave a working, demoable app. Write tests for the fork/sync logic
and the dedupe logic in particular, since that's where the subtle bugs will be.

## 11. Pilot success criteria

Pilot targets, not forecasts:

- **100** pilot students, **3–5** courses, **50+** useful documents, **5–10** active
  contributors
- A student can find a specific document **in under 30 seconds**
- Shared WhatsApp links bring in visitors who **come back**
- People contribute **without being chased**
- North-star signal: students open the vault **instead of** asking for materials in
  the WhatsApp group

Add basic analytics for: unique course-link visitors, return visits, % of courses with
useful materials, and the number of contributions and fulfilled requests.

## 12. Risks to design around

- **Content quality and trust:** a misfiled document or a made-up AI outline damages
  trust fast. Hence the review screen, provenance badges, moderation, and cited
  answers.
- **AI cost:** process once per blob, cache aggressively, and use cheap models for
  bulk work.
- **Copyright and privacy:** private by default, explicit confirmation to share, and
  a way to report and take down content.
- **Competition** (Google NotebookLM, Studocu): the edge is **institution-specific,
  community-maintained course vaults** that are already filled in when you arrive. Not
  "AI organizes your PDFs."

## 13. Open decisions (ask the project owner, or choose sensible defaults and flag them)

- Product name and branding (the owner wants to grow a broader brand later)
- Hosting target and budget (e.g. Fly/Render/Railway + Supabase + R2/S3)
- Who moderates at launch: the owner, class reps, or anyone with a verified role
- Whether vault previews without an account show full documents or only previews
- Phone-number OTP provider for Nigeria

## 14. Long-term direction (context only, not V1)

The vault is the **entry product** for a wider student-focused brand. Once there's
traction, possible expansions include an AI school assistant (e.g. telling it your
timetable in plain language), timetables and reminders, campus navigation with offline
maps and location sharing with friends (the original idea, parked because surveying a
campus is too heavy for an entry product), and partnerships or monetization. Keep the
V1 architecture open to these, **but don't build any of them yet.**
