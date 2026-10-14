# standing-viewer

Shows your personal course-standing file — the YAML file your instructor sends you — as a readable progress page: released marks, category totals and where you stand against the course hurdles.

**How it works**: `standing-view.html` is a self-contained page with no server and no install step. Open it directly in a browser (double-click it, or drag it onto an open browser window), then drop in or choose your personal status `.yaml` file. Everything runs client-side — the file never leaves your computer. The page loads the YAML reader from the internet, so you need to be online the first time you open it.

```bash
open standing-viewer/standing-view.html
```

Only marks already released in Brightspace are shown. The page is a planning aid, not an official grade.
