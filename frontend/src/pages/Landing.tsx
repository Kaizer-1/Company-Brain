/**
 * / — Landing page.
 *
 * Single-column, max-width 720px, left-aligned. Three paragraphs explaining
 * what Company Brain is, followed by a list of the four killer queries with
 * "Try it" links to /queries?kq=N, and a link to the graph.
 *
 * No hero. No stats grid. No marketing copy.
 */

import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

const KQS = [
  {
    id: 'kq1',
    question: 'Who owns the service that depends on the system deprecated by Decision X?',
    note: 'Multi-hop graph traversal — RAG cannot follow typed edges',
  },
  {
    id: 'kq2',
    question: 'Which currently-active decisions are contradicted by recent discussions?',
    note: 'Temporal contradiction — RAG retrieves similar text, not logical contradictions',
  },
  {
    id: 'kq3',
    question: 'If the payments service fails, which services, decisions, and people are affected?',
    note: 'Graph reachability — RAG has no model of structural dependencies',
  },
  {
    id: 'kq4',
    question: 'What changed about the auth system in the last quarter, and who approved each change?',
    note: 'Temporal edge traversal — RAG cannot reconstruct a change timeline with approvers',
  },
] as const;

export function Landing() {
  return (
    <div className="h-page overflow-y-auto">
      <div className="max-w-content mx-auto px-6 py-10 space-y-8">
        {/* Project description */}
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold text-txt">Company Brain</h1>
          <p className="text-base text-txt leading-relaxed">
            A self-updating knowledge graph built from scattered company knowledge — Slack messages,
            architecture decision records, and meeting notes. Entities are extracted by an LLM
            pipeline, resolved across surface forms (three aliases for the same person collapse into
            one canonical node), and queryable by structured graph traversal rather than
            similarity-based retrieval.
          </p>
          <p className="text-base text-txt leading-relaxed">
            The distinguishing claim: four queries that require multi-hop graph traversal, temporal
            reasoning, or structural reachability — capabilities where retrieval-augmented generation
            fails by design. Every answer carries provenance back to the raw source event that
            asserted it. Every AI resolution decision (merge or no-merge) is logged with its
            reasoning in a queryable audit trail.
          </p>
          <p className="text-base text-txt-muted leading-relaxed text-sm">
            Synthetic data only. The company is fictional:{' '}
            <span className="font-mono text-txt">Northwind Payments</span>, a B2B payments processor
            mid-migration. No PII. No production auth. These are deliberate scope decisions.
          </p>
        </div>

        <div className="divider" />

        {/* The four killer queries */}
        <div>
          <h2 className="text-xs font-medium text-txt-muted uppercase tracking-widest mb-4">
            The four killer queries
          </h2>
          <ul className="space-y-3">
            {KQS.map((kq, i) => (
              <li
                key={kq.id}
                className="group flex items-start gap-4 p-4 rounded border border-border hover:border-border-strong bg-surface hover:bg-s2 transition-colors duration-150"
              >
                {/* Index */}
                <span className="font-mono text-xs text-txt-faint mt-0.5 shrink-0 w-6">
                  {i + 1}.
                </span>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-txt leading-snug">{kq.question}</p>
                  <p className="text-xs text-txt-muted mt-1 leading-relaxed">{kq.note}</p>
                </div>

                {/* Try it link */}
                <Link
                  to={`/queries?kq=${kq.id}`}
                  className="flex items-center gap-1 text-xs text-accent hover:text-accent-hover transition-colors duration-150 shrink-0 mt-0.5 cursor-pointer"
                >
                  Try it
                  <ChevronRight size={12} />
                </Link>
              </li>
            ))}
          </ul>
        </div>

        {/* Navigation links */}
        <div className="flex gap-4 pt-2">
          <Link
            to="/graph"
            className="text-sm text-accent hover:text-accent-hover transition-colors cursor-pointer"
          >
            Browse the graph →
          </Link>
          <Link
            to="/audit"
            className="text-sm text-txt-muted hover:text-txt transition-colors cursor-pointer"
          >
            Resolution audit trail →
          </Link>
        </div>

        {/* Tech stack footnote */}
        <div className="divider" />
        <p className="text-xs text-txt-faint leading-relaxed font-mono">
          Stack: Neo4j 5 · Postgres 16 + pgvector · FastAPI · BAAI/bge-small-en-v1.5 ·
          claude-3.5-haiku (LLM adjudication) · React 18 + react-force-graph-2d
        </p>
      </div>
    </div>
  );
}
