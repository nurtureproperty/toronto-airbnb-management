require('dotenv').config();
const express = require('express');
const Anthropic = require('@anthropic-ai/sdk');

const app = express();
app.use(express.json());

// Initialize Anthropic client
const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

// GHL API base URL
const GHL_API_BASE = 'https://services.leadconnectorhq.com';

// ============================================
// MULTI-ACCOUNT SYSTEM
// ============================================
const fs = require('fs');
const path = require('path');

// Load account configs
let ACCOUNTS = {};
try {
  ACCOUNTS = JSON.parse(fs.readFileSync(path.join(__dirname, 'accounts.json'), 'utf-8'));
  console.log(`Loaded ${Object.keys(ACCOUNTS).length} account configs:`, Object.values(ACCOUNTS).map(a => a.name).join(', '));
} catch (e) {
  console.error('Failed to load accounts.json:', e.message);
}

// Default account (Nurture PM) when no locationId provided
const DEFAULT_LOCATION_ID = 'vtTGsxK2RAKQfFtpkhx5';

function getAccount(locationId) {
  return ACCOUNTS[locationId] || ACCOUNTS[DEFAULT_LOCATION_ID] || null;
}

function getAccountToken(account) {
  if (!account) return process.env.GHL_API_TOKEN;
  return process.env[account.tokenEnvVar] || process.env.GHL_API_TOKEN;
}

// ============================================
// DYNAMIC KNOWLEDGE BASE (cached per account, 24h TTL)
// ============================================
const GITHUB_RAW_BASE = 'https://raw.githubusercontent.com/nurtureproperty/toronto-airbnb-management/master/ghl-claude-server/';
const knowledgeCache = {}; // { accountKey: { content, cachedAt } }
const KNOWLEDGE_CACHE_TTL = 24 * 60 * 60 * 1000; // 24 hours

async function getKnowledgeBase(account) {
  // For Nurture PM, also fetch the extended blog knowledge base
  const knowledgeFile = account?.knowledgeFile || 'accounts/nurture-pm.md';
  const cacheKey = knowledgeFile;
  const now = Date.now();

  if (knowledgeCache[cacheKey] && (now - knowledgeCache[cacheKey].cachedAt) < KNOWLEDGE_CACHE_TTL) {
    return knowledgeCache[cacheKey].content;
  }

  try {
    console.log(`Fetching knowledge base: ${knowledgeFile}...`);
    const response = await fetch(GITHUB_RAW_BASE + knowledgeFile);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    let text = await response.text();

    // For Nurture PM, also load the extended blog knowledge
    if (knowledgeFile === 'accounts/nurture-pm.md') {
      try {
        const extResponse = await fetch(GITHUB_RAW_BASE + 'bot-knowledge.md');
        if (extResponse.ok) {
          const extText = await extResponse.text();
          text += '\n\n## EXTENDED KNOWLEDGE BASE (blog articles, FAQs, detailed bylaws)\n\n' + extText;
        }
      } catch (e) {
        console.error('Could not fetch extended knowledge:', e.message);
      }
    }

    // Truncate to ~80K chars to stay within Claude context limits
    const content = text.length > 80000 ? text.slice(0, 80000) + '\n\n[Knowledge base truncated]' : text;
    knowledgeCache[cacheKey] = { content, cachedAt: now };
    console.log(`Knowledge base loaded for ${account?.name || 'default'}: ${(content.length / 1024).toFixed(1)} KB`);
    return content;
  } catch (e) {
    console.error('Failed to fetch knowledge base:', e.message);
    if (knowledgeCache[cacheKey]) return knowledgeCache[cacheKey].content;
    return null;
  }
}

// ============================================
// COMPANY CONTEXT FOR CLAUDE
// ============================================
const COMPANY_CONTEXT = `
You are a sales development representative for Nurtre, a lead generation and lead nurturing company for real estate and mortgage professionals.

## Company Info
- Company Name: Nurtre Inc
- Address: 140 Simcoe Street, Toronto, ON M5H 4E9
- Website: nurtre.io

## What We Do
We help real estate agents, teams, brokerages, and mortgage professionals get qualified leads and close more deals through:
- **Video Ads on YouTube:** We produce video content that gets leads to want to speak to our clients specifically
- **Inside Sales Team:** Our English-fluent trained professionals call leads within 5 minutes to qualify them
- **Aggressive Follow-up:** 10+ calls and texts in the first week
- **Lead Nurturing:** We re-engage leads even after you've spoken to them, helping with follow-up until the deal closes
- **Exclusive Leads:** All leads are exclusive to you, not shared with other agents

## Key Differentiators
- Leads actually WANT to speak to the agent specifically (not generic leads)
- We handle the follow-up and nurturing so you can focus on closing
- Real English-fluent professionals, not offshore call centers
- We're great at helping agents who are already good on camera
- If you have a social media audience, we can retarget them with video ads

## Ideal Client
- Real estate agents, teams, or brokerages
- Mortgage professionals
- Already comfortable on camera or have video content
- Have an existing social media audience we can retarget

## Our Approach
We've already sent this agent a personalized video commenting on their YouTube content. Now we're following up to see if they're interested in learning more about how we can help them generate and nurture leads.

## Brand Voice
- Friendly, warm, and FUNNY. Write like you're texting a friend who makes you smile
- Use light humor, witty observations, or playful self-awareness
- Examples of humor: "I promise I'm not a robot (well, mostly)" or "I know, another follow-up text, but hear me out..."
- Be genuinely interested in their content. Compliment specific things you noticed
- Keep it real. A little self-deprecating humor works great ("I'll stop bugging you after this, pinky promise")
- Respect their time but make the message enjoyable to read
- NO corporate speak, NO stiff language. Write like a real human with personality

## Goal of Follow-ups
Get them on a quick Google Meet video call to discuss how we can help them generate and nurture leads.

## Words to Use
- "Quick call" or "video chat"
- "Your content"
- "Your channel"
- "Qualified leads"
- "Lead nurturing"
- "Follow-up"

## Words to Avoid
- "Buy" or "purchase"
- Overly salesy language
- Generic templates that don't reference their specific situation
- Desperate or pushy language
- **NEVER say "just sent" or "just reached out".** ALWAYS check conversation history dates first

## CRITICAL: TIMING AWARENESS
**ALWAYS check the dates in the conversation history before writing your message.**
- If the last message was sent weeks or months ago, DO NOT say "just sent" or imply recent contact
- Instead use phrases like: "Been a while!", "Circling back...", "Remember that video audit I sent?", "It's been a minute!"
- The dates are shown in the conversation history like "[1/15/2026] US: message here"
- Match your language to the actual timeline
`;

// ============================================
// STEP-SPECIFIC PROMPTS (Nurture Property Management)
// Note: Old Nurtre lead gen prompts preserved in COMPANY_CONTEXT above.
// When Nurtre outreach resumes, create separate NURTRE_STEP_PROMPTS.
// ============================================
const STEP_PROMPTS = {
  1: `This is the FIRST follow-up message to a property management lead.

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

READ THE CONVERSATION HISTORY FIRST:
- Check what we already discussed (their property, location, questions, concerns)
- Reference specific details they shared (property type, address, number of bedrooms, city)
- CHECK THE DATES: If it's been a while since last contact, acknowledge naturally

YOUR GOAL: Re-engage them toward booking a free consultation call.

APPROACH:
- Reference their property or situation specifically (don't be generic)
- Mention one relevant benefit (e.g., revenue potential, we handle everything, no contracts)
- End with a soft question or offer to chat
- If they mentioned a specific concern before (bylaws, pricing, investment property), address it

Guidelines:
- Keep it short (2-3 sentences max)
- Be warm and casual, like texting a friend
- Be helpful first, sales second
- If you know their city, mention something relevant (bylaw info, market opportunity)
- NEVER use dashes/hyphens except in compound words like "short-term"
- When suggesting a meeting, use available time slots if provided
- Remember: FIRST WORD must be "Hey [their name],"`,

  2: `This is the SECOND follow-up message (Day 3).

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

READ ALL PREVIOUS MESSAGES:
- What did we already say? DO NOT repeat the same angle
- What do we know about their property/situation?
- CHECK THE DATES for timing awareness

YOUR GOAL: Different angle to get them on a call.

APPROACH:
- Try a completely different angle than message 1
- Share a relevant insight (e.g., "properties like yours in [city] are averaging $X/mo on Airbnb")
- Or address a common concern ("a lot of owners worry about bylaws, but we handle all of that")
- Keep it value-forward, not pushy

Guidelines:
- Keep it short (2-3 sentences max)
- Use a DIFFERENT approach than message 1
- Light humor welcome ("I know, I'm back again...")
- NEVER use dashes/hyphens except in compound words
- Remember: FIRST WORD must be "Hey [their name],"`,

  3: `This is the THIRD follow-up message (Day 7).

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

READ ALL PREVIOUS MESSAGES: Don't repeat any previous angles. CHECK THE DATES.

YOUR GOAL: Last strong push before backing off.

APPROACH:
- Fresh angle. Maybe mention a specific result (client went from -$926/mo to +$847/mo)
- Or offer something specific: "Happy to run a free revenue estimate for your place, no strings attached"
- Low pressure but make the value clear

Guidelines:
- Keep it short (1-2 sentences)
- Self-aware humor is great here ("Ok, last pitch, I promise")
- NEVER use dashes/hyphens except in compound words
- Remember: FIRST WORD must be "Hey [their name],"`,

  4: `This is the FOURTH follow-up message (Day 14).

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

Long-term nurture touch. READ ALL PREVIOUS MESSAGES. CHECK THE DATES.

APPROACH:
- Casual check-in, not a pitch
- Reference their property/situation if you know it
- "Just checking in, still happy to chat whenever timing works"
- Maybe share one useful tidbit about their area

Guidelines:
- Keep it short (1-2 sentences)
- Very low pressure
- Humor about the time gap is fine
- Remember: FIRST WORD must be "Hey [their name],"`,

  5: `This is the FIFTH follow-up message (Day 21).

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

Value-add touch. READ ALL PREVIOUS MESSAGES. CHECK THE DATES.

APPROACH:
- Lead with something useful, no ask
- Share a relevant market insight or tip for their area
- "Thought you might find this interesting" energy

Guidelines:
- Keep it short (1-2 sentences)
- Pure value, no pitch
- Stay on their radar without being annoying
- Remember: FIRST WORD must be "Hey [their name],"`,

  6: `This is the SIXTH follow-up message (Day 30).

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

Monthly check-in. READ ALL PREVIOUS MESSAGES. CHECK THE DATES.

Guidelines:
- Keep it very short (1-2 sentences)
- Friendly, zero pressure
- "Just your monthly check-in" energy
- Leave the door open
- Remember: FIRST WORD must be "Hey [their name],"`,

  7: `This is the SEVENTH and FINAL follow-up message (Day 45).

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

Final touch. READ ALL PREVIOUS MESSAGES.

Guidelines:
- Keep it very short (1 sentence)
- Warm farewell with humor
- Leave the door open gracefully
- "I'll stop bugging you, but if you ever want to chat about your property, you know where to find me"
- Remember: FIRST WORD must be "Hey [their name],"`,

  // For handling inbound replies
  reply: `The lead has REPLIED to your message. Craft a personalized response.

**MANDATORY FORMAT: Start with "Hey [Name]," using their first name.**

READ THEIR MESSAGE CAREFULLY and respond to what they actually said.

APPROACH:
- Answer their question directly using your knowledge base (pricing, bylaws, services, etc.)
- If they ask about a specific city's regulations, give them the key details
- If they're interested, offer to book a call using available time slots
- If they give a phone number or ask for a callback, use the notify_team tool
- If they're not interested, be gracious
- Match their tone and energy

Guidelines:
- Keep it conversational and short (1-3 sentences)
- Answer first, then nudge toward a call if it fits naturally
- Be helpful first, sales second
- NEVER use dashes/hyphens except in compound words
- NEVER promise to personally call or visit. You're a text assistant
- If you don't know something, say so honestly and offer to find out on a call
- Remember: FIRST WORD must be "Hey [their name],"`,
};

