/**
 * Local FAQ Schema Generator
 *
 * Generates SEO-optimized FAQ content with JSON-LD schema for local search.
 * Uses Claude to write answers tailored to your market and business.
 *
 * Usage:
 *   node scripts/faq-schema-generator.mjs "airbnb management toronto"
 *   node scripts/faq-schema-generator.mjs "short term rental mississauga" --output faq-mississauga.json
 */

import Anthropic from '@anthropic-ai/sdk';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

// Load .env from project root
const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '..', '.env') });

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

// Company context for generating answers
const COMPANY_CONTEXT = `
You are writing FAQ answers for Nurture (nurturestays.ca), a premium Airbnb property management company in Toronto and the Greater Toronto Area.

## Company Info
- Company: Nurture
- Website: nurturestays.ca
- Phone: (647) 957-8956
- Address: 140 Simcoe St, Toronto, ON M5H 4E9
- Service Area: Toronto, Mississauga, Brampton, Vaughan, Oakville, Hamilton, and surrounding GTA

## Key Stats
- 4.9 Average Airbnb Rating
- 9 minute average response time
- 10 to 15% management fee (competitors charge 18 to 25%)
- No long term contracts
- First booking within 1 week average

## Services
- Full Airbnb management
- Dynamic pricing optimization
- Professional cleaning coordination
- Guest communication (24/7)
- Listing optimization
- Professional photography
- Smart lock management

## Key Differentiators
- Clients own their listings (not hostage to us)
- No startup costs, commission only
- Locally owned, not a big corporation
- Direct owner contact, not group chats
- 30 to 100% income increase typical

## Brand Voice
- Professional but approachable
- Confident without being arrogant
- Helpful and educational
- Local expertise emphasized
- Never use unnecessary hyphens
`;

// Common local SEO questions by category
const FAQ_TEMPLATES = {
  general: [
    "What is Airbnb management?",
    "How much do Airbnb management companies charge?",
    "Is it worth hiring an Airbnb manager?",
    "What do Airbnb property managers do?",
    "How do I choose an Airbnb management company?",
  ],
  location: [
    "Is Airbnb legal in {location}?",
    "What are the short term rental rules in {location}?",
    "How much can I make on Airbnb in {location}?",
    "Do I need a license for Airbnb in {location}?",
    "What is the Airbnb occupancy rate in {location}?",
  ],
  pricing: [
    "How much does Airbnb management cost in {location}?",
    "What is the average Airbnb management fee?",
    "Are there hidden fees with Airbnb managers?",
    "Do Airbnb managers charge startup fees?",
    "What is included in Airbnb management fees?",
  ],
  comparison: [
    "Airbnb vs long term rental in {location}: which is better?",
    "How much more can I make with Airbnb vs renting?",
    "Should I do Airbnb myself or hire a manager?",
    "What are the pros and cons of Airbnb management?",
  ],
  process: [
    "How do I get started with Airbnb management?",
    "How long does it take to list on Airbnb?",
    "What do I need to provide for Airbnb management?",
    "How often will my property be rented?",
    "How do I get paid from Airbnb management?",
  ],
};

async function generateFAQAnswer(question, location) {
  const prompt = `Generate an SEO-optimized FAQ answer for a local Airbnb management company.

Question: "${question}"
Target Location: ${location}

Requirements:
1. Answer should be 2 to 4 sentences (50 to 150 words ideal for featured snippets)
2. Include the location naturally if relevant
3. Be helpful and informative, not salesy
4. Include a specific stat or fact when possible
5. Write in a friendly, authoritative tone
6. Do NOT use hyphens unnecessarily (write "short term" not "short-term")
7. End with a subtle value add or next step when appropriate

Write the answer now:`;

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 300,
    system: COMPANY_CONTEXT,
    messages: [{ role: 'user', content: prompt }],
  });

  return response.content[0].text.trim();
}

async function generateFAQs(keyword, options = {}) {
  const location = extractLocation(keyword) || 'Toronto';
  const outputFile = options.output || `faq-${location.toLowerCase().replace(/\s+/g, '-')}.json`;

  console.log(`\nGenerating FAQs for: "${keyword}"`);
  console.log(`Location: ${location}`);
  console.log(`Output: ${outputFile}\n`);

  const faqs = [];
  const allQuestions = [];

  // Collect all questions, replacing {location} placeholder
  for (const [category, questions] of Object.entries(FAQ_TEMPLATES)) {
    for (const q of questions) {
      allQuestions.push({
        category,
        question: q.replace(/{location}/g, location),
      });
    }
  }

  console.log(`Generating ${allQuestions.length} FAQ answers...\n`);

  for (let i = 0; i < allQuestions.length; i++) {
    const { category, question } = allQuestions[i];
    console.log(`[${i + 1}/${allQuestions.length}] ${question}`);

    try {
      const answer = await generateFAQAnswer(question, location);
      faqs.push({
        category,
        question,
        answer,
      });
      console.log(`   ✓ Generated\n`);

      // Small delay to avoid rate limits
      await new Promise(resolve => setTimeout(resolve, 500));
    } catch (error) {
      console.error(`   ✗ Error: ${error.message}\n`);
    }
  }

  // Generate JSON-LD schema
  const schema = generateJSONLDSchema(faqs);

  // Generate HTML snippet
  const htmlSnippet = generateHTMLSnippet(faqs);

  // Generate Astro component
  const astroComponent = generateAstroComponent(faqs, location);

  const output = {
    metadata: {
      keyword,
      location,
      generatedAt: new Date().toISOString(),
      totalFAQs: faqs.length,
    },
    faqs,
    schema,
    htmlSnippet,
    astroComponent,
  };

  // Save to file
  const outputPath = path.join(__dirname, outputFile);
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));
  console.log(`\n✓ Saved to ${outputPath}`);

  // Also output the schema for easy copy/paste
  console.log('\n========== JSON-LD SCHEMA (copy to your page) ==========\n');
  console.log(JSON.stringify(schema, null, 2));
  console.log('\n=========================================================\n');

  return output;
}

