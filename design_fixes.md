Refactor the website's visual styling to eliminate AI-generated design clichés and make the UI look like a production-grade, human-designed SaaS product (similar to Linear, Stripe, or Vercel).

Follow these specific design constraints:

1. Color Palette & Backgrounds:
   - Remove generic purple/violet/cyan gradients and neon glow blobs behind text or cards.
   - Use a solid, grounded background: if dark mode, use deep neutral slate/zinc (`#09090b` or `#0e1117`) instead of pitch black or oversaturated navy; if light mode, use clean white/off-white (`#fafafa` / `#ffffff`).
   - Limit accent colors to exactly ONE purposeful primary brand color (e.g., emerald green, cobalt blue, or orange) and neutral grays for everything else.

2. Cards & Borders:
   - Eliminate intense frosted glass effects (heavy `backdrop-blur` with 1px bright borders everywhere).
   - Use crisp, subtle structural borders (`border border-neutral-200 dark:border-neutral-800`) with solid card backgrounds (`bg-white dark:bg-neutral-900/50`).
   - Soften borders: no rainbow or glowing borders on hover unless specifically focused.

3. Typography & Hierarchy:
   - Switch typography to a solid system/modern sans-serif (Inter, Geist, Plus Jakarta Sans, or Outfit).
   - Avoid gradient-filled headline text (`bg-clip-text text-transparent bg-gradient-to-r`). Use solid, high-contrast colors (`text-neutral-900 dark:text-neutral-50`).
   - Fix pacing: ensure clear vertical rhythm (8pt grid), restrained headline sizes, and readable body text (14-16px, `text-neutral-600 dark:text-neutral-400`).

4. Shadows & Depth:
   - Remove oversized, muddy, or colored drop shadows.
   - Replace with tight, multi-layered, subtle ambient shadows (e.g., `shadow-sm` or `shadow-md` using low-opacity black/neutral tones, `rgba(0,0,0,0.04)`).

5. Layout, Spacing & Components:
   - Break repetitive 3-column card layouts where every card has an icon in a circle + title + generic 2-sentence description.
   - Use asymmetric grids, bento-grid layouts with varying card sizes, or real product mockups/code snippets/tables instead of generic icons.
   - Remove floating decorative 3D shapes, abstract isometric bubbles, or generic floating badges.
   - Give elements breathing room: increase generous padding inside cards (`p-6` to `p-8`) and section gutters (`py-20` to `py-24`).

6. Micro-interactions & Buttons:
   - Make buttons feel tactile: clean solid fills or clear ghost/outline states with subtle hover transitions (`transition-colors duration-150`), not oversized pulsating glow effects.

Apply these changes across all core layout components, headers, cards, and hero sections while preserving current functionality.
