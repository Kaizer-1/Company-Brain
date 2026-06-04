import type { ReactNode } from 'react';

type BadgeVariant = 'default' | 'accent' | 'success' | 'warn' | 'muted' | 'decision' | 'service' | 'system' | 'person' | 'team' | 'message';

const VARIANTS: Record<BadgeVariant, string> = {
  default:  'bg-s2 text-txt border border-border',
  accent:   'bg-accent-faint text-accent border border-accent/20',
  success:  'bg-emerald-950/50 text-emerald-400 border border-emerald-800/40',
  warn:     'bg-amber-950/50 text-amber-400 border border-amber-800/40',
  muted:    'bg-s2 text-txt-muted border border-border',
  decision: 'bg-amber-950/50 text-amber-400 border border-amber-800/40',
  service:  'bg-blue-950/50 text-blue-400 border border-blue-800/40',
  system:   'bg-zinc-800/60 text-zinc-400 border border-zinc-700/40',
  person:   'bg-emerald-950/50 text-emerald-400 border border-emerald-800/40',
  team:     'bg-violet-950/50 text-violet-400 border border-violet-800/40',
  message:  'bg-slate-800/60 text-slate-400 border border-slate-700/40',
};

interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
}

export function Badge({ variant = 'default', children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-2xs font-medium leading-none ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </span>
  );
}

export function nodeTypeBadge(nodeType: string): BadgeVariant {
  const map: Record<string, BadgeVariant> = {
    Decision: 'decision',
    Service:  'service',
    System:   'system',
    Person:   'person',
    Team:     'team',
    Message:  'message',
  };
  return map[nodeType] ?? 'default';
}
