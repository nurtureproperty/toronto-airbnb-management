# How to Publish a Blog Post from a URL

This guide explains how to create and publish a blog post on nurturestays.ca from any news article URL.

---

## Writing Style Guidelines

The blog generator follows these rules to create natural, human-sounding content that avoids AI detection.

### Punctuation Rules
- **No em dashes** (the long dash). Use commas, periods, or parentheses instead.
- **No semicolons** in casual content. Break into two sentences instead.
- Use contractions naturally (don't, won't, it's, we're, you'll, that's, here's)

### Banned Words (AI-typical, never use)
- delve, dive into, navigate, landscape, realm
- crucial, vital, essential, key (overused)
- leverage, utilize (use "use" instead)
- robust, comprehensive, streamline, optimize
- game-changer, cutting-edge, revolutionary, innovative
- multifaceted, synergy, paradigm, holistic
- world-class, top-notch, best-in-class, state-of-the-art

### Banned Phrases
- "In today's world", "In this day and age"
- "It's important to note", "It's worth mentioning"
- "Firstly", "Secondly", "Lastly"
- "In conclusion", "To sum up", "In summary"
- "When it comes to", "At the end of the day"
- "Moving forward", "Going forward"

### Tone and Style
- Write like you're explaining to a friend over coffee
- Use short, punchy sentences mixed with longer ones. Vary your rhythm.
- Start some sentences with "And" or "But" for natural flow
- Add casual transitions: "Here's the thing," "Look," "Honestly," "So," "Now,"
- Include rhetorical questions ("So what does this mean for your rental?")
- Add personal opinions ("This is great news" or "I'm not convinced this will work")
- Reference specific Toronto neighborhoods, GTA landmarks, Ontario details
- Throw in slightly imperfect phrasing. Real humans don't write perfectly.

### Structure
- Skip generic intros. Get to the point in the first sentence.
- Vary paragraph lengths. Some short (1-2 sentences), some longer.
- End sections with specific, actionable advice
- Cite specific facts, numbers, and dates from the source
- End with a natural CTA, not a forced sales pitch

### Tags and Categories
All blog posts must use only these 3 tags/categories:
- **News** - Current events, announcements, market updates, industry trends
- **Tips** - Actionable advice, strategies, recommendations, best practices
- **Guides** - Comprehensive how-to content, regulation guides, step-by-step instructions

The script automatically assigns tags based on content keywords. Posts can have multiple tags if relevant.

---

## Prerequisites

1. **Python installed** - Python 3.11+ must be installed on your computer
2. **API key configured** - The `.env` file must have your `ANTHROPIC_API_KEY` set
3. **Dependencies installed** - Run this once if you haven't already:
   ```
   pip install anthropic feedparser requests beautifulsoup4 python-dotenv
   ```

---

## Step-by-Step Instructions

### Step 1: Find an Article

Find a relevant news article about:
- Airbnb or short-term rentals
- Toronto/GTA real estate or housing
- Travel trends in Ontario/Canada
- Rental regulations or bylaws

Copy the full URL of the article.

### Step 2: Open PowerShell

1. Press `Windows + X`
2. Click **Windows Terminal** or **PowerShell**

### Step 3: Navigate to the Project Folder

```powershell
cd C:\Users\jef_p\toronto-airbnb-management
```

### Step 4: Run the Script with Your URL

```powershell
python scripts/create-blog-from-url.py "YOUR_URL_HERE"
```

**Example:**
```powershell
python scripts/create-blog-from-url.py "https://news.airbnb.com/2024-summer-release/"
```

### Step 5: Wait for Generation

The script will:
1. Fetch the article content
2. Generate an SEO-optimized blog post using AI
3. Save it to `src/content/blog/`
4. Send you an email notification with the post details

This takes about 30-60 seconds.

### Step 6: Push to Publish

After the script completes, push the changes to publish:

```powershell
git add .
git commit -m "Add new blog post"
git push
```

The site will automatically deploy within a few minutes.

---

## Multiple URLs at Once

You can create multiple posts by running the script multiple times:

```powershell
python scripts/create-blog-from-url.py "https://example.com/article1"
python scripts/create-blog-from-url.py "https://example.com/article2"
```

Then commit all at once:
```powershell
git add .
git commit -m "Add new blog posts"
git push
```

---

## Troubleshooting

### "Python was not found"
Install Python from the Microsoft Store or python.org

### "No module named 'anthropic'"
Run: `pip install anthropic feedparser requests beautifulsoup4 python-dotenv`

### "Could not fetch article"
- Check that the URL is correct and accessible
- Some sites block automated access - try a different source

### "ANTHROPIC_API_KEY not set"
Make sure the `.env` file exists with your API key

### Post not appearing on website
1. Make sure you ran `git push`
2. Wait 2-3 minutes for deployment
3. Check the URL matches the slug (no date prefix)

---

## Where Posts Are Saved

- **Local files:** `src/content/blog/[slug].md`
- **Live URL:** `https://www.nurturestays.ca/blog/[slug]`

---

## Email Notifications

After each post is created, you'll receive an email at info@nurtre.io with:
- Post title
- Post URL
- Summary of the content

---

## Quick Reference

| Action | Command |
|--------|---------|
| Navigate to project | `cd C:\Users\jef_p\toronto-airbnb-management` |
| Create post from URL | `python scripts/create-blog-from-url.py "URL"` |
| Commit changes | `git add . && git commit -m "Add blog post"` |
| Push to publish | `git push` |

---

*Last updated: January 2026*
