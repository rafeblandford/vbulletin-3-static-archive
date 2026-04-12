#!/usr/bin/env python3
"""
vBulletin Static Archive Generator

Generates a complete static HTML archive from a vBulletin 3.8 MySQL/MariaDB
database. Produces forum index, thread listings, thread pages with BBCode
conversion, statistics, search page, sitemaps, and Schema.org structured data.

Built with Claude Code (Anthropic) — see docs/development.md for background.

Usage:
    python3 build.py -c config.yaml -o ./site/                    # Full build
    python3 build.py -c config.yaml -o ./site/ --forum 91         # Single forum
    python3 build.py -c config.yaml -o ./site/ --limit 500        # First 500 threads
"""

import argparse
import html
import json
import math
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone

import pymysql
import yaml
from jinja2 import Environment, FileSystemLoader

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(path):
    """Load and validate the YAML configuration file."""
    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Resolve banner/footer template strings
    site_name = config['site']['name']
    date_range = config['site']['date_range']

    banner = config.get('banner', {})
    if 'text' in banner:
        banner['text'] = banner['text'].format(
            site_name=site_name, date_range=date_range)

    footer = config.get('footer', {})
    if 'text' in footer:
        footer['text'] = footer['text'].format(
            site_name=site_name, date_range=date_range)

    # Ensure base_path has no trailing slash
    config['site']['base_path'] = config['site'].get('base_path', '').rstrip('/')

    # Defaults for content settings
    content = config.setdefault('content', {})
    content.setdefault('posts_per_page', 30)
    content.setdefault('threads_per_page', 50)
    content.setdefault('popular_threads', 15)
    content.setdefault('notable_contributors', 40)
    content.setdefault('skip_forums', [])
    content.setdefault('parent_overrides', {})

    return config


# Image extensions for attachment display
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'bmp'}

# ---------------------------------------------------------------------------
# BBCode to HTML converter
# ---------------------------------------------------------------------------

SMILIE_MAP = {
    ":)": "\U0001f60a", ":-)": "\U0001f60a", ";)": "\U0001f609", ";-)": "\U0001f609",
    ":D": "\U0001f603", ":-D": "\U0001f603", ":(": "\U0001f61e", ":-(": "\U0001f61e",
    ":o": "\U0001f62e", ":-o": "\U0001f62e", ":p": "\U0001f61b", ":-p": "\U0001f61b",
    ":rolleyes:": "\U0001f644", ":cool:": "\U0001f60e", ":eek:": "\U0001f631",
    ":confused:": "\U0001f615", ":mad:": "\U0001f621",
}


