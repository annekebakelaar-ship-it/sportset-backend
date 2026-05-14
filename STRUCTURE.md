# Sportset Backend Structure

## Directory Layout

```
sportset-backend/
├── src/
│   ├── main.py                    # FastAPI app entry point + lifespan
│   ├── __init__.py
│   │
│   ├── api/                       # API endpoints (routers)
│   │   ├── __init__.py
│   │   ├── auth.py               # ✅ User auth (register, login, me, logout)
│   │   ├── oura.py               # ✅ Oura OAuth + data endpoints
│   │   ├── payment.py            # ✅ Mollie payment + webhooks
│   │   ├── scans.py              # Existing: photo scan endpoints
│   │   ├── onboarding.py         # Existing: onboarding
│   │   ├── supplements.py        # Existing: supplement data
│   │   └── upload.py             # Existing: file upload
│   │
│   ├── core/                      # Core utilities
│   │   ├── __init__.py
│   │   ├── config.py             # ✅ Updated: added MOLLIE env vars
│   │   └── security.py           # ✅ NEW: encryption, hashing, JWT
│   │
│   ├── db/                        # Database layer
│   │   ├── __init__.py
│   │   ├── database.py           # ✅ Updated: register new models
│   │   ├── models.py             # ✅ NEW: User, OuraToken, Subscription, Payment
│   │   ├── session.py            # Existing: session management
│   │   ├── seed.py               # Existing: database seeding
│   │   └── migrations/           # Alembic migrations
│   │
│   ├── models/                    # ORM models (legacy)
│   │   ├── orm_models.py         # Existing: supplements, ingredients, etc.
│   │   ├── onboarding.py         # Existing: onboarding models
│   │   └── scan_schemas.py       # Existing: scan schemas
│   │
│   ├── services/                  # Business logic (existing)
│   │   ├── oura/                 # Oura service (refactored)
│   │   ├── auth_service.py       # Magic link auth (legacy)
│   │   └── ...
│   │
│   └── utils/                     # Utilities (existing)
│       ├── file_utils.py
│       ├── image_validation.py
│       └── json_parser.py
│
├── requirements.txt              # ✅ Updated: added crypto, Mollie deps
├── .env.example                  # ✅ NEW: environment template
├── .env                          # (secrets, not in git)
├── Dockerfile                    # Docker build config
├── Procfile                      # Render deployment config
├── .gitignore                    # Git ignore rules
├── .git/                         # Git repository
│
├── API_DOCUMENTATION.md          # ✅ NEW: complete API reference
├── DEPLOYMENT.md                 # ✅ NEW: deployment guide
├── BUILD_SUMMARY.md              # ✅ NEW: build summary
├── STRUCTURE.md                  # This file
└── README.md                     # (existing project readme)
```

## Key Files

### New Production Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/core/security.py` | 180 | Password hashing, encryption, JWT |
| `src/db/models.py` | 250 | Database models (User, OuraToken, Subscription, Payment) |
| `src/api/payment.py` | 310 | Mollie payment integration |
| `.env.example` | 70 | Environment variables template |
| `API_DOCUMENTATION.md` | 280 | API reference |
| `DEPLOYMENT.md` | 320 | Deployment guide |
| `BUILD_SUMMARY.md` | 385 | Build summary |

### Updated Files

| File | Changes | Impact |
|------|---------|--------|
| `src/main.py` | Added payment routers, DB init | Backend boot |
| `src/api/auth.py` | Complete rewrite with JWT | User authentication |
| `src/api/oura.py` | Rewritten with OAuth flow | Oura integration |
| `src/core/config.py` | Added Mollie vars | Configuration |
| `src/db/database.py` | Register new models | Database setup |
| `requirements.txt` | Added crypto, Mollie deps | Dependencies |

## API Endpoints

### Authentication (5 endpoints)
```
POST   /auth/register          ← User registration
POST   /auth/login             ← User login (JWT)
GET    /auth/me                ← Current user profile
POST   /auth/logout            ← Logout
GET    /auth/dev-token         ← Dev token (dev only)
```

### Oura OAuth (8 endpoints)
```
GET    /api/oura/connect       ← Initiate OAuth
GET    /api/oura/callback      ← OAuth redirect (internal)
POST   /api/oura/disconnect    ← Disconnect account
GET    /api/oura/status        ← Connection status
POST   /api/oura/pull          ← Fetch data (45 days)
GET    /api/oura/sleep         ← Sleep data
GET    /api/oura/activity      ← Activity data
GET    /api/oura/heart-rate    ← Heart rate data
```

