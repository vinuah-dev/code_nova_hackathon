# Inkloom AI — Intelligent Brand Governance

> **AI recommends. Humans decide. Brand knowledge provides the evidence.**

Inkloom checks marketing content **before it is published**. It compares the content against an organisation's approved brand knowledge (guidelines, verified facts, approved claims, terminology, palette and logos). It explains every issue with its source and suggests corrections. Content then goes through a role-based approval workflow, and the approved version is sealed with a SHA-256 hash.

The demo organisation is **Voltaro Mobility**, a *fictional* Indian electric-scooter brand. All its people, figures and certificates are invented.

---

## Run it

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python run.py
```

Open **http://127.0.0.1:8000**. On first start the database is created in `data/` and seeded with the demo organisation.

**Sign in.** The sign-in page offers one-click **demo accounts** for all five demo people (Admin, two Creators, Manager, Approver). You can also sign in with email + password: every demo account (`asha@voltaro.demo`, `rohan@voltaro.demo`, `kavya@pixelkite.demo`, `meera@voltaro.demo`, `vikram@voltaro.demo`) uses the demo password `voltaro-demo`. Set `INKLOOM_DEMO_PASSWORD` to change it before the first start, or `INKLOOM_DEMO_LOGIN=0` to remove the one-click buttons. Sign out from the avatar / account menu. Sessions are HMAC-signed cookies so they work across Vercel's multiple instances; set `INKLOOM_SESSION_SECRET` to a long random value in production (otherwise the key is derived from the AI key, or a dev-only key when none is set).

**Enable AI review (optional, free option available):** copy `.env.example` to `.env` and pick a provider:

| Provider | Cost | Set in `.env` |
|---|---|---|
| **Google Gemini** (recommended free option) | Free tier key from [Google AI Studio](https://aistudio.google.com) | `INKLOOM_AI_PROVIDER=gemini`, `GEMINI_API_KEY=…` |
| Anthropic Claude | Paid API credits | `ANTHROPIC_API_KEY=…` |
| Groq / OpenRouter | Free keys with rate limits | `INKLOOM_AI_PROVIDER=groq`, `INKLOOM_AI_API_KEY=…` |
| Ollama (local) | Free, offline, private | `INKLOOM_AI_PROVIDER=ollama` |

On Vercel, add the same variables under Project → Settings → Environment Variables and redeploy. Without any key the app runs in **Rule engine mode**: every deterministic check still runs and the UI labels the report as rule-engine only. This is also the automatic fallback if the AI service fails or hits a free-tier rate limit.

**Shared database (Supabase / any Postgres, optional):** set `DATABASE_URL` to a Postgres connection string and the app uses it instead of SQLite. Tables are created automatically, the demo organisation is seeded once (an advisory lock stops two cold starts seeding twice) and uploaded files are stored in a `blobs` table, so every Vercel instance sees the same data. For Supabase use the **Session pooler** string from *Connect* (port 5432, IPv4) and percent-encode special characters in the password (`@` → `%40`). Row Level Security is switched on for every table, which blocks Supabase's public REST Data API; the app itself connects as the table owner. Put the Vercel functions in the same region as the database (`vercel.json` → `regions`; this repo uses `syd1` for a Sydney project). Without `DATABASE_URL` (or with `INKLOOM_DB=sqlite`) the app uses the local SQLite file.

**Test the whole journey (no API key needed, uses a throwaway database):**

```bash
python scripts/smoke_test.py
```

It runs 34 checks covering upload → review → fixes → approval → integrity → gap intelligence → analytics. `python scripts/mock_ai_test.py` runs 11 more against a local mock of an OpenAI-compatible AI server (request format, image input, grounding validation, fallback on 429). `python scripts/auth_test.py` runs 22 sign-in/sign-out checks with real cookies. `python scripts/feedback_test.py` runs 12 checks on in-app user-testing feedback and the audit-log export. `python scripts/extract_test.py` runs 13 checks on extracting rules from brand documents and the health endpoint. `python scripts/learning_test.py` runs 14 checks on the feedback-learning model (shadow mode, quality gate, activation, admin pin).

---

## Demo script (≈ 6 minutes)

Switch person from the account menu (top right, or the avatar on mobile). Roles are enforced by the server.

| # | As | Do |
|---|----|----|
| 1 | Anyone | **Dashboard**: compliance KPIs, most-violated guidelines, mistakes by channel |
| 2 | Asha (Admin) | **Brand Brain → Documents** → upload `web/demo/Voltaro_Brand_Book_2026.pdf`. Then try **Test retrieval** with "diwali firecracker offer" |
| 3 | Asha | **Approved facts** → *Add approved fact*; **Visual identity** shows the official logo and palette |
| 4 | Rohan (Creator) | **Content Studio → New content → Load Diwali sample files** (an agency draft: caption, poster, and the logo file they used) |
| 5–7 | Rohan | **Save & run brand review**. The report shows an unsupported claim ("fastest", "GUARANTEED"), a wrong range (150 vs 120 km), wrong product name, an expired offer, a stretched and recoloured logo, an off-brand red, low contrast, missing alt text and "click here". Each finding shows its **evidence** and source id |
| 8–9 | Rohan | **Accept all text fixes** (or accept/reject one by one), toggle **Preview**, then **Apply** |
| 10 | Rohan | The before/after pop-up shows the score moving (e.g. 9 → 32), dimension by dimension. **Brand DNA** compares the two versions |
| — | Rohan | **Edit** → add alt text → re-run review → **Submit for approval** |
| 11–12 | Meera (Manager) → Vikram (Approver) | Meera **Endorses**. Vikram **Approves**: open visual issues require a recorded **override reason** |
| 13 | Asha | **Approval Center → Integrity Shield → Simulate tampering** (direct database edit) → alert with the word-level diff; the content drops back to re-review |
| 14 | Asha | **Brand Intelligence**: "3 submissions used 'Glide-S1'…" → **Propose clearer guideline** → edit → **Approve**. Then try the **Brand DNA Simulator** |

---

## Architecture

```
Browser (vanilla JS SPA, no build step)
   │  JSON over HTTP, HttpOnly session cookie (sign-in; roles enforced server-side)
