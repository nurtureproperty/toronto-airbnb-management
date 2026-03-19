/**
 * GHL Auto Follow-Up for Nurture Property Management
 *
 * Detects leads in target pipeline stages with no recent outbound contact,
 * generates a personalized SMS via Claude, and sends it through GHL.
 * 11-step sequence: Day 4, 8, 12, 17, 23, 43, 64, 84, 105, 127, 149.
 *
 * Usage:
 *   node scripts/ghl-auto-followup.js --dry-run   # preview only, no sends
 *   node scripts/ghl-auto-followup.js              # send follow-ups + email summary
 */

import { config } from 'dotenv';
import { createTransport } from 'nodemailer';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import Anthropic from '@anthropic-ai/sdk';

config();

const GHL_API_BASE = 'https://services.leadconnectorhq.com';
const API_TOKEN = process.env.GHL_API_TOKEN;
const LOCATION_ID = process.env.GHL_LOCATION_ID;
const DRY_RUN = process.argv.includes('--dry-run');
const PIPELINE_ID = '5evE1uBxqtMqrqfXc7qM'; // B2B Pipeline
const TRACKER_PATH = new URL('./followup-tracker.json', import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1');

const MAX_STEPS = 11;        // Max auto-followups per lead

// Days since last outbound (step 1) or days since previous auto-send (steps 2+)
const STEP_GAPS = {
  1: 4,    // Day 4: first contact after 4 days inactive
  2: 4,    // Day 8: 4 days after step 1
  3: 4,    // Day 12: 4 days after step 2
  4: 5,    // Day 17: 5 days after step 3
  5: 6,    // Day 23: 6 days after step 4
  6: 20,   // Day 43: 20 days after step 5
  7: 21,   // Day 64: 21 days after step 6
  8: 20,   // Day 84: 20 days after step 7
  9: 21,   // Day 105: 21 days after step 8
  10: 22,  // Day 127: 22 days after step 9
  11: 22,  // Day 149: 22 days after step 10
};

const TARGET_STAGES = [
  { id: '03ceb60c-99e4-4cfa-82fe-95c02151831e', name: 'ISA TO FOLLOW UP' },
  { id: 'bcc48228-e9e6-484d-84fb-5631ae96c0e7', name: 'Follow-up Sequence (New Leads)' },
  { id: 'cd49a3d6-8f7a-45f6-b65c-05c7c9ce3b8d', name: "Can't Contact (contract sent - 5 attempts made)" },
];

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const delay = (ms) => new Promise(r => setTimeout(r, ms));

// ============================================
// COMPANY CONTEXT (System Prompt)
// ============================================

const COMPANY_CONTEXT = `You are a friendly follow-up assistant for Nurture Property Management, a premium Airbnb management company in the Greater Toronto Area.

ABOUT NURTURE:
- We help GTA homeowners maximize rental income through expert Airbnb management
- 12-15% management fee on host payout only (competitors charge 18-25%)
- Clients typically see 30-100% increases in monthly revenue
- No long-term contracts, commission only
- Clients own their listings (we never hold listings hostage)
- First booking within 1 week on average
- 4.9 star average Airbnb rating, <9 minute average guest response time
- Locally owned in the GTA
- Phone: (647) 957-8956
- Website: nurturestays.ca

OUR ORIGIN STORY (use sparingly for authenticity):
- We started as frustrated Airbnb hosts ourselves who fired our property managers and did it ourselves
- Friends and family started asking for help, which grew into the business
- We know the pain points because we lived them

SPECIFIC CLIENT RESULTS (use one per message, don't stack):
- One client went from -$926/month cashflow (long-term rental) to +$847/month with Airbnb in the first month
- A 1-bedroom condo generated $4,123/month after switching to our management
- 87% cashflow increase in month one for a featured case study

UNIQUE SERVICE DETAILS (rotate these across messages):
- Commission on host payout only, never on cleaning fees or Airbnb charges
- No setup fees, no monthly minimums. We only make money when you make money
- AI + manual dynamic pricing adjusted daily for maximum revenue
- Professional photography included at no extra cost
- 24/7 emergency support for guest issues (burst pipes, lockouts, etc.)
- Monthly performance reports with full transparency
- Guest screening with strict no-party policy
- Multi-platform distribution: Airbnb, Booking.com, VRBO, Google
- Entire launch process from staging to first booking takes less than a week
- Superhost status and "Guest Favorite" badge on our managed properties

BRAND VOICE:
- Professional but approachable, never corporate
- Confident without being arrogant
- Helpful and educational
- Local and relatable (we're GTA-based, not a faceless corporation)
- Use "you" and "your" language
- Never badmouth competitors
- Never overpromise specific dollar amounts unless citing the EXACT case studies listed above
- NEVER make up or fabricate case studies, revenue numbers, or results. Only use the three specific client results listed above, word for word. Do not invent stats about specific cities, property types, or markets.

CRITICAL SMS RULES:
- Write in first person ("I", "me", "my"). NEVER use any team member names.
- NEVER use dashes or hyphens ( - ) in message content. Use commas, periods, or "and" instead. The only exception is compound words like "short-term". Never write "something - something else". Write "something, something else" or split into two sentences.
- Keep messages to 1-3 sentences. This is a text message, not an email.
- Write like you're texting a friend who you respect professionally
- Always end with a soft question or gentle next step
- Never use emojis
- Never say "just following up" or "just checking in" as the opener
- Reference something specific from the conversation history or their notes if possible
- If you don't know their property details, ask about it naturally
- Each follow-up should use a DIFFERENT angle/fact. Never repeat what was said before.
- Do NOT sign off with a name. No "- Name" at the end.
- NEVER say "I'll give you a call", "I'll call you shortly", or promise any phone call. You are a text bot and cannot make calls. Instead say something like "want to hop on a quick call? You can book one at nurturestays.ca/contact" or offer a free estimate.

ANTI-REPETITION RULES (READ CAREFULLY):
- STUDY the conversation history below. Your message must NOT repeat ANY sentence structure, phrasing, or angle already used.
- BANNED phrases that make texts sound robotic and identical: "I know you mentioned", "just curious", "just wanted to", "wanted to check", "wanted to reach out", "hope you're doing well", "hope all is well", "thought of you", "circling back"
- Vary your opener structure EVERY time. Do NOT always use "Hey [Name], [reference to past convo]. [Question]?" Rotate between these patterns:
  * Direct question: "Hey [Name], did anything change with the [city] property?"
  * Value lead: "Hey [Name], [interesting fact or insight]. [Soft question]?"
  * Casual: "Hey [Name]! [Short statement]. [Question]?"
  * News hook: "Hey [Name], [timely event or update]. [Connection to them]?"
- If the conversation history shows previous automated messages, make yours sound COMPLETELY different in structure.
- Read your drafted message and ask: "Would someone reading all my messages back to back think a bot wrote these?" If yes, rewrite.`;

// ============================================
// STEP PROMPTS
// ============================================

const STEP_PROMPTS = {
  1: `This is the FIRST automated follow-up (Day 4). The ISA hasn't contacted this lead in 4+ days.

Your goal: Re-engage warmly. Reference their property if you can see it in notes or conversation.
- If you know their address/city, reference it naturally ("How's everything going with the property on [street]?")
- If no property context, offer a free rental estimate
- Keep it casual and curious, not salesy
- End with a question that's easy to answer
- DO NOT mention any stats or company details yet, just be human`,

  2: `This is the SECOND follow-up (Day 8). They didn't respond to the first one.

Your goal: Share a specific, compelling insight they haven't heard. Pick ONE of these angles:
- A real client result: "One of our clients went from losing $926/month on a long-term rental to making $847/month on Airbnb in just the first month"
- The "we only earn when you earn" angle: "We charge 12-15% of your host payout only, no setup fees, no monthly minimums"
- A timely angle: spring/summer is peak season for Airbnb in the GTA, now is the time to get listed
- Keep it to 2 sentences max. Don't repeat anything from step 1.`,

  3: `This is the THIRD follow-up (Day 12). Still no response.

Your goal: Share a unique trust-building detail. Pick ONE angle:
- Our origin story: "We actually started as Airbnb hosts ourselves, fired our managers and did it better. That's how this company started"
- The speed angle: "Most properties go from signing up to their first booking in under a week"
- The control angle: "You keep full ownership of your listing and reviews. We never hold anything hostage"
- The results angle: "We've got Superhost status and Guest Favorite badges across our managed properties, which means higher search ranking for your listing"
- 1-2 sentences max. Sound genuinely helpful, not desperate.`,

  4: `This is the FOURTH follow-up (Day 17). Low response likelihood but worth one more try.

Your goal: Address a common fear or objection. Pick ONE:
- No lock-in fear: "No long contracts and we work on commission only, so we only make money when you do"
- The hidden fee concern: "Our commission is only on your host payout, never on cleaning fees or Airbnb charges. No surprises"
- The effort concern: "We handle literally everything. Guest messages, cleaning, pricing, restocking, even emergency repairs at 2am"
- Or just: "Happy to answer any questions, zero pressure"
- Keep it the shortest message yet, 1-2 sentences.`,

  5: `This is the FIFTH follow-up (Day 23). You've tried several times with no response.

Your goal: Soft close with a door left open.
- Let them know the door is always open
- "No worries if the timing isn't right, we're here whenever you're ready"
- This should feel like a genuine goodbye, not a guilt trip
- 1 sentence is fine`,

  6: `This is a LONG-TERM NURTURE follow-up (Day 43). It's been about 3 weeks since the last message.

Your goal: Re-engage with fresh value. This is NOT a follow-up on old conversations. Treat it like a new touchpoint.
- Share something timely: a seasonal insight ("summer bookings are picking up"), a general market trend, or a service detail they haven't heard
- Or reference something relevant to their area if you know it
- Keep it to 1-2 sentences, casual and helpful
- Don't reference previous unanswered messages
- Make it feel like you just thought of them, not like you're grinding through a list
- Do NOT make up revenue numbers, case studies, or stats about specific areas. Only use the exact client results from the company context if needed.`,

  7: `This is a LONG-TERM NURTURE follow-up (Day 64). About 3 weeks since the last message.

Your goal: One more value-driven touchpoint.
- Share a different angle than step 6: one of the real client results from the company context, a seasonal opportunity, or a simple "still here if you ever want to chat"
- If their property is in a city with new STR regulations, mention it as a helpful heads-up
- 1-2 sentences max. Warm and zero pressure.
- Don't reference previous unanswered messages
- Do NOT fabricate case studies or revenue numbers. Only cite the exact results provided in the company context.`,

  8: `This is a LONG-TERM NURTURE follow-up (Day 84). About 3 weeks since the last message.

Your goal: Share a fresh, useful angle they haven't heard yet.
- Pick ONE: a seasonal trend ("spring is peak booking season in the GTA"), a service detail they haven't heard, or a general insight about short-term rentals
- Keep it to 1-2 sentences, casual and helpful
- Don't reference previous unanswered messages
- Do NOT make up revenue numbers, case studies, or stats. Only use the exact client results from the company context if needed.`,

  9: `This is a LONG-TERM NURTURE follow-up (Day 105). About 3 weeks since the last message.

Your goal: Offer a different value angle.
- Pick ONE: the "we only earn when you earn" angle, a real client result from the company context, or a simple helpful tip about maximizing rental income
- Keep it to 1-2 sentences. Warm and zero pressure.
- Don't reference previous unanswered messages
- Do NOT fabricate case studies or revenue numbers. Only cite the exact results provided in the company context.`,

  10: `This is a LONG-TERM NURTURE follow-up (Day 127). About 3 weeks since the last message.

Your goal: One last value touchpoint before the final close.
- Share something genuinely helpful: a market insight, a service detail, or simply let them know you're still around
- 1-2 sentences max. Zero pressure, no sales pitch
- Don't reference previous unanswered messages
- Do NOT make up revenue numbers or case studies.`,

  11: `This is the FINAL long-term follow-up (Day 149). Last message ever for this lead.

Your goal: Graceful, permanent close.
- Something like "Just wanted to say the offer always stands if you ever want help with your property"
- This is the last automated message they'll receive. Make it kind and memorable.
- 1 sentence only. No sales pitch.`,
};

// ============================================
// NOTE PARSING (reused from audit)
// ============================================

const MONTH_NAMES = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
const MONTH_FULL = { january: 0, february: 1, march: 2, april: 3, may: 4, june: 5, july: 6, august: 7, september: 8, october: 9, november: 10, december: 11 };

function splitNoteEntries(notesText) {
  if (!notesText) return [];
  const lines = notesText.split('\n').map(l => l.trim()).filter(Boolean);
  const entries = [];
  let cur = '';
  for (const line of lines) {
    if (/^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}\s*[-:]/i.test(line) || /^SB\s/i.test(line)) {
      if (cur) entries.push(cur.trim());
      cur = line;
    } else if (/^\*\s/.test(line)) {
      if (cur) entries.push(cur.trim());
      cur = line;
    } else {
      cur += ' ' + line;
    }
  }
  if (cur) entries.push(cur.trim());
  return entries;
}

