/**
 * Periodic polling that stops when nobody is looking.
 *
 * A forgotten tab querying every few seconds for days is free load on a
 * Cortex-A7 that is also running the control loop, so the polling stops while
 * the document is hidden. Coming back to a tab and seeing hours-old data with no
 * warning would be worse than not refreshing, so returning to the foreground
 * refreshes IMMEDIATELY rather than waiting for the next tick.
 */

import { Injectable, signal } from '@angular/core';

/** 5 s matches the controller's own poll_seconds: no point asking more often. */
export const DEFAULT_INTERVAL_SECONDS = 5;
/** A panel querying every 200 ms would be noticeable load on the device. */
export const MIN_INTERVAL_SECONDS = 2;
export const MAX_INTERVAL_SECONDS = 60;

export function clampInterval(seconds: number): number {
  if (!Number.isFinite(seconds)) {
    return DEFAULT_INTERVAL_SECONDS;
  }
  return Math.min(MAX_INTERVAL_SECONDS, Math.max(MIN_INTERVAL_SECONDS, seconds));
}

export interface PollHost {
  setInterval(handler: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
  isHidden(): boolean;
  onVisibilityChange(listener: () => void): () => void;
}

/** The real browser. Injected so tests never depend on a real timer. */
export function browserPollHost(): PollHost {
  return {
    setInterval: (handler, ms) => globalThis.setInterval(handler, ms),
    clearInterval: (handle) => globalThis.clearInterval(handle as number),
    isHidden: () => globalThis.document?.visibilityState === 'hidden',
    onVisibilityChange: (listener) => {
      globalThis.document?.addEventListener('visibilitychange', listener);
      return () =>
        globalThis.document?.removeEventListener('visibilitychange', listener);
    },
  };
}

export class Poller {
  private handle: unknown = null;
  private stopListening: (() => void) | null = null;
  private intervalSeconds = DEFAULT_INTERVAL_SECONDS;
  readonly running = signal(false);

  constructor(
    private readonly tick: () => void,
    private readonly host: PollHost = browserPollHost(),
  ) {}

  start(intervalSeconds: number = DEFAULT_INTERVAL_SECONDS): void {
    this.intervalSeconds = clampInterval(intervalSeconds);
    this.stopListening = this.host.onVisibilityChange(() => this.onVisibility());
    if (!this.host.isHidden()) {
      this.resume();
    }
  }

  stop(): void {
    this.pause();
    this.stopListening?.();
    this.stopListening = null;
  }

  private onVisibility(): void {
    if (this.host.isHidden()) {
      this.pause();
      return;
    }
    // Immediately, not on the next tick: returning to a tab must not show
    // hours-old data as if it were fresh.
    this.tick();
    this.resume();
  }

  private resume(): void {
    if (this.handle !== null) {
      return;
    }
    this.handle = this.host.setInterval(
      () => this.tick(),
      this.intervalSeconds * 1000,
    );
    this.running.set(true);
  }

  private pause(): void {
    if (this.handle === null) {
      return;
    }
    this.host.clearInterval(this.handle);
    this.handle = null;
    this.running.set(false);
  }
}