FastAPI (server/main.py) ── SQLite (data/inkloom.db) or Postgres/Supabase (DATABASE_URL) + file store (local, mirrored to the DB)
   ├─ rag.py        Brand Brain → chunks with stable ids → BM25 retrieval
   ├─ rules.py      deterministic checks (text + images) → findings with exact offsets
   ├─ visual.py     palette (median cut), CIE ΔE colour distance, WCAG contrast, logo aspect/colour/shape hash
   ├─ ai.py         Claude review: retrieved sources in, JSON-schema findings out, citations validated
   ├─ analysis.py   orchestrates rules + retrieval + AI, merges, scores, stores
   ├─ scoring.py    transparent formula (below)
   ├─ integrity.py  SHA-256 approval seal, verification, word-level diff
   ├─ gaps.py       Guideline Gap Intelligence (repeated signatures across submissions)
   ├─ auth.py       sign-in: PBKDF2-SHA256 passwords, HMAC-signed stateless session cookie, lockout after 5 wrong tries
   ├─ learning.py   Feedback Learning: our own model trained on accept/reject decisions (shadow → active)
   └─ seed.py / demo_assets.py   fictional org + generated demo images/PDF
```

### Key technical decisions

- **A hybrid engine, not "just ask the LLM".** Deterministic rules catch what must never be missed: wrong numbers, banned terms, palette, logo distortion, alt text. They are reproducible and point at exact characters. Claude adds what rules can't judge: tone drift, implied claims, visual misuse. If the AI is down, the product still works.
- **Grounding you can verify.** Every Brand Brain item becomes a chunk with an id (`G-CLAIM-01`, `F-RANGE`, `DOC-1#3`…). The model gets only the top retrieved chunks and must cite ids. The server drops unknown ids. AI findings with no valid citation are labelled **Ungrounded** and get 40% less weight.
- **BM25 instead of embeddings.** Brand knowledge is small and term-heavy (product names, numbers). Lexical retrieval is fast, needs no extra service, and its ranking can be shown to judges (**Brand Brain → Test retrieval**).
- **Structured outputs.** Claude returns JSON constrained by a schema (`output_config.format`), so parsing can't break mid-demo. Requests use `claude-opus-5-5` by default, plus server-side refusal fallback. `stop_reason` and API errors are handled and fall back to the rule report.
- **Fixes are span-exact and opt-in.** A fix applies only to the offsets the finding points at, only when a person accepted it, and only as a new version. The original is never overwritten.
- **Scores are computed, not guessed:** `overall = 100 × e^(−Σ penalty/100)`, where penalty = severity weight (critical 35, high 20, medium 10, low 4) × confidence. Rejected (false-positive) findings don't count. Same input → same score.
- **Feedback Learning (our own trained model).** Every accept/reject on a finding is a training label. `server/learning.py` trains an L2 logistic regression (NumPy, Newton's method) that predicts *P(finding is a real issue)* from interpretable features: category, severity, engine, grounding, the engine's confidence, location and rule family. It retrains on every decision (milliseconds).
  - **Quality gate.** The model is evaluated with grouped 5-fold cross-validation (split by submission) against the baseline of the engine's own confidence. It only becomes **active** with ≥ 30 decisions, ≥ 5 of each class, ≥ 4 submissions, ≥ 10% lower Brier score and no loss in accuracy. Until then it runs in **shadow mode**: its prediction is shown on each finding but Gemini + rules decide the score. An admin can pin it to shadow at any time.
  - **When active** it only recalibrates confidence (and so the score). It never hides a finding; Gemini and the rules still produce every one. **Brand Intelligence → Feedback Learning model** shows the metrics vs baseline and the learned weights.
  - The demo seeds 14 archived posts with **simulated** reviewer decisions (labelled "Seeded demo feedback" and counted separately in the UI) so there is something to learn from. Real decisions you make are added on top.
- **Integrity seal:** SHA-256 over canonical JSON of title + body + alt text + SHA-256 of every attached file, stored at approval. Edits inside the app and out-of-band database edits are both detected.

### APIs, models, libraries

| What | Used for |
|------|----------|
| Anthropic Claude API (`claude-opus-5-5`) **or** any OpenAI-compatible API: Google Gemini (`gemini-3.5-flash`, free tier), Groq, OpenRouter, Ollama | Grounded compliance review (text + images), guideline rewrite proposals |
| FastAPI, Uvicorn | HTTP API and static hosting |
| SQLite (stdlib) / PostgreSQL via psycopg 3 (Supabase) | Storage |
| pypdf | PDF text extraction |
| Pillow, NumPy | Palette extraction, colour science, logo comparison, demo image generation, and the feedback-learning model (logistic regression written from scratch in NumPy) |
| Lucide icons (CDN), Inter font (Google Fonts) | UI |

No templates or boilerplate were used. Demo images and the brand-book PDF are generated by `server/demo_assets.py`.

---

## Responsible design

- **Disclosure:** with AI on, content text, images and the retrieved guideline excerpts are sent to the configured provider. Free tiers (e.g. Gemini's) may let the provider use submitted data to improve its products, so sensitive material should be marked Confidential (never sent) or reviewed with local Ollama. The UI shows which engine produced every report and every finding.
- **Confidential mode:** content marked confidential is never sent to an external service; only local rule checks run.
- **Secrets:** the API key is read from `.env` on the server only and is never sent to the browser. `.env` is git-ignored.
- **Human control:** AI never edits content. Approving with open critical or high findings needs a written override, which is stored in the approval record. Guideline changes proposed by the system need admin approval and are versioned.
- **Explainability:** every finding shows its category, severity, confidence, engine, explanation, the approved source text, and (for images) the measured evidence (ΔE, aspect ratio, contrast ratio).

## Known limitations

- Image checks are heuristic. Palette contrast uses the two dominant colours, not OCR'd text. The logo check compares the logo file the creator declares; it does not locate the logo inside a poster (Claude's vision covers that when enabled).
- Rule-based rewrites are simple substitutions; better rewrites come from Claude when enabled.
- Sign-in is email + password with server-side sessions, but there is no self-service sign-up, password reset or SSO, and the one-click demo accounts must be turned off (`INKLOOM_DEMO_LOGIN=0`) for any real use. Production also needs per-tenant isolation. The failed-login lockout is per server instance (in memory).
- The integrity hash lives in the same database. Production should anchor it externally (e.g. a signed log).
- The Gemini path has been run live (free tier, `gemini-3.5-flash`); the Anthropic path has not been exercised with a live key in this build. Model names on free tiers change often, so override `INKLOOM_MODEL` if a provider rejects the default.
- The feedback-learning model is small and only as good as the decisions it gets. Its demo metrics come mostly from **simulated** seed feedback, so they show the mechanism, not real-world accuracy. Without `DATABASE_URL`, Vercel keeps the database in `/tmp`, so decisions (and the model) reset when an instance restarts; with Supabase they persist.

## Roadmap

CMS/Figma/Google Drive connectors · OCR for text inside images · multilingual checks (Hindi and other regional languages) · SSO and audit export · per-market rule sets · embeddings + BM25 hybrid retrieval as the Brand Brain grows · browser extension that checks drafts in place.

## Disclosure (hackathon rule 7)

This project was built with significant AI assistance (Claude Code). The feedback-learning model is trained by the app itself, inside this project, on the organisation's own accept/reject decisions; no pre-trained model weights are used for it. All dependencies are listed above and used under their licences.
