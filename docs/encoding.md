# The Encoding Problem (and Fix)

This is probably the most useful technical detail in this project. If you're working with any vBulletin 3.x database in Python, you'll hit this.

## The problem

vBulletin 3.x was typically configured with MySQL `latin1` (or `swedish`) character set. When users posted UTF-8 content (accented characters, Chinese text, emoji, Euro signs), the UTF-8 bytes were stored directly in `latin1` columns without conversion. MySQL happily stored the bytes because `latin1` maps 1:1 to byte values 0x00–0xFF.

This "double encoding" means the data is actually UTF-8, but MySQL thinks it's latin1.

## Why pymysql makes it worse

When you connect to MySQL with `charset='latin1'`, pymysql receives the raw bytes and tries to decode them. But pymysql maps MySQL's `latin1` to Python's `cp1252` (Windows-1252), not to `iso-8859-1` (true Latin-1).

`cp1252` and `iso-8859-1` differ in the range 0x80–0x9F:

- **iso-8859-1** maps these to control characters (valid, if rarely used)
- **cp1252** maps them to specific characters (€, „, ", etc.) but **leaves gaps** — bytes like 0x81, 0x8D, 0x8F, 0x90, 0x9D have no mapping

When pymysql encounters byte 0x8F (which is common in UTF-8 multi-byte sequences), it throws:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 6: character maps to <undefined>
```

## The fix

After creating the pymysql connection, override the encoding:

```python
conn = pymysql.connect(
    host=host, user=user, password=password,
    database=database, charset='latin1',
    cursorclass=pymysql.cursors.DictCursor
)
# Override pymysql's cp1252 mapping to true latin1
conn.encoding = 'iso-8859-1'
```

This tells pymysql to decode bytes using `iso-8859-1` instead of `cp1252`. Since `iso-8859-1` maps all 256 byte values, nothing throws an error.

## Then decode the double-encoding

The strings you get back are now Python strings where each character corresponds to a raw byte. To recover the original UTF-8:

```python
def decode_vb(text):
    """Decode vBulletin latin1-stored UTF-8 text."""
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
```

The key line is `text.encode('latin1').decode('utf-8')`:
1. `.encode('latin1')` — converts the Python string back to raw bytes
2. `.decode('utf-8')` — interprets those bytes as UTF-8

## Approaches that don't work

We tried several alternatives before landing on the above:

| Approach | Problem |
|---|---|
| `use_unicode=False` | Returns `bytes` everywhere, breaks pymysql's internal type conversion (e.g., `SUM()` results can't convert from bytes to `Decimal`) |
| `charset='binary'` | pymysql raises "unknown encoding" |
| `charset='utf8'` | MySQL tries to convert from latin1 to utf8 on the server side, mangling the double-encoded data |
| Post-processing only (no connection fix) | Crashes on byte 0x8F before you get to post-process |

The `conn.encoding = 'iso-8859-1'` fix is clean, non-invasive, and handles all 256 byte values.

## How to verify

After applying the fix, test with known content:

```python
# Should produce readable characters, not mojibake
for row in db.query("SELECT pagetext FROM post WHERE postid = 12345"):
    text = decode_vb(row['pagetext'])
    print(text)
```

Look for:
- Accented characters (é, ü, ñ) — common in European names
- Euro sign (€) — common in price discussions
- Chinese/Japanese characters — if your forum had international users
- Em dashes, smart quotes — from users pasting from Word

If these display correctly, the encoding chain is working.

## Further reading

- [MySQL character sets and collations](https://dev.mysql.com/doc/refman/8.0/en/charset.html)
- [The difference between latin1, cp1252, and iso-8859-1](https://en.wikipedia.org/wiki/Windows-1252#Codepage_layout)
- pymysql maps MySQL charset names to Python codec names in `pymysql.charset.charset_by_name`
