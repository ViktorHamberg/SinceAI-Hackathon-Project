import { useEffect, useRef, useState } from 'react';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import './OriginSelector.css';

export function nearestOriginIndex(origins: string[], time: number): number {
  let nearest = 0;
  for (let index = 1; index < origins.length; index++) {
    if (Math.abs(Date.parse(origins[index]) - time) < Math.abs(Date.parse(origins[nearest]) - time)) nearest = index;
  }
  return nearest;
}

interface Props {
  origins: string[];
  selectedOrigin: string;
  displayedOrigin: string | null;
  loading: boolean;
  zone: DisplayZone;
  onSelect: (origin: string) => void;
}

export default function OriginSelector({ origins, selectedOrigin, displayedOrigin, loading, zone, onSelect }: Props) {
  const selected = origins.indexOf(selectedOrigin);
  const [draft, setDraft] = useState(selected);
  const [dragging, setDragging] = useState(false);
  const pointer = useRef<number | null>(null);
  const cancelled = useRef(false);
  const draftIndex = useRef(selected);
  const first = Date.parse(origins[0]);
  const last = Date.parse(origins[origins.length - 1]);
  const shown = dragging ? draft : selected;
  const position = (origin: string) => last === first ? 0 : (Date.parse(origin) - first) / (last - first) * 1000;

  useEffect(() => {
    draftIndex.current = selected;
    setDraft(selected);
    pointer.current = null;
    setDragging(false);
  }, [selected]);

  function preview(index: number) {
    draftIndex.current = index;
    setDraft(index);
  }
  function choose(index: number) {
    cancelled.current = false;
    preview(index);
    pointer.current = null;
    setDragging(false);
    if (origins[index] !== selectedOrigin) onSelect(origins[index]);
  }
  function cancelDrag() {
    cancelled.current = true;
    pointer.current = null;
    setDragging(false);
    preview(selected);
  }

  return <section className="origin-selector" aria-labelledby="origin-heading">
    <div className="origin-heading">
      <div><h2 id="origin-heading">Forecast issue time</h2><p>{origins.length} cached {origins.length === 1 ? 'forecast' : 'forecasts'} · Historical replay</p></div>
      <div className="origin-navigation" role="group" aria-label="Forecast navigation">
        <button type="button" disabled={selected === 0} onClick={() => choose(selected - 1)}>Previous forecast</button>
        <button type="button" disabled={selected === origins.length - 1} onClick={() => choose(selected + 1)}>Next forecast</button>
      </div>
    </div>
    <div className="origin-controls">
      <div className="origin-precise">
        <label htmlFor="origin-choice">Choose exact issue time</label>
        <select id="origin-choice" value={selectedOrigin} onChange={(event) => choose(origins.indexOf(event.target.value))}>
          {origins.map((origin) => <option key={origin} value={origin}>{formatTimestamp(origin, zone)}</option>)}
        </select>
      </div>
      <div className="origin-readout" aria-live="polite" aria-atomic="true">
        <span>{dragging ? 'Preview · release to load' : 'Selected issue time'}</span>
        <output htmlFor="origin-timeline">{formatTimestamp(origins[shown], zone)}</output>
      </div>
    </div>
    <div className="origin-rail">
      <svg className="origin-track" viewBox="0 0 1000 48" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" x2="1000" y1="24" y2="24" className="origin-track-base" />
        <line x1="0" x2={position(origins[shown])} y1="24" y2="24" className="origin-track-selected" />
        {origins.map((origin) => <line key={origin} data-origin={origin} x1={position(origin)} x2={position(origin)} y1="16" y2="32" className="origin-marker" />)}
      </svg>
      <input id="origin-timeline" className="origin-timeline" type="range" min={first} max={Math.max(first + 1, last)} step={3_600_000}
        value={Date.parse(origins[shown])} disabled={origins.length === 1}
        aria-label="Historical forecast timeline" aria-describedby="origin-help" aria-valuetext={`${formatTimestamp(origins[shown], zone)}, forecast ${shown + 1} of ${origins.length}`}
        onPointerDown={(event) => {
          if (!event.isPrimary || event.button !== 0) return;
          pointer.current = event.pointerId;
          cancelled.current = false;
          setDragging(true);
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }}
        onChange={(event) => {
          if (cancelled.current) return;
          const index = nearestOriginIndex(origins, Number(event.target.value));
          if (pointer.current !== null) preview(index);
          else choose(index);
        }}
        onPointerUp={(event) => { if (pointer.current === event.pointerId) choose(draftIndex.current); }}
        onPointerCancel={cancelDrag}
        onLostPointerCapture={() => { if (pointer.current !== null) cancelDrag(); }}
        onKeyDown={(event) => {
          const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'];
          if (event.key === 'Escape') { event.preventDefault(); cancelDrag(); return; }
          if (!keys.includes(event.key)) return;
          event.preventDefault();
          if (event.key === 'Home') choose(0);
          else if (event.key === 'End') choose(origins.length - 1);
          else choose(Math.max(0, Math.min(origins.length - 1, draftIndex.current + (['ArrowRight', 'ArrowUp', 'PageUp'].includes(event.key) ? 1 : -1))));
        }} />
    </div>
    <div className="origin-endpoints" aria-hidden="true"><span>{formatTimestamp(origins[0], zone)}</span>{origins.length > 1 && <span>{formatTimestamp(origins[origins.length - 1], zone)}</span>}</div>
    <p className="origin-help" id="origin-help">Drag to preview; release to load. Marks show available forecasts at their actual times; gaps have no cached forecasts. Use arrow keys or the exact-time list for nearby marks.</p>
    <p className="origin-displayed">{displayedOrigin ? <>Displayed forecast: <time dateTime={displayedOrigin}>{formatTimestamp(displayedOrigin, zone)}</time></> : loading ? 'No forecast displayed while loading.' : 'No forecast displayed.'}</p>
  </section>;
}
