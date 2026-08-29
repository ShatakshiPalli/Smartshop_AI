# SmartShop AI

**Discover, Compare, and Shop Smarter with AI**

An AI-powered ecommerce comparison platform that pulls **live** product data
from Amazon and Flipkart via Apify, ranks it with AI, lets users compare
products cross-platform, analyzes real customer reviews, and answers
shopping questions through a RAG-powered assistant.

No mock data, no Kaggle/CSV datasets, no hardcoded products — every price,
rating, review count, and product URL comes from a live Apify actor run.

---

## Tech stack

- **Backend:** Python 3.11, FastAPI
- **Frontend:** HTML, CSS, vanilla JavaScript (served by FastAPI as static files)
- **Database:** PostgreSQL + SQLAlchemy + Alembic
- **AI:** LangChain, Sentence-Transformers, FAISS, OpenAI / Azure OpenAI
- **Auth:** JWT + bcrypt
- **Charts:** Chart.js (lightweight, CDN-loaded)
- **Live data:** Apify (separate actors for Amazon and Flipkart)

---

## Project layout

```
smartshop-ai/
├── app/
│   ├── main.py              # FastAPI app entrypoint, mounts routers + static frontend
│   ├── config.py            # Settings loaded from environment (.env)
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models.py            # ORM models (Users, Products, Offers, Reviews, etc.)
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── security.py          # Password hashing + JWT
│   ├── deps.py               # FastAPI auth dependencies
│   ├── routers/
│   │   ├── auth.py           # /api/auth - register/login/me
│   │   ├── products.py       # /api/search, /api/products/* - search, compare, reviews, recs
│   │   ├── assistant.py      # /api/assistant/ask - RAG shopping assistant
│   │   └── analytics.py      # /api/analytics/summary
│   ├── services/
│   │   ├── apify_client.py   # Live Amazon + Flipkart data via Apify
│   │   ├── normalize.py      # Cross-platform product dedup/merge
│   │   ├── ranking.py        # AI + heuristic product ranking
│   │   ├── comparison.py     # Cross-platform verdict + multi-product comparison
│   │   ├── sentiment.py      # Review sentiment analysis
│   │   ├── embeddings.py     # Sentence-Transformers + FAISS semantic search
│   │   ├── assistant.py      # RAG pipeline (retrieval + LLM answer)
│   │   ├── recommendations.py# Similar/better/budget/premium alternatives
│   │   └── llm.py            # OpenAI/Azure OpenAI wrapper
│   └── static/
│       ├── css/style.css
│       ├── js/app.js
│       └── pages/            # index, product, compare, assistant, analytics, login, register
├── alembic/                  # DB migrations
├── requirements.txt
├── .env.example
└── README.md
```

---

## 1. Prerequisites

