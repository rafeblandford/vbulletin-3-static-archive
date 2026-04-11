#!/usr/bin/env python3
"""
Regenerate stats, about, search, and listing pages only.

Much faster than a full build (~15s vs ~150s) — skips thread/forum page
generation entirely. Use this when iterating on visualisations or page content.

Usage:
    python3 build_pages.py -c config.yaml -o ./output/
"""

import argparse
import json
import os
import shutil
import sys
import time
from collections import defaultdict
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

    # Stats cutoff: exclude long-tail posts after the community was effectively dead
    STATS_CUTOFF = 'AND dateline < UNIX_TIMESTAMP("2014-01-01")'
    STATS_CUTOFF_P = 'AND p.dateline < UNIX_TIMESTAMP("2014-01-01")'

    # Top users
    print("Loading top users...")
    contributors_limit = config['content']['notable_contributors']
    top_users = db.get_top_users(contributors_limit)
    for u in top_users:
        u['username'] = decode_vb(u['username'])

    # --- Stats page data ---
    print("Generating stats page...")
    monthly_data = db.query(f"""
        SELECT CONCAT(YEAR(FROM_UNIXTIME(dateline)), '-', LPAD(MONTH(FROM_UNIXTIME(dateline)), 2, '0')) as month,
            COUNT(*) as posts
        FROM post WHERE visible = 1 {STATS_CUTOFF}
        GROUP BY month ORDER BY month
    """)
    monthly_json = json.dumps([[decode_vb(r['month']), r['posts']] for r in monthly_data])

    yearly_stats = db.query(f"""
        SELECT YEAR(FROM_UNIXTIME(dateline)) as year, COUNT(*) as posts,
            COUNT(DISTINCT threadid) as threads
        FROM post WHERE visible = 1 {STATS_CUTOFF} GROUP BY year ORDER BY year
    """)

    busiest_days = db.query(f"""
        SELECT CONCAT(YEAR(FROM_UNIXTIME(dateline)), '-',
            LPAD(MONTH(FROM_UNIXTIME(dateline)), 2, '0'), '-',
            LPAD(DAY(FROM_UNIXTIME(dateline)), 2, '0')) as day,
            COUNT(*) as posts
        FROM post WHERE visible = 1 {STATS_CUTOFF} GROUP BY day ORDER BY posts DESC LIMIT 10
    """)
    for d in busiest_days:
        d['day'] = decode_vb(d['day'])

    top_forums_data = db.query(f"""
        SELECT f.title, COUNT(p.postid) as posts
        FROM post p JOIN thread t ON p.threadid = t.threadid JOIN forum f ON t.forumid = f.forumid
        WHERE p.visible = 1 AND t.visible = 1 {STATS_CUTOFF_P}
        GROUP BY f.forumid ORDER BY posts DESC LIMIT 20
    """)
    forums_json = json.dumps([[decode_vb(r['title']), r['posts']] for r in top_forums_data])

    # Activity heatmap
    print("  Loading activity heatmap data...")
    heatmap_data = db.query(f"""
        SELECT DAYOFWEEK(FROM_UNIXTIME(dateline)) as dow,
            HOUR(FROM_UNIXTIME(dateline)) as hr, COUNT(*) as posts
        FROM post WHERE visible = 1 {STATS_CUTOFF}
        GROUP BY dow, hr ORDER BY dow, hr
    """)
    heatmap_json = json.dumps([[r['dow'], r['hr'], r['posts']] for r in heatmap_data])

    # Streamgraph / ThemeRiver
    print("  Loading streamgraph data...")
    streamgraph_data = db.query(f"""
        SELECT CONCAT(YEAR(FROM_UNIXTIME(p.dateline)), '-',
            LPAD(MONTH(FROM_UNIXTIME(p.dateline)), 2, '0')) as month,
            f.title as forum_name, COUNT(*) as posts
        FROM post p JOIN thread t ON p.threadid = t.threadid
        JOIN forum f ON t.forumid = f.forumid
        WHERE p.visible = 1 AND t.visible = 1 {STATS_CUTOFF_P}
        AND f.forumid IN (
            SELECT forumid FROM (
                SELECT t2.forumid, COUNT(*) as cnt
                FROM post p2 JOIN thread t2 ON p2.threadid = t2.threadid
                WHERE p2.visible = 1 AND t2.visible = 1 AND p2.dateline < UNIX_TIMESTAMP('2014-01-01')
                GROUP BY t2.forumid ORDER BY cnt DESC LIMIT 15
            ) top
        )
        GROUP BY month, f.forumid ORDER BY month
    """)
    streamgraph_json = json.dumps([[decode_vb(r['month']), r['posts'], decode_vb(r['forum_name'])]
                                   for r in streamgraph_data])

    # Thread lifespan
    print("  Loading thread lifespan data...")
    lifespan_data = db.query(f"""
        SELECT
            CASE
                WHEN duration_days = 0 THEN 'Same day'
                WHEN duration_days BETWEEN 1 AND 7 THEN '1 week'
                WHEN duration_days BETWEEN 8 AND 30 THEN '1 month'
                WHEN duration_days BETWEEN 31 AND 90 THEN '3 months'
                WHEN duration_days BETWEEN 91 AND 365 THEN '1 year'
                ELSE '1+ years'
            END as lifespan,
            COUNT(*) as threads
        FROM (
            SELECT t.threadid,
                DATEDIFF(FROM_UNIXTIME(MAX(p.dateline)), FROM_UNIXTIME(MIN(p.dateline))) as duration_days
            FROM thread t JOIN post p ON t.threadid = p.threadid
            WHERE t.visible = 1 AND p.visible = 1 AND t.replycount > 0 {STATS_CUTOFF_P}
            GROUP BY t.threadid
        ) sub
        GROUP BY lifespan
        ORDER BY FIELD(lifespan, 'Same day', '1 week', '1 month', '3 months', '1 year', '1+ years')
    """)
    lifespan_json = json.dumps([[r['lifespan'], r['threads']] for r in lifespan_data])

    # Forum affinity network
    print("  Loading forum affinity network...")
    forum_nodes = db.query("""
        SELECT f.forumid, f.title, COUNT(p.postid) as posts
        FROM post p JOIN thread t ON p.threadid = t.threadid JOIN forum f ON t.forumid = f.forumid
        WHERE p.visible = 1 AND t.visible = 1
        GROUP BY f.forumid HAVING posts > 500
        ORDER BY posts DESC
    """)
    node_ids = {r['forumid'] for r in forum_nodes}
    nodes_json = json.dumps([{
        'id': r['forumid'],
        'label': decode_vb(r['title']),
        'posts': r['posts']
    } for r in forum_nodes])

    print("  Loading forum affinity edges...")
    forum_edges = db.query("""
        SELECT sub.forumid as source, sub2.forumid as target, COUNT(DISTINCT sub.userid) as weight
        FROM (
            SELECT DISTINCT p.userid, t.forumid
            FROM post p JOIN thread t ON p.threadid = t.threadid
            WHERE p.visible = 1 AND t.visible = 1 AND p.userid > 0
        ) sub
        JOIN (
            SELECT DISTINCT p.userid, t.forumid
            FROM post p JOIN thread t ON p.threadid = t.threadid
            WHERE p.visible = 1 AND t.visible = 1 AND p.userid > 0
        ) sub2 ON sub.userid = sub2.userid AND sub.forumid < sub2.forumid
        GROUP BY sub.forumid, sub2.forumid
        HAVING weight >= 50
        ORDER BY weight DESC
    """)
    edges_json = json.dumps([{
        'source': r['source'],
        'target': r['target'],
        'weight': r['weight']
    } for r in forum_edges if r['source'] in node_ids and r['target'] in node_ids])

    # Forum category mapping for colour coding
    forum_categories = db.query("""
        SELECT f.forumid,
            (SELECT p.title FROM forum p
             WHERE p.forumid = CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(f.parentlist, ',', 2), ',', -1) AS UNSIGNED)
            ) as category
        FROM forum f
    """)
    category_json = json.dumps({r['forumid']: decode_vb(r['category'] or '') for r in forum_categories})

    # User migration Sankey
    print("  Loading user migration data...")
    top_forum_rows = db.query("""
        SELECT t.forumid, COUNT(*) as cnt FROM post p JOIN thread t ON p.threadid = t.threadid
        WHERE p.visible = 1 AND t.visible = 1 GROUP BY t.forumid ORDER BY cnt DESC LIMIT 15
    """)
    top_forum_ids = tuple(r['forumid'] for r in top_forum_rows)
    placeholders = ','.join(['%s'] * len(top_forum_ids))

    migration_rows = db.query(f"""
        SELECT
          CASE
            WHEN YEAR(FROM_UNIXTIME(p.dateline)) BETWEEN 2001 AND 2002 THEN 1
            WHEN YEAR(FROM_UNIXTIME(p.dateline)) BETWEEN 2003 AND 2005 THEN 2
            WHEN YEAR(FROM_UNIXTIME(p.dateline)) BETWEEN 2006 AND 2008 THEN 3
            WHEN YEAR(FROM_UNIXTIME(p.dateline)) BETWEEN 2009 AND 2011 THEN 4
            WHEN YEAR(FROM_UNIXTIME(p.dateline)) BETWEEN 2012 AND 2013 THEN 5
          END as era,
          t.forumid, f.title, p.userid, COUNT(*) as posts
        FROM post p
        JOIN thread t ON p.threadid = t.threadid
        JOIN forum f ON t.forumid = f.forumid
        WHERE p.visible = 1 AND t.visible = 1 AND p.userid > 0
        AND t.forumid IN ({placeholders})
        GROUP BY era, t.forumid, p.userid
    """, top_forum_ids)

    forum_name_lookup = {}
    user_era_forums = defaultdict(lambda: defaultdict(int))
    for r in migration_rows:
        if r['era'] is None:
            continue
        user_era_forums[(r['userid'], r['era'])][r['forumid']] = r['posts']
        forum_name_lookup[r['forumid']] = decode_vb(r['title'])

    # Primary forum per user per era
    user_primary = {}
    all_uids = set()
    for (uid, era), forum_posts in user_era_forums.items():
        user_primary[(uid, era)] = max(forum_posts, key=forum_posts.get)
        all_uids.add(uid)

    # Build flows between consecutive eras
    era_labels = {1: '2001-02', 2: '2003-05', 3: '2006-08', 4: '2009-11', 5: '2012-13'}
    flow_counts = defaultdict(int)
    for uid in all_uids:
        for era in [1, 2, 3, 4]:
            if (uid, era) in user_primary and (uid, era + 1) in user_primary:
                flow_counts[(era, user_primary[(uid, era)], user_primary[(uid, era + 1)])] += 1

    # Build Sankey nodes and links
    sankey_nodes = []
    sankey_idx = {}
    for era in [1, 2, 3, 4, 5]:
        era_forums = set()
        for (uid, e), fid in user_primary.items():
            if e == era:
                era_forums.add(fid)
        for fid in sorted(era_forums, key=lambda f: -sum(1 for (u, e), ff in user_primary.items() if e == era and ff == f)):
            short = forum_name_lookup.get(fid, str(fid)).replace('Nokia ', '').replace(' and ', ' & ')
            name = f"{short} ({era_labels[era]})"
            sankey_idx[(era, fid)] = len(sankey_nodes)
            sankey_nodes.append({'name': name})

    sankey_links = []
    for (era, src, tgt), count in flow_counts.items():
        if count < 5:
            continue
        if (era, src) in sankey_idx and (era + 1, tgt) in sankey_idx:
            sankey_links.append({
                'source': sankey_idx[(era, src)],
                'target': sankey_idx[(era + 1, tgt)],
                'value': count
            })

    sankey_json = json.dumps({'nodes': sankey_nodes, 'links': sankey_links})
    print(f"  Sankey: {len(sankey_nodes)} nodes, {len(sankey_links)} links")

    # --- Render stats page ---
    tpl_stats = env.get_template('stats.html')
    stats_html = tpl_stats.render(
        stats=stats, monthly_json=monthly_json, forums_json=forums_json,
        yearly_stats=yearly_stats, busiest_days=busiest_days, top_users=top_users,
        heatmap_json=heatmap_json, streamgraph_json=streamgraph_json,
        lifespan_json=lifespan_json,
        nodes_json=nodes_json, edges_json=edges_json,
        category_json=category_json, sankey_json=sankey_json,
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
