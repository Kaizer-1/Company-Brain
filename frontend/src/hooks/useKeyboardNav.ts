import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

/**
 * Implements "g h/g/q/a" chord keyboard shortcuts (Linear-style nav).
 * The first key press starts a 1s window for the second key.
 * Skipped when focus is in an input, textarea, or select.
 */
export function useKeyboardNav() {
  const navigate = useNavigate();
  const pending = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const key = e.key.toLowerCase();

      if (pending.current === 'g') {
        if (timer.current) clearTimeout(timer.current);
        pending.current = null;
        switch (key) {
          case 'h': navigate('/'); break;
          case 'g': navigate('/graph'); break;
          case 'q': navigate('/queries'); break;
          case 'a': navigate('/audit'); break;
        }
        return;
      }

      if (key === 'g') {
        pending.current = 'g';
        timer.current = setTimeout(() => { pending.current = null; }, 1000);
      }
    }

    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [navigate]);
}
