# Sportset Backend Deployment Guide

## Current Status

✅ Production-ready Sportset backend with:
- Oura OAuth 2.0 (login, callback, token storage, refresh)
- Supabase PostgreSQL integration
- Mollie payment gateway (checkout, webhooks, status)
- User authentication (register, login, logout, JWT)
- Protected data endpoints (sleep, activity, heart rate)
- Security: AES-256-GCM encryption, bcrypt hashing, JWT tokens

## Deployment Steps

### 1. Render Environment Variables

Go to https://dashboard.render.com and add these environment variables:

```
# Application
APP_ENV=production
APP_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(64))">
DEBUG=false
FRONTEND_URL=https://sportset.vercel.app  # Your frontend domain

# Database (Supabase)
DATABASE_URL=postgresql://[user]:[password]@[host]:[port]/[database]
SUPABASE_URL=https://[project-id].supabase.co
SUPABASE_SERVICE_ROLE_KEY=[service-role-key-from-supabase]

# Token Encryption
TOKEN_ENCRYPTION_KEY=<generate: openssl rand -hex 32>

# Oura OAuth (from https://cloud.ouraring.com/oauth/applications)
OURA_CLIENT_ID=<your-oura-client-id>
OURA_CLIENT_SECRET=<your-oura-client-secret>
OURA_REDIRECT_URI=https://[your-render-domain]/api/oura/callback

# Mollie Payment (from https://www.mollie.com/)
MOLLIE_API_KEY=<your-mollie-api-key>
MOLLIE_WEBHOOK_SECRET=<your-mollie-webhook-secret>

# CORS
ALLOWED_ORIGINS=https://sportset.vercel.app,https://www.sportset.app
ALLOWED_ORIGIN_REGEX=

# Rate Limiting
RATE_LIMIT_AI_CALLS=10/minute
RATE_LIMIT_SCAN=10/minute
RATE_LIMIT_GLOBAL=60/minute
```

### 2. Oura OAuth Setup

1. Visit https://cloud.ouraring.com/oauth/applications
2. Create OAuth 2.0 application
3. Set callback URI: `https://[your-render-domain]/api/oura/callback`
4. Copy client ID and secret to Render env vars

### 3. Mollie Webhook Setup

1. Visit https://dashboard.mollie.com/settings/webhooks
2. Add webhook URL: `https://[your-render-domain]/webhook/mollie`
3. Copy webhook secret to Render env var `MOLLIE_WEBHOOK_SECRET`

### 4. Supabase PostgreSQL Setup

1. Create Supabase project at https://supabase.com
2. Get connection string from Settings → Database
3. Add to `DATABASE_URL` env var
4. Get service role key from Settings → API
5. Add to `SUPABASE_SERVICE_ROLE_KEY` env var

### 5. Database Migration

When you redeploy, the backend will auto-create tables:
- `sportset_users` (email, password, subscription status)
- `sportset_oura_tokens` (encrypted OAuth tokens)
- `sportset_subscriptions` (subscription records)
- `sportset_payments` (Mollie payment records)

### 6. Test Production Backend

After deployment, test these endpoints:

```bash
# Test health check
curl https://[your-render-domain]/health

# Register user
curl -X POST https://[your-render-domain]/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123",
    "name": "Test User"
  }'

# Login
curl -X POST https://[your-render-domain]/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123"
  }'

# Get current user (replace TOKEN with JWT from login response)
curl -X GET https://[your-render-domain]/auth/me \
  -H "Authorization: Bearer TOKEN"

# Check Oura status
curl -X GET https://[your-render-domain]/api/oura/status \
  -H "Authorization: Bearer TOKEN"
```

## Post-Deployment Checklist

- [ ] Test user registration/login flow
- [ ] Test Oura OAuth connection (redirect to cloud.ouraring.com)
- [ ] Test Oura data endpoints (mock data if not connected)
- [ ] Test payment checkout creation (gets Mollie checkout URL)
- [ ] Test webhook receipt (Mollie → backend)
- [ ] Monitor logs in Render dashboard
- [ ] Enable auto-redeployment on GitHub push
- [ ] Set up error monitoring (Sentry, etc.)
- [ ] Configure database backups (Supabase auto-backup)

## Troubleshooting

### OAuth Redirect Loop
- Check `OURA_REDIRECT_URI` matches exactly in Oura dashboard
- Check `FRONTEND_URL` points to correct frontend domain

### Token Encryption Errors
- Verify `TOKEN_ENCRYPTION_KEY` is exactly 64 hex characters (32 bytes)
- Generate new: `openssl rand -hex 32`

### Mollie Webhook Not Received
- Check webhook URL in Mollie dashboard
- Verify webhook secret in env var matches Mollie dashboard
- Check Render logs for webhook receipt

### Database Connection Failed
- Verify `DATABASE_URL` is correct
- Check Supabase project is accessible
- Ensure service role key has database permissions

### Oura API Errors
- Check Oura credentials are correct
- Verify Oura OAuth app is approved by Oura team
- Check Oura rate limits (burst: 10/min, sustained: 1/sec)

## Scaling Considerations

### Database
- Supabase provides auto-scaling
- Monitor connection pool usage
- Add indexes on frequently-queried columns (user_id, email)

### Rate Limiting
- Adjust `RATE_LIMIT_*` env vars per your traffic
- Consider implementing per-subscription-tier limits

### Token Refresh
- Token refresh happens automatically on data endpoint access
- Adjust 5-minute buffer in `_get_valid_access_token()` if needed

### Webhooks
- Mollie retry policy: 5 retries over 5 days
- Store webhook delivery attempts in database for audit

## Monitoring

### Key Metrics
1. User registrations per day
2. Oura connections per day
3. Payment success rate
4. API response times
5. Database query times
6. JWT token expiry errors

### Alerts to Set Up
- High error rate (>5% of requests)
- Database connection pool exhaustion
- Webhook failures (payment webhooks not received)
- Oura API errors (token refresh failures)

## Security Best Practices

1. **Rotate secrets regularly**
   - Regenerate `APP_SECRET_KEY` every 90 days
   - Mollie → revoke old webhook secrets, create new ones

2. **Monitor token usage**
   - Log all OAuth token grants/refreshes
   - Alert on suspicious patterns

3. **Backup Mollie payment records**
   - Ensure payment data is backed up
   - Supabase auto-backup is enabled

4. **Enable HTTPS only**
   - Render auto-provides SSL/TLS

5. **Database security**
   - Use Supabase RLS (Row Level Security) for user data
   - Encrypt payment PII at application level

## Rollback Procedure

If deployment fails:
1. Click "Revert" in Render dashboard
2. Previous version will be restored
3. Database migrations are not rolled back (manual action needed)

## Next Steps

1. **Frontend Integration**
   - Update frontend to use new OAuth flow
   - Add checkout flow for payments
   - Display user profile and subscription status

2. **Mobile App** (if applicable)
   - Use same backend endpoints
   - Store JWT tokens in secure storage
   - Handle deep links for OAuth redirect

3. **Analytics**
   - Track user registrations, Oura connections, payments
   - Monitor subscription churn
   - Analyze sleep/activity trends

4. **Support & Documentation**
   - Set up customer support channel
   - Document API for third-party integrations
   - Create user onboarding guide

## Support

For deployment issues:
1. Check Render logs: Dashboard → Logs
2. Check Supabase logs: Console → Logs
3. Check Mollie logs: Dashboard → Webhooks
4. Check Oura logs: OAuth app details

Email: support@sportset.app
