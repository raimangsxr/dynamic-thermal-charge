/** Polling stops when hidden and refreshes at once on return: FR-046. */

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_INTERVAL_SECONDS,
  MAX_INTERVAL_SECONDS,
  MIN_INTERVAL_SECONDS,
  Poller,
  clampInterval,
  type PollHost,
} from './poll';

/** A host the test drives: no real timers, no real document. */
class FakeHost implements PollHost {
  hidden = false;
  intervalMs: number | null = null;
  private handler: (() => void) | null = null;
  private listener: (() => void) | null = null;
  removed = false;

  setInterval(handler: () => void, ms: number): unknown {
    this.handler = handler;
    this.intervalMs = ms;
    return 'handle';
  }

  clearInterval(): void {
    this.handler = null;
    this.intervalMs = null;
  }

  isHidden(): boolean {
    return this.hidden;
  }

  onVisibilityChange(listener: () => void): () => void {
    this.listener = listener;
    return () => {
      this.removed = true;
    };
  }

  fireTick(): void {
    this.handler?.();
  }

  setHidden(hidden: boolean): void {
    this.hidden = hidden;
    this.listener?.();
  }

  get scheduled(): boolean {
    return this.handler !== null;
  }
}

function poller(): { host: FakeHost; ticks: number[]; poller: Poller } {
  const host = new FakeHost();
  const ticks: number[] = [];
  const instance = new Poller(() => ticks.push(ticks.length), host);
  return { host, ticks, poller: instance };
}

describe('clampInterval', () => {
  it('keeps a sensible value', () => {
    expect(clampInterval(5)).toBe(5);
  });

  it('raises a value below the floor', () => {
    expect(clampInterval(0.1)).toBe(MIN_INTERVAL_SECONDS);
  });

  it('lowers a value above the ceiling', () => {
    expect(clampInterval(9999)).toBe(MAX_INTERVAL_SECONDS);
  });

  it('falls back to the default for a nonsensical value', () => {
    expect(clampInterval(Number.NaN)).toBe(DEFAULT_INTERVAL_SECONDS);
  });
});

describe('Poller', () => {
  it('schedules at the default cadence', () => {
    const { host, poller: instance } = poller();
    instance.start();
    expect(host.intervalMs).toBe(DEFAULT_INTERVAL_SECONDS * 1000);
    expect(instance.running()).toBe(true);
  });

  it('clamps a cadence outside the allowed range', () => {
    const { host, poller: instance } = poller();
    instance.start(9999);
    expect(host.intervalMs).toBe(MAX_INTERVAL_SECONDS * 1000);
  });

  it('emits on every tick', () => {
    const { host, ticks, poller: instance } = poller();
    instance.start();
    host.fireTick();
    host.fireTick();
    expect(ticks.length).toBe(2);
  });

  it('stops while the document is hidden', () => {
    const { host, poller: instance } = poller();
    instance.start();
    host.setHidden(true);
    expect(host.scheduled).toBe(false);
    expect(instance.running()).toBe(false);
  });

  it('refreshes immediately on returning to the foreground, not on the next tick', () => {
    const { host, ticks, poller: instance } = poller();
    instance.start();
    host.setHidden(true);
    const before = ticks.length;
    host.setHidden(false);
    expect(ticks.length).toBe(before + 1);
    expect(host.scheduled).toBe(true);
  });

  it('does not start scheduling if it begins hidden', () => {
    const { host, poller: instance } = poller();
    host.hidden = true;
    instance.start();
    expect(host.scheduled).toBe(false);
  });

  it('releases the visibility listener when stopped', () => {
    const { host, poller: instance } = poller();
    instance.start();
    instance.stop();
    expect(host.scheduled).toBe(false);
    expect(host.removed).toBe(true);
  });

  it('does not schedule twice when already running', () => {
    const { host, poller: instance } = poller();
    instance.start();
    host.setHidden(false); // a spurious visibility event while visible
    expect(host.intervalMs).toBe(DEFAULT_INTERVAL_SECONDS * 1000);
  });
});
