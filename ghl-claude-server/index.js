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
// STEP-SPECIFIC PROMPTS
// ============================================
const STEP_PROMPTS = {
  1: `This is the FIRST follow-up message.

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

FIRST, CHECK IF A CLIPIO VIDEO (video audit) WAS SENT:
- Look for "Clipio Link" in the contact's Relevant Details section
- If "Clipio Link" is NOT listed, is empty "", or says "undefined" → NO VIDEO WAS SENT
- ONLY if "Clipio Link" contains an actual URL (like "https://video.nurtre.io/...") → A video WAS sent

**CRITICAL: If you don't see a Clipio Link URL, DO NOT mention any video you "sent." You didn't send one!**

IF NO VIDEO AUDIT WAS SENT (Clipio Link is missing/empty/undefined):
- OFFER them a FREE VIDEO AUDIT of their YouTube channel
- Reference their specific YouTube VIDEO using "Custom Video Title and Comment" field or "Channel Video Page"
- Compliment something specific about their YouTube video (not just "your content," be specific: "your YouTube video about [topic]")
- Say something like "I'd love to put together a quick video audit of your YouTube channel, totally free, no strings attached"

IF VIDEO AUDIT WAS SENT (Clipio Link exists):
- They already received the video audit. NOW we want to get them on a FREE CONSULTATION
- The consultation is where we teach them how to generate PAYING CLIENTS from their YouTube channel
- Be clear about the video: "the video audit I sent" or "my video reviewing your content," NOT "video about your listing"
- Check "Loom Watched Follow Up" field to see if they watched
- If NOT watched → Ask if they watched, offer to resend OR offer the free consultation
- If watched → Ask what they thought, then offer the FREE CONSULTATION to show them how to turn their YouTube into paying clients
- The pitch: "Would you be open to a quick call where I show you how to turn your YouTube content into paying clients?"

IMPORTANT: WHAT WE DO AND DON'T DO:
- We do NOT create videos for them
- We do NOT help with their listing videos or YouTube production
- We HELP them turn their EXISTING YouTube VIDEOS into LEADS and PAYING CLIENTS
- The consultation is about LEAD GENERATION from their YouTube videos, not video creation
- Use "paying clients", "leads", "GCI," NOT "grow your channel", "create content", or "YouTube presence"
- Always say "YouTube video" or "YouTube videos," NOT just "content"

CRITICAL: READ THE CONVERSATION HISTORY AND CHECK TIMING:
- Look at what messages WE already sent (marked as "US:") and their DATES
- DO NOT repeat the same angle or wording from previous messages
- CHECK THE DATES: If the last message was sent weeks or months ago, DO NOT say "just sent" or imply it was recent
- If it's been a while since contact, acknowledge the time gap naturally: "Been a while!" or "Circling back..." or "Remember that video audit I sent you a while back?"
- NEVER say "just sent you a video" if the dates show it was sent long ago

Guidelines:
- Keep it short (2-3 sentences max)
- BE FUNNY AND WARM. Add a light joke, witty comment, or playful observation
- Reference their specific YouTube video or channel
- End with a soft question. Don't be pushy
- Remember: FIRST WORD must be "Hey [their name],"
- Write like you're texting a friend: casual, warm, with personality`,

  2: `This is the SECOND follow-up message (Day 3).

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

FIRST, CHECK IF A CLIPIO VIDEO (video audit) WAS SENT:
- Look for "Clipio Link" in the contact's Relevant Details
- If "Clipio Link" is NOT listed, empty, or undefined → NO VIDEO WAS SENT
- ONLY if it contains an actual URL → A video WAS sent

**CRITICAL: If you don't see a Clipio Link URL, DO NOT mention any video. You didn't send one!**

IF NO VIDEO AUDIT WAS SENT (Clipio Link missing/empty):
- Re-offer the FREE VIDEO AUDIT with a different angle
- Make it sound valuable. Mention you'll share specific tips for their YouTube channel
- Reference their YouTube video from "Custom Video Title and Comment" field

IF VIDEO AUDIT WAS SENT (Clipio Link exists):
- They already received the video audit. NOW we want to get them on a FREE CONSULTATION
- The consultation is where we teach them how to generate PAYING CLIENTS from their YouTube
- Check "Loom Watched Follow Up" field
- If NOT watched → Offer to resend OR offer the free consultation
- If watched → Offer the FREE CONSULTATION to show them how to turn YouTube into paying clients
- Example: "Would love to show you how to turn your content into actual leads, free 15 min call?"

IMPORTANT: WE DO NOT CREATE VIDEOS:
- We do NOT create videos for them
- We HELP them turn their EXISTING YouTube VIDEOS into LEADS and PAYING CLIENTS
- Never say "content." Say "YouTube videos" (e.g., "help you get leads from your YouTube videos")

CRITICAL: READ THE CONVERSATION HISTORY AND CHECK TIMING:
- Look at ALL previous messages marked as "US:" as these are what we already sent
- CHECK THE DATES: If it's been weeks/months since last contact, acknowledge the time gap
- DO NOT say "just sent" if the video was sent long ago. Say "sent you a while back" or "remember that video?"
- DO NOT repeat the same phrases, questions, or angles
- MUST use a COMPLETELY DIFFERENT approach than message 1

Guidelines:
- Keep it short (2-3 sentences max)
- BE FUNNY. Use self-aware humor like "I know, I'm back again..." or "Promise I'm not stalking you"
- Reference their content if relevant
- MUST use a different angle than previous messages
- Stay helpful and curious, not salesy, but make them smile
- Remember: FIRST WORD must be "Hey [their name],"
- Write like a friend with a good sense of humor`,

  3: `This is the THIRD follow-up message (Day 7).

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

FIRST, CHECK IF A CLIPIO VIDEO (video audit) WAS SENT:
- Look for "Clipio Link" in the contact's Relevant Details
- If "Clipio Link" is NOT listed, empty, or undefined → NO VIDEO WAS SENT
- ONLY if it contains an actual URL → A video WAS sent

**CRITICAL: If you don't see a Clipio Link URL, DO NOT mention any video. You didn't send one!**

IF NO VIDEO AUDIT WAS SENT (Clipio Link missing/empty):
- Last offer for the free video audit
- Make it low pressure but valuable sounding
- Reference their YouTube video

IF VIDEO AUDIT WAS SENT (Clipio Link exists):
- They already received the video audit. NOW we want to get them on a FREE CONSULTATION
- The consultation is where we teach them how to generate PAYING CLIENTS from their YouTube
- Check "Loom Watched Follow Up" field
- If NOT watched → Last gentle offer to resend OR offer the free consultation
- If watched → Last offer for the FREE CONSULTATION
- Keep it low pressure but valuable: "No worries if not, just thought I could show you some quick wins for turning your YouTube videos into clients"

IMPORTANT: WE DO NOT CREATE VIDEOS:
- We do NOT create videos for them. We help them get LEADS from their EXISTING YouTube videos
- Never say "content." Say "YouTube videos" (e.g., "help you get clients from your YouTube videos")

CRITICAL: READ THE CONVERSATION HISTORY AND CHECK TIMING:
- Review ALL messages marked as "US:" to see what we've already said AND their DATES
- CHECK THE DATES: If it's been weeks/months since last contact, acknowledge the time gap naturally
- DO NOT say "just sent" if the video was sent long ago
- DO NOT repeat any previous phrases or approaches
- This is message #3, so you need a FRESH angle that's different from messages 1 and 2

Guidelines:
- Keep it very short (1-2 sentences)
- USE HUMOR to acknowledge the multiple messages or the time gap if applicable. "Ok last one, I swear" or "I'll let you off the hook after this"
- Low pressure but make them laugh
- Leave an easy way to re-engage in the future
- Don't guilt trip. Be playfully self-aware instead
- Remember: FIRST WORD must be "Hey [their name],"
- Write like a friend who knows when to back off gracefully`,

  4: `This is the FOURTH follow-up message (Day 14, 2 weeks in).

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

This is a "long-term nurture" touch. They may have been busy or the timing wasn't right before.

FIRST, CHECK IF A CLIPIO VIDEO (video audit) WAS SENT:
- Look for "Clipio Link" in the contact's Relevant Details
- If "Clipio Link" is NOT listed, empty, or undefined → NO VIDEO WAS SENT
- ONLY if it contains an actual URL → A video WAS sent

**CRITICAL: If you don't see a Clipio Link URL, DO NOT mention any video. You didn't send one!**

IF NO VIDEO AUDIT WAS SENT (Clipio Link missing/empty):
- Circle back with the free video audit offer using a fresh angle
- Maybe mention you've helped other agents in their market

IF VIDEO AUDIT WAS SENT (Clipio Link exists):
- They already received the video audit. NOW we want to get them on a FREE CONSULTATION
- The consultation is where we teach them how to generate PAYING CLIENTS from their YouTube
- Check "Loom Watched Follow Up" field
- If NOT watched → Fresh angle to offer resend OR the free consultation
- If watched → Fresh angle to offer the FREE CONSULTATION
- Try a different value prop: "I've helped agents turn their YouTube into 5-10 new clients/month, happy to show you how"

IMPORTANT: WE DO NOT CREATE VIDEOS:
- We do NOT create videos for them. We help them get LEADS from their EXISTING YouTube videos
- Never say "content." Say "YouTube videos" (e.g., "help you get clients from your YouTube videos")

CRITICAL: READ THE CONVERSATION HISTORY AND CHECK TIMING:
- Review ALL messages marked as "US:" to see what angles we've already used AND their DATES
- CHECK THE DATES: Acknowledge how long it's been since you last reached out
- By now we've sent 3 messages. DO NOT repeat ANY of those approaches
- Try something completely new

Guidelines:
- Keep it short (1-2 sentences)
- USE HUMOR about the time gap. "Plot twist: I'm back" or "Remember me?" or "It's been a minute!"
- Be playfully persistent, not desperate
- If you can reference something specific about their content, do it
- Remember: FIRST WORD must be "Hey [their name],"
- Write like a friend checking in with a smile`,

  5: `This is the FIFTH follow-up message (Day 21, 3 weeks in).

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

This is a value-add touch. Share something useful without asking for anything.

IMPORTANT: Do NOT mention any video at this point. Focus on value and relationship building.

CRITICAL: READ THE CONVERSATION HISTORY AND CHECK TIMING:
- Review ALL previous "US:" messages as we've sent 4 already AND their DATES
- CHECK THE DATES: If it's been a while, acknowledge the gap casually
- This message should feel DIFFERENT. Lead with pure value, no ask

Guidelines:
- Keep it short (1-2 sentences)
- Lead with value AND humor. Share something useful in a fun way
- Mention you're still happy to chat if they're interested
- Very low pressure. This is about staying on their radar while making them smile
- Reference their YouTube channel or content if possible
- Remember: FIRST WORD must be "Hey [their name],"
- Write like a friend sharing a cool tip`,

  6: `This is the SIXTH follow-up message (Day 30, 1 month in).

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

Monthly check-in. Keep the door open without being pushy.

CRITICAL: READ THE CONVERSATION HISTORY AND CHECK TIMING:
- We've sent 5 messages already. Read them ALL in the "US:" entries AND their DATES
- CHECK THE DATES: Acknowledge how long it's been if relevant
- At this point, don't mention the video at all
- This is just a friendly check-in, not a pitch

Guidelines:
- Keep it very short (1-2 sentences)
- BE PLAYFUL. "Just your monthly reminder that I exist" or "Popping in like that friend who texts once a month"
- Mention you help agents with lead generation and follow-up
- Leave an easy way to re-engage with humor
- Zero pressure. Just be likeable
- Remember: FIRST WORD must be "Hey [their name],"
- Write like a fun friend who doesn't take themselves too seriously`,

  7: `This is the SEVENTH and FINAL follow-up message (Day 45, 6 weeks in).

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

Final touch before moving to long-term cold storage.

CRITICAL: READ THE CONVERSATION HISTORY AND CHECK TIMING:
- We've sent 6 messages and this is the last one. CHECK THE DATES
- Don't repeat anything from previous messages
- Keep it simple and gracious. Just a farewell

Guidelines:
- Keep it very short (1 sentence)
- END WITH HUMOR AND WARMTH. "Alright, I'll officially stop bugging you now, but your content is still great!"
- Leave the door open with a smile
- No ask. Just a memorable, likeable farewell
- This is about ending on a good note that makes them smile
- Remember: FIRST WORD must be "Hey [their name],"
- Write like a friend signing off who might reconnect someday`,

  // For handling inbound replies (not part of sequence)
  reply: `The lead (a real estate agent) has REPLIED to your message. Craft a personalized response.

**MANDATORY FORMAT: Your message MUST begin with "Hey [Name]," where [Name] is their first name from the Contact Information. For example, if their name is "Nate Morris", start with "Hey Nate,". If their name is "Chelsea Anderson", start with "Hey Chelsea,". The FIRST WORD of your output MUST be "Hey" followed by their name and a comma. DO NOT SKIP THIS.**

FIRST, CHECK IF A CLIPIO VIDEO (video audit) WAS SENT:
- Look for "Clipio Link" in the contact's Relevant Details
- If "Clipio Link" is NOT listed, empty, or undefined → NO VIDEO WAS SENT
- ONLY if it contains an actual URL (like "https://video.nurtre.io/...") → A video WAS sent

**CRITICAL: If you don't see a Clipio Link URL, DO NOT mention any video you "sent." You didn't send one!**

TWO TYPES OF LEADS:
1. NO Clipio Link = They haven't received a video audit yet → Offer FREE VIDEO AUDIT
2. HAS Clipio Link = They got the video audit → Offer FREE CONSULTATION to teach them how to generate paying clients from their YouTube

IMPORTANT: WE DO NOT CREATE VIDEOS:
- We do NOT create videos for them
- We HELP them turn their EXISTING YouTube VIDEOS into LEADS and PAYING CLIENTS
- Never say "content." Say "YouTube videos" (e.g., "help you get clients from your YouTube videos")
- Use "paying clients", "leads", "GCI," NOT "grow your channel" or "YouTube presence"

Guidelines:
- Read their message carefully and respond to what they actually said
- BE WARM AND FRIENDLY. They took time to reply, so match their energy with enthusiasm
- If they asked a question, answer it directly and honestly. Maybe add a light joke
- If they showed interest in the video audit, great! Ask what they thought or offer to send one
- If they want to chat, suggest a quick Google Meet video call to discuss lead generation
- If no video audit was sent yet, offer to put one together for them
- Mention key benefits if relevant: exclusive leads, leads that want to speak to THEM specifically, your team handles nurturing/follow-up
- If they're not interested, be gracious with humor: "No worries at all! I'll go back to admiring your content from afar"
- Match their tone. If they're casual, be casual and fun. If they're brief, keep it short but warm
- Keep it conversational and human. This is SMS, not email
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

async function generateResponse(contact, conversationHistory, step, firstName = 'there') {
  // Build context from contact data
  const contactContext = buildContactContext(contact);

  // firstName is now passed directly from webhook body - no need to extract

  // Get step-specific prompt
  const stepPrompt = STEP_PROMPTS[step] || STEP_PROMPTS.reply;

  // Build the full prompt
  const userPrompt = `
## CRITICAL: The lead's first name is "${firstName}" - your message MUST start with "Hey ${firstName},"

## Contact Information
${contactContext}

## Conversation History
${conversationHistory}

## Your Task
${stepPrompt}

Generate the SMS message now. IMPORTANT: Start with "Hey ${firstName}," - this is mandatory. Keep it short and natural.`;

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 300,
    system: COMPANY_CONTEXT,
    messages: [
      {
        role: 'user',
        content: userPrompt,
      },
    ],
  });

  let message = response.content[0].text.trim();

  console.log('=== BULLETPROOF DEBUG ===');
  console.log('firstName param:', firstName);
  console.log('Raw Claude message:', message);

  // BULLETPROOF: Guarantee the name is included - prepend if Claude didn't include it
  const expectedGreeting = `hey ${firstName.toLowerCase()}`;
  console.log('Expected greeting:', expectedGreeting);
  console.log('Message starts with expected?', message.toLowerCase().startsWith(expectedGreeting));

  if (!message.toLowerCase().startsWith(expectedGreeting)) {
    // Remove any existing generic greeting Claude might have used
    const beforeStrip = message;
    message = message.replace(/^(hey there,?|hi there,?|hey,?|hi,?)\s*/i, '');
    console.log('After stripping generic greeting:', message);
    message = `Hey ${firstName}, ${message}`;
    console.log('After prepending name:', message);
  }

  console.log('=== FINAL MESSAGE ===');
  console.log(message);

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

    // Generate personalized response with Claude - pass firstName explicitly
    const generatedMessage = await generateResponse(contact, conversationHistory, step, firstName);
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

    // Generate reply using 'reply' step - pass firstName explicitly
    const generatedMessage = await generateResponse(contact, conversationHistory, 'reply', firstName);
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
- Airbnb management for GTA homeowners, 10-15% fee (competitors charge 18-25%)
- Clients see 30-100% more income. No contracts, no startup costs, commission only
- You own your listing. First booking within a week. 4.9 star rating
- Phone: (647) 957-8956 | nurturestays.ca

SERVICES: Full management (listing, guests, pricing, cleaning, maintenance), co-hosting, dynamic pricing, pro photography, multi-platform (Airbnb, VRBO, Booking.com), guest screening, 24/7 support

PRICING:
- Starter (10%): listing, pricing, guest comms, screening, reviews
- Professional (15%): + cleaning, supplies, smart locks, dedicated manager

CLIENT RESULTS (use sparingly, one at a time):
- Client went from -$926/mo (long-term) to +$847/mo with Airbnb
- 1-bed condo: $4,123/mo after switching to us
- Average managed listing: $4,460+/mo

REGULATIONS:
- Toronto: 180 nights/year, principal residence, 8.5% MAT
- Most GTA cities require principal residence for short-term
- Mid-term (30+ days) works for investment properties in restricted areas
- We handle licensing and compliance

WRITING RULES:
- Write like you're texting. 1-3 sentences max. No essays
- NEVER use dashes/hyphens ( - ) except in compound words like "short-term"
- First person ("I", "we"). Never sign off with a name
- Answer their question first, then nudge toward next step (estimate, call, nurturestays.ca/contact)
- Don't make up numbers. Only cite the exact results above
- Be helpful first, sales second. No corporate speak, no fluff`;

const NURTURE_FB_PROMPT = `Reply to the lead's LATEST message. Read the full conversation history first.

RULES:
1. Never ask something they already answered. Read the history
2. Reply to their most recent message directly. Don't start over
3. Keep it short. 1-3 sentences. Match their energy
4. If the conversation is already going, don't re-introduce yourself
5. Answer first, then nudge toward a call or estimate if it fits naturally`;

async function generateFBResponse(contact, conversationHistory, firstName) {
  const contactContext = buildContactContext(contact);

  console.log('Conversation history being sent to Claude:', conversationHistory);

  const userPrompt = `## Your Task
${NURTURE_FB_PROMPT}

## Contact Information
${contactContext}

${firstName && firstName !== 'there' ? `The lead's name is "${firstName}".` : 'You do not know their name yet.'}

## Full Conversation History (read this carefully before replying)
${conversationHistory}

Now write your reply to the lead's most recent message above. Reply ONLY with the message text, nothing else.`;

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 500,
    system: NURTURE_PM_CONTEXT,
    messages: [{ role: 'user', content: userPrompt }],
  });

  let message = response.content[0].text.trim();

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

    // Generate response with Claude using Nurture PM context
    const generatedMessage = await generateFBResponse(contact, conversationHistory, firstName);
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
// START SERVER
// ============================================

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`GHL Claude Server running on port ${PORT}`);
  console.log('Endpoints:');
  console.log(`  POST /webhook/followup?step=1-7 - Follow-up sequence`);
  console.log(`  POST /webhook/reply - Handle inbound replies`);
  console.log(`  POST /webhook/fb-message - Facebook Messenger auto-reply (Nurture PM)`);
});

// Export for Vercel
module.exports = app;
