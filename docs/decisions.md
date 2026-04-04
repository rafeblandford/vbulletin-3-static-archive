# Design Decisions

This document explains the thinking behind the major design choices in the generator. It's intended both as context for anyone adapting the tool and as a record of the trade-offs we considered.

## Static HTML, not a dynamic viewer

The first decision was whether to build a read-only dynamic app (e.g., a Flask/Django viewer querying the database live) or generate static HTML files.

**We chose static** because:

- **Zero ongoing infrastructure.** No application server, no database, no runtime dependencies. The output is just HTML files served by any web server.
- **Permanence.** Static files are the most durable format for archival content. They'll work in 20 years without maintaining a Python runtime or database server.
- **Performance.** Pre-rendered HTML is as fast as it gets. No database queries at read time.
- **Security.** No attack surface — there's no application to exploit, no SQL injection possible, no user input processing.

The trade-off is that you need to rebuild to update content (which is fine for an archive — the content doesn't change) and that the output can be large (1.3 GB for ~80K pages, though this compresses well).

**Alternative considered:** A lightweight viewer using SQLite as a read-only data source. This would have been simpler to develop but adds a runtime dependency and isn't meaningfully better for content that never changes.

## Design: modern forum layout

We evaluated three design approaches:

1. **Option A — Minimal Reading View.** Clean thread reading with stripped-down chrome. Optimised for content consumption.
2. **Option B — Modern Forum Layout.** Recognisable forum structure (categories, thread tables, post cards) but with modern web design. Familiar to anyone who's used a forum.
3. **Option C — Search-First Portal.** Search as the primary entry point, with forum structure secondary.

**We chose Option B** because:

- The expected audience is a mix of nostalgic former community members and researchers/historians. Former members will recognise and navigate a forum layout instinctively. Researchers will appreciate the structured hierarchy.
- Forum archives are inherently browse-oriented. People often want to explore a topic area, not just find a specific post. A familiar hierarchy supports that.
- We took elements from the other options: clean thread reading from A (the post card design), and search prominence from C (search in the header nav, powered by Pagefind).

## Expected audiences

The design priorities are shaped by who we think will use the archive:

1. **Former community members** returning out of nostalgia or to find specific discussions they remember. They know the forum structure and want to browse familiar topics.
2. **Researchers and historians** studying mobile technology history, the Symbian ecosystem, or online community dynamics. They want structured data, searchable content, and citations.
3. **Search engine users** arriving at specific threads via Google. They need clear context (breadcrumbs, forum name) and readable content.
4. **Developers and archivists** looking to do similar preservation work on other vBulletin forums. They want the tool and documentation.

The priority order matters: we optimised for browsing and reading first, search second, and developer documentation third.

## What to include

A vBulletin database contains a lot more than threads and posts. We had to decide what was worth archiving.

**Included:**
- All publicly visible threads and posts (449,030 posts in our case)
- Forum hierarchy (categories, sub-forums)
- Thread metadata (views, reply counts, dates, authors)
- File attachments stored as BLOBs in the database
- Basic user attribution (usernames on posts)

**Excluded:**
- Private messages — privacy
- Email addresses, IP addresses, passwords, dates of birth — privacy (GDPR)
- User profiles and avatars — adds significant complexity for low archival value; avatars are filesystem files not in the database
- Post edit history — not stored by vBulletin
- Reputation/thanks — low value for a read-only archive
- Content from banned users — already moderated out by `visible=1` filter

**Deliberately kept simple:**
- Polls are shown as text notices ("This thread included a poll: [question]") rather than recreated with vote counts. Only 323 polls existed in the forum — not worth the complexity.
- Smilies are converted to emoji rather than serving the original image files. Simpler and more portable.
- User signatures are stripped. They were repetitive and not part of the discussion.

## Spam filtering

We initially expected to need aggressive spam filtering, but exploration of the data revealed that the original moderators had done excellent work. Of 553 visible threads from banned users, only 2 were actual spam — the rest were legitimate threads from users banned for other reasons. The `visible=1` filter on threads and posts was sufficient.

The 15 highest-velocity spam accounts (hundreds of posts each) had zero visible posts — everything was already cleaned up.

**Lesson:** Check your data before building complex filtering. For well-moderated forums, the existing moderation state in the database is likely sufficient.

## Encoding approach

See [encoding.md](encoding.md) for the full technical explanation. The key decision was to handle the encoding at the connection level rather than post-processing every string, which is both more correct and more performant.

## BBCode conversion

See [bbcode.md](bbcode.md) for the full converter documentation. The key decision was to build a custom regex-based converter rather than using an existing BBCode library, because:

- vBulletin 3.x BBCode has quirks that generic libraries don't handle (the `[QUOTE=user;postid]` format, `[ATTACH]` tags, `[addsig]` markers, legacy HTML comments from phpBB migration)
- We need to resolve internal links (showthread.php → archive URLs)
- We need to resolve attachment references to actual files
- The converter is ~100 lines — simple enough to debug and extend for edge cases

## Pagination thresholds

- **50 threads per page** on forum listings — balances information density with page load time
- **30 posts per page** on thread pages — the first page of a thread should feel complete for short discussions (most threads have <30 posts), while long threads are paginated to keep pages manageable
- Only threads with more than 30 posts are paginated at all — no pagination UI for short threads

## Schema.org structured data

Every page has appropriate Schema.org JSON-LD:

- **Thread pages:** `DiscussionForumPosting` with headline, author, date, reply/view counts, plus `BreadcrumbList`
- **Forum listings:** `DiscussionForum` linked to the parent `WebSite`
- **Forum index:** `WebSite` with publisher

This helps search engines understand the content structure and can produce rich results for forum content.

## Search via Pagefind

Rather than building server-side search or relying solely on Google, we use [Pagefind](https://pagefind.app/) — a static search library that:

- Builds an index as a post-processing step after the HTML is generated
- Runs entirely client-side via WebAssembly
- Loads only the index chunks needed for each query (~100–300 KB per search)
- Requires zero server resources

For the All About Symbian archive (78,722 pages), the index is 430 MB on disk but users only download a tiny fraction per search. The indexing step takes ~3.5 minutes.

The `data-pagefind-body` attribute on the post-list container ensures Pagefind indexes the actual discussion content rather than navigation chrome.

## Sitemap splitting

Google Search Console rejects sitemaps with more than 50,000 URLs. The generator automatically splits sitemaps and creates a sitemap index file. This is transparent — you just submit `sitemap.xml` and Google follows the index to the individual files.

## CSS approach

A single CSS file with CSS custom properties for theming. No build tools, no preprocessors. The design uses system fonts for performance and accessibility. The colour palette is customisable via the CSS variables at the top of `style.css`.

Responsive design is handled with a single `@media (max-width: 768px)` breakpoint that hides less-important table columns and adjusts layout for mobile.