// ============================================
// GHL API FUNCTIONS
// ============================================

async function getContact(contactId, token = null) {
  const response = await fetch(`${GHL_API_BASE}/contacts/${contactId}`, {
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch contact: ${response.status}`);
  }

  return response.json();
}

async function getConversations(contactId, token = null) {
  const response = await fetch(`${GHL_API_BASE}/conversations/search?contactId=${contactId}`, {
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch conversations: ${response.status}`);
  }

  return response.json();
}

async function getMessages(conversationId, token = null) {
  const response = await fetch(`${GHL_API_BASE}/conversations/${conversationId}/messages`, {
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch messages: ${response.status}`);
  }

  return response.json();
}

async function sendSMS(contactId, message, token = null) {
  const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      type: 'SMS',
      contactId: contactId,
      message: message,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to send SMS: ${response.status} - ${error}`);
  }

  return response.json();
}

// ============================================
// CLAUDE API FUNCTION
// ============================================

async function generateResponse(contact, conversationHistory, step, firstName = 'there', contactId = null, account = null) {
  // Build context from contact data
  const contactContext = buildContactContext(contact);
  const token = getAccountToken(account);

  // Get step-specific prompt
  const stepPrompt = STEP_PROMPTS[step] || STEP_PROMPTS.reply;

  // Fetch knowledge base and calendar slots in parallel
  const calendarId = account?.calendarId || process.env.GHL_CALENDAR_ID;
  const [knowledgeBase, rawSlots] = await Promise.all([
    getKnowledgeBase(account),
    calendarId ? getCalendarFreeSlots(calendarId, token).catch(e => { console.error('Could not fetch calendar slots:', e.message); return null; }) : Promise.resolve(null),
  ]);

  let slotsContext = 'No specific slots available right now. Direct to nurturestays.ca/contact to book.';
  if (rawSlots) {
    const formatted = formatSlotsForClaude(rawSlots);
    if (formatted) slotsContext = formatted;
  }

  // Build system prompt from account knowledge base
  let systemPrompt = knowledgeBase || NURTURE_PM_CONTEXT;

  // Build the full prompt
  const userPrompt = `
## CRITICAL: The lead's first name is "${firstName}" - your message MUST start with "Hey ${firstName},"

## Contact Information
${contactContext}

## Available Meeting Slots
${slotsContext}

## Conversation History
${conversationHistory}

## Your Task
${stepPrompt}

Generate the SMS message now. IMPORTANT: Start with "Hey ${firstName}," - this is mandatory. Keep it short and natural.
If the lead has clearly confirmed they want to book a specific slot, use the book_appointment tool.`;

  // Include tools
  const tools = [NOTIFY_TEAM_TOOL];
  if (calendarId) tools.push(BOOK_APPOINTMENT_TOOL);

  const messages = [{ role: 'user', content: userPrompt }];

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 300,
    system: systemPrompt,
    tools,
    messages,
  });

  // Handle tool use (appointment booking and/or team notification)
  const toolUseBlocks = response.content.filter(b => b.type === 'tool_use');
  const textBlock = response.content.find(b => b.type === 'text');

  if (toolUseBlocks.length > 0) {
    const toolResults = [];

    for (const toolUseBlock of toolUseBlocks) {
      if (toolUseBlock.name === 'book_appointment' && calendarId && contactId) {
        const { start_datetime, duration_minutes = 30 } = toolUseBlock.input;
        console.log('SMS: Claude wants to book appointment at:', start_datetime);

        let toolResultContent;
        try {
          const appt = await createAppointment(calendarId, contactId, start_datetime, duration_minutes, token);
          console.log('Appointment created:', appt?.id || JSON.stringify(appt).slice(0, 100));
          toolResultContent = JSON.stringify({ success: true, message: 'Appointment booked successfully' });
        } catch (e) {
          console.error('Failed to create appointment:', e.message);
          toolResultContent = JSON.stringify({ success: false, error: e.message });
        }

        toolResults.push({ type: 'tool_result', tool_use_id: toolUseBlock.id, content: toolResultContent });

      } else if (toolUseBlock.name === 'notify_team') {
        const { lead_name, lead_phone, summary, urgent } = toolUseBlock.input;
        console.log(`SMS: Notifying team: ${lead_name} - ${summary} (urgent: ${urgent})`);

        await Promise.all([
          notifyTeamSlack(lead_name, lead_phone, summary, urgent, contactId),
          notifyTeamSMS(lead_name, lead_phone, summary, urgent, token),
        ]);

        toolResults.push({ type: 'tool_result', tool_use_id: toolUseBlock.id, content: JSON.stringify({ success: true, message: 'Team notified' }) });
      }
    }

    // Get final message after tools ran
    const confirmResponse = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 300,
      system: systemPrompt,
      tools,
      messages: [
        ...messages,
        { role: 'assistant', content: response.content },
        { role: 'user', content: toolResults },
      ],
    });

    let confirmText = confirmResponse.content.find(b => b.type === 'text')?.text?.trim() || '';
    if ((confirmText.startsWith('"') && confirmText.endsWith('"')) || (confirmText.startsWith("'") && confirmText.endsWith("'"))) {
      confirmText = confirmText.slice(1, -1);
    }

    // Guarantee name
    const greet = `hey ${firstName.toLowerCase()}`;
    if (!confirmText.toLowerCase().startsWith(greet)) {
      confirmText = confirmText.replace(/^(hey there,?|hi there,?|hey,?|hi,?)\s*/i, '');
      confirmText = `Hey ${firstName}, ${confirmText}`;
    }
    return confirmText;
  }

  // No tool use - return plain text
  let message = textBlock?.text?.trim() || '';
  if ((message.startsWith('"') && message.endsWith('"')) || (message.startsWith("'") && message.endsWith("'"))) {
    message = message.slice(1, -1);
  }

  // Guarantee name is included
  const expectedGreeting = `hey ${firstName.toLowerCase()}`;
  if (!message.toLowerCase().startsWith(expectedGreeting)) {
    message = message.replace(/^(hey there,?|hi there,?|hey,?|hi,?)\s*/i, '');
    message = `Hey ${firstName}, ${message}`;
  }

  return message;
}

