# feedback-viewer

Renders a [GradeIt](https://github.com/ayalac1111/GradeIt) feedback YAML file — the file your instructor sends back after grading a lab — as a readable, colour-coded report instead of raw YAML.

**How it works**: `feedback-view.html` is a self-contained page with no server and no install step. Open it directly in a browser (double-click it, or drag it onto an open browser window), then open or drag in your `studID-Lab-feedback.yaml` file(s). Everything runs client-side — the file never leaves your computer.

```bash
open feedback-viewer/feedback-view.html
```

Load more than one feedback file at once (one per lab) to build up a history you can click through in the sidebar. Each task shows its points earned out of the possible points, with the grader's comment underneath, colour-coded green (full credit), amber (partial credit), or red (no credit).
