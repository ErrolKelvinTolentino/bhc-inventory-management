/* A small, dependency-free interface. Inventory rules live in Python/Postgres. */
(() => {
  'use strict';
  let state = JSON.parse(document.getElementById('initial-state').textContent);
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = name => `<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#${name}"></use></svg>`;
  const number = value => new Intl.NumberFormat('en').format(Number(value || 0));
  const dateLabel = (value, options = {}) => value ? new Intl.DateTimeFormat('en', {day:'numeric',month:'short',year:'numeric',timeZone:value.length===10?'UTC':state.facility.timezone,...options}).format(new Date(value.length === 10 ? `${value}T12:00:00Z` : value)) : 'No expiry';
  const facilityDate = value => new Intl.DateTimeFormat('en-CA',{timeZone:state.facility.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const units = (unit, quantity = 2) => esc(quantity === 1 || /^(mL|mg|g|L)$/i.test(unit) || /s$/i.test(unit) ? unit : `${unit}${/(x|z|ch|sh)$/i.test(unit)?'es':'s'}`);
  const timeLabel = value => new Intl.DateTimeFormat('en', {hour:'numeric',minute:'2-digit',timeZone:state.facility.timezone}).format(new Date(value));
  const initials = value => (value || '').split(' ').filter(Boolean).slice(0,2).map(s => s[0]).join('').toUpperCase();
  const activeItems = () => state.items.filter(i => !i.is_archived);
  const itemById = id => state.items.find(i => i.id === id);
  const categoryName = id => state.categories.find(c => c.id === id)?.name || 'Uncategorized';
  const admin = () => state.user.role === 'admin';
  const stockAlerts = () => activeItems().filter(i => i.stock_status !== 'in_stock');
  const expiryBatches = () => state.batches.filter(b => b.quantity_on_hand > 0 && b.expiry_date && !itemById(b.item_id)?.is_archived && b.expiry_status !== 'usable').sort((a,b) => a.expiry_date.localeCompare(b.expiry_date));
  const detail = item => [item.strength || item.specification, item.dosage_form || item.unit].filter(Boolean).join(' · ');
  const tile = (item, extra = '') => `<span class="item-tile ${item.item_type === 'supply' ? 'supply' : ''} ${extra}">${icon(item.item_type === 'supply' ? 'box' : 'pill')}</span>`;
  const statusLabel = value => ({in_stock:'In stock',low_stock:'Low stock',out_of_stock:'Out of stock'}[value] || value);
  const badge = (text, color = '') => `<span class="badge ${color}">${esc(text)}</span>`;
  const movementLabel = kind => ({receipt:'Received',issue:'Issued',adjustment:'Adjusted',disposal:'Disposed'}[kind] || kind);
  const movementIcon = kind => ({receipt:'receive',issue:'issue',adjustment:'arrows',disposal:'archive'}[kind] || 'arrows');
  let view, filters = {type:'all',search:'',status:'all',category:'all',page:1}, attentionTab = 'stock';
  let historyTab = 'stock', historyType = 'all', historySearch = '', historyDate = '', expiryTab = 'all';
  let toastTimer, lastFocus;

  function syncRoute() {
    const path = location.pathname;
    view = ({'/':'overview','/inventory':'inventory','/movements':'movements','/expiry':'expiry','/categories':'categories','/team':'team','/settings':'settings'})[path] || 'overview';
    filters.type = new URLSearchParams(location.search).get('type') || 'all';
    if (!['all','medicine','supply'].includes(filters.type)) filters.type = 'all';
  }
  function navigate(next, type = 'all', extra = {}) {
    filters = {type,search:'',status:'all',category:'all',page:1,...extra};
    const path = next === 'overview' ? '/' : `/${next}`;
    history.pushState({},'',path + (next === 'inventory' && type !== 'all' ? `?type=${type}` : ''));
    view = next;
    closeSidebar();
    render();
    window.scrollTo({top:0,behavior:'instant'});
  }
  function toast(message, error = false) {
    const element = $('#toast'); element.textContent = message;
    element.className = `toast visible${error ? ' error' : ''}`;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => element.classList.remove('visible'), 4200);
  }
  async function api(action, payload) {
    let response;
    try {
      response = await fetch(`/api/actions/${action}`, {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(payload)});
    } catch (_) { throw new Error('Connection interrupted. Try again; your operation key is preserved.'); }
    const result = await response.json().catch(() => ({error:'The workspace could not complete this request.'}));
    if (!response.ok) throw new Error(result.error || 'Something went wrong. Please try again.');
    if (result.state) state = result.state;
    return result;
  }
  function heading(title, description, actions = '', eyebrow = 'YOUR FACILITY, IN FOCUS') {
    return `<div class="page-heading"><div><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1><p>${esc(description)}</p></div><div class="heading-actions">${actions}</div></div>`;
  }
  const stockButtons = () => `<button class="button secondary-action" data-stock="issue">${icon('issue')}Issue stock</button><button class="button primary" data-stock="receipt">${icon('plus')}Receive stock</button>`;
  const addItemButton = () => admin() ? `<button class="button primary" data-action="new-item">${icon('plus')}Add item</button>` : '';
  function empty(title, description, compact = false, action = '') {
    return `<div class="empty-state ${compact ? 'compact' : ''}">${icon('checkcircle')}<h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
  }

  function updateShell() {
    const nav = view === 'inventory' ? filters.type === 'supply' ? 'supply' : 'medicine' : view;
    $$('[data-nav]').forEach(link => {link.classList.toggle('active',link.dataset.nav === nav);if(link.dataset.nav === nav) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');});
    $('#facility-name').textContent = state.facility.name;
    $('#medicine-count').textContent = activeItems().filter(i => i.item_type === 'medicine').length;
    $('#supply-count').textContent = activeItems().filter(i => i.item_type === 'supply').length;
    $('#expiry-count').textContent = expiryBatches().length || '';
    $('#expiry-count').hidden = !expiryBatches().length;
    $('#user-name').textContent = state.user.name;
    $('#user-role').textContent = admin() ? 'Administrator' : 'Staff member';
    $('#user-avatar').textContent = $('#topbar-avatar').textContent = initials(state.user.name);
    $('#preview-note').hidden = state.mode !== 'demo';
    if ($('#mode-chip')) $('#mode-chip').hidden = state.mode !== 'demo';
    $('#sync-label').textContent = state.mode === 'demo' ? 'Demo data · changes stay in this preview' : 'Facility workspace · connected to Supabase';
    const title = view === 'inventory' ? filters.type === 'medicine' ? 'Medicines' : filters.type === 'supply' ? 'Medical supplies' : 'All inventory' : {overview:'Overview',movements:'Stock movements',expiry:'Expiry watch',categories:'Categories',team:'Team members',settings:'Facility settings'}[view];
    $('#breadcrumb-title').textContent = title;
    document.title = `${title} · Inventory`;
    $('.notification-button>span').hidden = !stockAlerts().length && !expiryBatches().length;
  }
  function render(preserveFocus = false) {
    const focus = preserveFocus ? document.activeElement?.id : null;
    const start = preserveFocus ? document.activeElement?.selectionStart : null;
    updateShell();
    $('#content').innerHTML = ({overview:overviewPage,inventory:inventoryPage,movements:historyPage,expiry:expiryPage,categories:categoriesPage,team:teamPage,settings:settingsPage}[view] || overviewPage)();
    if (focus && document.getElementById(focus)) {
      const field = document.getElementById(focus);field.focus({preventScroll:true});
      if (typeof start === 'number' && field.setSelectionRange && ['search','text'].includes(field.type)) field.setSelectionRange(start,start);
    }
  }

  function overviewPage() {
    const items = activeItems(), alerts = stockAlerts(), batches = expiryBatches();
    const near = batches.filter(b => b.expiry_status === 'near_expiry');
    const weekday = dateLabel(state.today,{weekday:'long',day:'numeric',month:'long',year:undefined});
    const stats = [
      {label:'Medicines',value:items.filter(i => i.item_type === 'medicine').length,foot:'Active medicine items',icon:'pill',nav:'medicine'},
      {label:'Medical supplies',value:items.filter(i => i.item_type === 'supply').length,foot:'Active supply items',icon:'box',nav:'supply'},
      {label:'Stock alerts',value:alerts.length,foot:`${alerts.filter(i => i.stock_status==='low_stock').length} low · ${alerts.filter(i => i.stock_status==='out_of_stock').length} out of stock`,icon:'arrows',color:'terra',nav:'alerts'},
      {label:'Expiring soon',value:near.length,foot:`Within ${state.facility.near_expiry_days} days`,icon:'clock',color:'amber',nav:'expiry'},
    ];
    return heading('Overview','A daily check on your facility’s essentials.',stockButtons(),weekday.toUpperCase()) +
      `<div class="stats-grid">${stats.map(s=>`<button class="stat-card" data-stat="${s.nav}"><span class="stat-label">${s.label}</span>${icon(s.icon)}<strong class="stat-value ${s.color || ''}">${number(s.value)}</strong><span class="stat-foot">${icon(s.nav==='alerts'?'info':'checkcircle')}${esc(s.foot)}</span></button>`).join('')}</div>
      <div class="overview-middle"><section class="panel attention-panel"><div class="panel-heading"><div><h2 class="panel-title">Needs attention</h2><p class="panel-subtitle">A small check today. Fewer surprises tomorrow.</p></div>${icon('info')}</div><div class="attention-tabs"><button class="attention-tab ${attentionTab==='stock'?'active':''}" data-attention="stock">Stock alerts <span>${alerts.length}</span></button><button class="attention-tab ${attentionTab==='expiry'?'active':''}" data-attention="expiry">Expiry watch <span>${batches.length}</span></button></div><div class="attention-list">${attentionTab==='stock' ? alerts.slice(0,3).map(i=>`<button class="attention-row" data-item="${i.id}" type="button">${tile(i)}<div class="attention-copy"><strong>${esc(i.name)}${i.strength?` <span class="muted-strength">${esc(i.strength)}</span>`:''}</strong><p>${number(i.usable_quantity)} ${units(i.unit,i.usable_quantity)} left · Minimum ${number(i.low_stock_threshold)}</p></div>${badge(statusLabel(i.stock_status),i.stock_status==='out_of_stock'?'red':'amber')}${icon('chevron')}</button>`).join('') || empty('All stocked up','No items are below their stock threshold.',true) : batches.slice(0,3).map(b=>{const i=itemById(b.item_id);return `<button class="attention-row" data-item="${i.id}" type="button">${tile(i)}<div class="attention-copy"><strong>${esc(i.name)}</strong><p>${esc(b.batch_number)} · ${dateLabel(b.expiry_date)}</p></div>${badge(b.expiry_status==='expired'?'Expired':'Expiring soon',b.expiry_status==='expired'?'red':'amber')}${icon('chevron')}</button>`;}).join('') || empty('Nothing expiring soon','Your upcoming expiry window is clear.',true)}</div></section>${activityChart()}</div>
      <div class="section-heading"><div><h2>Inventory snapshot</h2><p>The essentials, all in one place.</p></div><button class="text-link" data-action="all-inventory">View all inventory ${icon('arrow')}</button></div>${inventoryTable(true)}`;
  }
  function activityChart() {
    const days = Array.from({length:7},(_,index)=>{const d = new Date(`${state.today}T12:00:00`);d.setDate(d.getDate()-(6-index));return d;});
    const localDate = date => new Intl.DateTimeFormat('en-CA',{timeZone:state.facility.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
    const counts = days.map(d=>{const match = state.transactions.filter(t=>localDate(new Date(t.occurred_at))===localDate(d));return {received:match.filter(t=>t.transaction_type==='receipt').length,issued:match.filter(t=>t.transaction_type==='issue').length};});
    const max = Math.max(4,...counts.flatMap(c=>[c.received,c.issued]));
    const sum = counts.reduce((s,c)=>s+c.received+c.issued,0);
    return `<section class="panel activity-panel"><div class="panel-heading"><div><h2 class="panel-title">Stock activity</h2><p class="panel-subtitle">Movements recorded over the past week.</p></div><span class="activity-range">Last 7 days</span></div><div class="chart-legend"><span><i class="legend-dot"></i>Received</span><span><i class="legend-dot issue"></i>Issued</span></div><div class="chart" role="img" aria-label="${sum} receipts and issues recorded over the last seven days"><div class="chart-axis"><span>${max}</span><span>${Math.round(max/2)}</span><span>0</span></div>${counts.map((c,index)=>`<div class="chart-group" title="${dateLabel(days[index].toISOString())}: ${c.received} receipts, ${c.issued} issues"><span class="chart-bar" style="height:${c.received/max*92}%"></span><span class="chart-bar issue" style="height:${c.issued/max*92}%"></span></div>`).join('')}</div><div class="chart-days">${days.map(d=>`<span>${new Intl.DateTimeFormat('en',{weekday:'short'}).format(d)}</span>`).join('')}</div><div class="chart-footer">${icon('checkcircle')}Every movement has a place in your history.</div></section>`;
  }

  function filteredItems() {
    const q = filters.search.toLowerCase().trim();
    const source = filters.status === 'archived' ? state.items.filter(i=>i.is_archived) : activeItems();
    return source.filter(i => (filters.type === 'all' || i.item_type === filters.type) &&
      (['all','archived'].includes(filters.status) || (filters.status === 'alerts' ? i.stock_status !== 'in_stock' : i.stock_status === filters.status)) &&
      (filters.category === 'all' || i.category_id === filters.category) &&
      (!q || [i.name,i.code,i.brand,i.strength,i.specification,categoryName(i.category_id)].join(' ').toLowerCase().includes(q)));
  }
  function inventoryTable(snapshot = false) {
    let matching = filteredItems();
    if (snapshot && filters.type === 'all' && !filters.search) {
      const featured = ['Paracetamol','Amoxicillin','Examination gloves','Cetirizine','Sterile gauze','Losartan'];
      matching = [...matching].sort((a,b)=>(featured.indexOf(a.name)<0?999:featured.indexOf(a.name))-(featured.indexOf(b.name)<0?999:featured.indexOf(b.name)));
    }
    const pageSize = snapshot?6:10, pages = Math.max(1,Math.ceil(matching.length/pageSize));
    filters.page = Math.min(filters.page,pages);
    const rows = matching.slice((filters.page-1)*pageSize,filters.page*pageSize);
    return `<section class="panel table-panel"><div class="table-toolbar"><div class="segmented" aria-label="Inventory type"><button data-type="all" class="${filters.type==='all'?'active':''}">All items</button><button data-type="medicine" class="${filters.type==='medicine'?'active':''}">Medicines</button><button data-type="supply" class="${filters.type==='supply'?'active':''}">Supplies</button></div><div class="table-tools"><label class="table-search">${icon('search')}<input type="search" id="inventory-search" placeholder="Search inventory..." value="${esc(filters.search)}" aria-label="Search inventory"></label><select class="filter-select" id="stock-filter" aria-label="Filter by stock status"><option value="all">All stock levels</option><option value="alerts" ${filters.status==='alerts'?'selected':''}>Needs attention</option>${['in_stock','low_stock','out_of_stock'].map(s=>`<option value="${s}" ${filters.status===s?'selected':''}>${statusLabel(s)}</option>`).join('')}<option value="archived" ${filters.status==='archived'?'selected':''}>Archived items</option></select></div></div>${filters.category!=='all'?`<div class="filter-caption">Category: ${esc(categoryName(filters.category))} <button data-action="clear-category">Clear filter ×</button></div>`:''}<div class="table-wrap"><table class="inventory-table"><thead><tr><th>Item name</th><th>Category</th><th>Available</th><th>Stock level</th><th>Next expiry</th><th><span class="sr-only">Details</span></th></tr></thead><tbody>${rows.map(i=>{
      const next = state.batches.filter(b=>b.item_id===i.id && b.quantity_on_hand>0 && b.expiry_date && b.expiry_date>=state.today).sort((a,b)=>a.expiry_date.localeCompare(b.expiry_date))[0];
      const pct = Math.min(100,Math.max(0,i.usable_quantity/Math.max(i.low_stock_threshold*3,1)*100));
      return `<tr data-item="${i.id}"><td class="item-cell"><div class="item-cell-inner">${tile(i,'table-tile')}<span><button class="item-name-button" data-item="${i.id}" aria-label="View ${esc(i.name)}">${esc(i.name)}</button><small>${esc(detail(i))}</small></span></div></td><td>${esc(categoryName(i.category_id))}</td><td class="available"><strong>${number(i.usable_quantity)}</strong><span>${units(i.unit,i.usable_quantity)}</span><small class="mobile-stock ${i.stock_status}">${i.is_archived?'Archived':statusLabel(i.stock_status)}</small></td><td><span class="stock-meter ${i.stock_status}"><span><i style="width:${pct}%"></i></span>${i.is_archived?'Archived':statusLabel(i.stock_status)}</span></td><td>${next?dateLabel(next.expiry_date):'—'}</td><td>${icon('chevron').replace('class="icon"','class="icon row-arrow"')}</td></tr>`;
    }).join('')}</tbody></table>${!rows.length?empty('No items here yet',filters.search||filters.status!=='all'?'Try a different search or stock filter.':'Add your first item, then receive stock to start its history.',false,admin()&&!filters.search?`<button class="button primary" data-action="new-item">${icon('plus')}Add your first item</button>`:''):''}</div><div class="table-footer"><span>${matching.length?`Showing ${(filters.page-1)*pageSize+1}–${Math.min(filters.page*pageSize,matching.length)} of ${matching.length} items`:'No matching items'}</span>${snapshot?`<button data-action="all-inventory">Open full inventory ${icon('arrow')}</button>`:`<span class="pagination"><button data-page="${filters.page-1}" ${filters.page===1?'disabled':''}>Previous</button><span>${filters.page} / ${pages}</span><button data-page="${filters.page+1}" ${filters.page===pages?'disabled':''}>Next</button></span>`}</div></section>`;
  }
  function inventoryPage() {
    const title = filters.type==='medicine'?'Medicines':filters.type==='supply'?'Medical supplies':'All inventory';
    return heading(title,'Organized by item. Tracked by batch. Ready when needed.',`<button class="button secondary-action" data-stock="receipt">${icon('receive')}Receive stock</button>${addItemButton()}`,'THE STOCKROOM')+inventoryTable();
  }

  function historyPage() {
    const transactions = state.transactions.filter(t=>(historyType==='all'||t.transaction_type===historyType) &&
      (!historySearch||[t.item_name,t.actor_name,t.item_code,t.reference_number,t.source_destination].join(' ').toLowerCase().includes(historySearch.toLowerCase())) &&
      (!historyDate||facilityDate(t.occurred_at)===historyDate));
    return heading('Stock movements','Every receipt, every issue. A clear record of what changed.',stockButtons(),'THE PAPER TRAIL')+
      `<div class="type-tabs"><button class="${historyTab==='stock'?'active':''}" data-history-tab="stock">Stock history <small>${state.transactions.length}</small></button>${admin()?`<button class="${historyTab==='activity'?'active':''}" data-history-tab="activity">Activity log <small>${state.audit_events.length}</small></button>`:''}</div>`+
      (historyTab==='activity'?activityLog():`<section class="panel table-panel"><div class="table-toolbar"><span class="panel-title">Transaction history</span><div class="table-tools"><label class="table-search">${icon('search')}<input type="search" id="history-search" aria-label="Search transaction history" placeholder="Item, reference, or staff..." value="${esc(historySearch)}"></label><input class="table-date-input" type="date" id="history-date" value="${esc(historyDate)}" aria-label="Filter transaction date"><select class="filter-select" id="history-filter" aria-label="Filter movement type"><option value="all">All movements</option>${['receipt','issue','adjustment','disposal'].map(k=>`<option value="${k}" ${historyType===k?'selected':''}>${movementLabel(k)}</option>`).join('')}</select></div></div><div class="table-wrap"><table class="movement-table"><thead><tr><th>Date & time</th><th>Item</th><th>Movement</th><th>Quantity</th><th>Recorded by</th><th></th></tr></thead><tbody>${transactions.map(t=>`<tr data-transaction="${t.id}"><td class="history-date">${dateLabel(t.occurred_at)}<small>${timeLabel(t.occurred_at)}</small></td><td class="item-cell"><button class="item-name-button" data-transaction="${t.id}">${esc(t.item_name)}</button><small>${esc(t.reference_number || t.item_code)}</small></td><td><span class="movement-type ${t.transaction_type}">${icon(movementIcon(t.transaction_type))}${movementLabel(t.transaction_type)}${t.corrects_transaction_id?' · correction':''}</span></td><td class="${t.quantity_change>0?'positive':'negative'}">${t.quantity_change>0?'+':''}${number(t.quantity_change)} <span class="unit-note">${units(t.unit,Math.abs(t.quantity_change))}</span></td><td>${esc(t.actor_name)}</td><td>${icon('chevron').replace('class="icon"','class="icon row-arrow"')}</td></tr>`).join('')}</tbody></table>${!transactions.length?empty('A clean start','Stock movements will appear here as your team receives and issues inventory.'):''}</div><div class="table-footer"><span>${transactions.length} recorded movements${state.history_limit?` · latest ${state.history_limit} loaded`:''}</span><span>Original records are always preserved</span></div></section>`);
  }
  function activityLog() {
    return `<section class="panel table-panel"><div class="table-wrap"><table><thead><tr><th>Date & time</th><th>Activity</th><th>Details</th><th>Recorded by</th></tr></thead><tbody>${state.audit_events.map(a=>{
      const name = a.new_data?.name || a.old_data?.name || a.new_data?.code || a.new_data?.user_id || '';
      const changes = a.action==='UPDATE'?Object.keys(a.new_data || {}).filter(k=>!['updated_at','created_at'].includes(k)&&JSON.stringify(a.new_data[k])!==JSON.stringify(a.old_data?.[k])).map(k=>`${k.replaceAll('_',' ')}: ${a.old_data?.[k]??'—'} → ${a.new_data?.[k]??'—'}`).join('; '):a.action==='DELETE'?'Removed unused catalog record':'New record created';
      return `<tr><td class="history-date">${dateLabel(a.occurred_at)}<small>${timeLabel(a.occurred_at)}</small></td><td>${esc(({items:'Item',categories:'Category',facilities:'Facility',facility_memberships:'Staff access'})[a.table_name] || a.table_name)} ${a.action==='INSERT'?'added':a.action==='DELETE'?'removed':'updated'}<small class="audit-record">${esc(name)}</small></td><td class="audit-details">${esc(changes)}</td><td>${esc(a.actor_name)}</td></tr>`;
    }).join('')}</tbody></table>${!state.audit_events.length?empty('Your activity log starts here','Item edits, facility changes, and staff access updates are recorded automatically.'):''}</div><div class="table-footer"><span>Administrative activity · latest 100 events</span><span>Administrator access only</span></div></section>`;
  }
  function expiryPage() {
    const batches = expiryBatches().filter(b=>expiryTab==='all'||b.expiry_status===expiryTab);
    return heading('Expiry watch','Know what to use next, and what to set aside.','',`LOOKING ${state.facility.near_expiry_days} DAYS AHEAD`)+
      `<div class="notice-strip">${icon('info')}<span>Expiry dates are checked in your facility’s timezone. Expired stock stays in your physical count until disposal is recorded.</span></div><div class="type-tabs">${[['all','All flagged'],['near_expiry','Expiring soon'],['expired','Expired']].map(([value,label])=>`<button class="${expiryTab===value?'active':''}" data-expiry-tab="${value}">${label}<small>${expiryBatches().filter(b=>value==='all'||b.expiry_status===value).length}</small></button>`).join('')}</div><section class="panel table-panel"><div class="table-wrap"><table><thead><tr><th>Item</th><th>Batch</th><th>Expiry date</th><th>On hand</th><th>Status</th><th></th></tr></thead><tbody>${batches.map(b=>{const i=itemById(b.item_id);return `<tr data-item="${i.id}"><td class="item-cell"><div class="item-cell-inner">${tile(i,'table-tile')}<span><button class="item-name-button" data-item="${i.id}">${esc(i.name)}</button><small>${esc(detail(i))}</small></span></div></td><td>${esc(b.batch_number)}</td><td>${dateLabel(b.expiry_date)}</td><td>${number(b.quantity_on_hand)} ${units(i.unit,b.quantity_on_hand)}</td><td>${badge(b.expiry_status==='expired'?'Expired':'Expiring soon',b.expiry_status==='expired'?'red':'amber')}</td><td>${admin()&&b.expiry_status==='expired'?`<button class="button small danger" data-dispose="${b.id}">Record disposal</button>`:icon('chevron').replace('class="icon"','class="icon row-arrow"')}</td></tr>`;}).join('')}</tbody></table>${!batches.length?empty('Your expiry window is clear','There are no stocked batches in this expiry group.'):''}</div><div class="table-footer"><span>${batches.length} flagged batches</span><span>Expired items are blocked from issue</span></div></section>`;
  }
  function categoriesPage() {
    return heading('Categories','A familiar place for every kind of essential.',admin()?`<button class="button primary" data-action="new-category">${icon('plus')}Add category</button>`:'','A LITTLE STRUCTURE')+
      `<div class="category-grid">${state.categories.map(c=>`<button class="category-card" data-category="${c.id}">${tile({item_type:c.item_type})}<span><strong>${esc(c.name)}</strong><p>${activeItems().filter(i=>i.category_id===c.id).length} ${c.item_type==='medicine'?'medicine':'supply'} items</p></span>${icon('chevron')}</button>`).join('')}</div>${!state.categories.length?empty('Start with a little structure','Create categories to make finding medicines and supplies easier.'):''}`;
  }
  function teamPage() {
    return heading('Team members','The people keeping your facility’s essentials in order.',admin()?(state.mode==='demo'?`<a class="button" href="/login">Open your facility ${icon('arrow')}</a>`:`<button class="button primary" data-action="new-member">${icon('plus')}Add existing account</button>`):'','YOUR PEOPLE')+
      (state.mode==='demo'?`<div class="notice-strip">${icon('info')}<span>This sample team is for preview. Sign in to manage access to your own facility.</span></div>`:'')+
      `<section class="panel table-panel"><div class="table-wrap"><table><thead><tr><th>Team member</th><th>Role</th><th>Access</th><th></th></tr></thead><tbody>${state.members.map(m=>`<tr><td><div class="team-name"><span class="avatar">${esc(initials(m.name))}</span><span><strong>${esc(m.name)}${m.user_id===state.user.id?' <span class="you-label">(you)</span>':''}</strong><small>${m.role==='admin'?'Workspace management':'Daily inventory operations'}</small></span></div></td><td>${m.role==='admin'?'Administrator':'Staff member'}</td><td>${badge(m.is_active?'Active':'Inactive',m.is_active?'':'gray')}</td><td>${admin()&&state.mode==='live'?`<button class="button small" data-member="${m.user_id}">Manage</button>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;
  }
  function settingsPage() {
    if (!admin()) return heading('Facility settings','Your facility’s workspace preferences.')+empty('Managed by your administrator','Ask a facility administrator to update workspace settings.');
    return heading('Facility settings','Your name on the door. Your preferences inside.','','MAKE IT YOURS')+
      `<div class="settings-grid"><section class="panel settings-panel"><h2>Workspace details</h2><p>These settings apply to everyone in your facility.</p><form id="settings-form"><label>Facility name<input name="name" maxlength="200" required value="${esc(state.facility.name)}"><small>Shown throughout your facility’s workspace.</small></label><div class="form-row"><label>Facility timezone<select name="timezone">${[...new Set(['Asia/Manila','Asia/Singapore','UTC',state.facility.timezone])].map(t=>`<option ${t===state.facility.timezone?'selected':''}>${esc(t)}</option>`).join('')}</select></label><label>Near-expiry window<input name="near_expiry_days" type="number" min="1" max="365" required value="${state.facility.near_expiry_days}"><small>Days ahead to flag upcoming expiries.</small></label></div><p class="form-error" hidden role="alert"></p><button class="button primary" type="submit">Save changes ${icon('check')}</button></form></section><aside class="settings-aside">${icon('shield')}<h3>A workspace of your own.</h3><p>Your medicines, supplies, stock history, and team access belong to this facility. Other facilities have their own separate workspace.</p><div class="settings-divider"></div><dl class="definition-list"><dt>Branding</dt><dd>Facility name</dd><dt>Stock locations</dt><dd>One facility stockroom</dd><dt>History</dt><dd>Always preserved</dd><dt>Workspace</dt><dd>${state.mode==='demo'?'Demo preview':'Live facility'}</dd></dl></aside></div>`;
  }

  function closeDialogs() { $$('dialog[open]').forEach(d=>d.close()); }
  function openDialog(id, html) {
    lastFocus = document.activeElement;
    closeDialogs();
    const element = document.getElementById(id);
    if (html) $(`#${id}-content`).innerHTML = html;
    element.setAttribute('aria-label',$('h2',element)?.textContent || 'Search inventory');
    element.showModal();
    $('form select, form input:not([type="hidden"]), form textarea',element)?.focus();
  }
  const closeButton = id => `<button type="button" class="icon-button" data-close="${id}" aria-label="Close dialog">${icon('close')}</button>`;
  const dialogHeader = (title, subtitle = '') => `<div class="dialog-header"><div><h2>${esc(title)}</h2>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div>${closeButton('form-dialog')}</div>`;
  const dialogFooter = (label = 'Save changes') => `<div class="dialog-footer"><button type="button" class="button" data-close="form-dialog">Cancel</button><button class="button primary" type="submit">${esc(label)}</button></div>`;
  const errorField = () => `<p class="form-error" hidden role="alert"></p>`;
  function openStock(kind, itemId = '', options = {}) {
    const title = {receipt:'Receive stock',issue:'Issue stock',adjustment:options.corrects?'Record a correction':'Adjust stock count',disposal:'Record disposal'}[kind];
    openDialog('form-dialog',dialogHeader(title,kind==='issue'?'The earliest usable batches are selected first.':kind==='adjustment'?'Counted stock becomes the new batch balance.':'Every change is saved to your stock history.')+
      `<form id="stock-form" data-kind="${kind}"><div class="dialog-body"><input type="hidden" name="idempotency_key" value="${crypto.randomUUID()}"><input type="hidden" name="corrects" value="${esc(options.corrects || '')}"><label>Item<select name="item_id" id="stock-item" required><option value="">Choose a medicine or supply</option>${activeItems().map(i=>`<option value="${i.id}" ${i.id===itemId?'selected':''}>${esc(i.name)}${i.strength?' · '+esc(i.strength):''}</option>`).join('')}</select></label><div id="stock-specific-fields"></div><label>${kind==='receipt'?'Received from':kind==='issue'?'Issued to / purpose':'Reference (optional)'}<input name="source_destination" placeholder="${kind==='receipt'?'e.g. Municipal health office':kind==='issue'?'e.g. Outpatient services':'e.g. Physical inventory check'}" maxlength="200"></label><label>Reference number <span class="optional">(optional)</span><input name="reference_number" placeholder="e.g. DEL-2026-015" maxlength="120"></label><label>Reason ${['adjustment','disposal'].includes(kind)||options.corrects?'':'<span class="optional">(optional)</span>'}<textarea name="reason" placeholder="${kind==='adjustment'?'Explain the difference from the recorded balance':kind==='disposal'?'e.g. Expired batch removed from stock':'Add a note for your team'}" ${['adjustment','disposal'].includes(kind)||options.corrects?'required':''} maxlength="1000"></textarea></label>${options.corrects?`<div class="inline-note">${icon('info')}The original transaction stays in history. This entry will be linked as its correction.</div>`:''}${errorField()}</div>${dialogFooter(kind==='receipt'?'Receive stock':kind==='issue'?'Issue stock':'Record change')}</form>`);
    updateStockFields(options.batch);
  }
  function updateStockFields(selectedBatch = '') {
    const form = $('#stock-form'), kind = form.dataset.kind, item = itemById(form.elements.item_id.value);
    const target = $('#stock-specific-fields');
    if (!item) {target.innerHTML='';return;}
    const batches = state.batches.filter(b=>b.item_id===item.id && (kind!=='issue'||b.quantity_on_hand>0));
    target.innerHTML = `<div class="inline-note">${icon('box')}<span>${number(kind==='issue'?item.usable_quantity:item.physical_quantity)} ${units(item.unit,kind==='issue'?item.usable_quantity:item.physical_quantity)} ${kind==='issue'?'available to issue':'physically on hand'}. ${kind==='issue'?'Expired stock is excluded.':''}</span></div><div class="stock-inputs"><label>${kind==='adjustment'?'Counted quantity':'Quantity'} <span class="optional">(${units(item.unit)})</span><input type="number" name="quantity" min="${kind==='adjustment'?0:1}" step="1" required placeholder="0" inputmode="numeric"></label>${kind==='receipt'?`<div class="form-row"><label>Batch / lot number<input name="batch_number" required maxlength="120" placeholder="e.g. MED26-120"></label><label>Expiry date${!item.expiry_required?' <span class="optional">(optional)</span>':''}<input name="expiry_date" type="date" ${item.expiry_required?'required':''}></label></div>`:`<label>Batch<select name="batch_id" ${['adjustment','disposal'].includes(kind)?'required':''}>${kind==='issue'?'<option value="">Automatic · earliest expiry first</option>':'<option value="">Select a batch</option>'}${batches.map(b=>`<option value="${b.id}" ${b.id===selectedBatch?'selected':''} ${kind==='issue'&&b.expiry_status==='expired'?'disabled':''}>${esc(b.batch_number)} · ${number(b.quantity_on_hand)} on hand${b.expiry_status==='expired'?' · Expired':''}</option>`).join('')}</select></label>`}</div>`;
  }
  function openItemForm(id = '') {
    const item = itemById(id), type = item?.item_type || (filters.type==='supply'?'supply':'medicine');
    const locked = item && state.transactions.some(t=>t.item_id===id);
    openDialog('form-dialog',dialogHeader(item?'Edit item':'Add an item','Start with the item details. Receive its opening stock separately.')+
      `<form id="item-form" data-id="${esc(id)}"><div class="dialog-body"><div class="form-row"><label>Item type<select name="item_type" id="item-type" ${locked?'disabled':''}><option value="medicine" ${type==='medicine'?'selected':''}>Medicine</option><option value="supply" ${type==='supply'?'selected':''}>Medical supply</option></select></label><label>Item code<input name="code" value="${esc(item?.code || '')}" placeholder="e.g. MED-020" maxlength="64" required></label></div><label>Item name<input name="name" value="${esc(item?.name || '')}" placeholder="e.g. Paracetamol" maxlength="200" required></label><div class="form-row"><label>Category<select name="category_id" id="item-category"><option value="">Uncategorized</option>${state.categories.filter(c=>c.item_type===type).map(c=>`<option value="${c.id}" ${c.id===item?.category_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><label>Base stock unit<input name="unit" value="${esc(item?.unit || '')}" placeholder="e.g. tablet, box, bottle" maxlength="40" required ${locked?'readonly':''}></label></div><div class="form-row" id="medicine-fields" ${type==='supply'?'hidden':''}><label>Strength<input name="strength" placeholder="e.g. 500 mg" value="${esc(item?.strength || '')}" maxlength="120"></label><label>Dosage form<input name="dosage_form" placeholder="e.g. Tablet" value="${esc(item?.dosage_form || '')}" maxlength="120"></label></div><label id="supply-fields" ${type==='medicine'?'hidden':''}>Specification<input name="specification" placeholder="e.g. Medium · powder-free" value="${esc(item?.specification || '')}" maxlength="200"></label><div class="form-row"><label>Brand <span class="optional">(optional)</span><input name="brand" value="${esc(item?.brand || '')}" maxlength="120"></label><label>Low-stock threshold<input name="low_stock_threshold" type="number" min="0" step="1" required value="${item?.low_stock_threshold??10}"></label></div><label class="checkbox-label"><input type="checkbox" name="expiry_required" id="item-expiry-required" ${type==='medicine'||item?.expiry_required?'checked':''} ${type==='medicine'?'disabled':''}>Require expiry dates for received batches</label>${locked?'<div class="inline-note">Stock unit and item type stay fixed once stock history exists.</div>':''}${errorField()}</div>${dialogFooter(item?'Save item':'Add item')}</form>`);
  }
  function openCategoryForm() {
    openDialog('form-dialog',dialogHeader('Add a category','Give related essentials a familiar home.')+`<form id="category-form"><div class="dialog-body"><label>Category name<input name="name" required maxlength="120" placeholder="e.g. Wound care"></label><label>Item type<select name="item_type"><option value="medicine">Medicine</option><option value="supply">Medical supply</option></select></label>${errorField()}</div>${dialogFooter('Add category')}</form>`);
  }
  function openMemberForm(id = '') {
    const member = state.members.find(m=>m.user_id===id);
    openDialog('form-dialog',dialogHeader(member?'Manage staff access':'Add an existing account','A staff member must already have a verified account.')+`<form id="member-form"><div class="dialog-body"><label>Account ID<input name="user_id" required value="${esc(id)}" placeholder="Account UUID" ${member?'readonly':''}><small>Ask the person for the account ID shown in their account menu.</small></label><label>Role<select name="role"><option value="staff" ${member?.role==='staff'?'selected':''}>Staff member</option><option value="admin" ${member?.role==='admin'?'selected':''}>Administrator</option></select></label><label class="checkbox-label"><input name="is_active" type="checkbox" ${member?.is_active!==false?'checked':''}>Allow access to this facility</label><div class="inline-note">${icon('shield')}Administrators can manage settings, staff, and stock corrections. Your last administrator must remain active.</div>${errorField()}</div>${dialogFooter('Save access')}</form>`);
  }

  function showItem(id) {
    const item = itemById(id);if(!item)return;
    const batches = state.batches.filter(b=>b.item_id===id).sort((a,b)=>(a.expiry_date||'9999').localeCompare(b.expiry_date||'9999'));
    const txs = state.transactions.filter(t=>t.item_id===id).slice(0,5);
    openDialog('detail-dialog',`<div class="dialog-header"><span class="eyebrow">ITEM DETAILS · ${esc(item.code)}</span>${closeButton('detail-dialog')}</div><div class="detail-hero">${tile(item)}<h2>${esc(item.name)}</h2><p>${esc(detail(item))} · ${esc(categoryName(item.category_id))}</p><div class="detail-stats"><div><small>Available</small><strong>${number(item.usable_quantity)}</strong></div><div><small>Physical stock</small><strong>${number(item.physical_quantity)}</strong></div><div><small>Expired</small><strong>${number(item.expired_quantity)}</strong></div></div><div class="detail-actions">${!item.is_archived?`<button class="button primary" data-stock="receipt" data-stock-item="${id}">${icon('receive')}Receive</button><button class="button" data-stock="issue" data-stock-item="${id}">${icon('issue')}Issue</button>`:badge('Archived','gray')}${admin()?`<button class="button" data-edit-item="${id}">${icon('edit')}Edit</button>`:''}</div></div><section class="detail-section"><h3>Batch inventory <span class="count-label">${batches.length}</span></h3>${batches.map(b=>`<div class="batch-row"><div><strong>${esc(b.batch_number)}</strong><small>${b.expiry_date?`Expires ${dateLabel(b.expiry_date)}`:'No expiry date'}</small></div><span>${number(b.quantity_on_hand)} ${units(item.unit,b.quantity_on_hand)}</span>${b.quantity_on_hand>0&&b.expiry_status!=='usable'?badge(b.expiry_status==='expired'?'Expired':'Soon',b.expiry_status==='expired'?'red':'amber'):''}</div>`).join('') || '<p class="quiet-copy">No batches yet. Receive stock to create the first one.</p>'}${admin()&&batches.length&&!item.is_archived?`<button class="button subtle" data-stock="adjustment" data-stock-item="${id}">${icon('arrows')}Adjust a batch count</button>`:''}</section><section class="detail-section"><h3>Recent movements</h3>${txs.map(t=>`<button class="timeline-row" data-transaction="${t.id}">${icon(movementIcon(t.transaction_type))}<div><strong>${movementLabel(t.transaction_type)} stock</strong><p>${dateLabel(t.occurred_at)} · ${esc(t.actor_name)}</p></div><span>${t.quantity_change>0?'+':''}${number(t.quantity_change)}</span></button>`).join('') || '<p class="quiet-copy">Your stock history will appear here.</p>'}</section>${admin()?`<section class="detail-section"><button class="button small" data-archive-item="${id}" data-archive-value="${!item.is_archived}">${icon('archive')}${item.is_archived?'Restore item':'Archive item'}</button><p class="field-footnote">Archival requires zero physical stock. History is always kept.</p></section>`:''}`);
  }
  function showTransaction(id) {
    const tx = state.transactions.find(t=>t.id===id);if(!tx)return;
    openDialog('detail-dialog',`<div class="dialog-header"><div><span class="eyebrow">STOCK HISTORY</span><h2>${movementLabel(tx.transaction_type)} stock</h2><p>${dateLabel(tx.occurred_at)} at ${timeLabel(tx.occurred_at)}</p></div>${closeButton('detail-dialog')}</div><div class="detail-hero"><h2>${esc(tx.item_name)}</h2><p>${esc(tx.item_code)} · Recorded by ${esc(tx.actor_name)}</p><div class="transaction-amount ${tx.quantity_change>0?'positive':'negative'}">${tx.quantity_change>0?'+':''}${number(tx.quantity_change)} <small>${units(tx.unit,Math.abs(tx.quantity_change))}</small></div><dl class="definition-list"><dt>Reference</dt><dd>${esc(tx.reference_number || '—')}</dd><dt>Source / destination</dt><dd>${esc(tx.source_destination || '—')}</dd><dt>Reason</dt><dd>${esc(tx.reason || '—')}</dd>${tx.corrects_transaction_id?`<dt>Linked correction</dt><dd>Original record preserved</dd>`:''}</dl></div><section class="detail-section"><h3>Batch changes</h3>${(tx.lines||[]).map(line=>`<div class="batch-row"><div><strong>${esc(line.batch_number)}</strong><small>${dateLabel(line.expiry_date)}</small></div><span>${number(line.balance_before)} → ${number(line.balance_after)}</span></div>`).join('')}<p class="field-footnote">Balances shown before and after this transaction, per batch.</p></section>${admin()?`<section class="detail-section"><button class="button" data-correct="${tx.id}">${icon('arrows')}Record a linked correction</button><p class="field-footnote">Creates a counted adjustment. This record will stay unchanged.</p></section>`:''}`);
  }
  function showAccount() {
    openDialog('form-dialog',dialogHeader('Your account',state.mode==='demo'?'You are exploring a separate sample workspace.':'Signed in to your facility workspace.')+`<div class="dialog-body"><div class="account-card"><span class="avatar">${esc(initials(state.user.name))}</span><strong>${esc(state.user.name)}</strong><p>${esc(state.user.email || '')}</p></div>${state.mode==='live'?`<label>Account ID<input readonly value="${esc(state.user.id)}"><small>Share this ID only with an administrator who should add you to their facility.</small></label>`:''}<div class="inline-note">${icon('shield')}${state.mode==='demo'?'Your preview changes are isolated from all live facilities.':'Your permissions come from your current facility membership.'}</div></div><div class="dialog-footer">${state.mode==='demo'?'<a class="button primary" href="/login">Sign in to your facility</a>':'<button class="button" data-action="logout">Sign out</button>'}</div>`);
  }
  function search() {
    openDialog('search-dialog');$('#command-input').value='';renderSearch();$('#command-input').focus();
  }
  function renderSearch() {
    const q = $('#command-input').value.trim().toLowerCase();
    const matches = activeItems().filter(i=>!q||[i.name,i.code,i.strength,i.specification,categoryName(i.category_id)].join(' ').toLowerCase().includes(q)).slice(0,7);
    $('#command-results').innerHTML = matches.map(i=>`<button data-item="${i.id}">${tile(i)}<span><strong>${esc(i.name)}</strong><small>${esc(detail(i))}</small></span><span class="command-stock">${number(i.usable_quantity)} ${units(i.unit)}</span>${icon('chevron')}</button>`).join('') || empty('No matching essentials','Try a different name, category, or item code.',true);
  }

  document.addEventListener('click',async event=>{
    const target = event.target.closest('button,a,[data-item],[data-transaction]');if(!target)return;
    if (target.dataset.close) {document.getElementById(target.dataset.close).close();return;}
    if (target.dataset.nav) {event.preventDefault();const name=target.dataset.nav;navigate(name==='medicine'||name==='supply'?'inventory':name,name==='medicine'||name==='supply'?name:'all');return;}
    if (target.dataset.dispose) {const batch=state.batches.find(b=>b.id===target.dataset.dispose);openStock('disposal',batch.item_id,{batch:batch.id});return;}
    if (target.dataset.stock) {openStock(target.dataset.stock,target.dataset.stockItem || '');return;}
    if (target.dataset.editItem) {openItemForm(target.dataset.editItem);return;}
    if (target.dataset.correct) {const tx=state.transactions.find(t=>t.id===target.dataset.correct);openStock('adjustment',tx.item_id,{batch:tx.lines?.[0]?.batch_id,corrects:tx.id});return;}
    if (target.dataset.archiveItem) {try{target.disabled=true;const result=await api('archive',{id:target.dataset.archiveItem,is_archived:target.dataset.archiveValue==='true'});closeDialogs();render();toast(result.message);}catch(error){toast(error.message,true);target.disabled=false;}return;}
    if (target.dataset.transaction) {showTransaction(target.dataset.transaction);return;}
    if (target.dataset.item) {showItem(target.dataset.item);return;}
    if (target.dataset.type) {filters.type=target.dataset.type;filters.page=1;if(view==='inventory')history.replaceState({},'',filters.type==='all'?'/inventory':`/inventory?type=${filters.type}`);render();return;}
    if (target.dataset.page) {filters.page=Number(target.dataset.page);render();return;}
    if (target.dataset.attention) {attentionTab=target.dataset.attention;render();return;}
    if (target.dataset.historyTab) {historyTab=target.dataset.historyTab;render();return;}
    if (target.dataset.expiryTab) {expiryTab=target.dataset.expiryTab;render();return;}
    if (target.dataset.category) {const c=state.categories.find(c=>c.id===target.dataset.category);navigate('inventory',c.item_type,{category:c.id});return;}
    if (target.dataset.member) {openMemberForm(target.dataset.member);return;}
    if (target.dataset.stat) {const nav=target.dataset.stat;if(nav==='expiry')navigate('expiry');else if(nav==='alerts')navigate('inventory','all',{status:'alerts'});else navigate('inventory',nav);return;}
    if (target.dataset.facility) {try{const result=await api('switch',{facility_id:target.dataset.facility});$('#workspace-menu').hidden=true;render();toast(result.message);}catch(error){toast(error.message,true);}return;}
    const action = target.dataset.action;
    if (action==='all-inventory') navigate('inventory',filters.type);
    if (action==='new-item') openItemForm();
    if (action==='new-category') openCategoryForm();
    if (action==='new-member') openMemberForm();
    if (action==='clear-category') {filters.category='all';render();}
    if (action==='alerts') {attentionTab='stock';if(stockAlerts().length)navigate('inventory','all',{status:'alerts'});else navigate('expiry');}
    if (action==='logout') {try{const response=await fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:'{}'});const result=await response.json();if(!response.ok)throw new Error(result.error);location.href=result.redirect;}catch(error){toast(error.message,true);}}
  });
  document.addEventListener('input',event=>{
    if (event.target.id==='inventory-search') {filters.search=event.target.value;filters.page=1;render(true);}
    if (event.target.id==='history-search') {historySearch=event.target.value;render(true);}
    if (event.target.id==='command-input') renderSearch();
  });
  document.addEventListener('change',event=>{
    if(event.target.id==='stock-filter'){filters.status=event.target.value;filters.page=1;render();}
    if(event.target.id==='history-filter'){historyType=event.target.value;render();}
    if(event.target.id==='history-date'){historyDate=event.target.value;render();}
    if(event.target.id==='stock-item')updateStockFields();
    if(event.target.id==='item-type'){
      const medicine=event.target.value==='medicine';$('#medicine-fields').hidden=!medicine;$('#supply-fields').hidden=medicine;
      $('#item-expiry-required').disabled=medicine;$('#item-expiry-required').checked=medicine;
      $('#item-category').innerHTML='<option value="">Uncategorized</option>'+state.categories.filter(c=>c.item_type===event.target.value).map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('');
    }
  });
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!['stock-form','item-form','category-form','settings-form','member-form'].includes(form.id))return;
    event.preventDefault();if(!form.reportValidity())return;
    const values=Object.fromEntries(new FormData(form)), submit=$('button[type="submit"]',form), error=$('.form-error',form);
    submit.disabled=true;error.hidden=true;
    let action,payload;
    if(form.id==='stock-form'){
      action='stock';payload={p_item_id:values.item_id,p_transaction_type:form.dataset.kind,p_quantity:Number(values.quantity),p_idempotency_key:values.idempotency_key,p_reason:values.reason||null,p_source_destination:values.source_destination||null,p_reference_number:values.reference_number||null};
      if(values.batch_id)payload.p_batch_id=values.batch_id;
      if(values.batch_number)payload.p_batch_number=values.batch_number;
      if(values.expiry_date)payload.p_expiry_date=values.expiry_date;
      if(values.corrects)payload.p_corrects_transaction_id=values.corrects;
    }else if(form.id==='item-form'){
      action='item';const existing=itemById(form.dataset.id);payload={...values,id:form.dataset.id||null,item_type:values.item_type||existing?.item_type,category_id:values.category_id||null,low_stock_threshold:Number(values.low_stock_threshold),expiry_required:values.item_type==='medicine'||existing?.item_type==='medicine'||values.expiry_required==='on'};
      payload.generic_name=payload.item_type==='medicine'?values.name:null;
    }else if(form.id==='settings-form'){action='settings';payload={...values,near_expiry_days:Number(values.near_expiry_days)};}
    else if(form.id==='member-form'){action='member';payload={...values,is_active:values.is_active==='on'};}
    else{action='category';payload=values;}
    try{const result=await api(action,payload);closeDialogs();render();toast(result.message);}catch(err){error.textContent=err.message;error.hidden=false;submit.disabled=false;error.scrollIntoView({block:'nearest'});}
  });
  function closeSidebar() {$('#sidebar').classList.remove('open');$('#sidebar-scrim').classList.remove('open');$('#mobile-menu').setAttribute('aria-expanded','false');}
  $('#mobile-menu').addEventListener('click',()=>{const open=$('#sidebar').classList.toggle('open');$('#sidebar-scrim').classList.toggle('open',open);$('#mobile-menu').setAttribute('aria-expanded',String(open));});
  $('#sidebar-scrim').addEventListener('click',closeSidebar);
  $('#search-trigger').addEventListener('click',search);
  $('#profile-button').addEventListener('click',showAccount);
  $('#facility-selector').addEventListener('click',()=>{
    const menu=$('#workspace-menu');menu.hidden=!menu.hidden;$('#facility-selector').setAttribute('aria-expanded',String(!menu.hidden));
    menu.innerHTML=`<small>${state.mode==='demo'?'SAMPLE WORKSPACE':'YOUR FACILITIES'}</small>${state.facilities.map(f=>`<button data-facility="${f.id}">${esc(f.name)}${f.id===state.facility.id?' ✓':''}</button>`).join('')}${state.mode==='demo'?'<a href="/login">Sign in to your facility →</a>':''}`;
  });
  document.addEventListener('keydown',event=>{
    if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();search();}
    if(event.key==='Escape')closeSidebar();
    if(event.key==='Enter'&&event.target.id==='command-input')$('#command-results button')?.click();
  });
  $$('dialog').forEach(dialog=>{
    dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
    dialog.addEventListener('close',()=>{if(!$$('dialog[open]').length&&lastFocus?.isConnected)lastFocus.focus({preventScroll:true});});
  });
  window.addEventListener('popstate',()=>{syncRoute();render();});
  syncRoute();render();
})();