function buildContactContext(contact) {
  const c = contact.contact || contact;

  let context = `Name: ${c.firstName || ''} ${c.lastName || ''}`.trim();

  if (c.email) context += `\nEmail: ${c.email}`;
  if (c.phone) context += `\nPhone: ${c.phone}`;
  if (c.address1) context += `\nAddress: ${c.address1}`;
  if (c.city) context += `\nCity: ${c.city}`;

  // Important custom fields for YouTube outreach
  const importantFields = [
    'Loom Watched Follow Up',  // CRITICAL: Check if they watched the video
    'Custom Video Title and Comment',
    'Clipio Link',
    'Channel Video Page',
    'Channel link',
    'Video Link',
    'Call Notes',
    'Notes'
  ];

  // Custom fields
  if (c.customFields && c.customFields.length > 0) {
    context += '\n\nRelevant Details:';
    c.customFields.forEach(field => {
      if (field.value) {
        const fieldName = field.key || field.id;
        // Prioritize important fields
        if (importantFields.some(f => fieldName.toLowerCase().includes(f.toLowerCase()))) {
          context += `\n- ${fieldName}: ${field.value}`;
        }
      }
    });

    // Add other custom fields
    context += '\n\nOther Info:';
    c.customFields.forEach(field => {
      if (field.value) {
        const fieldName = field.key || field.id;
        if (!importantFields.some(f => fieldName.toLowerCase().includes(f.toLowerCase()))) {
          context += `\n- ${fieldName}: ${field.value}`;
        }
      }
    });
  }

  // Tags
  if (c.tags && c.tags.length > 0) {
    context += `\n\nTags: ${c.tags.join(', ')}`;
  }

  // Notes
  if (c.notes) {
    context += `\n\nNotes: ${c.notes}`;
  }

  return context;
}

function formatConversationHistory(messagesResponse) {
  // Handle various GHL API response formats
  // GHL returns: { messages: { lastMessageId, nextPage, messages: [...] } }
  let messageList = null;

  if (Array.isArray(messagesResponse)) {
    messageList = messagesResponse;
  } else if (messagesResponse?.messages?.messages && Array.isArray(messagesResponse.messages.messages)) {
    // Nested format: { messages: { messages: [...] } }
    messageList = messagesResponse.messages.messages;
  } else if (messagesResponse?.messages && Array.isArray(messagesResponse.messages)) {
    messageList = messagesResponse.messages;
  } else if (messagesResponse?.data && Array.isArray(messagesResponse.data)) {
    messageList = messagesResponse.data;
  }

  if (!messageList || messageList.length === 0) {
    return 'No previous messages.';
  }

  // Sort by date and take last 20 messages
  const sorted = [...messageList]
    .sort((a, b) => new Date(a.dateAdded || a.createdAt || 0) - new Date(b.dateAdded || b.createdAt || 0))
    .slice(-20);

  return sorted.map(msg => {
    const direction = msg.direction === 'inbound' ? 'LEAD' : 'US';
    const date = new Date(msg.dateAdded || msg.createdAt).toLocaleDateString();
    const body = msg.body || msg.message || msg.text || '[no text]';
    return `[${date}] ${direction}: ${body}`;
  }).join('\n');
}

// ============================================
// WEBHOOK ENDPOINTS
// ============================================

// Health check
app.get('/', (req, res) => {
  res.json({ status: 'ok', service: 'GHL Claude Server' });
});

// Helper to extract contact ID from various GHL webhook formats
function extractContactId(body) {
  // GHL sends data in many formats depending on workflow configuration
  // Try all common patterns
  return body.contact_id
    || body.contactId
    || body.id
    || body.contact?.id
    || body.customData?.contact_id
    || body.customData?.contactId
    || (typeof body.contact === 'string' ? body.contact : null)
    || body.workflow?.contact_id
    || body.workflow?.contactId;
}

// Main webhook endpoint for follow-up sequence
app.post('/webhook/followup', async (req, res) => {
  try {
    console.log('Received webhook:', JSON.stringify(req.body, null, 2));
    console.log('Query params:', req.query);

    // Detect account from locationId or query param
    const locationId = req.body.locationId || req.body.location_id || req.query.location || DEFAULT_LOCATION_ID;
    const account = getAccount(locationId);
    const token = getAccountToken(account);
    console.log(`Account: ${account?.name || 'default'} (${locationId})`);

    // Extract data from GHL webhook - try multiple formats
    const contactId = extractContactId(req.body);
    const step = parseInt(req.query.step || req.body.step || '1');

    if (!contactId) {
      console.error('No contact ID provided');
      return res.status(400).json({ error: 'Missing contact_id' });
    }

    console.log(`Processing step ${step} for contact ${contactId}`);

    // Extract first name directly from webhook body (most reliable source)
    const firstName = req.body.first_name || req.body.firstName || 'there';
    console.log('First name from webhook:', firstName);

    // Fetch contact details
    const contact = await getContact(contactId, token);
    console.log('Contact fetched:', contact.contact?.firstName);

    // Fetch conversation history
    const conversations = await getConversations(contactId, token);
    let conversationHistory = 'No previous messages.';

    if (conversations.conversations && conversations.conversations.length > 0) {
      const conversationId = conversations.conversations[0].id;
      const messages = await getMessages(conversationId, token);
      conversationHistory = formatConversationHistory(messages);
    }

    // Generate personalized response with Claude using account context
    const generatedMessage = await generateResponse(contact, conversationHistory, step, firstName, contactId, account);
    console.log('Generated message:', generatedMessage);

    // Send the SMS via GHL
    const sendResult = await sendSMS(contactId, generatedMessage, token);
    console.log('SMS sent successfully');

    res.json({
      success: true,
      contactId,
      step,
      messageSent: generatedMessage,
      sendResult,
    });

  } catch (error) {
    console.error('Webhook error:', error);
    res.status(500).json({
      error: error.message,
      stack: process.env.NODE_ENV === 'development' ? error.stack : undefined,
    });
  }
});

// Debug endpoint - shows what GHL is sending (useful for troubleshooting)
app.post('/webhook/debug', async (req, res) => {
  console.log('DEBUG - Headers:', JSON.stringify(req.headers, null, 2));
  console.log('DEBUG - Body:', JSON.stringify(req.body, null, 2));
  console.log('DEBUG - Query:', req.query);

  const extractedId = extractContactId(req.body);

  res.json({
    received: true,
    extractedContactId: extractedId,
    body: req.body,
    query: req.query
  });
});

// Webhook endpoint for handling inbound replies
app.post('/webhook/reply', async (req, res) => {
  try {
    console.log('Received reply webhook:', JSON.stringify(req.body, null, 2));

    // Detect account
    const locationId = req.body.locationId || req.body.location_id || req.query.location || DEFAULT_LOCATION_ID;
    const account = getAccount(locationId);
    const token = getAccountToken(account);
    console.log(`Account: ${account?.name || 'default'} (${locationId})`);

    const contactId = extractContactId(req.body);

    if (!contactId) {
      return res.status(400).json({ error: 'Missing contact_id' });
    }

    // Extract first name directly from webhook body
    const firstName = req.body.first_name || req.body.firstName || 'there';
    console.log('First name from webhook:', firstName);

    // Fetch contact and conversation
    const contact = await getContact(contactId, token);
    const conversations = await getConversations(contactId, token);

    let conversationHistory = 'No previous messages.';
    if (conversations.conversations && conversations.conversations.length > 0) {
      const conversationId = conversations.conversations[0].id;
      const messages = await getMessages(conversationId, token);
      conversationHistory = formatConversationHistory(messages);
    }

    // Generate reply using 'reply' step
    const generatedMessage = await generateResponse(contact, conversationHistory, 'reply', firstName, contactId, account);
    console.log('Generated reply:', generatedMessage);

    // Send the SMS
    const sendResult = await sendSMS(contactId, generatedMessage, token);

    res.json({
      success: true,
      contactId,
      messageSent: generatedMessage,
      sendResult,
    });

  } catch (error) {
    console.error('Reply webhook error:', error);
    res.status(500).json({ error: error.message });
  }
});

// ============================================
// NURTURE PROPERTY MANAGEMENT - FACEBOOK MESSENGER
// ============================================

