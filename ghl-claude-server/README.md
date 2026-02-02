# GHL Claude Server

Automated personalized follow-up messages for GoHighLevel using Claude AI.

## How It Works

1. GHL workflow triggers webhook when lead enters pipeline stage
2. Server fetches contact details and conversation history from GHL
3. Claude generates a personalized message based on context
4. Server sends the message via GHL API

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/webhook/followup?step=1` | POST | Day 1 follow-up |
| `/webhook/followup?step=2` | POST | Day 3 follow-up |
| `/webhook/followup?step=3` | POST | Day 7 follow-up |
| `/webhook/reply` | POST | Auto-reply to inbound messages |

## Setup

### 1. Get Your API Keys

- **GHL Token**: Your Private Integration Token (pit-xxx)
- **Anthropic Key**: Get from https://console.anthropic.com/

### 2. Deploy to Vercel (Recommended)

```bash
# Install Vercel CLI
npm i -g vercel

# Navigate to server directory
cd ghl-claude-server

# Deploy
vercel

# Set environment variables
vercel env add GHL_API_TOKEN
vercel env add ANTHROPIC_API_KEY

# Deploy to production
vercel --prod
```

Your server URL will be something like: `https://ghl-claude-server.vercel.app`

### 3. Alternative: Run Locally with ngrok

```bash
# Install dependencies
npm install

# Create .env file
cp .env.example .env
# Edit .env with your keys

# Start server
npm start

# In another terminal, expose with ngrok
ngrok http 3000
```

### 4. Configure GHL Workflow

1. Go to **Automation** > **Workflows** in GHL
2. Create new workflow
3. Set trigger: **Pipeline Stage Changed** > "No Response after loom sent"
4. Add actions:

```
[Trigger: Pipeline Stage Changed]
        ↓
[Webhook: POST https://your-server.vercel.app/webhook/followup?step=1]
        ↓
[Wait: 2 days] (Enable "Stop if contact replies")
        ↓
[Webhook: POST https://your-server.vercel.app/webhook/followup?step=2]
        ↓
[Wait: 4 days] (Enable "Stop if contact replies")
        ↓
[Webhook: POST https://your-server.vercel.app/webhook/followup?step=3]
```

### 5. GHL Webhook Configuration

In the webhook action, set:
- **Method**: POST
- **URL**: `https://your-server.vercel.app/webhook/followup?step=1`
- **Headers**: `Content-Type: application/json`
- **Body** (Custom JSON):
```json
{
  "contact_id": "{{contact.id}}",
  "first_name": "{{contact.first_name}}",
  "email": "{{contact.email}}"
}
```

## Message Strategy

### Step 1 (Day 1)
Re-engage by acknowledging the loom video. Reference specific conversation details.

### Step 2 (Day 3)
Try a different angle - share value, address objections, or reference local market data.

### Step 3 (Day 7)
Low-pressure final check-in. Leave the door open gracefully.

### Reply Handler
When lead responds, Claude reads the full conversation and crafts a contextual response.

## Customization

Edit `COMPANY_CONTEXT` and `STEP_PROMPTS` in `index.js` to adjust:
- Company information
- Brand voice
- Message strategy per step

## Costs

- **Vercel**: Free tier is sufficient for most use cases
- **Claude API**: ~$0.01-0.05 per message depending on conversation length

## Troubleshooting

**Webhook not receiving data?**
- Check GHL workflow is active
- Verify the webhook URL is correct
- Check Vercel function logs

**Messages not sending?**
- Verify GHL_API_TOKEN has SMS permissions
- Check the contact has a valid phone number
- Review server logs for errors

**Claude responses seem off?**
- Review conversation history in GHL
- Adjust prompts in STEP_PROMPTS
- Check COMPANY_CONTEXT is accurate