def bbcode_to_html(text):
    """Convert vBulletin BBCode to HTML.

    Handles the full range of vBulletin 3.x BBCode including:
    - Standard formatting: [b], [i], [u], [s], [color], [size]
    - Links and images: [url], [img]
    - Quotes with attribution: [QUOTE=username;postid]
    - Code blocks: [code]
    - Lists: [list][*]items[/list]
    - Attachments: [ATTACH]id[/ATTACH] (resolved later with actual files)
    - Legacy markers: [addsig], HTML comments
    - Smilies: both image tags and text codes converted to emoji
    """
    if not text:
        return ""

    # Strip legacy markers
    text = re.sub(r'\[addsig\]', '', text)
    text = re.sub(r'<!--.*?-->', '', text)

    # Escape HTML first (BBCode tags will be converted back)
    text = html.escape(text)

    # [b], [i], [u], [s]
    text = re.sub(r'\[b\](.*?)\[/b\]', r'<strong>\1</strong>', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\[i\](.*?)\[/i\]', r'<em>\1</em>', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\[u\](.*?)\[/u\]', r'<u>\1</u>', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\[s\](.*?)\[/s\]', r'<s>\1</s>', text, flags=re.DOTALL | re.IGNORECASE)

    # [color=X]
    text = re.sub(r'\[color=([^\]]+)\](.*?)\[/color\]',
                  r'<span style="color:\1">\2</span>', text, flags=re.DOTALL | re.IGNORECASE)

    # [size=X]
    text = re.sub(r'\[SIZE=(\d+)\](.*?)\[/SIZE\]',
                  r'<span class="text-size-\1">\2</span>', text, flags=re.DOTALL | re.IGNORECASE)

    # [url=X]...[/url] and [url]...[/url]
    def url_replace(m):
        url = m.group(1)
        link_text = m.group(2)
        url = url.replace('&quot;', '').replace('&amp;', '&')
        if not url.startswith(('http', 'https', 'ftp', '/')):
            url = 'http://' + url
        return f'<a href="{url}" rel="nofollow">{link_text}</a>'

    text = re.sub(r'\[url=([^\]]+)\](.*?)\[/url\]', url_replace,
                  text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\[url\](.*?)\[/url\]',
                  lambda m: f'<a href="{m.group(1).replace("&amp;", "&")}" rel="nofollow">{m.group(1)}</a>',
                  text, flags=re.DOTALL | re.IGNORECASE)

    # [img]
    text = re.sub(r'\[img\](.*?)\[/img\]',
                  r'<img src="\1" loading="lazy" alt="User posted image" class="post-image">',
                  text, flags=re.DOTALL | re.IGNORECASE)

    # [QUOTE=username;postid] and [QUOTE]
    def quote_replace(m):
        username = m.group(1) if m.group(1) else ""
        postid = m.group(2) if m.group(2) else ""
        content = m.group(3)
        cite = f'<cite>{html.escape(username)} wrote:</cite>' if username else ''
        if postid:
            cite = f'<cite><a href="#post{postid}" style="color: inherit;">{html.escape(username)} wrote:</a></cite>'
        return f'<blockquote class="post-quote">{cite}{content}</blockquote>'

    # Handle nested quotes (run multiple passes)
    for _ in range(5):
        new_text = re.sub(r'\[QUOTE=([^;\]]*);?(\d*)\](.*?)\[/QUOTE\]', quote_replace,
                          text, flags=re.DOTALL | re.IGNORECASE)
        if new_text == text:
            break
        text = new_text

    text = re.sub(r'\[QUOTE\](.*?)\[/QUOTE\]',
                  r'<blockquote class="post-quote">\1</blockquote>', text, flags=re.DOTALL | re.IGNORECASE)

    # [code]
    text = re.sub(r'\[code\](.*?)\[/code\]',
                  r'<pre class="post-code"><code>\1</code></pre>', text, flags=re.DOTALL | re.IGNORECASE)

    # [list] [*] [/list]
    def list_replace(m):
        items = re.split(r'\[\*\]', m.group(1))
        items = [i.strip() for i in items if i.strip()]
        li = "".join(f"<li>{i}</li>" for i in items)
        return f"<ul>{li}</ul>"

    text = re.sub(r'\[list\](.*?)\[/list\]', list_replace, text, flags=re.DOTALL | re.IGNORECASE)

    # [ATTACH]NNN[/ATTACH] — resolved later with actual attachment files
    text = re.sub(r'\[ATTACH\](\d+)\[/ATTACH\]',
                  r'<!-- ATTACH:\1 -->', text, flags=re.IGNORECASE)

    # Legacy smilie images -> emoji
    text = re.sub(r'<img src=&quot;/phpBB/images/smiles/[^&]*&quot;[^>]*>', '\U0001f60a', text)

    # Smilie text codes
    for code, emoji in SMILIE_MAP.items():
        escaped = html.escape(code)
        text = text.replace(escaped, emoji)

    # Line breaks
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r'\n\n+', '</p><p>', text)
    text = text.replace("\n", "<br>")
    text = f"<p>{text}</p>"

    return text


def rewrite_internal_links(text, post_thread_map, base_path):
    """Rewrite vBulletin internal links to archive URLs."""
    text = re.sub(r'showthread\.php\?t=(\d+)',
                  lambda m: f'{base_path}/thread/{m.group(1)}/', text)

    def resolve_post(m):
        pid = int(m.group(1))
        tid = post_thread_map.get(pid)
        if tid:
            return f'{base_path}/thread/{tid}/#post{pid}'
        return f'#post{pid}'

    text = re.sub(r'showthread\.php\?p=(\d+)', resolve_post, text)
    text = re.sub(r'forumdisplay\.php\?f=(\d+)',
                  lambda m: f'{base_path}/f/{m.group(1)}/', text)
    return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def decode_vb(text):
    """Decode vBulletin latin1-stored UTF-8 text.

    vBulletin 3.x stores user-submitted UTF-8 text in latin1 columns.
    This double-encoding means we need to encode back to latin1 bytes,
    then decode as UTF-8 to recover the original characters.
    See docs/encoding.md for the full explanation.
    """
    if text is None:
        return ""
    if isinstance(text, bytes):
        try:
            return text.decode('utf-8', errors='replace')
        except Exception:
            return text.decode('latin1', errors='replace')
    try:
        return text.encode('latin1').decode('utf-8', errors='replace')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return str(text)


def format_date(timestamp, fmt="%d %B %Y"):
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(fmt)


def format_datetime(timestamp):
    """ISO 8601 format for schema.org."""
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def format_date_short(timestamp):
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%d %b %Y, %H:%M")


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1048576:
        return f"{size_bytes // 1024} KB"
    else:
        return f"{size_bytes / 1048576:.1f} MB"


def commafy(value):
    """Jinja2 filter for comma-separated numbers."""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def page_range(current, total, window=3):
    """Generate a pagination range with ellipsis."""
    if total <= 1:
        return []
    pages = []
    for p in range(1, total + 1):
        if p == 1 or p == total or abs(p - current) <= window:
            pages.append(p)
        elif pages and pages[-1] != '...':
            pages.append('...')
    return pages


