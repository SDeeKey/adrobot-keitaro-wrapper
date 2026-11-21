'use strict';

const $ = (selector) => document.querySelector(selector);
const state = { config: null, refs: null, campaigns: [], selected: null, busy: false };

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function message(text, error = false) {
  const node = $('#message');
  node.textContent = text;
  node.className = error ? 'error' : '';
  node.hidden = !text;
}

async function api(path, method = 'GET', data) {
  const response = await fetch(`/api${path}`, {
    method, headers: { 'Content-Type': 'application/json' },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  });
  const body = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join('; ') : body.detail;
    throw new Error(detail || `Ошибка HTTP ${response.status}`);
  }
  return body;
}

async function perform(action, successMessage = '') {
  if (state.busy) return;
  state.busy = true;
  const controls = [...document.querySelectorAll('button, input, select')];
  const previousDisabled = controls.map((node) => node.disabled);
  controls.forEach((node) => { node.disabled = true; });
  message('Выполняется запрос…');
  try {
    await action();
    message(successMessage);
  } catch (error) {
    message(error.message || 'Не удалось выполнить запрос. Проверьте соединение.', true);
  } finally {
    controls.forEach((node, index) => { if (node.isConnected) node.disabled = previousDisabled[index]; });
    state.busy = false;
  }
}

function options(select, rows, label = 'Выберите…') {
  select.replaceChildren();
  const placeholder = element('option', label);
  placeholder.value = '';
  placeholder.disabled = true;
  placeholder.selected = true;
  select.append(placeholder);
  for (const row of rows) {
    const option = element('option', `#${row.id} · ${row.name || row.url || row.host || 'Без названия'}`);
    option.value = row.id;
    select.append(option);
  }
  if (rows.length === 1) select.value = rows[0].id;
}

async function loadList() {
  state.campaigns = await api('/campaigns');
  renderList();
}

function renderList() {
  const container = $('#campaigns');
  container.replaceChildren();
  if (!state.campaigns.length) container.append(element('p', 'Пока нет кампаний с вашим префиксом.', 'muted'));
  for (const campaign of state.campaigns) {
    const button = element('button', undefined, 'campaign-item');
    button.type = 'button';
    button.classList.toggle('selected', state.selected?.id === campaign.id);
    button.append(element('span', campaign.name), element('small', `#${campaign.id}`));
    button.addEventListener('click', () => perform(() => openCampaign(campaign.id)));
    container.append(button);
  }
}

async function openCampaign(id) {
  state.selected = await api(`/campaigns/${id}/refresh`, 'POST');
  $('#stats').textContent = '';
  renderEditor();
  renderList();
}

async function changeOffer(streamId, offerId, action, share) {
  const selected = state.selected;
  state.selected = await api(`/campaigns/${selected.id}/streams/${streamId}/offers`, 'POST', {
    revision: selected.revision, action, offer_id: offerId,
    ...(share === undefined ? {} : { share }),
  });
  renderEditor();
}

function offerRow(stream, offer) {
  const row = element('div', undefined, `offer-row${offer.removed ? ' removed' : ''}`);
  const name = element('div', offer.name, 'offer-name');
  name.append(element('small', `ID ${offer.offer_id}${offer.removed ? ' · удалён из потока' : ''}`));
  const share = element('input', undefined, 'share-input');
  share.type = 'number'; share.min = '0'; share.max = '100'; share.step = '1';
  share.value = offer.share;
  share.setAttribute('aria-label', `Доля в процентах: ${offer.name}`);
  share.disabled = offer.removed;
  const saveShare = () => {
    const value = Number(share.value);
    if (!share.value.trim() || !Number.isInteger(value) || value < 0 || value > 100) {
      share.value = offer.share;
      message('Доля должна быть целым числом от 0 до 100.', true);
      return;
    }
    if (value === offer.share) return;
    perform(async () => {
      try { await changeOffer(stream.id, offer.offer_id, 'share', value); }
      catch (error) { share.value = offer.share; throw error; }
    }, 'Доля сохранена и закреплена.');
  };
  share.addEventListener('change', saveShare);
  share.addEventListener('blur', saveShare);
  const shareControl = element('form', undefined, 'share-control');
  const save = element('button', '✓', 'share-save');
  save.type = 'submit'; save.disabled = offer.removed;
  save.title = 'Сохранить процент';
  save.setAttribute('aria-label', `Сохранить долю: ${offer.name}`);
  shareControl.append(share, save);
  shareControl.addEventListener('submit', (event) => { event.preventDefault(); saveShare(); });
  const pin = element('button', offer.pinned ? '●' : '○', `pin${offer.pinned ? ' active' : ''}`);
  pin.type = 'button'; pin.disabled = offer.removed;
  const pinLabel = `${offer.pinned ? 'Открепить' : 'Закрепить'} долю: ${offer.name}`;
  pin.title = pinLabel; pin.setAttribute('aria-label', pinLabel); pin.setAttribute('aria-pressed', String(offer.pinned));
  pin.addEventListener('click', () => perform(() => changeOffer(stream.id, offer.offer_id, offer.pinned ? 'unpin' : 'pin'), 'Распределение сохранено.'));
  const action = element('button', offer.removed ? 'Восстановить' : 'Удалить', `offer-action${offer.removed ? ' restore' : ''}`);
  action.type = 'button';
  action.setAttribute('aria-label', `${offer.removed ? 'Восстановить' : 'Удалить'} оффер: ${offer.name}`);
  action.addEventListener('click', () => perform(() => changeOffer(stream.id, offer.offer_id, offer.removed ? 'restore' : 'remove'), 'Офферы и доли обновлены.'));
  row.append(name, shareControl, pin, action);
  return row;
}