function checkSuppression(notesText) {
  const entries = splitNoteEntries(notesText);
  if (entries.length === 0) return { suppress: false };
  const recent = entries.slice(-3).map(e => e.toLowerCase()).join(' ');
  if (/(?:not|don'?t)\s+(?:like|want)\s+(?:for\s+)?us\s+to\s+(?:reach|call|contact)/i.test(recent) ||
      /(?:he|she|they)'?(?:ll| will| would)\s+(?:give us a\s+)?(?:call|reach|contact|update)/i.test(recent) ||
      /(?:he|she|they)\s+(?:will|would)\s+(?:call|reach|contact|update|get back)/i.test(recent) ||
      /would\s+(?:call\s+(?:back|us)|get\s+back\s+to\s+us|reach\s+out|contact\s+us)/i.test(recent) ||
      /will\s+(?:update\s+us|get\s+back\s+to\s+us|reach\s+out|call\s+us)/i.test(recent) ||
      /(?:busy\s+and\s+would\s+call|said\s+(?:she|he|they)'?d?\s+call)/i.test(recent) ||
      /(?:not interested|declined|not\s+moving\s+forward|doesn'?t want|do not (?:call|contact))/i.test(recent) ||
      /(?:sold\s+(?:the\s+)?property|no\s+longer\s+(?:hosting|renting|interested)|property\s+sold)/i.test(recent)) {
    return { suppress: true };
  }
  return { suppress: false };
}

function parseRelativeDate(dateStr) {
  const match = dateStr.match(/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})/i);
  if (!match) return null;
  const month = MONTH_NAMES[match[1].toLowerCase()];
  if (month === undefined) return null;
  let year = new Date().getFullYear();
  const candidate = new Date(year, month, parseInt(match[2]));
  if (candidate > new Date(Date.now() + 90 * 24 * 60 * 60 * 1000)) year--;
  return new Date(year, month, parseInt(match[2]));
}

function checkDeferredFollowUp(notesText) {
  const entries = splitNoteEntries(notesText);
  if (entries.length === 0) return { deferred: false };
  const now = new Date();
  const recent = entries.slice(-5).join(' ');
  const lower = recent.toLowerCase();

  if (/(?:in\s+a\s+few\s+months|couple\s+(?:of\s+)?months|once\s+the\s+weather|after\s+(?:the\s+)?snow)/i.test(lower))
    return { deferred: true };

  if (/(?:try\s+back|reach\s+(?:back\s+)?out|ro\s+(?:back\s+)?out|check\s+back|follow[\s-]?up)\s+(?:again\s+)?in\s+a\s+few\s+weeks/i.test(lower)) {
    const entryWithPhrase = entries.slice(-5).find(e => /in\s+a\s+few\s+weeks/i.test(e));
    const dateMatch = entryWithPhrase?.match(/^((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2})/i);
    if (dateMatch) {
      const noteDate = parseRelativeDate(dateMatch[1]);
      if (noteDate && new Date(noteDate.getTime() + 21 * 24 * 60 * 60 * 1000) > now) return { deferred: true };
    } else {
      return { deferred: true };
    }
  }

  const actionVerb = '(?:follow[\\s-]?up|reach\\s+(?:back\\s+)?out|check\\s+back|call\\s+(?:him|her|them|back)|ro\\s+(?:back\\s+)?out|cb)';
  const calendarVerb = '(?:put\\s+in\\s+calendar\\s+to\\s+(?:call|reach\\s+out|contact)|setup\\s+follow[\\s-]?up\\s+for|set\\s+up\\s+follow[\\s-]?up\\s+for)';
  const monthName = '(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)';

  const patterns = [
    new RegExp(`${calendarVerb}\\s+(?:in\\s+)?(?:late\\s+|early\\s+|mid[\\s-]?)?${monthName}(?:\\s+(\\d{1,2})(?:st|nd|rd|th)?)?`, 'i'),
    new RegExp(`${actionVerb}\\s+(?:in\\s+|closer\\s+to\\s+)?(?:late\\s+|early\\s+|mid[\\s-]?)${monthName}(?:\\s+(\\d{1,2})(?:st|nd|rd|th)?)?`, 'i'),
    new RegExp(`${actionVerb}\\s+(?:in\\s+)${monthName}(?:\\s+(\\d{1,2})(?:st|nd|rd|th)?)?`, 'i'),
    new RegExp(`${actionVerb}\\s+(?:monthly|weekly)?\\s*starting\\s+(?:from\\s+)?${monthName}(?:\\s+(\\d{1,2})(?:st|nd|rd|th)?)?`, 'i'),
  ];

  for (const pattern of patterns) {
    const match = lower.match(pattern);
    if (!match) continue;
    const monthStr = (match[1] || '').toLowerCase();
    const monthNum = MONTH_NAMES[monthStr.slice(0, 3)] ?? MONTH_FULL[monthStr];
    if (monthNum === undefined) continue;
    let dayNum = match[2] ? parseInt(match[2]) : null;
    if (/mid[\s-]?/.test(lower) && dayNum === null) dayNum = 15;
    if (/late\s+/.test(lower) && dayNum === null) dayNum = 25;
    if (dayNum === null) dayNum = 1;
    const target = new Date(now.getFullYear(), monthNum, dayNum);
    if (target < new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)) continue;
    if (target > now) return { deferred: true };
  }

  return { deferred: false };
}