const NURTURE_PM_CONTEXT = `You are texting as a rep for Nurture, an Airbnb management company in the GTA. Write like you're texting a friend. Short, casual, no fluff.

ABOUT US:
- Premium Airbnb management for Southern Ontario homeowners
- 12-15% fee on host payout only (competitors charge 18-25%). No cut of cleaning fees or Airbnb service charges
- Clients see 30-100% more income. No contracts (30-day cancellation), no startup costs, commission only
- You own your listing and all reviews. First booking within 1 week on average
- 4.9 star average guest rating. Under 9-minute average response time
- Phone: (647) 957-8956 | nurturestays.ca
- Hours: Mon-Fri 10am-7pm, Sat-Sun 11am-5pm
- We started as Airbnb owners ourselves, fired our property managers, and built something better

SERVICE AREAS:
- GTA Core: Toronto (all boroughs), North York, Scarborough, Etobicoke, Downtown Toronto
- Peel: Mississauga, Brampton, Caledon
- York: Vaughan, Richmond Hill, Markham, Aurora, Newmarket
- Halton: Oakville, Burlington, Milton
- Durham: Ajax, Pickering, Whitby, Oshawa
- Other: Hamilton, Kingston, Waterloo Region, Niagara Region, cottage country
- If they ask about a city not listed, say we may be able to help and suggest booking a call

SERVICES:
- Full Airbnb Management (complete hands-off, 12-15%)
- Short-Term Rental Management (nightly/vacation rentals)
- Mid-Term Rental Management (30+ day rentals, corporate housing)
- Airbnb Co-Hosting (flexible support, owner stays in control)
- Listing creation, optimization, and professional photography (HDR, virtual staging)
- Dynamic pricing (manual + AI, event-based, seasonal adjustments)
- Multi-platform distribution (Airbnb, VRBO, Booking.com)
- Guest communication, screening, vetting, and review management
- Professional cleaning coordination and same-day turnovers
- Supply restocking (toiletries, coffee, linens), linen management
- Smart lock / key exchange management
- Maintenance, repairs, contractor coordination
- Monthly performance reports with detailed financials
- Insurance claim assistance, furnishing consulting

PRICING:
- Starter (12%): listing creation, multi-platform distribution, dynamic pricing, listing SEO, guest communication, guest vetting, screening, review management, monthly reports, booking management
- Professional (15%, most popular): everything in Starter PLUS professional cleaning, linen & supply restocking, smart lock management, dedicated account manager, contractor coordination, insurance claim assistance, guest e-book, furnishing consulting
- Fee is on host payout only. No setup fees, no monthly minimums. "We only earn when you earn"

CLIENT RESULTS (use sparingly, one at a time):
- 1-bed condo went from -$926/mo (long-term) to +$847/mo with Airbnb (87% increase first month)
- 1-bed condo: $4,123/mo after switching to us
- Average managed listing: $4,460+/mo
- We've never had a client make less with short/mid-term vs long-term

COMMON QUESTIONS:
- "How long to get listed?" Less than a week. First booking within 1 week on average
- "Do I need a long contract?" No. 30-day cancellation notice, that's it
- "Who owns the listing?" You do. Created under your account. If you leave, everything stays with you
- "Can I still use my property?" Yes! Just block the dates you want for personal use
- "Starter vs Professional?" Starter (12%) is for hands-on hosts. Professional (15%) is true full-service where we handle everything. Most clients pick Professional
- "What about cleaning fees?" We coordinate cleaning. The cleaning fee charged to guests covers the cost, we don't take a cut of it
- "Can I Airbnb my investment property?" Most GTA cities require principal residence for short-term rentals. But mid-term (30+ days) works for investment properties since it's exempt from STR rules. We can help with both
- "What about bylaws/licensing?" We know the regulations inside and out. We handle licensing and compliance for you

REGULATIONS BY CITY (use when someone asks about a specific city):
- Toronto: 180 nights/year entire home (unlimited for room rentals while home), principal residence only, registration required, 8.5% MAT
- Mississauga: 180 days/year, principal residence only, license $283/year, fines up to $100K
- Brampton: 180 days/year, principal residence only, max 3 bedrooms rented, 4% MAT
- Vaughan: 29 days or less = STR, principal residence only, license + MAT registration, 4% MAT
- Hamilton: Principal residence only, license $200-$1,000, $1M liability insurance, license valid 2 years
- Oakville: 28 days or less = STR, principal residence, license $237/year, 4% MAT
- Burlington: 183 days/year max, principal residence, license required, $2M liability insurance, demerit point system
- Milton: 180 days/year, principal residence, license required, $2M insurance, no parties/events allowed
- Oshawa: 180 days/year, principal residence, license $150, 5% MAT, $2M insurance
- Ottawa: Under 30 nights = STR, principal residence (cottage exception for rural), permit $123/2 years, 4% MAT
- London: 29 days or less, principal residence, license $196/year, 4% MAT
- Ajax, Pickering, Clarington: Not regulated, no specific STR bylaws
- Richmond Hill: Not regulated (under review)
- Markham: STRs under 30 days generally not allowed
- Niagara Falls: Strictly regulated, zoning restricted (tourist/commercial zones only), license $500, $2/night MAT
- Caledon: Regulated spring 2026, principal residence, 180 nights, 300 license cap, $500/year
- Muskoka Lakes: License $1,000/year, 2 persons per bedroom max, demerit point system
- General: Most regulated cities require principal residence. Mid-term (30+ days) usually exempt. Condo corps can prohibit STRs even if city allows. Always verify with municipality before listing
- If asked about a city not listed here, say "I'd want to double check the latest rules for that area. Let's hop on a call and I can give you the full breakdown"

WHAT HAPPENS ON A FREE CONSULTATION CALL:
- Custom revenue projection for their specific property
- Breakdown of expenses so they see real profit, not just revenue
- Honest assessment of whether Airbnb makes sense for them
- No obligation to sign up

WRITING RULES:
- Write like you're texting. 1-3 sentences max. No essays
- NEVER use dashes/hyphens ( - ) except in compound words like "short-term"
- First person ("I", "we"). Never sign off with a name
- Answer their question first, then nudge toward next step (estimate, call, nurturestays.ca/contact)
- Don't make up numbers. Only cite the exact results above
- Be helpful first, sales second. No corporate speak, no fluff
- If someone asks something you genuinely don't know, say so and offer to find out on a call

MEETING AVAILABILITY (STRICT RULES):
- ONLY offer meetings Monday to Friday, 10:00 AM to 6:30 PM Eastern Time (Toronto time)
- NEVER suggest Saturday or Sunday under any circumstances
- When offering to book, always use a specific time slot from the Available Meeting Slots list provided in the prompt
- If no slots are listed, say "book a quick call at nurturestays.ca/contact" instead of guessing a time`;

const NURTURE_FB_PROMPT = `Reply to the lead's LATEST message. Read the full conversation history first.

RULES:
1. Never ask something they already answered. Read the history
2. Reply to their most recent message directly. Don't start over
3. Keep it short. 1-3 sentences. Match their energy
4. If the conversation is already going, don't re-introduce yourself
5. Answer first, then nudge toward a call or estimate if it fits naturally
6. When suggesting a meeting, ONLY use time slots from the "Available Meeting Slots" list below. Never invent times. If they confirm a slot, use the book_appointment tool to lock it in
7. NEVER say "I'll give you a call", "I'll call you", "let me call you", or promise ANY phone call. You are a text assistant and cannot make calls. Instead, offer to BOOK a consultation using the available time slots below. Example: "Want me to lock in a quick 15 min call? I've got [slot] or [slot] open." If no slots are available, say "You can book a free consultation at nurturestays.ca/contact"
8. If someone gives their phone number and asks for a callback, use the notify_team tool so someone can call them back. Say something like "Got it! I've flagged your number for the team, someone will reach out shortly. In the meantime, mind if I ask what property you're looking to manage?"
9. If a lead seems urgent or ready to talk NOW (gives phone number, says "call me", "ASAP", "right now", etc.), ALWAYS use the notify_team tool with urgent: true
10. When the conversation naturally reaches a point where a call would help, proactively offer available time slots from the list below`;

// ============================================
// CALENDAR API FUNCTIONS
// ============================================

const NOTIFY_TEAM_TOOL = {
  name: 'notify_team',
  description: 'Notify the team (via SMS and Slack) that a lead needs attention. Use this when a lead gives their phone number, asks for a callback, says "call me", or wants to talk ASAP. Always use this BEFORE replying so the team gets notified immediately.',
  input_schema: {
    type: 'object',
    properties: {
      lead_name: {
        type: 'string',
        description: 'The lead\'s name',
      },
      lead_phone: {
        type: 'string',
        description: 'The lead\'s phone number (if provided)',
      },
      summary: {
        type: 'string',
        description: 'Brief summary of what the lead wants (e.g. "wants a callback to discuss their condo", "ready to talk ASAP about property management")',
      },
      urgent: {
        type: 'boolean',
        description: 'True if the lead wants immediate attention (said "ASAP", "call me now", gave phone number for callback)',
        default: false,
      },
    },
    required: ['lead_name', 'summary'],
  },
};

async function notifyTeamSMS(leadName, leadPhone, summary, urgent, token = null) {
  const ownerPhone = process.env.OWNER_PHONE;
  if (!ownerPhone) {
    console.log('OWNER_PHONE not set, skipping SMS notification');
    return;
  }

  const urgentTag = urgent ? '🔴 URGENT' : '📩 New';
  let msg = `${urgentTag} FB lead: ${leadName}`;
  if (leadPhone) msg += ` (${leadPhone})`;
  msg += `\n${summary}`;

  try {
    // Send SMS via GHL internal notification (to owner's contact in GHL)
    const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
        'Version': '2021-07-28',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        type: 'SMS',
        contactId: ownerPhone, // This should be the owner's GHL contact ID
        message: msg,
      }),
    });
    console.log('Team SMS notification sent:', response.ok);
  } catch (e) {
    console.error('Failed to send SMS notification:', e.message);
  }
}

async function notifyTeamSlack(leadName, leadPhone, summary, urgent, contactId) {
  const slackToken = process.env.SLACK_BOT_TOKEN;
  const slackChannel = process.env.SLACK_CHANNEL_ID;
  if (!slackToken || !slackChannel) {
    console.log('Slack not configured, skipping Slack notification');
    return;
  }

  const urgentEmoji = urgent ? ':rotating_light:' : ':incoming_envelope:';
  const urgentLabel = urgent ? '*URGENT* ' : '';
  let text = `${urgentEmoji} ${urgentLabel}*FB Messenger Lead Wants a Call*\n`;
  text += `*Name:* ${leadName}\n`;
  if (leadPhone) text += `*Phone:* ${leadPhone}\n`;
  text += `*Summary:* ${summary}`;
  if (contactId) text += `\n<https://app.gohighlevel.com/v2/location/your-location/contacts/${contactId}|View in GHL>`;

  try {
    const response = await fetch('https://slack.com/api/chat.postMessage', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${slackToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        channel: slackChannel,
        text,
        unfurl_links: false,
      }),
    });
    const result = await response.json();
    console.log('Slack notification sent:', result.ok);
  } catch (e) {
    console.error('Failed to send Slack notification:', e.message);
  }
}

