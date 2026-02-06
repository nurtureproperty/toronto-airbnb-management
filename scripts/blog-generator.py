#!/usr/bin/env python3
"""
Automated Blog Post Generator for Nurture Airbnb Property Management

This script scans RSS feeds for relevant short-term rental news and generates
blog posts using the Claude API. Posts are auto-published and email notifications
are sent to the configured address.

WEEKLY LIMIT: Publishes up to 4 posts per week IF there's enough relevant Ontario STR content.
              Only publishes articles that are SPECIFICALLY about Ontario/GTA short-term rentals.
              If fewer relevant articles are found, fewer posts are published (quality over quantity).

PRIORITY SYSTEM:
- Fresh news is prioritized over backlogged articles (breaking news goes first)
- Articles must mention BOTH an Ontario location AND an STR/Airbnb topic
- Backlogged articles are processed after all new relevant articles
- Maximum 5 articles kept in backlog for slow news weeks

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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse, quote
from dateutil import parser as dateparser

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
BACKLOG_FILE = SCRIPT_DIR / "article_backlog.json"
SITE_URL = "https://www.nurturestays.ca"
MAX_POSTS_PER_WEEK = 4  # Maximum posts per week (only publishes if content meets strict filters)
POSTS_THIS_WEEK_FILE = SCRIPT_DIR / "posts_this_week.json"

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
# STRICT FILTERING: Articles must contain BOTH a location keyword AND a topic keyword
RELEVANCE_KEYWORDS = {
    # Location keywords - article MUST mention Ontario/GTA locations
    "required_locations": [
        "toronto", "ontario", "gta", "greater toronto area",
        "mississauga", "brampton", "vaughan", "markham", "richmond hill",
        "oakville", "hamilton", "burlington", "ajax", "pickering", "whitby",
        "oshawa", "scarborough", "etobicoke", "north york", "caledon",
        "kitchener", "waterloo", "guelph", "cambridge", "london ontario",
        "ottawa", "kingston", "barrie", "niagara", "st. catharines",
        "st catharines", "muskoka", "huntsville", "collingwood", "blue mountains",
    ],
    # Topic keywords - article must also be about STR/Airbnb topics
    "required_topics": [
        "airbnb", "short term rental", "short-term rental", "str ",
        "vrbo", "vacation rental", "mid term rental", "mid-term rental",
        "furnished rental", "rental regulation", "rental bylaw", "rental license",
        "rental licensing", "host", "listing", "mat tax", "accommodation tax",
        "principal residence", "180 day", "180 night",
    ],
    # Exclude negative/irrelevant content
    "exclude": [
        # Financial/corporate news not relevant to hosts
        "stock price", "ipo", "quarterly earnings", "revenue report",
        "brian chesky net worth", "celebrity", "lawsuit unrelated",
        # Negative STR sentiment - exclude articles that make STR look bad
        "housing crisis", "blame airbnb", "ban short-term", "ban airbnb",
        "crackdown", "crack down", "illegal airbnb", "illegal short-term",
        "evict", "eviction", "tenant rights", "housing shortage",
        "destroy neighborhood", "ruining neighborhood", "party house",
        "noise complaint", "neighbor complaint", "neighbour complaint",
        "affordable housing crisis", "housing affordability",
        "anti-airbnb", "anti-str", "airbnb problem", "str problem",
        "short-term rental problem", "airbnb plague", "airbnb scourge",
        "hotel lobby", "regulate out", "shut down airbnb",
        "ghost hotel", "illegal hotel", "homelessness", "homeless",
        "protest airbnb", "airbnb protest", "community opposition",
        "failed to", "failure", "nightmare", "horror story",
        "scam", "fraud", "dangerous", "unsafe",
        # Generic industry news (not Ontario-specific)
        "new york", "california", "florida", "texas", "los angeles",
        "san francisco", "miami", "europe", "uk ", "london uk", "australia",
        "global report", "worldwide", "international",
    ]
}

# Blog post generation prompt
BLOG_PROMPT_TEMPLATE = """You are a content writer for Nurture, a premium Airbnb property management company based in Toronto, serving Ontario. Your job is to write blog posts about short-term rental news that help property owners and Airbnb hosts.

