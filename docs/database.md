# Database Requirements

## What you need

You need a MySQL or MariaDB dump of a **vBulletin 3.x** database. This is the `mysqldump` output — typically a single `.sql` file.

The generator reads from a live MySQL/MariaDB instance, so you'll need to import the dump before building.

### Key tables used

The generator queries these vBulletin tables:

| Table | What it provides |
|---|---|
| `forum` | Forum structure, hierarchy, descriptions |
| `thread` | Thread metadata (title, author, dates, view counts) |
| `post` | Post content (BBCode text), author, dates |
| `user` | Username lookup, post counts, join/last-active dates |
| `attachment` | File attachments (filenames, sizes, extensions) |
| `poll` | Poll questions (displayed as text notices) |

The `visible` column on `thread` and `post` tables is used to filter out deleted/moderated content. This is vBulletin's own moderation flag — `visible=1` means the content was publicly viewable.

### What's NOT in the database

Understanding what vBulletin stores in the database vs. the filesystem is important:

**In the database:**
- All post content (BBCode text)
- Thread and forum metadata
- User accounts and usernames
- Attachment file data (stored as BLOBs in the `attachment` table, or sometimes in `filedata`)
- Poll data

**NOT in the database (filesystem only):**
- User avatars and profile images
- Custom smilie images
- Forum icons and style assets
- Any files uploaded outside vBulletin's attachment system

If you only have the database dump (no server filesystem backup), the archive will be complete for discussions but won't have avatars or custom images. This is the most common scenario for database-only recovery.

### Attachment storage

vBulletin 3.x can store attachments in two ways:

1. **In the database** — attachment file data in the `attachment` or `filedata` table (BLOB columns)
2. **On the filesystem** — files in a directory, with only metadata in the database

The generator assumes database storage and references attachments by `attachmentid_filename` pattern. If your vBulletin instance used filesystem storage, you'll need to either:
- Import the attachment files to match the expected path pattern
- Modify the attachment URL pattern in the templates

## Importing the dump

### Basic import

```bash
# Create the database
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS allabout_vb"

# Import with the correct character set
mysql -u root -p --default-character-set=latin1 allabout_vb < /path/to/dump.sql
```

The `--default-character-set=latin1` flag is important. See [encoding.md](encoding.md) for why.

### Large dumps

For dumps over 1 GB:

```bash
# Disable binary logging and keys during import for speed
mysql -u root -p --default-character-set=latin1 \
    -e "SET GLOBAL max_allowed_packet=1073741824;" allabout_vb

mysql -u root -p --default-character-set=latin1 allabout_vb < dump.sql
```

The All About Symbian dump (1.6 GB, 180 tables) imports in a few minutes on modern hardware.

### Docker / containerised databases

If your MariaDB runs in Docker:

```bash
# Copy dump into container
docker cp dump.sql mariadb-container:/tmp/

# Import
docker exec -i mariadb-container mysql -u root -p"$PASSWORD" \
    --default-character-set=latin1 dbname < dump.sql
```

## Exploring your data

Before building, it's worth checking what you have:

```sql
-- How many visible threads and posts?
SELECT COUNT(*) FROM thread WHERE visible = 1;
SELECT COUNT(*) FROM post WHERE visible = 1;

-- How many forums with content?
SELECT COUNT(DISTINCT forumid) FROM thread WHERE visible = 1;

-- Date range
SELECT
    FROM_UNIXTIME(MIN(dateline)) as earliest,
    FROM_UNIXTIME(MAX(dateline)) as latest
FROM post WHERE visible = 1;

-- Attachment count and types
SELECT extension, COUNT(*) as cnt
FROM attachment WHERE visible = 1
GROUP BY extension ORDER BY cnt DESC;

-- Spam check: visible posts from banned users
SELECT COUNT(*) FROM post p
JOIN user u ON p.userid = u.userid
WHERE p.visible = 1 AND u.usergroupid IN (8, 9);
```

These queries help you understand the scale and quality of your data before committing to a full build. You may discover that the forum was well-moderated (making spam filtering unnecessary) or that the date range differs from what you expected.

## vBulletin version compatibility

This generator was built for **vBulletin 3.8.0** and tested with that schema. It should work with other vBulletin 3.x versions (3.0 through 3.8) as the core tables (`forum`, `thread`, `post`, `user`, `attachment`) have been stable across the 3.x line.

**vBulletin 4.x and 5.x** use a different schema and are not supported. The core concepts (BBCode conversion, static generation) would apply, but the SQL queries would need rewriting.

## Privacy considerations

The generator deliberately excludes:
- Email addresses (in the `user` table)
- IP addresses (in the `post` table)
- Passwords/salts (in the `user` table)
- Private messages (the `pm` and `pmtext` tables)
- Date-of-birth fields

Only publicly visible content (usernames, post text, thread titles) is included in the output. This aligns with GDPR Article 89 provisions for archiving in the public interest, but you should consider your own jurisdiction's requirements.