### Payment (3 endpoints)
```
POST   /api/payment/create-checkout     ← Create payment
GET    /api/payment/status/{id}         ← Payment status
POST   /webhook/mollie                  ← Webhook handler
```

### Health (1 endpoint)
```
GET    /health                  ← Health check
```

**Total: 17 endpoints**

## Database Tables

```sql
-- User accounts
sportset_users (
  id, email (UNIQUE), name, hashed_password,
  subscription_status, is_active, created_at, updated_at
)

-- OAuth token storage (encrypted)
sportset_oura_tokens (
  id, user_id (FK, UNIQUE), encrypted_data (AES-256-GCM),
  created_at, last_refreshed_at, expires_at
)

-- Subscription records
sportset_subscriptions (
  id, user_id (FK), status, plan_id,
  started_at, expires_at, renewal_date, created_at, updated_at
)

-- Mollie payment records
sportset_payments (
  id, user_id (FK), mollie_payment_id (UNIQUE),
  amount, currency, status, mollie_checkout_url, plan_id,
  paid_at, created_at, updated_at, metadata
)
```

## Security Layers

1. **Transport**: HTTPS/TLS (Render auto-enabled)
2. **Authentication**: JWT (HS256, 7-day expiry)
3. **Authorization**: Per-user isolation via JWT claims
4. **Passwords**: bcrypt hashing (adaptive rounds)
5. **Tokens**: AES-256-GCM encryption (at-rest)
6. **Webhooks**: HMAC-SHA256 signature verification
7. **Inputs**: Pydantic validation (type-safe)
8. **Secrets**: Environment variables (never hardcoded)

## Technology Stack

**Framework**: FastAPI (async ASGI)
**ORM**: SQLAlchemy 2.0+
**Database**: Supabase PostgreSQL (or SQLite dev)
**Authentication**: JWT (python-jose)
**Password**: bcrypt (via passlib)
**Encryption**: cryptography (AES-256-GCM)
**HTTP**: httpx (async client)
**Validation**: pydantic v2
**Payments**: Mollie API
**OAuth**: requests-oauthlib
**Server**: uvicorn
**Testing**: pytest, pytest-asyncio

## Configuration

Environment variables required for production:

```
APP_ENV=production
APP_SECRET_KEY=<64+ char random string>
TOKEN_ENCRYPTION_KEY=<32-byte hex from openssl rand -hex 32>
DATABASE_URL=postgresql://...
OURA_CLIENT_ID=<from cloud.ouraring.com>
OURA_CLIENT_SECRET=<from cloud.ouraring.com>
OURA_REDIRECT_URI=https://your-domain/api/oura/callback
MOLLIE_API_KEY=<from mollie.com>
MOLLIE_WEBHOOK_SECRET=<from mollie.com>
SUPABASE_URL=<from supabase.com>
SUPABASE_SERVICE_ROLE_KEY=<from supabase.com>
FRONTEND_URL=https://your-frontend-domain
```

## Deployment

**Platform**: Render.com
**Database**: Supabase PostgreSQL
**OAuth Provider**: Oura Cloud
**Payment Provider**: Mollie

See `DEPLOYMENT.md` for step-by-step instructions.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# View API docs
# → http://localhost:8000/docs

# Run tests
pytest

# Check syntax
python3 -m py_compile src/**/*.py

# Generate encryption key
openssl rand -hex 32

# Generate JWT secret
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Performance Considerations

- **Async endpoints**: All I/O operations non-blocking
- **Connection pooling**: SQLAlchemy handles DB connections
- **Token caching**: Encrypted tokens cached in database
- **Auto-refresh**: 5-minute buffer prevents race conditions
- **Webhook queueing**: Mollie auto-retries failed webhooks
- **Rate limiting**: Configurable per endpoint/user tier

## Monitoring & Logging

- Health check: `GET /health`
- Application logs: Render dashboard
- Database logs: Supabase console
- Webhook logs: Mollie dashboard
- OAuth logs: Oura app details

## Error Handling

All endpoints return standard HTTP status codes:
- `200` OK
- `201` Created
- `204` No Content
- `400` Bad Request (validation)
- `401` Unauthorized (auth required)
- `403` Forbidden (permission denied)
- `404` Not Found
- `409` Conflict (duplicate)
- `502` Bad Gateway (external API error)

Errors include helpful detail messages without leaking sensitive info.