LOCATION-AWARE WRITING:
- If the article is about a SPECIFIC CITY (Burlington, Hamilton, Ottawa, Muskoka, etc.), write FOR THAT AUDIENCE
- Focus on that city's regulations, hosts, and local context. Do NOT pivot everything to "GTA hosts"
- Example: An article about Burlington STR rules should be titled "Burlington's New Short-Term Rental Rules" not "What GTA Hosts Need to Know About Burlington"
- Only reference GTA/Toronto if the article is actually about Toronto or the broader GTA region
- For Ontario-wide or Canada-wide news, write for Ontario hosts generally

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
7. Reference specific local details relevant to the article's location
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
- Location: Based in Toronto, serving Ontario
- Services: Full Airbnb management, short-term rental management, mid-term rental management
- Fees: 10-15% (competitors charge 18-25%)
- Key differentiator: No long contracts, you own your listing, local expertise

INTERNAL LINKS TO INCLUDE (use 2-3 naturally where relevant):
- /services/short-term-rental-management-toronto - for STR management mentions
- /services/mid-term-rental-management-toronto - for mid-term rental mentions
- /full-airbnb-management-toronto - for full-service management mentions (NOTE: this is a root-level page, not under /services/)
- /pricing-toronto-airbnb-management - when discussing costs or fees
- /contact - for CTAs

