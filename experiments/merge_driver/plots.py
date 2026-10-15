"""Render the merge-driver results as static SVG charts, light and dark.

Hand-written SVG with no dependencies, so the figures are reproducible from
the committed data byte for byte (tests/test_experiment_plots.py checks it).

    python experiments/merge_driver/plots.py --data DIR --out DIR
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from html import escape
from pathlib import Path

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
THEMES = {
    'light': {
        'surface': '#fcfcfb', 'ink': '#0b0b0b', 'ink2': '#52514e', 'muted': '#898781',
        'grid': '#e1e0d9', 'axis': '#c3c2b7', 'neutral': '#898781', 'neutral2': '#c3c2b7',
        'accent': '#2a78d6', 'amber': '#eda100',
    },
    'dark': {
        'surface': '#1a1a19', 'ink': '#ffffff', 'ink2': '#c3c2b7', 'muted': '#898781',
        'grid': '#2c2c2a', 'axis': '#383835', 'neutral': '#898781', 'neutral2': '#55544f',
        'accent': '#3987e5', 'amber': '#c98500',
    },
}
# Outcome colors, validated with the dataviz palette checker in both themes
# (blue / amber / red pass colour-vision separation; green beside red does
# not). Every use sits beside a text label, and the data ships as a table.
CRITICAL = '#d03b3b'

OUTCOME_STYLE = [  # (outcome, label, theme key or hex)
    ('fresh', 'Merged; artifacts match a rebuild', 'accent'),
    ('source', 'Stopped: the source conflicts', 'neutral'),
    ('other-stop', 'Stopped: nothing left to apply', 'neutral2'),
    ('metadata-only', 'Stopped needlessly on .semantic/', 'amber'),
    ('stale', 'Merged; artifacts silently wrong', CRITICAL),
]


def ink_on(fill: str) -> str:
    """Black or white label ink for text set inside a filled mark."""
    r, g, b = (int(fill[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lum = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    luminance = 0.2126 * lum(r) + 0.7152 * lum(g) + 0.0722 * lum(b)
    return '#0b0b0b' if (luminance + 0.05) / 0.05 > 1.05 / (luminance + 0.05) else '#ffffff'


def text_width(text: str, size: float) -> float:
    return len(text) * size * 0.6


class Svg:
    def __init__(self, width: int, height: int, theme: dict, title: str) -> None:
        self.width, self.height, self.t = width, height, theme
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" font-family="{escape(FONT)}">',
            f'<title>{escape(title)}</title>',
            f'<rect width="{width}" height="{height}" rx="8" fill="{theme["surface"]}"/>',
        ]

    def color(self, key: str) -> str:
        return self.t.get(key, key)

    def text(self, x: float, y: float, value: str, size: int = 13, fill: str = 'ink',
             weight: int = 400, anchor: str = 'start') -> None:
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
            f'fill="{self.color(fill)}" text-anchor="{anchor}">{escape(value)}</text>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, stroke: str, width: float = 1) -> None:
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{self.color(stroke)}" stroke-width="{width}"/>'
        )

    def bar(self, x: float, y: float, w: float, h: float, fill: str, round_end: bool) -> None:
        """A horizontal bar segment; only the data end is rounded (4px)."""
        if w <= 0:
            return
        fill = self.color(fill)
        r = min(4.0, w / 2, h / 2) if round_end else 0
        if r == 0:
            self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"/>')
            return
        self.parts.append(
            f'<path d="M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
            f'V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z" fill="{fill}"/>'
        )

    def swatch(self, x: float, y: float, fill: str) -> None:
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="10" height="10" rx="2" fill="{self.color(fill)}"/>')

    def render(self) -> str:
        return '\n'.join(self.parts + ['</svg>']) + '\n'


def replay_chart(data: Path, theme: dict) -> str:
    rows = list(csv.DictReader(open(data / 'replay.csv', encoding='utf-8')))
    meta = json.loads((data / 'replay.json').read_text(encoding='utf-8'))
    groups = [(mode, method) for mode in ('merge', 'rebase', 'cherry-pick') for method in ('text', 'driver')]
    counts = {g: Counter(r['outcome'] for r in rows if (r['mode'], r['method']) == g) for g in groups}
    trials = meta['trials']

    width, left, right = 760, 138, 64
    plot_w = width - left - right
    top, header_h, bar_h, pair_gap, group_gap = 124, 22, 22, 8, 18
    height = top + 3 * (header_h + 2 * bar_h + pair_gap + group_gap) + 30
    svg = Svg(width, height, theme, f'Outcome of {trials} replayed concurrent changes, Git text merge vs AIGit driver')
    svg.text(24, 36, 'What happens to .semantic/ when two branches meet', 18, weight=600)
    svg.text(24, 58, f'{trials} replayed pairs of concurrent changes on this repository, '
                     'each combined three ways', 13, 'ink2')

    legend_x, legend_y = 24, 86
    for outcome, label, fill in OUTCOME_STYLE:
        svg.swatch(legend_x, legend_y - 9, fill)
        svg.text(legend_x + 16, legend_y, label, 12, 'ink2')
        legend_x += 16 + text_width(label, 12) + 22
        if legend_x > width - 200:
            legend_x, legend_y = 24, legend_y + 18

    y = top
    for mode in ('merge', 'rebase', 'cherry-pick'):
        svg.text(24, y + 14, f'git {mode}', 13, weight=600)
        y += header_h
        for method in ('text', 'driver'):
            label = 'Git text merge' if method == 'text' else 'AIGit driver'
            svg.text(left - 12, y + bar_h - 6, label, 12, 'ink2', anchor='end')
            x = left
            present = [(o, f) for o, _, f in OUTCOME_STYLE if counts[(mode, method)][o]]
            for i, (outcome, fill) in enumerate(present):
                n = counts[(mode, method)][outcome]
                w = plot_w * n / trials
                last = i == len(present) - 1
                svg.bar(x, y, w - (0 if last else 2), bar_h, fill, round_end=last)
                if text_width(str(n), 11) + 10 < w - 2:
                    ink = ink_on(svg.color(fill))
                    svg.parts.append(
                        f'<text x="{x + (w - 2) / 2:.1f}" y="{y + bar_h - 7:.1f}" font-size="11" font-weight="600" '
                        f'fill="{ink}" text-anchor="middle">{n}</text>'
                    )
                x += w
            stale = counts[(mode, method)]['stale']
            svg.text(left + plot_w + 8, y + bar_h - 6, f'{stale} stale', 11, 'muted')
            y += bar_h + pair_gap
        y += group_gap - pair_gap
    svg.text(24, height - 14, f"Git {meta['git']} · AIGit {meta['aigit_commit'][:7]} · seed {meta['seed']} · "
                              'data: replay.csv', 11, 'muted')
    return svg.render()


def algorithms_chart(data: Path, theme: dict) -> str:
    meta = json.loads((data / 'algorithms.json').read_text(encoding='utf-8'))
    summary, trials = meta['summary'], meta['trials']
    kinds = [
        ('both clean, different text', 'Both merge cleanly, into different text', CRITICAL),
        ('merge-file clean, git conflicts', 'merge-file clean, Git conflicts', 'neutral'),
        ('git clean, merge-file conflicts', 'Git clean, merge-file conflicts', 'neutral'),
    ]
    disagree = sum(summary.get(k, 0) for k, _, _ in kinds)
    width, left, right, top, bar_h, gap = 760, 300, 60, 104, 22, 14
    height = top + len(kinds) * (bar_h + gap) + 34
    scale_max = max(max(summary.get(k, 0) for k, _, _ in kinds), 1)
    svg = Svg(width, height, theme, 'Where git merge-file and git merge disagree')
    svg.text(24, 36, 'Why the driver runs Git’s own merge', 18, weight=600)
    svg.text(24, 58, f'{disagree} of {trials} random three-way merges differ between git merge-file (Myers diff)', 13, 'ink2')
    svg.text(24, 76, "and git merge (ort's histogram diff). Red: stale artifacts with no conflict at all", 13, 'ink2')
    y = top
    for key, label, fill in kinds:
        n = summary.get(key, 0)
        svg.text(left - 12, y + bar_h - 6, label, 12, 'ink2', anchor='end')
        w = (width - left - right) * n / scale_max
        svg.bar(left, y, w, bar_h, fill, round_end=True)
        svg.text(left + w + 8, y + bar_h - 6, str(n), 12, weight=600)
        y += bar_h + gap
    svg.line(left, top - 6, left, y - gap + 6, 'axis')
    svg.text(24, height - 14, f"Git {meta['git']} · seed {meta['seed']} · data: algorithms.csv", 11, 'muted')
    return svg.render()


def scaling_chart(data: Path, theme: dict) -> str:
    rows = list(csv.DictReader(open(data / 'scaling.csv', encoding='utf-8')))
    meta = json.loads((data / 'scaling.json').read_text(encoding='utf-8'))
    series = {v: [(int(r['files']), float(r['median_seconds'])) for r in rows if r['variant'] == v]
              for v in ('per-file', 'batched')}
    width, height = 760, 410
    left, right, top, bottom = 64, 150, 96, 80
    plot_w, plot_h = width - left - right, height - top - bottom
    x_max = max(f for pts in series.values() for f, _ in pts)
    y_raw = max(s for pts in series.values() for _, s in pts)
    step = next(s for s in (1, 2, 5, 10, 20, 50) if y_raw / s <= 6)
    y_max = step * -(-y_raw // step)
    px = lambda f: left + plot_w * f / x_max
    py = lambda s: top + plot_h * (1 - s / y_max)

    svg = Svg(width, height, theme, 'Merge time against files changed on both sides')
    svg.text(24, 36, 'One batched merge instead of one per file', 18, weight=600)
    svg.text(24, 58, 'Wall time of git merge (median of '
                     f"{meta['repeats']}) when every file was changed on both branches", 13, 'ink2')
    legend_x = 24
    for variant, fill, label in (('batched', 'accent', 'Batched (now)'), ('per-file', 'neutral', 'Per file (before)')):
        svg.line(legend_x, 77, legend_x + 16, 77, fill, 2)
        svg.text(legend_x + 22, 81, label, 12, 'ink2')
        legend_x += 22 + text_width(label, 12) + 24
    tick = 0
    while tick <= y_max:
        svg.line(left, py(tick), left + plot_w, py(tick), 'grid' if tick else 'axis')
        svg.text(left - 8, py(tick) + 4, f'{tick:g} s', 11, 'muted', anchor='end')
        tick += step
    for f, _ in series['batched']:
        svg.text(px(f), top + plot_h + 18, str(f), 11, 'muted', anchor='middle')
    svg.text(left + plot_w / 2, top + plot_h + 40, 'files changed on both sides', 12, 'ink2', anchor='middle')
    for variant, fill, label in (('per-file', 'neutral', 'per file'), ('batched', 'accent', 'batched')):
        pts = series[variant]
        path = ' '.join(f'{"M" if i == 0 else "L"}{px(f):.1f},{py(s):.1f}' for i, (f, s) in enumerate(pts))
        svg.parts.append(f'<path d="{path}" fill="none" stroke="{svg.color(fill)}" stroke-width="2" '
                         'stroke-linejoin="round" stroke-linecap="round"/>')
        for f, s in pts:
            svg.parts.append(f'<circle cx="{px(f):.1f}" cy="{py(s):.1f}" r="4" fill="{svg.color(fill)}" '
                             f'stroke="{svg.color("surface")}" stroke-width="2"/>')
        f, s = pts[-1]
        svg.text(px(f) + 10, py(s) + 4, f'{s:.1f} s {label}', 12, 'ink', weight=600)
    svg.text(24, height - 14, f"Git {meta['git']} · {meta['platform'].split('-')[0]} · data: scaling.csv", 11, 'muted')
    return svg.render()


def headline(data: Path, theme: dict) -> str:
    replay = list(csv.DictReader(open(data / 'replay.csv', encoding='utf-8')))
    sweep = list(csv.DictReader(open(data / 'sweep.csv', encoding='utf-8')))
    driver = [r for r in replay if r['method'] == 'driver']
    text = [r for r in replay if r['method'] == 'text']
    tiles = [
        (f"{sum(r['outcome'] == 'stale' for r in driver)}", 'stale merges',
         f'across {len(driver):,} replayed merges,', 'rebases and cherry-picks'),
        (f"{sum(r['outcome'] == 'metadata-only' for r in driver)}", 'needless .semantic/ conflicts',
         f"Git's text merge stopped {sum(r['outcome'] == 'metadata-only' for r in text)} times", 'on the same changes'),
        (f"{sum(int(r['as_expected']) for r in sweep)}/{len(sweep)}", 'corner cases handled',
         'merge queues, reverts, stash,', 'renames, symlinks, worktrees'),
    ]
    width, height, gap = 760, 168, 16
    tile_w = (width - 48 - gap * 2) / 3
    svg = Svg(width, height, theme, 'AIGit merge driver results')
    for i, (value, label, note1, note2) in enumerate(tiles):
        x = 24 + i * (tile_w + gap)
        svg.parts.append(f'<rect x="{x:.1f}" y="16" width="{tile_w:.1f}" height="{height - 32}" rx="8" '
                         f'fill="none" stroke="{svg.color("grid")}"/>')
        svg.text(x + 18, 66, value, 40, weight=600)
        svg.text(x + 18, 92, label, 13, weight=600)
        svg.text(x + 18, 116, note1, 11, 'ink2')
        svg.text(x + 18, 132, note2, 11, 'ink2')
    return svg.render()


CHARTS = {'headline': headline, 'replay-outcomes': replay_chart,
          'algorithm-divergence': algorithms_chart, 'scaling': scaling_chart}


def render_all(data: Path) -> dict[str, str]:
    return {f'{name}-{mode}.svg': chart(data, THEMES[mode]) for name, chart in CHARTS.items() for mode in THEMES}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, svg in render_all(args.data).items():
        (args.out / name).write_text(svg, encoding='utf-8')
        print(args.out / name)


if __name__ == '__main__':
    main()
