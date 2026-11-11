/** The design's animated background: dot grid, the sweeping spotlight and (light theme) colour blobs.
 *  Decorative only. Animations stop for `prefers-reduced-motion` and while the tab is hidden. */
export function Backdrop() {
  return (
    <div className="backdrop" aria-hidden="true">
      <div className="blob b1" />
      <div className="blob b2" />
      <div className="blob b3" />
      <div className="blob b4" />
      <div className="blob b5" />
      <div className="dots" />
      <div className="spot" />
      <div className="spot spot2" />
    </div>
  );
}
