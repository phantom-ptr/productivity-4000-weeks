// Four Thousand Weeks: the page. Plain JavaScript, no framework, no network
// beyond this machine. Every write is followed by a fresh GET /api/state.
// User text only ever enters the page as text nodes.
'use strict';

const VIEWS = ['focus', 'open', 'neglect', 'weeks', 'review', 'report', 'settings', 'why'];
const BUCKETS = ['focus', 'closed', 'open'];
const UP = { open: 'closed', closed: 'focus' };
const DOWN = { focus: 'closed', closed: 'open' };
const LABEL = { focus: 'Focus', closed: 'Closed', open: 'Open', neglect: 'Neglect', done: 'Done', let_go: 'Let go' };
const KIND = { focus: 'card', closed: 'ticket', open: 'row' };
const WEEKS_TOTAL = 4000;
const WEEKS_PER_ROW = 52;
const SEGMENTS = 200;
const WEEKS_PER_SEGMENT = WEEKS_TOTAL / SEGMENTS;
const FADE_MS = 180;
const TOAST_MS = 6000;
const THEMES = ['system', 'light', 'dark'];
const THEME_ICON = { system: 'auto', light: 'sun', dark: 'moon' };

let current = null;        // the last GET /api/state
let theme = 'system';
let messageTimer = null;
let toastTimer = null;
let placeholder = null;
let dragId = null;
let popoverAnchor = null;
let staleOnClose = false;   // a conflict picker is open; closing it re-renders

// ------------------------------------------------------------------ helpers

function $(id) {
  return document.getElementById(id);
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== 'string') node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(name) {
  const svg = $('icon-template').content.firstElementChild.cloneNode(true);
  svg.querySelector('use').setAttribute('href', '#icon-' + name);
  return svg;
}

function iconButton(name, label, onClick) {
  return el('button', { type: 'button', class: 'icon-button ' + name, 'aria-label': label, title: label, onclick: onClick },
    icon(name));
}

function capital(word) {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function number(n) {
  return n.toLocaleString('en-US');
}

function isTyping(target) {
  return target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) &&
    target.type !== 'checkbox' && target.type !== 'radio';
}

function prefersLessMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function showMessage(text) {
  const box = $('message');
  box.textContent = text;
  box.hidden = false;
  clearTimeout(messageTimer);
  messageTimer = setTimeout(() => { box.hidden = true; }, 5000);
}