// ============================================
// GHL API
// ============================================

function buildHeaders() {
  return {
    'Authorization': `Bearer ${API_TOKEN}`,
    'Version': '2021-07-28',
    'Content-Type': 'application/json',
  };
}

async function apiGet(path) {
  const url = `${GHL_API_BASE}${path}`;
  const response = await fetch(url, { headers: buildHeaders() });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${path.slice(0, 60)} - ${text.slice(0, 150)}`);
  }
  return response.json();
}

async function getStageOpportunities(stageId) {
  const allOpps = [];
  let hasMore = true;
  let page = 0;
  while (hasMore) {
    const data = await apiGet(
      `/opportunities/search?location_id=${LOCATION_ID}&pipeline_id=${PIPELINE_ID}&pipeline_stage_id=${stageId}&limit=100${page ? `&startAfter=${page * 100}` : ''}`
    );
    const opps = data.opportunities || [];
    allOpps.push(...opps);
    hasMore = opps.length === 100;
    page++;
    if (hasMore) await delay(200);
  }
  return allOpps;
}

async function getContact(contactId) {
  const data = await apiGet(`/contacts/${contactId}?locationId=${LOCATION_ID}`);
  return data.contact || data;
}

async function getMessages(contactId) {
  try {
    const convData = await apiGet(`/conversations/search?contactId=${contactId}`);
    const convs = convData.conversations || [];
    if (convs.length === 0) return [];
    const allMsgs = [];
    for (const conv of convs) {
      const msgData = await apiGet(`/conversations/${conv.id}/messages`);
      const wrapper = msgData.messages || {};
      const msgs = Array.isArray(wrapper) ? wrapper : (wrapper.messages || []);
      allMsgs.push(...msgs);
      await delay(100);
    }
    return allMsgs.sort((a, b) => new Date(a.dateAdded) - new Date(b.dateAdded));
  } catch (e) {
    return [];
  }
}

async function sendSMS(contactId, message) {
  const response = await fetch(`${GHL_API_BASE}/conversations/messages`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({
      type: 'SMS',
      contactId,
      message,
    }),
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to send SMS: ${response.status} - ${error}`);
  }
  return response.json();
}

