// App bootstrap, routing, orchestration

import { fetchWorks } from './data.js';
import { renderHome, showScreen, selectWork } from './ui.js';
import { getSettings } from './storage.js';

async function init() {
  try {
    const works = await fetchWorks();

    // Seed initial history state
    history.replaceState({ screen: 'home' }, '', '#home');

    renderHome(works);

    // Handle browser back/forward
    window.addEventListener('popstate', (event) => {
      const screen = event.state?.screen || window.location.hash.replace('#', '') || 'home';
      handleRoute(works, screen);
    });

    // Arrow key navigation (non-quiz screens only)
    document.addEventListener('keydown', (e) => {
      const activeScreen = document.querySelector('.screen.active')?.id;
      if (activeScreen === 'quiz') return;
      if (document.activeElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
      if (e.key === 'ArrowLeft') history.back();
      if (e.key === 'ArrowRight') history.forward();
    });

    // Restore last work if returning
    const settings = getSettings();
    if (settings.lastWorkId && window.location.hash === '#home') {
      // Stay on home, user can select
    }
  } catch (err) {
    console.error('Failed to initialize app:', err);
    document.getElementById('app').innerHTML = `
      <div class="card" style="text-align:center; margin-top: 2rem;">
        <h2>Failed to Load</h2>
        <p>Could not load vocabulary data. Make sure the data files exist in <code>docs/data/</code>.</p>
        <p style="color: #666; font-size: 0.875rem;">${err.message}</p>
      </div>
    `;
  }
}

function handleRoute(works, screen) {
  switch (screen) {
    case 'home':
      renderHome(works);
      break;
    case 'level-select':
    case 'quiz':
    case 'results':
    case 'progress':
      // These screens require vocab to be loaded; if not, redirect home
      if (!document.querySelector(`#${screen}.active`)) {
        renderHome(works);
      }
      break;
    default:
      renderHome(works);
  }
}

// Boot
init();
