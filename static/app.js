/**
 * Troudz WhatsApp AI Sales Copilot — Frontend Application Logic
 * Pure Vanilla JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {
  // State
  let currentFilter = 'pending_review';
  let activeDrafts = [];
  let allCustomers = [];
  let currentEditingDraft = null;
  let selectedCustomerDetailId = null;

  // DOM Elements
  const statCustomers = document.getElementById('stat-customers');
  const statOrders = document.getElementById('stat-orders');
  const statDraftsPending = document.getElementById('stat-drafts-pending');
  const statDraftsApproved = document.getElementById('stat-drafts-approved');
  const tabInboxBadge = document.getElementById('tab-inbox-badge');

  const btnRunIngest = document.getElementById('btn-run-ingest');
  const ingestLimitSelect = document.getElementById('ingest-limit-select');
  const ingestStatusMsg = document.getElementById('ingest-status-msg');

  const btnRunCrossSell = document.getElementById('btn-run-cross-sell');
  const crossSellInput = document.getElementById('cross-sell-customer-input');
  const crossSellStatusMsg = document.getElementById('cross-sell-status-msg');

  const draftsGrid = document.getElementById('drafts-grid');
  const customersTableBody = document.getElementById('customers-table-body');
  const ordersTableBody = document.getElementById('orders-table-body');
  const customerSearch = document.getElementById('customer-search');

  // Modals
  const modalEditDraft = document.getElementById('modal-edit-draft');
  const modalCloseBtn = document.getElementById('modal-close-btn');
  const modalBtnCancel = document.getElementById('modal-btn-cancel');
  const modalBtnSaveSend = document.getElementById('modal-btn-save-send');
  const modalCustomerMeta = document.getElementById('modal-customer-meta');
  const modalEditTextarea = document.getElementById('modal-edit-textarea');
  const modalWaPreviewText = document.getElementById('modal-wa-preview-text');

  const modalCustomerDetail = document.getElementById('modal-customer-detail');
  const custModalCloseBtn = document.getElementById('cust-modal-close-btn');
  const custModalBtnClose = document.getElementById('cust-modal-btn-close');
  const custModalBtnCrossSell = document.getElementById('cust-modal-btn-cross-sell');
  const custModalBody = document.getElementById('cust-modal-body');

  const toastContainer = document.getElementById('toast-container');

  // ── Toast Helper ────────────────────────────────────────────────────────────
  function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'error' ? 'toast-error' : type === 'info' ? 'toast-info' : ''}`;
    const icon = type === 'error' ? '❌' : type === 'info' ? 'ℹ️' : '✅';
    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // ── Fetch Dashboard Stats ───────────────────────────────────────────────────
  async function loadStats() {
    try {
      const res = await fetch('/api/dashboard/stats');
      if (!res.ok) return;
      const data = await res.json();
      statCustomers.textContent = data.customers_total;
      statOrders.textContent = data.orders_total;
      statDraftsPending.textContent = data.drafts_pending;
      statDraftsApproved.textContent = data.drafts_approved;
      tabInboxBadge.textContent = data.drafts_pending;
      document.getElementById('stat-purchases-sub').textContent = `${data.purchases_total} purchases in catalog`;
    } catch (e) {
      console.warn('Stats fetch failed', e);
    }
  }

  // ── Fetch Review Drafts (HITL Inbox) ────────────────────────────────────────
  async function loadDrafts() {
    try {
      const url = currentFilter ? `/review/drafts?status=${currentFilter}` : '/review/drafts';
      const res = await fetch(url);
      if (!res.ok) throw new Error('Failed to load drafts');
      activeDrafts = await res.json();
      renderDrafts(activeDrafts);
    } catch (e) {
      draftsGrid.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">⚠️</div>
          <h3>Error loading drafts</h3>
          <p>${e.message}</p>
        </div>
      `;
    }
  }

  function renderDrafts(drafts) {
    if (!drafts || drafts.length === 0) {
      draftsGrid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <div class="empty-state-icon">🎉</div>
          <h3>No ${currentFilter.replace('_', ' ')} drafts</h3>
          <p>Click "Run LangGraph Agent" above to generate proactive cross-sell drafts for customers.</p>
        </div>
      `;
      return;
    }

    draftsGrid.innerHTML = drafts.map(d => {
      const analysis = d.analysis || {};
      const recs = analysis.cross_sell_recommendations || [];
      const mentioned = analysis.mentioned_products || [];
      const sentiment = d.sentiment || 'neutral';
      const sentimentClass = `badge-sentiment-${sentiment}`;
      const isPending = d.status === 'pending_review';

      const firstRec = recs.length > 0 ? recs[0] : null;
      const firstMention = mentioned.length > 0 ? mentioned[0] : null;

      // Extract clean message text if agent returned JSON object
      let displayMessage = d.final_message || d.generated_message || '';
      if (displayMessage.includes('{') && displayMessage.includes('}')) {
        try {
          const cleanStr = displayMessage.replace(/```json/g, '').replace(/```/g, '').trim();
          const parsed = JSON.parse(cleanStr);
          if (parsed.message_template && parsed.message_template.body) {
            displayMessage = parsed.message_template.body;
          } else if (parsed.body) {
            displayMessage = parsed.body;
          } else if (parsed.message) {
            displayMessage = parsed.message;
          }
        } catch (e) {
          // ignore parsing error
        }
      }
      if (!displayMessage.trim()) {
        displayMessage = 'Hello, thank you for your recent order with Troudz Industrial Supplies. We have ready stock of high-performance complementary consumables with contract volume pricing. Please let us know if you would like to include this in your upcoming delivery.';
      }

      return `
        <div class="draft-card" id="card-draft-${d.id}">
          <div class="draft-card-header">
            <div class="customer-meta">
              <h3>
                <span>📱 ${d.customer_id}</span>
              </h3>
              <div class="customer-phone">Draft ID: #${d.id} · ${d.created_at ? new Date(d.created_at).toLocaleTimeString() : 'Just now'}</div>
            </div>
            <div class="badge-cluster">
              <span class="badge ${sentimentClass}">${sentiment} sentiment</span>
              <span class="badge badge-repeat">${d.status.replace('_', ' ')}</span>
            </div>
          </div>

          ${d.manual_review_reason ? `
            <div class="review-reason-banner">
              <span>⚠️</span>
              <span>${d.manual_review_reason}</span>
            </div>
          ` : ''}

          <!-- Cross-Sell Intelligence Breakdown -->
          <div class="cross-sell-intel">
            <div class="intel-row">
              <span class="intel-label">Purchased / Context:</span>
              <span class="intel-value">${firstMention ? (firstMention.product_name || firstMention.product_id) : 'Past Order History'}</span>
            </div>
            ${firstRec ? `
              <div class="intel-row">
                <span class="intel-label">Cross-Sell Recommended:</span>
                <span class="intel-value highlight">✨ ${firstRec.product_name || firstRec.product_id}</span>
              </div>
              <div class="intel-row">
                <span class="intel-label">Algorithm Reason:</span>
                <span class="intel-value" style="font-size: 11px; max-width: 70%;">${firstRec.reason || 'High correlation purchase'}</span>
              </div>
            ` : ''}
          </div>

          <!-- WhatsApp Chat Preview -->
          <div class="wa-preview-container">
            <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px; font-weight: 600;">WHATSAPP OUTBOUND DRAFT</div>
            <div class="wa-bubble">
              ${escapeHtml(displayMessage)}
              <div class="wa-bubble-meta">
                <span>${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                <span class="wa-checks">✓✓</span>
              </div>
            </div>
          </div>


          <!-- HITL Action Buttons -->
          ${isPending ? `
            <div class="draft-card-actions">
              <button class="btn btn-primary btn-sm btn-approve" data-id="${d.id}" data-customer="${d.customer_id}">
                <span>Approve & Send</span>
                <span>🚀</span>
              </button>
              <button class="btn btn-secondary btn-sm btn-edit" data-id="${d.id}">
                <span>Edit</span>
                <span>✏️</span>
              </button>
              <button class="btn btn-danger btn-sm btn-reject" data-id="${d.id}">
                <span>Reject</span>
                <span>🛑</span>
              </button>
            </div>
          ` : `
            <div style="font-size: 12px; color: var(--text-muted); padding-top: 6px;">
              Status: <strong style="color: var(--text-primary); text-transform: capitalize;">${d.status.replace('_', ' ')}</strong>
              ${d.sent_at ? ` · Sent at ${new Date(d.sent_at).toLocaleTimeString()}` : ''}
            </div>
          `}
        </div>
      `;
    }).join('');

    // Attach button events
    document.querySelectorAll('.btn-approve').forEach(b => {
      b.addEventListener('click', async () => {
        const id = b.getAttribute('data-id');
        await handleApprove(id);
      });
    });

    document.querySelectorAll('.btn-reject').forEach(b => {
      b.addEventListener('click', async () => {
        const id = b.getAttribute('data-id');
        await handleReject(id);
      });
    });

    document.querySelectorAll('.btn-edit').forEach(b => {
      b.addEventListener('click', () => {
        const id = b.getAttribute('data-id');
        const draft = activeDrafts.find(item => String(item.id) === String(id));
        if (draft) openEditModal(draft);
      });
    });
  }

  // ── Action Handlers ─────────────────────────────────────────────────────────
  async function handleApprove(draftId) {
    try {
      showToast(`Approving draft #${draftId}...`, 'info');
      const res = await fetch(`/api/drafts/${draftId}/approve`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Approval failed');

      showToast(`Draft #${draftId} approved and dispatched via WhatsApp!`, 'success');
      loadDrafts();
      loadStats();
    } catch (e) {
      showToast(`Failed to approve draft #${draftId}: ${e.message}`, 'error');
    }
  }


  async function handleReject(draftId) {
    try {
      const res = await fetch(`/api/drafts/${draftId}/reject`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Rejection failed');

      showToast(`Draft #${draftId} rejected. Pipeline halted.`, 'info');
      loadDrafts();
      loadStats();
    } catch (e) {
      showToast(`Failed to reject draft #${draftId}: ${e.message}`, 'error');
    }
  }

  // ── Edit Modal ──────────────────────────────────────────────────────────────
  function openEditModal(draft) {
    currentEditingDraft = draft;
    modalCustomerMeta.textContent = `${draft.customer_id} · Draft #${draft.id}`;
    const initialText = draft.final_message || draft.generated_message || '';
    modalEditTextarea.value = initialText;
    modalWaPreviewText.textContent = initialText;
    modalEditDraft.classList.add('open');
  }

  function closeEditModal() {
    modalEditDraft.classList.remove('open');
    currentEditingDraft = null;
  }

  modalEditTextarea.addEventListener('input', (e) => {
    modalWaPreviewText.textContent = e.target.value || 'Type message above...';
  });

  modalCloseBtn.addEventListener('click', closeEditModal);
  modalBtnCancel.addEventListener('click', closeEditModal);

  modalBtnSaveSend.addEventListener('click', async () => {
    if (!currentEditingDraft) return;
    const editedMsg = modalEditTextarea.value.trim();
    if (!editedMsg) {
      showToast('Message cannot be empty', 'error');
      return;
    }

    try {
      showToast(`Saving edits and dispatching for draft #${currentEditingDraft.id}...`, 'info');
      const res = await fetch(`/api/drafts/${currentEditingDraft.id}/edit`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ edited_message: editedMsg })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Edit failed');

      showToast(`Draft #${currentEditingDraft.id} updated and sent to WhatsApp!`, 'success');
      closeEditModal();
      loadDrafts();
      loadStats();
    } catch (e) {
      showToast(`Edit failed: ${e.message}`, 'error');
    }
  });

  // ── Trigger API 1: Data Ingestion ───────────────────────────────────────────
  btnRunIngest.addEventListener('click', async () => {
    const limit = parseInt(ingestLimitSelect.value, 10) || 10;
    btnRunIngest.disabled = true;
    btnRunIngest.innerHTML = `<span>Ingesting...</span><span class="pulse-dot"></span>`;
    ingestStatusMsg.innerHTML = `Running data pipeline for limit=${limit}...`;

    try {
      const res = await fetch('/api/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ingest failed');

      showToast(`Data Ingestion Completed! Batch ID: ${data.batch_id || 'OK'}`, 'success');
      ingestStatusMsg.innerHTML = `<span style="color: var(--accent-emerald);">✔ Batch ${data.batch_id || 'done'} completed.</span>`;
      loadStats();
      loadCustomers();
      loadOrders();
      loadDrafts();
    } catch (e) {
      showToast(`Ingestion failed: ${e.message}`, 'error');
      ingestStatusMsg.innerHTML = `<span style="color: var(--accent-rose);">✖ Error: ${e.message}</span>`;
    } finally {
      btnRunIngest.disabled = false;
      btnRunIngest.innerHTML = `<span>Run Ingest Pipeline</span><span>⚡</span>`;
    }
  });

  // ── Trigger API 2: LangGraph Cross-Sell Agent ────────────────────────────────
  btnRunCrossSell.addEventListener('click', async () => {
    const customerId = crossSellInput.value.trim();
    if (!customerId) {
      showToast('Please enter a valid customer phone number', 'error');
      return;
    }

    btnRunCrossSell.disabled = true;
    btnRunCrossSell.innerHTML = `<span>Executing...</span><span class="pulse-dot"></span>`;
    crossSellStatusMsg.innerHTML = `Evaluating past orders for <strong>${customerId}</strong>...`;

    try {
      const res = await fetch(`/api/run-cross-sell/${encodeURIComponent(customerId)}`, {
        method: 'POST'
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Cross-sell execution failed');

      showToast(`Cross-sell draft generated for ${customerId}. Awaiting HITL approval.`, 'success');
      crossSellStatusMsg.innerHTML = `<span style="color: var(--accent-emerald);">&#10004; Draft #${data.draft_id || 'new'} held for HITL review.</span>`;

      document.querySelector('[data-tab="tab-inbox"]').click();
      loadStats();
      loadDrafts();
    } catch (e) {
      resetPipeline();
      showToast(`Cross-sell failed: ${e.message}`, 'error');
      crossSellStatusMsg.innerHTML = `<span style="color: var(--accent-rose);">✖ Error: ${e.message}</span>`;
    } finally {
      btnRunCrossSell.disabled = false;
      btnRunCrossSell.innerHTML = `<span>Run LangGraph Agent</span><span>🔥</span>`;
    }
  });

  // Sample Chips
  document.querySelectorAll('.sample-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      crossSellInput.value = chip.getAttribute('data-phone');
      showToast(`Selected sample customer: ${crossSellInput.value}`, 'info');
    });
  });

  // ── Fetch Customers (Tab 2) ─────────────────────────────────────────────────
  async function loadCustomers() {
    try {
      const res = await fetch('/api/dashboard/customers');
      if (!res.ok) return;
      allCustomers = await res.json();
      renderCustomers(allCustomers);
    } catch (e) {
      console.warn('Failed to load customers', e);
    }
  }

  function renderCustomers(customers) {
    if (!customers || customers.length === 0) {
      customersTableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 30px;">No customers found.</td></tr>`;
      return;
    }

    customersTableBody.innerHTML = customers.map(c => `
      <tr data-id="${c.id}">
        <td style="font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #60a5fa;">${c.phone}</td>
        <td><strong>${c.name || 'Anna'}</strong></td>
        <td><span class="badge badge-${c.segment}">${c.segment}</span></td>
        <td><strong>${c.rfm_recency}d / ${c.rfm_frequency} orders</strong></td>
        <td>₹${Number(c.rfm_monetary || 0).toLocaleString()}</td>
        <td><span style="color: ${c.churn_risk === 'high' ? 'var(--accent-rose)' : 'var(--accent-emerald)'}; font-weight: 600;">${c.churn_risk.toUpperCase()}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm btn-cust-cross-sell" data-phone="${c.phone}">
            <span>Cross-Sell</span> ⚡
          </button>
        </td>
      </tr>
    `).join('');

    document.querySelectorAll('#customers-table-body tr').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.closest('.btn-cust-cross-sell')) return;
        const id = row.getAttribute('data-id');
        openCustomerDetail(id);
      });
    });

    document.querySelectorAll('.btn-cust-cross-sell').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const phone = btn.getAttribute('data-phone');
        crossSellInput.value = phone;
        btnRunCrossSell.click();
      });
    });
  }

  // Customer search filter
  customerSearch.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    if (!q) {
      renderCustomers(allCustomers);
      return;
    }
    const filtered = allCustomers.filter(c => 
      c.phone.toLowerCase().includes(q) ||
      c.name.toLowerCase().includes(q) ||
      c.segment.toLowerCase().includes(q)
    );
    renderCustomers(filtered);
  });

  // ── Customer Detail Modal ───────────────────────────────────────────────────
  async function openCustomerDetail(customerId) {
    selectedCustomerDetailId = customerId;
    custModalBody.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--text-muted);">Loading 360° profile for ${customerId}...</div>`;
    modalCustomerDetail.classList.add('open');

    try {
      const res = await fetch(`/api/dashboard/customer/${encodeURIComponent(customerId)}`);
      if (!res.ok) throw new Error('Customer data not found');
      const data = await res.json();
      const c = data.customer;
      const orders = data.orders || [];
      const messages = data.messages || [];

      document.getElementById('cust-modal-title').textContent = `Customer 360° · ${c.name || 'Anna'} (${c.phone})`;

      custModalBody.innerHTML = `
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; background: var(--bg-surface-elevated); padding: 16px; border-radius: var(--radius-md);">
          <div>
            <div style="font-size: 11px; color: var(--text-muted);">SEGMENT</div>
            <div style="font-size: 14px; font-weight: 700;"><span class="badge badge-${c.segment}">${c.segment}</span></div>
          </div>
          <div>
            <div style="font-size: 11px; color: var(--text-muted);">TOTAL SPEND</div>
            <div style="font-size: 14px; font-weight: 700; color: var(--accent-emerald);">₹${Number(c.rfm_monetary || 0).toLocaleString()}</div>
          </div>
          <div>
            <div style="font-size: 11px; color: var(--text-muted);">CHURN RISK</div>
            <div style="font-size: 14px; font-weight: 700; color: ${c.churn_risk === 'high' ? 'var(--accent-rose)' : 'var(--accent-emerald)'};">${c.churn_risk.toUpperCase()}</div>
          </div>
        </div>

        <div>
          <h4 style="font-size: 14px; font-weight: 700; margin-bottom: 10px;">📦 Past Orders from Custom Layer (${orders.length})</h4>
          ${orders.length === 0 ? '<p style="font-size: 12px; color: var(--text-muted);">No orders synced yet.</p>' : `
            <div style="display: flex; flex-direction: column; gap: 8px;">
              ${orders.map(o => `
                <div style="background: var(--bg-surface-elevated); padding: 10px 14px; border-radius: 6px; font-size: 12px; display: flex; justify-content: space-between; align-items: center;">
                  <div>
                    <strong>Order #${o.id}</strong> · State: <span class="badge badge-repeat">${o.current_state}</span>
                    <div style="color: var(--text-muted); font-size: 11px;">
                      Items: ${o.raw_order_items.map(i => `${i.product_retailer_id} (qty: ${i.quantity})`).join(', ') || 'Standard supply'}
                    </div>
                  </div>
                  <strong style="color: var(--accent-emerald);">₹${Number(o.total_amount || 0).toLocaleString()}</strong>
                </div>
              `).join('')}
            </div>
          `}
        </div>

        <div>
          <h4 style="font-size: 14px; font-weight: 700; margin-bottom: 10px;">💬 Recent WhatsApp Chat Messages (${messages.length})</h4>
          ${messages.length === 0 ? '<p style="font-size: 12px; color: var(--text-muted);">No chat messages recorded.</p>' : `
            <div style="max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding: 10px; background: var(--wa-bg); border-radius: 8px;">
              ${messages.map(m => `
                <div style="background: var(--wa-bubble-in); color: #fff; padding: 8px 12px; border-radius: 8px; font-size: 12px; max-width: 80%;">
                  ${escapeHtml(m.text || '')}
                  <div style="font-size: 10px; color: var(--text-muted); text-align: right; margin-top: 2px;">${m.created_at ? new Date(m.created_at).toLocaleTimeString() : ''}</div>
                </div>
              `).join('')}
            </div>
          `}
        </div>
      `;
    } catch (e) {
      custModalBody.innerHTML = `<div style="color: var(--accent-rose); padding: 20px;">Error: ${e.message}</div>`;
    }
  }

  custModalCloseBtn.addEventListener('click', () => modalCustomerDetail.classList.remove('open'));
  custModalBtnClose.addEventListener('click', () => modalCustomerDetail.classList.remove('open'));

  custModalBtnCrossSell.addEventListener('click', () => {
    if (!selectedCustomerDetailId) return;
    modalCustomerDetail.classList.remove('open');
    crossSellInput.value = selectedCustomerDetailId;
    btnRunCrossSell.click();
  });

  // ── Fetch Synced Orders (Tab 3) ─────────────────────────────────────────────
  async function loadOrders() {
    try {
      const res = await fetch('/api/dashboard/orders');
      if (!res.ok) return;
      const orders = await res.json();

      if (!orders || orders.length === 0) {
        ordersTableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 30px;">No synced orders yet. Click "Run Ingest Pipeline" above to pull orders from Custom Layer.</td></tr>`;
        return;
      }

      ordersTableBody.innerHTML = orders.map(o => {
        const phone = o.phone_number || o.customer_id || 'Unknown';
        const items = o.raw_order_items || [];
        const itemsDisplay = items.length > 0
          ? items.map(i => `<code>${i.product_retailer_id || i.product_id}</code> (x${i.quantity || 1})`).join(', ')
          : 'Standard Order';

        return `
          <tr>
            <td style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #f59e0b;">#${o.id}</td>
            <td style="font-family: 'JetBrains Mono', monospace; color: #60a5fa; font-weight: 600;">${phone}</td>
            <td><span class="badge badge-new">${o.current_state || 'PENDING'}</span></td>
            <td style="font-weight: 700; color: var(--accent-emerald);">₹${Number(o.total_amount || 0).toLocaleString()}</td>
            <td style="font-size: 12px;">${itemsDisplay}</td>
            <td><span style="color: var(--accent-cyan); font-weight: 500;">Complementary Accessories</span></td>
            <td>
              <button class="btn btn-primary btn-sm btn-order-cross" data-phone="${phone}">Cross-Sell ⚡</button>
            </td>
          </tr>
        `;
      }).join('');

      document.querySelectorAll('.btn-order-cross').forEach(b => {
        b.addEventListener('click', () => {
          const phone = b.getAttribute('data-phone');
          if (phone) {
            crossSellInput.value = phone;
            btnRunCrossSell.click();
          }
        });
      });
    } catch (e) {
      console.warn('Orders tab error', e);
    }
  }


  // ── Tab Switching ───────────────────────────────────────────────────────────
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');

      btn.classList.add('active');
      const targetTab = document.getElementById(btn.getAttribute('data-tab'));
      if (targetTab) targetTab.style.display = 'block';

      if (btn.getAttribute('data-tab') === 'tab-customers') loadCustomers();
      if (btn.getAttribute('data-tab') === 'tab-orders') loadOrders();
    });
  });

  // Filter Buttons
  document.querySelectorAll('.filter-btn').forEach(fb => {
    fb.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      fb.classList.add('active');
      currentFilter = fb.getAttribute('data-status');
      loadDrafts();
    });
  });

  document.getElementById('btn-refresh-drafts').addEventListener('click', loadDrafts);

  const btnClearMock = document.getElementById('btn-clear-mock');
  if (btnClearMock) {
    btnClearMock.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to remove all legacy mock drafts?')) return;
      try {
        const res = await fetch('/review/drafts/mock', { method: 'DELETE' });
        const data = await res.json();
        showToast(`Cleared ${data.deleted || 0} mock drafts. Inbox is clean!`, 'success');
        loadDrafts();
        loadStats();
      } catch (e) {
        showToast(`Failed to clear mock drafts: ${e.message}`, 'error');
      }
    });
  }


  // Utility
  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initial Load
  loadStats();
  loadDrafts();
  loadCustomers();
});
