"use client";

/**
 * LatexRenderer — Layer 2 renderer for LaTeX math via KaTeX.
 *
 * Backend contract (`LatexComponentData`):
 *   { content: string, display: boolean }
 *
 *   - `display=true`  → `<BlockMath>` (centered, large)
 *   - `display=false` → `<InlineMath>` (inline with surrounding text)
 *
 * Side effect:
 *   - `katex/dist/katex.min.css` is imported once at module load. Per-renderer
 *     side-effect imports of CSS are fine — Next/Turbopack dedupes the import
 *     across pages.
 *
 * Error handling:
 *   - KaTeX throws on invalid TeX. We pass `renderError` so the user sees a
 *     compact error rather than an exception bubbling out into the React tree.
 */
import { BlockMath, InlineMath } from "react-katex";
import "katex/dist/katex.min.css";

import { registerRenderer, type UIRenderer } from "./registry";
import { ErrorBox } from "./_helpers";

interface LatexData {
  content: string;
  display: boolean;
}

const LatexRenderer: UIRenderer<LatexData> = (spec) => {
  const Cmp = spec.data.display ? BlockMath : InlineMath;

  return (
    <div className={spec.data.display ? "my-2 overflow-x-auto" : "inline"}>
      <Cmp
        math={spec.data.content}
        renderError={(err: Error) => (
          <ErrorBox message={`LaTeX parse error: ${err.message}`} />
        )}
      />
    </div>
  );
};

registerRenderer("latex", LatexRenderer);
export default LatexRenderer;
