# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm run dev      # Start dev server at localhost:4321
npm run build    # Build production site to ./dist/
npm run preview  # Preview production build locally
```

## Architecture

This is a static marketing website for Nurture (nurturestays.ca), an Airbnb property management company in Toronto/GTA. Built with Astro 5.

### Structure

- `src/layouts/Layout.astro` - Base HTML layout with Header/Footer, meta tags, Google Fonts (DM Sans, Poppins)
- `src/components/` - Header.astro, Footer.astro
- `src/styles/global.css` - CSS variables for brand colors, utility classes, responsive breakpoints
- `src/pages/` - File-based routing, each .astro file becomes a page

### Brand Colors (CSS Variables)

- Primary: `#759b8f` (sage green)
- Primary dark: `#5a7d73`
- Accent: `#d4a373` (warm tan)
- Background: `#FFFDF9` (warm white)
- Background alt: `#F8F6F1` (cream)

### Page Patterns

Service pages follow a consistent structure:
1. Hero section with `hero-small` class
2. Trust bar with stats
3. Content sections alternating white/cream backgrounds
4. FAQ section
5. Related services grid
6. CTA section with phone number

Each page defines its own scoped styles within `<style>` tags. Data arrays (packages, FAQs, steps) are defined in the frontmatter.

## Deployment

Changes pushed to `master` branch auto-deploy to production (GitHub → hosting provider).

---

## SEO Guidelines: The 3 Kings

When creating blog articles, ALWAYS optimize these three elements for the target keyword:

### 1. Meta Title (pageTitle)
- **Keep under 60 characters** to avoid truncation in search results
- **Put focus keyword first** (e.g., "Oakville Airbnb Rules" not "Guide to Oakville...")
- Format: `[City] Airbnb [Rules/Regulations] 2026 | [Hook]`
- Example: `Ottawa Airbnb Short Term Rental Rules 2026`

