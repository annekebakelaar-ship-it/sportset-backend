# Sportset Backend API Documentation

## Overview

Production-ready FastAPI backend with:
- **Oura OAuth 2.0** integration (sleep, activity, heart rate data)
- **Mollie Payment** gateway (subscription checkout + webhooks)
- **User Authentication** (register, login, JWT tokens)
- **Database** (Supabase PostgreSQL or SQLite)
- **Security** (AES-256-GCM token encryption, bcrypt password hashing)

## Quick Start

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env from example
cp .env.example .env
# Edit .env with your values (especially OURA_* and MOLLIE_*)

# Run server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Visit API docs: http://localhost:8000/docs
```

### Production (Render)

1. Add environment variables to Render dashboard:
   - `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, `OURA_REDIRECT_URI`
   - `MOLLIE_API_KEY`, `MOLLIE_WEBHOOK_SECRET`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `TOKEN_ENCRYPTION_KEY` (generate: `openssl rand -hex 32`)
   - `APP_SECRET_KEY` (generate: `python -c "import secrets; print(secrets.token_urlsafe(64))"`)

2. Redeploy the app

## Authentication Endpoints

### Register User
```
POST /auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secure_password",
  "name": "John Doe"
}

Response 201:
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

### Login User
```
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secure_password"
}

Response 200:
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

### Get Current User
```
GET /auth/me
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200:
{
  "id": "uuid-123",
  "email": "user@example.com",
  "name": "John Doe",
  "subscription_status": "active",
  "is_active": true
}
```

### Logout
```
POST /auth/logout
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 204: No Content
```

## Oura Integration Endpoints

### Start OAuth Connection
```
GET /api/oura/connect

Response: Redirect to Oura authorization page
(User logs in with Oura account, authorizes Sportset)
```

### OAuth Callback (handled internally)
```
GET /api/oura/callback?code=xxx&state=yyy
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response: Redirect to frontend /connect?status=success
(Tokens are encrypted and stored in database)
```

### Disconnect Oura
```
POST /api/oura/disconnect
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200:
{
  "status": "disconnected"
}
```

### Check Connection Status
```
GET /api/oura/status
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200:
{
  "connected": true,
  "expires_at": "2026-05-15T10:30:00Z",
  "user_id": "uuid-123"
}
```

### Pull Oura Data (45 days)
```
POST /api/oura/pull?days=45
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200:
{
  "sleep": [
    {
      "day": "2026-05-12",
      "duration": 28800,
      "quality": 85
    },
    ...
  ],
  "activity": [
    {
      "day": "2026-05-12",
      "active_calories": 450,
      "steps": 8234
    },
    ...
  ],
  "heart_rate": [
    {
      "day": "2026-05-12",
      "hrv": 45,
      "resting_hr": 62
    },
    ...
  ],
  "pulled_at": "2026-05-14T10:30:00Z"
}
```

### Get Sleep Data
```
GET /api/oura/sleep
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200: [{ "day": "2026-05-12", "duration": 28800, "quality": 85 }, ...]
```

### Get Activity Data
```
GET /api/oura/activity
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200: [{ "day": "2026-05-12", "active_calories": 450, "steps": 8234 }, ...]
```

### Get Heart Rate Data
```
GET /api/oura/heart-rate
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200: [{ "day": "2026-05-12", "hrv": 45, "resting_hr": 62 }, ...]
```

## Payment Endpoints

### Create Checkout
```
POST /api/payment/create-checkout
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
Content-Type: application/json

{
  "plan_id": "premium",
  "amount_cents": 2999
}

Response 200:
{
  "payment_id": "uuid-456",
  "mollie_payment_id": "tr_WDqYK6vllg",
  "checkout_url": "https://www.mollie.com/checkout/..."
}
```

Redirect user to `checkout_url` to complete payment.

### Check Payment Status
```
GET /api/payment/status/tr_WDqYK6vllg
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Response 200:
{
  "id": "uuid-456",
  "mollie_payment_id": "tr_WDqYK6vllg",
  "status": "paid",
  "amount": 2999,
  "currency": "EUR",
  "paid_at": "2026-05-14T10:30:00Z"
}
```

Possible statuses: `open`, `pending`, `paid`, `expired`, `failed`, `cancelled`

