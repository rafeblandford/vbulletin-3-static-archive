# Deployment

## Basic deployment

The generator output is plain static HTML. Any web server works:

```bash
# Build
python3 build.py -c config.yaml -o ./output/

# Deploy
rsync -av --delete output/ user@server:/var/www/forum/
```

## Adding search with Pagefind

The generator creates a search page (`/search/`) with Pagefind UI, but you need to build the search index separately after generating the HTML:

```bash
# Install Pagefind
curl -sL https://github.com/CloudCannon/pagefind/releases/latest/download/pagefind_extended-linux-x86_64.tar.gz | tar xz

# Build the index (run from the output directory)
./pagefind --site ./output/ --bundle-dir pagefind
```

This indexes all pages with `data-pagefind-body` attributes (the post content on thread pages) and creates a `pagefind/` directory in the output.

For the All About Symbian archive (78,722 pages):
- Indexing time: ~3.5 minutes
- Index size on disk: 430 MB
- Per-query download: ~100–300 KB (chunked index, loads on demand)

Pagefind runs entirely client-side via WebAssembly — no server resources are used at search time.

## Web server configuration

### Caddy

```
example.com {
    root * /var/www/forum
    file_server
    encode gzip

    # Cache static assets
    @static path *.css *.js *.png *.jpg *.gif
    header @static Cache-Control "public, max-age=31536000, immutable"

    # Cache HTML pages (content doesn't change in an archive)
    @html path *.html */
    header @html Cache-Control "public, max-age=86400"

    # vBulletin URL redirects (if replacing an existing vBulletin install)
    @showthread query t=*
    redir @showthread /thread/{query.t}/ permanent

    @forumdisplay query f=*
    redir @forumdisplay /f/{query.f}/ permanent
}
```

### Nginx

```nginx
server {
    listen 80;
    server_name example.com;
    root /var/www/forum;
    index index.html;

    gzip on;
    gzip_types text/html text/css application/javascript;

    location ~* \.(css|js|png|jpg|gif)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # vBulletin URL redirects
    location /showthread.php {
        if ($arg_t) {
            return 301 /thread/$arg_t/;
        }
        if ($arg_p) {
            return 301 /thread/?post=$arg_p;
        }
    }

    location /forumdisplay.php {
        if ($arg_f) {
            return 301 /f/$arg_f/;
        }
    }
}
```

## Cloudflare considerations

If you use Cloudflare in front of your server:

### Cache headers
Be careful with `Cache-Control: immutable` on HTML pages. If you deploy a broken page, Cloudflare will cache the error for the full TTL. Use shorter cache durations for HTML (e.g., `max-age=86400`) and reserve `immutable` for truly static assets (CSS, JS, images).

### Cache purging
If you need to invalidate cached content:
- **Single URL:** Cloudflare dashboard → Caching → Purge by URL
- **Everything:** API call to `purge_everything` — use sparingly
- **Cache bypass rule:** As a temporary measure, create a Cache Rule matching your forum path with "Bypass Cache"

### CSP headers
If you're using Content Security Policy, you'll need to allow:
- `cdn.jsdelivr.net` for Chart.js (stats page)
- `'self'` for Pagefind (served from your own domain)
- `'unsafe-inline'` for Chart.js initialisation scripts in the stats template (or move them to an external file)

## Sitemaps and Google Search Console

The generator creates split sitemaps automatically (50,000 URLs max per file):

```
/sitemap.xml          → sitemap index
/sitemap-1.xml        → first 49,000 URLs
/sitemap-2.xml        → remaining URLs
```

Submit `/sitemap.xml` to Google Search Console. Google will follow the index to the individual sitemaps.

### Gotchas
- GSC rejects sitemaps with >50,000 URLs — the generator handles this automatically
- GSC may take days to weeks to fully index large archives
- The `<priority>` values in the sitemap are hints only — Google may ignore them

## Attachment extraction

If your vBulletin database stores attachments as BLOBs (the default for many installs), you'll need to extract them to the filesystem before or after building. Use the included `extract_attachments.py` script:

```bash
python3 extract_attachments.py -c config.yaml -o ./output/attachments/
```

This reads the same `config.yaml` as the main generator. It extracts both full-size files and thumbnails (to an `attachments/thumbs/` subdirectory).

This is a separate script because it only needs to run once — attachments don't change in an archive, so there's no need to re-extract on every build.

## Hosting costs

A static archive is cheap to host. The All About Symbian archive (1.3 GB, 81K pages) runs on a shared hosting server alongside other sites. Traffic is modest (historical content, not viral) — a basic VPS or even static hosting (Cloudflare Pages, Netlify, GitHub Pages) would work.

The Pagefind index adds ~430 MB but is chunked and loaded on demand, so bandwidth impact is minimal.