const BOOK_APPOINTMENT_TOOL = {
  name: 'book_appointment',
  description: 'Book a consultation appointment in the CRM calendar. Only use this tool when the lead has explicitly confirmed they want to book at a specific time from the available slots list. Do NOT use speculatively.',
  input_schema: {
    type: 'object',
    properties: {
      start_datetime: {
        type: 'string',
        description: 'The appointment start time in ISO 8601 format (e.g. "2026-02-20T14:00:00-05:00"). Must match one of the available slots exactly.',
      },
      duration_minutes: {
        type: 'integer',
        description: 'Meeting duration in minutes. Default 30.',
        default: 30,
      },
    },
    required: ['start_datetime'],
  },
};

async function getCalendarFreeSlots(calendarId, token = null) {
  // Start from tomorrow 10am Toronto time, look 5 days out
  const now = new Date();
  const torontoNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/Toronto' }));

  const start = new Date(torontoNow);
  start.setDate(start.getDate() + 1);
  start.setHours(10, 0, 0, 0);

  const end = new Date(start);
  end.setDate(end.getDate() + 5);
  end.setHours(18, 30, 0, 0);

  const params = new URLSearchParams({
    calendarId,
    startDate: start.getTime().toString(),
    endDate: end.getTime().toString(),
    timezone: 'America/Toronto',
  });

  const response = await fetch(`${GHL_API_BASE}/calendars/free-slots?${params}`, {
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
    },
  });

  if (!response.ok) {
    const err = await response.text();
    console.error('Calendar API error:', response.status, err);
    return null;
  }

  return response.json();
}

function formatSlotsForClaude(slotsData) {
  if (!slotsData) return null;

  console.log('Raw calendar slots:', JSON.stringify(slotsData).slice(0, 600));

  // Handle multiple GHL response formats
  const slotGroups =
    slotsData?.data?.slots ||
    slotsData?.slots ||
    slotsData?.data ||
    slotsData;

  if (!slotGroups || typeof slotGroups !== 'object') return null;

  const slots = [];

  for (const [, times] of Object.entries(slotGroups)) {
    if (!Array.isArray(times)) continue;

    times.slice(0, 3).forEach(slot => {
      const startTime = slot.startTime || slot.start || slot;
      if (!startTime || typeof startTime !== 'string') return;

      const start = new Date(startTime);
      if (isNaN(start.getTime())) return;

      // Double-check: must be weekday, within business hours EST
      const estStr = start.toLocaleString('en-US', { timeZone: 'America/Toronto', hour12: false });
      const estDate = new Date(estStr);
      const dayOfWeek = estDate.getDay();
      const hour = estDate.getHours();
      const minute = estDate.getMinutes();

      if (dayOfWeek === 0 || dayOfWeek === 6) return; // Skip weekends
      if (hour < 10) return;
      if (hour > 18 || (hour === 18 && minute > 0)) return; // After 6:30pm

      const label = start.toLocaleString('en-CA', {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZone: 'America/Toronto',
      });

      slots.push({ label, iso: start.toISOString() });
    });
  }

  if (!slots.length) return null;

  const top = slots.slice(0, 6);
  return (
    'Available meeting slots (Toronto time, Mon-Fri only):\n' +
    top.map((s, i) => `${i + 1}. ${s.label}  [ISO: ${s.iso}]`).join('\n') +
    '\n\nWhen the lead picks one of these, use the book_appointment tool with its ISO time.'
  );
}

async function createAppointment(calendarId, contactId, startIso, durationMinutes = 30, token = null) {
  const start = new Date(startIso);
  const end = new Date(start.getTime() + durationMinutes * 60 * 1000);

  const response = await fetch(`${GHL_API_BASE}/calendars/events/appointments`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      calendarId,
      contactId,
      startTime: start.toISOString(),
      endTime: end.toISOString(),
      title: 'Nurture Consultation',
      status: 'confirmed',
    }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Failed to create appointment: ${response.status} - ${err}`);
  }

  return response.json();
}

// Property-to-team-member mapping for guest message escalation
const PROPERTY_ASSIGNMENTS = {
  '140 simcoe': { name: 'Alondra', slackId: 'U09192YPUSW' },
  '14641 1st': { name: 'Clarita', slackId: 'U08MXLMN6Q0' },
  '14655 1st': { name: 'Clarita', slackId: 'U08MXLMN6Q0' },
  '14639 1st': { name: 'Clarita', slackId: 'U08MXLMN6Q0' },
};

function findAssignedPerson(conversationText) {
  const lower = (conversationText || '').toLowerCase();
  for (const [key, person] of Object.entries(PROPERTY_ASSIGNMENTS)) {
    if (lower.includes(key)) return person;
  }
  // Default fallback
  return { name: 'Angelica', slackId: 'U05VAHNTEVD' };
}

async function notifyGuestEscalation(guestName, property, confidence, guestMessage, draftReply, assignedPerson, contactId) {
  const slackToken = process.env.SLACK_BOT_TOKEN;
  const slackChannel = process.env.SLACK_CHANNEL_ID;
  if (!slackToken || !slackChannel) {
    console.log('Slack not configured, skipping escalation notification');
    return;
  }

  let text = `:warning: *Guest Message Needs Human Response*\n`;
  text += `*Guest:* ${guestName}\n`;
  if (property) text += `*Property:* ${property}\n`;
  text += `*Confidence:* ${confidence}%\n`;
  text += `*Guest said:* "${guestMessage}"\n`;
  if (draftReply) text += `*Draft reply (not sent):* "${draftReply}"\n`;
  text += `*Assigned to:* <@${assignedPerson.slackId}> please respond in Hospitable.`;
  if (contactId) text += `\n<https://app.gohighlevel.com/v2/location/your-location/contacts/${contactId}|View in GHL>`;

  try {
    const response = await fetch('https://slack.com/api/chat.postMessage', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${slackToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        channel: slackChannel,
        text,
        unfurl_links: false,
      }),
    });
    const result = await response.json();
    console.log('Guest escalation Slack notification sent:', result.ok);
  } catch (e) {
    console.error('Failed to send guest escalation Slack notification:', e.message);
  }
}

async function logGuestBotAction(action, guestName, property, confidence, guestMessage, botReply, assignedTo) {
  const slackToken = process.env.SLACK_BOT_TOKEN;
  const slackChannel = process.env.SLACK_CHANNEL_ID;
  if (!slackToken || !slackChannel) return;

  const emoji = action === 'auto-reply' ? ':robot_face:' : ':warning:';
  const confEmoji = confidence >= 90 ? ':large_green_circle:' : confidence >= 70 ? ':large_yellow_circle:' : ':red_circle:';
  const time = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'America/Toronto' });

  let text = `${emoji} *GUEST_BOT_LOG* | ${time} | ${action.toUpperCase()}\n`;
  text += `Guest: ${guestName || 'Unknown'} | Property: ${property || 'Unknown'} | Confidence: ${confEmoji} ${confidence}%\n`;
  text += `Q: "${(guestMessage || '').slice(0, 150)}"\n`;
  text += `A: "${(botReply || '').slice(0, 200)}"`;
  if (action === 'escalated' && assignedTo) text += `\nEscalated to: ${assignedTo}`;

  try {
    await fetch('https://slack.com/api/chat.postMessage', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${slackToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel: slackChannel, text, unfurl_links: false }),
    });
  } catch (e) {
    console.error('Failed to log guest bot action to Slack:', e.message);
  }
}

