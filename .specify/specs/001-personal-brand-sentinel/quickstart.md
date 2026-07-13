# Quickstart: Personal Brand Sentinel

Deploy the complete MVP stack on your Oracle VM in under 10 minutes.

## Prerequisites

- Oracle VM (2 OCPU, 12GB RAM) with Docker and Docker Compose installed
- Portainer installed (for stack management)
- Domain or IP accessible from your machine
- Telegram bot token (from [@BotFather](https://t.me/botfather))
- Postiz API key (generated after Postiz setup)

## Step 1: Clone & Configure

```bash
git clone <your-repo-url> /opt/n8n-social-brand
cd /opt/n8n-social-brand
cp .env.example .env
```

Edit `.env` — must set these:

```env
N8N_ENCRYPTION_KEY=<generate a random 32-char string>
POSTIZ_JWT_SECRET=<generate a random secret>
TELEGRAM_BOT_TOKEN=<your bot token from @BotFather>
TELEGRAM_CHAT_ID=<your Telegram user ID>
POSTIZ_API_KEY=<from Postiz Settings > Developers > Public API>
SCHEDULED_POST_TIME=10:00
```

## Step 2: Start the Stack

**Option A — CLI:**
```bash
docker compose up -d
```

**Option B — Portainer (fire-and-forget):**
1. Open Portainer → **Stacks** → **Add Stack**
2. Name: `n8n-social-brand`
3. Upload `docker-compose.yml` or paste contents
4. Add all `.env` variables in the **Environment variables** section
5. Click **Deploy the stack**

Verify all services:
```bash
curl http://localhost:8103/health
```

Verify all services:

```bash
curl http://localhost:8103/health
# → {"status":"ok","workers":{"n8n":"ok","postiz":"ok"}}

curl http://localhost:8103/capabilities
# → {"sentinel_type":"personal-brand-sentinel","capabilities":["post-draft","schedule-post"],"workers":{...}}
```

## Step 3: Configure Postiz

1. Open `http://<your-vm-ip>:5000`
2. Complete the setup wizard
3. Go to **Settings → Developers → Public API** → copy your API key
4. Add it to `.env` as `POSTIZ_API_KEY`
5. Go to **Integrations** → connect X, LinkedIn, Threads, Bluesky
6. Note each integration ID — add to `.env` as `POSTIZ_INTEGRATION_X=<id>`, `POSTIZ_INTEGRATION_LINKEDIN=<id>`, etc.

## Step 4: Import n8n Workflow

1. Open `http://<your-vm-ip>:5678`
2. Create account (first-run setup)
3. **Workflows → Import from File** → select `n8n-workflows/telegram-approval.json`
4. Configure the Telegram nodes with your bot token
5. Activate the workflow

## Step 5: Test the Pipeline

Send a test draft:

```bash
curl -X POST http://localhost:8103/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Testing the Personal Brand Sentinel! 🚀",
    "platforms": ["x"],
    "type": "now",
    "source": "manual"
  }'
```

Check Telegram → tap Approve → verify post appears on X.

## Daily Operations

- **Monitor**: Portainer dashboard → all service health
- **Logs**: `docker compose logs -f personal-brand-sentinel`
- **Stop**: `docker compose down`
- **Update**: `docker compose pull && docker compose up -d`

## Files Reference

| File | Purpose |
|---|---|
| `docker-compose.yml` | Portainer stack — deploy this |
| `.env` | All secrets and configuration |
| `sentinels/personal-brand/main.py` | FastAPI Sentinel (port 8103) |
| `janitor/main.py` | Stale job resetter (1min loop) |
| `n8n-workflows/telegram-approval.json` | Importable Telegram approval workflow |
