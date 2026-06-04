# ADR 0020 — Frontend Design Philosophy: Software-Tools Aesthetic and Custom Primitives

## Status

Accepted

## Context

By the time a portfolio project reaches its frontend, the hard work is done — the graph
schema is proven, the entity resolution runs, the killer queries return grounded answers. The
frontend's job is to make that visible in a 3-minute walkthrough. The risk is the opposite of
the backend: not "did it work?" but "does it look like every other LLM-built portfolio
project?"

There is a recognizable pattern in AI-generated frontends: centered hero section with a
large gradient headline, a stats grid with four rounded cards showing percentages, frosted
glass panels, purple-to-pink or blue-to-cyan gradient backgrounds, shadcn/ui components with
their default tokens unchanged, lucide icons floated into every empty corner, and marketing
copy like "Empower your workflow" or "Transform your data." This pattern is the modal output
of "build me a React frontend" prompts because it recapitulates the training distribution —
the most common patterns across millions of public React projects. It is recognizable to
any senior engineer who reviews it, and it undermines everything the backend work represents.

The decision to avoid this was not aesthetic preference. It was defensive: the frontend
should not become the thing a recruiter's or interviewer's eye catches and uses to dismiss
the project. The data is interesting; the UI just needs to get out of its way.

## Decision

The frontend follows the **software-tools aesthetic** — Linear, Vercel dashboard, Retool,
react-force-graph's own demo gallery. Custom primitives over shadcn defaults. Restrained
palette over gradient backgrounds. Monospace only where it earns the slot. Dark mode default
that doesn't look like a Halloween theme. These choices are not creative flourishes; they are
the set of anti-patterns most likely to make the UI read as deliberately designed rather than
AI-generated.

## Alternatives Considered

### Option A — shadcn/ui with customized tokens

**What it is**: Use shadcn/ui's component library but override its CSS variables with the
project's color tokens to push past the default look.

**Pros**:
- Large ecosystem of accessible, tested components (Dialog, Dropdown, Table, etc.)
- Saves time on component boilerplate.
- shadcn is genuinely good for production systems.

**Cons**:
- The default shadcn aesthetic is itself a strong AI signal in 2026 — components that are
  95% of the way to default shadcn read as "generated," even with token overrides.
- The primitives this project needs (Button, Badge, Skeleton, ProgressBar, one table) are
  each under 30 lines of TSX. Writing them demonstrates the skill; using shadcn hides it.
- A demo that uses shadcn defaults would look indistinguishable from 1000 other portfolio
  projects.

**Verdict**: Rejected. The primitives are small enough to write. The signal cost of shadcn
defaults is too high.

### Option B — Design-system-first (Radix + Stitches or vanilla-extract)

**What it is**: Use a headless component library (Radix UI) paired with a typed CSS-in-JS
system to build a formal design system.

**Pros**:
- Highest correctness and accessibility baseline.
- Excellent type safety for design tokens.

**Cons**:
- Significant setup and boilerplate for a demo that needs four pages.
- The compilation overhead and added complexity are not justified at this scale.
- Radix + Stitches adds two more non-obvious dependencies to explain to an interviewer.

**Verdict**: Rejected. Overkill for a demo.

### Option C — Tailwind with custom theme (chosen)

**What it is**: Tailwind CSS with the `theme.extend` (and partially `theme.fontSize`)
overridden to establish project-specific color tokens and type scale. No shadcn. Custom
primitives.

**Pros**:
- Zero runtime overhead — Tailwind is pure CSS.
- Overriding the theme at the root level means no default Tailwind colors leak through.
- Small bundle; the PurgeCSS/JIT step strips unused utilities.
- Demonstrates comfort writing CSS through a utility system, not through a component library.

**Cons**:
- No pre-built accessible components — focus rings, ARIA, keyboard nav must be built manually.
- More typing than shadcn for common patterns.

**Verdict**: Accepted. The manual work is bounded (four pages, ~8 primitives) and the signal
value of not looking like shadcn is worth it.

## The anti-pattern list (enforced, not aspirational)

These are explicit prohibitions, not guidelines. Every one was evaluated during implementation:

| Anti-pattern | Why it's a problem |
|---|---|
| Purple-to-pink or any multi-stop gradient on backgrounds or text | The single most recognizable AI-slop signal. Gradients on body text are never appropriate at any size. |
| Centered hero section with headline + subtitle + CTA | Describes a landing page from 2019, not a developer tool. |
| Glass-morphism / frosted glass cards | `backdrop-filter: blur` on cards is the 2022 version of skeumorphism — heavy, distracting, inconsistent across browsers. |
| Stats grid with 4 metrics in rounded cards | Every AI-generated dashboard. Shows no information architecture judgment. |
| Lucide icons as decoration | Icons placed in corners because they exist is visual noise. Icons are used only where they add information density (an arrow on a button, a toggle indicator). |
| Spinner for loading states | A thin top progress bar (2px, no animation jank) is the Linear/GitHub convention. Spinners are for indeterminate loads in modals, not page state. |
| Generic marketing copy | This is a developer tool. The audience can read. "Company Brain ingests scattered company knowledge" is enough. "Transform your organizational intelligence" is not. |
| `text-gray-500` on a white background for body text | Fails WCAG AA contrast at standard body size. Never used. |

## The positive constraints

These are the design rules that replaced the anti-patterns:

1. **7-color palette maximum** — `bg`, `surface`, `s2`, `border`, `txt`, `txt-muted`, `accent`.
   Node colors (6 more) are a separate set. Nothing else.
2. **Monospace only for data** — IDs, timestamps, UUIDs, code-like content. Inter for prose.
3. **Dark mode default** — `html.dark` on page load, no flash. Light mode support is not in
   scope for the demo.
4. **Left-aligned layouts** — The landing page is `max-width: 720px`, left-aligned. No
   centered content below the topbar. Centering is a crutch for designs without hierarchy.
5. **Type hierarchy through size + weight, not boxes** — `text-2xl font-semibold` for page
   titles. `text-sm text-txt-muted` for labels. No cards around things just to make them look
   like cards.

## Consequences

**Enables**: a frontend that reads as deliberate — a senior engineer looking at it sees
choices that would require knowledge to make, not defaults that a model would output.

**Constrains**: no shortcut to pre-built accessible components — keyboard navigation, ARIA
labels, and focus management must be built explicitly. For a demo with four pages and ~200
interactive elements, this is manageable.

**Locked into**: the custom Tailwind token system. Changing the color palette later requires
touching `tailwind.config.js` and the CSS variables in `index.css`, not individual component
files.

**At larger scale / in production**: a production system would graduate to a proper design
system (Radix UI headless components + typed CSS-in-JS, or shadcn with fully custom tokens)
to get accessibility guarantees without hand-rolling each primitive. The current approach
does not scale to 50+ components.

## Interview Defense

> "We avoided shadcn defaults and gradient patterns because both are strong AI-slop signals
> in 2026 — any senior engineer who has reviewed LLM-generated frontends will pattern-match
> on them instantly. The custom Tailwind tokens and small primitives took roughly the same
> time to write as configuring shadcn overrides, but they produce a result that looks like a
> deliberate design decision rather than the modal output of a 'build me a React frontend'
> prompt. The trade-off is that we don't get pre-built accessible components; at this demo
> scale (four pages, eight primitives), that's acceptable — at production scale, we'd use
> Radix UI headless components underneath the same design tokens."