// ============================================
// CONVERSATION HISTORY FORMATTER
// ============================================

function formatConversationHistory(messages) {
  if (!messages || messages.length === 0) return 'No previous messages.';

  const SYSTEM_TYPES = new Set([28, 31, '28', '31']);
  const real = messages.filter(m => {
    const type = m.type ?? m.messageType;
    if (SYSTEM_TYPES.has(type)) return false;
    if (type === 1 || type === '1') return true;
    return !!(m.body?.trim());
  });

  const recent = real.slice(-20);
  return recent.map(msg => {
    const dir = msg.direction === 'inbound' ? 'LEAD' : 'US';
    const date = new Date(msg.dateAdded || msg.createdAt).toLocaleDateString('en-CA');
    const type = msg.type ?? msg.messageType;
    const body = (type === 1 || type === '1') ? '[phone call]' : (msg.body || '[no text]');
    return `[${date}] ${dir}: ${body}`;
  }).join('\n');
}

// ============================================
// CONTACT CONTEXT BUILDER
// ============================================

function buildContactContext(contact) {
  const c = contact;
  let context = `Name: ${c.firstName || ''} ${c.lastName || ''}`.trim();
  if (c.email) context += `\nEmail: ${c.email}`;
  if (c.phone) context += `\nPhone: ${c.phone}`;
  if (c.address1) context += `\nAddress: ${c.address1}`;
  if (c.city) context += `\nCity: ${c.city}`;

  // Custom fields relevant to property management
  const importantFields = ['Notes', 'notes', 'Property Address', 'Listing Type', 'Bedrooms', 'Call Notes'];
  if (c.customFields && c.customFields.length > 0) {
    const relevant = c.customFields.filter(f => f.value && importantFields.some(k => (f.key || f.id || '').toLowerCase().includes(k.toLowerCase())));
    if (relevant.length > 0) {
      context += '\n\nRelevant Details:';
      relevant.forEach(f => { context += `\n- ${f.key || f.id}: ${String(f.value).slice(0, 300)}`; });
    }
  }

  if (c.tags && c.tags.length > 0) context += `\n\nTags: ${c.tags.join(', ')}`;
  return context;
}

