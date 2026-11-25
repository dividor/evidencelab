import React, { useEffect, useRef } from 'react';

const DOT_SIZES = [12, 12, 12, 12, 12];
const DOT_OPACITIES = [1, 0.8, 0.6, 0.4, 0.2];
const TRAIL_GAP = 10; // frames between each trailing dot
const HISTORY_SIZE = TRAIL_GAP * 4 + 1;
const ORBIT_RADIUS = 30;
const ORBIT_PERIOD_MS = 1800;
const ORBIT_COUNT = 3;
const ORBIT_DURATION_MS = ORBIT_PERIOD_MS * ORBIT_COUNT;
const WANDER_MARGIN = 40;

/** Compute edge-repulsion steering to keep the snake away from container walls */
const computeEdgeRepulsion = (
  x: number, y: number, heading: number,
  centerX: number, centerY: number, width: number, height: number,
): number => {
  const toCenterAngle = Math.atan2(centerY - y, centerX - x);
  let pull = 0;
  if (x < WANDER_MARGIN) pull = (WANDER_MARGIN - x) / WANDER_MARGIN;
  if (x > width - WANDER_MARGIN) pull = Math.max(pull, (x - width + WANDER_MARGIN) / WANDER_MARGIN);
  if (y < WANDER_MARGIN) pull = Math.max(pull, (WANDER_MARGIN - y) / WANDER_MARGIN);
  if (y > height - WANDER_MARGIN) pull = Math.max(pull, (y - height + WANDER_MARGIN) / WANDER_MARGIN);
  if (pull <= 0) return heading;
  let diff = toCenterAngle - heading;
  while (diff > Math.PI) diff -= 2 * Math.PI;
  while (diff < -Math.PI) diff += 2 * Math.PI;
  return heading + diff * pull * 0.15;
};

/** The app's loading animation: a multicoloured worm of five dots that
 *  circles, then wanders inside its container. Used wherever a page waits
 *  for data (search results, Brief Central). */
export const WanderingSpinner: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const dotsRef = useRef<(HTMLDivElement | null)[]>([]);
  const animFrameRef = useRef<number>(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const bounds = container.getBoundingClientRect();
    const centerX = bounds.width / 2;
    const centerY = bounds.height / 2;

    // Match wander speed to orbit speed so transition is seamless
    const circumference = 2 * Math.PI * ORBIT_RADIUS;
    const framesPerOrbit = ORBIT_PERIOD_MS / 16.67;
    const speed = circumference / framesPerOrbit;

    const history: Array<{ x: number; y: number }> = [];
    let headX = centerX + ORBIT_RADIUS; // start at 0° (right)
    let headY = centerY;
    let wanderAngle = 0;
    let wandering = false;

    // Pre-fill history along the circle so trailing dots appear immediately
    for (let i = 0; i < HISTORY_SIZE; i++) {
      const framesBack = HISTORY_SIZE - 1 - i;
      const pastOrbitAngle = -(framesBack / framesPerOrbit) * 2 * Math.PI;
      history.push({
        x: centerX + ORBIT_RADIUS * Math.cos(pastOrbitAngle),
        y: centerY + ORBIT_RADIUS * Math.sin(pastOrbitAngle),
      });
    }

    const startTime = performance.now();

    const step = (now: number) => {
      if (!containerRef.current) return;
      const elapsed = now - startTime;

      if (!wandering && elapsed < ORBIT_DURATION_MS) {
        const orbitAngle = (elapsed / ORBIT_PERIOD_MS) * 2 * Math.PI;
        headX = centerX + ORBIT_RADIUS * Math.cos(orbitAngle);
        headY = centerY + ORBIT_RADIUS * Math.sin(orbitAngle);
      } else {
        if (!wandering) {
          const orbitAngle = (elapsed / ORBIT_PERIOD_MS) * 2 * Math.PI;
          wanderAngle = orbitAngle + Math.PI / 2;
          wandering = true;
        }
        wanderAngle += (Math.random() - 0.5) * 0.25;
        wanderAngle = computeEdgeRepulsion(headX, headY, wanderAngle, centerX, centerY, bounds.width, bounds.height);
        headX = Math.max(10, Math.min(bounds.width - 10, headX + Math.cos(wanderAngle) * speed));
        headY = Math.max(10, Math.min(bounds.height - 10, headY + Math.sin(wanderAngle) * speed));
      }

      history.push({ x: headX, y: headY });
      if (history.length > HISTORY_SIZE) history.shift();

      // Position each dot from the history — trailing dots read older positions
      for (let i = 0; i < 5; i++) {
        const dot = dotsRef.current[i];
        if (!dot) continue;
        const histIdx = Math.max(0, history.length - 1 - i * TRAIL_GAP);
        const pos = history[histIdx];
        const size = DOT_SIZES[i];
        dot.style.left = `${pos.x - size / 2}px`;
        dot.style.top = `${pos.y - size / 2}px`;
      }

      animFrameRef.current = requestAnimationFrame(step);
    };

    animFrameRef.current = requestAnimationFrame(step);
    return () => { if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current); };
  }, []);

  return (
    <div
      className="search-loading-spinner search-loading-wandering"
      ref={containerRef}
      role="status"
      aria-label="Loading"
    >
      {DOT_SIZES.map((size, i) => (
        <div
          key={i}
          ref={(el) => { dotsRef.current[i] = el; }}
          className="search-loading-snake-dot"
          style={{ width: size, height: size, opacity: DOT_OPACITIES[i] }}
        />
      ))}
    </div>
  );
};
