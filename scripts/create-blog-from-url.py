#!/usr/bin/env python3
"""
Create Blog Post from URL - Nurture Airbnb Property Management

This script creates and publishes a blog post from a specific article URL.
An email notification is sent when posts are published.

Usage:
    python scripts/create-blog-from-url.py "https://example.com/article"
    python scripts/create-blog-from-url.py "url1" "url2" "url3"

Environment Variables Required:
    ANTHROPIC_API_KEY - Your Anthropic API key
    EMAIL_SMTP_HOST - SMTP server (e.g., smtp.gmail.com)
    EMAIL_SMTP_PORT - SMTP port (e.g., 587)
    EMAIL_SMTP_USER - SMTP username/email
    EMAIL_SMTP_PASSWORD - SMTP password or app password
    EMAIL_NOTIFY_TO - Email address to send notifications to
"""

import os
import sys
import json
import hashlib
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import anthropic
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
POSTS_DIR = PROJECT_ROOT / "src" / "content" / "blog"
PROCESSED_FILE = SCRIPT_DIR / "processed_articles.json"
SITE_URL = "https://www.nurturestays.ca"

# Blog post generation prompt (same as blog-generator.py)
BLOG_PROMPT_TEMPLATE = """You are a content writer for Nurture, a premium Airbnb property management company serving the Greater Toronto Area. Your job is to write blog posts that help GTA property owners understand short-term rental news and how it affects them.

IMPORTANT WRITING RULES (follow these exactly to avoid AI detection):

PUNCTUATION:
1. NEVER use em dashes (the long dash). Use commas, periods, or parentheses instead.
2. Avoid semicolons in casual content. Break into two sentences instead.
3. Use contractions naturally (don't, won't, it's, we're, you'll, that's, here's)

BANNED WORDS (never use these AI-typical words):
- delve, dive into, navigate, landscape, realm
- crucial, vital, essential, key (overused)
- leverage, utilize (use "use" instead)
- robust, comprehensive, streamline, optimize
- game-changer, cutting-edge, revolutionary, innovative
- multifaceted, synergy, paradigm, holistic
- world-class, top-notch, best-in-class, state-of-the-art

BANNED PHRASES:
- "In today's world", "In this day and age"
- "It's important to note", "It's worth mentioning"
- "Firstly", "Secondly", "Lastly"
- "In conclusion", "To sum up", "In summary"
- "When it comes to", "At the end of the day"
- "Moving forward", "Going forward"

TONE AND STYLE:
1. Write like you're explaining to a friend over coffee
2. Use short, punchy sentences mixed with longer ones. Vary your rhythm.
3. Start some sentences with "And" or "But" for natural flow
4. Add casual transitions: "Here's the thing," "Look," "Honestly," "So," "Now,"
5. Include rhetorical questions ("So what does this mean for your rental?")
6. Add personal opinions ("This is great news" or "I'm not convinced this will work")
7. Reference specific Toronto neighborhoods, GTA landmarks, Ontario details
8. Throw in slightly imperfect phrasing. Real humans don't write perfectly.

STRUCTURE:
1. Skip generic intros. Get to the point in the first sentence.
2. Vary paragraph lengths. Some short (1-2 sentences), some longer.
3. End sections with specific, actionable advice
4. Cite specific facts, numbers, and dates from the source
5. End with a natural CTA, not a forced sales pitch

COMPANY INFO:
- Company name: Nurture (stylized exactly as "Nurture")
- Website: nurturestays.ca
- Phone: (647) 957-8956
- Location: Toronto, serving all of GTA
- Services: Full Airbnb management, short-term rental management, mid-term rental management
- Fees: 10-15% (competitors charge 18-25%)
- Key differentiator: No long contracts, you own your listing, local GTA expertise

INTERNAL LINKS TO INCLUDE (use 2-3 naturally where relevant):
- /services/short-term-rental-management-toronto - for STR management mentions
- /services/mid-term-rental-management-toronto - for mid-term rental mentions
- /full-airbnb-management-toronto - for full-service management mentions (NOTE: this is a root-level page, not under /services/)
- /pricing-toronto-airbnb-management - when discussing costs or fees
- /contact - for CTAs

TARGET KEYWORDS (work in naturally, don't force):
- Toronto Airbnb
- GTA short term rental
- Ontario STR regulations
- Airbnb management Toronto
- short term rental management GTA

SOURCE ARTICLE TO ANALYZE:
Title: {article_title}
Source: {article_source}
URL: {article_url}
Published: {article_date}

Full Article Content:
{article_content}

---

Based on the source article above, write a blog post that:
1. Has a unique angle relevant to GTA property owners (not just a summary)
2. Includes practical takeaways Airbnb hosts can act on
3. Is 600-900 words
4. References specific facts and quotes from the source article
5. Ends with a CTA mentioning Nurture can help

TITLE REQUIREMENTS:
- Create a UNIQUE, SPECIFIC title based on the article's main topic
- NEVER use generic titles like "What GTA Airbnb Hosts Need to Know" or "What Toronto Hosts Should Know"
- Use varied title formats: questions, how-to, numbers, direct statements
- Examples of GOOD titles: "Toronto Rent Drops to Lowest Point Since 2022", "5 New Airbnb Rules Coming to Ontario in 2026", "Why Your Airbnb Photos Aren't Converting"
- Examples of BAD titles: "What GTA Hosts Need to Know About X", "Important Update for Toronto Airbnb Hosts"

OUTPUT FORMAT (use exactly this format):
---
title: "[UNIQUE title based on article topic, 50-60 chars, specific not generic]"
description: "[Meta description, 150-160 characters, compelling and includes target keyword]"
pubDate: "{today_date}"
author: "Nurture Airbnb Property Management"
category: "[News/Tips/Guides]"
tags: [{tags_list}]
sourceUrl: "{article_url}"
sourceTitle: "{article_title}"
draft: false
---

[Your blog post content here with proper markdown formatting. Use ## for h2, ### for h3. Include links as [text](/path)]
"""


