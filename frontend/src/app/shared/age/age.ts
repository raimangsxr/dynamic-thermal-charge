/**
 * Formatting an age, from the numbers the API gives.
 *
 * Deliberately takes `ageSeconds` as an argument instead of computing
 * `Date.now() - lastSeenAt`. The device that shows the panel -- a phone, a
 * laptop -- and the Raspberry Pi can disagree on the time, and the Pi has no
 * battery-backed clock, so a fresh boot before time sync is a real scenario.
 *
 * Computing the age locally would show negative ages, or ages of hours, in
 * exactly the indicator the operator relies on to decide whether to trust the
 * screen. The API already computed it against the same clock that wrote the
 * heartbeat, which makes that the only coherent figure.
 *
 * A guard test fails if any other module reaches for the local clock.
 */

/** Human-readable age. `null` means "there is nothing to age". */
export function formatAge(ageSeconds: number | null): string {
  if (ageSeconds === null) {
    return '—';
  }
  // A negative age means the API saw a heartbeat dated ahead of its own clock.
  // It already resolved that to "not current"; here it is only worth not
  // printing something absurd like "hace -3 s".
  if (ageSeconds < 0) {
    return 'instante futuro';
  }
  const seconds = Math.round(ageSeconds);
  if (seconds < 60) {
    return `hace ${seconds} s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `hace ${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `hace ${hours} h`;
  }
  const days = Math.floor(hours / 24);
  return `hace ${days} d`;
}

/** An absolute instant, for when the operator needs the actual time. */
export function formatInstant(iso: string | null): string {
  if (iso === null) {
    return '—';
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return parsed.toLocaleString();
}
