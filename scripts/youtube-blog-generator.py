#!/usr/bin/env python3
"""
YouTube to Blog Post Generator for Nurture Airbnb Property Management

This script monitors a YouTube channel for new long-form videos and automatically
generates blog post summaries with embedded video players.

Features:
- Monitors YouTube channel RSS feed for new videos
- Filters out YouTube Shorts (videos under 60 seconds)
- Fetches video transcripts for content generation
- Generates SEO-optimized blog summaries using Claude
- Embeds YouTube video at top of blog post
- Auto-publishes and sends email notifications

Usage:
    python scripts/youtube-blog-generator.py

Environment Variables Required:
    ANTHROPIC_API_KEY - Your Anthropic API key
    YOUTUBE_API_KEY - YouTube Data API key (optional, for transcripts)
    EMAIL_SMTP_HOST - SMTP server
    EMAIL_SMTP_PORT - SMTP port
    EMAIL_SMTP_USER - SMTP username
    EMAIL_SMTP_PASSWORD - SMTP password
    EMAIL_NOTIFY_TO - Notification email address
"""

import os
import sys
import json
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import hashlib

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
PROCESSED_FILE = SCRIPT_DIR / "processed_youtube_videos.json"
SITE_URL = "https://www.nurturestays.ca"

# YouTube Channel Configuration
YOUTUBE_CHANNEL_HANDLE = "@nurtureproperties"
YOUTUBE_CHANNEL_ID = None  # Will be fetched from handle if not set

# Minimum video duration in seconds (to filter out Shorts)
MIN_VIDEO_DURATION_SECONDS = 61  # Shorts are 60 seconds or less

# Blog post generation prompt for YouTube videos
BLOG_PROMPT_TEMPLATE = """You are a content writer for Nurture, a premium Airbnb property management company based in Toronto, serving Ontario. Your job is to write blog posts summarizing YouTube videos about short-term rentals and property management.

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
- "In this video", "In today's video" (too meta)

TONE AND STYLE:
1. Write like you're explaining to a friend over coffee
2. Use short, punchy sentences mixed with longer ones. Vary your rhythm.
3. Start some sentences with "And" or "But" for natural flow
4. Add casual transitions: "Here's the thing," "Look," "Honestly," "So," "Now,"
5. Include rhetorical questions where appropriate
6. Add personal opinions ("This is great advice" or "I'm not sure this works for everyone")
7. Reference specific Toronto/GTA/Ontario details when relevant
8. Throw in slightly imperfect phrasing. Real humans don't write perfectly.

STRUCTURE:
1. Start with a hook that gets to the main point immediately
2. Vary paragraph lengths. Some short (1-2 sentences), some longer.
3. Pull out key insights and actionable takeaways
4. Include timestamps for key sections if available
5. End with a natural CTA, not a forced sales pitch

COMPANY INFO:
- Company name: Nurture (stylized exactly as "Nurture")
- Website: nurturestays.ca
- Phone: (647) 957-8956
- Location: Based in Toronto, serving Ontario
- Services: Full Airbnb management, short-term rental management, mid-term rental management
- Fees: 10-15% (competitors charge 18-25%)
- Key differentiator: No long contracts, you own your listing, local expertise

INTERNAL LINKS TO INCLUDE (use 1-2 naturally where relevant):
- /services/short-term-rental-management-toronto - for STR management mentions
- /services/mid-term-rental-management-toronto - for mid-term rental mentions
- /full-airbnb-management-toronto - for full-service management mentions
- /pricing-toronto-airbnb-management - when discussing costs or fees
- /contact - for CTAs

VIDEO INFORMATION:
Title: {video_title}
Channel: {channel_name}
Published: {published_date}
Duration: {duration}
Video URL: {video_url}

Video Description:
{video_description}

Video Transcript:
{transcript}

---

Based on the video above, write a blog post that:
1. Summarizes the key points and insights from the video
2. Makes the content accessible to people who prefer reading over watching
3. Includes actionable takeaways hosts can use
4. Is 500-800 words
5. Ends with a CTA mentioning Nurture can help

TITLE REQUIREMENTS:
- Create a title that captures the video's main topic
- Don't just copy the video title, make it blog-appropriate
- Include relevant keywords for SEO
- Keep under 60 characters

NOTE: The blog post will automatically have the YouTube video embedded at the top, so you don't need to link to it or say "watch the video above".

OUTPUT FORMAT (use exactly this format):
---
title: "[Blog title, 50-60 chars]"
description: "[Meta description, 150-160 characters]"
pubDate: "{today_date}"
author: "Nurture Airbnb Property Management"
category: "[Tips/Guides/News]"
tags: [{tags_list}]
youtubeId: "{video_id}"
sourceUrl: "{video_url}"
sourceTitle: "{video_title}"
draft: false
---

[Your blog post content here with proper markdown formatting. Use ## for h2, ### for h3. Include links as [text](/path)]
"""


