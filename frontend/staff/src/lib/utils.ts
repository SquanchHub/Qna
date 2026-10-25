import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Renders an API timestamp (UTC ISO 8601) in the viewer's locale. */
export function formatTimestamp(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—';
}
