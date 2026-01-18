# Nurture Blog Generator Scripts

Automated blog post generation system for the Nurture Airbnb Property Management website. These scripts scan news sources for relevant short-term rental content, generate SEO-optimized blog posts using the Claude API, **auto-publish them**, and **send email notifications**.

## Quick Start

### 1. Install Dependencies

```bash
pip install anthropic feedparser requests beautifulsoup4 python-dotenv
```

### 2. Set Up Environment Variables

Copy the environment template and configure:

```bash
cp .env.example .env
# Edit .env with your API key and email settings
```

Required variables:
- `ANTHROPIC_API_KEY` - Get at https://console.anthropic.com/
- `EMAIL_SMTP_HOST` - Your SMTP server (e.g., smtp.gmail.com)
- `EMAIL_SMTP_PORT` - Usually 587
- `EMAIL_SMTP_USER` - Your email address
- `EMAIL_SMTP_PASSWORD` - App password (for Gmail, generate at https://myaccount.google.com/apppasswords)
- `EMAIL_NOTIFY_TO` - Where to send notifications (default: info@nurture.io)

### 3. Run the Scripts

```bash
# Automatic RSS scan - finds and publishes all new relevant articles
python scripts/blog-generator.py

# Create from specific URL
python scripts/create-blog-from-url.py "https://example.com/article"
```

---

## How It Works

1. **Scans RSS feeds** for relevant short-term rental news
2. **Filters articles** using keywords (Toronto, Ontario, Airbnb, STR, etc.)
3. **Fetches full article content** from source URLs
4. **Generates blog posts** using Claude API with your brand voice
5. **Auto-publishes** to `src/content/blog/posts/`
6. **Sends email notification** to info@nurture.io with links to new posts

---

## Scripts

### `blog-generator.py` - Automatic RSS Scanner

Scans configured RSS feeds and auto-publishes relevant articles.

```bash
python scripts/blog-generator.py
```

**What it does:**
- Fetches articles from all configured RSS feeds
- Filters for relevant content (STR, Airbnb, Ontario, Toronto, GTA)
- Skips already-processed articles
- Generates and publishes blog posts
- Sends email notification with links to new posts

---

### `create-blog-from-url.py` - Manual URL Generator

Create and publish blog posts from specific article URLs.

**Single URL:**
```bash
python scripts/create-blog-from-url.py "https://news.airbnb.com/some-announcement"
```

**Multiple URLs:**
```bash
python scripts/create-blog-from-url.py "url1" "url2" "url3"
```

**Force Regenerate (bypass duplicate check):**
```bash
python scripts/create-blog-from-url.py --force "https://example.com/article"
```

---

## Configuration

### Adding/Removing News Sources

Edit `blog-generator.py` and modify the `RSS_FEEDS` list:

```python
RSS_FEEDS = [
    {
        "name": "Source Name",
        "url": "https://example.com/feed/",
        "priority": "high"  # or "medium"
    },
]
```

**Google News RSS Format:**
```python
{
    "name": "Google News - Your Search",
    "url": "https://news.google.com/rss/search?q=your+search+terms&hl=en-CA&gl=CA&ceid=CA:en",
    "priority": "high"
}
```

### Adjusting Relevance Filters

Edit the `RELEVANCE_KEYWORDS` dictionary in `blog-generator.py`:

```python
RELEVANCE_KEYWORDS = {
    "high_priority": [
        "toronto", "ontario", "gta", ...
    ],
    "medium_priority": [
        "airbnb", "short term rental", ...
    ],
    "exclude": [
        "stock price", "ipo", ...
    ]
}
```

---

## GitHub Actions Automation

The workflow runs automatically:

- **Schedule:** Daily at 9am EST (14:00 UTC)
- **Manual:** Can be triggered from GitHub Actions tab

**Required Secrets** (Settings → Secrets → Actions):
- `ANTHROPIC_API_KEY`
- `EMAIL_SMTP_HOST`
- `EMAIL_SMTP_PORT`
- `EMAIL_SMTP_USER`
- `EMAIL_SMTP_PASSWORD`
- `EMAIL_NOTIFY_TO`

---

## Email Notifications

When new posts are published, you'll receive an email with:
- Post title and link
- Source article URL
- Direct "View Post" button

**Email Setup for Gmail:**
1. Enable 2-factor authentication
2. Generate App Password at https://myaccount.google.com/apppasswords
3. Use the app password (not your regular password) in `EMAIL_SMTP_PASSWORD`

---

## File Structure

```
scripts/
├── blog-generator.py         # Main RSS scanner (auto-publish + email)
├── create-blog-from-url.py   # Manual URL generator (auto-publish + email)
├── processed_articles.json   # Tracks processed articles
├── requirements.txt          # Python dependencies
└── README.md                 # This file

src/content/blog/
└── posts/                    # Published posts go here
    └── YYYY-MM-DD-slug.md

.github/workflows/
└── blog-generator.yml        # Daily automation

.env                          # Your API keys (not committed)
.env.example                  # Template
```

---

## Troubleshooting

### "ANTHROPIC_API_KEY environment variable not set"

Make sure your `.env` file exists and contains the API key.

### "Email not configured. Skipping notification."

Set all EMAIL_* variables in your `.env` file.

### Gmail: "Username and Password not accepted"

- Enable 2-factor authentication
- Use an App Password, not your regular password
- Generate at: https://myaccount.google.com/apppasswords

### "This URL has already been processed"

Use the `--force` flag:
```bash
python scripts/create-blog-from-url.py --force "https://example.com/article"
```

---

## Writing Style

The Claude prompt is configured to:
- Write in Nurture's brand voice
- Avoid unnecessary hyphens in adjectives
- Use contractions and casual transitions
- Include local GTA references
- Add opinions and editorial takes
- Avoid AI-typical phrases
- Include internal links to service pages
- End with a CTA mentioning Nurture

---

## Support

For issues, check the repository or contact the development team.