async function generateFBResponse(contact, conversationHistory, firstName, contactId, account = null) {
  const contactContext = buildContactContext(contact);
  const token = getAccountToken(account);

  console.log('Conversation history being sent to Claude:', conversationHistory);

  // Fetch knowledge base and calendar slots in parallel
  const calendarId = account?.calendarId || process.env.GHL_CALENDAR_ID;
  const [knowledgeBase, rawSlots] = await Promise.all([
    getKnowledgeBase(account),
    calendarId ? getCalendarFreeSlots(calendarId, token).catch(e => { console.error('Could not fetch calendar slots:', e.message); return null; }) : Promise.resolve(null),
  ]);

  let slotsContext = 'No specific slots available right now. Direct to nurturestays.ca/contact to book.';
  if (rawSlots) {
    const formatted = formatSlotsForClaude(rawSlots);
    if (formatted) slotsContext = formatted;
  }

  // Build system prompt from account knowledge base
  let systemPrompt = knowledgeBase || NURTURE_PM_CONTEXT;

  const userPrompt = `## Your Task
${NURTURE_FB_PROMPT}

## Contact Information
${contactContext}

${firstName && firstName !== 'there' ? `The lead's name is "${firstName}".` : 'You do not know their name yet.'}

## Available Meeting Slots
${slotsContext}

## Full Conversation History (read this carefully before replying)
${conversationHistory}

Now write your reply to the lead's most recent message above. You MUST respond in this exact JSON format:
{"confidence": <number 0-100>, "property": "<property address or null>", "reply": "<your message text>", "reason": "<why confidence is below 90, or 'confident' if 90+>"}

Confidence guidelines:
- 90-100: You have the exact answer in the property guide (WiFi, parking, check-in instructions, house rules, etc.)
- 70-89: You have a general answer but are not certain about specifics (e.g. pricing, availability, building policies not in the guide)
- Below 70: The question is about something not covered in your knowledge (maintenance issues, special requests, complaints, refunds, booking changes)

If the lead has clearly confirmed they want to book a specific slot from the list above, also call the book_appointment tool.`;

  // Include tools - always include notify_team, add booking tool when calendar is configured
  const tools = [NOTIFY_TEAM_TOOL];
  if (calendarId) tools.push(BOOK_APPOINTMENT_TOOL);

  const messages = [{ role: 'user', content: userPrompt }];

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 500,
    system: systemPrompt,
    tools,
    messages,
  });

  // Handle tool use (appointment booking and/or team notification)
  const toolUseBlocks = response.content.filter(b => b.type === 'tool_use');
  const textBlock = response.content.find(b => b.type === 'text');

  if (toolUseBlocks.length > 0) {
    const toolResults = [];

    for (const toolUseBlock of toolUseBlocks) {
      if (toolUseBlock.name === 'book_appointment' && calendarId && contactId) {
        const { start_datetime, duration_minutes = 30 } = toolUseBlock.input;
        console.log('Claude wants to book appointment at:', start_datetime);

        let toolResultContent;
        try {
          const appt = await createAppointment(calendarId, contactId, start_datetime, duration_minutes, token);
          console.log('Appointment created:', appt?.id || JSON.stringify(appt).slice(0, 100));
          toolResultContent = JSON.stringify({ success: true, message: 'Appointment booked successfully' });
        } catch (e) {
          console.error('Failed to create appointment:', e.message);
          toolResultContent = JSON.stringify({ success: false, error: e.message });
        }

        toolResults.push({
          type: 'tool_result',
          tool_use_id: toolUseBlock.id,
          content: toolResultContent,
        });

      } else if (toolUseBlock.name === 'notify_team') {
        const { lead_name, lead_phone, summary, urgent } = toolUseBlock.input;
        console.log(`Notifying team: ${lead_name} - ${summary} (urgent: ${urgent})`);

        // Send notifications in parallel
        await Promise.all([
          notifyTeamSlack(lead_name, lead_phone, summary, urgent, contactId),
          notifyTeamSMS(lead_name, lead_phone, summary, urgent, token),
        ]);

        toolResults.push({
          type: 'tool_result',
          tool_use_id: toolUseBlock.id,
          content: JSON.stringify({ success: true, message: 'Team notified via Slack and SMS' }),
        });
      }
    }

    // Ask Claude for the final message now that tools have run
    const confirmResponse = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 300,
      system: systemPrompt,
      tools,
      messages: [
        ...messages,
        { role: 'assistant', content: response.content },
        { role: 'user', content: toolResults },
      ],
    });

    let confirmText = confirmResponse.content.find(b => b.type === 'text')?.text?.trim() || '';
    if ((confirmText.startsWith('"') && confirmText.endsWith('"')) || (confirmText.startsWith("'") && confirmText.endsWith("'"))) {
      confirmText = confirmText.slice(1, -1);
    }
    // Tool use paths (booking, notification) are always high confidence actions
    return { reply: confirmText, confidence: 95, property: null, reason: 'tool use' };
  }

  // No tool use - parse JSON response with confidence
  let rawText = textBlock?.text?.trim() || '';

  // Try to parse as JSON with confidence
  try {
    // Extract JSON from the response (Claude sometimes wraps in markdown code blocks)
    let jsonStr = rawText;
    const jsonMatch = rawText.match(/\{[\s\S]*\}/);
    if (jsonMatch) jsonStr = jsonMatch[0];

    const parsed = JSON.parse(jsonStr);
    const confidence = parsed.confidence || 0;
    const reply = parsed.reply || rawText;
    const property = parsed.property || null;
    const reason = parsed.reason || '';

    console.log(`Response confidence: ${confidence}%, property: ${property}, reason: ${reason}`);

    return { reply, confidence, property, reason };
  } catch (e) {
    // If JSON parsing fails, treat as plain text with high confidence
    console.log('Could not parse confidence JSON, treating as plain text');
    let message = rawText;
    if ((message.startsWith('"') && message.endsWith('"')) || (message.startsWith("'") && message.endsWith("'"))) {
      message = message.slice(1, -1);
    }
    return { reply: message, confidence: 95, property: null, reason: 'plain text fallback' };
  }
}

async function sendFBMessage(contactId, message, token = null) {
  const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      type: 'FB',
      contactId: contactId,
      message: message,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to send FB message: ${response.status} - ${error}`);
  }

  return response.json();
}

// Facebook Messenger webhook endpoint
app.post('/webhook/fb-message', async (req, res) => {
  try {
    console.log('Received FB message webhook:', JSON.stringify(req.body, null, 2));

    // Detect account
    const locationId = req.body.locationId || req.body.location_id || req.query.location || DEFAULT_LOCATION_ID;
    const account = getAccount(locationId);
    const token = getAccountToken(account);
    console.log(`Account: ${account?.name || 'default'} (${locationId})`);

    const contactId = extractContactId(req.body);

    if (!contactId) {
      console.error('No contact ID in FB webhook');
      return res.status(400).json({ error: 'Missing contact_id' });
    }

    const firstName = req.body.first_name || req.body.firstName || 'there';
    console.log(`FB message from contact ${contactId}, name: ${firstName}`);

    // Fetch contact details
    const contact = await getContact(contactId, token);
    console.log('Contact fetched:', contact.contact?.firstName || contact.firstName);

    // Fetch conversation history
    const conversations = await getConversations(contactId, token);
    let conversationHistory = 'No previous messages.';
    let rawMessages = [];

    if (conversations.conversations && conversations.conversations.length > 0) {
      // Try to find the Facebook conversation specifically
      const fbConv = conversations.conversations.find(c =>
        c.type === 'FB' || c.type === 'facebook' || c.type === 'Facebook'
      ) || conversations.conversations[0];

      const messagesResponse = await getMessages(fbConv.id, token);

      // Extract the raw message list
      // GHL returns: { messages: { lastMessageId, nextPage, messages: [...] } }
      if (Array.isArray(messagesResponse)) {
        rawMessages = messagesResponse;
      } else if (messagesResponse?.messages?.messages && Array.isArray(messagesResponse.messages.messages)) {
        rawMessages = messagesResponse.messages.messages;
      } else if (messagesResponse?.messages && Array.isArray(messagesResponse.messages)) {
        rawMessages = messagesResponse.messages;
      } else if (messagesResponse?.data && Array.isArray(messagesResponse.data)) {
        rawMessages = messagesResponse.data;
      }

      conversationHistory = formatConversationHistory(messagesResponse);
    }

    // Check if the last message is outbound (we already replied) - skip if so
    const forceReply = req.query.force === 'true';
    if (!forceReply && rawMessages.length > 0) {
      const sorted = [...rawMessages].sort((a, b) =>
        new Date(b.dateAdded || b.createdAt || 0) - new Date(a.dateAdded || a.createdAt || 0)
      );
      const lastMsg = sorted[0];
      if (lastMsg && lastMsg.direction === 'outbound') {
        console.log('Last message is outbound (already replied). Skipping auto-reply.');
        return res.json({ success: true, skipped: true, reason: 'Already replied' });
      }
    }

    // Generate response with Claude using account context
    const result = await generateFBResponse(contact, conversationHistory, firstName, contactId, account);
    const reply = typeof result === 'string' ? result : result.reply;
    const confidence = typeof result === 'string' ? 95 : (result.confidence || 95);
    const property = typeof result === 'string' ? null : result.property;

    console.log(`Generated FB reply (confidence: ${confidence}%):`, reply);

    // If confidence is below 90%, escalate instead of auto-replying
    if (confidence < 90) {
      const assignedPerson = findAssignedPerson(conversationHistory + ' ' + (property || ''));
      const lastGuestMsg = conversationHistory.split('\n').filter(l => l.includes('[INBOUND]') || l.includes('Guest:')).pop() || 'See conversation history';

      const lastGuestMsgText = lastGuestMsg.replace(/.*\]\s*/, '').trim();
      await notifyGuestEscalation(firstName, property, confidence, lastGuestMsgText, reply, assignedPerson, contactId);
      logGuestBotAction('escalated', firstName, property, confidence, lastGuestMsgText, reply, assignedPerson.name);
      console.log(`Confidence ${confidence}% < 90%. Escalated to ${assignedPerson.name}. No auto-reply sent.`);

      return res.json({ success: true, escalated: true, confidence, assignedTo: assignedPerson.name, draftReply: reply });
    }

    // Send the reply via Facebook
    const sendResult = await sendFBMessage(contactId, reply, token);
    const lastInbound = conversationHistory.split('\n').filter(l => l.includes('[INBOUND]') || l.includes('Guest:')).pop() || '';
    logGuestBotAction('auto-reply', firstName, property, confidence, lastInbound.replace(/.*\]\s*/, '').trim(), reply, null);
    console.log('FB message sent successfully');

    res.json({
      success: true,
      contactId,
      confidence,
      messageSent: reply,
      sendResult,
    });

  } catch (error) {
    console.error('FB message webhook error:', error);
    res.status(500).json({ error: error.message });
  }
});

// ============================================
// NURTURE PM - GENERIC MESSAGE WEBHOOK (SMS, Chat, Email, etc.)
// ============================================
// Use this for any Nurture PM pipeline that isn't Facebook Messenger.
// GHL workflow: trigger on inbound message → webhook to /webhook/nurture-pm?type=SMS
// Supports: SMS, Email, Live_Chat, WhatsApp, GMB, IG, Custom