async function api(method, path, body) {
  const options = { method: method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'Something went wrong.');
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

// Run one write, show the server's sentence if it refuses, then re-render.
async function write(method, path, body) {
  let ok = true;
  try {
    await api(method, path, body);
  } catch (error) {
    ok = false;
    showMessage(error.message);
  }
  await refresh();
  return ok;
}

function findTask(id) {
  if (!current) return null;
  for (const state of Object.keys(current.lists)) {
    const task = current.lists[state].find((t) => t.id === id);
    if (task) return task;
  }
  return current.today_done.find((t) => t.id === id) || null;
}

function isFull(bucket) {
  return Boolean(current) && current.lists[bucket].length >= current.caps[bucket];
}

function focusInOrder() {
  return current.lists.focus.slice().sort((a, b) => Number(b.is_first) - Number(a.is_first));
}

// ------------------------------------------------------------------ theme

function readTheme() {
  try {
    const value = window.localStorage.getItem('theme');
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch (error) {
    return 'system';
  }
}

function applyTheme() {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
  const button = $('theme-toggle');
  if (!button) return;
  button.replaceChildren(icon(THEME_ICON[theme]));
  button.dataset.theme = theme;
  button.setAttribute('aria-label', 'Theme: ' + theme + '. Change theme');
  button.title = 'Theme: ' + theme;
}

function cycleTheme() {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  try {
    if (theme === 'system') window.localStorage.removeItem('theme');
    else window.localStorage.setItem('theme', theme);
  } catch (error) {
    // storage blocked: the choice lasts for this page only
  }
  applyTheme();
}

// ------------------------------------------------------------------ toast

function showToast(text) {
  const toast = $('toast');
  toast.textContent = text;
  toast.hidden = false;
  toast.classList.remove('is-visible');
  void toast.offsetWidth; // restart the enter transition
  toast.classList.add('is-visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove('is-visible');
    toastTimer = setTimeout(() => { toast.hidden = true; }, prefersLessMotion() ? 0 : 250);
  }, TOAST_MS);
}

// "Fence moved to Focus · Call Dad moved to Closed · Sourdough moved to Open."
function toastCascade(task, cascade, verb) {
  if (!cascade || !cascade.length) return;
  const parts = [task.title + ' ' + verb + ' ' + LABEL[task.state]]
    .concat(cascade.map((c) => c.title + ' moved to ' + LABEL[c.to]));
  showToast(parts.join(' · ') + '.');
}

// ------------------------------------------------------------------ moves

// One move through the server. A 409 that asks a question opens the matching
// picker, pre-filled for this move, and the answer retries it.
async function requestMove(task, to, extra, anchor) {
  closePopovers(true);
  try {
    const data = await api('POST', '/api/tasks/' + task.id + '/move', Object.assign({ to: to }, extra));
    toastCascade(data.task, data.cascade, 'moved to');
  } catch (error) {
    if (error.status === 409 && error.data && error.data.needs && anchor && anchor.isConnected) {
      openConflictPicker(anchor, task, to, extra, error.data);
      return;
    }
    showMessage(error.message);
  }
  await refresh();
}

function markDone(li, task) {
  li.classList.add('leaving');
  setTimeout(() => requestMove(task, 'done', {}, null), prefersLessMotion() ? 0 : FADE_MS);
}

function letGo(task, prompt) {
  const reason = window.prompt(prompt || 'Let it go. A reason, if you like:', '');
  if (reason === null) return;
  requestMove(task, 'let_go', { reason: reason }, null);
}

function setAside(task) {
  const reason = window.prompt('Set it aside on purpose. One line on why:', '');
  if (reason === null) return;
  requestMove(task, 'neglect', { reason: reason }, null);
}

function renew(task) {
  return write('POST', '/api/tasks/' + task.id + '/renew', {});
}

function idsInList(state) {
  return Array.from($('list-' + state).querySelectorAll('li.row')).map((li) => Number(li.dataset.id));
}

function reorder(state, ids) {
  return write('POST', '/api/tasks/reorder', { state: state, ids: ids });
}

function moveWithinList(task, step) {
  const ids = idsInList(task.state);
  const from = ids.indexOf(task.id);
  const to = from + step;
  if (from < 0 || to < 0 || to >= ids.length) return;
  ids.splice(from, 1);
  ids.splice(to, 0, task.id);
  reorder(task.state, ids);
}

// ------------------------------------------------------------------ popovers

// `quiet` skips the re-render a cancelled conflict picker needs (the caller renders anyway).
function closePopovers(quiet) {
  const rerender = staleOnClose && !quiet;
  staleOnClose = false;
  for (const id of ['bucket-popover', 'more-menu']) {
    const box = $(id);
    box.hidden = true;
    box.classList.remove('is-open');
    box.replaceChildren();
  }
  if (popoverAnchor) {
    popoverAnchor.setAttribute('aria-expanded', 'false');
    popoverAnchor.classList.remove('is-active');
  }
  popoverAnchor = null;
  if (rerender) refresh(); // e.g. put back a ledger tick whose undo was cancelled
}

// Place a floating box under (or above) its anchor, inside the viewport.
function showNear(box, anchor) {
  box.hidden = false;
  box.classList.add('is-open');
  popoverAnchor = anchor;
  anchor.setAttribute('aria-expanded', 'true');
  anchor.classList.add('is-active');
  const rect = anchor.getBoundingClientRect();
  const width = box.offsetWidth;
  const height = box.offsetHeight;
  const viewWidth = document.documentElement.clientWidth;
  const left = Math.max(8, Math.min(rect.right - width, viewWidth - width - 8));
  let top = rect.bottom + 6;
  if (top + height > window.innerHeight - 8 && rect.top - height - 6 > 8) top = rect.top - height - 6;
  // CSSOM writes are allowed by the CSP; inline style attributes are not.
  box.style.left = (left + window.scrollX) + 'px';
  box.style.top = (top + window.scrollY) + 'px';
  const first = box.querySelector('input:checked, button:not([disabled]), input');
  if (first) first.focus();
}

function popoverButtons(onCancel, confirmLabel) {
  return el('div', { class: 'popover-actions' },
    el('button', { type: 'button', class: 'cancel', onclick: onCancel }, 'Cancel'),
    el('button', { type: 'submit', class: 'confirm' }, confirmLabel || 'Confirm'));
}

// The bucket chooser: Focus / Closed / Open, current one marked.
function openBucketPopover(anchor, task) {
  if (popoverAnchor === anchor) { closePopovers(); return; }
  closePopovers();
  const box = $('bucket-popover');
  const openNeedsPosition = isFull('open') && task.state !== 'open';
  const positionInput = el('input', { type: 'number', id: 'popover-position', min: '1',
    max: String(current.caps.open), step: '1', value: '1' });
  const options = BUCKETS.map((bucket) => {
    const here = task.state === bucket;
    const count = current.lists[bucket].length + '/' + current.caps[bucket];
    return el('button', {
      type: 'button',
      class: 'bucket-option' + (here ? ' is-current' : '') + (isFull(bucket) && !here ? ' is-full' : ''),
      'data-bucket': bucket,
      'aria-current': here ? 'true' : null,
      onclick: () => chooseBucket(anchor, task, bucket, openNeedsPosition ? positionInput : null),
    }, el('span', { class: 'bucket-name' }, LABEL[bucket]), ' ', el('span', { class: 'bucket-count' }, count));
  });
  box.setAttribute('aria-label', 'Choose a list for ' + task.title);
  box.append(el('p', { class: 'popover-title' }, task.state === 'neglect' ? 'Revive to' : 'Move to'),
    el('div', { class: 'bucket-options' }, ...options));
  if (openNeedsPosition) {
    box.append(el('div', { class: 'position-field' },
      el('label', { for: 'popover-position' }, 'Position in Open, if you pick Open'), positionInput,
      el('p', { class: 'note' }, 'Open is full. The last item in Open moves to the Neglect page.')));
  }
  showNear(box, anchor);
}

function chooseBucket(anchor, task, bucket, positionInput) {
  if (task.state === bucket) { closePopovers(); return; }
  if (bucket === 'focus' && isFull('focus')) {
    const candidates = focusInOrder().map((t) => ({ id: t.id, title: t.title }));
    showBumpPicker(anchor, task, 'focus', {}, candidates);
    return;
  }
  if (bucket === 'open' && positionInput) {
    const n = Number(positionInput.value);
    if (!Number.isInteger(n) || n < 1 || n > current.caps.open) {
      positionInput.focus();
      return;
    }
    requestMove(task, 'open', { position: n - 1 }, anchor);
    return;
  }
  requestMove(task, bucket, {}, anchor);
}

function openConflictPicker(anchor, task, to, extra, conflict) {
  if (conflict.needs === 'bump') showBumpPicker(anchor, task, to, extra, conflict.candidates || []);
  else if (conflict.needs === 'position') showPositionPicker(anchor, task, to, extra, conflict.cap);
  else { showMessage(conflict.error || 'That list is full.'); refresh(); return; }
  staleOnClose = true;
}

function bumpRadios(candidates, name) {
  return candidates.map((c, i) => el('label', { class: 'bump-option' },
    el('input', { type: 'radio', name: name, value: String(c.id), checked: i === candidates.length - 1 }),
    el('span', { class: 'bump-title' }, c.title)));
}

// "Focus is full. Which one steps aside?"
function showBumpPicker(anchor, task, to, extra, candidates) {
  closePopovers();
  const box = $('bucket-popover');
  const form = el('form', { class: 'bump-picker' },
    el('fieldset', {},
      el('legend', {}, 'Focus is full. Which one steps aside?'),
      el('div', { class: 'bump-options' }, ...bumpRadios(candidates, 'popover-bump'))),
    el('p', { class: 'note' }, 'It moves to the top of Closed; if Closed is full, its last item moves to the top of Open.'),
    popoverButtons(() => closePopovers(), 'Confirm'));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const picked = form.querySelector('input[name="popover-bump"]:checked');
    if (!picked) return;
    requestMove(task, to, Object.assign({}, extra, { bump_id: Number(picked.value) }), anchor);
  });
  box.setAttribute('aria-label', 'Focus is full');
  box.append(form);
  showNear(box, anchor);
}

