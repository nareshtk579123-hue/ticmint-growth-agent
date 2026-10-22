// Ticmint Growth Agent Frontend Controller
// Natural Light Blue Theme — Clean Real-Time Dashboard (Zero Emojis)

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const runBtn = document.getElementById('run-agent-btn');
  const btnSpinner = document.getElementById('btn-spinner');
  const btnIconWrapper = document.getElementById('btn-icon-wrapper');
  const btnText = document.getElementById('btn-text');
  const querySelect = document.getElementById('query-select');
  const limitSelect = document.getElementById('limit-select');
  const progressBarFill = document.getElementById('progress-bar-fill');
  const progressPercentLabel = document.getElementById('progress-percent-label');
  const executionBadge = document.getElementById('execution-badge');
  const stageTitle = document.getElementById('stage-title');
  const liveStatusMessage = document.getElementById('live-status-message');
  const terminalBody = document.getElementById('terminal-body');
  const clearTerminalBtn = document.getElementById('clear-terminal-btn');
  const leadsGrid = document.getElementById('leads-grid');
  const sheetLink = document.getElementById('sheet-link');
  const toast = document.getElementById('toast');
  const filterPills = document.querySelectorAll('.filter-pill');

  // KPI Elements
  const kpiIngested = document.getElementById('kpi-ingested');
  const kpiDuplicates = document.getElementById('kpi-duplicates');
  const kpiQualified = document.getElementById('kpi-qualified');
  const kpiHighPriority = document.getElementById('kpi-high-priority');

  let currentFilter = 'all';
  let allLeads = [];
  let isRunning = false;

  // 1. Load Initial Configuration
  async function loadConfig() {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      if (data.spreadsheet_url) {
        sheetLink.href = data.spreadsheet_url;
      }
      if (data.gemini_model) {
        const modelEl = document.getElementById('llm-model-text');
        if (modelEl) modelEl.textContent = data.gemini_model;
      }
      if (data.has_google_auth) {
        const sheetEl = document.getElementById('sheet-status-text');
        if (sheetEl) sheetEl.textContent = 'Connected (Live)';
      }
    } catch (e) {
      console.warn('Config fetch error:', e);
    }
  }

  // 2. Load Existing Leads
  async function loadLeads() {
    try {
      const res = await fetch('/api/leads');
      const data = await res.json();
      allLeads = data.leads || [];
      updateKPIs(allLeads);
      renderLeads();
    } catch (e) {
      console.warn('Leads fetch error:', e);
    }
  }

  // 3. Update KPI Counters
  function updateKPIs(leads) {
    if (kpiQualified) kpiQualified.textContent = leads.length;
    const high = leads.filter(l => l.priority === 'HIGH').length;
    if (kpiHighPriority) kpiHighPriority.textContent = high;
  }

  // 4. Render Lead Cards
  function renderLeads() {
    if (!leadsGrid) return;
    leadsGrid.innerHTML = '';

    const filtered = currentFilter === 'all'
      ? allLeads
      : allLeads.filter(l => l.complaint_category === currentFilter);

    if (filtered.length === 0) {
      leadsGrid.innerHTML = `
        <div class="empty-state-box">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="empty-icon-svg">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <div class="empty-title">No leads matching filter '${escapeHtml(currentFilter)}'</div>
          <div class="empty-sub">Select another filter pill or trigger "Run Listener" to scan public sources.</div>
        </div>
      `;
      return;
    }

    filtered.forEach((lead) => {
      const card = document.createElement('div');
      const isHigh = lead.priority === 'HIGH';
      card.className = `lead-card ${isHigh ? 'high-priority' : ''}`;
      const categoryLabel = (lead.complaint_category || 'general').replace(/_/g, ' ');

      card.innerHTML = `
        <div class="lead-card-header">
          <div class="lead-meta">
            <div class="lead-author">
              @${escapeHtml(lead.author)}
              <span class="source-badge">${escapeHtml(lead.source || 'public')}</span>
            </div>
            <span class="lead-category-tag">${categoryLabel}</span>
          </div>
          <div class="score-badge-circle ${isHigh ? 'high' : 'medium'}">
            <span class="score-number">${lead.lead_score}</span>
            <span class="score-tier">${lead.priority}</span>
          </div>
        </div>

        <div class="evidence-box">
          "${escapeHtml(lead.evidence_quote || 'Specific ticketing pain cited')}"
        </div>

        <div class="draft-box">
          <div class="draft-label">Personalized Outreach Draft</div>
          <p class="draft-text">${escapeHtml(lead.outreach_draft || 'No draft generated.')}</p>
        </div>

        <div class="lead-card-actions">
          <button class="copy-draft-btn" data-draft="${encodeURIComponent(lead.outreach_draft || '')}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <span>Copy Draft</span>
          </button>
          ${lead.source_url ? `
            <a href="${escapeHtml(lead.source_url)}" target="_blank" rel="noopener noreferrer" class="open-source-btn">
              <span>View Source</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                <polyline points="15 3 21 3 21 9"></polyline>
                <line x1="10" y1="14" x2="21" y2="3"></line>
              </svg>
            </a>
          ` : ''}
        </div>
      `;
      leadsGrid.appendChild(card);
    });

    // Attach Copy Handlers
    leadsGrid.querySelectorAll('.copy-draft-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const text = decodeURIComponent(btn.getAttribute('data-draft'));
        navigator.clipboard.writeText(text).then(() => {
          showToast('Outreach draft copied to clipboard');
          const originalHtml = btn.innerHTML;
          btn.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <span>Copied</span>
          `;
          setTimeout(() => {
            btn.innerHTML = originalHtml;
          }, 2000);
        });
      });
    });
  }

  // 5. Connect Server-Sent Events (SSE) Stream
  function connectEventStream() {
    const evtSource = new EventSource('/api/events');

    evtSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleStreamEvent(payload.event, payload.data);
      } catch (e) {
        console.error('SSE JSON error:', e);
      }
    };

    evtSource.onerror = () => {
      console.warn('SSE disconnected. Reconnecting in 3s...');
      evtSource.close();
      setTimeout(connectEventStream, 3000);
    };
  }

  // 6. Handle Incoming Live Stream Events
  function handleStreamEvent(type, data) {
    if (type === 'initial_state') {
      if (data.is_running) {
        setRunningState(true);
      }
      updateProgressBar(data.progress_percent, data.status_message, data.current_stage);
      return;
    }

    const stage = data.stage || 'running';
    const progress = data.progress || 10;
    const msg = data.message || '';

    updateProgressBar(progress, msg, stage);

    if (msg) {
      appendTerminalLog(type, msg);
    }

    if (type === 'run_started') {
      setRunningState(true);
      setActiveStep(1);
      appendTerminalLog('system', `[RUN] Execution initiated (ID: ${data.payload?.run_id || 'active'})`);
    } else if (type === 'mcp_connected') {
      setActiveStep(2);
      appendTerminalLog('info', `[MCP] Server connected. Tools available: ${data.payload?.tools?.join(', ')}`);
    } else if (type === 'query_completed') {
      if (kpiIngested) kpiIngested.textContent = data.payload?.total_pool || 0;
      appendTerminalLog('info', `[DISCOVERY] ${data.payload?.query} -> ${data.payload?.count} raw discussion items found`);
    } else if (type === 'dedup_completed') {
      setActiveStep(3);
      if (kpiDuplicates) kpiDuplicates.textContent = data.payload?.duplicates_filtered || 0;
      appendTerminalLog('highlight', `[DEDUP] ${data.payload?.unique_count} unique items retained (${data.payload?.duplicates_filtered} duplicates filtered via canonical URL & SHA256)`);
    } else if (type === 'analysis_started') {
      setActiveStep(4);
      appendTerminalLog('info', `[ANALYSIS] Classifying organizer intent and extracting pain citations...`);
    } else if (type === 'signal_evaluated') {
      setActiveStep(5);
      const isQual = data.payload?.is_qualified;
      const author = data.payload?.author;
      const score = data.payload?.score;
      const tier = data.payload?.priority;
      const cat = data.payload?.category;

      appendTerminalLog(
        isQual ? 'success' : 'system',
        `[EVAL] @${author}: ${score}/100 [${tier}] ${cat} -> ${isQual ? 'QUALIFIED' : 'FILTERED'}`
      );

      if (isQual) {
        const existingIdx = allLeads.findIndex(l => l.author === author);
        const leadObj = {
          author: author,
          source: data.payload?.source || 'hacker_news',
          source_url: data.payload?.url || '',
          evidence_quote: data.payload?.quote || '',
          complaint_category: cat,
          lead_score: score,
          priority: tier,
          outreach_draft: data.payload?.draft || '',
        };

        if (existingIdx >= 0) {
          allLeads[existingIdx] = leadObj;
        } else {
          allLeads.unshift(leadObj);
        }
        updateKPIs(allLeads);
        renderLeads();
      }
    } else if (type === 'sheet_sync_started') {
      setActiveStep(6);
      appendTerminalLog('highlight', `[SHEETS] Synchronizing qualified records to Google Sheets...`);
    } else if (type === 'sheet_sync_completed') {
      const res = data.payload?.result || {};
      appendTerminalLog('success', `[SHEETS] Upsert complete: ${res.inserted || 0} inserted, ${res.updated || 0} updated in-place`);
    } else if (type === 'run_completed') {
      setRunningState(false);
      markAllStepsCompleted();
      appendTerminalLog('success', `[COMPLETE] Growth listener run finished successfully`);
      showToast('Growth listener run completed. Google Sheets updated.');
      loadLeads();
    } else if (type === 'run_failed') {
      setRunningState(false);
      if (executionBadge) {
        executionBadge.textContent = 'FAILED';
        executionBadge.className = 'status-pill-badge failed';
      }
      appendTerminalLog('error', `[ERROR] Run interrupted: ${data.error}`);
    }
  }

  // 7. Stepper UI Helper
  function setActiveStep(stepNum) {
    for (let i = 1; i <= 6; i++) {
      const node = document.getElementById(`step-${i}`);
      const line = document.getElementById(`line-${i}`);
      if (!node) continue;

      if (i < stepNum) {
        node.className = 'step-item completed';
        if (line) line.classList.add('completed');
      } else if (i === stepNum) {
        node.className = 'step-item active';
        if (line) line.classList.remove('completed');
      } else {
        node.className = 'step-item';
        if (line) line.classList.remove('completed');
      }
    }
  }

  function markAllStepsCompleted() {
    for (let i = 1; i <= 6; i++) {
      const node = document.getElementById(`step-${i}`);
      const line = document.getElementById(`line-${i}`);
      if (node) node.className = 'step-item completed';
      if (line) line.classList.add('completed');
    }
  }

  // 8. Progress Bar & Status Helpers
  function updateProgressBar(percent, message, stage) {
    const cleanPercent = Math.min(Math.max(percent || 0, 0), 100);
    if (progressBarFill) progressBarFill.style.width = `${cleanPercent}%`;
    if (progressPercentLabel) progressPercentLabel.textContent = `${cleanPercent}%`;

    if (message && liveStatusMessage) {
      liveStatusMessage.textContent = message;
    }

    if (stage && stageTitle) {
      stageTitle.textContent = formatStageTitle(stage);
    }
  }

  function formatStageTitle(stage) {
    const map = {
      'idle': 'System Ready',
      'starting': 'Initializing Agent Process...',
      'mcp_handshake': 'Handshake with MCP Server...',
      'querying_sources': 'Scanning Discussion Sources...',
      'deduplicating': 'Filtering Duplicate Signals...',
      'ai_analysis': 'Classifying Intent & Pain Points...',
      'google_sheets_sync': 'Synchronizing with Google Sheets...',
      'completed': 'Execution Completed',
      'failed': 'Execution Interrupted',
    };
    return map[stage] || stage;
  }

  function setRunningState(running) {
    isRunning = running;
    if (running) {
      if (runBtn) {
        runBtn.disabled = true;
      }
      if (btnSpinner) btnSpinner.style.display = 'inline-block';
      if (btnIconWrapper) btnIconWrapper.style.display = 'none';
      if (btnText) btnText.textContent = 'Running Listener...';
      if (executionBadge) {
        executionBadge.textContent = 'RUNNING';
        executionBadge.className = 'status-pill-badge running';
      }
    } else {
      if (runBtn) {
        runBtn.disabled = false;
      }
      if (btnSpinner) btnSpinner.style.display = 'none';
      if (btnIconWrapper) btnIconWrapper.style.display = 'inline-block';
      if (btnText) btnText.textContent = 'Run Listener';
      if (executionBadge) {
        executionBadge.textContent = 'COMPLETED';
        executionBadge.className = 'status-pill-badge completed';
      }
    }
  }

  function appendTerminalLog(type, text) {
    if (!terminalBody) return;
    const line = document.createElement('div');
    line.className = `console-line ${type}`;
    const time = new Date().toLocaleTimeString('en-GB');
    line.textContent = `[${time}] ${text}`;
    terminalBody.appendChild(line);
    terminalBody.scrollTop = terminalBody.scrollHeight;
  }

  // 9. Toast Helper
  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3200);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // 10. Event Listeners
  if (runBtn) {
    runBtn.addEventListener('click', async () => {
      if (isRunning) return;

      const query = querySelect ? querySelect.value : '';
      const limit = limitSelect ? parseInt(limitSelect.value, 10) : 10;

      setRunningState(true);
      updateProgressBar(5, 'Triggering agent run...', 'starting');
      appendTerminalLog('system', `[ACTION] User triggered run (Limit: ${limit}, Query: '${query || 'Default Target Queries'}')`);

      try {
        const res = await fetch('/api/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: query, limit: limit }),
        });
        const data = await res.json();
        if (data.status === 'busy') {
          showToast('Agent is currently running another task');
        }
      } catch (e) {
        appendTerminalLog('error', `Trigger failed: ${e.message}`);
        setRunningState(false);
      }
    });
  }

  if (clearTerminalBtn && terminalBody) {
    clearTerminalBtn.addEventListener('click', () => {
      terminalBody.innerHTML = '<div class="console-line system">[SYSTEM] Activity log cleared.</div>';
    });
  }

  filterPills.forEach(pill => {
    pill.addEventListener('click', (e) => {
      filterPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentFilter = pill.getAttribute('data-filter') || 'all';
      renderLeads();
    });
  });

  // Initialization
  loadConfig();
  loadLeads();
  connectEventStream();
});