def send_email_notification(posts: list[dict]) -> bool:
    """Send email notification about newly published blog posts."""
    smtp_host = os.getenv("EMAIL_SMTP_HOST")
    smtp_port = os.getenv("EMAIL_SMTP_PORT", "587")
    smtp_user = os.getenv("EMAIL_SMTP_USER")
    smtp_password = os.getenv("EMAIL_SMTP_PASSWORD")
    notify_to = os.getenv("EMAIL_NOTIFY_TO", "info@nurtre.io")

    if not all([smtp_host, smtp_user, smtp_password]):
        print("  Warning: Email not configured. Skipping notification.")
        print("  Set EMAIL_SMTP_HOST, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD in .env")
        return False

    try:
        # Build email content with post title(s) in subject
        if len(posts) == 1:
            subject = f"New Post: {posts[0]['title']}"
        else:
            subject = f"New Blog Posts: {posts[0]['title']} (+{len(posts) - 1} more)"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #759b8f;">New Blog Post{'s' if len(posts) > 1 else ''} Published</h2>
            <p>The following blog post{'s have' if len(posts) > 1 else ' has'} been automatically published to nurturestays.ca:</p>
            <hr style="border: 1px solid #eee;">
        """

        for post in posts:
            post_url = f"{SITE_URL}/blog/{post['slug']}"
            html_content += f"""
            <div style="margin: 20px 0; padding: 15px; background: #f8f6f1; border-radius: 8px;">
                <h3 style="margin: 0 0 10px 0; color: #333;">
                    <a href="{post_url}" style="color: #759b8f; text-decoration: none;">{post['title']}</a>
                </h3>
                <p style="margin: 5px 0; color: #666; font-size: 14px;">
                    Source: <a href="{post['source_url']}" style="color: #759b8f;">{post['source_url'][:60]}...</a>
                </p>
                <p style="margin: 10px 0 0 0;">
                    <a href="{post_url}" style="background: #759b8f; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none; display: inline-block;">
                        View Post
                    </a>
                </p>
            </div>
            """

        html_content += """
            <hr style="border: 1px solid #eee;">
            <p style="color: #999; font-size: 12px;">
                This is an automated notification from the Nurture Blog Generator.
            </p>
        </body>
        </html>
        """

        # Plain text version
        text_content = f"New Blog Post{'s' if len(posts) > 1 else ''} Published\n\n"
        for post in posts:
            post_url = f"{SITE_URL}/blog/{post['slug']}"
            text_content += f"- {post['title']}\n  {post_url}\n  Source: {post['source_url']}\n\n"

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = notify_to

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        # Send email
        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        print(f"  Email notification sent to {notify_to}")
        return True

    except Exception as e:
        print(f"  Error sending email: {e}")
        return False


def load_processed_articles() -> dict:
    """Load the list of already processed article URLs."""
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed": [], "last_run": None}


def save_processed_articles(data: dict) -> None:
    """Save the list of processed article URLs."""
    data["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_article_hash(url: str) -> str:
    """Generate a unique hash for an article URL."""
    return hashlib.md5(url.encode()).hexdigest()


def fetch_article_content(url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetch and extract the main content from an article URL.
    Returns (title, content, source_name).
    Tries multiple methods to handle various website structures.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    # Extract source name from domain
    parsed = urlparse(url)
    source_name = parsed.netloc.replace("www.", "").split(".")[0].title()

    try:
        print(f"  Fetching article from URL...")
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title - try multiple methods
        title = None

        # Method 1: og:title (usually most accurate)
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title.get("content", "").strip()

        # Method 2: title tag
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
                # Clean up title - often contains site name
                if " | " in title:
                    title = title.split(" | ")[0].strip()
                elif " - " in title:
                    title = title.split(" - ")[0].strip()

        # Method 3: h1 tag
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        if not title:
            title = "Untitled Article"

        # Remove script, style, nav, footer, aside elements
        for element in soup(["script", "style", "nav", "footer", "aside", "header", "form", "iframe", "noscript"]):
            element.decompose()

        # Try to find the main article content using site-specific and generic selectors
        article = None
        content_text = None

        # Site-specific selectors (add more as needed)
        site_selectors = {
            "ctvnews": [".article-content", ".c-text", '[data-component="text"]', ".article__content"],
            "cbc": [".story-content", ".story"],
            "globalnews": [".c-posts__content", ".article-body"],
            "thestar": [".article__body", ".c-article-body"],
            "blogto": [".content", ".article-content"],
        }

        # Generic selectors (order matters - most specific first)
        generic_selectors = [
            '[itemprop="articleBody"]',
            '[data-testid="article-body"]',
            ".article-body",
            ".article-content",
            ".post-content",
            ".entry-content",
            ".content-body",
            ".story-body",
            "article .content",
            "article",
            '[role="main"]',
            "main",
            ".main-content",
        ]

        # Try site-specific selectors first
        domain_key = parsed.netloc.replace("www.", "").split(".")[0].lower()
        if domain_key in site_selectors:
            for selector in site_selectors[domain_key]:
                article = soup.select_one(selector)
                if article:
                    print(f"  Found content using site-specific selector: {selector}")
                    break

        # Try generic selectors
        if not article:
            for selector in generic_selectors:
                article = soup.select_one(selector)
                if article:
                    # Verify it has substantial text content
                    text = article.get_text(strip=True)
                    if len(text) > 200:  # Minimum content threshold
                        print(f"  Found content using selector: {selector}")
                        break
                    article = None

        # Try extracting from JSON-LD structured data (many news sites use this)
        if not article:
            json_ld = soup.find("script", type="application/ld+json")
            if json_ld:
                try:
                    import json
                    data = json.loads(json_ld.string)
                    # Handle both single object and array formats
                    if isinstance(data, list):
                        for item in data:
                            if item.get("@type") in ["NewsArticle", "Article", "BlogPosting"]:
                                data = item
                                break
                    if data.get("articleBody"):
                        content_text = data["articleBody"]
                        print("  Found content in JSON-LD structured data")
                        if not title and data.get("headline"):
                            title = data["headline"]
                except:
                    pass

        # Fall back to body with paragraph extraction
        if not article and not content_text:
            # Try to get all paragraphs from body
            paragraphs = soup.find_all("p")
            if paragraphs:
                # Filter to paragraphs that seem like article content (reasonable length)
                article_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50]
                if article_paragraphs:
                    content_text = "\n\n".join(article_paragraphs)
                    print(f"  Extracted {len(article_paragraphs)} paragraphs from page")

        # Get final text content
        if content_text:
            text = content_text
        elif article:
            text = article.get_text(separator="\n", strip=True)
        else:
            print(f"  Warning: Could not find article content container")
            return title, None, source_name

        # Clean up the text
        text = re.sub(r'\n\s*\n', '\n\n', text)  # Remove excessive whitespace
        text = re.sub(r'[ \t]+', ' ', text)  # Normalize spaces

        # Limit length
        if len(text) > 15000:
            text = text[:15000] + "...[truncated]"

        # Verify we got meaningful content
        if len(text) < 100:
            print(f"  Warning: Content too short ({len(text)} chars)")
            return title, None, source_name

        return title, text, source_name

    except requests.exceptions.RequestException as e:
        print(f"  Network error fetching article: {e}")
        return None, None, None
    except Exception as e:
        print(f"  Error fetching article: {e}")
        return None, None, None


def generate_blog_post(title: str, content: str, url: str, source: str, client: anthropic.Anthropic) -> Optional[str]:
    """Generate a blog post using Claude API."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Determine appropriate tags based on content (only use: News, Tips, Guides)
    tags = []
    content_lower = (title + " " + content).lower()

    # Guides: regulation guides, how-to content, comprehensive information
    if any(word in content_lower for word in ["regulation", "bylaw", "law", "rule", "policy", "guide", "how to", "step by step", "complete", "everything you need"]):
        tags.append('"Guides"')

    # Tips: actionable advice, strategies, recommendations
    if any(word in content_lower for word in ["tip", "strategy", "advice", "recommend", "should", "best practice", "optimize", "improve", "increase", "maximize"]):
        tags.append('"Tips"')

    # News: current events, announcements, updates, market trends
    if any(word in content_lower for word in ["announce", "new", "update", "launch", "report", "study", "trend", "market", "data", "statistics"]):
        tags.append('"News"')

    # Default to News if no tags matched
    if not tags:
        tags.append('"News"')

    prompt = BLOG_PROMPT_TEMPLATE.format(
        article_title=title,
        article_source=source,
        article_url=url,
        article_date=datetime.now().strftime("%B %d, %Y"),
        article_content=content,
        today_date=today,
        tags_list=", ".join(tags),
    )

    try:
        print(f"  Generating blog post with Claude...")
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return message.content[0].text

    except Exception as e:
        print(f"  Error generating blog post: {e}")
        return None