// "Open is full. Which position?"
function showPositionPicker(anchor, task, to, extra, cap) {
  closePopovers();
  const box = $('bucket-popover');
  const start = Math.min(cap, (extra.position || 0) + 1);
  const input = el('input', { type: 'number', id: 'popover-position', min: '1', max: String(cap), step: '1',
    value: String(start) });
  const form = el('form', { class: 'position-picker' },
    el('label', { for: 'popover-position' }, 'Open is full. Which position, 1 to ' + cap + '?'), input,
    el('p', { class: 'note' }, 'The last item in Open moves to the Neglect page.'),
    popoverButtons(() => closePopovers(), 'Move'));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const n = Number(input.value);
    if (!Number.isInteger(n) || n < 1 || n > cap) { input.focus(); return; }
    requestMove(task, to, Object.assign({}, extra, { position: n - 1 }), anchor);
  });
  box.setAttribute('aria-label', 'Open is full');
  box.append(form);
  showNear(box, anchor);
}

// The ⋯ menu.
function openMoreMenu(anchor, task, li) {
  if (popoverAnchor === anchor) { closePopovers(); return; }
  closePopovers();
  const box = $('more-menu');
  const items = [];
  const add = (label, handler) => items.push(el('button', { type: 'button', role: 'menuitem', class: 'menu-item',
    onclick: () => { closePopovers(); handler(); } }, label));
  add('Edit', () => startEditing(li, task));
  if (task.state === 'focus') {
    if (task.is_first) add('Not first', () => write('PATCH', '/api/tasks/' + task.id, { is_first: false }));
    else add('Mark first', () => write('PATCH', '/api/tasks/' + task.id, { is_first: true }));
  }
  add('Move up', () => moveWithinList(task, -1));
  add('Move down', () => moveWithinList(task, 1));
  if (task.state === 'open') add('Renew', () => renew(task));
  add('Let go', () => letGo(task));
  add('Set aside', () => setAside(task));
  box.setAttribute('aria-label', 'More actions for ' + task.title);
  box.append(...items);
  showNear(box, anchor);
}