function renderEditor() {
  const campaign = state.selected;
  $('#empty').hidden = Boolean(campaign);
  $('#campaign-editor').hidden = !campaign;
  if (!campaign) return;
  $('#campaign-name').textContent = campaign.name;
  $('#campaign-meta').textContent = `КАМПАНИЯ #${campaign.id} · ${campaign.campaign.state === 'active' ? 'АКТИВНА' : 'ПРИОСТАНОВЛЕНА'}`;
  const container = $('#streams');
  container.replaceChildren();
  for (const stream of [...campaign.streams].sort((a, b) => a.position - b.position)) {
    const section = element('section', undefined, 'stream');
    const header = element('div', undefined, 'stream-header');
    header.append(element('h3', `${stream.position}. ${stream.name} · #${stream.id}`));
    const active = stream.offers.filter((offer) => !offer.removed);
    if (active.length) header.append(element('span', `${active.reduce((sum, offer) => sum + offer.share, 0)}%`, 'total'));
    section.append(header);
    if (stream.schema !== 'landings') {
      const filters = stream.filters.map((filter) => `${filter.name}: ${Array.isArray(filter.payload) ? filter.payload.join(', ') : filter.payload}`).join(' · ');
      section.append(element('p', `${filters || 'Без фильтров'} → ${typeof stream.target === 'string' ? stream.target : 'Действие потока'}`, 'stream-description'));
    } else {
      for (const offer of stream.offers) {
        if (!offer.removed || $('#show-removed').checked) section.append(offerRow(stream, offer));
      }
      const form = element('form', undefined, 'add-offer');
      const select = element('select');
      select.required = true;
      select.setAttribute('aria-label', `Добавить оффер в поток ${stream.name}`);
      const knownIds = new Set(stream.offers.map((offer) => offer.offer_id));
      const available = state.refs.offers.filter((offer) => !knownIds.has(offer.id) && offer.state !== 'disabled');
      options(select, available, available.length ? 'Выберите оффер' : 'Все офферы уже добавлены');
      const button = element('button', '+ Добавить');
      button.type = 'submit'; button.disabled = available.length === 0;
      form.append(select, button);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        if (select.value) perform(() => changeOffer(stream.id, Number(select.value), 'add'), 'Оффер добавлен, доли пересчитаны.');
      });
      section.append(form);
    }
    container.append(section);
  }
}

$('#create-form').addEventListener('submit', (event) => {
  event.preventDefault();
  // Read before perform() disables inputs: disabled fields are excluded by FormData.
  const data = Object.fromEntries(new FormData(event.currentTarget));
  for (const key of ['offer_id', 'domain_id', 'group_id', 'traffic_source_id']) data[key] = Number(data[key]);
  perform(async () => {
    state.selected = await api('/campaigns', 'POST', data);
    renderEditor();
    await loadList();
  }, 'Кампания создана: два потока, домен, группа и источник настроены.');
});
$('#open-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const id = Number(new FormData(event.currentTarget).get('campaign_id'));
  perform(() => openCampaign(id));
});
$('#refresh').addEventListener('click', () => perform(() => openCampaign(state.selected.id), 'Данные обновлены из Keitaro.'));
$('#reload-list').addEventListener('click', () => perform(loadList));
$('#show-removed').addEventListener('change', renderEditor);
$('#load-stats').addEventListener('click', () => perform(async () => {
  const report = await api(`/campaigns/${state.selected.id}/stats`);
  const total = report.total;
  if (!total) throw new Error('Отчёт не содержит итогов. Проверьте доступ к отчётам в Keitaro.');
  $('#stats').textContent = `Сегодня (UTC): кликов ${total.clicks ?? '—'}, конверсий ${total.conversions ?? '—'}, доход ${total.revenue ?? '—'} (валюта трекера).`;
}));

perform(async () => {
  state.config = await api('/config');
  $('#mode').textContent = state.config.demo_mode ? 'ДЕМО · ЛОКАЛЬНО' : 'KEITARO · LIVE';
  $('#prefix-hint').textContent = `Префикс ${state.config.prefix} добавится автоматически.`;
  state.refs = await api('/references');
  for (const [id, key] of [['create-offer', 'offers'], ['domain', 'domains'], ['group', 'groups'], ['source', 'sources']]) {
    options($(`#${id}`), state.refs[key].filter((row) => row.state !== 'disabled'));
  }
  await loadList();
});