TARGET KEYWORDS (work in naturally based on article location, don't force):
- [City name] Airbnb (e.g., "Burlington Airbnb", "Toronto Airbnb")
- [City name] short term rental regulations
- Ontario STR regulations
- Airbnb management Ontario

SOURCE ARTICLE TO ANALYZE:
Title: {article_title}
Source: {article_source}
URL: {article_url}
Published: {article_date}

Full Article Content:
{article_content}

---

Based on the source article above, write a blog post that:
1. Focuses on the SPECIFIC LOCATION mentioned in the article (not generic "GTA hosts")
2. Covers the actual topic and regulations thoroughly
3. Includes practical takeaways hosts in that area can act on
4. Is 600-900 words
5. References specific facts and quotes from the source article
6. Ends with a CTA mentioning Nurture can help

TITLE REQUIREMENTS:
- Create a UNIQUE, SPECIFIC title based on the article's main topic and location
- Include the city/region name if the article is location-specific
- NEVER use generic titles like "What GTA Airbnb Hosts Need to Know" or "What Toronto Hosts Should Know"
- Use varied title formats: questions, how-to, numbers, direct statements
- Examples of GOOD titles: "Burlington Launches New STR Licensing Program", "Muskoka's $1,000 Airbnb License Fee Starts January 2025", "Ottawa Cracks Down on Unlicensed Short-Term Rentals"
- Examples of BAD titles: "What GTA Hosts Need to Know About Burlington", "Important Update for Ontario Airbnb Hosts"

OUTPUT FORMAT (use exactly this format):
---
title: "[UNIQUE title with location if applicable, 50-60 chars]"
description: "[Meta description, 150-160 characters, include location and target keyword]"
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

# Additional prompt for reframing older news (14 days - 1 year old)
REFRAME_PROMPT_ADDITION = """
IMPORTANT - THIS IS OLDER NEWS:
The source article is {days_old} days old (from {original_date}). You MUST reframe this as HISTORICAL context, not breaking news.

REFRAMING REQUIREMENTS:
1. Use PAST TENSE throughout - this already happened
2. Open with context like "Earlier this year..." or "Back in [month]..." or "In a decision from [date]..."
3. Focus on ONGOING IMPLICATIONS - what does this mean for hosts TODAY?
4. Include the actual date when the event occurred
5. Position as "looking back" or "what we learned" rather than "breaking news"
6. Title should NOT sound like breaking news - use formats like:
   - "How [City]'s [Month] STR Decision Affects Hosts Today"
   - "Looking Back: [City]'s Airbnb Ruling and What It Means Now"
   - "[City] STR Rules One Year Later: What Hosts Need to Know"
7. The value is in analysis and ongoing relevance, not novelty

DO NOT write this as if it just happened. Readers will be confused if you present old news as new.
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


def load_backlog() -> list[dict]:
    """Load the article backlog."""
    if BACKLOG_FILE.exists():
        with open(BACKLOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("backlog", [])
    return []


def save_backlog(articles: list[dict]) -> None:
    """Save the article backlog."""
    data = {
        "backlog": articles,
        "updated": datetime.now(timezone.utc).isoformat()
    }
    with open(BACKLOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_to_backlog(articles: list[dict]) -> None:
    """Add articles to the backlog for future publishing."""
    backlog = load_backlog()
    existing_hashes = {a["hash"] for a in backlog}

    for article in articles:
        if article["hash"] not in existing_hashes:
            backlog.append(article)
            print(f"  + Added to backlog: {article['title'][:50]}...")

    save_backlog(backlog)


def get_week_number() -> str:
    """Get current ISO week number as string (YYYY-WW format)."""
    now = datetime.now()
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def load_weekly_count() -> dict:
    """Load the weekly post count tracker."""
    if POSTS_THIS_WEEK_FILE.exists():
        with open(POSTS_THIS_WEEK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"week": None, "count": 0}


def save_weekly_count(data: dict) -> None:
    """Save the weekly post count."""
    with open(POSTS_THIS_WEEK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_posts_remaining_this_week() -> int:
    """Get how many posts can still be published this week."""
    current_week = get_week_number()
    weekly_data = load_weekly_count()

    # Reset count if it's a new week
    if weekly_data.get("week") != current_week:
        return MAX_POSTS_PER_WEEK

    return max(0, MAX_POSTS_PER_WEEK - weekly_data.get("count", 0))


def increment_weekly_count(num_posts: int = 1) -> None:
    """Increment the weekly post counter."""
    current_week = get_week_number()
    weekly_data = load_weekly_count()

    # Reset if new week
    if weekly_data.get("week") != current_week:
        weekly_data = {"week": current_week, "count": 0}

    weekly_data["count"] = weekly_data.get("count", 0) + num_posts
    save_weekly_count(weekly_data)


def get_article_hash(url: str) -> str:
    """Generate a unique hash for an article URL."""
    return hashlib.md5(url.encode()).hexdigest()


def parse_article_date(date_string: str) -> Optional[datetime]:
    """
    Parse various date formats from RSS feeds.
    Returns a timezone-aware datetime or None if parsing fails.
    """
    if not date_string or date_string == "Unknown":
        return None

    try:
        # Use dateutil parser which handles most formats
        parsed = dateparser.parse(date_string)
        if parsed:
            # Make timezone-aware if not already
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
    except Exception as e:
        print(f"  Warning: Could not parse date '{date_string}': {e}")

    return None


def classify_article_freshness(date_string: str) -> Tuple[str, int]:
    """
    Classify article freshness based on publication date.

    Returns:
        Tuple of (classification, days_old)
        - "fresh": 0-14 days old, publish normally
        - "recent": 14 days - 1 year old, reframe as historical
        - "stale": over 1 year old, skip entirely
        - "unknown": could not parse date, treat as fresh
    """
    parsed_date = parse_article_date(date_string)

    if not parsed_date:
        return "unknown", 0

    now = datetime.now(timezone.utc)
    age = now - parsed_date
    days_old = age.days

    if days_old < 0:
        # Future date (possibly timezone issue), treat as fresh
        return "fresh", 0
    elif days_old <= 14:
        return "fresh", days_old
    elif days_old <= 365:
        return "recent", days_old
    else:
        return "stale", days_old


def is_relevant(title: str, summary: str = "") -> tuple[bool, str]:
    """
    Check if an article is relevant based on STRICT keyword matching.
    Articles must contain BOTH a location keyword AND a topic keyword.
    Returns (is_relevant, reason).
    """
    text = f"{title} {summary}".lower()

    # Check exclusions first
    for keyword in RELEVANCE_KEYWORDS["exclude"]:
        if keyword in text:
            return False, "excluded"

    # STRICT CHECK: Must have BOTH location AND topic
    has_location = False
    matched_location = None
    for keyword in RELEVANCE_KEYWORDS["required_locations"]:
        if keyword in text:
            has_location = True
            matched_location = keyword
            break

    has_topic = False
    matched_topic = None
    for keyword in RELEVANCE_KEYWORDS["required_topics"]:
        if keyword in text:
            has_topic = True
            matched_topic = keyword
            break

    # Only accept articles that have BOTH location AND topic
    if has_location and has_topic:
        return True, f"ontario_str ({matched_location} + {matched_topic})"

    # Reject articles missing either requirement
    if has_topic and not has_location:
        return False, "no_ontario_location"
    if has_location and not has_topic:
        return False, "no_str_topic"

    return False, "no_match"


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

                relevant, reason = is_relevant(title, summary)

                if relevant:
                    articles.append({
                        "title": title,
                        "summary": summary[:500] if summary else "",
                        "url": link,
                        "published": published,
                        "source": feed_config["name"],
                        "priority": reason,  # Stores match reason like "ontario_str (toronto + airbnb)"
                        "hash": get_article_hash(link),
                    })
                    print(f"  + MATCH: {title[:50]}... [{reason}]")
                elif reason == "no_ontario_location":
                    print(f"  - Skip (no Ontario): {title[:50]}...")
                elif reason == "excluded":
                    print(f"  - Skip (excluded): {title[:50]}...")

        except Exception as e:
            print(f"  Error fetching feed: {e}")

    return articles


def generate_blog_post(article: dict, client: anthropic.Anthropic, freshness: str = "fresh", days_old: int = 0) -> Optional[str]:
    """Generate a blog post using Claude API.

    Args:
        article: Article data dict
        client: Anthropic client
        freshness: "fresh", "recent", or "unknown"
        days_old: How many days old the article is
    """
    print(f"\n  Fetching full article content...")
    content = fetch_article_content(article["url"])

    if not content:
        print(f"  Could not fetch article content, using summary only")
        content = article.get("summary", "No content available")

    today = datetime.now().strftime("%Y-%m-%d")

    # Determine appropriate tags (only use: News, Tips, Guides)
    tags = []
    content_lower = (article["title"] + " " + content).lower()

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
        article_title=article["title"],
        article_source=article["source"],
        article_url=article["url"],
        article_date=article.get("published", "Unknown"),
        article_content=content,
        today_date=today,
        tags_list=", ".join(tags),
    )

    # Add reframing instructions for older news
    if freshness == "recent" and days_old > 14:
        original_date = article.get("published", "Unknown")
        reframe_addition = REFRAME_PROMPT_ADDITION.format(
            days_old=days_old,
            original_date=original_date
        )
        prompt = prompt + "\n" + reframe_addition
        print(f"  Note: Reframing as historical news ({days_old} days old)")

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
    print("Nurture Blog Post Generator (Ontario STR Focus)")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Week: {get_week_number()}")
    posts_remaining = get_posts_remaining_this_week()
    print(f"Weekly limit: {MAX_POSTS_PER_WEEK} posts | Remaining this week: {posts_remaining}")
    print("=" * 60)

    # Check weekly limit before doing anything
    if posts_remaining <= 0:
        print("\nWeekly post limit reached. No new posts will be published.")
        print("The limit resets at the start of each new week (Monday).")
        return

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

    # Load existing backlog
    backlog = load_backlog()
    print(f"Articles in backlog: {len(backlog)}")

    # Fetch RSS feeds
    print("\n" + "-" * 40)
    print("Scanning RSS feeds for Ontario STR articles...")
    print("(Requires BOTH Ontario location + STR topic keywords)")
    print("-" * 40)

    articles = fetch_rss_feeds()

    # Filter out already processed articles
    new_articles = [a for a in articles if a["hash"] not in processed_hashes]

    # Separate new articles from backlog
    backlog_hashes = {a["hash"] for a in backlog}
    new_not_in_backlog = [a for a in new_articles if a["hash"] not in backlog_hashes]

    # PRIORITY: Fresh news first, then backlog
    # This ensures breaking Ontario STR news gets published immediately
    articles_to_process = new_not_in_backlog + backlog

    print(f"\n" + "-" * 40)
    print(f"Found {len(articles)} Ontario STR articles in feeds")
    print(f"New articles (not processed): {len(new_articles)}")
    print(f"From backlog: {len(backlog)}")
    print(f"Total to consider: {len(articles_to_process)}")
    print(f"Will publish up to: {posts_remaining} (weekly limit)")
    print("-" * 40)

    if not articles_to_process:
        print("\nNo Ontario STR articles found. Exiting.")
        print("(Articles must mention Ontario/GTA location AND STR/Airbnb topic)")
        save_processed_articles(processed_data)
        return

    # Process articles up to weekly limit
    posts_created = []
    articles_published_hashes = []

    for i, article in enumerate(articles_to_process, 1):
        # Stop if we've hit the weekly limit
        if len(posts_created) >= posts_remaining:
            print(f"\n{'=' * 60}")
            print(f"Weekly limit reached ({MAX_POSTS_PER_WEEK} posts/week).")
            break

        print(f"\n{'=' * 60}")
        print(f"Processing article {i}/{len(articles_to_process)} (published: {len(posts_created)}/{posts_remaining} remaining)")
        print(f"Title: {article['title'][:70]}...")
        print(f"Source: {article['source']}")
        print(f"Match: {article.get('priority', 'ontario_str')}")
        print(f"URL: {article['url']}")

        # Check article freshness
        freshness, days_old = classify_article_freshness(article.get("published", ""))
        print(f"Freshness: {freshness} ({days_old} days old)")

        # Skip stale articles (over 1 year old)
        if freshness == "stale":
            print(f"  SKIPPED: Article is over 1 year old ({days_old} days)")
            # Mark as processed so we don't keep checking it
            processed_data["processed"].append(article["hash"])
            continue

        # Generate blog post (with reframing for recent/older articles)
        blog_content = generate_blog_post(article, client, freshness, days_old)

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

                # Mark as processed and track for backlog removal
                processed_data["processed"].append(article["hash"])
                articles_published_hashes.append(article["hash"])
            else:
                print(f"  Failed to save post")
        else:
            print(f"  Failed to generate blog post")
            # Still mark as processed to avoid retrying failed articles
            processed_data["processed"].append(article["hash"])
            articles_published_hashes.append(article["hash"])

    # Handle remaining articles (add to backlog for next week)
    remaining_articles = [
        a for a in articles_to_process
        if a["hash"] not in articles_published_hashes
        and a["hash"] not in processed_hashes
    ]

    # Keep remaining Ontario STR articles in backlog, limit to 5
    remaining_for_backlog = remaining_articles[:5]

    if remaining_for_backlog:
        print(f"\n" + "-" * 40)
        print(f"Adding {len(remaining_for_backlog)} articles to backlog for later")
        print("-" * 40)
        for article in remaining_for_backlog:
            print(f"  + {article['title'][:60]}...")

    # Update backlog: remove published, add new
    updated_backlog = [a for a in backlog if a["hash"] not in articles_published_hashes]
    for article in remaining_for_backlog:
        if article["hash"] not in {a["hash"] for a in updated_backlog}:
            updated_backlog.append(article)

    save_backlog(updated_backlog[:5])  # Keep max 5 in backlog

    # Update weekly counter
    if posts_created:
        increment_weekly_count(len(posts_created))

    # Save processed articles list
    save_processed_articles(processed_data)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Ontario STR articles found: {len(articles)}")
    print(f"Articles considered (incl. backlog): {len(articles_to_process)}")
    new_remaining = get_posts_remaining_this_week()
    print(f"Posts published this run: {len(posts_created)}")
    print(f"Weekly limit: {MAX_POSTS_PER_WEEK} | Remaining this week: {new_remaining}")
    print(f"Articles in backlog: {len(updated_backlog)}")

    if posts_created:
        print("\nNewly published posts:")
        for post in posts_created:
            print(f"  - {post['file']}")
            print(f"    URL: {SITE_URL}/blog/{post['slug']}")
            print(f"    Source: {post['source_url']}")

        # Send email notification
        print("\nSending email notification...")
        send_email_notification(posts_created)

    if updated_backlog:
        print(f"\nBacklogged for future publishing:")
        for article in updated_backlog:
            print(f"  - {article['title'][:60]}...")

    # Output for GitHub Actions
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"posts_created={len(posts_created)}\n")
            f.write(f"backlog_count={len(updated_backlog)}\n")

    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