def get_channel_id_from_handle(handle: str) -> Optional[str]:
    """Get YouTube channel ID from a @handle."""
    try:
        # Try to fetch the channel page and extract the channel ID
        url = f"https://www.youtube.com/{handle}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # Look for channel ID in the page source
        match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]+)"', response.text)
        if match:
            return match.group(1)

        # Alternative pattern
        match = re.search(r'<link rel="canonical" href="https://www.youtube.com/channel/(UC[a-zA-Z0-9_-]+)"', response.text)
        if match:
            return match.group(1)

        return None
    except Exception as e:
        print(f"Error fetching channel ID: {e}")
        return None


def get_youtube_rss_feed(channel_id: str) -> str:
    """Get the RSS feed URL for a YouTube channel."""
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def parse_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration string to seconds."""
    # Format: PT#H#M#S or PT#M#S or PT#S
    if not duration_str:
        return 0

    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def format_duration(seconds: int) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s" if secs else f"{mins}m"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m" if mins else f"{hours}h"


def get_video_details(video_id: str, api_key: Optional[str] = None) -> Optional[dict]:
    """Get video details including duration from YouTube API or page scraping."""

    # Try YouTube API first if key is available
    if api_key:
        try:
            url = f"https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "contentDetails,snippet",
                "id": video_id,
                "key": api_key
            }
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("items"):
                item = data["items"][0]
                duration_str = item["contentDetails"]["duration"]
                duration_seconds = parse_duration(duration_str)

                return {
                    "duration_seconds": duration_seconds,
                    "duration_formatted": format_duration(duration_seconds),
                    "title": item["snippet"]["title"],
                    "description": item["snippet"]["description"],
                    "published": item["snippet"]["publishedAt"],
                }
        except Exception as e:
            print(f"  YouTube API error: {e}")

    # Fallback: scrape the video page
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # Look for duration in page data
        match = re.search(r'"lengthSeconds":"(\d+)"', response.text)
        if match:
            duration_seconds = int(match.group(1))
            return {
                "duration_seconds": duration_seconds,
                "duration_formatted": format_duration(duration_seconds),
            }

        return None
    except Exception as e:
        print(f"  Error fetching video details: {e}")
        return None


def get_video_transcript(video_id: str) -> Optional[str]:
    """Fetch video transcript using youtube-transcript-api or fallback methods."""

    # Try youtube-transcript-api if installed (v1.x API)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Create API instance and fetch transcript (v1.x API)
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)

        # Combine transcript segments
        full_transcript = " ".join([snippet.text for snippet in transcript.snippets])

        # Limit length
        if len(full_transcript) > 15000:
            full_transcript = full_transcript[:15000] + "...[truncated]"

        return full_transcript

    except ImportError:
        print("  youtube-transcript-api not installed, using description only")
        return None
    except Exception as e:
        print(f"  Could not fetch transcript: {e}")
        return None


def load_processed_videos() -> dict:
    """Load the list of already processed video IDs."""
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed": [], "last_run": None}


def save_processed_videos(data: dict) -> None:
    """Save the list of processed video IDs."""
    data["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def fetch_channel_videos(channel_id: str) -> list[dict]:
    """Fetch recent videos from a YouTube channel RSS feed."""
    rss_url = get_youtube_rss_feed(channel_id)
    print(f"Fetching RSS feed: {rss_url}")

    videos = []

    try:
        feed = feedparser.parse(rss_url)

        if feed.bozo and feed.bozo_exception:
            print(f"  Warning: Feed parsing issue - {feed.bozo_exception}")

        for entry in feed.entries[:10]:  # Check last 10 videos
            video_id = entry.get("yt_videoid", "")
            if not video_id:
                # Try to extract from link
                link = entry.get("link", "")
                match = re.search(r'v=([a-zA-Z0-9_-]+)', link)
                if match:
                    video_id = match.group(1)

            if not video_id:
                continue

            videos.append({
                "video_id": video_id,
                "title": entry.get("title", ""),
                "description": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "link": f"https://www.youtube.com/watch?v={video_id}",
                "channel": entry.get("author", "Nurture Properties"),
            })

    except Exception as e:
        print(f"Error fetching RSS feed: {e}")

    return videos


def generate_blog_post(video: dict, transcript: str, client: anthropic.Anthropic) -> Optional[str]:
    """Generate a blog post from video content using Claude."""

    today = datetime.now().strftime("%Y-%m-%d")

    # Determine appropriate tags
    tags = []
    content_lower = (video["title"] + " " + video.get("description", "") + " " + (transcript or "")).lower()

    if any(word in content_lower for word in ["how to", "guide", "step", "tutorial", "walkthrough"]):
        tags.append('"Guides"')
    if any(word in content_lower for word in ["tip", "advice", "strategy", "should", "recommend"]):
        tags.append('"Tips"')
    if any(word in content_lower for word in ["news", "update", "announce", "new", "change"]):
        tags.append('"News"')

    if not tags:
        tags.append('"Tips"')  # Default for educational video content

    prompt = BLOG_PROMPT_TEMPLATE.format(
        video_title=video["title"],
        channel_name=video.get("channel", "Nurture Properties"),
        published_date=video.get("published", "Unknown"),
        duration=video.get("duration_formatted", "Unknown"),
        video_url=video["link"],
        video_id=video["video_id"],
        video_description=video.get("description", "No description available"),
        transcript=transcript or "Transcript not available. Generate summary from title and description.",
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
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug[:60]


def save_post(content: str, video: dict) -> Optional[tuple[Path, str]]:
    """Save a blog post to the posts directory."""
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    slug = slugify(video["title"])
    filename = f"{slug}.md"
    filepath = POSTS_DIR / filename

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


def send_email_notification(posts: list[dict]) -> bool:
    """Send email notification about newly published blog posts."""
    smtp_host = os.getenv("EMAIL_SMTP_HOST")
    smtp_port = os.getenv("EMAIL_SMTP_PORT", "587")
    smtp_user = os.getenv("EMAIL_SMTP_USER")
    smtp_password = os.getenv("EMAIL_SMTP_PASSWORD")
    notify_to = os.getenv("EMAIL_NOTIFY_TO", "info@nurtre.io")

    if not all([smtp_host, smtp_user, smtp_password]):
        print("  Warning: Email not configured. Skipping notification.")
        return False

    try:
        if len(posts) == 1:
            subject = f"YouTube Blog: {posts[0]['title']}"
        else:
            subject = f"YouTube Blog Posts: {posts[0]['title']} (+{len(posts) - 1} more)"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #759b8f;">New YouTube Blog Post{'s' if len(posts) > 1 else ''} Published</h2>
            <p>Blog post{'s have' if len(posts) > 1 else ' has'} been auto-generated from your YouTube video{'s' if len(posts) > 1 else ''}:</p>
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
                    YouTube: <a href="{post['video_url']}" style="color: #759b8f;">{post['video_title']}</a>
                </p>
                <p style="margin: 10px 0 0 0;">
                    <a href="{post_url}" style="background: #759b8f; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none; display: inline-block;">
                        View Blog Post
                    </a>
                </p>
            </div>
            """

        html_content += """
            <hr style="border: 1px solid #eee;">
            <p style="color: #999; font-size: 12px;">
                Auto-generated from YouTube by youtube-blog-generator.py
            </p>
        </body>
        </html>
        """

        text_content = f"New YouTube Blog Post{'s' if len(posts) > 1 else ''}\n\n"
        for post in posts:
            post_url = f"{SITE_URL}/blog/{post['slug']}"
            text_content += f"- {post['title']}\n  {post_url}\n  Video: {post['video_url']}\n\n"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = notify_to

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        print(f"  Email notification sent to {notify_to}")
        return True

    except Exception as e:
        print(f"  Error sending email: {e}")
        return False