// ============================================
// CLAUDE MESSAGE GENERATION
// ============================================

async function generateFollowUp(contact, messages, step, firstName) {
  const contactContext = buildContactContext(contact);
  const conversationHistory = formatConversationHistory(messages);
  const stepPrompt = STEP_PROMPTS[step] || STEP_PROMPTS[1];

  // Extract our previous outbound messages to show Claude what to avoid
  const priorOutbound = messages
    .filter(m => m.direction === 'outbound' || m.direction === 'outgoing')
    .map(m => (m.body || '').trim())
    .filter(Boolean)
    .slice(-5);  // Last 5 outbound messages

  const avoidSection = priorOutbound.length > 0
    ? `## MESSAGES WE ALREADY SENT (DO NOT repeat structure, phrasing, or angles from these):\n${priorOutbound.map((m, i) => `${i + 1}. "${m}"`).join('\n')}\n\nYour message MUST sound completely different from all of the above. Different opener, different structure, different angle.`
    : '';

  const userPrompt = `## CRITICAL: The lead's first name is "${firstName}" - your message MUST start with "Hey ${firstName},"

## Contact Information
${contactContext}

## Conversation History
${conversationHistory}

${avoidSection}

## Your Task
${stepPrompt}

Generate the SMS message now. Start with "Hey ${firstName}," - this is mandatory. Keep it short and natural. Use "I" and "me". Do NOT sign off with any name. Make sure this message sounds NOTHING like our previous messages to this person.`;

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 300,
    system: COMPANY_CONTEXT,
    messages: [{ role: 'user', content: userPrompt }],
  });

  let message = response.content[0].text.trim();

  // Guarantee name in greeting
  const expected = `hey ${firstName.toLowerCase()}`;
  if (!message.toLowerCase().startsWith(expected)) {
    message = message.replace(/^(hey there,?|hi there,?|hey,?|hi,?)\s*/i, '');
    message = `Hey ${firstName}, ${message}`;
  }

  return message;
}

