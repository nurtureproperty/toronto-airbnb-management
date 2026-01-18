#!/usr/bin/env python3
"""
Automated Blog Post Generator for Nurture Airbnb Property Management

This script scans RSS feeds for relevant short-term rental news and generates
blog posts using the Claude API. Posts are auto-published and email notifications
are sent to the configured address.

Usage:
    python scripts/blog-generator.py

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
from urllib.parse import urlparse, quote

import anthropic
import feedparser
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

# RSS Feeds to monitor
RSS_FEEDS = [
    {
        "name": "Airbnb Newsroom",
        "url": "https://news.airbnb.com/feed/",
        "priority": "high"
    },
    {
        "name": "Short Term Rentalz",
        "url": "https://shorttermrentalz.com/feed/",
        "priority": "high"
    },
    {
        "name": "Skift Travel News",
        "url": "https://skift.com/feed/",
        "priority": "medium"
    },
    # Google News RSS feeds for specific searches
    {
        "name": "Google News - STR Ontario",
        "url": "https://news.google.com/rss/search?q=short+term+rental+Ontario&hl=en-CA&gl=CA&ceid=CA:en",
        "priority": "high"
    },
    {
        "name": "Google News - Airbnb Ontario Regulations",
        "url": "https://news.google.com/rss/search?q=Airbnb+Ontario+regulations&hl=en-CA&gl=CA&ceid=CA:en",
        "priority": "high"
    },
    {
        "name": "Google News - Mid Term Rental Canada",
        "url": "https://news.google.com/rss/search?q=mid+term+rental+Canada&hl=en-CA&gl=CA&ceid=CA:en",
        "priority": "medium"
    },
]

# Keywords for relevance filtering (case-insensitive)
RELEVANCE_KEYWORDS = {
    "high_priority": [
        "toronto", "ontario", "gta", "greater toronto", "mississauga", "brampton",
        "vaughan", "markham", "richmond hill", "oakville", "hamilton", "burlington",
        "airbnb regulation", "str regulation", "short term rental regulation",
        "short-term rental regulation", "airbnb bylaw", "str bylaw", "180 day",
        "180 night", "principal residence", "municipal accommodation tax",
    ],
    "medium_priority": [
        "airbnb", "vrbo", "short term rental", "short-term rental", "str",
        "vacation rental", "mid term rental", "mid-term rental", "furnished rental",
        "canada rental", "canadian rental", "ontario housing", "rental income",
        "property management", "host", "listing", "booking", "guest",
    ],
    "exclude": [
        "stock price", "ipo", "quarterly earnings", "revenue report",
        "brian chesky net worth", "celebrity", "lawsuit unrelated",
    ]
}

# Blog post generation prompt
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
- /services/full-airbnb-management-toronto - for full-service management mentions
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

OUTPUT FORMAT (use exactly this format):
---
title: "[SEO optimized title, 50-60 characters, include location if relevant]"
description: "[Meta description, 150-160 characters, compelling and includes target keyword]"
pubDate: "{today_date}"
author: "Nurture Airbnb Property Management"
category: "[News/Regulations/Tips/Market Update]"
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
        # Build email content
        subject = f"New Blog Post{'s' if len(posts) > 1 else ''} Published - {datetime.now().strftime('%Y-%m-%d')}"

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


def is_relevant(title: str, summary: str = "") -> tuple[bool, str]:
    """
    Check if an article is relevant based on keywords.
    Returns (is_relevant, priority_level).
    """
    text = f"{title} {summary}".lower()

    # Check exclusions first
    for keyword in RELEVANCE_KEYWORDS["exclude"]:
        if keyword in text:
            return False, "excluded"

    # Check high priority keywords
    for keyword in RELEVANCE_KEYWORDS["high_priority"]:
        if keyword in text:
            return True, "high"

    # Check medium priority keywords
    for keyword in RELEVANCE_KEYWORDS["medium_priority"]:
        if keyword in text:
            return True, "medium"

    return False, "none"


def fetch_article_content(url: str) -> Optional[str]:
    """Fetch and extract the main content from an article URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script, style, nav, footer, aside elements
        for element in soup(["script", "style", "nav", "footer", "aside", "header", "form", "iframe"]):
            element.decompose()

        # Try to find the main article content
        article = None

        # Common article selectors
        selectors = [
            "article",
            '[role="main"]',
            ".article-content",
            ".post-content",
            ".entry-content",
            ".content-body",
            ".article-body",
            "main",
            ".main-content",
        ]

        for selector in selectors:
            article = soup.select_one(selector)
            if article:
                break

        if not article:
            # Fall back to body
            article = soup.body

        if article:
            # Get text and clean it up
            text = article.get_text(separator="\n", strip=True)
            # Remove excessive whitespace
            text = re.sub(r'\n\s*\n', '\n\n', text)
            # Limit length
            if len(text) > 15000:
                text = text[:15000] + "...[truncated]"
            return text

        return None

    except Exception as e:
        print(f"  Error fetching article content: {e}")
        return None


