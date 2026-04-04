#!/usr/bin/env python3
"""
Extract vBulletin attachments from database BLOBs to filesystem.

Run this once before or after building the static archive. The main generator
(build.py) references attachments by path but doesn't extract them itself —
this keeps the build fast and idempotent.

Usage:
    python3 extract_attachments.py -c config.yaml -o ./output/attachments/

    # Or with explicit database credentials
    python3 extract_attachments.py -c config.yaml -o ./output/attachments/ -p yourpassword
"""

import argparse
import os
import sys

import pymysql
import yaml


def main():
    parser = argparse.ArgumentParser(
        description='Extract vBulletin attachments from database BLOBs to filesystem')
    parser.add_argument('--config', '-c', required=True, help='Path to config.yaml')
    parser.add_argument('--output', '-o', required=True,
                        help='Output directory for attachments')
    parser.add_argument('--password', '-p', default=None,
                        help='Database password (or set ARCHIVE_DB_ROOT_PASSWORD env var)')
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    db_config = config['database']
    password = args.password or os.environ.get('ARCHIVE_DB_ROOT_PASSWORD')
    if not password:
        print("Error: provide --password or set ARCHIVE_DB_ROOT_PASSWORD")
        sys.exit(1)

    output_dir = args.output
    thumb_dir = os.path.join(output_dir, 'thumbs')
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)

    print(f"Connecting to {db_config['host']}/{db_config['name']}...")
    conn = pymysql.connect(
        host=db_config['host'],
        user=db_config['user'],
        password=password,
        database=db_config['name'],
        charset=db_config.get('charset', 'latin1'),
        cursorclass=pymysql.cursors.DictCursor
    )
    conn.encoding = 'iso-8859-1'

    print("Extracting attachments...")
    files_written = 0
    thumbs_written = 0

    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.attachmentid, a.filename, a.extension, a.filedata, a.thumbnail
            FROM attachment a WHERE a.visible = 1
        """)
        for row in cur:
            aid = row['attachmentid']
            fname = row['filename']

            if row['filedata']:
                path = os.path.join(output_dir, f"{aid}_{fname}")
                with open(path, 'wb') as f:
                    f.write(row['filedata'])
                files_written += 1

            if row['thumbnail']:
                path = os.path.join(thumb_dir, f"{aid}_thumb.{row['extension']}")
                with open(path, 'wb') as f:
                    f.write(row['thumbnail'])
                thumbs_written += 1

            if files_written % 500 == 0 and files_written > 0:
                print(f"  {files_written} files extracted...")

    conn.close()
    print(f"\nDone! Extracted {files_written} attachments and {thumbs_written} thumbnails")
    print(f"Output: {output_dir}")


if __name__ == '__main__':
    main()