async function sendGHLMessage(contactId, message, messageType = 'SMS', token = null) {
  const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token || process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      type: messageType,
      contactId: contactId,
      message: message,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to send ${messageType} message: ${response.status} - ${error}`);
  }

  return response.json();
}

app.post('/webhook/nurture-pm', async (req, res) => {
  try {
    console.log('Received Nurture PM webhook:', JSON.stringify(req.body, null, 2));

    const contactId = extractContactId(req.body);
    // Message type from query param, body, or default to SMS
    const messageType = req.query.type || req.body.type || req.body.messageType || 'SMS';

    // Multi-account detection
    const locationId = req.body.locationId || req.body.location_id || req.query.location || DEFAULT_LOCATION_ID;
    const account = getAccount(locationId);
    const token = getAccountToken(account);
    console.log(`Account: ${account?.name || 'default'}, Location: ${locationId}`);

    if (!contactId) {
      console.error('No contact ID in Nurture PM webhook');
      return res.status(400).json({ error: 'Missing contact_id' });
    }

    const firstName = req.body.first_name || req.body.firstName || 'there';
    console.log(`Nurture PM ${messageType} message from contact ${contactId}, name: ${firstName}`);

    // Fetch contact details
    const contact = await getContact(contactId, token);
    console.log('Contact fetched:', contact.contact?.firstName || contact.firstName);

    // Fetch conversation history
    const conversations = await getConversations(contactId, token);
    let conversationHistory = 'No previous messages.';
    let rawMessages = [];

    if (conversations.conversations && conversations.conversations.length > 0) {
      // Try to find the matching conversation type, fallback to most recent
      const matchingConv = conversations.conversations.find(c =>
        c.type && c.type.toUpperCase() === messageType.toUpperCase()
      ) || conversations.conversations[0];

      const messagesResponse = await getMessages(matchingConv.id, token);

      if (Array.isArray(messagesResponse)) {
        rawMessages = messagesResponse;
      } else if (messagesResponse?.messages?.messages && Array.isArray(messagesResponse.messages.messages)) {
        rawMessages = messagesResponse.messages.messages;
      } else if (messagesResponse?.messages && Array.isArray(messagesResponse.messages)) {
        rawMessages = messagesResponse.messages;
      } else if (messagesResponse?.data && Array.isArray(messagesResponse.data)) {
        rawMessages = messagesResponse.data;
      }

      conversationHistory = formatConversationHistory(messagesResponse);
    }

    // Check if the last message is outbound (already replied) - skip unless forced
    const forceReply = req.query.force === 'true';
    if (!forceReply && rawMessages.length > 0) {
      const sorted = [...rawMessages].sort((a, b) =>
        new Date(b.dateAdded || b.createdAt || 0) - new Date(a.dateAdded || a.createdAt || 0)
      );
      const lastMsg = sorted[0];
      if (lastMsg && lastMsg.direction === 'outbound') {
        console.log('Last message is outbound (already replied). Skipping auto-reply.');
        return res.json({ success: true, skipped: true, reason: 'Already replied' });
      }
    }

    // Generate response using account-specific context + knowledge base + tools
    const result = await generateFBResponse(contact, conversationHistory, firstName, contactId, account);

    // Handle both old string returns and new {reply, confidence} returns
    const reply = typeof result === 'string' ? result : result.reply;
    const confidence = typeof result === 'string' ? 95 : (result.confidence || 95);
    const property = typeof result === 'string' ? null : result.property;
    const reason = typeof result === 'string' ? '' : (result.reason || '');

    console.log(`Generated ${messageType} reply (confidence: ${confidence}%):`, reply);

    // If confidence is below 90%, escalate to assigned team member instead of auto-replying
    if (confidence < 90) {
      const assignedPerson = findAssignedPerson(conversationHistory + ' ' + (property || ''));

      // Extract the guest's last message from conversation history
      const lastGuestMsg = conversationHistory.split('\n').filter(l => l.includes('[INBOUND]') || l.includes('Guest:')).pop() || 'See conversation history';

      await notifyGuestEscalation(
        firstName,
        property,
        confidence,
        lastGuestMsg.replace(/.*\]\s*/, '').trim(),
        reply,
        assignedPerson,
        contactId
      );

      console.log(`Confidence ${confidence}% < 90%. Escalated to ${assignedPerson.name} via Slack. No auto-reply sent.`);

      // Log the escalation
      const lastGuestMsgText = lastGuestMsg.replace(/.*\]\s*/, '').trim();
      logGuestBotAction('escalated', firstName, property, confidence, lastGuestMsgText, reply, assignedPerson.name);

      return res.json({
        success: true,
        contactId,
        messageType,
        escalated: true,
        confidence,
        assignedTo: assignedPerson.name,
        reason,
        draftReply: reply,
      });
    }

    // Confidence >= 90%, send the reply
    const sendResult = await sendGHLMessage(contactId, reply, messageType, token);
    console.log(`${messageType} message sent successfully (confidence: ${confidence}%)`);

    // Log the auto-reply
    const lastInbound = conversationHistory.split('\n').filter(l => l.includes('[INBOUND]') || l.includes('Guest:')).pop() || '';
    logGuestBotAction('auto-reply', firstName, property, confidence, lastInbound.replace(/.*\]\s*/, '').trim(), reply, null);

    res.json({
      success: true,
      contactId,
      messageType,
      confidence,
      messageSent: reply,
      sendResult,
    });

  } catch (error) {
    console.error('Nurture PM webhook error:', error);
    res.status(500).json({ error: error.message });
  }
});

// ============================================
// INTERACTIVE PRICING ACTIONS PAGE
// ============================================
const crypto = require('crypto');
const PRICING_SECRET = process.env.PRICING_ACTION_SECRET || '';
const HOSPITABLE_TOKEN = process.env.HOSPITABLE_API_TOKEN || '';
const HOSPITABLE_API = 'https://public.api.hospitable.com/v2';

// Google Sheets-backed storage for pricing actions
const PRICING_SHEET_ID = '1cnp7qHzfJ3mScJVpWUUInGWqK_0ZEAtHJFXszoJf-MI';
const SHEETS_API_KEY = process.env.GOOGLE_SHEETS_API_KEY || '';

async function fetchActionsFromSheets() {
  // Use Google Sheets API v4 with API key (read-only, sheet must be shared)
  // Or use OAuth — but simpler: the MCP server uses service account credentials
  // For Vercel, use the public Google Sheets API with the sheet shared to "anyone with link"
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${PRICING_SHEET_ID}/values/Pending%20Actions!A1:K200?key=${SHEETS_API_KEY}`;

  const resp = await fetch(url);
  if (!resp.ok) {
    // Fallback: try fetching as CSV (works for public sheets without API key)
    const csvUrl = `https://docs.google.com/spreadsheets/d/${PRICING_SHEET_ID}/gviz/tq?tqx=out:json&sheet=Pending%20Actions`;
    const csvResp = await fetch(csvUrl);
    if (!csvResp.ok) throw new Error(`Sheets API error: ${resp.status}`);

    const text = await csvResp.text();
    // Google returns JSONP-like format: google.visualization.Query.setResponse({...})
    const jsonStr = text.match(/setResponse\(([\s\S]*)\);?$/)?.[1];
    if (!jsonStr) throw new Error('Could not parse Sheets response');

    const data = JSON.parse(jsonStr);
    const cols = data.table.cols.map(c => c.label);
    const rows = data.table.rows.map(r => r.c.map(cell => cell?.v ?? ''));
    return { header: cols.length ? cols : rows[0], rows: rows.slice(cols.length ? 0 : 1) };
  }

  const data = await resp.json();
  const allRows = data.values || [];
  if (allRows.length < 2) return { header: [], rows: [] };
  return { header: allRows[0], rows: allRows.slice(1) };
}

function sheetsRowsToActions(header, rows) {
  if (!rows.length) return null;

  const reportId = rows[0]?.[0] || '';
  const reportDate = rows[0]?.[1] || 'Today';
  const expires = rows[0]?.[2] || '';

  const items = rows.map(row => {
    const datesJson = row[10] || '[]';
    let dates = [];
    try { dates = JSON.parse(datesJson); } catch (e) { /* ignore */ }

    return {
      group: row[4] || '',
      property: row[5] || '',
      property_id: row[6] || '',
      city: row[7] || '',
      description: row[8] || '',
      recommended: row[9] === 'TRUE',
      dates,
    };
  });

  return { reportId, reportDate, expires, items };
}

