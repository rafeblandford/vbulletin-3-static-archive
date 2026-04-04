# How This Project Was Built

This project was built collaboratively with [Claude Code](https://claude.ai/claude-code), over an extended session in early April 2026. This document describes the process honestly - what was done by AI, what required human judgment, and how the collaboration worked.

## The setup

**Human:** Rafe, who ran the All About Symbian website and had recovered a MySQL database dump from a 2020 server backup... and was wondering how to make it available with a reasonable amount of effort.

**AI:** Claude Code (Claude Opus), operating via SSH on a remote server (for database access and builds) and locally (for design prototyping and file editing).

**The goal:** Turn a 1.6 GB vBulletin database dump into a browsable, searchable, well-indexed static archive, allowing for easy and public access and longer term preservation.

## What Claude Code did

- **Database exploration:** Imported the dump, queried the schema, assessed data quality (post counts, spam levels, encoding, date ranges, attachment types)
- **Research:** Generated 6 research documents covering vBulletin schema analysis, static generation approaches, encoding issues, Pagefind feasibility, and design options
- **Design prototyping:** Built HTML/CSS prototypes for three design approaches, exported sample data as JSON, rendered test pages
- **Generator development:** Wrote the Python generator (~860 lines), Jinja2 templates, CSS, BBCode converter
- **Iterative debugging:** Fixed encoding issues, Caddy configuration, Cloudflare caching, sitemap splitting, accessibility contrast ratios — each discovered through testing and fixed in the same session
- **SEO:** Schema.org structured data, sitemaps, canonical URLs, meta descriptions
- **Documentation:** Session logs, research docs, this README and docs directory

## What required human judgment

- **Design direction:** Rafe chose Option B (Modern Forum) over the other two prototypes, with specific feedback on spacing, icons, hierarchy presentation
- **Content scope:** What to include vs exclude (e.g., keeping all zero-reply threads, showing polls as text only, stripping signatures)
- **Forum hierarchy overrides:** Which forums to reclassify (e.g., "Symbian^3 phones" should appear under "S60" not as a top-level category)
- **Date range for display:** "2001–2013" rather than "2001–2018" — the community was effectively dormant after 2013 even though the database ran until 2018
- **Privacy decisions:** The GDPR approach, what counts as personal data in this context, the Article 89 archiving exemption
- **Quality review:** Spotting visual issues (spacing, breadcrumb duplication, missing usernames on early posts) that required reading the actual rendered pages
- **Deployment path:** Where to host, how to configure Caddy alongside existing sites, when to rebuild after fixes

## What worked well

- **Speed of iteration.** Going from "here's a database dump" to "81,000 pages deployed with perfect Lighthouse scores" in a single session. The AI handled boilerplate, SQL queries, regex patterns, and template markup very efficiently.
- **Research breadth.** Running 5-6 background research agents simultaneously to explore the database, evaluate approaches, and assess tools — all before writing a single line of generator code.
- **Planning loops.** Spending time thinking and plannig about what was required sped up later phases. Critically making decisions about was not required simplified the project. It also allowed for the creation of artefacts (essentially Product Requirements Document and a Technical Solution Document) that both gave confidence and helped keep things on track during the implementation and iteration phase. 
- **Debugging loops.** When things went wrong (encoding errors, Caddy misconfiguration, Cloudflare caching a 404), the AI could diagnose, propose fixes, test, and iterate without losing context.
- **Documentation.** Having the AI write docs while everything was still in context meant the technical details were captured accurately.

## What was harder

- **Product sense, audience and contextual knowledge.** Assessing the requirements and tradeoffs for difference audiences (information seekers, nostalgia, historical/researchers) required human input and consideration, which the AI sometimes pulled against. The same applied to the contextual knowledge of the forum and how it operated, with some decision reflected it developing over multiple years.
- **Visual design.** The AI could generate CSS and HTML structure but needed human eyes to judge whether spacing "looked right" or if a hierarchy presentation was intuitive. Screenshots and iterative feedback were essential.
- **Caddy configuration.** The interaction between Caddy's route matching, an existing `archive-rewrites` snippet, and Docker container reload behaviour required several rounds of debugging. The AI's fix attempts were logical but the environment was complex enough that systematic testing was needed.
- **Encoding.** The pymysql `latin1` → `cp1252` mapping issue was solved correctly, but only after trying three other approaches that failed for non-obvious reasons. The AI was thorough but the problem space had several plausible-looking dead ends.

## Takeaways

This was a genuine collaboration, not just "AI writes code, human approves." The human brought domain knowledge (understanding the community, editorial judgment about content scope, visual taste) while the AI brought technical execution speed, breadth of knowledge (SQL, Python, CSS, Caddy, Cloudflare, Schema.org, Pagefind), and the ability to hold the full context of a complex project in a single session.

The code is real, tested against real data, and running in production. It's not a prototype or demo - it's the actual tool that built [allaboutsymbian.com/forum/](https://allaboutsymbian.com/forum/).

## Tools used

- **Claude Code** (Anthropic) — primary development tool
- **Python 3** with pymysql and Jinja2 — generator
- **MariaDB** — database
- **Caddy** — web server
- **Cloudflare** — CDN and DNS
- **Pagefind** — client-side search
- **Chart.js** — statistics visualisations
