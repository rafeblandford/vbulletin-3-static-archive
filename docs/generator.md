# How the Generator Works

This document explains the build pipeline — how `build.py` turns a vBulletin database into a static website.

## The pipeline

```
MySQL/MariaDB ──→ build.py ──→ Static HTML files
                    │
                    ├── Queries database (forums, threads, posts, users, attachments)
                    ├── Converts BBCode to HTML
                    ├── Rewrites internal links
                    ├── Renders Jinja2 templates
                    ├── Generates sitemaps
                    └── Copies static assets (CSS)
```

The generator connects to the database, runs a series of SQL queries, processes the results in Python, renders HTML through Jinja2 templates, and writes the output to disk. There's no intermediate format — it reads from MySQL and writes HTML files directly.

A full build for the All About Symbian archive (76,783 threads, 449,030 posts) takes ~2 minutes and produces 81,117 HTML files (1.3 GB). The generator is single-threaded and makes no attempt at parallelism — the bottleneck is the database queries, not rendering.

## Why Jinja2

[Jinja2](https://jinja.palletsprojects.com/) is a Python template engine. It was chosen because:

- **It's the standard.** If you've used Flask, Django, or Ansible, you already know the syntax (`{{ variable }}`, `{% for item in list %}`, `{% extends "base.html" %}`).
- **Template inheritance.** A `base.html` defines the page shell (header, nav, footer). Every other template extends it and fills in content blocks. Change the nav once, it updates everywhere.
- **Filters.** Custom filters like `{{ count|commafy }}` (adds thousand separators) are trivial to add.
- **No build tools.** Jinja2 renders at build time in Python. No npm, no webpack, no node_modules. The templates are plain HTML with `{{ }}` markers.
- **Autoescape is off** by design — the BBCode converter produces trusted HTML, and the structured data blocks contain raw JSON-LD. Template variables that need escaping use Jinja's `|e` filter explicitly.

## Templates

Each template extends `base.html` and produces one type of page:

### `base.html` — Page shell

The root template. Defines the HTML structure shared by every page:
- `<head>` with charset, viewport, stylesheet link
- Archive banner (configurable text from `config.yaml`)
- Header with site title and navigation links (from `config.nav_links`)
- `<main>` content area (filled by child templates)
- Footer with configurable text and links

Child templates override blocks: `{% block title %}`, `{% block meta %}`, `{% block head %}` (for page-specific scripts/schema), `{% block breadcrumbs %}`, `{% block content %}`.

### `forum_index.html` — Home page

The forum index at `/`. Shows:
- Stats bar (threads, posts, members, forums)
- Category hierarchy (3 levels: category → sub-category → forum)
- Popular threads table (top N by views, configurable)
- Notable contributors (top N by posts, configurable)
- Schema.org `WebSite` structured data

### `thread_list.html` — Forum listing

One page per forum (plus pagination pages). Shows:
- Breadcrumbs
- Sub-forum links (if the forum has child forums)
- Thread table: title, author, date, replies, views, last post date
- Pagination (configurable threads per page)
- Schema.org `DiscussionForum` structured data

### `thread_view.html` — Thread page

One page per thread (plus pagination for long threads). The most common page type — this is what search engines index. Shows:
- Breadcrumbs
- Thread title, reply count, view count, start date
- Poll notice (text only, if the thread had a poll)
- Post cards: author, date, BBCode-converted content, attachments
- First post gets a blue left border (CSS class `first-post`)
- Pagination (only for threads exceeding the post threshold)
- Schema.org `DiscussionForumPosting` + `BreadcrumbList`
- `data-pagefind-body` attribute on the post list (for Pagefind indexing)

### `stats.html` — Statistics page

Charts and tables showing forum activity. Uses Chart.js (loaded from CDN):
- Posts per month line chart
- Activity by year table
- Busiest days table
- Top forums horizontal bar chart
- Notable contributors

The data is pre-computed as JSON in `build.py` and injected into the template as JavaScript variables.

### `search.html` — Search page

A thin wrapper around [Pagefind](https://pagefind.app/) UI. The search index is built separately after the HTML generation (see [deployment.md](deployment.md)).

### `about.html` — About/privacy page

Static content with configurable site name and stats. Uses the `.prose` CSS class for long-form typography.

### `sis_listing.html` — Custom attachment listing

Lists attachments of a specific file type (`.sis` Symbian packages in the AAS example). This template is optional and controlled by `config.custom_pages.sis_listing`.

## Template variables

Templates receive data as Python dicts/lists from `build.py`. Key variables available in all templates via Jinja2 globals:

| Variable | Type | Available in | Description |
|---|---|---|---|
| `config` | dict | All templates | The full parsed `config.yaml` |
| `base_path` | string | All templates | URL prefix (e.g., `/forum` or empty) |
| `now` | datetime | All templates | Build timestamp |

Page-specific variables are passed via `tpl.render()` — see the `generate_site()` function in `build.py` for the exact data each template receives.

## Configuration reference

The `config.yaml` file controls all site-specific settings. Here's every field:

### Required

```yaml
site:
  name: "Your Forum Archive"       # Full site name, used in titles and headers
  url: "https://example.com"        # Canonical URL (no trailing slash)
  base_path: "/forum"               # URL prefix, or "" for root
  publisher: "Your Name"            # Schema.org publisher

database:
  host: "localhost"                 # MySQL/MariaDB host
  user: "root"                      # Database user
  name: "your_vb_db"                # Database name
```

### Recommended

```yaml
site:
  short_name: "Your Forum"          # Shorter name for descriptions
  description: "What the forum was about"
  date_range: "2001–2013"           # Human-readable, for banners/footers

banner:
  text: "Read-only archive of the {site_name} ({date_range})"
  about_link_text: "About this archive"

nav_links:                          # Header navigation
  - label: "Forums"
    url: "/"
  - label: "Search"
    url: "/search/"
  - label: "Stats"
    url: "/stats/"
  - label: "About"
    url: "/about/"

footer:
  text: "This is a read-only archive of the {site_name}..."
  links:
    - label: "Forum Index"
      url: "/"
```

The `{site_name}` and `{date_range}` placeholders in banner/footer text are replaced at load time.

### Optional

```yaml
database:
  charset: "latin1"                 # Default: latin1. Almost always correct for vB 3.x.

content:
  posts_per_page: 30                # Default: 30. Threads with more posts are paginated.
  threads_per_page: 50              # Default: 50. Threads per forum listing page.
  popular_threads: 15               # Default: 15. Top threads on index page.
  notable_contributors: 40          # Default: 40. Top users shown.
  skip_forums: [62, 61]             # Default: []. Forum IDs to exclude entirely.
  parent_overrides:                 # Default: {}. Override forum hierarchy for display.
    113: 40                         # Move forum 113 under forum 40

custom_pages:
  sis_listing:                      # Optional attachment listing page
    enabled: true
    title: "Symbian App Packages"
    path: "/symbian-apps/"
    description: "..."

nav_links:
  - label: "External"
    url: "https://example.com"
    external: true                  # External links aren't prefixed with base_path
```

### Finding forum IDs for skip_forums and parent_overrides

```sql
-- List all forums with their IDs, parents, and thread counts
SELECT forumid, title, parentid,
    (SELECT COUNT(*) FROM thread t WHERE t.forumid = f.forumid AND t.visible = 1) as threads
FROM forum f
ORDER BY parentid, forumid;
```

Forums with `link` set (redirect forums) are automatically excluded. Use `skip_forums` for forums that exist in the database but shouldn't appear in the archive (e.g., admin-only forums, test forums).

Use `parent_overrides` when the database hierarchy doesn't match how you want the archive to display. For example, if a forum was created as a top-level category but logically belongs under another.

## build_pages.py — Fast rebuild

`build_pages.py` regenerates only the stats, about, search, listing, and index pages — skipping the thread and forum listing pages entirely. This is useful when iterating on page content, styling, or chart configuration.

```bash
python3 build_pages.py -c config.yaml -o ./output/
```

Typical time: ~13 seconds vs ~2 minutes for a full build. The thread pages (which take 95% of the build time) are left untouched on disk.