function onPopoverKey(event) {
  if (event.key === 'Escape' && popoverAnchor) {
    event.preventDefault();
    const anchor = popoverAnchor;
    closePopovers();
    if (anchor.isConnected) anchor.focus();
  }
}

function onOutsidePointer(event) {
  if (!popoverAnchor) return;
  if (event.target.closest('#bucket-popover, #more-menu')) return;
  if (popoverAnchor.contains(event.target)) return;
  closePopovers();
}

// ------------------------------------------------------------------ rendering

function tickBox(checked, labelId, onChange) {
  const input = el('input', { type: 'checkbox', class: 'tick', checked: checked, 'aria-labelledby': labelId,
    onchange: onChange });
  return el('label', { class: 'tick-wrap' }, input, icon('check'));
}

function chips(task) {
  return [
    task.project ? el('span', { class: 'chip' }, task.project) : null,
    task.for_its_own_sake ? el('span', { class: 'chip soft' }, 'for its own sake') : null,
  ];
}

function ageLabel(task) {
  return el('span', { class: 'age' }, icon('clock'), task.age_days + (task.age_days === 1 ? ' day' : ' days'));
}

function startEditing(li, task) {
  closePopovers();
  const title = el('input', { value: task.title, maxlength: '500', 'aria-label': 'Title', class: 'edit-title' });
  const project = el('input', { value: task.project, maxlength: '100', class: 'edit-project', placeholder: 'project',
    'aria-label': 'Project' });
  const form = el('form', { class: 'edit' }, title, project,
    el('button', { type: 'submit' }, 'Save'),
    el('button', { type: 'button', onclick: () => refresh() }, 'Cancel'));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    write('PATCH', '/api/tasks/' + task.id, { title: title.value, project: project.value });
  });
  form.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); refresh(); }
  });
  li.classList.add('is-editing');
  li.draggable = false;
  li.replaceChildren(form);
  title.focus();
  title.select();
}

// A task row in Focus (card), Closed (ticket) or Open (row).
function renderRow(task) {
  const kind = KIND[task.state];
  const li = el('li', { class: kind === 'row' ? 'row' : kind + ' row', draggable: false });
  if (task.state === 'focus' && task.is_first) li.classList.add('is-first');
  if (task.stale) li.classList.add('stale');
  li.dataset.id = task.id;
  li.dataset.state = task.state;
  const titleId = 'title-' + task.id;

  const grip = el('span', { class: 'grip', title: 'Drag to move', 'aria-hidden': 'true' }, icon('grip'));
  grip.addEventListener('pointerdown', () => { li.draggable = true; });
  grip.addEventListener('pointerup', () => { li.draggable = false; });
  li.addEventListener('dragstart', (event) => {
    dragId = task.id;
    event.dataTransfer.setData('text/plain', String(task.id));
    event.dataTransfer.effectAllowed = 'move';
    closePopovers();
    li.classList.add('dragging');
  });
  li.addEventListener('dragend', () => {
    li.classList.remove('dragging');
    li.draggable = false;
    dragId = null;
    removePlaceholder();
  });

  const title = el('button', { type: 'button', class: 'title', id: titleId, title: 'Click to edit' }, task.title);
  title.addEventListener('click', () => startEditing(li, task));
  const body = el('div', { class: 'body' },
    li.classList.contains('is-first') ? el('span', { class: 'first-label' }, 'first') : null,
    title, ...chips(task),
    task.stale ? ageLabel(task) : null,
    task.notes ? el('p', { class: 'notes' }, task.notes) : null);

  const controls = el('div', { class: 'controls' });
  if (UP[task.state]) {
    controls.append(iconButton('up', 'Promote to ' + LABEL[UP[task.state]],
      (event) => requestMove(task, UP[task.state], {}, event.currentTarget)));
  }
  if (DOWN[task.state]) {
    controls.append(iconButton('down', 'Demote to ' + LABEL[DOWN[task.state]],
      (event) => requestMove(task, DOWN[task.state], {}, event.currentTarget)));
  }
  const bucket = iconButton('bucket', 'Choose a list for ' + task.title,
    (event) => openBucketPopover(event.currentTarget, task));
  bucket.setAttribute('aria-haspopup', 'dialog');
  bucket.setAttribute('aria-expanded', 'false');
  const more = iconButton('more', 'More actions for ' + task.title,
    (event) => openMoreMenu(event.currentTarget, task, li));
  more.setAttribute('aria-haspopup', 'menu');
  more.setAttribute('aria-expanded', 'false');
  controls.append(bucket, more);

  li.append(grip, tickBox(false, titleId, () => markDone(li, task)), body, controls);
  return li;
}

