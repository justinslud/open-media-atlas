// Pessimistic state: never display success before the server confirms it.
document.addEventListener('click', event => {
  if (event.target.closest('[data-library-control]')) event.stopPropagation();
});
document.addEventListener('submit', async event => {
  const form = event.target;
  if (!form.matches('[data-library-control]')) return;
  event.preventDefault();
  event.stopPropagation();
  const button = form.querySelector('button');
  if (button.disabled) return;
  const error = form.querySelector('[role="alert"]');
  button.disabled = true;
  error.textContent = '';
  try {
    const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {'Accept': 'application/json'}});
    if (response.redirected) { window.location.assign(response.url); return; }
    if (!response.ok) throw new Error('request failed');
    const {active} = await response.json();
    // Synchronize every control for this same action/object on the page.
    document.querySelectorAll('[data-library-control]').forEach(other => {
      if (other.action !== form.action) return;
      const control = other.querySelector('button');
      other.elements.active.value = active ? '0' : '1';
      control.setAttribute('aria-pressed', String(active));
      control.textContent = active ? control.dataset.activeLabel : control.dataset.label;
      control.setAttribute('aria-label', active ? (control.dataset.action === 'save' ? `Remove ${control.dataset.object} from saved works` : `Unfollow ${control.dataset.object}`) : `${control.dataset.label} ${control.dataset.object}`);
    });
  } catch (_) {
    error.textContent = 'Could not update your library. Please try again.';
  } finally { button.disabled = false; }
});