def main():
    """Main function to run the YouTube blog generator."""
    print("=" * 60)
    print("Nurture YouTube to Blog Generator")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nError: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    youtube_api_key = os.getenv("YOUTUBE_API_KEY")

    # Get channel ID
    global YOUTUBE_CHANNEL_ID
    if not YOUTUBE_CHANNEL_ID:
        print(f"\nFetching channel ID for {YOUTUBE_CHANNEL_HANDLE}...")
        YOUTUBE_CHANNEL_ID = get_channel_id_from_handle(YOUTUBE_CHANNEL_HANDLE)

        if not YOUTUBE_CHANNEL_ID:
            print("Error: Could not determine YouTube channel ID")
            sys.exit(1)

        print(f"Channel ID: {YOUTUBE_CHANNEL_ID}")

    # Initialize Anthropic client
    client = anthropic.Anthropic(api_key=api_key)

    # Load processed videos
    processed_data = load_processed_videos()
    processed_ids = set(processed_data.get("processed", []))

    print(f"\nPreviously processed videos: {len(processed_ids)}")
    if processed_data.get("last_run"):
        print(f"Last run: {processed_data['last_run']}")

    # Fetch channel videos
    print("\n" + "-" * 40)
    print("Fetching recent videos from channel...")
    print("-" * 40)

    videos = fetch_channel_videos(YOUTUBE_CHANNEL_ID)
    print(f"Found {len(videos)} recent videos")

    # Filter out already processed videos
    new_videos = [v for v in videos if v["video_id"] not in processed_ids]
    print(f"New videos to process: {len(new_videos)}")

    if not new_videos:
        print("\nNo new videos found. Exiting.")
        save_processed_videos(processed_data)
        return

    # Process new videos
    posts_created = []

    for i, video in enumerate(new_videos, 1):
        print(f"\n{'=' * 60}")
        print(f"Processing video {i}/{len(new_videos)}")
        print(f"Title: {video['title'][:70]}...")
        print(f"Video ID: {video['video_id']}")

        # Get video details (including duration)
        print("  Fetching video details...")
        details = get_video_details(video["video_id"], youtube_api_key)

        if details:
            video["duration_seconds"] = details.get("duration_seconds", 0)
            video["duration_formatted"] = details.get("duration_formatted", "Unknown")

            # Update description if we got a better one from API
            if details.get("description"):
                video["description"] = details["description"]

            print(f"  Duration: {video['duration_formatted']}")

            # Skip Shorts
            if video["duration_seconds"] < MIN_VIDEO_DURATION_SECONDS:
                print(f"  SKIPPING: Video is a Short ({video['duration_seconds']}s < {MIN_VIDEO_DURATION_SECONDS}s)")
                processed_data["processed"].append(video["video_id"])
                continue
        else:
            print("  Warning: Could not fetch video details, assuming long-form")
            video["duration_formatted"] = "Unknown"

        # Fetch transcript
        print("  Fetching transcript...")
        transcript = get_video_transcript(video["video_id"])

        if transcript:
            print(f"  Transcript: {len(transcript)} characters")
        else:
            print("  No transcript available, using description only")

        # Generate blog post
        blog_content = generate_blog_post(video, transcript, client)

        if blog_content:
            result = save_post(blog_content, video)

            if result:
                post_path, slug = result
                print(f"  Published: {post_path.name}")
                posts_created.append({
                    "title": video["title"],
                    "slug": slug,
                    "file": str(post_path.relative_to(PROJECT_ROOT)),
                    "video_url": video["link"],
                    "video_title": video["title"],
                })

                processed_data["processed"].append(video["video_id"])
            else:
                print(f"  Failed to save post")
        else:
            print(f"  Failed to generate blog post")
            # Still mark as processed to avoid retrying
            processed_data["processed"].append(video["video_id"])

    # Save processed videos list
    save_processed_videos(processed_data)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Videos checked: {len(videos)}")
    print(f"New videos: {len(new_videos)}")
    print(f"Posts created: {len(posts_created)}")

    if posts_created:
        print("\nNewly published posts:")
        for post in posts_created:
            print(f"  - {post['file']}")
            print(f"    URL: {SITE_URL}/blog/{post['slug']}")
            print(f"    Video: {post['video_url']}")

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