// ============================================
// TRACKER
// ============================================

function loadTracker() {
  try {
    if (existsSync(TRACKER_PATH)) {
      return JSON.parse(readFileSync(TRACKER_PATH, 'utf-8'));
    }
  } catch (e) { /* ignore corrupt file */ }
  return {};
}

function saveTracker(tracker) {
  // Clean entries older than 180 days (sequence runs up to day 130)
  const cutoff = Date.now() - 180 * 24 * 60 * 60 * 1000;
  for (const [id, entry] of Object.entries(tracker)) {
    if (new Date(entry.lastSent).getTime() < cutoff) delete tracker[id];
  }
  writeFileSync(TRACKER_PATH, JSON.stringify(tracker, null, 2));
}

// ============================================
// MAIN LOGIC
// ============================================

/**
 * Checks if a phone number is Canadian (+1 with 10 digits, or 10-digit starting with valid area code).
 * Skips international numbers like +91 (India), +44 (UK), etc.
 */
function isCanadianNumber(phone) {
  if (!phone) return false;
  const digits = phone.replace(/\D/g, '');
  // +1XXXXXXXXXX (11 digits starting with 1) or XXXXXXXXXX (10 digits)
  if (digits.length === 11 && digits.startsWith('1')) return true;
  if (digits.length === 10) return true;
  return false;
}

async function processLead(opp, tracker, today, actions) {
  const name = opp.contact?.name || opp.name || 'Unknown';
  const contactId = opp.contactId || opp.contact?.id;
  if (!contactId) return;

  const contact = await getContact(contactId);
  await delay(100);

  // Skip non-Canadian phone numbers
  if (!isCanadianNumber(contact.phone)) {
    actions.push({ name, status: 'SKIPPED', reason: `Non-Canadian number: ${contact.phone || 'none'}` });
    return;
  }

  const firstName = contact.firstName || name.split(' ')[0] || 'there';

  // Get notes from custom field
  const cf = contact.customFields || [];
  const notesField = cf.find(f => f.id === 'JJ0KZuIGHR0OC996z1b6' || f.fieldKey === 'contact.notes');
  const notesText = notesField ? (notesField.value || '') : '';

  // Check suppression and deferral
  if (checkSuppression(notesText).suppress) {
    actions.push({ name, status: 'SKIPPED', reason: 'Suppressed (lead will contact us)' });
    return;
  }
  if (checkDeferredFollowUp(notesText).deferred) {
    actions.push({ name, status: 'SKIPPED', reason: 'Deferred (future follow-up date)' });
    return;
  }

  // Get messages
  const messages = await getMessages(contactId);

  const SYSTEM_TYPES = new Set([28, 31, '28', '31']);
  const isReal = (m) => {
    const type = m.type ?? m.messageType;
    if (SYSTEM_TYPES.has(type)) return false;
    if (type === 1 || type === '1') return true;
    return !!(m.body?.trim());
  };

  const outbound = messages.filter(m => m.direction === 'outbound' && isReal(m));
  const inbound = messages.filter(m => m.direction === 'inbound' && isReal(m));

  // Check: has there been any outbound recently?
  const lastOut = outbound.length > 0 ? outbound[outbound.length - 1] : null;
  const lastOutDate = lastOut ? new Date(lastOut.dateAdded) : null;
  const daysSinceOut = lastOutDate ? Math.floor((today - lastOutDate) / (1000 * 60 * 60 * 24)) : 999;

  if (daysSinceOut < STEP_GAPS[1]) {
    actions.push({ name, status: 'SKIPPED', reason: `Outbound ${daysSinceOut}d ago (< ${STEP_GAPS[1]}d)` });
    return;
  }

  // Check: did the lead respond since our last outbound? (means ISA needs to handle it, not us)
  const lastIn = inbound.length > 0 ? inbound[inbound.length - 1] : null;
  if (lastIn && lastOut && new Date(lastIn.dateAdded) > lastOutDate) {
    // Lead responded but ISA didn't reply - this IS a valid follow-up scenario
    // But we should be careful: if the lead's last message was very recent, give ISA time
    const daysSinceIn = Math.floor((today - new Date(lastIn.dateAdded)) / (1000 * 60 * 60 * 24));
    if (daysSinceIn < STEP_GAPS[1]) {
      actions.push({ name, status: 'SKIPPED', reason: `Lead responded ${daysSinceIn}d ago, giving ISA time` });
      return;
    }
  }

  // Determine step and check timing
  const tracked = tracker[contactId];
  const step = tracked ? tracked.step + 1 : 1;

  if (step > MAX_STEPS) {
    actions.push({ name, status: 'SKIPPED', reason: `Max ${MAX_STEPS} auto-followups reached` });
    return;
  }

  const requiredGap = STEP_GAPS[step] || STEP_GAPS[MAX_STEPS];
  if (tracked) {
    const daysSinceLastSend = Math.floor((today - new Date(tracked.lastSent)) / (1000 * 60 * 60 * 24));
    if (daysSinceLastSend < requiredGap) {
      actions.push({ name, status: 'SKIPPED', reason: `Auto-followup sent ${daysSinceLastSend}d ago (step ${step} needs ${requiredGap}d gap)` });
      return;
    }
  }

  // Generate message with Claude
  let smsText;
  try {
    smsText = await generateFollowUp(contact, messages, step, firstName);
  } catch (e) {
    actions.push({ name, status: 'ERROR', reason: `Claude error: ${e.message}` });
    return;
  }

  // Send or dry-run
  if (DRY_RUN) {
    actions.push({ name, status: 'DRY-RUN', step, message: smsText, daysSinceOut });
  } else {
    try {
      await sendSMS(contactId, smsText);
      tracker[contactId] = { lastSent: today.toISOString(), step, stageName: opp.pipelineStageId };
      actions.push({ name, status: 'SENT', step, message: smsText, daysSinceOut });
    } catch (e) {
      actions.push({ name, status: 'ERROR', reason: `Send failed: ${e.message}` });
    }
  }

  await delay(300); // Rate limiting between Claude + send calls
}

