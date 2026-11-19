(() => {
  const fixture = JSON.parse(document.getElementById('preview-fixture').textContent);
  try {
    localStorage.setItem('cubos-workspace:' + fixture.configDir, JSON.stringify({
      activeTab: 'Gantry',
      gantryFile: fixture.gantry,
      deckFile: fixture.deck,
      protocolFile: fixture.protocol,
    }));
  } catch {
    // The viewer still loads if the browser blocks workspace storage.
  }

  const params = new URLSearchParams(location.search);
  const observe = new MutationObserver(() => {
    const header = document.querySelector('.operator-header');
    if (!header) return;
    if (!header.querySelector('.preview-setup')) {
      const label = document.createElement('label');
      label.className = 'preview-setup';
      label.textContent = 'Preview setup';
      const select = document.createElement('select');
      for (const [value, title] of Object.entries(fixture.setups)) {
        select.add(new Option(title, value, false, value === fixture.active));
      }
      select.addEventListener('change', () => {
        params.set('setup', select.value);
        location.search = params.toString();
      });
      label.append(select);
      header.append(label);
    }

    if (params.get('workspace') !== 'workflow'
        && !document.querySelector('.operator-workspace--visualize')) {
      const visualize = [...header.querySelectorAll('button')]
        .find(button => button.textContent.trim() === 'Visualize');
      visualize?.click();
      return;
    }
    const view = params.get('view') === '2d' ? '2D' : '3D';
    const toggle = [...document.querySelectorAll('[aria-label="Deck view"] button')]
      .find(button => button.textContent.trim() === view);
    if (toggle) {
      observe.disconnect();
      toggle.click();
    }
  });
  observe.observe(document.documentElement, { subtree: true, childList: true });
})();
