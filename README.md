# vBulletin Static Archive Generator

Generate a complete, self-contained static HTML archive from a vBulletin 3.x MySQL database. One command produces a browsable website with forum index, thread pages, BBCode rendering, full-text search, statistics, Schema.org structured data, and sitemaps.

Built to archive the [All About Symbian](https://allaboutsymbian.com/forum/) forum (76,000+ threads, 449,000 posts, 2001–2013) — now [live and searchable](https://allaboutsymbian.com/forum/).

## What it does

Given a vBulletin 3.8 MySQL/MariaDB database dump, the generator produces:

- **Forum index** with full category hierarchy, popular threads, notable contributors
- **Thread listings** with pagination (configurable threads per page)
- **Thread pages** with complete BBCode-to-HTML conversion, paginated for long threads
- **Statistics page** with Chart.js visualisations (posts over time, top forums, busiest days)
- **Full-text search** via [Pagefind](https://pagefind.app/) (client-side, zero server resources)
- **Schema.org structured data** (DiscussionForumPosting, BreadcrumbList, DiscussionForum, WebSite)
- **Split sitemaps** respecting Google's 50,000 URL limit
- **About/privacy page** with GDPR notice
- **Attachment references** with inline images and download links

For the All About Symbian forum, this generates **81,117 static HTML pages (1.3 GB) in ~110 seconds** on a Xeon E-2136.

## What it doesn't do

This tool works with what's in the vBulletin database. It's worth understanding what that means — and what it doesn't include:

- **No user avatars or profile images.** vBulletin stores avatar paths in the database but the actual files lived on the web server's filesystem. If you have the original server files, you could add avatar support.
- **No post edit history.** vBulletin stores the current version of each post, not revision history.
- **No user profiles.** The generator creates an archive of discussions, not a user directory. Usernames appear on posts but there are no profile pages.
- **No private messages.** Excluded by design (privacy).
- **No reputation/thanks data.** vBulletin stores these but they add complexity without much archival value.
- **No working polls.** Poll questions are shown as text notices; the interactive voting UI is not reproduced.
- **No search initially.** The generator creates a Pagefind-ready page, but you need to run `pagefind` separately after the build to create the search index (see [Deployment](docs/deployment.md)).

The focus is on preserving the *discussions* — the actual content people came to forums for. Design decisions are documented in [docs/decisions.md](docs/decisions.md).

## Quick start

### Prerequisites

- Python 3.8+
- A vBulletin 3.x MySQL/MariaDB database (imported and accessible)
- `pip install -r requirements.txt`

### Setup

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your site details, database connection, etc.
```

### Build

```bash
# Full build
python3 build.py -c config.yaml -o ./output/

# Test with a single forum
python3 build.py -c config.yaml -o ./output/ --forum 91

# Limit threads per forum (useful for testing)
python3 build.py -c config.yaml -o ./output/ --limit 50

# Database password via environment variable
export ARCHIVE_DB_ROOT_PASSWORD=yourpassword
python3 build.py -c config.yaml -o ./output/
```

### Deploy

The output is plain static HTML. Serve it with any web server:

```bash
# Quick local preview
cd output && python3 -m http.server 8000

# Or deploy to your web server
rsync -av output/ user@server:/var/www/forum/
```

See [docs/deployment.md](docs/deployment.md) for Caddy/nginx configuration, Pagefind setup, Cloudflare considerations, and URL redirects from the original vBulletin URLs.

## Configuration

All site-specific settings live in `config.yaml`. See `config.example.yaml` for the full reference — it's the actual configuration used for the All About Symbian archive.

Key sections:
- **site** — name, URL, base path, date range, publisher
- **banner/footer** — text with `{site_name}` and `{date_range}` placeholders
- **nav_links** — header navigation (internal and external links)
- **database** — host, user, database name, charset
- **content** — pagination settings, forums to skip, hierarchy overrides
- **custom_pages** — optional extras like the .sis file listing

## Documentation

| Document | What it covers |
|---|---|
| [docs/decisions.md](docs/decisions.md) | Design decisions, feature priorities, and trade-offs |
| [docs/database.md](docs/database.md) | What you need from vBulletin, schema notes, importing |
| [docs/encoding.md](docs/encoding.md) | The MySQL latin1/cp1252 encoding problem and fix |
| [docs/bbcode.md](docs/bbcode.md) | BBCode converter: what's handled, edge cases, extending |
| [docs/deployment.md](docs/deployment.md) | Web server config, Pagefind, Cloudflare, URL redirects |
| [docs/development.md](docs/development.md) | How this project was built (with Claude Code) |

## Real-world example

The All About Symbian forum archive is live at **[allaboutsymbian.com/forum/](https://allaboutsymbian.com/forum/)**:

- 76,783 threads, 449,030 posts from 39,542 members
- 88 active forums in a 3-level hierarchy
- 3,929 file attachments (327 MB)
- Lighthouse scores: 100 / 100 / 100 / 100
- Full-text search across all content via Pagefind
- Sitemaps submitted to Google Search Console

## How this was built

This project was built collaboratively with [Claude Code](https://claude.ai/claude-code) (Anthropic's CLI coding tool) over an extended session. The entire process — from database exploration through design prototyping, generator development, iterative debugging, deployment, and documentation — was done in conversation with Claude Code, supervised by Rafe Blandford.

See [docs/development.md](docs/development.md) for the full story, including what worked well and what required human judgment.

## Licence

MIT. See [LICENSE](LICENSE).