def write_file(path, content):
    """Write content to file, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

class ForumDB:
    """Query interface for a vBulletin 3.x MySQL/MariaDB database.

    Handles the connection encoding quirk where pymysql maps MySQL 'latin1'
    to Python 'cp1252', which can't handle all 256 byte values. We override
    to 'iso-8859-1' (true latin1) after connection. See docs/encoding.md.
    """

    def __init__(self, host, user, password, database, charset='latin1'):
        self.conn = pymysql.connect(
            host=host, user=user, password=password,
            database=database, charset=charset,
            cursorclass=pymysql.cursors.DictCursor
        )
        # pymysql maps MySQL 'latin1' to Python 'cp1252' which can't handle
        # byte 0x8F and others. Override to true latin1 (iso-8859-1).
        self.conn.encoding = 'iso-8859-1'

    def query(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def query_one(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def get_forums(self):
        return self.query("""
            SELECT forumid, title, description, parentid, parentlist, link,
                (SELECT COUNT(*) FROM thread t WHERE t.forumid = f.forumid AND t.visible = 1) as thread_count,
                (SELECT COALESCE(SUM(t.replycount), 0) FROM thread t WHERE t.forumid = f.forumid AND t.visible = 1) as reply_count,
                f.lastpost,
                (SELECT YEAR(FROM_UNIXTIME(MIN(t.dateline))) FROM thread t WHERE t.forumid = f.forumid AND t.visible = 1) as first_year,
                (SELECT YEAR(FROM_UNIXTIME(MAX(t.dateline))) FROM thread t WHERE t.forumid = f.forumid AND t.visible = 1) as last_year
            FROM forum f
            WHERE f.link = '' OR f.link IS NULL
            ORDER BY f.parentid, f.forumid
        """)

    def get_threads(self, forum_id, limit=None, offset=0):
        sql = """
            SELECT t.threadid, t.title, t.replycount, t.views, t.dateline,
                t.postusername, t.lastpost, t.postuserid, t.pollid, t.firstpostid
            FROM thread t
            WHERE t.forumid = %s AND t.visible = 1
            ORDER BY t.sticky DESC, t.lastpost DESC
            LIMIT %s OFFSET %s
        """
        return self.query(sql, (forum_id, limit or 999999, offset))

    def get_posts(self, thread_id, limit=None, offset=0):
        sql = """
            SELECT p.postid, p.threadid, p.username, p.userid, p.title as post_title,
                p.dateline, p.pagetext, p.attach
            FROM post p
            WHERE p.threadid = %s AND p.visible = 1
            ORDER BY p.dateline ASC
            LIMIT %s OFFSET %s
        """
        return self.query(sql, (thread_id, limit or 999999, offset))

    def count_posts(self, thread_id):
        row = self.query_one("SELECT COUNT(*) as cnt FROM post WHERE threadid = %s AND visible = 1", (thread_id,))
        return row['cnt']

    def get_attachments_for_posts(self, post_ids):
        if not post_ids:
            return {}
        placeholders = ','.join(['%s'] * len(post_ids))
        rows = self.query(f"""
            SELECT attachmentid, postid, filename, extension, filesize
            FROM attachment WHERE postid IN ({placeholders}) AND visible = 1
        """, post_ids)
        result = {}
        for r in rows:
            pid = r['postid']
            r['is_image'] = r['extension'].lower() in IMAGE_EXTENSIONS
            r['size_str'] = format_size(r['filesize'])
            result.setdefault(pid, []).append(r)
        return result

    def get_poll(self, poll_id):
        if not poll_id:
            return None
        return self.query_one("SELECT question, options, votes, numberoptions FROM poll WHERE pollid = %s", (poll_id,))

    def get_stats(self):
        return self.query_one("""
            SELECT
                (SELECT COUNT(*) FROM thread WHERE visible = 1) as threads,
                (SELECT COUNT(*) FROM post WHERE visible = 1) as posts,
                (SELECT COUNT(DISTINCT userid) FROM post WHERE visible = 1 AND userid > 0) as users,
                (SELECT COUNT(DISTINCT forumid) FROM thread WHERE visible = 1) as forums
        """)

    def build_user_lookup(self):
        """Build userid -> username mapping for posts with missing usernames."""
        rows = self.query("SELECT userid, username FROM user WHERE posts > 0 LIMIT 50000")
        return {r['userid']: decode_vb(r['username']) for r in rows}

    def get_popular_threads(self, limit=15):
        return self.query("""
            SELECT t.threadid, t.title, t.views, t.replycount, t.dateline,
                t.postusername, f.title as forum_title, f.forumid
            FROM thread t JOIN forum f ON t.forumid = f.forumid
            WHERE t.visible = 1
            ORDER BY t.views DESC
            LIMIT %s
        """, (limit,))

    def get_attachment_files(self, extension):
        """Get all attachments with a specific file extension."""
        return self.query("""
            SELECT a.attachmentid, a.filename, a.filesize, a.dateline,
                t.threadid, t.title as thread_title, f.title as forum_title
            FROM attachment a
            JOIN post p ON a.postid = p.postid
            JOIN thread t ON p.threadid = t.threadid
            JOIN forum f ON t.forumid = f.forumid
            WHERE a.visible = 1 AND a.extension = %s AND t.visible = 1
            ORDER BY a.filename
        """, (extension,))

    def get_top_users(self, limit=20):
        """Most prolific posters (excluding banned and spam accounts)."""
        return self.query("""
            SELECT u.userid, u.username, u.posts,
                YEAR(FROM_UNIXTIME(u.joindate)) as join_year,
                YEAR(FROM_UNIXTIME(u.lastpost)) as last_year
            FROM user u
            WHERE u.usergroupid NOT IN (8, 9)
                AND u.posts > 10
                AND DATEDIFF(FROM_UNIXTIME(u.lastpost), FROM_UNIXTIME(u.joindate)) > 30
            ORDER BY u.posts DESC
            LIMIT %s
        """, (limit,))

    def get_all_posting_users(self):
        """Get all users with visible posts, excluding banned/spam accounts."""
        return self.query("""
            SELECT u.userid, u.username, u.posts,
                u.joindate, u.lastpost,
                YEAR(FROM_UNIXTIME(u.joindate)) as join_year,
                YEAR(FROM_UNIXTIME(u.lastpost)) as last_year
            FROM user u
            WHERE u.usergroupid NOT IN (8, 9)
                AND u.posts > 0
            ORDER BY u.posts DESC
        """)

    def get_all_user_threads(self):
        """Batch-load all threads grouped by postuserid."""
        return self.query("""
            SELECT t.threadid, t.title, t.replycount, t.views, t.dateline,
                t.lastpost, t.postuserid, f.title as forum_title, f.forumid
            FROM thread t
            JOIN forum f ON t.forumid = f.forumid
            WHERE t.visible = 1
            ORDER BY t.postuserid, t.dateline DESC
        """)

    def build_post_thread_map(self):
        """Build postid -> threadid mapping for internal link rewriting."""
        rows = self.query("SELECT postid, threadid FROM post WHERE visible = 1")
        return {r['postid']: r['threadid'] for r in rows}

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Forum hierarchy builder
# ---------------------------------------------------------------------------

def build_hierarchy(forums_raw, config):
    """Build a nested forum hierarchy for the index page."""
    skip_forums = set(config['content'].get('skip_forums', []))
    parent_overrides = config['content'].get('parent_overrides', {})
    # YAML may load int keys as int or str depending on quoting
    parent_overrides = {int(k): int(v) for k, v in parent_overrides.items()}

    by_id = {f['forumid']: f for f in forums_raw}

    for fid, new_parent in parent_overrides.items():
        if fid in by_id:
            by_id[fid]['parentid'] = new_parent

    for f in forums_raw:
        f['title'] = decode_vb(f['title'])
        f['description'] = decode_vb(f.get('description', ''))
        if f['description']:
            f['description'] = re.sub(r'<[^>]+>', '', f['description'])[:120]
        f['thread_count'] = f['thread_count'] or 0
        f['reply_count'] = int(f['reply_count'] or 0)
        f['children'] = []

    def get_children(parent_id):
        children = [f for f in forums_raw
                    if f['parentid'] == parent_id and f['forumid'] not in skip_forums]
        return sorted(children, key=lambda x: x['thread_count'], reverse=True)

    categories = [f for f in forums_raw if f['parentid'] == -1]

    for cat in categories:
        cat['children'] = get_children(cat['forumid'])
        for sub in cat['children']:
            sub['children'] = get_children(sub['forumid'])
            sub['total_threads'] = sub['thread_count'] + sum(
                c['thread_count'] + sum(gc['thread_count']
                    for gc in get_children(c['forumid']))
                for c in sub['children']
            )
            for child in sub['children']:
                child['children'] = get_children(child['forumid'])

    return [c for c in categories if any(s.get('total_threads', s['thread_count']) > 0 for s in c['children'])]


def get_breadcrumbs(forum, forums_by_id):
    """Build breadcrumb trail for a forum."""
    crumbs = []
    fid = forum['parentid']
    while fid > 0:
        parent = forums_by_id.get(fid)
        if parent:
            crumbs.insert(0, parent)
            fid = parent['parentid']
        else:
            break
    return crumbs


# ---------------------------------------------------------------------------
# Site generator
# ---------------------------------------------------------------------------

def generate_site(db, config, output_dir, forum_filter=None, thread_limit=None):
    start_time = time.time()
    base_path = config['site']['base_path']
    skip_forums = set(config['content'].get('skip_forums', []))
    posts_per_page = config['content']['posts_per_page']
    threads_per_page = config['content']['threads_per_page']

    # Set up Jinja2
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.filters['commafy'] = commafy
    env.globals['now'] = datetime.now(tz=timezone.utc)
    env.globals['config'] = config
    env.globals['base_path'] = base_path

    # Copy static files
    static_src = os.path.join(os.path.dirname(__file__), 'static')
    static_dst = os.path.join(output_dir, 'static')
    if os.path.exists(static_src):
        os.makedirs(static_dst, exist_ok=True)
        for fname in os.listdir(static_src):
            shutil.copy2(os.path.join(static_src, fname), os.path.join(static_dst, fname))

    # Load data
    print("Loading forum structure...")
    forums_raw = db.get_forums()
    forums_by_id = {f['forumid']: f for f in forums_raw}
    for f in forums_raw:
        f['title'] = decode_vb(f['title'])

    print("Building user lookup...")
    user_lookup = db.build_user_lookup()

    print("Building post->thread map for link rewriting...")
    post_thread_map = db.build_post_thread_map()

    stats = db.get_stats()

    # Build hierarchy for index page
    categories = build_hierarchy(forums_raw, config)

    # Popular threads and top users for index page
    print("Loading popular threads and top users...")
    popular_limit = config['content']['popular_threads']
    popular_threads = db.get_popular_threads(popular_limit)
    for t in popular_threads:
        t['title'] = decode_vb(t['title'])
        t['forum_title'] = decode_vb(t['forum_title'])
        t['postusername'] = decode_vb(t['postusername'])
        t['date_str'] = format_date(t['dateline'], "%Y")

    contributors_limit = config['content']['notable_contributors']
    top_users = db.get_top_users(contributors_limit)
    for u in top_users:
        u['username'] = decode_vb(u['username'])

    # --- Generate forum index ---
    print("Generating forum index...")
    tpl = env.get_template('forum_index.html')
    index_html = tpl.render(categories=categories, stats=stats,
                            popular_threads=popular_threads, top_users=top_users)
    write_file(os.path.join(output_dir, 'index.html'), index_html)

    total_threads_generated = 0
    total_pages_generated = 1  # index page

    # --- Generate category pages (forums with sub-forums but no threads) ---
    print("Generating category pages...")
    tpl_list = env.get_template('thread_list.html')
    for forum in forums_raw:
        fid = forum['forumid']
        if fid in skip_forums:
            continue
        if forum['thread_count'] > 0:
            continue
        child_forums = [f for f in forums_raw
                        if f['parentid'] == fid and f['thread_count'] > 0 and f['forumid'] not in skip_forums]
        child_cats = [f for f in forums_raw
                      if f['parentid'] == fid and f['thread_count'] == 0 and f['forumid'] not in skip_forums
                      and any(cf['thread_count'] > 0 for cf in forums_raw if cf['parentid'] == f['forumid'])]
        all_children = child_forums + child_cats
        if not all_children:
            continue
        for cf in all_children:
            cf['title'] = decode_vb(cf['title'])
            if cf['thread_count'] == 0:
                cf['_sort_count'] = sum(f2['thread_count'] for f2 in forums_raw if f2['parentid'] == cf['forumid'])
            else:
                cf['_sort_count'] = cf['thread_count']
        all_children.sort(key=lambda f: f['_sort_count'], reverse=True)

        forum_obj = forums_by_id[fid]
        breadcrumbs = get_breadcrumbs(forum_obj, forums_by_id)
        cat_html = tpl_list.render(
            forum=forum, threads=[], breadcrumbs=breadcrumbs,
            sub_forums=all_children,
            page=1, total_pages=1, page_range=[],
        )
        write_file(os.path.join(output_dir, f'f/{fid}/index.html'), cat_html)
        total_pages_generated += 1

    # --- Generate thread lists and thread pages ---
    active_forums = [f for f in forums_raw
                     if f['thread_count'] > 0 and f['forumid'] not in skip_forums]

    if forum_filter:
        active_forums = [f for f in active_forums if f['forumid'] == forum_filter]

    for forum in active_forums:
        fid = forum['forumid']
        forum_obj = forums_by_id[fid]
        breadcrumbs = get_breadcrumbs(forum_obj, forums_by_id)
        sub_forums = [f for f in forums_raw
                      if f['parentid'] == fid and f['thread_count'] > 0 and f['forumid'] not in skip_forums]
        sub_forums.sort(key=lambda f: f['thread_count'], reverse=True)
        for sf in sub_forums:
            sf['title'] = decode_vb(sf['title'])

        tc = forum['thread_count']
        if thread_limit:
            tc = min(tc, thread_limit)
        total_forum_pages = max(1, math.ceil(tc / threads_per_page))

        tpl_list = env.get_template('thread_list.html')

        for list_page in range(1, total_forum_pages + 1):
            offset = (list_page - 1) * threads_per_page
            limit = min(threads_per_page, tc - offset) if thread_limit else threads_per_page

            threads = db.get_threads(fid, limit=limit, offset=offset)
            for t in threads:
                t['title'] = decode_vb(t['title'])
                t['postusername'] = decode_vb(t['postusername']) or user_lookup.get(t['postuserid'], 'Unknown')
                t['date_str'] = format_date(t['dateline'], "%d %b %Y")
                t['lastpost_str'] = format_date(t['lastpost'], "%d %b %Y")

            list_html = tpl_list.render(
                forum=forum, threads=threads, breadcrumbs=breadcrumbs,
                sub_forums=sub_forums,
                page=list_page, total_pages=total_forum_pages,
                page_range=page_range(list_page, total_forum_pages),
            )

            if list_page == 1:
                path = os.path.join(output_dir, f'f/{fid}/index.html')
            else:
                path = os.path.join(output_dir, f'f/{fid}/page/{list_page}/index.html')
            write_file(path, list_html)
            total_pages_generated += 1

        # Generate thread pages
        all_threads = db.get_threads(fid, limit=thread_limit)
        tpl_thread = env.get_template('thread_view.html')

        for thread in all_threads:
            tid = thread['threadid']
            thread['title'] = decode_vb(thread['title'])
            thread['postusername'] = decode_vb(thread['postusername']) or user_lookup.get(thread['postuserid'], 'Unknown')
            thread['date_str'] = format_date(thread['dateline'])
            thread['dateline_iso'] = format_datetime(thread['dateline']) if thread['dateline'] else ''

            poll = None
            if thread.get('pollid'):
                poll_data = db.get_poll(thread['pollid'])
                if poll_data:
                    poll = {'question': decode_vb(poll_data['question'])}

            post_count = db.count_posts(tid)
            total_thread_pages = max(1, math.ceil(post_count / posts_per_page)) if post_count > posts_per_page else 1
            posts_per = posts_per_page if post_count > posts_per_page else post_count

            for thread_page in range(1, total_thread_pages + 1):
                offset = (thread_page - 1) * posts_per
                posts = db.get_posts(tid, limit=posts_per, offset=offset)

                post_ids = [p['postid'] for p in posts]
                attachments = db.get_attachments_for_posts(post_ids)

                first_post_text = ""

                for p in posts:
                    p['pagetext'] = decode_vb(p['pagetext'])
                    p['username'] = decode_vb(p['username'])
                    p['display_name'] = p['username'] or user_lookup.get(p['userid'], f"Member #{p['userid']}" if p['userid'] else "Guest")
                    p['date_str'] = format_date_short(p['dateline'])
                    p['dateline_iso'] = format_datetime(p['dateline']) if p['dateline'] else ''
                    # Clean text excerpt for schema.org Comment
                    clean_text = re.sub(r'\[.*?\]', '', p['pagetext']) if p['pagetext'] else ''
                    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                    p['text_excerpt'] = clean_text[:500]

                    p['html_content'] = bbcode_to_html(p['pagetext'])
                    p['html_content'] = rewrite_internal_links(p['html_content'], post_thread_map, base_path)

                    # Resolve [ATTACH] placeholders
                    post_attachments = attachments.get(p['postid'], [])
                    for a in post_attachments:
                        placeholder = f'<!-- ATTACH:{a["attachmentid"]} -->'
                        if a['is_image']:
                            replacement = f'<img src="{base_path}/attachments/{a["attachmentid"]}_{a["filename"]}" loading="lazy" alt="{html.escape(a["filename"])}" class="post-image">'
                        else:
                            replacement = f'<a href="{base_path}/attachments/{a["attachmentid"]}_{a["filename"]}">{html.escape(a["filename"])}</a> ({a["size_str"]})'
                        p['html_content'] = p['html_content'].replace(placeholder, replacement)

                    p['attachments'] = post_attachments

                    if not first_post_text and p['pagetext']:
                        clean = re.sub(r'\[.*?\]', '', p['pagetext'])
                        clean = re.sub(r'\s+', ' ', clean).strip()
                        first_post_text = clean[:160]

                thread_html = tpl_thread.render(
                    thread=thread, forum=forum_obj, posts=posts,
                    breadcrumbs=breadcrumbs, poll=poll,
                    first_post_excerpt=html.escape(first_post_text),
                    page=thread_page, total_pages=total_thread_pages,
                    page_range=page_range(thread_page, total_thread_pages),
                )

                if thread_page == 1:
                    path = os.path.join(output_dir, f'thread/{tid}/index.html')
                else:
                    path = os.path.join(output_dir, f'thread/{tid}/page/{thread_page}/index.html')
                write_file(path, thread_html)
                total_pages_generated += 1

            total_threads_generated += 1

            if total_threads_generated % 100 == 0:
                elapsed = time.time() - start_time
                rate = total_threads_generated / elapsed
                print(f"  {total_threads_generated} threads ({total_pages_generated} pages) in {elapsed:.0f}s ({rate:.0f} threads/s)")

    # --- Generate stats page ---
    print("Generating stats page...")
    monthly_data = db.query("""
        SELECT CONCAT(YEAR(FROM_UNIXTIME(dateline)), '-', LPAD(MONTH(FROM_UNIXTIME(dateline)), 2, '0')) as month,
            COUNT(*) as posts
        FROM post WHERE visible = 1
        GROUP BY month ORDER BY month
    """)
    monthly_json = json.dumps([[decode_vb(r['month']), r['posts']] for r in monthly_data])

    yearly_stats = db.query("""
        SELECT YEAR(FROM_UNIXTIME(dateline)) as year, COUNT(*) as posts,
            COUNT(DISTINCT threadid) as threads
        FROM post WHERE visible = 1 GROUP BY year ORDER BY year
    """)

    busiest_days = db.query("""
        SELECT CONCAT(YEAR(FROM_UNIXTIME(dateline)), '-',
            LPAD(MONTH(FROM_UNIXTIME(dateline)), 2, '0'), '-',
            LPAD(DAY(FROM_UNIXTIME(dateline)), 2, '0')) as day,
            COUNT(*) as posts
        FROM post WHERE visible = 1 GROUP BY day ORDER BY posts DESC LIMIT 10
    """)
    for d in busiest_days:
        d['day'] = decode_vb(d['day'])

    top_forums_data = db.query("""
        SELECT f.title, COUNT(p.postid) as posts
        FROM post p JOIN thread t ON p.threadid = t.threadid JOIN forum f ON t.forumid = f.forumid
        WHERE p.visible = 1 AND t.visible = 1
        GROUP BY f.forumid ORDER BY posts DESC LIMIT 20
    """)
    forums_json = json.dumps([[decode_vb(r['title']), r['posts']] for r in top_forums_data])

    tpl_stats = env.get_template('stats.html')
    stats_html = tpl_stats.render(
        stats=stats, monthly_json=monthly_json, forums_json=forums_json,
        yearly_stats=yearly_stats, busiest_days=busiest_days, top_users=top_users,
        heatmap_json='[]', streamgraph_json='[]', lifespan_json='[]',
        nodes_json='[]', edges_json='[]', category_json='{}',
        sankey_json='{"nodes":[],"links":[]}',
    )
    write_file(os.path.join(output_dir, 'stats/index.html'), stats_html)
    print("  NOTE: Stats page has basic charts only. Run build_pages.py for full visualisations.")

    # --- Generate custom pages ---
    custom = config.get('custom_pages', {})
    sis_config = custom.get('sis_listing', {})
    if sis_config.get('enabled'):
        print("Generating custom attachment listing...")
        sis_files = db.get_attachment_files('sis')
        for s in sis_files:
            s['filename'] = decode_vb(s['filename'])
            s['thread_title'] = decode_vb(s['thread_title'])
            s['forum_title'] = decode_vb(s['forum_title'])
            s['size_str'] = format_size(s['filesize'])
            s['date_str'] = format_date(s['dateline'], "%d %b %Y")
        tpl_sis = env.get_template('sis_listing.html')
        sis_html = tpl_sis.render(sis_files=sis_files, stats=stats, sis_config=sis_config)
        sis_path = sis_config.get('path', '/symbian-apps/').strip('/')
        write_file(os.path.join(output_dir, f'{sis_path}/index.html'), sis_html)

    # --- Generate search page ---
    print("Generating search page...")
    tpl_search = env.get_template('search.html')
    search_html = tpl_search.render(stats=stats)
    write_file(os.path.join(output_dir, 'search/index.html'), search_html)

    # --- Generate about page ---
    print("Generating about page...")
    tpl_about = env.get_template('about.html')
    about_html = tpl_about.render(stats=stats)
    write_file(os.path.join(output_dir, 'about/index.html'), about_html)

    # --- Generate user profile pages ---
    print("Loading users for profile pages...")
    all_users = db.get_all_posting_users()

    print("Batch-loading user threads...")
    all_user_threads_raw = db.get_all_user_threads()

    # Group threads by postuserid
    threads_by_user = {}
    forums_by_user = {}
    for t in all_user_threads_raw:
        uid = t['postuserid']
        threads_by_user.setdefault(uid, []).append(t)
        forums_by_user.setdefault(uid, set()).add(t['forumid'])
    del all_user_threads_raw  # Free memory

    tpl_user = env.get_template('user_profile.html')
    users_generated = 0

    for user in all_users:
        uid = user['userid']
        user['username'] = decode_vb(user['username'])
        user['join_year'] = user['join_year'] or ''
        user['last_year'] = user['last_year'] or ''
        user['join_date_iso'] = format_datetime(user['joindate']) if user.get('joindate') else ''
        user['last_post_iso'] = format_datetime(user['lastpost']) if user.get('lastpost') else ''

        threads = threads_by_user.get(uid, [])
        user['threads_started'] = len(threads)
        user['forums_active'] = len(forums_by_user.get(uid, set()))

        for t in threads:
            t['title'] = decode_vb(t['title'])
            t['forum_title'] = decode_vb(t['forum_title'])
            t['date_str'] = format_date(t['dateline'], "%d %b %Y")
            t['dateline_iso'] = format_datetime(t['dateline']) if t.get('dateline') else ''

        user_html = tpl_user.render(user=user, threads=threads,
                                    recent_posts=[])
        write_file(os.path.join(output_dir, f'user/{uid}/index.html'), user_html)
        users_generated += 1

        if users_generated % 2000 == 0:
            print(f"  {users_generated} user pages generated...")

    print(f"  {users_generated} user profile pages generated")
    total_pages_generated += users_generated

    # --- Generate user index page ---
    print("Generating user index page...")
    # Build top users list with thread counts for the index
    top_users_with_threads = []
    for u in all_users[:100]:
        u_copy = dict(u)
        u_copy['threads_started'] = len(threads_by_user.get(u['userid'], []))
        top_users_with_threads.append(u_copy)

    # Compute year range
    years = [u['join_year'] for u in all_users if u['join_year']] + \
            [u['last_year'] for u in all_users if u['last_year']]
    earliest_year = min(years) if years else ''
    latest_year = max(years) if years else ''

    tpl_user_index = env.get_template('user_index.html')
    user_index_html = tpl_user_index.render(
        users=all_users, top_users=top_users_with_threads,
        earliest_year=earliest_year, latest_year=latest_year,
    )
    write_file(os.path.join(output_dir, 'users/index.html'), user_index_html)
    total_pages_generated += 1

    # --- Generate sitemaps ---
    print("Generating sitemaps...")
    site_url = config['site']['url'].rstrip('/')
    MAX_URLS_PER_SITEMAP = 49000

    all_urls = []
    all_urls.append((f'{site_url}{base_path}/', '1.0'))
    all_urls.append((f'{site_url}{base_path}/stats/', '0.7'))
    all_urls.append((f'{site_url}{base_path}/users/', '0.6'))

    for forum in forums_raw:
        if forum['forumid'] in skip_forums:
            continue
        if forum['thread_count'] > 0 or any(f['parentid'] == forum['forumid'] for f in forums_raw):
            all_urls.append((f'{site_url}{base_path}/f/{forum["forumid"]}/', '0.6'))

    thread_dir = os.path.join(output_dir, 'thread')
    if os.path.exists(thread_dir):
        for tid in sorted(os.listdir(thread_dir)):
            if tid.isdigit():
                all_urls.append((f'{site_url}{base_path}/thread/{tid}/', None))

    user_dir = os.path.join(output_dir, 'user')
    if os.path.exists(user_dir):
        for uid in sorted(os.listdir(user_dir)):
            if uid.isdigit():
                all_urls.append((f'{site_url}{base_path}/user/{uid}/', '0.4'))

    sitemap_files = []
    for i in range(0, len(all_urls), MAX_URLS_PER_SITEMAP):
        chunk = all_urls[i:i + MAX_URLS_PER_SITEMAP]
        sitemap_num = (i // MAX_URLS_PER_SITEMAP) + 1
        filename = f'sitemap-{sitemap_num}.xml'

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for url, priority in chunk:
            if priority:
                lines.append(f'<url><loc>{url}</loc><priority>{priority}</priority></url>')
            else:
                lines.append(f'<url><loc>{url}</loc></url>')
        lines.append('</urlset>')
        write_file(os.path.join(output_dir, filename), '\n'.join(lines))
        sitemap_files.append(filename)

    index_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                   '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for sf in sitemap_files:
        index_lines.append(f'<sitemap><loc>{site_url}{base_path}/{sf}</loc></sitemap>')
    index_lines.append('</sitemapindex>')
    write_file(os.path.join(output_dir, 'sitemap.xml'), '\n'.join(index_lines))
    print(f"  {len(all_urls)} URLs across {len(sitemap_files)} sitemaps")

    elapsed = time.time() - start_time
    print(f"\nDone! Generated {total_pages_generated} pages from {total_threads_generated} threads in {elapsed:.1f}s")
    print(f"Output: {output_dir}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generate a static HTML archive from a vBulletin 3.x database')
    parser.add_argument('--config', '-c', required=True, help='Path to config.yaml')
    parser.add_argument('--output', '-o', required=True, help='Output directory')
    parser.add_argument('--forum', '-f', type=int, help='Generate only this forum ID')
    parser.add_argument('--limit', '-l', type=int, help='Limit threads per forum')
    parser.add_argument('--password', '-p', default=None,
                        help='Database password (or set ARCHIVE_DB_ROOT_PASSWORD env var)')
    args = parser.parse_args()

    config = load_config(args.config)

    db_config = config['database']
    password = args.password or os.environ.get('ARCHIVE_DB_ROOT_PASSWORD')
    if not password:
        print("Error: provide --password or set ARCHIVE_DB_ROOT_PASSWORD")
        sys.exit(1)

    print(f"Connecting to {db_config['host']}/{db_config['name']}...")
    db = ForumDB(
        host=db_config['host'],
        user=db_config['user'],
        password=password,
        database=db_config['name'],
        charset=db_config.get('charset', 'latin1'),
    )

    try:
        generate_site(db, config, args.output,
                      forum_filter=args.forum, thread_limit=args.limit)
    finally:
        db.close()


if __name__ == '__main__':
    main()
