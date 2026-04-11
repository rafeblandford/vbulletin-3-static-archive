# Advanced Visualisations

The basic stats page included in this repo (Chart.js posts-per-month and top-forums charts) works for any forum. For the All About Symbian archive, we built a richer set of visualisations that are worth documenting as a reference for what's possible with vBulletin data.

**Live example:** [allaboutsymbian.com/forum/stats/](https://allaboutsymbian.com/forum/stats/)

## What we built

### Activity heatmap (ECharts)
Hour-of-day × day-of-week grid, colour-coded by post volume. Reveals when the community was active — AAS showed a clear European working-hours pattern (09:00–15:00 weekdays).

**Data:** `SELECT DAYOFWEEK(FROM_UNIXTIME(dateline)), HOUR(FROM_UNIXTIME(dateline)), COUNT(*) FROM post GROUP BY ...`

### Forum affinity network (Cytoscape.js)
Force-directed graph where nodes are forums (sized by post count) and edges connect forums that share active members. Interactive: threshold slider to adjust minimum shared users, click to highlight connections, drag to rearrange.

For AAS, this revealed the Nokia device upgrade path (7650 → 3650 → 6600 → N80 → N95) and showed Sony Ericsson UIQ as a semi-detached community cluster.

**Data:** Self-join on user-forum pairs to count shared users between all forum pairs. Filter to edges with ≥50 shared users, show nodes with >500 posts. The self-join is the heaviest query (~8s on 449K posts).

### Community migration Sankey (ECharts)
Shows how members' primary forum changed across time eras. Each user is assigned to their most-posted forum per era, then flows are drawn between consecutive eras.

For AAS, we used five eras aligned to device generations: 2001-02 (early), 2003-05 (boom), 2006-08 (N-series), 2009-11 (decline), 2012-13 (twilight). The Sankey clearly shows the Nokia upgrade path and the late-era dispersal into general forums.

**Data:** Query user/era/forum post counts, compute primary forum per user per era in Python, count flows between consecutive eras. Filter to flows of ≥5 users.

### ThemeRiver (ECharts)
Centred flowing river showing how the top 15 forums contributed to total activity over time. Each forum is a coloured band; the width represents monthly post volume. Hover to isolate a single forum.

**Data:** Posts per month grouped by forum, for the top 15 forums by total posts. Requires filling missing month/forum combinations with zeros for ECharts to render correctly.

### Thread lifespan (ECharts)
Bar chart showing how long threads with replies stayed active (same day, 1 week, 1 month, 3 months, 1 year, 1+ years).

**Data:** `DATEDIFF(MAX(post.dateline), MIN(post.dateline))` per thread, bucketed.

## Libraries used

| Library | CDN size | What it does |
|---|---|---|
| [Chart.js](https://www.chartjs.org/) | ~200 KB | Posts-per-month line chart, top forums bar chart |
| [ECharts](https://echarts.apache.org/) | ~1 MB | ThemeRiver, heatmap, Sankey, lifespan bar |
| [Cytoscape.js](https://js.cytoscape.org/) | ~400 KB | Forum affinity network graph |

All loaded from cdn.jsdelivr.net. The combined ~1.6 MB is significant for Lighthouse Performance scores. For the basic stats page (Chart.js only), the cost is ~200 KB.

## Included in the default template

All advanced visualisations are now included in the default `stats.html` template and `build_pages.py`. The data queries run automatically — forums with insufficient data will simply produce smaller or empty charts.

The editorial descriptions in the template reference AAS-specific history. Customise these for your own forum by editing the `<p>` elements in `templates/stats.html`.

**Note:** The combined JS payload (~1.6 MB) is significant. The stats page loads these from CDN, which is acceptable for a page users visit intentionally. Thread and listing pages use no external JS.

## Fast iteration

Use `build_pages.py` to regenerate just the stats, about, search, and index pages without rebuilding all thread pages:

```bash
python3 build_pages.py -c config.yaml -o ./output/
```

This takes ~13 seconds vs ~2 minutes for a full build, making it practical to iterate on chart configuration and layout.
