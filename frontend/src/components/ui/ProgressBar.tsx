/**
 * Thin loading indicator at the top of the page — NOT a spinner.
 * Follows the Linear/GitHub approach: a 2px bar with an animated shimmer.
 */
export function ProgressBar({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div
      role="progressbar"
      aria-label="Loading"
      className="progress-bar"
    />
  );
}