function renderSlot(state) {
  return el('li', { class: 'slot', 'data-state': state },
    el('button', { type: 'button', class: 'slot-button', 'aria-label': 'Add to ' + LABEL[state],
      onclick: () => openCreate(state) },
    icon('plus'), el('span', { class: 'slot-label' }, 'open slot')));
}

function fillList(state, tasks, slots) {
  const items = tasks.map(renderRow);
  for (let i = tasks.length; i < slots; i++) items.push(renderSlot(state));
  $('list-' + state).replaceChildren(...items);
}

// Aging in Open: renew, choose a list, or retire.
function renderAging(task) {
  const titleId = 'aging-title-' + task.id;
  const li = el('li', { class: 'row aging stale', 'data-id': String(task.id), 'data-state': task.state },
    el('div', { class: 'body' }, el('span', { class: 'title', id: titleId }, task.title), ...chips(task), ageLabel(task)));
  const bucket = iconButton('bucket', 'Choose a list for ' + task.title,
    (event) => openBucketPopover(event.currentTarget, task));
  bucket.setAttribute('aria-haspopup', 'dialog');
  bucket.setAttribute('aria-expanded', 'false');
  li.append(el('div', { class: 'controls' },
    el('button', { type: 'button', class: 'text-button renew', onclick: () => renew(task) }, 'Renew'),
    bucket,
    el('button', { type: 'button', class: 'text-button retire', onclick: () => letGo(task, 'Retire it. A reason, if you like:') },
      'Retire')));
  return li;
}

// Set aside: revive into any list, or retire.
function renderSetAside(task) {
  const li = el('li', { class: 'row set-aside', 'data-id': String(task.id), 'data-state': task.state },
    el('div', { class: 'body' }, el('span', { class: 'title' }, task.title), ...chips(task),
      task.reason ? el('p', { class: 'reason' }, task.reason) : null));
  const revive = el('button', { type: 'button', class: 'text-button revive', 'aria-haspopup': 'dialog',
    'aria-expanded': 'false', onclick: (event) => openBucketPopover(event.currentTarget, task) }, 'Revive');
  li.append(el('div', { class: 'controls' }, revive,
    el('button', { type: 'button', class: 'text-button retire', onclick: () => letGo(task, 'Retire it. A reason, if you like:') },
      'Retire')));
  return li;
}

function renderDone(tasks) {
  $('empty-done').hidden = tasks.length > 0;
  $('today-done').replaceChildren(...tasks.map((task) => {
    const titleId = 'done-title-' + task.id;
    const tick = tickBox(true, titleId, (event) => requestMove(task, 'open', {}, event.currentTarget));
    return el('li', { class: 'ledger-line', 'data-id': String(task.id) },
      tick,
      el('time', { class: 'time', datetime: task.done_at }, task.done_at.slice(11, 16)),
      el('span', { class: 'done-title', id: titleId }, task.title),
      ...chips(task));
  }));
}

// The lifeline: 200 segments of 20 weeks each. A picture, not a chart.
function renderLifeline(week) {
  const known = week !== null && week !== undefined;
  const ribbon = $('ribbon');
  if (ribbon.children.length !== SEGMENTS) {
    const segments = [];
    for (let i = 0; i < SEGMENTS; i++) segments.push(el('span', { class: 'segment' }));
    ribbon.replaceChildren(...segments);
  }
  const now = known ? Math.floor(week / WEEKS_PER_SEGMENT) : -1;
  Array.from(ribbon.children).forEach((segment, i) => {
    segment.classList.toggle('lived', known && i < now);
    segment.classList.toggle('now', known && i === now);
    // 0 at the far left, 1 at the present: the stylesheet warms lilac into ember along it.
    segment.style.setProperty('--i', known && now > 0 ? String(i / now) : '0');
  });
  const band = $('lifeline');
  band.classList.toggle('is-unset', !known);
  band.setAttribute('href', known ? '#/weeks' : '#/settings');
  $('lifeline-lived').hidden = !known;
  $('lifeline-ask').hidden = known;
  $('lifeline-remaining').hidden = !known;
  if (!known) {
    band.setAttribute('aria-label', 'Add your birth date to light the ribbon. Opens Settings.');
    return;
  }
  const left = WEEKS_TOTAL - week;
  $('lifeline-numeral').textContent = number(week);
  if (left > 0) {
    $('lifeline-left-line').replaceChildren('about ', el('span', { class: 'lifeline-left' }, number(left)), ' to go');
    $('lifeline-left-caption').textContent = 'if you get the average';
  } else {
    $('lifeline-left-line').replaceChildren('past the average');
    $('lifeline-left-caption').textContent = 'and still here';
  }
  band.setAttribute('aria-label', number(week) + ' weeks lived' +
    (left > 0 ? ', about ' + number(left) + ' to go if you get the average.' : '.') + ' Opens the weeks page.');
}

