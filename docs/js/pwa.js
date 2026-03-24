import { getSettings, saveSettings } from './storage.js';

const HOME_PROMPT_ID = 'pwa-home-card';
const STATUS_REGION_ID = 'pwa-status-region';
const IOS_HINT = 'In Safari, tap Share, then choose Add to Home Screen.';

const state = {
  canInstall: false,
  isStandalone: false,
  isOffline: !navigator.onLine,
  isIos: detectIos(),
  updateAvailable: false,
};

let registration = null;
let deferredPrompt = null;
let reloadOnControllerChange = false;

function detectIos() {
  const ua = navigator.userAgent || '';
  return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

function detectStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}

function getInstallSettings() {
  return getSettings();
}

function setInstallPromptDismissed(value) {
  const settings = getInstallSettings();
  settings.pwaInstallPromptDismissed = value;
  saveSettings(settings);
}

function shouldShowInstallPrompt() {
  const settings = getInstallSettings();
  if (settings.pwaInstallPromptDismissed || state.isStandalone) {
    return false;
  }
  return state.canInstall || state.isIos;
}

function ensureStatusRegion() {
  let region = document.getElementById(STATUS_REGION_ID);
  if (!region) {
    region = document.createElement('div');
    region.id = STATUS_REGION_ID;
    document.body.appendChild(region);
  }
  return region;
}

function renderStatusBanner() {
  const region = ensureStatusRegion();
  region.innerHTML = '';

  if (state.updateAvailable) {
    const banner = document.createElement('div');
    banner.className = 'pwa-banner pwa-banner--update';
    banner.innerHTML = `
      <p>A new version of Flash is ready.</p>
      <div class="pwa-banner__actions">
        <button class="btn btn-primary btn--sm" type="button" data-pwa-action="apply-update">Reload</button>
      </div>
    `;
    banner.querySelector('[data-pwa-action="apply-update"]')?.addEventListener('click', applyUpdate);
    region.appendChild(banner);
    return;
  }

  if (state.isOffline) {
    const banner = document.createElement('div');
    banner.className = 'pwa-banner pwa-banner--offline';
    banner.innerHTML = '<p>Offline mode: cached texts remain available.</p>';
    region.appendChild(banner);
  }
}

export function renderPwaHomePrompt(root = document.querySelector('#home .screen-inner')) {
  if (!root) return;

  const existing = document.getElementById(HOME_PROMPT_ID);
  if (existing) existing.remove();

  if (!shouldShowInstallPrompt()) return;

  const anchor = root.querySelector('.works-list');
  if (!anchor) return;

  const card = document.createElement('div');
  card.id = HOME_PROMPT_ID;
  card.className = 'card pwa-install-card';

  if (state.canInstall) {
    card.innerHTML = `
      <h3>Install Flash</h3>
      <p>Save Flash to your home screen for a full-screen app feel and reliable offline study.</p>
      <div class="pwa-install-card__actions">
        <button class="btn btn-primary" type="button" data-pwa-action="install">Install</button>
        <button class="btn btn-secondary" type="button" data-pwa-action="dismiss-install">Not now</button>
      </div>
    `;
    card.querySelector('[data-pwa-action="install"]')?.addEventListener('click', promptInstall);
  } else if (state.isIos) {
    card.innerHTML = `
      <h3>Add Flash To Home Screen</h3>
      <p>${IOS_HINT}</p>
      <div class="pwa-install-card__actions">
        <button class="btn btn-secondary" type="button" data-pwa-action="dismiss-install">Hide tip</button>
      </div>
    `;
  }

  card.querySelector('[data-pwa-action="dismiss-install"]')?.addEventListener('click', () => {
    setInstallPromptDismissed(true);
    renderPwaHomePrompt();
  });

  root.insertBefore(card, anchor);
}

function updateBodyState() {
  document.body.classList.toggle('app-standalone', state.isStandalone);
  document.body.classList.toggle('app-offline', state.isOffline);
}

function syncState(partial = {}) {
  Object.assign(state, partial);
  state.isStandalone = detectStandalone();
  updateBodyState();
  renderStatusBanner();
  renderPwaHomePrompt();
}

async function promptInstall() {
  if (!deferredPrompt) return;

  const prompt = deferredPrompt;
  deferredPrompt = null;
  syncState({ canInstall: false });
  await prompt.prompt();

  try {
    const result = await prompt.userChoice;
    if (result?.outcome === 'accepted') {
      setInstallPromptDismissed(true);
    }
  } catch (err) {
    console.warn('Install prompt failed:', err);
  }
}

async function applyUpdate() {
  if (registration?.waiting) {
    reloadOnControllerChange = true;
    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
    return;
  }

  if (registration) {
    await registration.update();
  }
}

function monitorRegistration(reg) {
  registration = reg;
  if (reg.waiting) {
    syncState({ updateAvailable: true });
  }

  reg.addEventListener('updatefound', () => {
    const worker = reg.installing;
    if (!worker) return;
    worker.addEventListener('statechange', () => {
      if (worker.state === 'installed' && navigator.serviceWorker.controller) {
        syncState({ updateAvailable: true });
      }
    });
  });
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;

  try {
    const reg = await navigator.serviceWorker.register('./sw.js');
    monitorRegistration(reg);
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (reloadOnControllerChange) {
        window.location.reload();
      }
    });
  } catch (err) {
    console.warn('Service worker registration failed:', err);
  }
}

export function initPwa() {
  syncState();

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    syncState({ canInstall: true });
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    setInstallPromptDismissed(true);
    syncState({ canInstall: false });
  });

  window.addEventListener('online', () => syncState({ isOffline: false }));
  window.addEventListener('offline', () => syncState({ isOffline: true }));

  const displayMode = window.matchMedia('(display-mode: standalone)');
  if (typeof displayMode.addEventListener === 'function') {
    displayMode.addEventListener('change', () => syncState());
  } else if (typeof displayMode.addListener === 'function') {
    displayMode.addListener(() => syncState());
  }

  registerServiceWorker();
}
