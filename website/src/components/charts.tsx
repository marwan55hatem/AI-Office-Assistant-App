/** Small SVG charts (no chart library). Each has a text alternative for screen readers.
 *  Charts keep left-to-right time even on the Arabic site, like printed Arabic charts do. */

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= value) return step * power;
  return 10 * power;
}

type Series = { name: string; color: string; values: (number | null)[]; dashed?: boolean };

export function LineChart({ labels, series, max = 100, unit = "%", summary }: {
  labels: string[]; series: Series[]; max?: number; unit?: string; summary: string;
}) {
  const W = 720, H = 240, L = 40, R = 12, T = 12, B = 28;
  const x = (i: number) => L + (labels.length <= 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (labels.length - 1));
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const every = Math.max(1, Math.ceil(labels.length / 8));
  return (
    <figure style={{ margin: 0 }}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} style={{ direction: "ltr" }} width="100%">
        {ticks.map((v) => (
          <g key={v}>
            <line className="grid-line" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            <text x={L - 6} y={y(v) + 4} textAnchor="end">{Math.round(v)}{unit}</text>
          </g>
        ))}
        {labels.map((label, i) => (i % every === 0 || i === labels.length - 1 ? (
          <text key={i} x={x(i)} y={H - 8}
                textAnchor={labels.length > 1 && i === 0 ? "start" : labels.length > 1 && i === labels.length - 1 ? "end" : "middle"}>{label}</text>
        ) : null))}
        {series.map((s) => {
          // a line is broken where there is no data (null), never drawn down to zero
          const runs: string[] = [];
          let current = "";
          s.values.forEach((v, i) => {
            if (v === null) {
              if (current) runs.push(current);
              current = "";
            } else current += `${current ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
          });
          if (current) runs.push(current);
          return (
            <g key={s.name}>
              {runs.map((d, i) => <path key={i} d={d} fill="none" style={{ stroke: s.color }} strokeWidth={2.5}
                                         strokeDasharray={s.dashed ? "6 5" : undefined} />)}
              {!s.dashed && s.values.map((v, i) => (v === null ? null :
                <circle key={i} cx={x(i)} cy={y(v)} r={3.2} style={{ fill: s.color }} />))}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export function StackedBars({ labels, rows, colors, names, summary, unit = "h", width = 720 }: {
  labels: string[]; rows: number[][]; colors: string[]; names: string[]; summary: string; unit?: string; width?: number;
}) {
  // `width` is the drawing's own width: a narrower drawing keeps its text readable in a narrow card
  const W = width, H = 240, L = 40, R = 12, T = 12, B = 28;
  const max = niceMax(Math.max(0, ...rows.map((r) => r.reduce((a, b) => a + b, 0))));
  const band = (W - L - R) / Math.max(labels.length, 1);
  const bar = Math.min(36, band * 0.6);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const every = Math.max(1, Math.ceil(labels.length / Math.max(3, Math.floor(W / 90))));
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} style={{ direction: "ltr" }} width="100%">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line className="grid-line" x1={L} x2={W - R} y1={y(f * max)} y2={y(f * max)} />
          <text x={L - 6} y={y(f * max) + 4} textAnchor="end">{+(f * max).toFixed(1)}{unit}</text>
        </g>
      ))}
      {rows.map((row, i) => {
        let base = 0;
        const cx = L + band * i + band / 2;
        return (
          <g key={i}>
            {row.map((value, k) => {
              const top = y(base + value);
              const height = y(base) - top;
              base += value;
              return height > 0 ? <rect key={k} x={cx - bar / 2} y={top} width={bar} height={height} style={{ fill: colors[k] }}>
                <title>{`${labels[i]} · ${names[k]}: ${value.toFixed(1)}${unit}`}</title>
              </rect> : null;
            })}
            {i % every === 0 || i === rows.length - 1 ? <text x={cx} y={H - 8} textAnchor="middle">{labels[i]}</text> : null}
          </g>
        );
      })}
    </svg>
  );
}

const DONUT = ["#2563eb", "#0f766e", "#c2410c", "#7c3aed", "#0891b2", "#db2777"];

export function Donut({ slices, center, summary }: { slices: { name: string; value: number; caption: string }[];
  center: string; summary: string }) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  const R = 70, r = 44, C = 90;
  const sweeps = slices.map((s) => (s.value / total) * Math.PI * 2);
  const starts = sweeps.map((_s, i) => -Math.PI / 2 + sweeps.slice(0, i).reduce((a, b) => a + b, 0));
  const arcs = slices.map((s, i) => {
    const a0 = starts[i], a1 = starts[i] + Math.min(sweeps[i], Math.PI * 2 - 0.0001);
    const p = (a: number, rad: number) => `${C + rad * Math.cos(a)},${C + rad * Math.sin(a)}`;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const d = `M${p(a0, R)} A${R},${R} 0 ${large} 1 ${p(a1, R)} L${p(a1, r)} A${r},${r} 0 ${large} 0 ${p(a0, r)} Z`;
    return <path key={s.name} d={d} fill={DONUT[i % DONUT.length]}><title>{`${s.name}: ${s.caption}`}</title></path>;
  });
  return (
    <div className="row" style={{ alignItems: "center", gap: 20 }}>
      <svg viewBox="0 0 180 180" width={180} height={180} role="img" aria-label={summary} className="chart">
        {arcs}
        <text x={C} y={C + 5} textAnchor="middle" style={{ fontSize: 15, fontWeight: 700, fill: "var(--text)" }}>{center}</text>
      </svg>
      <ul className="list" style={{ listStyle: "none", padding: 0, flex: 1, minWidth: 200 }}>
        {slices.map((s, i) => (
          <li key={s.name} className="row" style={{ marginBottom: 4 }}>
            <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 3, background: DONUT[i % DONUT.length] }} />
            <span>{s.name}</span>
            <span className="spacer" />
            <span className="muted">{s.caption}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
