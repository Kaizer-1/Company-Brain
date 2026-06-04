import { ApiError } from '../../api/client';

interface ErrorMessageProps {
  error: Error | null;
  className?: string;
}

export function ErrorMessage({ error, className = '' }: ErrorMessageProps) {
  if (!error) return null;

  const detail =
    error instanceof ApiError
      ? `${error.status}: ${error.detail}`
      : error.message;

  return (
    <div
      role="alert"
      className={`font-mono text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2 ${className}`}
    >
      {detail}
    </div>
  );
}
