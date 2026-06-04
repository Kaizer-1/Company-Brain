import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { useEffect } from 'react';
import { fetchEvent } from '../../api/events';
import { queryKeys } from '../../api/client';
import { Skeleton } from '../ui/Skeleton';
import { ErrorMessage } from '../ui/ErrorMessage';

interface EventModalProps {
  eventId: string;
  onClose: () => void;
}

export function EventModal({ eventId, onClose }: EventModalProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.event(eventId),
    queryFn: () => fetchEvent(eventId),
    staleTime: Infinity, // events are immutable
  });

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Source event"
        className="relative w-full max-w-2xl bg-surface border border-border rounded-lg shadow-2xl mx-4 max-h-[80vh] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <span className="text-sm font-medium text-txt">Source event</span>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-txt-muted hover:text-txt cursor-pointer rounded p-0.5 hover:bg-s2 transition-colors duration-150"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {isLoading && <Skeleton className="h-32 w-full" />}
          {error && <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />}
          {data && (
            <>
              {/* Metadata */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                <div>
                  <span className="text-txt-muted">ID</span>
                  <p className="font-mono text-txt truncate">{data.id}</p>
                </div>
                <div>
                  <span className="text-txt-muted">Type</span>
                  <p className="font-mono text-txt">{data.source_type}</p>
                </div>
                <div>
                  <span className="text-txt-muted">Created</span>
                  <p className="font-mono text-txt">
                    {new Date(data.created_at).toLocaleString()}
                  </p>
                </div>
                <div>
                  <span className="text-txt-muted">External ID</span>
                  <p className="font-mono text-txt truncate">{data.source_external_id}</p>
                </div>
              </div>

              <div className="divider" />

              {/* Raw content */}
              <div>
                <span className="text-xs text-txt-muted block mb-1.5">Content</span>
                <pre className="font-mono text-xs text-txt bg-bg border border-border rounded p-3 whitespace-pre-wrap leading-relaxed overflow-y-auto max-h-64">
                  {data.content}
                </pre>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
