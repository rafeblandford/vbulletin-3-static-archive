# BBCode Converter

The generator includes a custom BBCode-to-HTML converter (~100 lines) that handles the full range of vBulletin 3.x formatting. This document covers what's supported, known edge cases, and how to extend it.

## Why a custom converter

Existing BBCode libraries (e.g., `bbcode`, `postmarkup`) handle standard BBCode but not vBulletin's quirks:

- **`[QUOTE=username;postid]`** — vBulletin's quote format includes a post ID for linking back to the quoted post. Generic libraries only handle `[QUOTE]` or `[QUOTE=username]`.
- **`[ATTACH]id[/ATTACH]`** — attachment references that need resolving against the database.
- **`[addsig]`** — legacy marker from vBulletin's "append signature" feature.
- **HTML comments from phpBB migration** — some vBulletin databases were migrated from phpBB and contain `<!-- ... -->` comments in post content.
- **Internal link rewriting** — `showthread.php?t=12345` URLs need converting to archive paths.

Building a custom converter also means we control the output HTML classes and can match them to our CSS.

## What's converted

### Standard formatting
| BBCode | Output |
|---|---|
| `[b]text[/b]` | `<strong>text</strong>` |
| `[i]text[/i]` | `<em>text</em>` |
| `[u]text[/u]` | `<u>text</u>` |
| `[s]text[/s]` | `<s>text</s>` |
| `[color=red]text[/color]` | `<span style="color:red">text</span>` |
| `[SIZE=3]text[/SIZE]` | `<span class="text-size-3">text</span>` |

### Links and images
| BBCode | Output |
|---|---|
| `[url=http://example.com]text[/url]` | `<a href="..." rel="nofollow">text</a>` |
| `[url]http://example.com[/url]` | `<a href="..." rel="nofollow">http://example.com</a>` |
| `[img]http://example.com/pic.jpg[/img]` | `<img src="..." loading="lazy" class="post-image">` |

All external links get `rel="nofollow"`. URLs without a protocol prefix get `http://` prepended. HTML entities in URLs (`&quot;`, `&amp;`) are cleaned up.

### Quotes
| BBCode | Output |
|---|---|
| `[QUOTE]text[/QUOTE]` | `<blockquote class="post-quote">text</blockquote>` |
| `[QUOTE=Alice]text[/QUOTE]` | `<blockquote>` with `<cite>Alice wrote:</cite>` |
| `[QUOTE=Alice;12345]text[/QUOTE]` | Quote with cite linking to `#post12345` |

Nested quotes are handled by running the regex up to 5 passes. This handles the common case of 2-3 levels of quoting. Deeply nested quotes (>5 levels) will have the innermost quotes left as BBCode text — this is extremely rare in practice.

### Code blocks
```
[code]some code here[/code]
```
Becomes `<pre class="post-code"><code>...</code></pre>`.

### Lists
```
[list]
[*]First item
[*]Second item
[/list]
```
Becomes a standard `<ul>` with `<li>` elements.

### Attachments
```
[ATTACH]12345[/ATTACH]
```
Initially converted to `<!-- ATTACH:12345 -->` placeholder, then resolved against the attachment database to produce either an inline image or a download link, depending on file type.

### Smilies
- **Legacy image tags** (from phpBB migration): `<img src="/phpBB/images/smiles/...">` → generic smiley emoji
- **Text codes**: `:)`, `;)`, `:D`, `:(`, `:rolleyes:`, `:cool:`, `:eek:`, etc. → Unicode emoji equivalents

## Processing order

The converter processes BBCode in a specific order:

1. Strip legacy markers (`[addsig]`, HTML comments)
2. HTML-escape all text (prevents XSS from user content)
3. Convert BBCode tags to HTML (working with the escaped text)
4. Convert smilies
5. Convert line breaks (`\n\n` → `</p><p>`, `\n` → `<br>`)
6. Wrap in `<p>` tags

The HTML-escape-first approach is important for security: user content is escaped before any HTML is generated, so BBCode like `[url=javascript:alert(1)]` produces escaped, harmless output.

## Internal link rewriting

After BBCode conversion, a second pass rewrites vBulletin URLs:

| Original | Rewritten |
|---|---|
| `showthread.php?t=12345` | `/forum/thread/12345/` |
| `showthread.php?p=67890` | `/forum/thread/{tid}/#post67890` (resolved via post-thread map) |
| `forumdisplay.php?f=42` | `/forum/f/42/` |

The base path is configurable (e.g., `/forum` or empty for root).

Post-to-thread resolution requires building a `postid → threadid` map from the database at startup. For the All About Symbian archive (449K posts), this takes a few seconds and uses ~50 MB of memory.

## Known edge cases

- **Malformed BBCode** — unclosed tags, mismatched tags, or tags with unexpected attributes are left as-is (the escaped BBCode text remains visible). This is intentional: better to show `[b]something` than to silently eat content.
- **Deeply nested quotes** — more than 5 levels of nesting won't be fully converted. Extremely rare in practice.
- **Custom vBulletin BBCode** — some forums add custom BBCode via plugins (e.g., `[spoiler]`, `[youtube]`). These won't be converted and will appear as text. See "Extending" below.
- **[SIZE] values** — vBulletin uses its own size scale (1-7), not pixels. The converter outputs a CSS class (`text-size-3`) that you can style as needed.
- **Mixed HTML and BBCode** — some posts contain raw HTML (from admin posts or database edits). The HTML-escape step converts this to visible text, which is the safe default.

## Extending the converter

To add support for additional BBCode tags, add a regex substitution in the `bbcode_to_html()` function. Example for a `[spoiler]` tag:

```python
# [spoiler]
text = re.sub(r'\[spoiler\](.*?)\[/spoiler\]',
              r'<details class="post-spoiler"><summary>Spoiler</summary>\1</details>',
              text, flags=re.DOTALL | re.IGNORECASE)
```

Place new conversions after the HTML escape step but before line break processing.

For a `[youtube]` tag:

```python
# [youtube]VIDEO_ID[/youtube]
text = re.sub(r'\[youtube\]([a-zA-Z0-9_-]{11})\[/youtube\]',
              r'<div class="post-video"><a href="https://www.youtube.com/watch?v=\1">YouTube video: \1</a></div>',
              text, flags=re.IGNORECASE)
```

Note: embedding YouTube iframes would require updating your Content Security Policy. A link is the safer default for an archive.