// ============================================
// REPORT
// ============================================

function generateSummary(stageActions) {
  const lines = [];
  const hr = '═'.repeat(60);
  const today = new Date();
  const dateStr = today.toLocaleDateString('en-CA', { timeZone: 'America/Toronto' });
  const timeStr = today.toLocaleTimeString('en-CA', { timeZone: 'America/Toronto', hour: '2-digit', minute: '2-digit' });

  lines.push(hr);
  lines.push(`  Auto Follow-Up Summary`);
  lines.push(`  ${dateStr} ${timeStr}${DRY_RUN ? ' [DRY RUN]' : ''}`);
  lines.push(hr);

  let totalSent = 0;
  let totalSkipped = 0;
  let totalErrors = 0;

  for (const { stage, actions } of stageActions) {
    const sent = actions.filter(a => a.status === 'SENT' || a.status === 'DRY-RUN');
    const skipped = actions.filter(a => a.status === 'SKIPPED');
    const errors = actions.filter(a => a.status === 'ERROR');
    totalSent += sent.length;
    totalSkipped += skipped.length;
    totalErrors += errors.length;

    if (actions.length === 0) continue;

    lines.push('');
    lines.push(`  ${stage.name}`);
    lines.push(`  ${'─'.repeat(50)}`);

    for (const a of sent) {
      lines.push(`  [${a.status}] ${a.name} (step ${a.step}, ${a.daysSinceOut}d inactive)`);
      lines.push(`    MSG: "${a.message}"`);
    }
    for (const a of errors) {
      lines.push(`  [ERROR] ${a.name}: ${a.reason}`);
    }
    if (skipped.length > 0) {
      lines.push(`  Skipped: ${skipped.length} leads`);
    }
  }

  lines.push('');
  lines.push(hr);
  lines.push(`  Total: ${totalSent} sent, ${totalSkipped} skipped, ${totalErrors} errors`);
  lines.push(hr);

  return lines.join('\n');
}

