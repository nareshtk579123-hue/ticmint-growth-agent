// Ticmint Growth Agent Frontend Controller

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const runBtn = document.getElementById('run-agent-btn');
  const btnIcon = document.getElementById('btn-icon');
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
  const filterChips = document.querySelectorAll('.category-filter-chips .chip');

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
        document.getElementById('llm-model-text').textContent = data.gemini_model;
      }
      if (data.has_google_auth) {
        document.getElementById('sheet-status-text').textContent = 'Connected (Live)';
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
    kpiQualified.textContent = leads.length;
    const high = leads.filter(l => l.priority === 'HIGH').length;
    kpiHighPriority.textContent = high;
  }

  // 4. Render Lead Cards
  function renderLeads() {
    leadsGrid.innerHTML = '';

    const filtered = currentFilter === 'all'
      ? allLeads
      : allLeads.filter(l => l.complaint_category === currentFilter);

    if (filtered.length === 0) {
      leadsGrid.innerHTML = `
        <div class="empty-state glass-card">
          <div class="empty-icon">🔍</div>
          <h3>No leads matching filter '${currentFilter}'</h3>
          <p>Change your filter or launch a new run to discover fresh opportunities.</p>
        </div>
      `;
      return;
    }

    filtered.forEach((lead, idx) => {
      const card = document.createElement('div');
      card.className = 'lead-card glass-card';
      const isHigh = lead.priority === 'HIGH';
      const categoryLabel = (lead.complaint_category || 'general').replace(/_/g, ' ');

      card.innerHTML = `
        <div class="lead-card-header">
          <div class="lead-meta">
            <div class="lead-author">
              @${escapeHtml(lead.author)}
              <span class="source-badge">${escapeHtml(lead.source)}</span>
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
          <div class="draft-label">Personalized Outreach Draft (Evidence-Grounded)</div>
          <p class="draft-text">${escapeHtml(lead.outreach_draft || 'No draft generated.')}</p>
        </div>

        <div class="lead-card-actions">
          <button class="copy-draft-btn" data-draft="${encodeURIComponent(lead.outreach_draft || '')}">
            📋 Copy Outreach Draft
          </button>
          ${lead.source_url ? `<a href="${lead.source_url}" target="_blank" class="open-source-btn">View Source Thread ↗</a>` : ''}
        </div>
      `;
      leadsGrid.appendChild(card);
    });

    // Attach Copy Handlers
    document.querySelectorAll('.copy-draft-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const text = decodeURIComponent(e.currentTarget.getAttribute('data-draft'));
        navigator.clipboard.writeText(text).then(() => {
          showToast('Outreach draft copied to clipboard!');
          const prev = btn.textContent;
          btn.textContent = '✓ Copied!';
          setTimeout(() => btn.textContent = prev, 2000);
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

    // Append to Terminal Body
    if (msg) {
      appendTerminalLog(type, msg);
    }

    // Handle Specific Events
    if (type === 'run_started') {
      setRunningState(true);
      setActiveStep(1);
      appendTerminalLog('system', `▶ Execution Run Started [${data.payload?.run_id}]`);
    } else if (type === 'mcp_connected') {
      setActiveStep(2);
      appendTerminalLog('info', `[MCP] Server Handshake Complete. Tools: ${data.payload?.tools?.join(', ')}`);
    } else if (type === 'query_completed') {
      kpiIngested.textContent = data.payload?.total_pool || 0;
      appendTerminalLog('info', `[DISCOVERY] ${data.payload?.query} -> ${data.payload?.count} items.`);
    } else if (type === 'dedup_completed') {
      setActiveStep(3);
      kpiDuplicates.textContent = data.payload?.duplicates_filtered || 0;
      appendTerminalLog('highlight', `[DEDUP] ${data.payload?.unique_count} unique discussions retained (${data.payload?.duplicates_filtered} duplicates stripped).`);
    } else if (type === 'analysis_started') {
      setActiveStep(4);
      appendTerminalLog('info', `[GEMINI] LLM intent classification & pain point extraction active...`);
    } else if (type === 'signal_evaluated') {
      setActiveStep(5);
      const isQual = data.payload?.is_qualified;
      const author = data.payload?.author;
      const score = data.payload?.score;
      const tier = data.payload?.priority;
      const cat = data.payload?.category;

      appendTerminalLog(
        isQual ? 'success' : 'system',
        `[EVAL] @${author}: ${score}/100 [${tier}] Category: ${cat} -> ${isQual ? 'QUALIFIED' : 'FILTERED'}`
      );

      // If qualified, prepend to live leads array
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
      appendTerminalLog('highlight', `[SHEETS] Synchronizing qualified leads to Google Sheets...`);
    } else if (type === 'sheet_sync_completed') {
      const res = data.payload?.result || {};
      appendTerminalLog('success', `[SHEETS] Upsert complete: ${res.inserted || 0} inserted, ${res.updated || 0} updated in-place.`);
    } else if (type === 'run_completed') {
      setRunningState(false);
      markAllStepsCompleted();
      appendTerminalLog('success', `✔ [COMPLETE] Growth listener run finished successfully!`);
      showToast('Growth Listener Run Complete! Google Sheets updated.');
      loadLeads();
    } else if (type === 'run_failed') {
      setRunningState(false);
      executionBadge.textContent = 'FAILED';
      executionBadge.className = 'status-indicator-badge';
      appendTerminalLog('error', `✖ [ERROR] Run failed: ${data.error}`);
    }
  }

  // 7. Stepper UI Helper
  function setActiveStep(stepNum) {
    for (let i = 1; i <= 6; i++) {
      const node = document.getElementById(`step-${i}`);
      const line = document.getElementById(`line-${i}`);
      if (i < stepNum) {
        node.className = 'step-node completed';
        if (line) line.style.background = '#10b981';
      } else if (i === stepNum) {
        node.className = 'step-node active';
        if (line) line.style.background = 'rgba(0, 242, 254, 0.4)';
      } else {
        node.className = 'step-node';
        if (line) line.style.background = 'rgba(255, 255, 255, 0.1)';
      }
    }
  }

  function markAllStepsCompleted() {
    for (let i = 1; i <= 6; i++) {
      const node = document.getElementById(`step-${i}`);
      const line = document.getElementById(`line-${i}`);
      node.className = 'step-node completed';
      if (line) line.style.background = '#10b981';
    }
  }

  // 8. Progress Bar & Status Helpers
  function updateProgressBar(percent, message, stage) {
    const cleanPercent = Math.min(Math.max(percent || 0, 0), 100);
    progressBarFill.style.width = `${cleanPercent}%`;
    progressPercentLabel.textContent = `${cleanPercent}%`;

    if (message) {
      liveStatusMessage.textContent = message;
    }

    if (stage) {
      stageTitle.textContent = formatStageTitle(stage);
    }
  }

  function formatStageTitle(stage) {
    const map = {
      'idle': 'Ready to Scan Public Communities',
      'starting': 'Initializing Agent Process...',
      'mcp_handshake': 'Handshake with MCP Server...',
      'querying_sources': 'Scanning Hacker News & Public RSS...',
      'deduplicating': 'Canonical Deduplication (SHA256)...',
      'ai_analysis': 'Gemini 3.8 Flash Intent Classification...',
      'google_sheets_sync': 'Idempotent Google Sheets Synchronization...',
      'completed': 'Agent Run Completed Successfully',
      'failed': 'Execution Interrupted',
    };
    return map[stage] || stage;
  }

  function setRunningState(running) {
    isRunning = running;
    if (running) {
      runBtn.classList.add('running');
      btnIcon.textContent = '⏳';
      btnText.textContent = 'Listener Running...';
      executionBadge.textContent = 'RUNNING';
      executionBadge.className = 'status-indicator-badge running';
    } else {
      runBtn.classList.remove('running');
      btnIcon.textContent = '▶';
      btnText.textContent = 'Launch Growth Listener Run';
      executionBadge.textContent = 'COMPLETED';
      executionBadge.className = 'status-indicator-badge completed';
    }
  }

  function appendTerminalLog(type, text) {
    const line = document.createElement('div');
    line.className = `terminal-line ${type}`;
    const time = new Date().toLocaleTimeString('en-GB');
    line.textContent = `[${time}] ${text}`;
    terminalBody.appendChild(line);
    terminalBody.scrollTop = terminalBody.scrollHeight;
  }

  // 9. Toast Helper
  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3500);
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
  runBtn.addEventListener('click', async () => {
    if (isRunning) return;

    const query = querySelect.value;
    const limit = parseInt(limitSelect.value, 10);

    setRunningState(true);
    updateProgressBar(5, 'Triggering agent run...', 'starting');
    appendTerminalLog('system', `[ACTION] User triggered run (Limit: ${limit}, Query: '${query || 'Default'}')`);

    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query, limit: limit }),
      });
      const data = await res.json();
      if (data.status === 'busy') {
        showToast('Agent is already running!');
      }
    } catch (e) {
      appendTerminalLog('error', `Trigger failed: ${e.message}`);
      setRunningState(false);
    }
  });

  clearTerminalBtn.addEventListener('click', () => {
    terminalBody.innerHTML = '<div class="terminal-line system">[SYSTEM] Terminal logs cleared.</div>';
  });

  filterChips.forEach(chip => {
    chip.addEventListener('click', (e) => {
      filterChips.forEach(c => c.classList.remove('active'));
      e.target.classList.add('active');
      currentFilter = e.target.getAttribute('data-filter');
      renderLeads();
    });
  });

  // Initialization
  loadConfig();
  loadLeads();
  connectEventStream();
});
