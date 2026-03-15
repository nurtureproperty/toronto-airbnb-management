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
// DYNAMIC KNOWLEDGE BASE (fetched from GitHub, cached 24h)
// ============================================
const KNOWLEDGE_BASE_URL = 'https://raw.githubusercontent.com/nurtureproperty/toronto-airbnb-management/master/ghl-claude-server/bot-knowledge.md';
let cachedKnowledge = null;
let knowledgeCachedAt = 0;
const KNOWLEDGE_CACHE_TTL = 24 * 60 * 60 * 1000; // 24 hours

async function getKnowledgeBase() {
  const now = Date.now();
  if (cachedKnowledge && (now - knowledgeCachedAt) < KNOWLEDGE_CACHE_TTL) {
    return cachedKnowledge;
  }

  try {
    console.log('Fetching fresh knowledge base from GitHub...');
    const response = await fetch(KNOWLEDGE_BASE_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();

    // Truncate to ~80K chars to stay within Claude context limits
    cachedKnowledge = text.length > 80000 ? text.slice(0, 80000) + '\n\n[Knowledge base truncated]' : text;
    knowledgeCachedAt = now;
    console.log(`Knowledge base loaded: ${(cachedKnowledge.length / 1024).toFixed(1)} KB`);
    return cachedKnowledge;
  } catch (e) {
    console.error('Failed to fetch knowledge base:', e.message);
    // Return cached version if available, even if stale
    if (cachedKnowledge) return cachedKnowledge;
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

async function getContact(contactId) {
  const response = await fetch(`${GHL_API_BASE}/contacts/${contactId}`, {
    headers: {
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch contact: ${response.status}`);
  }

  return response.json();
}

async function getConversations(contactId) {
  const response = await fetch(`${GHL_API_BASE}/conversations/search?contactId=${contactId}`, {
    headers: {
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch conversations: ${response.status}`);
  }

  return response.json();
}

async function getMessages(conversationId) {
  const response = await fetch(`${GHL_API_BASE}/conversations/${conversationId}/messages`, {
    headers: {
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
      'Version': '2021-07-28',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch messages: ${response.status}`);
  }

  return response.json();
}

async function sendSMS(contactId, message) {
  const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
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

async function generateResponse(contact, conversationHistory, step, firstName = 'there', contactId = null) {
  // Build context from contact data
  const contactContext = buildContactContext(contact);

  // Get step-specific prompt
  const stepPrompt = STEP_PROMPTS[step] || STEP_PROMPTS.reply;

  // Fetch knowledge base and calendar slots in parallel
  const calendarId = process.env.GHL_CALENDAR_ID;
  const [knowledgeBase, rawSlots] = await Promise.all([
    getKnowledgeBase(),
    calendarId ? getCalendarFreeSlots(calendarId).catch(e => { console.error('Could not fetch calendar slots:', e.message); return null; }) : Promise.resolve(null),
  ]);

  let slotsContext = 'No specific slots available right now. Direct to nurturestays.ca/contact to book.';
  if (rawSlots) {
    const formatted = formatSlotsForClaude(rawSlots);
    if (formatted) slotsContext = formatted;
  }

  // Build system prompt: Nurture PM context + dynamic knowledge
  let systemPrompt = NURTURE_PM_CONTEXT;
  if (knowledgeBase) {
    systemPrompt += '\n\n## EXTENDED KNOWLEDGE BASE (use this to answer detailed questions about bylaws, blog articles, services, etc.)\n\n' + knowledgeBase;
  }

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
          const appt = await createAppointment(calendarId, contactId, start_datetime, duration_minutes);
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
          notifyTeamSMS(lead_name, lead_phone, summary, urgent),
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
    const contact = await getContact(contactId);
    console.log('Contact fetched:', contact.contact?.firstName);

    // Fetch conversation history
    const conversations = await getConversations(contactId);
    let conversationHistory = 'No previous messages.';

    if (conversations.conversations && conversations.conversations.length > 0) {
      const conversationId = conversations.conversations[0].id;
      const messages = await getMessages(conversationId);
      conversationHistory = formatConversationHistory(messages);
    }

    // Generate personalized response with Claude
    const generatedMessage = await generateResponse(contact, conversationHistory, step, firstName, contactId);
    console.log('Generated message:', generatedMessage);

    // Send the SMS via GHL
    const sendResult = await sendSMS(contactId, generatedMessage);
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

    const contactId = extractContactId(req.body);

    if (!contactId) {
      return res.status(400).json({ error: 'Missing contact_id' });
    }

    // Extract first name directly from webhook body
    const firstName = req.body.first_name || req.body.firstName || 'there';
    console.log('First name from webhook:', firstName);

    // Fetch contact and conversation
    const contact = await getContact(contactId);
    const conversations = await getConversations(contactId);

    let conversationHistory = 'No previous messages.';
    if (conversations.conversations && conversations.conversations.length > 0) {
      const conversationId = conversations.conversations[0].id;
      const messages = await getMessages(conversationId);
      conversationHistory = formatConversationHistory(messages);
    }

    // Generate reply using 'reply' step
    const generatedMessage = await generateResponse(contact, conversationHistory, 'reply', firstName, contactId);
    console.log('Generated reply:', generatedMessage);

    // Send the SMS
    const sendResult = await sendSMS(contactId, generatedMessage);

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
7. NEVER promise to personally call, visit, or take actions you cannot do. You are a text assistant. If they ask for a call, offer to book one using the available slots, or direct them to nurturestays.ca/contact
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

async function notifyTeamSMS(leadName, leadPhone, summary, urgent) {
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
        'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
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

async function getCalendarFreeSlots(calendarId) {
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
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
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

async function createAppointment(calendarId, contactId, startIso, durationMinutes = 30) {
  const start = new Date(startIso);
  const end = new Date(start.getTime() + durationMinutes * 60 * 1000);

  const response = await fetch(`${GHL_API_BASE}/calendars/events/appointments`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
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

async function generateFBResponse(contact, conversationHistory, firstName, contactId) {
  const contactContext = buildContactContext(contact);

  console.log('Conversation history being sent to Claude:', conversationHistory);

  // Fetch knowledge base and calendar slots in parallel
  const calendarId = process.env.GHL_CALENDAR_ID;
  const [knowledgeBase, rawSlots] = await Promise.all([
    getKnowledgeBase(),
    calendarId ? getCalendarFreeSlots(calendarId).catch(e => { console.error('Could not fetch calendar slots:', e.message); return null; }) : Promise.resolve(null),
  ]);

  let slotsContext = 'No specific slots available right now. Direct to nurturestays.ca/contact to book.';
  if (rawSlots) {
    const formatted = formatSlotsForClaude(rawSlots);
    if (formatted) slotsContext = formatted;
  }

  // Build system prompt: hardcoded rules + dynamic knowledge
  let systemPrompt = NURTURE_PM_CONTEXT;
  if (knowledgeBase) {
    systemPrompt += '\n\n## EXTENDED KNOWLEDGE BASE (use this to answer detailed questions about bylaws, blog articles, services, etc.)\n\n' + knowledgeBase;
  }

  const userPrompt = `## Your Task
${NURTURE_FB_PROMPT}

## Contact Information
${contactContext}

${firstName && firstName !== 'there' ? `The lead's name is "${firstName}".` : 'You do not know their name yet.'}

## Available Meeting Slots
${slotsContext}

## Full Conversation History (read this carefully before replying)
${conversationHistory}

Now write your reply to the lead's most recent message above. Reply ONLY with the message text, nothing else.
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
          const appt = await createAppointment(calendarId, contactId, start_datetime, duration_minutes);
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
          notifyTeamSMS(lead_name, lead_phone, summary, urgent),
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
    return confirmText;
  }

  // No tool use - return plain text reply
  let message = textBlock?.text?.trim() || '';

  // Remove any quotes Claude might wrap the message in
  if ((message.startsWith('"') && message.endsWith('"')) || (message.startsWith("'") && message.endsWith("'"))) {
    message = message.slice(1, -1);
  }

  return message;
}

async function sendFBMessage(contactId, message) {
  const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
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

    const contactId = extractContactId(req.body);

    if (!contactId) {
      console.error('No contact ID in FB webhook');
      return res.status(400).json({ error: 'Missing contact_id' });
    }

    const firstName = req.body.first_name || req.body.firstName || 'there';
    console.log(`FB message from contact ${contactId}, name: ${firstName}`);

    // Fetch contact details
    const contact = await getContact(contactId);
    console.log('Contact fetched:', contact.contact?.firstName || contact.firstName);

    // Fetch conversation history
    const conversations = await getConversations(contactId);
    let conversationHistory = 'No previous messages.';
    let rawMessages = [];

    if (conversations.conversations && conversations.conversations.length > 0) {
      // Try to find the Facebook conversation specifically
      const fbConv = conversations.conversations.find(c =>
        c.type === 'FB' || c.type === 'facebook' || c.type === 'Facebook'
      ) || conversations.conversations[0];

      const messagesResponse = await getMessages(fbConv.id);

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

    // Generate response with Claude using Nurture PM context (pass contactId for calendar booking)
    const generatedMessage = await generateFBResponse(contact, conversationHistory, firstName, contactId);
    console.log('Generated FB reply:', generatedMessage);

    // Send the reply via Facebook
    const sendResult = await sendFBMessage(contactId, generatedMessage);
    console.log('FB message sent successfully');

    res.json({
      success: true,
      contactId,
      messageSent: generatedMessage,
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

async function sendGHLMessage(contactId, message, messageType = 'SMS') {
  const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.GHL_API_TOKEN}`,
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

    if (!contactId) {
      console.error('No contact ID in Nurture PM webhook');
      return res.status(400).json({ error: 'Missing contact_id' });
    }

    const firstName = req.body.first_name || req.body.firstName || 'there';
    console.log(`Nurture PM ${messageType} message from contact ${contactId}, name: ${firstName}`);

    // Fetch contact details
    const contact = await getContact(contactId);
    console.log('Contact fetched:', contact.contact?.firstName || contact.firstName);

    // Fetch conversation history
    const conversations = await getConversations(contactId);
    let conversationHistory = 'No previous messages.';
    let rawMessages = [];

    if (conversations.conversations && conversations.conversations.length > 0) {
      // Try to find the matching conversation type, fallback to most recent
      const matchingConv = conversations.conversations.find(c =>
        c.type && c.type.toUpperCase() === messageType.toUpperCase()
      ) || conversations.conversations[0];

      const messagesResponse = await getMessages(matchingConv.id);

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

    // Generate response using same Nurture PM context + knowledge base + tools
    const generatedMessage = await generateFBResponse(contact, conversationHistory, firstName, contactId);
    console.log(`Generated ${messageType} reply:`, generatedMessage);

    // Send the reply via the appropriate channel
    const sendResult = await sendGHLMessage(contactId, generatedMessage, messageType);
    console.log(`${messageType} message sent successfully`);

    res.json({
      success: true,
      contactId,
      messageType,
      messageSent: generatedMessage,
      sendResult,
    });

  } catch (error) {
    console.error('Nurture PM webhook error:', error);
    res.status(500).json({ error: error.message });
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