def slugify(title: str) -> str:
    """Convert a title to a URL-friendly slug."""
    # Remove special characters and convert to lowercase
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    # Replace spaces with hyphens
    slug = re.sub(r'[\s_]+', '-', slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    # Trim hyphens from ends
    slug = slug.strip('-')
    # Limit length
    return slug[:60]


def save_post(content: str, title: str) -> Optional[tuple[Path, str]]:
    """Save a blog post to the posts directory. Returns (filepath, slug)."""
    # Ensure posts directory exists
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename from title (no date prefix - slug becomes the URL)
    slug = slugify(title)
    filename = f"{slug}.md"
    filepath = POSTS_DIR / filename

    # Handle duplicate filenames
    counter = 1
    base_slug = slug
    while filepath.exists():
        slug = f"{base_slug}-{counter}"
        filename = f"{slug}.md"
        filepath = POSTS_DIR / filename
        counter += 1

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath, slug
    except Exception as e:
        print(f"  Error saving post: {e}")
        return None


def process_url(url: str, client: anthropic.Anthropic, processed_data: dict) -> Optional[dict]:
    """Process a single URL and generate a blog post."""
    print(f"\n{'=' * 60}")
    print(f"Processing: {url}")
    print("=" * 60)

    # Check if already processed
    url_hash = get_article_hash(url)
    if url_hash in processed_data.get("processed", []):
        print(f"  This URL has already been processed. Skipping.")
        print(f"  (Use --force flag to regenerate)")
        return None

    # Fetch article content
    title, content, source = fetch_article_content(url)

    if not content:
        print(f"  Could not fetch article content. Aborting.")
        return None

    print(f"  Title: {title}")
    print(f"  Source: {source}")
    print(f"  Content length: {len(content)} characters")

    # Generate blog post
    blog_content = generate_blog_post(title, content, url, source, client)

    if not blog_content:
        print(f"  Failed to generate blog post.")
        return None

    # Save and publish post
    result = save_post(blog_content, title)

    if result:
        post_path, slug = result
        print(f"\n  Post published successfully!")
        print(f"  File: {post_path.relative_to(PROJECT_ROOT)}")
        print(f"  URL: {SITE_URL}/blog/{slug}")

        # Mark as processed
        if "processed" not in processed_data:
            processed_data["processed"] = []
        processed_data["processed"].append(url_hash)

        return {
            "title": title,
            "slug": slug,
            "file": str(post_path.relative_to(PROJECT_ROOT)),
            "source_url": url,
        }
    else:
        print(f"  Failed to save post.")
        return None


def main():
    """Main function."""
    print("=" * 60)
    print("Nurture Blog Post Generator - Create from URL")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Check for URLs
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python scripts/create-blog-from-url.py <url>")
        print("  python scripts/create-blog-from-url.py <url1> <url2> <url3>")
        print("\nExamples:")
        print('  python scripts/create-blog-from-url.py "https://news.airbnb.com/some-article"')
        print('  python scripts/create-blog-from-url.py "url1" "url2" "url3"')
        sys.exit(1)

    urls = sys.argv[1:]

    # Check for --force flag
    force = "--force" in urls
    if force:
        urls.remove("--force")

    # Validate URLs
    for url in urls:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            print(f"\nError: Invalid URL: {url}")
            print("URLs must include http:// or https://")
            sys.exit(1)

    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nError: ANTHROPIC_API_KEY environment variable not set")
        print("Please set it in your .env file or environment")
        sys.exit(1)

    # Initialize Anthropic client
    client = anthropic.Anthropic(api_key=api_key)

    # Load processed articles
    processed_data = load_processed_articles()

    if force:
        print("\n--force flag set: Will regenerate even if previously processed")

    # Process each URL
    results = []
    for url in urls:
        if force:
            # Remove from processed list if forcing
            url_hash = get_article_hash(url)
            if url_hash in processed_data.get("processed", []):
                processed_data["processed"].remove(url_hash)

        result = process_url(url, client, processed_data)
        if result:
            results.append(result)

    # Save processed articles list
    save_processed_articles(processed_data)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"URLs provided: {len(urls)}")
    print(f"Posts published: {len(results)}")

    if results:
        print("\nPublished posts:")
        for result in results:
            print(f"\n  Title: {result['title']}")
            print(f"  URL: {SITE_URL}/blog/{result['slug']}")
            print(f"  File: {result['file']}")
            print(f"  Source: {result['source_url']}")

        # Send email notification
        print("\nSending email notification...")
        send_email_notification(results)

    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
