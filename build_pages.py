#!/usr/bin/env python3
"""
Regenerate stats, about, search, and listing pages only.

Much faster than a full build — skips thread/forum page generation entirely.
Use this when iterating on visualisations, page content, or styling.

Usage:
    python3 build_pages.py -c config.yaml -o ./output/
"""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

import yaml
from jinja2 import Environment, FileSystemLoader

from build import (
    ForumDB, build_hierarchy, decode_vb, format_date, format_size,
    commafy, write_file, load_config, IMAGE_EXTENSIONS,
)


def main():
    parser = argparse.ArgumentParser(
        description='Regenerate stats/about/search pages (no thread rebuild)')
    parser.add_argument('--config', '-c', required=True, help='Path to config.yaml')
    parser.add_argument('--output', '-o', required=True, help='Output directory')
    parser.add_argument('--password', '-p', default=None,
                        help='Database password (or set ARCHIVE_DB_ROOT_PASSWORD env var)')
    args = parser.parse_args()

    config = load_config(args.config)
    db_config = config['database']
    password = args.password or os.environ.get('ARCHIVE_DB_ROOT_PASSWORD')
    if not password:
        print("Error: provide --password or set ARCHIVE_DB_ROOT_PASSWORD")
        sys.exit(1)

    start_time = time.time()
    output_dir = args.output
    base_path = config['site']['base_path']

    print(f"Connecting to {db_config['host']}/{db_config['name']}...")
    db = ForumDB(
        host=db_config['host'],
        user=db_config['user'],
        password=password,
        database=db_config['name'],
        charset=db_config.get('charset', 'latin1'),
    )

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

    stats = db.get_stats()

    # Top users
    print("Loading top users...")
    contributors_limit = config['content']['notable_contributors']
    top_users = db.get_top_users(contributors_limit)
    for u in top_users:
        u['username'] = decode_vb(u['username'])

    # --- Stats page ---
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
    )
    write_file(os.path.join(output_dir, 'stats/index.html'), stats_html)

    # --- Custom pages ---
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

    # --- Search page ---
    print("Generating search page...")
    tpl_search = env.get_template('search.html')
    search_html = tpl_search.render(stats=stats)
    write_file(os.path.join(output_dir, 'search/index.html'), search_html)

    # --- About page ---
    print("Generating about page...")
    tpl_about = env.get_template('about.html')
    about_html = tpl_about.render(stats=stats)
    write_file(os.path.join(output_dir, 'about/index.html'), about_html)

    # --- Forum index ---
    print("Generating forum index...")
    forums_raw = db.get_forums()
    for f in forums_raw:
        f['title'] = decode_vb(f['title'])
    categories = build_hierarchy(forums_raw, config)
    popular_limit = config['content']['popular_threads']
    popular_threads = db.get_popular_threads(popular_limit)
    for t in popular_threads:
        t['title'] = decode_vb(t['title'])
        t['forum_title'] = decode_vb(t['forum_title'])
        t['postusername'] = decode_vb(t['postusername'])
        t['date_str'] = format_date(t['dateline'], "%Y")
    tpl_index = env.get_template('forum_index.html')
    index_html = tpl_index.render(categories=categories, stats=stats,
                                  popular_threads=popular_threads, top_users=top_users)
    write_file(os.path.join(output_dir, 'index.html'), index_html)

    db.close()
    elapsed = time.time() - start_time
    print(f"\nDone! Pages regenerated in {elapsed:.1f}s")
    print(f"Output: {output_dir}")


if __name__ == '__main__':
    main()
