import type { ReactNode } from "react";

type TreeObj = Record<string, unknown>;

const BREEDERS = ["lab_b", "lab_c", "lab_d", "lab_e"] as const;

/**
 * SVG graph from ``labs_breeding_tree_snapshot.nodes`` + ``edges`` (birth / assignment / adoption).
 */
export default function BreedingLineageGraph({ tree }: { tree: TreeObj }) {
  const nodes = Array.isArray(tree?.nodes) ? (tree.nodes as TreeObj[]) : [];
  const edges = Array.isArray(tree?.edges) ? (tree.edges as TreeObj[]) : [];
  const W = 480;
  const H = 210;
  const padX = 28;
  const topY = 36;
  const midY = 108;
  const botY = 172;

  const step = (W - 2 * padX) / 3;
  const parentX: Record<string, number> = {};
  BREEDERS.forEach((bid, i) => {
    parentX[bid] = padX + i * step;
  });

  const nodeById = new Map<string, TreeObj>();
  for (const n of nodes) {
    const id = String(n?.id || "");
    if (id) nodeById.set(id, n);
  }

  const childIds = nodes.filter((n) => String(n?.kind || "").toLowerCase() === "child").map((n) => String(n.id || ""));
  const childX: Record<string, number> = {};
  for (const cid of childIds) {
    const ins = edges.filter((e) => String(e?.to || "") === cid && String(e?.kind || "") === "birth");
    const xs: number[] = [];
    for (const e of ins) {
      const from = String(e?.from || "").toLowerCase();
      if (parentX[from] != null) xs.push(parentX[from]!);
    }
    childX[cid] = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : W / 2;
  }

  const slotIds = nodes.filter((n) => String(n?.kind || "").toLowerCase() === "slot").map((n) => String(n.id || ""));
  const slotX: Record<string, number> = {};
  let slotIdx = 0;
  for (const sid of slotIds) {
    slotX[sid] = padX + (slotIdx % 6) * ((W - 2 * padX) / 5.5);
    slotIdx += 1;
  }

  const labAX = W - padX - 8;

  const lines: ReactNode[] = [];
  for (const e of edges) {
    const from = String(e?.from || "");
    const to = String(e?.to || "");
    const kind = String(e?.kind || "").toLowerCase();
    let x1: number;
    let y1: number;
    let x2: number;
    let y2: number;
    if (kind === "birth") {
      x1 = parentX[from] ?? W / 2;
      y1 = topY + 14;
      x2 = childX[to] ?? W / 2;
      y2 = midY - 12;
    } else if (kind === "assignment") {
      x1 = childX[from] ?? W / 2;
      y1 = midY + 12;
      x2 = slotX[to] ?? W / 2;
      y2 = botY - 14;
    } else if (kind === "adoption") {
      x1 = childX[from] ?? W / 2;
      y1 = midY - 2;
      x2 = labAX;
      y2 = topY + 4;
    } else {
      continue;
    }
    if (!Number.isFinite(x1) || !Number.isFinite(x2)) continue;
    const stroke =
      kind === "adoption" ? "rgba(167, 139, 250, 0.75)" : kind === "assignment" ? "rgba(94, 234, 212, 0.55)" : "rgba(110, 231, 255, 0.5)";
    lines.push(
      <line
        key={`${from}-${to}-${kind}-${lines.length}`}
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={stroke}
        strokeWidth={kind === "birth" ? 1.5 : 1.25}
        fill="none"
      />,
    );
  }

  const parentRects = BREEDERS.map((bid) => {
    const n = nodeById.get(bid);
    const x = parentX[bid] ?? 0;
    const label = String(n?.label || bid.replace("lab_", "Lab ").toUpperCase());
    const run = Boolean(n?.engine_running);
    return (
      <g key={bid}>
        <rect
          x={x - 34}
          y={topY - 22}
          width={68}
          height={28}
          rx={6}
          fill={run ? "rgba(34, 197, 94, 0.12)" : "rgba(9, 14, 34, 0.85)"}
          stroke={run ? "rgba(74, 222, 128, 0.55)" : "rgba(82, 97, 148, 0.75)"}
        />
        <text x={x} y={topY - 6} textAnchor="middle" fill="#e8eeff" fontSize={11} fontWeight={700}>
          {label.replace("Lab ", "")}
        </text>
      </g>
    );
  });

  const childRects = childIds.map((cid) => {
    const n = nodeById.get(cid);
    const x = childX[cid] ?? W / 2;
    const short = String(n?.label || cid.replace("child:", "").slice(0, 8));
    return (
      <g key={cid}>
        <rect x={x - 38} y={midY - 16} width={76} height={26} rx={6} fill="rgba(9, 14, 34, 0.88)" stroke="rgba(110, 231, 255, 0.55)" />
        <text x={x} y={midY} textAnchor="middle" fill="#c9d6f6" fontSize={10} fontWeight={600}>
          {short}
        </text>
      </g>
    );
  });

  const slotRects = slotIds.slice(0, 6).map((sid) => {
    const n = nodeById.get(sid);
    const x = slotX[sid] ?? W / 2;
    const label = String(n?.label || sid).replace(/_/g, " ").slice(0, 14);
    return (
      <g key={sid}>
        <rect x={x - 36} y={botY - 16} width={72} height={24} rx={5} fill="rgba(9, 14, 34, 0.75)" stroke="rgba(94, 234, 212, 0.45)" />
        <text x={x} y={botY} textAnchor="middle" fill="#94a3b8" fontSize={9} fontWeight={600}>
          {label}
        </text>
      </g>
    );
  });

  return (
    <div className="dash-breeding-lineage-graph" role="img" aria-label="Breeding lineage graph from server tree edges">
      <div className="sub" style={{ margin: "0 0 6px", fontSize: 11 }}>
        Lineage graph (parents {">"} children {">"} slots / Lab A). Same data as Tree tabs, from{" "}
        <code>labs_breeding_tree_snapshot</code>.
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ maxWidth: 520, display: "block" }}>
        <rect width={W} height={H} fill="rgba(6, 10, 24, 0.35)" rx={8} />
        {lines}
        {parentRects}
        {childRects}
        {slotRects}
        <g>
          <rect x={labAX - 40} y={topY - 22} width={80} height={28} rx={6} fill="rgba(99, 102, 241, 0.15)" stroke="rgba(165, 180, 252, 0.55)" />
          <text x={labAX} y={topY - 6} textAnchor="middle" fill="#c4b5fd" fontSize={10} fontWeight={700}>
            Lab A
          </text>
        </g>
      </svg>
    </div>
  );
}
