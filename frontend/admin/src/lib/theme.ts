import { useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

// Same key the inline script in index.html reads before first paint.
const STORAGE_KEY = 'theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light';
}

function initialTheme(): Theme {
  const current = document.documentElement.dataset.theme;
  if (current === 'light' || current === 'dark') return current;
  return storedTheme() ?? systemTheme();
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Follow OS changes until the user picks a theme explicitly.
  useEffect(() => {
    const query = window.matchMedia(DARK_QUERY);
    const onChange = () => {
      if (!storedTheme()) setTheme(systemTheme());
    };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked (private mode): the choice lasts for this page only.
    }
    setTheme(next);
  }

  return { theme, toggle };
}