- Python 3.11+
- A PostgreSQL database (a free tier from [Neon](https://neon.tech),
  [Supabase](https://supabase.com), or [Railway](https://railway.app) works well)
- An [Apify](https://apify.com) account with:
  - An API token
  - An Amazon search-scraper actor (e.g. search the Apify Store for
    "Amazon Product Search Scraper")
  - A Flipkart search-scraper actor (e.g. search for "Flipkart Scraper")
- An OpenAI API key **or** Azure OpenAI credentials (optional — the app
  degrades gracefully to heuristic ranking/deterministic summaries without
  an LLM key, but the AI assistant and richer AI reasoning need one)

> ⚠️ **Never commit real credentials.** Only `.env.example` is checked in;
> your real `.env` is git-ignored.

---

## 2. Local setup

```bash
git clone <your-repo-url> smartshop-ai
cd smartshop-ai

python3.11 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# now edit .env and fill in real values (see below)
```

### Configure `.env`

```env
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/smartshop

APIFY_API_TOKEN=your_real_apify_token
AMAZON_ACTOR_ID=your_amazon_actor_id      # e.g. "username/amazon-scraper"
FLIPKART_ACTOR_ID=your_flipkart_actor_id  # e.g. "username/flipkart-scraper"

LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini

JWT_SECRET_KEY=generate_a_long_random_string
ADMIN_INVITE_CODE=generate_a_private_admin_signup_code
```

Generate a JWT secret quickly:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Adapting to your chosen Apify actors

Different Apify actors return different field names (e.g. `price` vs
`currentPrice` vs `sellingPrice`). `app/services/apify_client.py` already
checks several common field-name variants per field
(`_normalize_amazon_item` / `_normalize_flipkart_item`). If your actor uses
different field names, just add them to the relevant `_first_present([...])`
list — no other code needs to change.

### Run database migrations

```bash
alembic upgrade head
```

(For rapid local prototyping, `app/main.py` also auto-creates tables on
startup as a fallback — but use Alembic for anything beyond local testing.)

### Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

Visit **http://localhost:8000**.

---

## 3. Using the app

1. **Search** — go to `/`, type a query like "best laptops under ₹50,000",
   optionally set max price / min rating / category, and search. This
   triggers a live Apify run against both Amazon and Flipkart, merges
   duplicate products, and ranks them.
2. **Product detail** — click a result to see cross-platform pricing,
   the AI's "better deal" verdict, specs, review sentiment, and
   recommendations.
3. **Compare** — select 2+ products from search results and click
   "Compare selected" for a side-by-side table, pros/cons, and AI verdict.
4. **AI Assistant** — `/assistant` — ask natural-language questions;
   answers are grounded only in retrieved product/review data.
5. **Analytics** — `/analytics` — search volume, top queries, categories,
   and brands.
6. **Register/Login** — optional; enables personalized search history.
   Search and browsing work without an account too.

### Account types

- **User** accounts can search, compare products, open marketplace listings, and use the assistant.
- **Admin** accounts can sign in to `/admin` to review tracked outbound clicks, search activity, and model health metrics.
- Admin registration requires the private `ADMIN_INVITE_CODE` from your `.env` file.

---

## 4. How live data flows (no mock data, ever)

```
User query
   │
   ▼
POST /api/search
   │
   ├─► Apify: Amazon actor run  ──► raw Amazon items
   ├─► Apify: Flipkart actor run ──► raw Flipkart items
   │      (each platform fails independently; failures become
   │       user-facing warnings, never fake substitute data)
   ▼
Normalize + dedupe (title similarity across platforms)
   │
   ▼
Canonical Product rows + linked PlatformOffer rows (real prices/urls)
   │
   ▼
AI + heuristic ranking (LLM only explains retrieved data, never invents it)
   │
   ▼
Response: ranked products with real prices, ratings, images, and URLs
```

If both Apify actors fail or are unconfigured, the API returns an empty
result set with a clear warning message — it never fabricates products.

---

## 5. Deployment (free-tier friendly)

This app is intentionally split into a stateless FastAPI service + external
Postgres, so it fits comfortably on free hosting:

### Backend (FastAPI)
- **Render** (free web service) or **Railway** or **Fly.io**:
  - Build command: `pip install -r requirements.txt`
  - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  - Set all `.env` variables as environment variables in the dashboard
  - Run `alembic upgrade head` as a one-off release/deploy command

### Database
- **Neon** or **Supabase** free Postgres tier — copy the connection string
  into `DATABASE_URL` (make sure to use the `postgresql+psycopg2://` prefix)

### Frontend
No separate deployment needed — FastAPI serves the static HTML/CSS/JS
directly from `app/static/`, so one deployed service covers everything.

### Notes for production
- Set `CORS_ORIGINS` to your real deployed domain(s)
- Rotate `JWT_SECRET_KEY` and any API keys before going live
- FAISS indices here are built in-memory per request for simplicity/easy
  deployment; for heavier traffic, consider persisting/caching the index
  per category instead of rebuilding every assistant query

---

## 6. Error handling & data integrity guarantees

- Amazon/Flipkart Apify calls run concurrently and **fail independently** —
  one platform being down never blocks the other or the whole search.
- All numeric fields (price, rating, review count) are parsed defensively;
  unparseable values become `None` and are shown as "unavailable" in the UI
  rather than guessed.
- Every `PlatformOffer.url` is the actual URL returned by Apify — the UI's
  "View on Amazon" / "View on Flipkart" buttons link directly to it.
- LLM prompts throughout the app (`services/ranking.py`,
  `services/comparison.py`, `services/sentiment.py`, `services/assistant.py`)
  are explicitly instructed to reason **only** over retrieved data and are
  designed to fall back to deterministic, data-only summaries if no LLM key
  is configured or the LLM call fails.

---

## 7. Roadmap / next increments

This repo ships the full core flow end-to-end. Natural next steps:
- Persist a shared FAISS index per category (rather than per-request) for
  faster semantic search at scale
- Background job to periodically refresh stale offers instead of only
  fetching on search
- Review scraping integration per-offer (currently reviews table is wired
  end-to-end but populated by whatever your Apify actor returns — if your
  chosen actor doesn't include reviews, add a dedicated Apify review-scraper
  actor and a small ingestion job)
- Pagination for large result sets
- Rate limiting on `/api/search` to control Apify usage costs
