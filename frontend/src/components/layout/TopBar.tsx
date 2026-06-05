import { NavLink } from 'react-router-dom';

const NAV = [
  { to: '/', label: 'overview', end: true },
  { to: '/graph', label: 'graph', end: false },
  { to: '/queries', label: 'queries', end: false },
  { to: '/search', label: 'search', end: false },
  { to: '/audit', label: 'audit', end: false },
] as const;

export function TopBar() {
  return (
    <header className="h-topbar border-b border-border flex items-center px-5 gap-8 shrink-0 bg-bg">
      {/* Project name — monospace, small, left-anchored */}
      <span className="font-mono text-xs text-txt-muted select-none tracking-tight">
        company-brain
      </span>

      {/* Nav links — text-only, active route gets accent color */}
      <nav className="flex items-center gap-1 flex-1">
        {NAV.map(({ to, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              [
                'px-3 py-1 rounded text-sm transition-colors duration-150 cursor-pointer',
                isActive
                  ? 'text-txt bg-s2'
                  : 'text-txt-muted hover:text-txt hover:bg-s2',
              ].join(' ')
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Keyboard shortcut hint */}
      <span className="font-mono text-2xs text-txt-faint select-none hidden sm:block">
        g h/g/q/s/a
      </span>
    </header>
  );
}