### Mollie Webhook (internal)
```
POST /webhook/mollie
X-Mollie-Signature: hmac-sha256-signature
Content-Type: application/json

{
  "id": "tr_WDqYK6vllg"
}

Response 204: No Content
```

When payment is confirmed:
1. Payment status is updated to `paid`
2. User subscription is auto-created/updated
3. User `subscription_status` is set to `active`

## Database Schema

### Users Table
```sql
CREATE TABLE sportset_users (
  id VARCHAR(36) PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255),
  hashed_password VARCHAR(255) NOT NULL,
  subscription_status VARCHAR(50) DEFAULT 'active',
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

### Oura Tokens Table
```sql
CREATE TABLE sportset_oura_tokens (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) FK NOT NULL UNIQUE,
  encrypted_data TEXT NOT NULL,
  created_at TIMESTAMP,
  last_refreshed_at TIMESTAMP,
  expires_at TIMESTAMP NOT NULL
)
```

Tokens are encrypted using AES-256-GCM. See `src/core/security.py` for encryption/decryption.

### Subscriptions Table
```sql
CREATE TABLE sportset_subscriptions (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) FK NOT NULL,
  status VARCHAR(50) DEFAULT 'active',
  plan_id VARCHAR(100) NOT NULL,
  started_at TIMESTAMP,
  expires_at TIMESTAMP,
  renewal_date TIMESTAMP,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

### Payments Table
```sql
CREATE TABLE sportset_payments (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) FK NOT NULL,
  mollie_payment_id VARCHAR(255) UNIQUE NOT NULL,
  amount INT NOT NULL,
  currency VARCHAR(3) DEFAULT 'EUR',
  status VARCHAR(50) DEFAULT 'open',
  mollie_checkout_url TEXT,
  plan_id VARCHAR(100) NOT NULL,
  paid_at TIMESTAMP,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  metadata TEXT
)
```

## Security

### JWT Tokens
- Issued on login/register with 7-day expiry
- Include `sub` (user_id) and `email` claims
- Validated on protected endpoints
- Signed with `APP_SECRET_KEY` (HS256)

### Password Security
- Hashed using bcrypt (configurable rounds)
- Never stored in plaintext
- Verified on login

### Oura Token Encryption
- Access/refresh tokens encrypted at-rest using AES-256-GCM
- 96-bit random nonce per encryption
- Authentication tag prevents tampering
- Requires `TOKEN_ENCRYPTION_KEY` environment variable

### CORS
- Configurable allowed origins (env var `ALLOWED_ORIGINS`)
- Supports regex patterns for dynamic URLs (ngrok, VS Code tunnels)

## Error Handling

All endpoints return standard HTTP status codes:
- `200` OK
- `201` Created
- `204` No Content
- `400` Bad Request (validation error)
- `401` Unauthorized (missing/invalid token)
- `403` Forbidden (inactive user)
- `404` Not Found (resource not found)
- `409` Conflict (email already exists)
- `502` Bad Gateway (external API error)

Error response format:
```json
{
  "detail": "User not found or inactive"
}
```

## Rate Limiting

Default limits (configurable):
- AI calls: 10/minute per user
- Photo scans: 10/minute per IP
- Global: 60/minute per IP

## Development vs Production

### Development
- SQLite database
- Debug mode ON
- CORS allows localhost:5173, :3000, :8000
- Mock data returned if Oura not connected

### Production
- PostgreSQL via Supabase
- Debug mode OFF
- CORS configured for your domain
- Real Oura/Mollie data only

## Deployment Checklist

- [ ] Set `APP_ENV=production`
- [ ] Generate strong `APP_SECRET_KEY` and `TOKEN_ENCRYPTION_KEY`
- [ ] Add Oura OAuth credentials to environment
- [ ] Add Mollie API key and webhook secret
- [ ] Configure Supabase URL and service role key
- [ ] Set correct `OURA_REDIRECT_URI` (production domain)
- [ ] Set correct `MOLLIE_WEBHOOK_SECRET` (from Mollie dashboard)
- [ ] Update `FRONTEND_URL` to production domain
- [ ] Enable HTTPS only
- [ ] Set up database backups
- [ ] Configure monitoring/logging
- [ ] Test OAuth flow end-to-end
- [ ] Test payment webhook

## Support

For issues or questions:
1. Check API docs: http://localhost:8000/docs
2. Review error logs in Render dashboard
3. Check Oura/Mollie dashboard for webhook events
