/* theme.js — Light/dark mode, no framework. Must load before app.js. */
(function () {
  'use strict';

  const KEY = 'meesho-theme';
  const root = document.documentElement;

  function getPreferred() {
    const saved = localStorage.getItem(KEY);
    if (saved === 'dark' || saved === 'light') return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    root.setAttribute('data-theme', theme);
    localStorage.setItem(KEY, theme);
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      btn.setAttribute('title', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      const icon = btn.querySelector('.theme-icon');
      if (icon) icon.textContent = theme === 'dark' ? '☀' : '☾';
    }
    /* Notify app.js charts if it has registered a listener */
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
  }

  function toggle() {
    applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  }

  /* Apply immediately to prevent flash */
  applyTheme(getPreferred());

  window.__themeToggle = toggle;
  window.__getTheme = () => root.getAttribute('data-theme');

  document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.addEventListener('click', toggle);
    /* Re-apply to sync icon after DOM is ready */
    applyTheme(root.getAttribute('data-theme') || getPreferred());
  });
})();
