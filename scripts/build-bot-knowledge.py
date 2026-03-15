"""
Build Bot Knowledge Base
Compiles CLAUDE.md + blog FAQs + service page content into a single
bot-knowledge.md file that the FB Messenger bot fetches at runtime.

Run weekly via Task Scheduler or manually:
  python scripts/build-bot-knowledge.py
"""

import os
import re
import glob
import logging
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_MD = os.path.join(ROOT, 'CLAUDE.md')
BLOG_DIR = os.path.join(ROOT, 'src', 'pages', 'blog')
CONTENT_DIR = os.path.join(ROOT, 'src', 'content', 'blog')
OUTPUT = os.path.join(ROOT, 'ghl-claude-server', 'bot-knowledge.md')
LOG_FILE = os.path.join(ROOT, 'scripts', 'build-bot-knowledge-log.txt')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def extract_faqs_from_astro(filepath):
    """Extract FAQ questions and answers from an .astro blog file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return []

    faqs = []
    # Match faq objects: { q: "...", a: "..." } or { q: '...', a: '...' }
    pattern = r"""\{\s*q:\s*['"`](.*?)['"`]\s*,\s*a:\s*['"`](.*?)['"`]\s*\}"""
    for m in re.finditer(pattern, content, re.DOTALL):
        q = m.group(1).strip().replace('\\n', ' ')
        a = m.group(2).strip().replace('\\n', ' ')
        if q and a:
            faqs.append((q, a))

    return faqs


def extract_page_meta(filepath):
    """Extract pageTitle and pageDescription from an .astro file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None, None

    title = None
    desc = None

    t = re.search(r'const\s+pageTitle\s*=\s*[\'"`](.*?)[\'"`]', content)
    if t:
        title = t.group(1)

    d = re.search(r'const\s+pageDescription\s*=\s*[\'"`](.*?)[\'"`]', content)
    if d:
        desc = d.group(1)

    return title, desc


def extract_markdown_meta(filepath):
    """Extract title and description from a markdown blog file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None, None

    title = None
    desc = None

    t = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', content, re.MULTILINE)
    if t:
        title = t.group(1).strip()

    d = re.search(r'^description:\s*["\']?(.*?)["\']?\s*$', content, re.MULTILINE)
    if d:
        desc = d.group(1).strip()

    return title, desc


def build_blog_summary():
    """Build a summary of all blog articles with their FAQs."""
    sections = []
    faq_count = 0
    article_count = 0

    # Process .astro blog files
    astro_files = glob.glob(os.path.join(BLOG_DIR, '*.astro'))
    for fp in sorted(astro_files):
        fname = os.path.basename(fp)
        if fname in ('index.astro', '[slug].astro', '[...slug].astro'):
            continue

        slug = fname.replace('.astro', '')
        title, desc = extract_page_meta(fp)
        faqs = extract_faqs_from_astro(fp)

        if not title:
            continue

        article_count += 1
        entry = f"### {title}\n"
        entry += f"URL: nurturestays.ca/blog/{slug}\n"
        if desc:
            entry += f"Summary: {desc}\n"

        if faqs:
            entry += "\nFAQs:\n"
            for q, a in faqs:
                # Truncate long answers for the knowledge base
                short_a = a if len(a) <= 300 else a[:297] + '...'
                entry += f"Q: {q}\nA: {short_a}\n\n"
                faq_count += 1

        sections.append(entry)

    # Process markdown blog files
    md_files = glob.glob(os.path.join(CONTENT_DIR, '*.md'))
    for fp in sorted(md_files):
        title, desc = extract_markdown_meta(fp)
        if not title:
            continue

        slug = os.path.basename(fp).replace('.md', '')
        article_count += 1
        entry = f"### {title}\n"
        entry += f"URL: nurturestays.ca/blog/{slug}\n"
        if desc:
            entry += f"Summary: {desc}\n"
        sections.append(entry)

    log.info(f"Processed {article_count} blog articles, {faq_count} FAQs")
    return '\n'.join(sections)


def extract_claude_md_sections():
    """Extract key sections from CLAUDE.md for the bot."""
    try:
        with open(CLAUDE_MD, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        log.error(f"Could not read CLAUDE.md: {e}")
        return ""

    # Extract sections we want: Company Overview, Services, Pricing, Stats, Bylaws
    # Skip: Commands, Architecture, Deployment, SEO Guidelines, Blog Checklist, Writing Guidelines
    skip_sections = [
        '## Commands', '## Architecture', '## Deployment', '## SEO Guidelines',
        '## Blog Publishing Checklist', '## Writing Guidelines', '### Structure',
        '### Brand Colors', '### Page Patterns', '### Schema', '### Blog Article Structure',
        '### Common Mistakes'
    ]

    lines = content.split('\n')
    output_lines = []
    skip = False

    for line in lines:
        # Check if we're entering a section to skip
        if any(line.strip().startswith(s) for s in skip_sections):
            skip = True
            continue

        # Check if we're entering a new section (stop skipping)
        if skip and (line.startswith('## ') or line.startswith('# ')):
            skip = False

        if not skip:
            output_lines.append(line)

    return '\n'.join(output_lines)


def build_knowledge():
    """Build the complete knowledge base file."""
    log.info("Building bot knowledge base...")

    parts = []

    # Header
    parts.append(f"# Nurture Bot Knowledge Base")
    parts.append(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    parts.append(f"Auto-generated by build-bot-knowledge.py. Do not edit manually.\n")

    # Company knowledge from CLAUDE.md
    parts.append("## Company Knowledge\n")
    claude_content = extract_claude_md_sections()
    if claude_content:
        parts.append(claude_content)
    else:
        parts.append("(Could not load CLAUDE.md)")

    # Blog articles and FAQs
    parts.append("\n## Blog Articles & FAQs\n")
    parts.append("When a lead asks a question covered by a blog article, answer it and mention we have a detailed guide: nurturestays.ca/blog/[slug]\n")
    blog_summary = build_blog_summary()
    if blog_summary:
        parts.append(blog_summary)
    else:
        parts.append("(No blog articles found)")

    full_content = '\n'.join(parts)

    # Write output
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write(full_content)

    size_kb = len(full_content.encode('utf-8')) / 1024
    log.info(f"Knowledge base written to {OUTPUT} ({size_kb:.1f} KB)")

    return full_content


if __name__ == '__main__':
    build_knowledge()