function generateJSONLDSchema(faqs) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": faqs.map(faq => ({
      "@type": "Question",
      "name": faq.question,
      "acceptedAnswer": {
        "@type": "Answer",
        "text": faq.answer,
      },
    })),
  };
}

function generateHTMLSnippet(faqs) {
  const schemaScript = `<script type="application/ld+json">
${JSON.stringify(generateJSONLDSchema(faqs), null, 2)}
</script>`;

  const faqHTML = faqs.map(faq => `
<div class="faq-item" itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
  <h3 itemprop="name">${faq.question}</h3>
  <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
    <p itemprop="text">${faq.answer}</p>
  </div>
</div>`).join('\n');

  return `<!-- FAQ Schema -->
${schemaScript}

<!-- FAQ HTML -->
<section class="faq-section">
  <h2>Frequently Asked Questions</h2>
  ${faqHTML}
</section>`;
}

function generateAstroComponent(faqs, location) {
  const faqData = JSON.stringify(faqs, null, 2);

  return `---
// FAQSection-${location}.astro
// Auto-generated FAQ component with JSON-LD schema

const faqs = ${faqData};

const schema = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": faqs.map(faq => ({
    "@type": "Question",
    "name": faq.question,
    "acceptedAnswer": {
      "@type": "Answer",
      "text": faq.answer,
    },
  })),
};
---

<section class="faq-section">
  <div class="container">
    <h2>Frequently Asked Questions</h2>
    <div class="faq-grid">
      {faqs.map((faq) => (
        <details class="faq-item">
          <summary>{faq.question}</summary>
          <p>{faq.answer}</p>
        </details>
      ))}
    </div>
  </div>
</section>

<script type="application/ld+json" set:html={JSON.stringify(schema)} />

<style>
  .faq-section {
    padding: 4rem 0;
    background: var(--background-alt);
  }

  .faq-section h2 {
    text-align: center;
    margin-bottom: 2rem;
  }

  .faq-grid {
    max-width: 800px;
    margin: 0 auto;
  }

  .faq-item {
    background: white;
    border-radius: 8px;
    margin-bottom: 1rem;
    padding: 1rem 1.5rem;
    cursor: pointer;
  }

  .faq-item summary {
    font-weight: 600;
    list-style: none;
  }

  .faq-item summary::-webkit-details-marker {
    display: none;
  }

  .faq-item[open] summary {
    margin-bottom: 0.5rem;
  }

  .faq-item p {
    color: var(--text-secondary);
    line-height: 1.6;
  }
</style>
`;
}

function extractLocation(keyword) {
  const locations = [
    'Toronto', 'Mississauga', 'Brampton', 'Vaughan', 'Oakville',
    'Hamilton', 'Burlington', 'Milton', 'Markham', 'Richmond Hill',
    'Scarborough', 'Etobicoke', 'North York', 'GTA', 'Greater Toronto Area'
  ];

  const keywordLower = keyword.toLowerCase();
  for (const loc of locations) {
    if (keywordLower.includes(loc.toLowerCase())) {
      return loc;
    }
  }
  return null;
}

// CLI handling
const args = process.argv.slice(2);
if (args.length === 0) {
  console.log(`
FAQ Schema Generator for Local SEO

Usage:
  node scripts/faq-schema-generator.mjs "your keyword" [options]

Examples:
  node scripts/faq-schema-generator.mjs "airbnb management toronto"
  node scripts/faq-schema-generator.mjs "short term rental mississauga" --output faq-miss.json

Options:
  --output, -o    Output filename (default: faq-{location}.json)
`);
  process.exit(0);
}

const keyword = args[0];
const outputIndex = args.indexOf('--output') !== -1 ? args.indexOf('--output') : args.indexOf('-o');
const output = outputIndex !== -1 ? args[outputIndex + 1] : undefined;

generateFAQs(keyword, { output }).catch(console.error);
