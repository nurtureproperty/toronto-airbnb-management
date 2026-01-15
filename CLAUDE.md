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