function renderState(state) {
  current = state;
  closePopovers();
  fillList('focus', focusInOrder(), state.caps.focus);
  $('list-focus').classList.toggle('has-first', state.lists.focus.some((t) => t.is_first));
  fillList('closed', state.lists.closed, state.caps.closed);
  fillList('open', state.lists.open, 0);
  $('empty-open').hidden = state.lists.open.length > 0;
  $('count-focus').textContent = state.lists.focus.length + ' of ' + state.caps.focus;
  $('count-closed').textContent = state.lists.closed.length + ' of ' + state.caps.closed;
  $('count-open').textContent = state.lists.open.length + ' of ' + state.caps.open;

  const aging = state.lists.open.filter((t) => t.stale).sort((a, b) => b.age_days - a.age_days);
  $('list-aging').replaceChildren(...aging.map(renderAging));
  $('empty-aging').hidden = aging.length > 0;
  $('list-neglect').replaceChildren(...state.lists.neglect.map(renderSetAside));
  $('empty-neglect').hidden = state.lists.neglect.length > 0;
  $('stale-days').textContent = String(state.settings.stale_days);

  renderDone(state.today_done);
  const serialize = $('serialize');
  serialize.hidden = !state.notes.serialize;
  serialize.textContent = state.notes.serialize ? capital(state.notes.serialize) + '. One at a time tends to go further.' : '';
  renderLifeline(state.week_number);
  if ($('create-dialog').open) updateCreateStep();
}

async function refresh() {
  try {
    renderState(await api('GET', '/api/state'));
  } catch (error) {
    showMessage(error.message);
  }
  if (currentView() === 'review') loadReview();
}

// ------------------------------------------------------------------ drag and drop

// Focus and Closed trade on the home page; Open reorders on its own page.
function canDrop(fromState, toState) {
  if (fromState === toState) return true;
  return ['focus', 'closed'].includes(fromState) && ['focus', 'closed'].includes(toState);
}

function removePlaceholder() {
  if (placeholder) placeholder.remove();
  placeholder = null;
}

function showPlaceholder(list, event) {
  if (!placeholder) placeholder = el('li', { class: 'placeholder', 'aria-hidden': 'true' });
  const target = event.target.closest('li.row');
  if (target && target.parentNode === list && !target.classList.contains('dragging')) {
    const box = target.getBoundingClientRect();
    const after = event.clientY > box.top + box.height / 2;
    list.insertBefore(placeholder, after ? target.nextSibling : target);
  } else if (!target && placeholder.parentNode !== list) {
    list.insertBefore(placeholder, list.querySelector('li.slot'));
  }
}

function placeholderBeforeId() {
  let next = placeholder ? placeholder.nextElementSibling : null;
  while (next && (!next.classList.contains('row') || next.classList.contains('dragging'))) {
    next = next.nextElementSibling;
  }
  return next ? Number(next.dataset.id) : null;
}

function dropTask(id, toState, beforeId) {
  const li = document.querySelector('li.row[data-id="' + id + '"]');
  const task = findTask(id);
  if (!li || !task) return;
  const ids = idsInList(toState).filter((x) => x !== id);
  let at = beforeId === null ? ids.length : ids.indexOf(beforeId);
  if (at < 0) at = ids.length;
  if (task.state === toState) {
    ids.splice(at, 0, id);
    reorder(toState, ids);
    return;
  }
  requestMove(task, toState, { position: at }, li.querySelector('.icon-button.bucket') || li);
}