// Serve the interactive pricing actions page by ID
app.get('/pricing-actions/:id', async (req, res) => {
  let actions;
  try {
    const { header, rows } = await fetchActionsFromSheets();
    actions = sheetsRowsToActions(header, rows);
  } catch (e) {
    console.error('Failed to fetch actions from Sheets:', e.message);
    return res.status(500).send(`
      <html><body style="font-family:Arial;padding:40px;text-align:center;">
        <h2>Error Loading Actions</h2>
        <p>Could not read pricing actions from Google Sheets: ${e.message}</p>
      </body></html>
    `);
  }

  if (!actions || !actions.items.length) {
    return res.status(404).send(`
      <html><body style="font-family:Arial;padding:40px;text-align:center;">
        <h2>No Actions Found</h2>
        <p>The Pending Actions sheet is empty. Run the daily pricing report to generate actions.</p>
      </body></html>
    `);
  }

  // Check if report ID matches (optional, for safety)
  if (actions.reportId && actions.reportId !== req.params.id) {
    console.log(`Report ID mismatch: URL has ${req.params.id}, sheet has ${actions.reportId}. Serving anyway.`);
  }

  const reportDate = actions.reportDate;
  const items = actions.items;

  // Group actions by type
  const groups = {};
  for (const item of items) {
    const group = item.group || 'Other';
    if (!groups[group]) groups[group] = [];
    groups[group].push(item);
  }

  // Build the HTML page
  let actionsHtml = '';
  let idx = 0;
  for (const [groupName, groupItems] of Object.entries(groups)) {
    const groupColors = {
      'Price Drops': '#c0392b',
      'Price Increases': '#27ae60',
      'Orphan Night Premiums': '#8e44ad',
      'Adjacent Discounts': '#2980b9',
    };
    const color = groupColors[groupName] || '#333';

    actionsHtml += `<h3 style="color:${color};margin-top:24px;margin-bottom:12px;">${groupName}</h3>`;

    for (const item of groupItems) {
      const checked = item.recommended ? 'checked' : '';
      actionsHtml += `
        <label style="display:flex;align-items:flex-start;gap:12px;padding:12px 16px;margin:6px 0;background:#f8f8f8;border-radius:6px;border-left:4px solid ${color};cursor:pointer;" class="action-row">
          <input type="checkbox" name="action" value="${idx}" ${checked}
            style="margin-top:3px;width:18px;height:18px;cursor:pointer;">
          <div style="flex:1;">
            <strong>${item.property}</strong> (${item.city})<br>
            <span style="font-size:14px;color:#555;">${item.description}</span><br>
            <span style="font-size:13px;">
              ${item.dates ? item.dates.map(d => `<span style="display:inline-block;background:white;border:1px solid #ddd;border-radius:4px;padding:2px 8px;margin:2px;font-size:12px;">${d.date}: $${(d.current_price/100).toFixed(0)} → $${(d.new_price/100).toFixed(0)}</span>`).join('') : ''}
            </span>
          </div>
        </label>`;
      idx++;
    }
  }

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nurture Pricing Actions | ${reportDate}</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: 'Helvetica Neue', Arial, sans-serif; background: #f0f0f0; margin: 0; padding: 16px; color: #333; }
    .container { max-width: 800px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
    .header { background: #759b8f; color: white; padding: 24px 30px; }
    .header h1 { margin: 0; font-size: 22px; }
    .header p { margin: 4px 0 0; opacity: 0.9; font-size: 14px; }
    .content { padding: 24px 30px; }
    .action-row:hover { background: #f0f0f0 !important; }
    .toolbar { position: sticky; bottom: 0; background: white; border-top: 2px solid #759b8f; padding: 16px 30px; display: flex; justify-content: space-between; align-items: center; }
    .btn { padding: 12px 32px; border-radius: 6px; border: none; font-size: 16px; font-weight: bold; cursor: pointer; }
    .btn-primary { background: #759b8f; color: white; }
    .btn-primary:hover { background: #5a7d73; }
    .btn-primary:disabled { background: #ccc; cursor: not-allowed; }
    .select-btns { display: flex; gap: 8px; }
    .select-btns button { background: none; border: 1px solid #ddd; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 13px; }
    .select-btns button:hover { background: #f0f0f0; }
    .status { display: none; padding: 16px 30px; text-align: center; font-size: 16px; }
    .status.success { display: block; background: #d5f5e3; color: #1e8449; }
    .status.error { display: block; background: #fadbd8; color: #c0392b; }
    .status.loading { display: block; background: #fef9e7; color: #7d6608; }
    .results { padding: 0 30px 20px; }
    .result-item { padding: 6px 0; font-size: 14px; border-bottom: 1px solid #f0f0f0; }
    .result-ok { color: #1e8449; }
    .result-fail { color: #c0392b; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Pricing Actions</h1>
      <p>${reportDate} | Select adjustments to apply</p>
    </div>

    <form id="actionsForm">
      <div class="content">
        ${actionsHtml || '<p>No actions suggested today.</p>'}
      </div>

      <div class="toolbar">
        <div class="select-btns">
          <button type="button" onclick="toggleAll(true)">Select All</button>
          <button type="button" onclick="toggleAll(false)">Deselect All</button>
          <span id="countLabel" style="font-size:13px;color:#666;margin-left:8px;">0 selected</span>
        </div>
        <button type="submit" class="btn btn-primary" id="submitBtn">Apply Selected</button>
      </div>
    </form>

    <div id="statusBar" class="status"></div>
    <div id="results" class="results"></div>
  </div>

  <script>
    const form = document.getElementById('actionsForm');
    const statusBar = document.getElementById('statusBar');
    const resultsDiv = document.getElementById('results');
    const submitBtn = document.getElementById('submitBtn');
    const countLabel = document.getElementById('countLabel');

    function updateCount() {
      const checked = document.querySelectorAll('input[name="action"]:checked').length;
      countLabel.textContent = checked + ' selected';
    }

    document.querySelectorAll('input[name="action"]').forEach(cb => {
      cb.addEventListener('change', updateCount);
    });
    updateCount();

    function toggleAll(state) {
      document.querySelectorAll('input[name="action"]').forEach(cb => cb.checked = state);
      updateCount();
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const selected = Array.from(document.querySelectorAll('input[name="action"]:checked')).map(cb => parseInt(cb.value));

      if (!selected.length) {
        statusBar.className = 'status error';
        statusBar.textContent = 'Please select at least one action.';
        return;
      }

      if (!confirm('Apply ' + selected.length + ' pricing change(s)? This will update rates in Hospitable immediately.')) return;

      statusBar.className = 'status loading';
      statusBar.textContent = 'Applying ' + selected.length + ' change(s)...';
      submitBtn.disabled = true;
      resultsDiv.innerHTML = '';

      try {
        const resp = await fetch('/pricing-actions/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            reportId: '${req.params.id}',
            selected: selected,
          }),
        });

        const result = await resp.json();

        if (result.success) {
          statusBar.className = 'status success';
          statusBar.textContent = result.applied + ' of ' + selected.length + ' changes applied successfully.';
        } else {
          statusBar.className = 'status error';
          statusBar.textContent = 'Error: ' + (result.error || 'Unknown error');
        }

        if (result.results) {
          resultsDiv.innerHTML = '<h4 style="margin:16px 0 8px;">Results:</h4>' +
            result.results.map(r =>
              '<div class="result-item ' + (r.ok ? 'result-ok' : 'result-fail') + '">' +
              (r.ok ? '✅' : '❌') + ' ' + r.property + ': ' + r.message + '</div>'
            ).join('');
        }

      } catch (err) {
        statusBar.className = 'status error';
        statusBar.textContent = 'Network error: ' + err.message;
      }

      submitBtn.disabled = false;
    });
  </script>
</body>
</html>`;

  res.setHeader('Content-Type', 'text/html');
  res.send(html);
});

// Execute selected pricing actions
app.post('/pricing-actions/execute', async (req, res) => {
  try {
    const { reportId, selected } = req.body;

    if (!reportId || !selected) {
      return res.status(400).json({ success: false, error: 'Missing required fields' });
    }

    // Read actions from Google Sheets
    let actions;
    try {
      const { header, rows } = await fetchActionsFromSheets();
      actions = sheetsRowsToActions(header, rows);
    } catch (e) {
      return res.status(500).json({ success: false, error: `Could not read actions from Sheets: ${e.message}` });
    }

    if (!actions || !actions.items.length) {
      return res.status(404).json({ success: false, error: 'No actions found in Sheets. Re-run the daily pricing report.' });
    }

    const items = actions.items || [];
    const results = [];
    let applied = 0;

    for (const idx of selected) {
      const item = items[idx];
      if (!item || !item.property_id || !item.dates) {
        results.push({ property: item?.property || 'Unknown', ok: false, message: 'Invalid action data' });
        continue;
      }

      // Build calendar update payload (max 60 dates per request)
      const calDates = item.dates.map(d => ({
        date: d.date,
        price: { amount: d.new_price },
      }));

      try {
        const resp = await fetch(`${HOSPITABLE_API}/properties/${item.property_id}/calendar`, {
          method: 'PUT',
          headers: {
            'Authorization': `Bearer ${HOSPITABLE_TOKEN}`,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: JSON.stringify({ dates: calDates }),
        });

        if (resp.ok) {
          applied++;
          const datesSummary = calDates.map(d => `${d.date}: $${(d.price.amount/100).toFixed(0)}`).join(', ');
          results.push({ property: item.property, ok: true, message: `Updated ${calDates.length} date(s): ${datesSummary}` });
        } else {
          const errText = await resp.text();
          results.push({ property: item.property, ok: false, message: `API error ${resp.status}: ${errText.slice(0, 200)}` });
        }
      } catch (e) {
        results.push({ property: item.property, ok: false, message: `Network error: ${e.message}` });
      }

      // Small delay between API calls
      await new Promise(r => setTimeout(r, 300));
    }

    res.json({ success: true, applied, total: selected.length, results });

  } catch (error) {
    console.error('Pricing action execute error:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// ============================================
// START SERVER
// ============================================

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`GHL Claude Server running on port ${PORT}`);
  console.log('Endpoints:');
  console.log(`  POST /webhook/followup?step=1-7 - Follow-up sequence (Nurtre lead gen)`);
  console.log(`  POST /webhook/reply - Handle inbound replies (Nurtre lead gen)`);
  console.log(`  POST /webhook/fb-message - Facebook Messenger auto-reply (Nurture PM)`);
  console.log(`  POST /webhook/nurture-pm?type=SMS|Email|Live_Chat|WhatsApp - Generic Nurture PM auto-reply`);
});

// Export for Vercel
module.exports = app;