async function sendSummaryEmail(summaryText) {
  const transporter = createTransport({
    host: process.env.EMAIL_SMTP_HOST,
    port: parseInt(process.env.EMAIL_SMTP_PORT),
    secure: false,
    auth: { user: process.env.EMAIL_SMTP_USER, pass: process.env.EMAIL_SMTP_PASSWORD },
  });

  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Toronto' });
  const escaped = summaryText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  body { font-family: 'Courier New', monospace; background: #f5f5f5; padding: 20px; color: #333; }
  .report { background: white; border-radius: 8px; padding: 30px; max-width: 900px; margin: 0 auto; }
  .header { background: #759b8f; color: white; padding: 20px 30px; border-radius: 8px 8px 0 0; margin: -30px -30px 20px; }
  .header h1 { margin: 0; font-size: 18px; }
  pre { white-space: pre-wrap; font-size: 12px; line-height: 1.5; }
</style></head><body>
<div class="report">
  <div class="header"><h1>Auto Follow-Up Summary</h1><p>${today}</p></div>
  <pre>${escaped}</pre>
</div></body></html>`;

  await transporter.sendMail({
    from: `"Nurture Auto Follow-Up" <${process.env.EMAIL_SMTP_USER}>`,
    to: process.env.EMAIL_NOTIFY_TO,
    cc: 'success@nurtre.io, angelica@nurtre.io',
    subject: `Auto Follow-Up Summary - ${today}${DRY_RUN ? ' [DRY RUN]' : ''}`,
    text: summaryText,
    html,
  });
}

// ============================================
// MAIN
// ============================================

async function main() {
  console.log(`GHL Auto Follow-Up ${DRY_RUN ? '[DRY RUN]' : '[LIVE]'}`);

  // Time window guard: only send between 10:30 AM and 6:00 PM EST
  const nowEST = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Toronto' }));
  const hour = nowEST.getHours();
  const minute = nowEST.getMinutes();
  const currentMinutes = hour * 60 + minute; // minutes since midnight
  const windowOpen = 10 * 60 + 30;  // 10:30 AM = 630 minutes
  const windowClose = 18 * 60;       // 6:00 PM = 1080 minutes

  if (!DRY_RUN && (currentMinutes < windowOpen || currentMinutes >= windowClose)) {
    const timeStr = nowEST.toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit' });
    console.log(`Outside send window (10:30 AM - 6:00 PM EST). Current time: ${timeStr}. Exiting.`);
    return;
  }

  // Random delay so messages don't always go out at the same time each day.
  // Waits 0 to 210 minutes (3.5 hours), keeping sends within the 10:30 AM - 2:00 PM range.
  if (!DRY_RUN) {
    const delayMinutes = Math.floor(Math.random() * 210);
    const delayMs = delayMinutes * 60 * 1000;
    const sendTime = new Date(nowEST.getTime() + delayMs);
    const sendTimeStr = sendTime.toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit' });
    console.log(`Random delay: ${delayMinutes} minutes. Messages will send around ${sendTimeStr} EST.`);
    await delay(delayMs);
  }

  console.log('Loading tracker...');

  const tracker = loadTracker();
  const today = new Date();
  const stageActions = [];

  for (const stage of TARGET_STAGES) {
    process.stdout.write(`\n${stage.name}...`);
    const opportunities = await getStageOpportunities(stage.id);
    console.log(` ${opportunities.length} leads`);
    await delay(200);

    const actions = [];
    for (let i = 0; i < opportunities.length; i++) {
      const opp = opportunities[i];
      const name = opp.contact?.name || opp.name || 'Unknown';
      process.stdout.write(`  ${i + 1}/${opportunities.length} ${name}...`);

      await processLead(opp, tracker, today, actions);

      const last = actions[actions.length - 1];
      console.log(` ${last?.status || 'OK'}`);

      // Stagger sends: wait 5 minutes after each actual send so messages look natural
      if (last?.status === 'SENT') {
        console.log('    Waiting 5 minutes before next send...');
        await delay(5 * 60 * 1000);
      } else {
        await delay(200);
      }
    }

    stageActions.push({ stage, actions });
  }

  // Save tracker
  if (!DRY_RUN) saveTracker(tracker);

  // Generate and print summary
  const summary = generateSummary(stageActions);
  console.log('\n' + summary);

  // Save daily actions to JSON for the 6 PM summary email
  const dailyLogPath = new URL('./followup-daily-log.json', import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1');
  const todayKey = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Toronto' });
  let dailyLog = {};
  try { if (existsSync(dailyLogPath)) dailyLog = JSON.parse(readFileSync(dailyLogPath, 'utf-8')); } catch (e) { /* ignore */ }

  // Flatten actions with stage name for the summary emailer
  const todayActions = [];
  for (const { stage, actions } of stageActions) {
    for (const a of actions) {
      todayActions.push({ ...a, stageName: stage.name });
    }
  }
  dailyLog[todayKey] = todayActions;

  // Clean entries older than 7 days
  const cutoff = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toLocaleDateString('en-CA', { timeZone: 'America/Toronto' });
  for (const key of Object.keys(dailyLog)) { if (key < cutoff) delete dailyLog[key]; }
  writeFileSync(dailyLogPath, JSON.stringify(dailyLog, null, 2));
  console.log(`Daily log saved to ${dailyLogPath}`);
}

main().catch(e => console.error('Fatal:', e.message));