def fetch_rss_feeds() -> list[dict]:
    """Fetch and parse all RSS feeds, returning relevant articles."""
    articles = []

    for feed_config in RSS_FEEDS:
        print(f"\nScanning: {feed_config['name']}")

        try:
            feed = feedparser.parse(feed_config["url"])

            if feed.bozo and feed.bozo_exception:
                print(f"  Warning: Feed parsing issue - {feed.bozo_exception}")

            for entry in feed.entries[:20]:  # Check last 20 entries per feed
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link = entry.get("link", "")
                published = entry.get("published", entry.get("updated", ""))

                if not link:
                    continue

                relevant, priority = is_relevant(title, summary)

                if relevant:
                    articles.append({
                        "title": title,
                        "summary": summary[:500] if summary else "",
                        "url": link,
                        "published": published,
                        "source": feed_config["name"],
                        "priority": priority,
                        "hash": get_article_hash(link),
                    })
                    print(f"  + Found relevant: {title[:60]}...")

        except Exception as e:
            print(f"  Error fetching feed: {e}")

    return articles


def generate_blog_post(article: dict, client: anthropic.Anthropic) -> Optional[str]:
    """Generate a blog post using Claude API."""
    print(f"\n  Fetching full article content...")
    content = fetch_article_content(article["url"])

    if not content:
        print(f"  Could not fetch article content, using summary only")
        content = article.get("summary", "No content available")

    today = datetime.now().strftime("%Y-%m-%d")

    # Determine appropriate tags
    tags = []
    title_lower = article["title"].lower()
    if "toronto" in title_lower or "ontario" in title_lower or "gta" in title_lower:
        tags.append('"Ontario"')
    if "regulation" in title_lower or "bylaw" in title_lower or "law" in title_lower:
        tags.append('"Regulations"')
    if "airbnb" in title_lower:
        tags.append('"Airbnb"')
    if "tax" in title_lower:
        tags.append('"Taxes"')
    if not tags:
        tags.append('"News"')

    prompt = BLOG_PROMPT_TEMPLATE.format(
        article_title=article["title"],
        article_source=article["source"],
        article_url=article["url"],
        article_date=article.get("published", "Unknown"),
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


def save_post(content: str, article: dict) -> Optional[tuple[Path, str]]:
    """Save a blog post to the posts directory. Returns (filepath, slug)."""
    # Ensure posts directory exists
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename from title (no date prefix so URL matches email link)
    slug = slugify(article["title"])
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


def main():
    """Main function to run the blog generator."""
    print("=" * 60)
    print("Nurture Blog Post Generator")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

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
    processed_hashes = set(processed_data.get("processed", []))

    print(f"\nPreviously processed articles: {len(processed_hashes)}")
    if processed_data.get("last_run"):
        print(f"Last run: {processed_data['last_run']}")

    # Fetch RSS feeds
    print("\n" + "-" * 40)
    print("Scanning RSS feeds for relevant articles...")
    print("-" * 40)

    articles = fetch_rss_feeds()

    # Filter out already processed articles
    new_articles = [a for a in articles if a["hash"] not in processed_hashes]

    print(f"\n" + "-" * 40)
    print(f"Found {len(articles)} relevant articles total")
    print(f"New articles to process: {len(new_articles)}")
    print("-" * 40)

    if not new_articles:
        print("\nNo new articles to process. Exiting.")
        save_processed_articles(processed_data)
        return

    # Sort by priority (high first)
    new_articles.sort(key=lambda x: 0 if x["priority"] == "high" else 1)

    # Process each new article
    posts_created = []

    for i, article in enumerate(new_articles, 1):
        print(f"\n{'=' * 60}")
        print(f"Processing article {i}/{len(new_articles)}")
        print(f"Title: {article['title'][:70]}...")
        print(f"Source: {article['source']}")
        print(f"Priority: {article['priority']}")
        print(f"URL: {article['url']}")

        # Generate blog post
        blog_content = generate_blog_post(article, client)

        if blog_content:
            # Save post
            result = save_post(blog_content, article)

            if result:
                post_path, slug = result
                print(f"  Published: {post_path.name}")
                posts_created.append({
                    "title": article["title"],
                    "slug": slug,
                    "file": str(post_path.relative_to(PROJECT_ROOT)),
                    "source_url": article["url"],
                })

                # Mark as processed
                processed_data["processed"].append(article["hash"])
            else:
                print(f"  Failed to save post")
        else:
            print(f"  Failed to generate blog post")
            # Still mark as processed to avoid retrying failed articles
            processed_data["processed"].append(article["hash"])

    # Save processed articles list
    save_processed_articles(processed_data)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Articles scanned: {len(articles)}")
    print(f"New articles processed: {len(new_articles)}")
    print(f"Posts published: {len(posts_created)}")

    if posts_created:
        print("\nNewly published posts:")
        for post in posts_created:
            print(f"  - {post['file']}")
            print(f"    URL: {SITE_URL}/blog/{post['slug']}")
            print(f"    Source: {post['source_url']}")

        # Send email notification
        print("\nSending email notification...")
        send_email_notification(posts_created)

    # Output for GitHub Actions
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"posts_created={len(posts_created)}\n")

    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