function setUpDropTargets() {
  for (const list of document.querySelectorAll('#list-focus, #list-closed, #list-open')) {
    list.addEventListener('dragover', (event) => {
      const source = dragId && findTask(dragId);
      if (!source || !canDrop(source.state, list.dataset.state)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      showPlaceholder(list, event);
    });
    list.addEventListener('dragleave', (event) => {
      if (!list.contains(event.relatedTarget)) removePlaceholder();
    });
    list.addEventListener('drop', (event) => {
      event.preventDefault();
      const id = Number(event.dataTransfer.getData('text/plain'));
      const beforeId = placeholderBeforeId();
      removePlaceholder();
      if (id) dropTask(id, list.dataset.state, beforeId === id ? null : beforeId);
    });
  }
}

// ------------------------------------------------------------------ create dialog

function selectedBucket() {
  const radio = $('create-form').querySelector('input[name="bucket"]:checked');
  return radio ? radio.value : 'open';
}

function updateCreateStep() {
  if (!current) return;
  for (const bucket of BUCKETS) {
    $('seg-count-' + bucket).textContent = current.lists[bucket].length + '/' + current.caps[bucket];
    $('create-bucket').querySelector('.seg[data-bucket="' + bucket + '"]').classList.toggle('is-full', isFull(bucket));
  }
  for (const seg of $('create-bucket').querySelectorAll('.seg')) {
    seg.classList.toggle('is-selected', seg.dataset.bucket === selectedBucket());
  }
  const bucket = selectedBucket();
  const bump = $('create-bump');
  const needsBump = bucket === 'focus' && isFull('focus');
  if (needsBump && bump.hidden) {
    $('create-bump-options').replaceChildren(...bumpRadios(focusInOrder(), 'create-bump'));
  }
  bump.hidden = !needsBump;
  const position = $('create-position-input');
  position.max = String(current.caps.open);
  $('create-position').hidden = !(bucket === 'open' && isFull('open'));
  $('create-closed-note').hidden = !(bucket === 'closed' && isFull('closed'));
}

function growNotes() {
  const notes = $('create-notes');
  notes.style.height = 'auto';
  notes.style.height = notes.scrollHeight + 'px';
}

function openCreate(bucket) {
  closePopovers();
  const dialog = $('create-dialog');
  if (dialog.open) return;
  $('create-form').reset();
  $('create-error').hidden = true;
  $('create-bump').hidden = true;
  $('create-form').querySelector('input[name="bucket"][value="' + (bucket || 'open') + '"]').checked = true;
  updateCreateStep();
  dialog.showModal();
  growNotes();
  $('create-title').focus();
}

function createError(text) {
  const box = $('create-error');
  box.textContent = text;
  box.hidden = false;
}

async function submitCreate(event) {
  event.preventDefault();
  const title = $('create-title');
  if (!title.value.trim()) { title.focus(); return; }
  const bucket = selectedBucket();
  const body = { title: title.value, project: $('create-project').value, notes: $('create-notes').value, state: bucket };
  if (!$('create-bump').hidden) {
    const picked = $('create-form').querySelector('input[name="create-bump"]:checked');
    if (!picked) { createError('Pick the one that steps aside.'); return; }
    body.bump_id = Number(picked.value);
  }
  if (!$('create-position').hidden) {
    const n = Number($('create-position-input').value);
    if (!Number.isInteger(n) || n < 1 || n > current.caps.open) {
      createError('Position is a number from 1 to ' + current.caps.open + '.');
      $('create-position-input').focus();
      return;
    }
    body.position = n - 1;
  }
  let data;
  try {
    data = await api('POST', '/api/tasks', body);
  } catch (error) {
    createError(error.message);
    await refresh(); // a list may have filled meanwhile; this reveals the step it needs
    return;
  }
  $('create-dialog').close();
  toastCascade(data.task, data.cascade, 'added to');
  await refresh();
}

// ------------------------------------------------------------------ review

async function loadReview() {
  let review;
  try {
    review = await api('GET', '/api/review');
  } catch (error) {
    showMessage(error.message);
    return;
  }
  $('review-week').textContent = review.week;
  $('review-question').textContent = review.question;
  const answer = $('review-answer');
  if (document.activeElement !== answer) answer.value = review.answer;
  answer.dataset.week = review.week;
  const titles = (tasks, revive) => tasks.length
    ? tasks.map((task) => el('li', {}, task.title,
        task.reason ? el('span', { class: 'quiet' }, '— ' + task.reason) : null,
        revive ? el('button', { type: 'button', class: 'link',
          onclick: (event) => requestMove(task, 'open', {}, event.currentTarget) }, 'Revive') : null))
    : [el('li', { class: 'empty' }, 'Nothing this week.')];
  $('review-done').replaceChildren(...titles(review.done, false));
  $('review-let-go').replaceChildren(...titles(review.let_go, true));
  $('review-neglect').replaceChildren(...titles(review.neglect, false));
  $('review-past').replaceChildren(...(review.past.length
    ? review.past.map((p) => el('li', {}, el('strong', {}, p.week), ' ', el('span', { class: 'quiet' }, p.question),
        el('p', {}, p.answer)))
    : [el('li', { class: 'empty' }, 'Nothing written yet.')]));
}

async function saveReview(event) {
  event.preventDefault();
  const answer = $('review-answer');
  try {
    await api('PUT', '/api/review/' + answer.dataset.week, { answer: answer.value });
    showMessage('Saved.');
  } catch (error) {
    showMessage(error.message);
  }
  answer.blur();
  loadReview();
}

// ------------------------------------------------------------------ weeks

// The local date on which week number `index` of a life begins, as YYYY-MM-DD.
function weekStartLabel(y, m, d, index) {
  const date = new Date(y, m - 1, d);
  date.setFullYear(y); // new Date() reads years below 100 as 19xx
  date.setDate(date.getDate() + 7 * index);
  const pad = (n) => String(n).padStart(2, '0');
  return String(date.getFullYear()).padStart(4, '0') + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
}

function renderDots(weeks) {
  const [y, m, d] = weeks.birth_date.split('-').map(Number);
  const rows = Math.ceil(weeks.weeks_total / WEEKS_PER_ROW);
  const grid = document.createDocumentFragment();
  for (let age = 0; age < rows; age++) {
    grid.append(el('span', { class: 'age-label' }, age % 10 === 0 ? String(age) : ''));
    for (let column = 0; column < WEEKS_PER_ROW; column++) {
      const index = age * WEEKS_PER_ROW + column;
      let kind = 'ahead';
      if (index < weeks.week_number) kind = 'lived';
      else if (index === weeks.week_number) kind = 'now';
      grid.append(el('span', { class: 'dot ' + kind, title: weekStartLabel(y, m, d, index) + ', age ' + age }));
    }
  }
  $('dots').replaceChildren(grid);
  const n = weeks.week_number;
  const left = weeks.weeks_total - n;
  $('dots-caption').textContent = 'Week ' + number(n) + '. ' + (left > 0
    ? 'About ' + number(left) + ' to go, if you get the average.'
    : 'Past the average, and still here.');
}

async function loadWeeks() {
  let weeks;
  try {
    weeks = await api('GET', '/api/weeks');
  } catch (error) {
    showMessage(error.message);
    return;
  }
  const known = weeks.birth_date !== null;
  $('weeks-ask').hidden = known;
  $('dots').hidden = !known;
  $('dots-caption').hidden = !known;
  if (known) renderDots(weeks);
}

// ------------------------------------------------------------------ settings and report

async function loadSettings() {
  try {
    const settings = await api('GET', '/api/settings');
    $('birth-date').value = settings.birth_date || '';
    $('open-cap').value = String(settings.open_cap);
  } catch (error) {
    showMessage(error.message);
  }
}

async function saveSettings(body) {
  if (await write('PUT', '/api/settings', body)) showMessage('Saved.');
  loadSettings();
}

function updateReportLinks() {
  const year = $('report-year').value || String(new Date().getFullYear());
  $('report-html').href = '/api/report/' + year + '.html';
  $('report-json').href = '/api/report/' + year;
}

// ------------------------------------------------------------------ views and keys

function currentView() {
  const name = location.hash.replace(/^#\/?/, '');
  return VIEWS.includes(name) ? name : 'focus';
}

function showView() {
  closePopovers();
  const name = currentView();
  for (const view of VIEWS) $('view-' + view).hidden = view !== name;
  for (const link of document.querySelectorAll('nav a')) {
    const target = link.getAttribute('href').replace(/^#\/?/, '') || 'focus';
    if (target === name) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  if (name === 'review') loadReview();
  if (name === 'weeks') loadWeeks();
  if (name === 'settings') loadSettings();
  if (name === 'report') updateReportLinks();
}

function onKeyDown(event) {
  onPopoverKey(event);
  if (event.key === 'n' && !isTyping(event.target) && !event.ctrlKey && !event.metaKey && !event.altKey &&
      !$('create-dialog').open) {
    event.preventDefault();
    openCreate('open');
  } else if (event.key === 'Escape' && isTyping(event.target) && !$('create-dialog').open) {
    if (event.target.closest('#quick-log')) event.target.value = '';
    event.target.blur();
  }
}

async function quickLog(event) {
  event.preventDefault();
  const title = $('log-title');
  const ownSake = $('log-own-sake');
  if (!title.value.trim()) return;
  const body = { title: title.value, state: 'done', for_its_own_sake: ownSake.checked };
  if (await write('POST', '/api/tasks', body)) {
    title.value = '';
    ownSake.checked = false;
  }
}

function start() {
  theme = readTheme();
  applyTheme();
  $('theme-toggle').addEventListener('click', cycleTheme);
  $('fab').addEventListener('click', () => openCreate('open'));
  $('create-form').addEventListener('submit', submitCreate);
  $('create-form').addEventListener('change', (event) => {
    if (event.target.name === 'bucket') { $('create-error').hidden = true; updateCreateStep(); }
  });
  $('create-cancel').addEventListener('click', () => $('create-dialog').close());
  $('create-notes').addEventListener('input', growNotes);
  $('create-notes').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      $('create-submit').click();
    }
  });
  $('quick-log').addEventListener('submit', quickLog);
  $('review-form').addEventListener('submit', saveReview);
  $('settings-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const cap = Number($('open-cap').value);
    if (!Number.isInteger(cap)) { showMessage('Open holds a whole number from 5 to 200.'); return; }
    saveSettings({ birth_date: $('birth-date').value, open_cap: cap });
  });
  $('birth-clear').addEventListener('click', () => saveSettings({ birth_date: '' }));
  $('report-year').value = String(new Date().getFullYear());
  $('report-year').addEventListener('input', updateReportLinks);
  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('pointerdown', onOutsidePointer);
  window.addEventListener('hashchange', showView);
  setUpDropTargets();
  showView();
  refresh();
}

// Apply the remembered theme as early as a deferred script can.
theme = readTheme();
if (theme !== 'system') document.documentElement.setAttribute('data-theme', theme);
document.addEventListener('DOMContentLoaded', start);