### 2. Meta Description (pageDescription)
- **Keep between 150-160 characters**
- **Include focus keyword naturally** (don't stuff)
- **End with a CTA** (Get licensed now, Start hosting today, Get compliant now)
- Formula: `[Key requirements] + [Differentiator] + [CTA]`
- Example: `Ottawa Airbnb rules: principal residence required, $123 permit, 4% MAT, plus cottage exception for rural zones. Your complete 2026 compliance guide.`

### 3. H1 Title (main heading)
- **Match or closely align with meta title**
- **Clear and keyword-focused** - visitors should know what the page is about in 2 seconds
- Don't try to be clever - be crystal clear

### Common Mistakes to Avoid
- **Keyword stuffing** - Don't repeat keyword endlessly
- **Duplicate titles/descriptions** - Every page needs unique meta
- **Being vague** - "Welcome to Our Website" helps no one
- **Missing CTAs** - Always include action words in descriptions

### Blog Article Structure
Each blog guide should include:
1. `pageTitle` - Meta title (under 60 chars, keyword first)
2. `pageDescription` - Meta description (150-160 chars with CTA)
3. `faqs` array - For FAQ schema (targets long-tail keywords)
4. `tocItems` - Table of contents for UX
5. `relatedPosts` - Internal linking to related content
6. `articleSchema` + `faqSchema` - Structured data for rich results

---

## Writing Guidelines

### Punctuation Rules
**Never use spaced hyphens ( - ) in paragraph content.** This is a common informal writing habit that looks unprofessional.

Instead of hyphens, use:
- **Commas** for clauses that add information: "your principal residence, where you normally live"
- **Periods** to start a new sentence: "The appeal extends beyond leisure. Major employers draw business travelers."
- **Colons** for lists or explanations: "Here's what you need: license, insurance, registration"
- **"and" or "or"** to connect ideas: "how much you could earn and how to maximize nights"

**Bad examples:**
- "could earn on Airbnb - with no hassles" ❌
- "principal residence - where you live" ❌
- "get started - before regulations change" ❌

**Good examples:**
- "could earn on Airbnb, with no hassles" ✓
- "principal residence, where you live" ✓
- "get started before regulations change" ✓

**Exceptions (hyphens are OK):**
- Compound words: "short-term", "full-service", "year-round"
- Headings with labels: "License Required: $237/Year"
- Code comments and CSS
- Page titles with separators: "Oakville Airbnb Management | GTA"

---

# Nurture - Airbnb Property Management

## Company Overview
- **Company Name:** Nurture (stylized as "Nurture" - NOT "Nurtre")
- **Website:** https://www.nurturestays.ca/
- **Phone:** (647) 957-8956
- **Address:** 140 Simcoe St, Toronto, ON M5H 4E9
- **Tagline:** "Earn 30-100% More by Switching to Airbnb"

## What We Do
Premium Airbnb management in the Greater Toronto Area. We help GTA homeowners maximize their rental income through expert Airbnb management - from listing optimization to guest communication.

## Key Stats & Differentiators
- 4.9? Average Airbnb Rating
- 9 minute average response time
- 10-15% management fee (competitors charge 18-25%)
- No long-term contracts
- Clients own their listings (no hostage situations)
- Direct owner contact (not group chats)
- Locally owned in GTA
- No startup costs - commission only
- No markup on supply restocking
- First booking within 1 week on average


## Services Offered

### Management
- Full Airbnb Management
- Short-Term Rental Management
- Mid-Term Rental Management
- Airbnb Co-Hosting

### Marketing
- Dynamic Pricing & Revenue Optimization
- Listing Optimization & SEO
- Multi-platform distribution

### Operations
- Professional Cleaning Coordination
- Turnover Management
- Key Exchange / Smart Lock Management
- Property Maintenance
- Professional Photography
- Supply Restocking & Inventory
- Linen management

### Guest Services
- Guest Communication & Support
- Guest Screening & Verification
- Review Management
- On-site support when needed

## Pricing

### Starter Plan - 10%
- Professional listing creation
- Multi-platform distribution
- Dynamic pricing optimization
- Guest communication
- Guest vetting & screening
- Review management

### Professional Plan - 15%
Everything in Starter, plus:
- Professional cleaning coordination
- Linen & supply restocking
- Smart lock management
- Dedicated account manager
- Insurance claim assistance

## Value Proposition
Most see 30-100% increases in monthly revenue."

## Client Results Example
1-Bedroom Condo in GTA:
- BEFORE: -$926/month cashflow (long-term rental)
- AFTER: +$847/month cashflow (Airbnb with Nurture)
- Result: 87% increase in first month

## Brand Voice
@docs/brand-voice.md

## Competitor overview
@docs/Competitoranalysis

## Bylaws - GTA Core Markets

### Toronto (All Boroughs)
@docs/bylaws/toronto short term rental bylaw.pdf
- 180 nights/year (entire home), unlimited (partial)
- Principal residence only
- Registration required
- 8.5% MAT tax

### Mississauga
@docs/bylaws/Mississauga short term rental bylaw.pdf
- 180 days/year limit
- Principal residence only
- License: $283/year
- Penalties up to $100K

### Brampton
@docs/bylaws/brampton bylaw.txt
- 180 days/year limit
- Principal residence only
- Max 3 bedrooms rented individually
- 4% MAT

### Vaughan
@docs/bylaws/vaughan bylaw.pdf
- 29 consecutive days or less = STR
- Principal residence only
- License required + MAT registration
- 4% MAT

### Hamilton
@docs/bylaws/hamilton bylaw.txt
- Principal residence only
- License: $200-$1,000
- $2M liability insurance required
- License valid 2 years

### Oakville
@docs/bylaws/oakville STR bylaw.pdf
- 28 consecutive days or less = STR
- Principal residence required
- License: $237/year
- 4% MAT

## Bylaws - Niagara Region

### Niagara Falls
@docs/bylaws/Niagara falls bylaw.txt
- VRU (Vacation Rental Unit) license required
- Zoning restricted (Tourist/Commercial zones only)
- License: $500 initial, $250 renewal
- $2/night MAT

### Niagara-on-the-Lake
@docs/bylaws/niagara on the lake bylaw.txt
- License required
- Processing time: up to 10 weeks

### St. Catharines
@docs/bylaws/st. catherines bylaw.txt
- By-law 2021-67
- Principal residence required
- 4% MAT

## Bylaws - Cottage Country

### Muskoka Lakes
@docs/bylaws/Muskoka bylaw.txt
- Effective January 1, 2025
- License: $1,000/year
- 2 persons per bedroom max
- Demerit point system

### Huntsville
@docs/bylaws/Huntsville bylaw.pdf
- Principal residence or 2 bedrooms in primary home
- Secondary units NOT permitted for STR

## Bylaws - Other Ontario

### Ottawa
@docs/bylaws/Ottawa bylaw.txt
- Under 30 consecutive nights
- Principal residence required
- Permit: $112/2 years
- 4% MAT

### London
@docs/bylaws/London bylaw.txt
- 29 days or less = STR
- Principal residence required
- License: $196/year
- 4% MAT

### Waterloo
@docs/bylaws/waterloo bylaw.txt
- Effective January 2025
- Principal residence required (low-rise)
- License required

### Sault Ste. Marie
@docs/bylaws/sault ste marie bylaw.pdf
- License: $500/year
- 4% MAT
- No principal residence requirement

## Bylaws - Summary Reference
@docs/bylaws/ontario-str-bylaws-summary.md
- Comprehensive summary of 70+ Ontario municipalities
- Quick reference tables
- Official links

---

# Quick Reference

## Common Client Questions

**Q: Can I Airbnb my investment property?**
A: Most GTA cities (Toronto, Mississauga, Brampton, Vaughan, Hamilton, Oakville) require STRs to be your principal residence. Investment properties generally cannot be used for short-term rentals. Mid-term rentals (30+ days) are often an alternative.

**Q: What's the night limit in Toronto?**
A: 180 nights/year for entire home rentals. Unlimited for partial unit (renting rooms while you're home).


## Important Notes
- Always verify bylaws directly with municipality before listing
- Condo corporations can prohibit STRs even if city allows
- Regulations change frequently - check for updates
- Mid-term rentals (30+ days) often exempt from STR rules


