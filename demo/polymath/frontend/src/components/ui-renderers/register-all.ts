// Side-effect imports — each module's top-level `registerRenderer` call
// runs once at module load. This file is the coordination point between
// Layer 1 (this agent) and Layer 2/3 (Agent C) renderers; both write
// here and the dispatcher's single `import "./register-all"` line picks
// up everything.
//
// Layer 1 — compositional primitives.
import "./LayoutRenderer";
import "./TextRenderer";
import "./MarkdownRenderer";
import "./ImageRenderer";
import "./BadgeRenderer";
import "./ButtonRenderer";
import "./InputRenderer";
// Layer 2 — declarative grammars.
import "./VegaChartRenderer";
import "./MermaidRenderer";
import "./LatexRenderer";
import "./JsonViewerRenderer";
// Layer 3 — sandboxed-HTML escape hatch (gated on the
// `sandboxed_html` feature flag at render time).
import "./SandboxedHTMLRenderer";

// Plan / Chart / Table / Form / TakeoverDialog have dedicated tabs
// (PlanHeader / ChartsTab / TakeoverDialogModal etc.) and don't need
// to land in the Canvas dispatcher. Register them here only if a
// future feature needs them rendered inline.
export {};
