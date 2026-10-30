/**
 * Otis AI Companion - Lovelace Dashboard Card
 * Version: 1.9.4
 * 
 * An interactive, proactive smart home co-pilot card featuring:
 * - Frosted glassmorphism with Sky Cyan & Lavender Purple neon accents
 * - Live AI multi-agent status and health monitoring
 * - Proactive suggestions feed with category filter pills & 1-click coordinator execution
 * - Embedded Assist conversational co-pilot with quick prompt chips
 * - Multimodal Video-to-Floorplan SVG Parser & Interactive Viewer
 * - Phase 4 Visual Floor Plan Boundary & Marker Adjuster on Lovelace Canvas
 * - Smart Home Maturity Score & Media/Security Architecture Inspector
 */

const CARD_VERSION = "1.9.4";
console.info(
  `%c OTIS AI COMPANION CARD %c v${CARD_VERSION} `,
  "background: #0ea5e9; color: #fff; font-weight: bold; border-radius: 4px 0 0 4px; padding: 2px 6px;",
  "background: #1e293b; color: #38bdf8; font-weight: bold; border-radius: 0 4px 4px 0; padding: 2px 6px;"
);

class OtisCompanionCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._capabilityMap = null;
    this._suggestions = [];
    this._dismissedIds = this._loadDismissedIds();
    this._loadingSuggestions = false;
    this._applyingIds = new Set();
    this._chatMessages = this._loadChatMessages();
    this._isSendingChat = false;
    this._reasoningSteps = [];
    this._reasoningStartTime = null;
    this._reasoningTimer = null;
    this._activeReasoningStep = 0;
    this._expandedReasoningIds = new Set();
    this._unsubReasoningEvents = null;
    this._isListening = false;
    this._recognition = null;
    this._activeTab = this._loadActiveTab(); // 'suggestions' | 'chat' | 'capabilities' | 'floorplan'
    this._selectedCategory = "all"; // 'all' | 'lighting' | 'media' | 'security' | 'cleanup' | 'system'
    this._conversationId = null;
    this._conversationAgentId = null;
    this._cachedAgentId = null;
    this._draftChatText = "";
    this._previewDismissed = false;

    // Phase 6: Floorplan & Walkthrough state
    this._floorplanModalOpen = false;
    this._themeModalOpen = false;
    this._themeApplyScope = "current";
    this._generatingTheme = false;
    this._uploadingVideo = false;
    this._uploadProgressText = "";
    this._floorplanSvg = null;
    this._loadingFloorplan = false;
    try {
      this._selectedFloorZone = localStorage.getItem("otis_floorplan_selected_zone") || "all";
    } catch (_) {
      this._selectedFloorZone = "all";
    }
    this._selectedRoomInfo = null;
    this._spokenOrderOverride = "";
    this._selectedWalkthroughFiles = [];
    this._discoveredWalkthroughAreas = [];
    this._hasWalkthrough = false;
    this._hasFloorplan = false;

    // Phase 4: Visual Floor Plan Boundary & Marker Adjuster Canvas Editor
    this._editorActive = false;
    this._dirtyBadges = {};
    this._dirtyRooms = {};
    this._selectedEditorRoomId = null;
    this._resizingHandle = null;
    this._hasUnsavedLayout = false;
    this._savingLayout = false;
    this._addMarkerModalOpen = false;
  }

  _loadActiveTab() {
    try {
      const saved = sessionStorage.getItem("otis_active_tab");
      if (saved && ["suggestions", "chat", "capabilities", "floorplan"].includes(saved)) {
        return saved;
      }
    } catch (_) {}
    return "suggestions";
  }

  _saveActiveTab(tab) {
    if (["suggestions", "chat", "capabilities", "floorplan"].includes(tab)) {
      this._activeTab = tab;
      try {
        sessionStorage.setItem("otis_active_tab", tab);
      } catch (_) {}
    }
  }

  _loadChatMessages() {
    try {
      const saved = sessionStorage.getItem("otis_chat_messages");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch (_) {}
    return [];
  }

  _saveChatMessages() {
    try {
      sessionStorage.setItem("otis_chat_messages", JSON.stringify(this._chatMessages.slice(-50)));
    } catch (_) {}
  }

  _escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  _getRoomEmoji(name) {
    const k = String(name || "").toLowerCase();
    if (k.includes("office") || k.includes("study") || k.includes("desk") || k.includes("work")) return "💼";
    if (k.includes("theater") || k.includes("cinema") || k.includes("media")) return "🎬";
    if (k.includes("backyard") || k.includes("patio") || k.includes("deck") || k.includes("yard") || k.includes("garden")) return "🌳";
    if (k.includes("frontyard") || k.includes("driveway") || k.includes("porch")) return "🏡";
    if (k.includes("bath") || k.includes("shower") || k.includes("restroom") || k.includes("powder")) return "🚿";
    if (k.includes("gym") || k.includes("fitness") || k.includes("workout")) return "🏋️";
    if (k.includes("garage") || k.includes("workshop")) return "🚗";
    if (k.includes("great room") || k.includes("living") || k.includes("family") || k.includes("lounge")) return "🛋️";
    if (k.includes("master") || k.includes("bed") || k.includes("guest")) return "🛏️";
    if (k.includes("kitchen")) return "🍳";
    if (k.includes("dining")) return "🍽️";
    if (k.includes("laundry") || k.includes("mudroom")) return "🧺";
    if (k.includes("hallway") || k.includes("corridor") || k.includes("foyer") || k.includes("entry")) return "🚪";
    if (k.includes("pool") || k.includes("spa")) return "🏊";
    return "📍";
  }

  _ensureValidActiveTab() {
    if (this._activeTab === "suggestions" && this._config.show_suggestions === false) {
      this._activeTab = this._config.show_chat !== false ? "chat" : "floorplan";
    } else if (this._activeTab === "chat" && this._config.show_chat === false) {
      this._activeTab = this._config.show_suggestions !== false ? "suggestions" : "floorplan";
    }
    this._saveActiveTab(this._activeTab);
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Load initial capability map and suggestions if not loaded
    if (!oldHass && hass) {
      this._fetchData();
      this._subscribeReasoningEvents();
    }
  }

  disconnectedCallback() {
    if (this._unsubReasoningEvents) {
      try {
        this._unsubReasoningEvents();
      } catch (_) {}
      this._unsubReasoningEvents = null;
    }
    if (this._reasoningTimer) {
      clearInterval(this._reasoningTimer);
      this._reasoningTimer = null;
    }
  }

  async _subscribeReasoningEvents() {
    if (this._unsubReasoningEvents) return;
    try {
      if (this._hass && this._hass.connection && typeof this._hass.connection.subscribeEvents === "function") {
        this._unsubReasoningEvents = await this._hass.connection.subscribeEvents((ev) => {
          this._handleReasoningEvent(ev?.data);
        }, "otis_ai_reasoning_step");
      }
    } catch (e) {
      console.debug("Could not subscribe to otis_ai_reasoning_step events:", e);
    }
  }

  _handleReasoningEvent(data) {
    if (!data || !this._isSendingChat) return;
    if (data.conversation_id && this._conversationId && data.conversation_id !== this._conversationId) {
      return;
    }
    const elapsed = this._reasoningStartTime ? ((Date.now() - this._reasoningStartTime) / 1000).toFixed(1) : "0.0";
    const stepId = data.step || "step_" + Date.now();
    const title = data.title || "Processing";
    const detail = data.detail || "";

    const existingIdx = this._reasoningSteps.findIndex((s) => s.id === stepId);
    if (existingIdx !== -1) {
      this._reasoningSteps[existingIdx].status = "active";
      if (detail) this._reasoningSteps[existingIdx].detail = detail;
      if (title) this._reasoningSteps[existingIdx].title = title;
      for (let i = 0; i < existingIdx; i++) {
        this._reasoningSteps[i].status = "done";
        if (!this._reasoningSteps[i].time) this._reasoningSteps[i].time = `${elapsed}s`;
      }
      this._activeReasoningStep = existingIdx;
    } else {
      if (this._reasoningSteps.length > 0) {
        this._reasoningSteps[this._reasoningSteps.length - 1].status = "done";
        if (!this._reasoningSteps[this._reasoningSteps.length - 1].time) {
          this._reasoningSteps[this._reasoningSteps.length - 1].time = `${elapsed}s`;
        }
      }
      this._reasoningSteps.push({
        id: stepId,
        title,
        detail,
        status: "active",
        time: "",
      });
      this._activeReasoningStep = this._reasoningSteps.length - 1;
    }
    this._updateThinkingDisplay(elapsed);
  }

  _advanceReasoningStep(targetIdx, elapsed) {
    if (!this._reasoningSteps || targetIdx >= this._reasoningSteps.length) return;
    for (let i = 0; i < targetIdx; i++) {
      if (this._reasoningSteps[i]) {
        this._reasoningSteps[i].status = "done";
        if (!this._reasoningSteps[i].time) {
          this._reasoningSteps[i].time = `${elapsed.toFixed(1)}s`;
        }
      }
    }
    if (this._reasoningSteps[targetIdx]) {
      this._reasoningSteps[targetIdx].status = "active";
    }
    this._activeReasoningStep = targetIdx;
  }

  _getCurrentThinkingTitle() {
    if (!this._reasoningSteps || this._reasoningSteps.length === 0) return "Analyzing request";
    const active = this._reasoningSteps.find((s) => s.status === "active") || this._reasoningSteps[this._reasoningSteps.length - 1];
    return active ? active.title : "Analyzing request";
  }

  _getCurrentThinkingStatus() {
    if (!this._reasoningSteps || this._reasoningSteps.length === 0) return "Evaluating home state...";
    const active = this._reasoningSteps.find((s) => s.status === "active") || this._reasoningSteps[this._reasoningSteps.length - 1];
    return active ? active.detail || active.title : "Formulating response...";
  }

  _renderThinkingStepsStream() {
    if (!this._reasoningSteps || this._reasoningSteps.length === 0) return "";
    return this._reasoningSteps
      .map((s) => {
        const isDone = s.status === "done";
        const isActive = s.status === "active";
        return `
          <div class="thinking-step-row ${s.status}">
            <span class="step-indicator ${s.status}">
              ${
                isDone
                  ? "✓"
                  : isActive
                  ? `<span class="step-mini-spinner"></span>`
                  : "○"
              }
            </span>
            <div class="step-info">
              <span class="step-name ${s.status}">${this._escapeHtml(s.title)}</span>
              ${s.detail ? `<span class="step-sub ${s.status}">${this._escapeHtml(s.detail)}</span>` : ""}
            </div>
            ${s.time ? `<span class="step-badge">${this._escapeHtml(s.time)}</span>` : ""}
          </div>
        `;
      })
      .join("");
  }

  _updateThinkingDisplay(elapsed) {
    const root = this.shadowRoot;
    if (!root) return;

    const timerEl = root.querySelector("#thinking-elapsed-timer");
    if (timerEl) {
      const secStr = typeof elapsed === "number" ? elapsed.toFixed(1) : elapsed;
      timerEl.textContent = `⏱️ ${secStr}s`;
    }

    const stageEl = root.querySelector("#thinking-stage-text");
    if (stageEl) {
      stageEl.textContent = this._getCurrentThinkingStatus();
    }

    const bannerTitle = root.querySelector("#thinking-banner-title");
    if (bannerTitle) {
      bannerTitle.textContent = `Otis is reasoning: ${this._getCurrentThinkingTitle()}`;
    }

    const bannerSub = root.querySelector("#thinking-banner-sub");
    if (bannerSub) {
      bannerSub.textContent = this._getCurrentThinkingStatus();
    }

    const streamEl = root.querySelector("#thinking-steps-stream");
    if (streamEl) {
      streamEl.innerHTML = this._renderThinkingStepsStream();
    }
  }

  setConfig(config) {
    if (!config) {
      throw new Error("Invalid configuration");
    }
    this._config = {
      title: "Otis AI Companion",
      theme_preset: "ha_native", // 'ha_native' | 'cyberpunk' | 'midnight' | 'emerald' | 'sunset' | 'light_frost'
      show_chat: true,
      show_suggestions: true,
      show_stats: true,
      max_suggestions: 5,
      ...config,
    };
    if (config.default_tab) {
      this._activeTab = config.default_tab;
      this._saveActiveTab(config.default_tab);
    } else if (config.mode === "floorplan_studio") {
      this._activeTab = "floorplan";
      this._saveActiveTab("floorplan");
    } else {
      this._activeTab = this._loadActiveTab();
    }
    this._ensureValidActiveTab();
    this._render();
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return {
      type: "custom:otis-companion-card",
      title: "Otis AI Companion",
      theme_preset: "ha_native",
      show_chat: true,
      show_suggestions: true,
      show_stats: true,
      max_suggestions: 5,
    };
  }

  static async getConfigElement() {
    return document.createElement("otis-companion-card-editor");
  }

  async _fetchData() {
    if (!this._hass) return;
    this._loadingSuggestions = true;
    this._render();

    try {
      // Call get_capability_map service
      const res = await this._hass.callService("otis_ai", "get_capability_map", {}, undefined, true, true);
      const capMap = res?.response || res || {};
      this._capabilityMap = capMap;
      if (capMap.conversation_agent_id) {
        this._conversationAgentId = capMap.conversation_agent_id;
      }
      this._suggestions = capMap.proactive_suggestions || [];
      this._hasWalkthrough = Boolean(capMap.floorplan?.walkthrough_completed);
      this._hasFloorplan = Boolean(capMap.floorplan?.exists);

      // Load floorplan SVG if exists
      if (capMap.floorplan?.exists && !this._floorplanSvg && !this._loadingFloorplan) {
        this._loadFloorplanSvg(capMap.floorplan.url);
      }
    } catch (err) {
      console.warn("Otis Companion Card: Could not fetch capability map directly, attempting get_suggestions:", err);
      try {
        const sRes = await this._hass.callService("otis_ai", "get_suggestions", {}, undefined, true, true);
        this._suggestions = sRes?.response?.suggestions || [];
      } catch (e2) {
        console.error("Otis Companion Card: Failed to fetch suggestions:", e2);
      }
    } finally {
      this._loadingSuggestions = false;
      this._render();
    }
  }

  async _loadFloorplanSvg(url) {
    if (!url) return;
    this._loadingFloorplan = true;
    try {
      const fetchUrl = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
      const resp = await fetch(fetchUrl);
      if (resp.ok) {
        let rawSvg = await resp.text();
        // Client-side sanitizer for any corrupted <text> elements where attributes leaked into text content
        rawSvg = rawSvg.replace(
          /<text\b([^>]*)class="([^"]*(?:room-header|room-label|subzone-pill)[^"]*)"([^>]*)>(.*?)<\/text>/gi,
          (fullMatch, preAttrs, clsName, postAttrs, content) => {
            const allAttrs = `${preAttrs} ${postAttrs}`;
            const xm = allAttrs.match(/x="([0-9.]+)"/) || content.match(/x="([0-9.]+)"/);
            const ym = allAttrs.match(/y="([0-9.]+)"/) || content.match(/y="([0-9.]+)"/);
            const xVal = xm ? xm[1] : "40";
            const yVal = ym ? ym[1] : "40";
            const cleanContent = content.replace(/^(?:\s*(?:x|y)="[^"]*"[>\s]*)+/g, "").trim();
            return `<text x="${xVal}" y="${yVal}" class="${clsName}">${cleanContent}</text>`;
          }
        );
        this._floorplanSvg = rawSvg;
      }
    } catch (err) {
      console.warn("Could not load floorplan SVG:", err);
    } finally {
      this._loadingFloorplan = false;
      this._render();
    }
  }

  async _generateFloorplanDirect(spokenOrder) {
    if (!this._hass) return;
    this._uploadingVideo = true;
    this._uploadProgressText = "Synthesizing vector floor plan from Home Assistant registry...";
    this._render();

    try {
      const payload = {};
      if (spokenOrder && spokenOrder.trim()) {
        payload.spoken_order = spokenOrder.trim();
      }
      const res = await this._hass.callService("otis_ai", "generate_floorplan", payload, undefined, true, true);
      const data = res?.response || res || {};
      if (data.success) {
        this._showToast(`Generated floor plan with ${data.room_count || "multiple"} rooms!`);
        this._floorplanModalOpen = false;
        this._activeTab = "floorplan";
        this._floorplanSvg = null;
        await this._fetchData();
        if (data.url) {
          await this._loadFloorplanSvg(data.url);
        }
      } else {
        this._showToast(data.error || "Failed to generate floor plan", true);
      }
    } catch (err) {
      console.error("Error generating floorplan:", err);
      this._showToast("Error generating floorplan. Check HA logs.", true);
    } finally {
      this._uploadingVideo = false;
      this._uploadProgressText = "";
      this._render();
    }
  }

  _updateWalkthroughProgressDom(stageText, discoveredList) {
    this._uploadProgressText = stageText;
    if (Array.isArray(discoveredList)) {
      this._discoveredWalkthroughAreas = discoveredList;
    }
    const root = this.shadowRoot;
    if (!root) return;
    const statusEl = root.querySelector("#walkthrough-status-text");
    if (statusEl) {
      statusEl.textContent = stageText;
    }
    const listEl = root.querySelector("#walkthrough-discovered-list");
    if (listEl && Array.isArray(this._discoveredWalkthroughAreas)) {
      listEl.innerHTML = this._discoveredWalkthroughAreas
        .map(
          (name) =>
            `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:999px;background:rgba(14,165,233,0.16);border:1px solid rgba(56,189,248,0.4);color:#e0f2fe;font-size:0.72rem;font-weight:600;">✓ Discovered ${name}</span>`
        )
        .join("");
    }
  }

  async _uploadWalkthroughVideo(filesOrFile, spokenOrder) {
    const fileList = Array.isArray(filesOrFile)
      ? filesOrFile
      : filesOrFile
      ? [filesOrFile]
      : [];
    if (fileList.length === 0) return;

    this._uploadingVideo = true;
    this._discoveredWalkthroughAreas = [];
    this._uploadProgressText = "Uploading videos";
    this._render();

    const shownSet = new Set();
    const pollTimer = setInterval(async () => {
      try {
        const stResp = await fetch("/api/otis_ai/upload_walkthrough", { method: "GET" });
        if (stResp.ok) {
          const st = await stResp.json();
          if (Array.isArray(st.discovered_areas)) {
            st.discovered_areas.forEach((n) => shownSet.add(n));
          }
          if (st.stage && st.stage !== "Idle") {
            this._updateWalkthroughProgressDom(st.stage, Array.from(shownSet));
          }
        }
      } catch (_e) {
        // Ignore transient poll errors during upload
      }
    }, 350);

    try {
      const formData = new FormData();
      for (const file of fileList) {
        formData.append("file", file);
      }
      if (spokenOrder && spokenOrder.trim()) {
        formData.append("spoken_order", spokenOrder.trim());
      }

      const resp = await fetch("/api/otis_ai/upload_walkthrough", {
        method: "POST",
        body: formData,
      });

      clearInterval(pollTimer);
      const data = await resp.json();
      if (resp.ok && data.success) {
        this._updateWalkthroughProgressDom("Analyzing videos", Array.from(shownSet));
        const allNames = Array.isArray(data.detected_area_names)
          ? data.detected_area_names
          : Array.isArray(data.detected_areas)
          ? data.detected_areas
          : [];

        for (const areaName of allNames) {
          if (!shownSet.has(areaName)) {
            shownSet.add(areaName);
            this._updateWalkthroughProgressDom(`Discovered ${areaName}`, Array.from(shownSet));
            await new Promise((r) => setTimeout(r, 220));
          }
        }

        this._updateWalkthroughProgressDom("Done", Array.from(shownSet));
        await new Promise((r) => setTimeout(r, 450));

        const detectedCount = allNames.length;
        const msg =
          detectedCount > 0
            ? `Processed ${fileList.length} video(s) (${detectedCount} areas discovered) & updated architectural floor plan!`
            : `Walkthrough processed (${fileList.length} video${fileList.length > 1 ? "s" : ""}) and floor plan generated!`;
        this._showToast(msg);
        this._floorplanModalOpen = false;
        this._selectedWalkthroughFiles = [];
        this._activeTab = "floorplan";
        this._floorplanSvg = null;
        await this._fetchData();
        if (data.url) {
          await this._loadFloorplanSvg(data.url);
        }
      } else {
        this._showToast(data.error || "Failed to parse walkthrough video", true);
      }
    } catch (err) {
      clearInterval(pollTimer);
      console.error("Error uploading walkthrough video:", err);
      this._showToast("Error uploading video. Check server logs.", true);
    } finally {
      clearInterval(pollTimer);
      this._uploadingVideo = false;
      this._uploadProgressText = "";
      this._render();
    }
  }

  async _copyLovelaceYaml() {
    if (!this._hasWalkthrough) {
      this._showToast("Please complete a video walkthrough first to unlock Lovelace YAML", true);
      return;
    }
    try {
      const res = await this._hass.callService("otis_ai", "generate_floorplan", {}, undefined, true, true);
      const data = res?.response || res || {};
      const yaml = data.lovelace_yaml || "type: picture-elements\nimage: /local/otis_floorplan.svg\nelements: []\n";
      await navigator.clipboard.writeText(yaml);
      this._showToast("Lovelace YAML copied to clipboard!");
    } catch (err) {
      console.warn("Could not copy YAML:", err);
      this._showToast("Could not copy Lovelace YAML", true);
    }
  }

  async _applySuggestion(suggestion) {
    if (!this._hass || !suggestion) return;
    const sId = suggestion.id;

    if (suggestion.action_type === "upload_walkthrough") {
      this._activeTab = "floorplan";
      this._floorplanModalOpen = true;
      this._render();
      return;
    }

    this._applyingIds.add(sId);
    this._render();

    try {
      const payload = {
        suggestion_id: sId,
        action_type: suggestion.action_type,
        action_payload: suggestion.action_payload,
      };
      const res = await this._hass.callService("otis_ai", "apply_suggestion", payload, undefined, true, true);
      const data = res?.response || res || {};

      if (data.action === "open_walkthrough_modal") {
        this._activeTab = "floorplan";
        this._floorplanModalOpen = true;
      } else if (data.success !== false) {
        this._showToast(data.message || `Applied "${suggestion.title}" successfully!`);
        this._dismissedIds.add(sId);
        // Refresh capability map so Quick Stats Bar and Capabilities Tab stay in sync
        await this._fetchData();
      } else {
        this._showToast(data.error || "Failed to apply suggestion", true);
      }
    } catch (err) {
      console.error("Error applying suggestion:", err);
      this._showToast("Error executing suggestion. Check Home Assistant logs.", true);
    } finally {
      this._applyingIds.delete(sId);
      this._render();
    }
  }

  _loadDismissedIds() {
    try {
      const stored = localStorage.getItem("otis_dismissed_suggestions");
      if (stored) {
        return new Set(JSON.parse(stored));
      }
    } catch (_) {}
    return new Set();
  }

  _saveDismissedIds() {
    try {
      if (this._dismissedIds && this._dismissedIds.size > 0) {
        localStorage.setItem("otis_dismissed_suggestions", JSON.stringify([...this._dismissedIds]));
      }
    } catch (_) {}
  }

  _dismissSuggestion(sId) {
    this._dismissedIds.add(sId);
    this._saveDismissedIds();
    this._render();
  }

  async _getConversationAgentId() {
    if (this._config && this._config.agent_id) {
      return this._config.agent_id;
    }
    if (this._capabilityMap && this._capabilityMap.conversation_agent_id) {
      return this._capabilityMap.conversation_agent_id;
    }
    if (this._conversationAgentId) {
      return this._conversationAgentId;
    }
    if (this._cachedAgentId) {
      return this._cachedAgentId;
    }

    try {
      if (this._hass && this._hass.callWS) {
        const res = await this._hass.callWS({ type: "conversation/agent/list" });
        if (res && res.agents && Array.isArray(res.agents)) {
          const otisAgent = res.agents.find(
            (a) =>
              (a.name && a.name.toLowerCase().includes("otis")) ||
              (a.id && a.id.toLowerCase().includes("otis"))
          );
          if (otisAgent) {
            this._cachedAgentId = otisAgent.id;
            return otisAgent.id;
          }
        }
      }
    } catch (e) {
      console.debug("Could not query conversation/agent/list:", e);
    }
    return null;
  }

  async _sendChatMessage(text) {
    const userText = (text || "").trim();
    if (!userText || !this._hass || this._isSendingChat) return;

    this._saveActiveTab("chat");
    const userMsgId = "user_" + Date.now();
    this._chatMessages.push({ id: userMsgId, sender: "user", text: userText, timestamp: new Date().toISOString() });
    this._saveChatMessages();
    this._isSendingChat = true;

    // Initialize contextual reasoning pipeline
    this._reasoningStartTime = Date.now();
    this._activeReasoningStep = 0;
    const lower = userText.toLowerCase();
    let domainDetail = "Scanning active devices & spatial adjacency";
    if (/power|energy|load|watt|solar|battery|grid|consumption|tariff|kwh/.test(lower)) {
      domainDetail = "Inspecting live power sensors, solar surplus & load balance";
    } else if (/media|music|play|audio|handoff|volume|speaker|zone|amp|stream/.test(lower)) {
      domainDetail = "Querying matrix audio zones & upstream media streamers";
    } else if (/security|lock|alarm|door|guard|motion|sensor|camera|perimeter/.test(lower)) {
      domainDetail = "Verifying security perimeter, locks & presence sensors";
    } else if (/light|lamp|bright|color|dim|switch/.test(lower)) {
      domainDetail = "Checking room lighting states, brightness & circadian curves";
    } else if (/undo|rollback|macro|history|revert/.test(lower)) {
      domainDetail = "Inspecting atomic state snapshots & rollback safety";
    } else if (/automation|script|scene|routine/.test(lower)) {
      domainDetail = "Auditing existing automations & cross-area coordinator scripts";
    }

    this._reasoningSteps = [
      { id: "intent", title: "Parsing Intent", detail: "Analyzing natural language prompt & target domains", status: "active", time: "0.0s" },
      { id: "topology", title: "Querying Topology", detail: "Inspecting spatial adjacency graph & active entities", status: "pending", time: "" },
      { id: "domain", title: "Domain Inspection", detail: domainDetail, status: "pending", time: "" },
      { id: "llm", title: "Consulting AI Model", detail: "Reasoning with prioritized agent & verifying safety guards", status: "pending", time: "" },
      { id: "synthesizing", title: "Synthesizing Actions", detail: "Validating action safety guards & formatting plan", status: "pending", time: "" },
    ];

    this._render();
    this._scrollChatToBottom();

    // Start timer for real-time stopwatch & step advancement
    if (this._reasoningTimer) clearInterval(this._reasoningTimer);
    this._reasoningTimer = setInterval(() => {
      if (!this._isSendingChat || !this._reasoningStartTime) {
        clearInterval(this._reasoningTimer);
        this._reasoningTimer = null;
        return;
      }
      const elapsed = (Date.now() - this._reasoningStartTime) / 1000;
      if (elapsed >= 0.8 && this._activeReasoningStep === 0) {
        this._advanceReasoningStep(1, elapsed);
      } else if (elapsed >= 2.0 && this._activeReasoningStep === 1) {
        this._advanceReasoningStep(2, elapsed);
      } else if (elapsed >= 3.8 && this._activeReasoningStep === 2) {
        this._advanceReasoningStep(3, elapsed);
      } else if (elapsed >= 6.5 && this._activeReasoningStep === 3) {
        this._advanceReasoningStep(4, elapsed);
      }
      this._updateThinkingDisplay(elapsed);
    }, 200);

    const extractSpeech = (resObj) => {
      if (!resObj) return "";
      if (typeof resObj === "string" && resObj.trim()) return resObj.trim();
      if (resObj && typeof resObj.response === "string" && resObj.response.trim()) return resObj.response.trim();
      if (resObj?.response && typeof resObj.response.response === "string" && resObj.response.response.trim()) {
        return resObj.response.response.trim();
      }
      if (resObj?.response?.speech?.plain?.speech) return resObj.response.speech.plain.speech.trim();
      if (resObj?.speech?.plain?.speech) return resObj.speech.plain.speech.trim();
      return "";
    };

    const extractConvId = (resObj) => {
      if (!resObj || typeof resObj !== "object") return null;
      return resObj.conversation_id || resObj.response?.conversation_id || null;
    };

    const callPromise = (async () => {
      let speech = "";
      const directPayload = { text: userText };
      if (this._conversationId) {
        directPayload.conversation_id = this._conversationId;
      }

      // 1. Direct call to otis_ai.chat service
      try {
        const directRes = await this._hass.callService(
          "otis_ai",
          "chat",
          directPayload,
          undefined,
          true,
          true
        );
        speech = extractSpeech(directRes);
        const cid = extractConvId(directRes);
        if (cid) this._conversationId = cid;
      } catch (serviceErr) {
        console.debug("otis_ai.chat callService failed, attempting callWS:", serviceErr);
      }

      // 2. WebSocket call_service fallback
      if (!speech && this._hass.callWS) {
        try {
          const wsRes = await this._hass.callWS({
            type: "call_service",
            domain: "otis_ai",
            service: "chat",
            service_data: directPayload,
            return_response: true,
          });
          speech = extractSpeech(wsRes);
          const cid = extractConvId(wsRes);
          if (cid) this._conversationId = cid;
        } catch (wsErr) {
          console.debug("otis_ai.chat callWS failed, attempting conversation.process:", wsErr);
        }
      }

      // 3. Fallback to conversation.process
      if (!speech) {
        const agentId = await this._getConversationAgentId();
        const payload = { text: userText };
        if (agentId) payload.agent_id = agentId;
        if (this._conversationId) payload.conversation_id = this._conversationId;

        if (this._hass.callWS) {
          try {
            const cRes = await this._hass.callWS({
              type: "conversation/process",
              ...payload,
            });
            speech = extractSpeech(cRes);
            const cid = extractConvId(cRes);
            if (cid) this._conversationId = cid;
          } catch (cErr) {
            console.debug("conversation/process callWS failed:", cErr);
          }
        }

        if (!speech) {
          const res = await this._hass.callService(
            "conversation",
            "process",
            payload,
            undefined,
            true,
            true
          );
          speech = extractSpeech(res);
          const cid = extractConvId(res);
          if (cid) this._conversationId = cid;
        }
      }

      return speech || "I'm here to assist, but received an empty response.";
    })();

    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(
        () => reject(new Error("Request timed out after 40 seconds. Please try again.")),
        40000
      )
    );

    try {
      const speech = await Promise.race([callPromise, timeoutPromise]);
      const totalElapsedSec = ((Date.now() - this._reasoningStartTime) / 1000).toFixed(1);
      this._reasoningSteps.forEach((s) => {
        s.status = "done";
        if (!s.time) s.time = `${totalElapsedSec}s`;
      });

      const otisMsgId = "otis_" + Date.now();
      this._chatMessages.push({
        id: otisMsgId,
        sender: "otis",
        text: speech,
        timestamp: new Date().toISOString(),
        reasoning: {
          duration: `${totalElapsedSec}s`,
          steps: JSON.parse(JSON.stringify(this._reasoningSteps)),
        },
      });
      this._saveChatMessages();

      if (
        speech &&
        (speech.includes("successfully created and enabled the automation") ||
          speech.includes("successfully created the script"))
      ) {
        this._fetchData();
      }
    } catch (err) {
      console.error("Error sending message to Otis:", err);
      const totalElapsedSec = this._reasoningStartTime ? ((Date.now() - this._reasoningStartTime) / 1000).toFixed(1) : "0.0";
      const otisErrId = "otis_err_" + Date.now();
      this._chatMessages.push({
        id: otisErrId,
        sender: "otis",
        text: `⚠️ **Assist Co-Pilot:** ${err.message || "Failed to connect to the AI agent. Please try again."}`,
        timestamp: new Date().toISOString(),
        isError: true,
        reasoning: {
          duration: `${totalElapsedSec}s`,
          steps: JSON.parse(JSON.stringify(this._reasoningSteps || [])),
        },
      });
      this._saveChatMessages();
    } finally {
      if (this._reasoningTimer) {
        clearInterval(this._reasoningTimer);
        this._reasoningTimer = null;
      }
      this._isSendingChat = false;
      this._render();
      this._scrollChatToBottom();
    }
  }

  _toggleVoiceRecording() {
    if (this._isListening) {
      this._stopVoiceRecording();
      return;
    }
    this._startVoiceRecording();
  }

  _startVoiceRecording() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      this._showToast("Speech recognition is not supported in this browser. Please type your message.", true);
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognition.lang = navigator.language || "en-US";
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      this._recognition = recognition;
      this._isListening = true;
      this._render();

      const input = this.shadowRoot.querySelector("#chat-input");
      if (input) {
        input.placeholder = "Listening... speak now";
      }

      recognition.onresult = (event) => {
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          transcript += event.results[i][0].transcript;
        }
        if (input) {
          input.value = transcript;
          input.style.height = "auto";
          input.style.height = Math.min(input.scrollHeight, 140) + "px";
        }
      };

      recognition.onerror = (event) => {
        console.warn("Otis Voice Error:", event.error);
        this._isListening = false;
        this._recognition = null;
        if (event.error !== "no-speech") {
          this._showToast(`Voice input: ${event.error}`, true);
        }
        this._render();
      };

      recognition.onend = () => {
        const wasListening = this._isListening;
        this._isListening = false;
        this._recognition = null;
        const finalInput = this.shadowRoot.querySelector("#chat-input");
        const capturedText = finalInput ? finalInput.value.trim() : "";
        this._render();
        if (wasListening && capturedText) {
          this._sendChatMessage(capturedText);
        }
      };

      recognition.start();
    } catch (err) {
      console.error("Otis Voice failed to start:", err);
      this._isListening = false;
      this._recognition = null;
      this._showToast("Could not access microphone.", true);
      this._render();
    }
  }

  _stopVoiceRecording() {
    if (this._recognition) {
      try {
        this._recognition.stop();
      } catch (e) {
        // Ignore stop error
      }
      this._recognition = null;
    }
    this._isListening = false;
    this._render();
  }

  _showToast(msg, isError = false) {
    const toast = this.shadowRoot.querySelector("#toast");
    if (toast) {
      toast.textContent = msg;
      toast.className = isError ? "toast error show" : "toast show";
      setTimeout(() => {
        toast.className = "toast";
      }, 4000);
    }
  }

  _scrollChatToBottom() {
    const doScroll = () => {
      const container = this.shadowRoot ? this.shadowRoot.querySelector("#chat-history") : null;
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    };
    requestAnimationFrame(doScroll);
    setTimeout(doScroll, 80);
    setTimeout(doScroll, 220);
  }

  _renderMarkdown(text) {
    if (text === undefined || text === null) return "";
    let src = String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    // 1. Protect code blocks first
    const codeBlocks = [];
    src = src.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (match, lang, code) => {
      const idx = codeBlocks.length;
      const cleanCode = code.trim();
      const escapedCode = cleanCode
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      const langLabel = lang ? `<div class="code-lang">${lang}</div>` : "";
      codeBlocks.push(
        `<div class="code-block-wrapper">${langLabel}<pre><code>${escapedCode}</code></pre></div>`
      );
      return `\n\n@@@OTIS_CB_${idx}@@@\n\n`;
    });

    // 2. Protect inline code second (prevents asterisks/underscores in entity IDs or wildcards from breaking bold/italic)
    const inlineCodes = [];
    src = src.replace(/`([^`\n]+)`/g, (match, code) => {
      const idx = inlineCodes.length;
      const escapedCode = code
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      inlineCodes.push(`<code>${escapedCode}</code>`);
      return `@@@OTIS_IC_${idx}@@@`;
    });

    // 3. Escape raw HTML characters
    src = src
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // 4. Normalize standalone headings and dividers
    // Reconnect standalone ### followed by text on the next line (e.g., "###\n1. Heading" -> "### 1. Heading")
    src = src.replace(/^[ \t]*(#{1,6})[ \t]*\n+([A-Za-z0-9*_\-].*)$/gm, "$1 $2");
    // Standalone ### without following text becomes an hr divider
    src = src.replace(/^[ \t]*#{1,6}[ \t]*$/gm, "<hr>");
    // Horizontal rules (--, ---, ***, ___)
    src = src.replace(/^[ \t]*(?:--{1,}|(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})[ \t]*$/gm, "<hr>");

    // 5. Blockquotes
    src = src.replace(/^[ \t]*&gt;[ \t]*(.*)$/gm, "<blockquote>$1</blockquote>");

    // 6. Tables
    src = src.replace(/(?:^[ \t]*\|[^\n]+\|[ \t]*(?:\n|$))+/gm, (tableMatch) => {
      const rows = tableMatch.trim().split("\n").map((r) => r.trim()).filter(Boolean);
      if (rows.length < 2) return tableMatch;
      const isSep = /^\|(?:[ \t]*:?-+:?[ \t]*\|)+$/.test(rows[1]);
      let html = '<div class="chat-table-wrapper"><table class="chat-table">';
      let startIdx = 0;
      if (isSep && rows.length >= 2) {
        const headerCells = rows[0].replace(/^\|/, "").replace(/\|$/, "").split("|");
        html += "<thead><tr>" + headerCells.map((c) => `<th>${c.trim()}</th>`).join("") + "</tr></thead>";
        startIdx = 2;
      }
      html += "<tbody>";
      for (let i = startIdx; i < rows.length; i++) {
        if (/^\|(?:[ \t]*:?-+:?[ \t]*\|)+$/.test(rows[i])) continue;
        const cells = rows[i].replace(/^\|/, "").replace(/\|$/, "").split("|");
        html += "<tr>" + cells.map((c) => `<td>${c.trim()}</td>`).join("") + "</tr>";
      }
      html += "</tbody></table></div>\n";
      return html;
    });

    // 7. Headings
    src = src.replace(/^[ \t]*######[ \t]+(.*)$/gm, "<h6>$1</h6>");
    src = src.replace(/^[ \t]*#####[ \t]+(.*)$/gm, "<h5>$1</h5>");
    src = src.replace(/^[ \t]*####[ \t]+(.*)$/gm, "<h4>$1</h4>");
    src = src.replace(/^[ \t]*###[ \t]+(.*)$/gm, "<h3>$1</h3>");
    src = src.replace(/^[ \t]*##[ \t]+(.*)$/gm, "<h2>$1</h2>");
    src = src.replace(/^[ \t]*#[ \t]+(.*)$/gm, "<h1>$1</h1>");

    // 8. Lists (Unordered & Ordered)
    src = src.replace(/(?:^[ \t]*[-*+][ \t]+[^\n]+(?:\n|$))+/gm, (match) => {
      const items = match
        .trim()
        .split("\n")
        .map((line) => line.replace(/^[ \t]*[-*+][ \t]+/, "").trim())
        .filter(Boolean)
        .map((item) => {
          if (item.startsWith("[ ] ")) {
            return `<li><input type="checkbox" disabled style="vertical-align:middle; margin-right:4px;"> ${item.slice(4)}</li>`;
          }
          if (item.startsWith("[x] ") || item.startsWith("[X] ")) {
            return `<li><input type="checkbox" checked disabled style="vertical-align:middle; margin-right:4px;"> ${item.slice(4)}</li>`;
          }
          return `<li>${item}</li>`;
        })
        .join("");
      return `<ul>${items}</ul>\n`;
    });

    src = src.replace(/(?:^[ \t]*\d+[.)][ \t]+[^\n]+(?:\n|$))+/gm, (match) => {
      const items = match
        .trim()
        .split("\n")
        .map((line) => line.replace(/^[ \t]*\d+[.)][ \t]+/, "").trim())
        .filter(Boolean)
        .map((item) => `<li>${item}</li>`)
        .join("");
      return `<ol>${items}</ol>\n`;
    });

    // 9. Bold, Italic & Strikethrough (word-boundary safe)
    src = src.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
    src = src.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    src = src.replace(/(^|[\s\(\[{])\*([^*\n]+)\*(?=[\s\.,!?:;\)\]}]|$)/g, "$1<em>$2</em>");
    src = src.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    src = src.replace(/(^|[\s\(\[{])_([^_\n]+)_(?=[\s\.,!?:;\)\]}]|$)/g, "$1<em>$2</em>");
    src = src.replace(/~~([^~]+)~~/g, "<del>$1</del>");

    // 10. Links
    src = src.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    // 11. Paragraphs & Line Breaks
    const paragraphs = src.split(/\n{2,}/);
    src = paragraphs
      .map((p) => {
        p = p.trim();
        if (!p) return "";
        if (
          p.startsWith("<h") ||
          p.startsWith("<ul") ||
          p.startsWith("<ol") ||
          p.startsWith("<hr") ||
          p.startsWith("<blockquote") ||
          p.startsWith('<div class="chat-table') ||
          p.startsWith("@@@OTIS_CB_")
        ) {
          return p;
        }
        return `<p>${p.replace(/\n/g, "<br>")}</p>`;
      })
      .filter(Boolean)
      .join("");

    // 12. Restore tokens
    src = src.replace(/@@@OTIS_IC_(\d+)@@@/g, (match, idx) => {
      return inlineCodes[Number(idx)] || "";
    });
    src = src.replace(/@@@OTIS_CB_(\d+)@@@/g, (match, idx) => {
      return codeBlocks[Number(idx)] || "";
    });

    return src;
  }

  _matchesCategoryFilter(suggestion, filterKey) {
    if (!filterKey || filterKey === "all") return true;
    const cat = String(suggestion?.category || "automation").toLowerCase();
    const map = {
      lighting: ["lighting", "automation", "habit_routine"],
      media: ["media"],
      security: ["security"],
      dashboard: ["dashboard", "visualization"],
      cleanup: ["cleanup"],
      system: ["system", "energy"],
    };
    const allowed = map[filterKey] || [filterKey];
    return allowed.includes(cat);
  }

  _getActionLabel(actionType) {
    switch (actionType) {
      case "create_package":
        return "📦 Deploy Coordinator Package";
      case "auto_assign_areas":
        return "📍 Auto-Assign Areas";
      case "improve_automation":
        return "🔧 Upgrade Automation";
      case "optimize_system_config":
        return "⚡ Optimize HA Config";
      case "create_dashboard":
        return "📊 Create Pro Dashboard";
      case "sync_ha_floors":
        return "🏢 Sync HA Floors";
      case "advisor_guide":
        return "📖 View Setup Guide";
      case "cleanup_orphans":
        return "🧹 Clean Up Orphans";
      case "upload_walkthrough":
        return "📹 Open Walkthrough Studio";
      case "configure_agent":
        return "⚙️ Configure AI Failover";
      default:
        return "⚡ Apply with 1-Click";
    }
  }

  _render() {
    const priorityRank = { critical: 0, high: 1, medium: 2, low: 3 };
    const activeSuggestions = (this._suggestions || [])
      .filter((s) => !this._dismissedIds.has(s.id))
      .slice()
      .sort((a, b) => {
        const rankA = priorityRank[String(a.priority || "medium").toLowerCase()] ?? 2;
        const rankB = priorityRank[String(b.priority || "medium").toLowerCase()] ?? 2;
        return rankA - rankB;
      });
    const filteredSuggestions = activeSuggestions.filter((s) =>
      this._matchesCategoryFilter(s, this._selectedCategory)
    );
    const visibleSuggestions = filteredSuggestions.slice(
      0,
      this._config.max_suggestions || 5
    );

    const stats = {
      areas: Object.keys(this._capabilityMap?.areas || {}).length,
      entities: (this._capabilityMap?.entities || []).length,
      automations: (this._capabilityMap?.entities || []).filter((e) => e.domain === "automation").length,
      orphans: (this._capabilityMap?.orphaned_entities || []).length,
    };

    const dashPrefix =
      window.location.pathname.startsWith("/command-center") ||
      this._config.dashboard_url_path === "command-center"
        ? "/command-center"
        : "/otis-ai";

    const areas = this._capabilityMap?.areas || {};
    const entities = this._capabilityMap?.entities || [];
    const activeAreas = [];
    for (const [aid, ainfo] of Object.entries(areas)) {
      const hasEntities =
        (ainfo.entities && ainfo.entities.length > 0) ||
        entities.some((e) => e.area_id === aid);
      if (hasEntities) {
        const slug = aid.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "room";
        activeAreas.push({
          id: aid,
          name: ainfo.name || aid,
          slug: slug,
          path: `${dashPrefix}/area_${slug}`,
        });
      }
    }
    activeAreas.sort((a, b) => a.name.localeCompare(b.name));

    const preset = this._config.theme_preset || this._config.theme || "ha_native";
    const themeClass = `theme-${preset.replace(/_/g, "-")}`;
    const isControlMode = this._config.mode === "floorplan_control";
    const isStudioMode = this._config.mode === "floorplan_studio" || isControlMode;
    const isAdmin = Boolean(this._hass?.user?.is_admin || this._hass?.user?.is_owner);

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          box-sizing: border-box;
          font-family: var(--ha-card-font-family, 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
        }

        /* Base Card Styling with Token Architecture for Card-Mod & Custom Themes */
        ha-card.card-container {
          /* Fallback Theme Variables (Follows Active HA / System Theme) */
          --otis-primary: var(--primary-color, #03a9f4);
          --otis-secondary: var(--accent-color, #ff9800);
          --otis-bg: var(--ha-card-background, var(--card-background-color, #1e293b));
          --otis-card-border: var(--ha-card-border-color, var(--divider-color, rgba(128, 128, 128, 0.2)));
          --otis-card-radius: var(--ha-card-border-radius, 20px);
          --otis-text: var(--primary-text-color, #f1f5f9);
          --otis-text-muted: var(--secondary-text-color, #94a3b8);
          --otis-surface: var(--secondary-background-color, rgba(15, 23, 42, 0.55));
          --otis-surface-border: var(--divider-color, rgba(128, 128, 128, 0.15));
          --otis-glow: rgba(var(--rgb-primary-color, 3, 169, 244), 0.25);
          --otis-badge-bg: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12);
          --otis-chip-bg: color-mix(in srgb, var(--primary-text-color, #f1f5f9) 6%, transparent);
          --otis-chip-border: var(--divider-color, rgba(128, 128, 128, 0.18));
          --otis-input-bg: var(--input-fill-color, var(--card-background-color, rgba(15, 23, 42, 0.6)));
          --otis-input-border: var(--input-outlined-idle-border-color, var(--divider-color, rgba(128, 128, 128, 0.2)));
          --otis-user-bubble-bg: var(--primary-color, #03a9f4);
          --otis-user-bubble-text: #ffffff;
          --otis-btn-text: #ffffff;

          position: relative;
          width: 100%;
          max-width: 1600px;
          margin: 0 auto;
          background: var(--ha-card-background, var(--otis-bg));
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--otis-card-border));
          border-radius: var(--ha-card-border-radius, var(--otis-card-radius));
          padding: 24px;
          box-shadow: var(--ha-card-box-shadow, 0 8px 28px rgba(0, 0, 0, 0.14));
          color: var(--primary-text-color, var(--otis-text));
          overflow: hidden;
          transition: border-color 0.3s ease, box-shadow 0.3s ease;
          box-sizing: border-box;
        }

        ha-card.card-container:hover {
          border-color: var(--otis-primary);
          box-shadow: 0 18px 42px rgba(0, 0, 0, 0.45), 0 0 20px var(--otis-glow);
        }

        /* Floor Plan Studio Full-Width Mode */
        ha-card.card-container.mode-floorplan-studio {
          width: 100% !important;
          max-width: 100% !important;
          margin: 0 !important;
          border-radius: 0 !important;
          border-left: none !important;
          border-right: none !important;
          padding: 16px 20px !important;
          box-shadow: none !important;
          min-height: calc(100vh - 80px) !important;
        }

        ha-card.card-container.mode-floorplan-studio .floorplan-svg-viewport {
          min-height: calc(100vh - 190px) !important;
          max-height: none !important;
          height: calc(100vh - 190px) !important;
        }

        ha-card.card-container.mode-floorplan-studio .floorplan-svg-viewport svg {
          max-height: calc(100vh - 200px) !important;
          height: 100% !important;
          width: 100% !important;
        }

        .studio-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 14px;
          padding-bottom: 12px;
          border-bottom: 1px solid var(--otis-surface-border);
          flex-wrap: wrap;
          gap: 10px;
        }

        /* Curated Theme Presets */
        ha-card.theme-cyberpunk {
          --otis-primary: #38bdf8;
          --otis-secondary: #c084fc;
          --otis-bg: radial-gradient(135% 120% at 10% 10%, rgba(30, 41, 59, 0.72) 0%, rgba(15, 23, 42, 0.90) 100%);
          --otis-card-border: rgba(255, 255, 255, 0.12);
          --otis-text: #f1f5f9;
          --otis-text-muted: #94a3b8;
          --otis-surface: rgba(15, 23, 42, 0.55);
          --otis-surface-border: rgba(255, 255, 255, 0.08);
          --otis-glow: rgba(56, 189, 248, 0.25);
          --otis-badge-bg: rgba(56, 189, 248, 0.12);
          --otis-chip-bg: rgba(255, 255, 255, 0.05);
          --otis-chip-border: rgba(255, 255, 255, 0.1);
          --otis-input-bg: rgba(15, 23, 42, 0.6);
          --otis-input-border: rgba(255, 255, 255, 0.12);
          --otis-user-bubble-bg: linear-gradient(135deg, #1e293b, #334155);
          --otis-user-bubble-text: #f8fafc;
        }

        ha-card.theme-midnight {
          --otis-primary: #60a5fa;
          --otis-secondary: #818cf8;
          --otis-bg: radial-gradient(135% 120% at 10% 10%, rgba(17, 24, 39, 0.88) 0%, rgba(3, 7, 18, 0.98) 100%);
          --otis-card-border: rgba(255, 255, 255, 0.08);
          --otis-text: #f3f4f6;
          --otis-text-muted: #9ca3af;
          --otis-surface: rgba(17, 24, 39, 0.65);
          --otis-surface-border: rgba(255, 255, 255, 0.06);
          --otis-glow: rgba(96, 165, 250, 0.20);
          --otis-badge-bg: rgba(96, 165, 250, 0.14);
          --otis-chip-bg: rgba(255, 255, 255, 0.04);
          --otis-chip-border: rgba(255, 255, 255, 0.08);
          --otis-input-bg: rgba(10, 15, 28, 0.7);
          --otis-input-border: rgba(255, 255, 255, 0.1);
          --otis-user-bubble-bg: linear-gradient(135deg, #1e293b, #0f172a);
          --otis-user-bubble-text: #f3f4f6;
        }

        ha-card.theme-emerald {
          --otis-primary: #34d399;
          --otis-secondary: #2dd4bf;
          --otis-bg: radial-gradient(135% 120% at 10% 10%, rgba(6, 78, 59, 0.45) 0%, rgba(2, 44, 34, 0.94) 100%);
          --otis-card-border: rgba(52, 211, 153, 0.22);
          --otis-text: #ecfdf5;
          --otis-text-muted: #a7f3d0;
          --otis-surface: rgba(4, 30, 24, 0.65);
          --otis-surface-border: rgba(52, 211, 153, 0.12);
          --otis-glow: rgba(52, 211, 153, 0.30);
          --otis-badge-bg: rgba(52, 211, 153, 0.14);
          --otis-chip-bg: rgba(52, 211, 153, 0.08);
          --otis-chip-border: rgba(52, 211, 153, 0.18);
          --otis-input-bg: rgba(2, 44, 34, 0.7);
          --otis-input-border: rgba(52, 211, 153, 0.25);
          --otis-user-bubble-bg: linear-gradient(135deg, #064e3b, #047857);
          --otis-user-bubble-text: #ecfdf5;
        }

        ha-card.theme-sunset {
          --otis-primary: #fb923c;
          --otis-secondary: #f43f5e;
          --otis-bg: radial-gradient(135% 120% at 10% 10%, rgba(67, 20, 7, 0.50) 0%, rgba(24, 10, 20, 0.94) 100%);
          --otis-card-border: rgba(251, 146, 60, 0.22);
          --otis-text: #fff7ed;
          --otis-text-muted: #fdba74;
          --otis-surface: rgba(30, 12, 16, 0.65);
          --otis-surface-border: rgba(251, 146, 60, 0.12);
          --otis-glow: rgba(251, 146, 60, 0.30);
          --otis-badge-bg: rgba(251, 146, 60, 0.14);
          --otis-chip-bg: rgba(251, 146, 60, 0.08);
          --otis-chip-border: rgba(251, 146, 60, 0.18);
          --otis-input-bg: rgba(24, 10, 20, 0.7);
          --otis-input-border: rgba(251, 146, 60, 0.25);
          --otis-user-bubble-bg: linear-gradient(135deg, #881337, #9f1239);
          --otis-user-bubble-text: #fff7ed;
        }

        ha-card.theme-light-frost {
          --otis-primary: #0284c7;
          --otis-secondary: #7c3aed;
          --otis-bg: radial-gradient(135% 120% at 10% 10%, rgba(255, 255, 255, 0.92) 0%, rgba(241, 245, 249, 0.96) 100%);
          --otis-card-border: rgba(0, 0, 0, 0.08);
          --otis-text: #0f172a;
          --otis-text-muted: #475569;
          --otis-surface: rgba(255, 255, 255, 0.75);
          --otis-surface-border: rgba(0, 0, 0, 0.06);
          --otis-glow: rgba(2, 132, 199, 0.15);
          --otis-badge-bg: rgba(2, 132, 199, 0.10);
          --otis-chip-bg: rgba(0, 0, 0, 0.04);
          --otis-chip-border: rgba(0, 0, 0, 0.08);
          --otis-input-bg: rgba(255, 255, 255, 0.9);
          --otis-input-border: rgba(0, 0, 0, 0.12);
          --otis-user-bubble-bg: linear-gradient(135deg, #0284c7, #2563eb);
          --otis-user-bubble-text: #ffffff;
          box-shadow: 0 16px 36px rgba(0, 0, 0, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.8);
        }

        ha-card.theme-ha-native {
          --otis-primary: var(--primary-color, #03a9f4);
          --otis-secondary: var(--accent-color, #ff9800);
          --otis-bg: var(--ha-card-background, var(--card-background-color, #1e293b));
          --otis-card-border: var(--ha-card-border-color, var(--divider-color, rgba(128, 128, 128, 0.2)));
          --otis-card-radius: var(--ha-card-border-radius, 16px);
          --otis-text: var(--primary-text-color, #f1f5f9);
          --otis-text-muted: var(--secondary-text-color, #94a3b8);
          --otis-surface: var(--secondary-background-color, rgba(15, 23, 42, 0.55));
          --otis-surface-border: var(--divider-color, rgba(128, 128, 128, 0.15));
          --otis-glow: rgba(var(--rgb-primary-color, 3, 169, 244), 0.25);
          --otis-badge-bg: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12);
          --otis-chip-bg: color-mix(in srgb, var(--primary-text-color, #f1f5f9) 6%, transparent);
          --otis-chip-border: var(--divider-color, rgba(128, 128, 128, 0.18));
          --otis-input-bg: var(--input-fill-color, var(--card-background-color, rgba(15, 23, 42, 0.6)));
          --otis-input-border: var(--input-outlined-idle-border-color, var(--divider-color, rgba(128, 128, 128, 0.2)));
          --otis-user-bubble-bg: var(--primary-color, #03a9f4);
          --otis-user-bubble-text: #ffffff;
        }

        /* Top Accent Glow */
        ha-card.card-container::before {
          content: "";
          position: absolute;
          top: 0;
          left: 10%;
          right: 10%;
          height: 2px;
          background: linear-gradient(90deg, transparent 0%, var(--otis-primary) 50%, var(--otis-secondary) 80%, transparent 100%);
          opacity: 0.85;
        }

        /* Header */
        .card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }

        .brand-section {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .emblem-icon {
          width: 38px;
          height: 38px;
          border-radius: 10px;
          background: linear-gradient(135deg, color-mix(in srgb, var(--otis-primary) 20%, transparent), color-mix(in srgb, var(--otis-secondary) 20%, transparent));
          border: 1px solid color-mix(in srgb, var(--otis-primary) 40%, transparent);
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 0 14px var(--otis-glow);
        }

        .emblem-icon svg {
          width: 24px;
          height: 24px;
          fill: none;
          stroke: var(--otis-primary);
          stroke-width: 2;
          stroke-linecap: round;
          stroke-linejoin: round;
        }

        .title-group {
          display: flex;
          flex-direction: column;
        }

        .main-title {
          font-size: 1.15rem;
          font-weight: 700;
          letter-spacing: -0.01em;
          background: linear-gradient(90deg, var(--otis-text) 0%, var(--otis-text-muted) 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }

        .sub-title {
          font-size: 0.75rem;
          color: var(--otis-text-muted);
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .status-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #34d399;
          box-shadow: 0 0 6px #34d399;
          animation: pulse 2s infinite ease-in-out;
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.2); }
        }

        .header-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .icon-btn {
          background: var(--otis-chip-bg);
          border: 1px solid var(--otis-chip-border);
          color: var(--otis-text-muted);
          border-radius: 8px;
          padding: 6px 10px;
          cursor: pointer;
          font-size: 0.8rem;
          display: flex;
          align-items: center;
          gap: 4px;
          transition: all 0.2s ease;
        }

        .icon-btn:hover {
          background: color-mix(in srgb, var(--otis-primary) 15%, transparent);
          color: var(--otis-primary);
          border-color: color-mix(in srgb, var(--otis-primary) 30%, transparent);
        }

        /* Stats Bar */
        .stats-bar {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 8px;
          margin-bottom: 16px;
          background: var(--otis-surface);
          border-radius: 12px;
          padding: 8px 12px;
          border: 1px solid var(--otis-surface-border);
        }

        .stat-item {
          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;
        }

        .stat-value {
          font-size: 1rem;
          font-weight: 700;
          color: var(--otis-text);
        }

        .stat-label {
          font-size: 0.68rem;
          color: var(--otis-text-muted);
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }

        .stat-item.warning .stat-value {
          color: #f59e0b;
        }

        /* Subview Hub Launchpad */
        .subviews-launchpad {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 12px;
          padding: 8px 10px;
          background: color-mix(in srgb, var(--otis-surface) 60%, transparent);
          border: 1px solid var(--otis-surface-border);
          border-radius: 8px;
        }

        .launchpad-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }

        .subviews-label {
          font-size: 0.72rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--otis-text-muted);
          margin-right: 4px;
          min-width: 58px;
        }

        /* Theme Studio Grid */
        .theme-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
          gap: 12px;
          max-height: 380px;
          overflow-y: auto;
          padding: 4px;
        }

        .theme-card {
          background: color-mix(in srgb, var(--otis-surface) 80%, transparent);
          border: 1px solid var(--otis-surface-border);
          border-radius: 12px;
          padding: 12px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          transition: all 0.15s ease;
        }

        .theme-card:hover {
          border-color: var(--otis-primary);
          transform: translateY(-2px);
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        }

        .theme-swatches {
          display: flex;
          gap: 6px;
          align-items: center;
        }

        .theme-swatch {
          width: 18px;
          height: 18px;
          border-radius: 50%;
          border: 1px solid rgba(255, 255, 255, 0.25);
          box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }

        .subview-chip {
          background: var(--otis-surface);
          border: 1px solid var(--otis-surface-border);
          color: var(--otis-text);
          font-size: 0.74rem;
          font-weight: 500;
          padding: 4px 9px;
          border-radius: 6px;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          transition: all 0.15s ease;
        }

        .subview-chip:hover {
          background: color-mix(in srgb, var(--otis-primary) 15%, transparent);
          border-color: var(--otis-primary);
          color: var(--otis-primary);
          transform: translateY(-1px);
        }

        .room-chip {
          background: color-mix(in srgb, var(--otis-surface) 80%, var(--otis-primary) 8%);
        }

        /* Navigation Tabs */
        .tabs-nav {
          display: flex;
          gap: 6px;
          background: var(--otis-surface);
          border-radius: 10px;
          padding: 4px;
          margin-bottom: 16px;
          border: 1px solid var(--otis-surface-border);
        }

        .tab-btn {
          flex: 1;
          background: transparent;
          border: 1px solid transparent;
          color: var(--otis-text-muted);
          font-size: 0.78rem;
          font-weight: 600;
          padding: 8px 10px;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
        }

        .tab-btn:hover {
          color: var(--otis-text);
        }

        .tab-btn.active {
          background: color-mix(in srgb, var(--otis-primary) 15%, transparent);
          color: var(--otis-primary);
          border: 1px solid color-mix(in srgb, var(--otis-primary) 35%, transparent);
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        }

        .tab-badge {
          background: var(--otis-primary);
          color: #0f172a;
          font-size: 0.65rem;
          font-weight: 700;
          padding: 1px 6px;
          border-radius: 10px;
        }

        /* Suggestions List & Category Filter Pills */
        .category-pills {
          display: flex;
          align-items: center;
          gap: 6px;
          overflow-x: auto;
          padding-bottom: 4px;
          margin-bottom: 10px;
        }

        .category-pill {
          background: var(--otis-chip-bg);
          border: 1px solid var(--otis-chip-border);
          color: var(--otis-text-muted);
          border-radius: 999px;
          padding: 4px 11px;
          font-size: 0.72rem;
          font-weight: 600;
          cursor: pointer;
          white-space: nowrap;
          transition: all 0.2s ease;
        }

        .category-pill:hover {
          color: var(--otis-text);
          border-color: color-mix(in srgb, var(--otis-primary) 35%, transparent);
        }

        .category-pill.active {
          background: color-mix(in srgb, var(--otis-primary) 18%, transparent);
          color: var(--otis-primary);
          border-color: var(--otis-primary);
          box-shadow: 0 0 10px var(--otis-glow);
        }

        .suggestions-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .suggestion-card {
          position: relative;
          background: var(--otis-surface);
          border: 1px solid var(--otis-surface-border);
          border-radius: 14px;
          padding: 14px;
          transition: all 0.25s ease;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .suggestion-card:hover {
          border-color: color-mix(in srgb, var(--otis-primary) 35%, transparent);
          transform: translateY(-1px);
        }

        .suggestion-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .suggestion-badge-group {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .badge-category {
          font-size: 0.65rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          padding: 2px 8px;
          border-radius: 6px;
          background: var(--otis-badge-bg);
          color: var(--otis-primary);
          border: 1px solid color-mix(in srgb, var(--otis-primary) 25%, transparent);
        }

        .badge-priority {
          font-size: 0.65rem;
          font-weight: 700;
          text-transform: uppercase;
          padding: 2px 6px;
          border-radius: 6px;
        }

        .badge-priority.high {
          background: rgba(244, 63, 94, 0.15);
          color: #fb7185;
          border: 1px solid rgba(244, 63, 94, 0.3);
        }

        .badge-priority.medium {
          background: rgba(245, 158, 11, 0.15);
          color: #fbbf24;
          border: 1px solid rgba(245, 158, 11, 0.3);
        }

        .badge-priority.low {
          background: rgba(148, 163, 184, 0.15);
          color: #cbd5e1;
          border: 1px solid rgba(148, 163, 184, 0.3);
        }

        .dismiss-btn {
          background: transparent;
          border: none;
          color: var(--otis-text-muted);
          cursor: pointer;
          font-size: 1rem;
          padding: 2px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: color 0.2s ease;
        }

        .dismiss-btn:hover {
          color: #f43f5e;
        }

        .suggestion-title {
          font-size: 0.92rem;
          font-weight: 600;
          color: var(--otis-text);
        }

        .suggestion-desc {
          font-size: 0.78rem;
          color: var(--otis-text-muted);
          line-height: 1.4;
        }

        .suggestion-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 4px;
        }

        .apply-btn {
          background: linear-gradient(135deg, var(--otis-primary) 0%, var(--otis-secondary) 100%);
          border: none;
          color: var(--otis-btn-text, #ffffff);
          font-weight: 600;
          font-size: 0.78rem;
          padding: 6px 14px;
          border-radius: 8px;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: all 0.2s ease;
          box-shadow: 0 2px 8px var(--otis-glow);
        }

        .apply-btn:hover {
          filter: brightness(1.1);
          box-shadow: 0 4px 14px var(--otis-glow);
          transform: translateY(-1px);
        }

        .apply-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
          transform: none;
        }

        .spinner {
          width: 12px;
          height: 12px;
          border: 2px solid rgba(255, 255, 255, 0.3);
          border-top-color: #ffffff;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        .empty-state {
          text-align: center;
          padding: 32px 16px;
          color: var(--otis-text-muted);
        }

        .empty-icon {
          font-size: 2rem;
          margin-bottom: 8px;
        }

        /* Chat Section */
        .chat-container {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .chat-chips {
          display: flex;
          gap: 6px;
          overflow-x: auto;
          padding-bottom: 4px;
        }

        .chip-btn {
          background: var(--otis-chip-bg);
          border: 1px solid var(--otis-chip-border);
          color: var(--otis-text-muted);
          font-size: 0.72rem;
          padding: 4px 10px;
          border-radius: 12px;
          cursor: pointer;
          white-space: nowrap;
          transition: all 0.2s ease;
        }

        .chip-btn:hover {
          background: color-mix(in srgb, var(--otis-primary) 15%, transparent);
          color: var(--otis-primary);
          border-color: color-mix(in srgb, var(--otis-primary) 30%, transparent);
        }

        .chat-history {
          min-height: 420px;
          max-height: 560px;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 12px;
          padding-right: 6px;
        }

        .chat-bubble {
          max-width: 90%;
          padding: 10px 14px;
          border-radius: 14px;
          font-size: 0.82rem;
          line-height: 1.5;
          word-break: break-word;
        }

        .chat-bubble p {
          margin: 0 0 8px 0;
        }
        .chat-bubble p:last-child {
          margin-bottom: 0;
        }

        .chat-bubble h1, .chat-bubble h2, .chat-bubble h3, .chat-bubble h4 {
          margin: 12px 0 6px 0;
          color: var(--otis-text);
          font-weight: 700;
          line-height: 1.3;
        }
        .chat-bubble h1 { font-size: 1.05rem; }
        .chat-bubble h2 { font-size: 0.95rem; }
        .chat-bubble h3 {
          font-size: 0.88rem;
          color: var(--otis-primary);
          border-bottom: 1px solid color-mix(in srgb, var(--otis-primary) 20%, transparent);
          padding-bottom: 3px;
        }
        .chat-bubble h4 { font-size: 0.82rem; }
        .chat-bubble h1:first-child, .chat-bubble h2:first-child, .chat-bubble h3:first-child {
          margin-top: 0;
        }

        .chat-bubble ul, .chat-bubble ol {
          margin: 6px 0 8px 0;
          padding-left: 20px;
        }
        .chat-bubble li {
          margin-bottom: 4px;
        }
        .chat-bubble li:last-child {
          margin-bottom: 0;
        }

        .chat-bubble strong {
          color: var(--otis-text);
          font-weight: 700;
        }

        .chat-bubble em {
          color: var(--otis-text-muted);
          font-style: italic;
        }

        .chat-bubble a {
          color: var(--otis-primary);
          text-decoration: underline;
          text-underline-offset: 2px;
          transition: opacity 0.2s ease;
        }
        .chat-bubble a:hover {
          opacity: 0.8;
        }

        .chat-macro-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 10px;
          padding-top: 8px;
          border-top: 1px solid rgba(255, 255, 255, 0.08);
        }

        .macro-action-btn {
          font-size: 0.72rem;
          font-weight: 600;
          padding: 5px 11px;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: inline-flex;
          align-items: center;
          gap: 5px;
          border: none;
        }

        .macro-action-btn.confirm {
          background: rgba(34, 197, 94, 0.18);
          border: 1px solid rgba(34, 197, 94, 0.45);
          color: #4ade80;
        }
        .macro-action-btn.confirm:hover {
          background: rgba(34, 197, 94, 0.35);
          transform: translateY(-1px);
        }

        .macro-action-btn.cancel {
          background: rgba(239, 68, 68, 0.18);
          border: 1px solid rgba(239, 68, 68, 0.45);
          color: #f87171;
        }
        .macro-action-btn.cancel:hover {
          background: rgba(239, 68, 68, 0.35);
          transform: translateY(-1px);
        }

        .macro-action-btn.rollback {
          background: rgba(14, 165, 233, 0.18);
          border: 1px solid rgba(14, 165, 233, 0.45);
          color: #38bdf8;
        }
        .macro-action-btn.rollback:hover {
          background: rgba(14, 165, 233, 0.35);
          transform: translateY(-1px);
        }

        .chat-bubble code {
          background: color-mix(in srgb, var(--otis-primary) 12%, transparent);
          color: var(--otis-primary);
          border: 1px solid color-mix(in srgb, var(--otis-primary) 25%, transparent);
          padding: 1px 5px;
          border-radius: 4px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          font-size: 0.76rem;
        }

        .code-block-wrapper {
          margin: 8px 0;
          border-radius: 8px;
          overflow: hidden;
          background: rgba(15, 23, 42, 0.85);
          border: 1px solid var(--otis-surface-border);
        }

        .code-lang {
          font-size: 0.68rem;
          color: var(--otis-primary);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          padding: 4px 10px;
          background: rgba(0, 0, 0, 0.35);
          border-bottom: 1px solid var(--otis-surface-border);
          font-family: ui-monospace, monospace;
          font-weight: 600;
        }

        .code-block-wrapper pre {
          margin: 0;
          padding: 10px 12px;
          overflow-x: auto;
          background: transparent;
        }
        .code-block-wrapper pre code {
          background: none;
          color: #e2e8f0;
          border: none;
          padding: 0;
          font-size: 0.76rem;
          line-height: 1.45;
          display: block;
          white-space: pre;
        }

        .chat-bubble hr,
        .chat-live-preview-body hr {
          border: none;
          border-top: 1px solid var(--otis-surface-border);
          margin: 10px 0;
          opacity: 0.6;
        }

        .chat-bubble blockquote,
        .chat-live-preview-body blockquote {
          margin: 8px 0;
          padding: 6px 12px;
          border-left: 3px solid var(--otis-primary);
          background: color-mix(in srgb, var(--otis-primary) 8%, transparent);
          border-radius: 0 8px 8px 0;
          color: var(--otis-text-muted);
          font-style: italic;
        }

        .chat-table-wrapper {
          margin: 8px 0;
          overflow-x: auto;
          border-radius: 8px;
          border: 1px solid var(--otis-surface-border);
        }

        .chat-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.78rem;
          text-align: left;
        }

        .chat-table th {
          background: color-mix(in srgb, var(--otis-primary) 15%, transparent);
          color: var(--otis-primary);
          padding: 6px 10px;
          font-weight: 700;
          border-bottom: 1px solid var(--otis-surface-border);
        }

        .chat-table td {
          padding: 6px 10px;
          border-bottom: 1px solid color-mix(in srgb, var(--otis-surface-border) 40%, transparent);
          color: var(--otis-text);
        }

        .chat-table tr:last-child td {
          border-bottom: none;
        }

        .chat-bubble.user {
          position: relative;
          align-self: flex-end;
          background: var(--otis-user-bubble-bg);
          color: var(--otis-user-bubble-text);
          border-bottom-right-radius: 3px;
          border: 1px solid var(--otis-surface-border);
          padding-right: 36px;
        }

        .prompt-copy-btn {
          position: absolute;
          top: 6px;
          right: 6px;
          background: rgba(0, 0, 0, 0.45);
          border: 1px solid rgba(255, 255, 255, 0.25);
          color: rgba(255, 255, 255, 0.9);
          border-radius: 4px;
          width: 24px;
          height: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: all 0.15s ease;
          padding: 0;
          opacity: 0.85;
          z-index: 2;
        }

        .copy-icon {
          width: 13px;
          height: 13px;
          fill: currentColor;
        }

        .chat-bubble.user:hover .prompt-copy-btn,
        .prompt-copy-btn:hover {
          opacity: 1;
          color: #ffffff;
          background: rgba(14, 165, 233, 0.65);
          border-color: rgba(56, 189, 248, 0.8);
          transform: scale(1.1);
        }

        .chat-bubble.user h1,
        .chat-bubble.user h2,
        .chat-bubble.user h3,
        .chat-bubble.user h4 {
          color: inherit;
        }

        .chat-bubble.otis {
          align-self: flex-start;
          background: var(--otis-surface);
          color: var(--otis-text);
          border-bottom-left-radius: 3px;
          border: 1px solid color-mix(in srgb, var(--otis-primary) 20%, transparent);
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
        }

        .chat-bubble.otis.thinking-bubble {
          border-left: 3px solid #c084fc;
          background: linear-gradient(135deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95));
          box-shadow: 0 4px 20px rgba(168, 85, 247, 0.15);
          padding: 12px 16px;
          min-width: 220px;
        }

        .thinking-bubble-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
          font-size: 0.74rem;
        }

        .thinking-status-pill {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 2px 8px;
          background: rgba(168, 85, 247, 0.2);
          border: 1px solid rgba(168, 85, 247, 0.5);
          border-radius: 12px;
          color: #e9d5ff;
          font-size: 0.7rem;
          font-weight: 600;
          letter-spacing: 0.02em;
        }

        .pill-pulse-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #38bdf8;
          box-shadow: 0 0 6px #38bdf8;
          animation: dotBounce 1.2s infinite ease-in-out;
        }

        .thinking-timer {
          margin-left: auto;
          font-family: monospace;
          font-size: 0.74rem;
          color: #38bdf8;
          font-weight: 600;
        }

        .thinking-steps-stream {
          display: flex;
          flex-direction: column;
          gap: 6px;
          margin-bottom: 10px;
          padding: 8px 10px;
          background: rgba(15, 23, 42, 0.6);
          border-radius: 8px;
          border: 1px solid rgba(255, 255, 255, 0.06);
        }

        .thinking-step-row {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          font-size: 0.73rem;
          transition: all 0.25s ease;
        }

        .thinking-step-row.pending {
          opacity: 0.45;
        }

        .thinking-step-row.active {
          opacity: 1;
        }

        .thinking-step-row.done {
          opacity: 0.85;
        }

        .step-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 16px;
          height: 16px;
          flex-shrink: 0;
          font-size: 0.75rem;
          margin-top: 1px;
        }

        .step-indicator.done {
          color: #34d399;
          font-weight: bold;
          text-shadow: 0 0 8px rgba(52, 211, 153, 0.6);
        }

        .step-indicator.active {
          color: #38bdf8;
        }

        .step-indicator.pending {
          color: rgba(255, 255, 255, 0.3);
        }

        .step-mini-spinner {
          display: inline-block;
          width: 11px;
          height: 11px;
          border: 2px solid rgba(56, 189, 248, 0.25);
          border-top-color: #38bdf8;
          border-radius: 50%;
          animation: spin 0.75s linear infinite;
        }

        .step-info {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 1px;
        }

        .step-name {
          font-weight: 600;
          color: #e2e8f0;
        }

        .step-name.active {
          color: #38bdf8;
        }

        .step-name.done {
          color: #cbd5e1;
        }

        .step-sub {
          font-size: 0.68rem;
          color: #94a3b8;
          line-height: 1.25;
        }

        .step-sub.active {
          color: #a5f3fc;
        }

        .step-badge {
          font-family: monospace;
          font-size: 0.66rem;
          color: rgba(255, 255, 255, 0.45);
          align-self: center;
        }

        /* Reasoning Trace Historical View */
        .reasoning-trace-container {
          margin-bottom: 8px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          padding-bottom: 6px;
        }

        .reasoning-trace-toggle {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(168, 85, 247, 0.12);
          border: 1px solid rgba(168, 85, 247, 0.3);
          color: #c084fc;
          border-radius: 6px;
          padding: 3px 8px;
          font-size: 0.71rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .reasoning-trace-toggle:hover {
          background: rgba(168, 85, 247, 0.22);
          border-color: rgba(168, 85, 247, 0.5);
          color: #e9d5ff;
        }

        .reasoning-brain-icon {
          font-size: 0.78rem;
        }

        .reasoning-summary-text {
          font-weight: 500;
        }

        .reasoning-chevron {
          width: 14px;
          height: 14px;
          fill: currentColor;
          transition: transform 0.2s ease;
        }

        .reasoning-trace-toggle.expanded .reasoning-chevron {
          transform: rotate(180deg);
        }

        .reasoning-steps-list {
          margin-top: 6px;
          padding: 6px 10px;
          background: rgba(0, 0, 0, 0.25);
          border-radius: 6px;
          border-left: 2px solid #a855f7;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .reasoning-step-item {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          font-size: 0.71rem;
        }

        .step-check {
          color: #34d399;
          font-weight: bold;
          flex-shrink: 0;
        }

        .step-content {
          flex: 1;
        }

        .step-content .step-title {
          font-weight: 600;
          color: #e2e8f0;
        }

        .step-content .step-detail {
          font-size: 0.67rem;
          color: #94a3b8;
        }

        .step-time {
          font-family: monospace;
          font-size: 0.65rem;
          color: rgba(255, 255, 255, 0.4);
        }

        .chat-thinking-banner {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 9px 14px;
          margin-bottom: 8px;
          background: linear-gradient(135deg, rgba(168, 85, 247, 0.15), rgba(59, 130, 246, 0.12));
          border: 1px solid rgba(168, 85, 247, 0.4);
          border-radius: 12px;
          animation: thinkingPulseGlow 2.5s infinite alternate ease-in-out;
        }

        @keyframes thinkingPulseGlow {
          0% { border-color: rgba(168, 85, 247, 0.35); box-shadow: 0 0 8px rgba(168, 85, 247, 0.12); }
          100% { border-color: rgba(59, 130, 246, 0.65); box-shadow: 0 0 16px rgba(59, 130, 246, 0.28); }
        }

        .thinking-avatar-pulse {
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          width: 30px;
          height: 30px;
          border-radius: 50%;
          background: rgba(168, 85, 247, 0.25);
          flex-shrink: 0;
        }

        .thinking-brain {
          font-size: 1.05rem;
          z-index: 1;
          animation: brainBounce 1.5s infinite ease-in-out;
        }

        @keyframes brainBounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-2px); }
        }

        .thinking-pulse-ring {
          position: absolute;
          inset: -2px;
          border-radius: 50%;
          border: 2px solid rgba(168, 85, 247, 0.6);
          animation: pulseRing 1.8s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
        }

        @keyframes pulseRing {
          0% { transform: scale(0.8); opacity: 1; }
          100% { transform: scale(1.4); opacity: 0; }
        }

        .thinking-text-group {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .thinking-title {
          font-size: 0.8rem;
          font-weight: 700;
          color: #c084fc;
          letter-spacing: 0.02em;
        }

        .thinking-subtitle {
          font-size: 0.69rem;
          color: var(--secondary-text-color, #94a3b8);
        }

        .thinking-dots {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          flex-shrink: 0;
        }

        .thinking-dots span {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #c084fc;
          display: inline-block;
          animation: dotBounce 1.4s infinite ease-in-out both;
        }

        .thinking-dots span:nth-child(1) { animation-delay: -0.32s; }
        .thinking-dots span:nth-child(2) { animation-delay: -0.16s; }

        @keyframes dotBounce {
          0%, 80%, 100% { transform: scale(0); opacity: 0.3; }
          40% { transform: scale(1); opacity: 1; }
        }

        .chat-bubble.error {
          border-color: rgba(244, 63, 94, 0.4);
          color: #fca5a5;
        }

        .chat-live-preview {
          margin-bottom: 8px;
          background: rgba(15, 23, 42, 0.75);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          border: 1px dashed var(--otis-primary);
          border-radius: 12px;
          padding: 8px 12px;
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3), 0 0 10px var(--otis-glow);
          animation: slideDownPreview 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        @keyframes slideDownPreview {
          from {
            opacity: 0;
            transform: translateY(6px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .chat-live-preview-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-size: 0.68rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.6px;
          color: var(--otis-primary);
          margin-bottom: 6px;
          padding-bottom: 4px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        .chat-live-preview-title {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .preview-icon {
          width: 14px;
          height: 14px;
          fill: currentColor;
        }

        .preview-close-btn {
          background: transparent;
          border: none;
          color: var(--otis-text-muted);
          cursor: pointer;
          font-size: 0.8rem;
          line-height: 1;
          padding: 2px 4px;
          border-radius: 4px;
          transition: all 0.15s ease;
        }

        .preview-close-btn:hover {
          color: #f43f5e;
          background: rgba(244, 63, 94, 0.12);
        }

        .chat-live-preview-body {
          max-height: 150px;
          overflow-y: auto;
          font-size: 0.82rem;
          line-height: 1.45;
          color: var(--otis-text);
          padding-right: 4px;
        }

        .chat-live-preview-body h1,
        .chat-live-preview-body h2,
        .chat-live-preview-body h3,
        .chat-live-preview-body h4 {
          margin: 4px 0 2px 0;
          font-weight: 700;
          color: var(--otis-text);
        }

        .chat-live-preview-body h1 { font-size: 1rem; }
        .chat-live-preview-body h2 { font-size: 0.92rem; }
        .chat-live-preview-body h3 { font-size: 0.85rem; }
        .chat-live-preview-body h4 { font-size: 0.8rem; }

        .chat-live-preview-body ul,
        .chat-live-preview-body ol {
          margin: 4px 0 4px 16px;
          padding: 0;
        }

        .chat-live-preview-body li {
          margin-bottom: 2px;
        }

        .chat-live-preview-body p {
          margin: 4px 0;
        }

        .chat-live-preview-body p:first-child {
          margin-top: 0;
        }

        .chat-live-preview-body p:last-child {
          margin-bottom: 0;
        }

        .chat-live-preview-body strong {
          color: var(--otis-primary);
          font-weight: 700;
        }

        .chat-live-preview-body code {
          background: rgba(0, 0, 0, 0.35);
          color: #38bdf8;
          padding: 1px 4px;
          border-radius: 4px;
          font-family: monospace;
          font-size: 0.8em;
        }

        .chat-input-bar {
          display: flex;
          align-items: flex-end;
          gap: 8px;
        }

        .chat-input-wrapper {
          flex: 1;
          display: flex;
          align-items: flex-end;
          background: var(--otis-input-bg);
          border: 1px solid var(--otis-input-border);
          border-radius: 12px;
          padding: 8px 12px;
          min-height: 42px;
          box-sizing: border-box;
          transition: all 0.2s ease;
        }

        .chat-input-wrapper:focus-within {
          border-color: var(--otis-primary);
          box-shadow: 0 0 10px var(--otis-glow);
        }

        .chat-input-wrapper.listening {
          border-color: #f43f5e;
          box-shadow: 0 0 14px rgba(244, 63, 94, 0.35);
          background: rgba(244, 63, 94, 0.08);
        }

        .voice-equalizer {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          height: 18px;
          margin-right: 8px;
          margin-bottom: 3px;
          flex-shrink: 0;
        }

        .equalizer-bar {
          width: 3px;
          background: #f43f5e;
          border-radius: 2px;
          animation: equalizerWave 1s ease-in-out infinite alternate;
        }

        .equalizer-bar:nth-child(1) { height: 6px; animation-delay: 0.1s; }
        .equalizer-bar:nth-child(2) { height: 16px; animation-delay: 0.35s; }
        .equalizer-bar:nth-child(3) { height: 10px; animation-delay: 0.2s; }
        .equalizer-bar:nth-child(4) { height: 18px; animation-delay: 0.45s; }
        .equalizer-bar:nth-child(5) { height: 8px; animation-delay: 0.25s; }

        @keyframes equalizerWave {
          0% {
            height: 4px;
            opacity: 0.4;
          }
          100% {
            height: 18px;
            opacity: 1;
            box-shadow: 0 0 8px rgba(244, 63, 94, 0.8);
          }
        }

        .chat-input {
          flex: 1;
          background: transparent;
          border: none;
          padding: 0;
          margin: 0;
          color: var(--otis-text);
          font-family: inherit;
          font-size: 0.82rem;
          line-height: 1.45;
          outline: none;
          resize: none;
          max-height: 140px;
          min-height: 24px;
          overflow-y: auto;
          box-sizing: border-box;
        }

        .chat-input::placeholder {
          color: var(--otis-text-muted);
        }

        .send-btn, .mic-btn {
          height: 42px;
          box-sizing: border-box;
        }

        .send-btn {
          background: linear-gradient(135deg, var(--otis-primary) 0%, var(--otis-secondary) 100%);
          border: none;
          color: var(--otis-btn-text, #ffffff);
          font-weight: 700;
          padding: 8px 14px;
          border-radius: 10px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .send-btn:hover {
          filter: brightness(1.1);
        }

        .send-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .send-btn.sending {
          background: linear-gradient(135deg, rgba(168, 85, 247, 0.5) 0%, rgba(59, 130, 246, 0.5) 100%);
          border: 1px solid rgba(168, 85, 247, 0.6);
          color: #f1f5f9;
          opacity: 0.9 !important;
          cursor: wait !important;
          gap: 6px;
          padding: 8px 12px;
        }

        .mic-btn {
          background: var(--otis-chip-bg);
          border: 1px solid var(--otis-chip-border);
          color: var(--otis-text-muted);
          width: 38px;
          height: 38px;
          border-radius: 10px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          position: relative;
        }

        .mic-btn:hover {
          background: color-mix(in srgb, var(--otis-primary) 15%, transparent);
          color: var(--otis-primary);
          border-color: color-mix(in srgb, var(--otis-primary) 30%, transparent);
        }

        .mic-btn.listening {
          background: rgba(244, 63, 94, 0.2);
          border-color: #f43f5e;
          color: #f43f5e;
          box-shadow: 0 0 14px rgba(244, 63, 94, 0.4);
          animation: micPulse 1.5s infinite ease-in-out;
        }

        @keyframes micPulse {
          0%, 100% {
            transform: scale(1);
            box-shadow: 0 0 8px rgba(244, 63, 94, 0.3);
          }
          50% {
            transform: scale(1.08);
            box-shadow: 0 0 18px rgba(244, 63, 94, 0.6);
          }
        }

        .mic-icon {
          width: 18px;
          height: 18px;
          fill: currentColor;
        }

        /* Capabilities Drawer */
        .capabilities-panel {
          font-size: 0.8rem;
          color: var(--otis-text-muted);
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .cap-block {
          background: var(--otis-surface);
          border-radius: 10px;
          padding: 10px 14px;
          border: 1px solid var(--otis-surface-border);
        }

        .cap-title {
          font-weight: 600;
          color: var(--otis-text);
          margin-bottom: 4px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .maturity-bar-track {
          width: 100%;
          height: 8px;
          background: rgba(255, 255, 255, 0.08);
          border-radius: 999px;
          overflow: hidden;
          margin: 8px 0;
        }

        .maturity-bar-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--otis-primary) 0%, var(--otis-secondary) 100%);
          border-radius: 999px;
          transition: width 0.4s ease;
        }

        .maturity-grid {
          display: grid;
          grid-template-columns: repeat(5, 1fr);
          gap: 6px;
          margin-top: 8px;
        }

        .maturity-pill {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.07);
          border-radius: 8px;
          padding: 5px 4px;
          text-align: center;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .maturity-pill-val {
          font-size: 0.78rem;
          font-weight: 700;
          color: var(--otis-primary);
        }

        .maturity-pill-lbl {
          font-size: 0.62rem;
          text-transform: uppercase;
          color: var(--otis-text-muted);
        }

        .topo-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 5px;
          margin-top: 6px;
        }

        .topo-tag {
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid rgba(255, 255, 255, 0.09);
          border-radius: 6px;
          padding: 2px 7px;
          font-size: 0.7rem;
          color: var(--otis-text);
        }

        /* Toast */
        .toast {
          position: absolute;
          bottom: 16px;
          left: 50%;
          transform: translateX(-50%) translateY(100px);
          background: var(--otis-primary);
          color: var(--otis-btn-text, #ffffff);
          padding: 8px 16px;
          border-radius: 8px;
          font-size: 0.78rem;
          font-weight: 600;
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
          transition: transform 0.3s cubic-bezier(0.18, 0.89, 0.32, 1.28);
          pointer-events: none;
          z-index: 100;
          white-space: nowrap;
        }

        .toast.error {
          background: #e11d48;
        }

        .toast.show {
          transform: translateX(-50%) translateY(0);
        }

        /* Floorplan Tab & Viewer */
        .floorplan-panel {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .floorplan-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 8px;
          background: var(--otis-surface);
          border: 1px solid var(--otis-surface-border);
          border-radius: 10px;
          padding: 8px 12px;
        }

        .zone-pills {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }

        .zone-pill {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.1);
          color: var(--otis-text-muted);
          border-radius: 20px;
          padding: 4px 10px;
          font-size: 0.72rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .zone-pill:hover {
          background: rgba(255, 255, 255, 0.1);
          color: var(--otis-text);
        }

        .zone-pill.active {
          background: var(--otis-primary);
          color: var(--otis-btn-text, #ffffff);
          border-color: var(--otis-primary);
        }

        .floorplan-actions {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .btn-toolbar {
          background: rgba(255, 255, 255, 0.06);
          border: 1px solid rgba(255, 255, 255, 0.12);
          color: var(--otis-text);
          border-radius: 8px;
          padding: 5px 10px;
          font-size: 0.72rem;
          font-weight: 600;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 5px;
          transition: all 0.2s ease;
        }

        .btn-toolbar:hover {
          background: rgba(255, 255, 255, 0.12);
          border-color: var(--otis-primary);
        }

        .btn-toolbar:disabled,
        .btn-toolbar.disabled {
          opacity: 0.4;
          cursor: not-allowed;
          pointer-events: none;
          background: rgba(255, 255, 255, 0.03);
          border-color: rgba(255, 255, 255, 0.06);
          color: var(--otis-text-muted);
        }

        .walkthrough-pending-banner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          background: rgba(245, 158, 11, 0.1);
          border: 1px solid rgba(245, 158, 11, 0.3);
          border-radius: 10px;
          padding: 8px 12px;
          margin-bottom: 10px;
          font-size: 0.74rem;
          color: #fbbf24;
        }

        .walkthrough-pending-text {
          display: flex;
          align-items: center;
          gap: 8px;
          line-height: 1.35;
        }

        .btn-banner-walkthrough {
          background: #f59e0b;
          color: #0b0f19;
          border: none;
          border-radius: 6px;
          padding: 5px 10px;
          font-size: 0.72rem;
          font-weight: 700;
          cursor: pointer;
          white-space: nowrap;
          transition: background 0.2s;
        }

        .btn-banner-walkthrough:hover {
          background: #d97706;
        }

        .floorplan-svg-viewport {
          background: #090d16;
          border: 1px solid var(--otis-surface-border);
          border-radius: 12px;
          padding: 12px;
          overflow: auto;
          min-height: 480px;
          max-height: 520px;
          display: flex;
          justify-content: center;
          align-items: center;
          position: relative;
          box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.5);
          user-select: none;
        }

        .floorplan-svg-viewport.editor-mode {
          background-image: radial-gradient(rgba(56, 189, 248, 0.15) 1px, transparent 1px);
          background-size: 24px 24px;
          border-color: var(--otis-primary);
        }

        .floorplan-svg-viewport.editor-mode .entity-badge {
          display: inline !important;
          cursor: grab !important;
          filter: drop-shadow(0 0 6px var(--otis-primary)) !important;
        }

        .floorplan-svg-viewport.editor-mode .entity-badge:active {
          cursor: grabbing !important;
        }

        .floorplan-svg-viewport svg {
          width: 100%;
          height: auto;
          max-height: 480px;
          filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.4));
        }

        .editor-toolbar-strip {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: rgba(56, 189, 248, 0.08);
          border: 1px solid rgba(56, 189, 248, 0.3);
          border-radius: 8px;
          padding: 8px 12px;
          gap: 8px;
          flex-wrap: wrap;
          font-size: 0.74rem;
          margin-bottom: 8px;
        }

        .editor-hud {
          position: absolute;
          top: 12px;
          right: 12px;
          background: rgba(15, 23, 42, 0.9);
          border: 1px solid var(--otis-primary);
          color: var(--otis-primary);
          padding: 4px 10px;
          border-radius: 6px;
          font-family: monospace;
          font-size: 0.72rem;
          z-index: 20;
          pointer-events: none;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
        }

        .room-inspector-card {
          position: absolute;
          top: 16px;
          right: 16px;
          background: var(--ha-card-background, #0f172a);
          border: 1.5px solid var(--otis-primary);
          border-radius: 12px;
          padding: 12px 16px;
          z-index: 30;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
          max-width: 320px;
          width: 100%;
          display: flex;
          flex-direction: column;
          gap: 8px;
          font-size: 0.78rem;
          animation: fadeIn 0.2s ease;
          user-select: none;
        }

        .inspector-drag-handle {
          cursor: grab;
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding-bottom: 4px;
          border-bottom: 1px solid var(--otis-surface-border);
        }

        .inspector-drag-handle:active {
          cursor: grabbing;
        }

        .room-resize-handle {
          fill: var(--otis-primary);
          stroke: #ffffff;
          stroke-width: 2;
          cursor: pointer;
          transition: fill 0.15s ease, stroke 0.15s ease;
        }

        .room-resize-handle:hover {
          fill: #ffffff;
          stroke: var(--otis-primary);
          stroke-width: 3;
        }

        .room-resize-handle[data-handle="nw"],
        .room-resize-handle[data-handle="se"] {
          cursor: nwse-resize;
        }

        .room-resize-handle[data-handle="ne"],
        .room-resize-handle[data-handle="sw"] {
          cursor: nesw-resize;
        }

        .room-resize-handle[data-handle="n"],
        .room-resize-handle[data-handle="s"] {
          cursor: ns-resize;
        }

        .room-resize-handle[data-handle="e"],
        .room-resize-handle[data-handle="w"] {
          cursor: ew-resize;
        }

        .room-info-card {
          background: var(--otis-surface);
          border: 1px solid var(--otis-primary);
          border-radius: 10px;
          padding: 10px 14px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          animation: fadeIn 0.3s ease;
        }

        /* Walkthrough Modal */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.75);
          backdrop-filter: blur(6px);
          display: flex;
          justify-content: center;
          align-items: center;
          z-index: 1000;
          padding: 16px;
        }

        .modal-card {
          background: var(--otis-bg, #0f172a);
          border: 1px solid var(--otis-primary);
          box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6), 0 0 24px rgba(14, 165, 233, 0.2);
          border-radius: 16px;
          width: 100%;
          max-width: 520px;
          max-height: 90vh;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 20px;
          position: relative;
          color: var(--otis-text, #f8fafc);
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
        }

        .modal-title {
          font-size: 1.05rem;
          font-weight: 700;
          color: var(--otis-text);
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .modal-subtitle {
          font-size: 0.75rem;
          color: var(--otis-text-muted);
          margin-top: 2px;
        }

        .modal-close-btn {
          background: transparent;
          border: none;
          color: var(--otis-text-muted);
          font-size: 1.2rem;
          cursor: pointer;
          padding: 4px;
          line-height: 1;
          border-radius: 4px;
        }

        .modal-close-btn:hover {
          color: #fff;
          background: rgba(255, 255, 255, 0.1);
        }

        .guide-box {
          background: rgba(14, 165, 233, 0.08);
          border: 1px solid rgba(14, 165, 233, 0.2);
          border-radius: 10px;
          padding: 12px;
          font-size: 0.75rem;
          line-height: 1.45;
          color: #bae6fd;
        }

        .guide-box strong {
          color: #38bdf8;
        }

        .guide-box ol {
          margin: 6px 0 0 16px;
          padding: 0;
        }

        .dropzone {
          border: 2px dashed rgba(255, 255, 255, 0.2);
          border-radius: 12px;
          padding: 24px 16px;
          text-align: center;
          cursor: pointer;
          background: rgba(255, 255, 255, 0.02);
          transition: all 0.2s ease;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
        }

        .dropzone:hover, .dropzone.dragover {
          border-color: var(--otis-primary);
          background: rgba(14, 165, 233, 0.06);
        }

        .dropzone-icon {
          font-size: 2rem;
        }

        .dropzone-text {
          font-size: 0.82rem;
          font-weight: 600;
          color: var(--otis-text);
        }

        .dropzone-sub {
          font-size: 0.7rem;
          color: var(--otis-text-muted);
        }

        .order-input-group {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .order-input-group label {
          font-size: 0.72rem;
          font-weight: 600;
          color: var(--otis-text-muted);
        }

        .order-input-group input {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid var(--otis-surface-border);
          border-radius: 8px;
          padding: 8px 12px;
          color: var(--otis-text);
          font-size: 0.78rem;
          outline: none;
        }

        .order-input-group input:focus {
          border-color: var(--otis-primary);
        }

        .modal-actions {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-top: 4px;
        }

        .btn-modal-primary {
          background: var(--otis-primary);
          color: var(--otis-btn-text, #ffffff);
          border: none;
          border-radius: 10px;
          padding: 10px 16px;
          font-weight: 700;
          font-size: 0.84rem;
          cursor: pointer;
          display: flex;
          justify-content: center;
          align-items: center;
          gap: 8px;
          transition: all 0.2s ease;
        }

        .btn-modal-primary:hover:not(:disabled) {
          filter: brightness(1.1);
          box-shadow: 0 4px 14px rgba(14, 165, 233, 0.4);
        }

        .btn-modal-primary:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .btn-modal-secondary {
          background: transparent;
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: var(--otis-text);
          border-radius: 10px;
          padding: 8px 16px;
          font-weight: 600;
          font-size: 0.78rem;
          cursor: pointer;
          transition: all 0.2s ease;
          text-align: center;
        }

        .btn-modal-secondary:hover:not(:disabled) {
          background: rgba(255, 255, 255, 0.08);
          border-color: var(--otis-primary);
        }
      </style>

      <ha-card class="card-container ${themeClass} ${isStudioMode ? "mode-floorplan-studio" : ""}">
        ${
          isStudioMode
            ? `
          <!-- Studio Header (Full Width Blueprint Workspace) -->
          <div class="studio-header">
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
              <button type="button" class="btn-toolbar" id="btn-back-dashboard" title="Return to Dashboard">
                ← Back
              </button>
              <div class="title-group">
                <span class="main-title">🗺️ ${isControlMode ? "Interactive Floor Plan" : "Architectural Floor Plan Studio"}</span>
                <span class="sub-title">
                  <span class="status-dot"></span>
                  ${this._editorActive ? "Canvas Editor Mode Active • Drag pins & resize rooms" : (isControlMode ? "Live Home Control Surface • Tap devices to control" : "Interactive Blueprint Viewer")}
                </span>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              ${
                isAdmin
                  ? `
                <button type="button" class="btn-toolbar ${this._editorActive ? 'active' : ''}" id="btn-toggle-editor" style="${this._editorActive ? 'background: var(--otis-primary); color: var(--otis-btn-text, #ffffff); border-color: var(--otis-primary);' : ''}">
                  ${this._editorActive ? "🛠️ Exit Editor" : "✏️ Edit Blueprint"}
                </button>
              `
                  : ""
              }
              <button type="button" class="icon-btn" id="refresh-btn" title="Refresh floor plan">
                ↻ Refresh
              </button>
            </div>
          </div>
          ${this._renderFloorplanTab()}
        `
            : `
          <!-- Header -->
          <div class="card-header">
            <div class="brand-section">
              <div class="emblem-icon">
                <svg viewBox="0 0 24 24">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                  <polyline points="9 22 9 12 15 12 15 22"></polyline>
                </svg>
              </div>
              <div class="title-group">
                <span class="main-title">${this._config.title || "Otis AI Companion"}</span>
                <span class="sub-title">
                  <span class="status-dot"></span>
                  Autonomous Co-Pilot Active
                </span>
              </div>
            </div>
            <div class="header-actions">
              <button type="button" class="icon-btn" id="refresh-btn" title="Refresh intelligence">
                ↻ Refresh
              </button>
            </div>
          </div>

          <!-- Quick Stats Bar -->
          ${
            this._config.show_stats !== false
              ? `
            <div class="stats-bar">
              <div class="stat-item">
                <span class="stat-value">${stats.areas}</span>
                <span class="stat-label">Areas</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">${stats.entities}</span>
                <span class="stat-label">Entities</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">${stats.automations}</span>
                <span class="stat-label">Automations</span>
              </div>
              <div class="stat-item ${stats.orphans > 0 ? "warning" : ""}">
                <span class="stat-value">${stats.orphans}</span>
                <span class="stat-label">Orphans</span>
              </div>
            </div>
          `
              : ""
          }

          <!-- Studio & Room Subviews Launchpad -->
          <div class="subviews-launchpad">
            <div class="launchpad-row">
              <span class="subviews-label">Studios:</span>
              <button type="button" class="subview-chip" data-subview="${dashPrefix}/media">🎵 Media Studio</button>
              <button type="button" class="subview-chip" data-subview="${dashPrefix}/security">🛡️ Security Center</button>
              <button type="button" class="subview-chip" data-subview="${dashPrefix}/climate">🌡️ Climate & Pool</button>
              <button type="button" class="subview-chip" data-subview="${dashPrefix}/floorplan">🗺️ Floor Plan</button>
              ${isAdmin ? `<button type="button" class="subview-chip" id="btn-sync-dashboards" title="Sync all Studios & Rooms to Command Center" style="margin-left: auto;">🔄 Sync Command Center</button>` : ""}
              <button type="button" class="subview-chip" id="btn-open-themes" style="${isAdmin ? "" : "margin-left: auto;"}">🎨 Themes</button>
            </div>
            ${
              activeAreas.length > 0
                ? `
              <div class="launchpad-row">
                <span class="subviews-label">Rooms:</span>
                ${activeAreas
                  .map(
                    (room) => `
                  <button type="button" class="subview-chip room-chip" data-subview="${room.path}">${this._getRoomEmoji(room.name)} ${this._escapeHtml(room.name)}</button>
                `
                  )
                  .join("")}
              </div>
            `
                : ""
            }
          </div>

          <!-- Navigation Tabs -->
          <div class="tabs-nav">
            ${
              this._config.show_suggestions !== false
                ? `
              <button type="button" class="tab-btn ${this._activeTab === "suggestions" ? "active" : ""}" id="tab-suggestions">
                Proactive Feed
                ${activeSuggestions.length > 0 ? `<span class="tab-badge">${activeSuggestions.length}</span>` : ""}
              </button>
            `
                : ""
            }
            ${
              this._config.show_chat !== false
                ? `
              <button type="button" class="tab-btn ${this._activeTab === "chat" ? "active" : ""}" id="tab-chat">
                Assist Co-Pilot
              </button>
            `
                : ""
            }
            <button type="button" class="tab-btn ${this._activeTab === "floorplan" ? "active" : ""}" id="tab-floorplan">
              Floor Plan
              ${this._capabilityMap?.floorplan?.exists ? "" : `<span class="tab-badge" style="background: var(--otis-accent, #a855f7);">New</span>`}
            </button>
            <button type="button" class="tab-btn ${this._activeTab === "capabilities" ? "active" : ""}" id="tab-capabilities">
              Capabilities
            </button>
          </div>

          ${this._activeTab === "suggestions" ? this._renderSuggestionsTab(visibleSuggestions) : ""}
          ${this._activeTab === "chat" ? this._renderChatTab() : ""}
          ${this._activeTab === "capabilities" ? this._renderCapabilitiesTab(stats) : ""}
          ${this._activeTab === "floorplan" ? this._renderFloorplanTab() : ""}
        `
        }

        ${this._floorplanModalOpen ? this._renderWalkthroughModal() : ""}
        ${this._themeModalOpen ? this._renderThemeModal() : ""}
        ${this._addMarkerModalOpen ? this._renderAddMarkerModal() : ""}

        <!-- Feedback Toast -->
        <div class="toast" id="toast"></div>
      </ha-card>
    `;

    this._bindEvents();
  }

  _renderSuggestionsTab(visibleSuggestions) {
    const categories = [
      { key: "all", label: "All" },
      { key: "lighting", label: "Lighting & Auto" },
      { key: "media", label: "Media" },
      { key: "security", label: "Security" },
      { key: "dashboard", label: "Dashboards" },
      { key: "cleanup", label: "Cleanup" },
      { key: "system", label: "System" },
    ];
    return `
      <div class="category-pills">
        ${categories
          .map(
            (c) => `
          <button type="button" class="category-pill ${this._selectedCategory === c.key ? "active" : ""}" data-category-pill="${c.key}">
            ${c.label}
          </button>
        `
          )
          .join("")}
      </div>
      <div class="suggestions-list">
        ${
          this._loadingSuggestions
            ? `<div class="empty-state"><div class="spinner" style="margin: 0 auto 8px auto; width: 20px; height: 20px;"></div>Analyzing home capabilities...</div>`
            : visibleSuggestions.length === 0
            ? `<div class="empty-state"><div class="empty-icon">✨</div>${
                this._selectedCategory === "all"
                  ? "Your smart home is running optimally! No proactive recommendations right now."
                  : `No active recommendations in the "${this._selectedCategory}" category.`
              }</div>`
            : visibleSuggestions
                .map((s) => {
                  const isApplying = this._applyingIds.has(s.id);
                  const btnLabel = this._getActionLabel(s.action_type);
                  return `
                    <div class="suggestion-card" data-id="${s.id}">
                      <div class="suggestion-top">
                        <div class="suggestion-badge-group">
                          <span class="badge-category">${s.category || "automation"}</span>
                          <span class="badge-priority ${s.priority || "medium"}">${s.priority || "medium"}</span>
                        </div>
                        <button type="button" class="dismiss-btn" data-dismiss="${s.id}" title="Dismiss recommendation">✕</button>
                      </div>
                      <div class="suggestion-title">${s.title}</div>
                      <div class="suggestion-desc">${s.description}</div>
                      <div class="suggestion-actions">
                        ${
                          s.action_type === "sentinel_alert_actions"
                            ? `
                          <div style="display: flex; gap: 8px; flex-wrap: wrap; width: 100%;">
                            <button type="button" class="btn-toolbar btn-ignore-alert" data-ignore-id="${s.id}" style="padding: 6px 12px; font-size: 0.76rem;">
                              ${s.action_payload?.dismiss_single_label || "Ignore this alert"}
                            </button>
                            <button type="button" class="btn-toolbar btn-ignore-category" data-ignore-cat="${s.action_payload?.category || s.anomaly_type || 'battery'}" style="padding: 6px 12px; font-size: 0.76rem; color: var(--otis-primary); border-color: var(--otis-primary);">
                              ${s.action_payload?.dismiss_category_label || "Ignore all alerts in this category"}
                            </button>
                          </div>
                        `
                            : `
                          <button type="button" class="apply-btn" data-apply="${s.id}" ${isApplying ? "disabled" : ""}>
                            ${isApplying ? `<div class="spinner"></div> Applying...` : btnLabel}
                          </button>
                        `
                        }
                      </div>
                    </div>
                  `;
                })
                .join("")
        }
      </div>
    `;
  }

  _renderChatActionButtons(m) {
    if (m.sender !== "otis" || m.isError) return "";
    const txt = m.text || "";
    if (txt.includes("Say 'yes' or 'confirm'") || txt.includes("Say 'yes' or 'apply'")) {
      return `
        <div class="chat-macro-actions">
          <button type="button" class="macro-action-btn confirm" data-chip="confirm">✅ Confirm & Execute</button>
          <button type="button" class="macro-action-btn cancel" data-chip="cancel">✕ Cancel</button>
        </div>
      `;
    }
    if (txt.includes("Say 'undo' or 'rollback'")) {
      return `
        <div class="chat-macro-actions">
          <button type="button" class="macro-action-btn rollback" data-chip="undo macro">↺ Rollback / Undo Macro</button>
        </div>
      `;
    }
    return "";
  }

  _renderReasoningTrace(m) {
    const traceId = m.id || m.timestamp || m.text;
    const isExpanded = this._expandedReasoningIds.has(traceId);
    return `
      <div class="reasoning-trace-container">
        <button type="button" class="reasoning-trace-toggle ${isExpanded ? "expanded" : ""}" data-trace-id="${this._escapeHtml(traceId)}">
          <span class="reasoning-brain-icon">🧠</span>
          <span class="reasoning-summary-text">Thought for ${this._escapeHtml(m.reasoning.duration || "a moment")} (${m.reasoning.steps.length} steps)</span>
          <svg class="reasoning-chevron" viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
        </button>
        ${
          isExpanded
            ? `
          <div class="reasoning-steps-list">
            ${m.reasoning.steps
              .map(
                (s) => `
              <div class="reasoning-step-item done">
                <span class="step-check">✓</span>
                <div class="step-content">
                  <div class="step-title">${this._escapeHtml(s.title || "Step")}</div>
                  <div class="step-detail">${this._escapeHtml(s.detail || "")}</div>
                </div>
                <span class="step-time">${this._escapeHtml(s.time || "")}</span>
              </div>
            `
              )
              .join("")}
          </div>
        `
            : ""
        }
      </div>
    `;
  }

  _renderChatTab() {
    return `
      <div class="chat-container">
        <div class="chat-chips">
          <button type="button" class="chip-btn" data-chip="Prep home for movie night">🎬 Movie Night</button>
          <button type="button" class="chip-btn" data-chip="Goodnight routine">🌙 Goodnight</button>
          <button type="button" class="chip-btn" data-chip="Party mode">🥂 Party Mode</button>
          <button type="button" class="chip-btn" data-chip="Lockdown home">🛡️ Lockdown</button>
          <button type="button" class="chip-btn" data-chip="Handoff audio to study">🎵 Audio Handoff</button>
          <button type="button" class="chip-btn" data-chip="Release idle sources">🔇 Idle Guard</button>
          <button type="button" class="chip-btn" data-chip="Undo last macro">↺ Undo</button>
          <button type="button" class="chip-btn" data-chip="Suggest automations for my active areas">💡 Automations</button>
          <button type="button" class="chip-btn" data-chip="Clean up orphaned entities">🧹 Clean orphans</button>
          <button type="button" class="chip-btn" id="btn-clear-chat" title="Clear conversation history">🗑️ Clear</button>
        </div>
        <div class="chat-history" id="chat-history">
          ${
            this._chatMessages.length === 0
              ? `<div class="empty-state" style="padding: 16px;">Ask Otis anything about your automations, devices, or areas.</div>`
              : this._chatMessages
                  .map(
                    (m) => `
                <div class="chat-bubble ${m.sender} ${m.isError ? "error" : ""}">
                  ${
                    m.sender === "user"
                      ? `
                    <button type="button" class="prompt-copy-btn" title="Copy prompt to input" data-prompt="${this._escapeHtml(m.text)}">
                      <svg viewBox="0 0 24 24" class="copy-icon">
                        <path d="M16 1H4C2.9 1 2 1.9 2 3v14h2V3h12V1zm3 4H8C6.9 5 6 5.9 6 7v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                      </svg>
                    </button>
                  `
                      : ""
                  }
                  ${
                    m.sender === "otis" && m.reasoning && m.reasoning.steps && m.reasoning.steps.length
                      ? this._renderReasoningTrace(m)
                      : ""
                  }
                  ${this._renderMarkdown(m.text)}
                  ${this._renderChatActionButtons(m)}
                </div>
              `
                  )
                  .join("")
          }
          ${
            this._isSendingChat
              ? `
            <div class="chat-bubble otis thinking-bubble" id="active-thinking-bubble">
              <div class="thinking-bubble-header">
                <span class="otis-badge">🤖 Otis</span>
                <span class="thinking-status-pill">
                  <span class="pill-pulse-dot"></span>
                  <span id="thinking-pill-text">Reasoning</span>
                </span>
                <span class="thinking-timer" id="thinking-elapsed-timer">⏱️ 0.0s</span>
              </div>
              <div class="thinking-steps-stream" id="thinking-steps-stream">
                ${this._renderThinkingStepsStream()}
              </div>
              <div class="thinking-wave-container">
                <div class="typing-wave">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <span class="thinking-stage-text" id="thinking-stage-text">${this._escapeHtml(this._getCurrentThinkingStatus())}</span>
              </div>
            </div>
          `
              : ""
          }
        </div>
        <div class="chat-live-preview" id="chat-live-preview" style="display: none;">
          <div class="chat-live-preview-header">
            <div class="chat-live-preview-title">
              <svg viewBox="0 0 24 24" class="preview-icon">
                <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/>
              </svg>
              <span>Markdown Live Preview</span>
            </div>
            <button type="button" class="preview-close-btn" id="chat-preview-close" title="Dismiss preview">✕</button>
          </div>
          <div class="chat-live-preview-body" id="chat-live-preview-body"></div>
        </div>
        ${
          this._isSendingChat
            ? `
          <div class="chat-thinking-banner">
            <div class="thinking-avatar-pulse">
              <span class="thinking-brain">🧠</span>
              <span class="thinking-pulse-ring"></span>
            </div>
            <div class="thinking-text-group">
              <div class="thinking-title" id="thinking-banner-title">Otis is reasoning: ${this._escapeHtml(this._getCurrentThinkingTitle())}</div>
              <div class="thinking-subtitle" id="thinking-banner-sub">${this._escapeHtml(this._getCurrentThinkingStatus())}</div>
            </div>
            <div class="thinking-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        `
            : ""
        }
        <div class="chat-input-bar">
          <div class="chat-input-wrapper ${this._isListening ? "listening" : ""} ${this._isSendingChat ? "sending" : ""}">
            ${
              this._isListening
                ? `
              <div class="voice-equalizer" title="Listening to speech...">
                <span class="equalizer-bar"></span>
                <span class="equalizer-bar"></span>
                <span class="equalizer-bar"></span>
                <span class="equalizer-bar"></span>
                <span class="equalizer-bar"></span>
              </div>
            `
                : ""
            }
            <textarea
              class="chat-input"
              id="chat-input"
              rows="1"
              ${this._isSendingChat ? "disabled" : ""}
              placeholder="${this._isSendingChat ? "Otis is reasoning & formulating response... please wait" : (this._isListening ? "Listening... speak now" : "Ask Otis or give a voice/text command... (Shift+Enter for newline)")}"
            >${this._draftChatText || ""}</textarea>
          </div>
          <button type="button" class="mic-btn ${this._isListening ? "listening" : ""}" id="chat-mic" title="${this._isListening ? "Listening... click to stop" : "Voice command"}" ${this._isSendingChat ? "disabled" : ""}>
            <svg viewBox="0 0 24 24" class="mic-icon">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
          </button>
          <button type="button" class="send-btn ${this._isSendingChat ? "sending" : ""}" id="chat-send" ${this._isSendingChat ? "disabled" : ""}>
            ${
              this._isSendingChat
                ? `<div class="spinner" style="display:inline-block; vertical-align:middle; width:12px; height:12px;"></div> Thinking...`
                : "Send"
            }
          </button>
        </div>
      </div>
    `;
  }

  _renderCapabilitiesTab(stats) {
    const namedAdj = Object.entries(this._capabilityMap?.spatial_graph?.named_adjacencies || {}).filter(
      ([_, nbrs]) => nbrs && nbrs.length > 0
    );
    const integrations = this._capabilityMap?.integrations || [];
    const maturity = this._capabilityMap?.maturity || {};
    const mScore = maturity.score ?? 50;
    const mStage = maturity.stage || "Configured Foundation";
    const bd = maturity.breakdown || {};
    const inferredCount =
      Object.keys(maturity.inferred_device_assignments || {}).length +
      Object.keys(maturity.inferred_entity_assignments || {}).length;

    const mediaTopo = this._capabilityMap?.media_topology || {};
    const matrixZones = mediaTopo.matrix_zones || [];
    const sharedSources = mediaTopo.shared_sources || [];
    const inputStreamers = mediaTopo.input_streamers || [];
    const tvZones = mediaTopo.tv_cinema_zones || [];

    const secTopo = this._capabilityMap?.security_topology || {};
    const alarmPanels = secTopo.alarm_panels || [];
    const locks = secTopo.locks || [];
    const garageCovers = secTopo.garage_covers || [];
    const sirens = secTopo.sirens || [];
    const cameras = secTopo.cameras || [];
    const bedSensors = secTopo.bed_occupancy_sensors || [];

    return `
      <div class="capabilities-panel">
        <div class="cap-block">
          <div class="cap-title">
            <span>Smart Home Maturity Score</span>
            <span style="color: var(--otis-primary); font-weight: 700;">${mScore} / 100 • ${mStage}</span>
          </div>
          <div class="maturity-bar-track">
            <div class="maturity-bar-fill" style="width: ${Math.min(100, Math.max(0, mScore))}%;"></div>
          </div>
          <div class="maturity-grid">
            <div class="maturity-pill">
              <span class="maturity-pill-val">${bd.spatial ?? 0}/20</span>
              <span class="maturity-pill-lbl">Spatial</span>
            </div>
            <div class="maturity-pill">
              <span class="maturity-pill-val">${bd.hygiene ?? 0}/20</span>
              <span class="maturity-pill-lbl">Hygiene</span>
            </div>
            <div class="maturity-pill">
              <span class="maturity-pill-val">${bd.automation ?? 0}/20</span>
              <span class="maturity-pill-lbl">Automations</span>
            </div>
            <div class="maturity-pill">
              <span class="maturity-pill-val">${bd.security ?? 0}/20</span>
              <span class="maturity-pill-lbl">Security</span>
            </div>
            <div class="maturity-pill">
              <span class="maturity-pill-val">${bd.media ?? 0}/20</span>
              <span class="maturity-pill-lbl">Media</span>
            </div>
          </div>
          ${
            inferredCount > 0
              ? `<div style="margin-top: 8px; font-size: 0.72rem; color: #fbbf24;">📍 ${inferredCount} unassigned device(s)/entities can be auto-assigned to rooms via the Proactive Feed.</div>`
              : ""
          }
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>Media &amp; Matrix Audio Architecture</span>
            <span>${
              mediaTopo.matrix_amp_detected
                ? `Matrix Amp (${matrixZones.length} Zones)`
                : `${mediaTopo.total_media_players || 0} Media Players`
            }</span>
          </div>
          <div style="font-size: 0.75rem; line-height: 1.4;">
            ${
              mediaTopo.matrix_amp_detected
                ? `
                  <div><strong>Output Zones:</strong> ${matrixZones.map((z) => z.name).join(", ")}</div>
                  ${
                    sharedSources.length > 0
                      ? `<div style="margin-top: 3px;"><strong>Shared Inputs:</strong> ${sharedSources.join(", ")}</div>`
                      : ""
                  }
                  ${
                    inputStreamers.length > 0
                      ? `<div style="margin-top: 3px;"><strong>Upstream Streamers:</strong> ${inputStreamers.map((s) => s.name).join(", ")}</div>`
                      : ""
                  }
                `
                : `<div>No multi-zone matrix audio amplifier detected.</div>`
            }
            ${
              tvZones.length > 0
                ? `<div style="margin-top: 3px;"><strong>Cinema / TV Displays:</strong> ${tvZones.map((t) => t.name).join(", ")}</div>`
                : ""
            }
          </div>
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>Security &amp; Presence Architecture</span>
            <span>${secTopo.ready_for_unified_coordinator ? "Coordinator Ready" : "Basic"}</span>
          </div>
          <div class="topo-tags">
            <span class="topo-tag">🛡️ Alarm Panels: ${alarmPanels.length}</span>
            <span class="topo-tag">🔒 Smart Locks: ${locks.length}</span>
            <span class="topo-tag">🚗 Garage Doors: ${garageCovers.length}</span>
            <span class="topo-tag">🚨 Sirens: ${sirens.length}</span>
            <span class="topo-tag">📷 Cameras: ${cameras.length}</span>
            <span class="topo-tag">🛏️ Bed Sensors: ${bedSensors.length}</span>
          </div>
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>Mapped Areas</span>
            <span>${stats.areas}</span>
          </div>
          <div>${Object.values(this._capabilityMap?.areas || {})
            .map((a) => a.name)
            .join(", ") || "No areas configured"}</div>
        </div>
        <div class="cap-block">
          <div class="cap-title">
            <span>Spatial Adjacency Graph</span>
            <span>${this._capabilityMap?.spatial_graph?.connection_count || 0} Connections</span>
          </div>
          <div class="spatial-graph-list" style="font-size: 0.76rem; line-height: 1.4; display: flex; flex-direction: column; gap: 4px; max-height: 160px; overflow-y: auto; padding-right: 4px;">
            ${
              namedAdj.length === 0
                ? `<div>No spatial connections mapped yet.</div>`
                : namedAdj
                    .map(
                      ([area, nbrs]) => `
                      <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); padding: 4px 8px; border-radius: 6px;">
                        <strong style="color: var(--otis-primary);">${area}</strong>
                        <span style="color: var(--otis-text-muted); margin: 0 4px;">↔</span>
                        <span style="color: var(--otis-text);">${nbrs.join(", ")}</span>
                      </div>
                    `
                    )
                    .join("")
            }
          </div>
        </div>
        <div class="cap-block">
          <div class="cap-title">
            <span>Active Integrations</span>
            <span>${integrations.length}</span>
          </div>
          <div style="font-size: 0.72rem; line-height: 1.3;">
            ${integrations.slice(0, 16).join(", ")}
            ${integrations.length > 16 ? "... and more" : ""}
          </div>
        </div>
        <div class="cap-block">
          <div class="cap-title">
            <span>Orphaned Entities</span>
            <span>${stats.orphans}</span>
          </div>
          <div>${
            stats.orphans === 0
              ? "Registry is clean! Zero orphaned entities detected."
              : `${stats.orphans} stale or disconnected entities found. Use the Proactive Feed to clean them up.`
          }</div>
        </div>
      </div>
    `;
  }

  _renderFloorplanTab() {
    const isControlOnly = this._config.mode === "floorplan_control";
    const isAdmin = Boolean(this._hass?.user?.is_admin || this._hass?.user?.is_owner);

    return `
      <div class="floorplan-panel">
        <div class="floorplan-toolbar">
          <div class="zone-pills">
            <button type="button" class="zone-pill ${this._selectedFloorZone === "all" ? "active" : ""}" data-zone="all">All Floors</button>
            <button type="button" class="zone-pill ${this._selectedFloorZone === "main" ? "active" : ""}" data-zone="main">Ground &amp; Outdoor</button>
            <button type="button" class="zone-pill ${this._selectedFloorZone === "upper" ? "active" : ""}" data-zone="upper">Upper Level</button>
            <button type="button" class="zone-pill ${this._selectedFloorZone === "outdoor" ? "active" : ""}" data-zone="outdoor">Outdoor Only</button>
          </div>
          <div class="floorplan-actions">
            ${
              !isControlOnly
                ? `
              <button type="button" class="btn-toolbar" id="btn-open-walkthrough" title="Record video walkthrough to generate or update floor plan">
                📹 Walkthrough
              </button>
              <button type="button" 
                class="btn-toolbar ${!this._hasWalkthrough ? 'disabled' : ''}" 
                id="btn-copy-lovelace" 
                ${!this._hasWalkthrough ? "disabled" : ""}
                title="${this._hasWalkthrough ? 'Copy Lovelace Dashboard YAML for picture-elements card' : 'Complete a video walkthrough first to unlock Lovelace YAML export'}"
              >
                📋 Lovelace YAML
              </button>
            `
                : ""
            }
            ${
              isAdmin
                ? `
              <button type="button" 
                class="btn-toolbar ${this._editorActive ? 'active' : ''}" 
                id="btn-toggle-editor"
                style="${this._editorActive ? 'background: var(--otis-primary); color: var(--otis-btn-text, #ffffff); border-color: var(--otis-primary);' : ''}"
                title="Toggle Interactive Canvas Editor to drag pins and adjust room boundaries"
              >
                ${this._editorActive ? "🛠️ Exit Editor" : "✏️ Canvas Editor"}
              </button>
            `
                : ""
            }
          </div>
        </div>

        ${
          this._editorActive
            ? `
          <div class="editor-toolbar-strip">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-weight: 700; color: var(--otis-primary);">🛠️ Layout Adjuster:</span>
              <span style="color: var(--otis-text-muted);">Drag pins or select room boundaries to reposition &amp; resize</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
              <button type="button" class="btn-toolbar" id="btn-open-add-marker" style="padding: 4px 8px;">
                ➕ Add Pin
              </button>
              <button type="button" class="btn-modal-primary" id="btn-save-layout" style="padding: 4px 10px; font-size: 0.74rem;" ${this._savingLayout ? "disabled" : ""}>
                ${this._savingLayout ? `<div class="spinner" style="width: 12px; height: 12px;"></div> Saving...` : (this._hasUnsavedLayout ? "💾 Save Changes *" : "💾 Save Layout")}
              </button>
              <button type="button" class="btn-toolbar" id="btn-exit-editor" style="padding: 4px 8px; color: var(--otis-text-muted);">
                ✕ Exit
              </button>
            </div>
          </div>
        `
            : ""
        }

        ${
          !isControlOnly && !this._hasWalkthrough && this._floorplanSvg && !this._editorActive
            ? `
          <div class="walkthrough-pending-banner">
            <div class="walkthrough-pending-text">
              <span style="font-size: 1rem;">📹</span>
              <span><strong>Walkthrough Pending:</strong> Current layout is an initial area estimate. Record or upload a video walkthrough calling out rooms to calibrate dimensions and unlock Lovelace YAML.</span>
            </div>
            <button type="button" class="btn-banner-walkthrough" id="btn-banner-walkthrough">Start Walkthrough</button>
          </div>
        `
            : ""
        }

        ${
          this._loadingFloorplan
            ? `<div class="empty-state"><div class="spinner" style="margin: 0 auto 8px auto; width: 24px; height: 24px;"></div>Rendering vector floor plan...</div>`
            : this._floorplanSvg
            ? `
            <div class="floorplan-svg-viewport ${this._editorActive ? 'editor-mode' : ''}" id="floorplan-viewport">
              ${this._editorActive ? `<div class="editor-hud" id="editor-hud">📐 Pointer: --, --</div>` : ''}
              ${this._floorplanSvg}
              ${this._editorActive && this._selectedEditorRoomId ? this._renderRoomInspector() : ""}
            </div>
            ${
              !this._editorActive && this._selectedRoomInfo
                ? `
              <div class="room-info-card" style="padding: 12px 16px; border-radius: 12px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); margin-top: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                  <div>
                    <div style="font-weight: 700; color: var(--otis-primary); font-size: 0.95rem;">📍 ${this._selectedRoomInfo.name}</div>
                    <div style="font-size: 0.74rem; color: var(--otis-text-muted);">
                      Zone: ${String(this._selectedRoomInfo.zone).toUpperCase()} • ${this._selectedRoomInfo.entities.length} Devices
                    </div>
                  </div>
                  <div style="display: flex; gap: 8px;">
                    ${this._selectedRoomInfo.slug ? `
                    <button type="button" class="btn-toolbar btn-nav-room" data-room-path="/otis-ai/area_${this._selectedRoomInfo.slug}" style="padding: 4px 10px; font-size: 0.75rem;">
                      Open Room Controls →
                    </button>
                    ` : ""}
                    <button type="button" class="btn-toolbar" id="btn-close-room-info" style="padding: 4px 8px;">✕</button>
                  </div>
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                  ${this._selectedRoomInfo.entities.slice(0, 10).map((eid) => {
                    const st = this._hass?.states?.[eid];
                    if (!st) return "";
                    const isOn = st.state === "on";
                    const icon = st.attributes?.icon || (eid.startsWith("light.") ? "💡" : eid.startsWith("switch.") ? "🔌" : eid.startsWith("climate.") ? "🌡️" : "⚡");
                    return `
                      <button type="button" class="subview-chip btn-quick-toggle" data-entity-id="${eid}" style="${isOn ? 'background: var(--otis-primary); color: #fff; border-color: var(--otis-primary);' : ''}">
                        ${icon} ${st.attributes?.friendly_name || eid.split(".")[1]} (${st.state})
                      </button>
                    `;
                  }).join("")}
                </div>
              </div>
            `
                : ""
            }
          `
            : `
            <div class="empty-state" style="padding: 30px 16px;">
              <div class="empty-icon" style="font-size: 2.2rem; margin-bottom: 8px;">📐</div>
              <div style="font-weight: 700; font-size: 0.95rem; margin-bottom: 6px; color: var(--otis-text);">
                Interactive Multimodal Floor Plan
              </div>
              <div style="font-size: 0.78rem; line-height: 1.45; color: var(--otis-text-muted); max-width: 360px; margin: 0 auto 16px auto;">
                Record a mobile video walkthrough calling out each room as you enter. Otis AI will extract the audio callouts, map wall boundaries, and build a multi-floor interactive vector dashboard.
              </div>
              <div style="display: flex; gap: 8px; justify-content: center; flex-wrap: wrap;">
                <button type="button" class="btn-modal-primary" id="btn-start-walkthrough">
                  📹 Record / Upload Walkthrough
                </button>
                <button type="button" class="btn-modal-secondary" id="btn-quick-generate">
                  ⚡ Instant Generate from Registered Areas
                </button>
              </div>
            </div>
          `
        }
      </div>
    `;
  }

  _renderRoomInspector() {
    const rid = this._selectedEditorRoomId;
    if (!rid) return "";
    const area = this._capabilityMap?.areas?.[rid] || { name: rid };
    const allAreas = Object.entries(this._capabilityMap?.areas || {}).map(([id, a]) => ({
      id,
      name: a.name || id,
    }));
    const posStyle = (this._inspectorX !== undefined && this._inspectorY !== undefined)
      ? `left: ${this._inspectorX}px; top: ${this._inspectorY}px; right: auto; bottom: auto;`
      : "";
    return `
      <div class="room-inspector-card" id="room-inspector" style="${posStyle}">
        <div class="inspector-drag-handle" id="inspector-header">
          <strong style="color: var(--otis-primary); font-size: 0.82rem; display: flex; align-items: center; gap: 4px;">
            <span>📐</span><span>Area Boundary Editor</span>
            <span style="font-size: 0.65rem; color: var(--otis-text-muted); font-weight: normal; margin-left: 4px;">(drag to move)</span>
          </strong>
          <button type="button" class="btn-toolbar" id="btn-close-inspector" style="padding: 2px 6px; font-size: 0.72rem;">✕</button>
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 0.7rem; color: var(--otis-text-muted);">Bind to HA Area Registry:</label>
          <select id="editor-area-select" style="background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 6px; padding: 4px 6px; font-size: 0.76rem;">
            ${allAreas.map(a => `<option value="${a.id}" ${a.id === rid ? "selected" : ""}>${this._escapeHtml(a.name)} (${a.id})</option>`).join("")}
          </select>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
          <div>
            <label style="font-size: 0.68rem; color: var(--otis-text-muted);">X Coord:</label>
            <input type="number" id="inspector-room-x" style="width: 100%; box-sizing: border-box; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 4px; padding: 3px 6px; font-size: 0.74rem;" />
          </div>
          <div>
            <label style="font-size: 0.68rem; color: var(--otis-text-muted);">Y Coord:</label>
            <input type="number" id="inspector-room-y" style="width: 100%; box-sizing: border-box; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 4px; padding: 3px 6px; font-size: 0.74rem;" />
          </div>
          <div>
            <label style="font-size: 0.68rem; color: var(--otis-text-muted);">Width:</label>
            <input type="number" id="inspector-room-w" style="width: 100%; box-sizing: border-box; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 4px; padding: 3px 6px; font-size: 0.74rem;" />
          </div>
          <div>
            <label style="font-size: 0.68rem; color: var(--otis-text-muted);">Height:</label>
            <input type="number" id="inspector-room-h" style="width: 100%; box-sizing: border-box; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 4px; padding: 3px 6px; font-size: 0.74rem;" />
          </div>
        </div>
        <div style="display: flex; gap: 6px; margin-top: 6px;">
          <button type="button" class="btn-modal-primary" id="btn-apply-inspector-dim" style="flex: 1; padding: 5px 8px; font-size: 0.74rem;">
            ✓ Update Boundary
          </button>
          <button type="button" class="btn-toolbar" id="btn-delete-inspector-room" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.35); padding: 5px 10px; font-size: 0.74rem; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 4px;">
            <span>🗑️</span><span>Delete Room</span>
          </button>
        </div>
      </div>
    `;
  }

  _renderAddMarkerModal() {
    if (!this._addMarkerModalOpen) return "";
    const entities = this._capabilityMap?.entities || [];
    const grouped = {
      light: [],
      switch: [],
      climate: [],
      media_player: [],
      camera: [],
      binary_sensor: [],
      other: [],
    };
    entities.forEach((e) => {
      const d = e.split(".")[0];
      if (grouped[d]) grouped[d].push(e);
      else grouped.other.push(e);
    });

    return `
      <div class="modal-overlay" id="add-marker-modal-backdrop">
        <div class="modal-card" style="max-width: 520px;">
          <div class="modal-header">
            <div>
              <div class="modal-title"><span>➕</span><span>Add Device Pin to Floor Plan</span></div>
              <div class="modal-subtitle">Select an entity to drop onto your architectural canvas</div>
            </div>
            <button type="button" class="modal-close-btn" id="add-marker-close-btn">✕</button>
          </div>
          <div style="max-height: 380px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding-right: 4px;">
            ${Object.entries(grouped).filter(([_, list]) => list.length > 0).map(([dom, list]) => `
              <div>
                <div style="font-size: 0.74rem; font-weight: 700; text-transform: uppercase; color: var(--otis-primary); margin-bottom: 4px;">
                  ${dom} (${list.length})
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                  ${list.slice(0, 24).map(eid => `
                    <button type="button" class="subview-chip btn-place-entity-pin" data-entity-id="${eid}" style="font-size: 0.72rem; padding: 4px 8px;">
                      ${eid}
                    </button>
                  `).join("")}
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      </div>
    `;
  }

  _renderWalkthroughModal() {
    return `
      <div class="modal-overlay" id="walkthrough-modal-backdrop">
        <div class="modal-card">
          <div class="modal-header">
            <div>
              <div class="modal-title">
                <span>📹</span>
                <span>Video Walkthrough to Floor Plan</span>
              </div>
              <div class="modal-subtitle">
                Transform your mobile phone camera walkthrough into a vector SVG layout
              </div>
            </div>
            <button type="button" class="modal-close-btn" id="modal-close-btn">✕</button>
          </div>

          <div class="guide-box">
            <strong>💡 Mobile Walkthrough Instructions:</strong>
            <ol>
              <li>Start recording video on your mobile phone while standing in your home entrance.</li>
              <li>Walk through your home room by room. As you step across each threshold, call out the area clearly (e.g. <em>"Entering Foyer"</em>, <em>"Walking into Kitchen"</em>, <em>"Now in Great Room"</em>, <em>"Stepping out to Backyard"</em>).</li>
              <li>Upload the video file below (MP4, MOV, WEBM). Otis AI will extract the audio track, detect room callouts, and automatically build your multi-floor vector layout!</li>
            </ol>
          </div>

          <!-- Drag and Dropzone -->
          <input type="file" id="walkthrough-file-input" multiple accept="video/mp4,video/quicktime,video/webm,video/*" style="display: none;" />
          <div class="dropzone" id="walkthrough-dropzone">
            <div class="dropzone-icon">📁</div>
            <div class="dropzone-text" id="dropzone-selected-filename">Tap or drag 1 or more walkthrough videos here</div>
            <div class="dropzone-sub">Supports selecting multiple MP4, MOV, or WEBM files at once</div>
          </div>

          <!-- Spoken Order Customization -->
          <div class="order-input-group">
            <label for="spoken-order-input">Spoken Room Order (Optional Override / Notes):</label>
            <input
              type="text"
              id="spoken-order-input"
              placeholder="e.g. Foyer, Great Room, Kitchen, Dining Room, Backyard, Pool"
              value="${this._spokenOrderOverride || ""}"
            />
          </div>

          ${
            this._uploadingVideo
              ? `
            <div style="display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px 0;">
              <div class="spinner" style="width: 28px; height: 28px;"></div>
              <div id="walkthrough-status-text" style="font-size: 0.86rem; font-weight: 700; color: var(--otis-primary); text-align: center;">
                ${this._uploadProgressText || "Uploading videos"}
              </div>
              <div id="walkthrough-discovered-list" style="display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; max-height: 110px; overflow-y: auto; padding: 2px 6px;">
                ${(this._discoveredWalkthroughAreas || [])
                  .map(
                    (name) =>
                      `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:999px;background:rgba(14,165,233,0.16);border:1px solid rgba(56,189,248,0.4);color:#e0f2fe;font-size:0.72rem;font-weight:600;">✓ Discovered ${name}</span>`
                  )
                  .join("")}
              </div>
            </div>
          `
              : `
            <div class="modal-actions">
              <button type="button" class="btn-modal-primary" id="btn-submit-walkthrough" disabled>
                🚀 Parse Video & Generate Floor Plan
              </button>
              <button type="button" class="btn-modal-secondary" id="btn-instant-generate-modal">
                ⚡ Generate Instantly from Registered HA Areas
              </button>
            </div>
          `
          }
        </div>
      </div>
    `;
  }

  _renderThemeModal() {
    const presets = this._capabilityMap?.theme_presets || [
      { key: "cyberpunk", name: "Cyberpunk Neon", preview: { primary: "#00f0ff", accent: "#f43f5e", background: "#070b14", card_bg: "#0f172a" } },
      { key: "midnight_slate", name: "Midnight Slate", preview: { primary: "#38bdf8", accent: "#818cf8", background: "#0b1120", card_bg: "#1e293b" } },
      { key: "oled_black", name: "OLED Obsidian", preview: { primary: "#10b981", accent: "#38bdf8", background: "#000000", card_bg: "#111113" } },
      { key: "sunset_amber", name: "Sunset Amber", preview: { primary: "#f59e0b", accent: "#ea580c", background: "#1c1917", card_bg: "#292524" } },
      { key: "emerald_luxury", name: "Emerald Luxury", preview: { primary: "#34d399", accent: "#fbbf24", background: "#022c22", card_bg: "#064e3b" } },
      { key: "nordic_frost", name: "Nordic Frost", preview: { primary: "#0284c7", accent: "#0d9488", background: "#f8fafc", card_bg: "#ffffff" } },
      { key: "high_contrast", name: "High Contrast", preview: { primary: "#ffff00", accent: "#00ffff", background: "#000000", card_bg: "#000000" } },
    ];
    const customThemes = this._capabilityMap?.themes || [];

    return `
      <div class="modal-overlay" id="theme-modal-backdrop">
        <div class="modal-card" style="max-width: 620px;">
          <div class="modal-header">
            <div>
              <div class="modal-title">
                <span>🎨</span>
                <span>Dynamic AI Theme Studio</span>
              </div>
              <div class="modal-subtitle">
                Collaborative natural language styling & instant live theme application
              </div>
            </div>
            <button type="button" class="modal-close-btn" id="theme-modal-close-btn">✕</button>
          </div>

          <!-- User Scope Selector -->
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 8px; font-size: 0.78rem;">
            <span style="color: var(--otis-text-muted); font-weight: 600;">Apply Scope:</span>
            <div style="display: flex; gap: 14px;">
              <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; color: var(--otis-text);">
                <input type="radio" name="theme-scope" id="scope-current" value="current" ${this._themeApplyScope !== "all" ? "checked" : ""} />
                Current User (${this._escapeHtml(this._hass?.user?.name || "Me")})
              </label>
              <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; color: var(--otis-text);">
                <input type="radio" name="theme-scope" id="scope-all" value="all" ${this._themeApplyScope === "all" ? "checked" : ""} />
                All Users (Global Profile Sync)
              </label>
            </div>
          </div>

          <!-- AI Natural Language Generator Prompt -->
          <div class="guide-box" style="display: flex; flex-direction: column; gap: 8px;">
            <div style="font-weight: 700; font-size: 0.85rem; color: var(--otis-primary);">
              ✨ Collaborative AI Theme Generator
            </div>
            <div style="display: flex; gap: 8px;">
              <input
                type="text"
                id="theme-prompt-input"
                placeholder="e.g. Glowing neon cyan and purple with dark slate cards and 16px radius..."
                style="flex: 1; padding: 8px 12px; border-radius: 8px; border: 1px solid var(--otis-surface-border); background: var(--otis-surface); color: var(--otis-text); font-size: 0.82rem;"
              />
              <button type="button"
                class="btn-modal-primary"
                id="btn-generate-theme-ai"
                style="white-space: nowrap;"
                ${this._generatingTheme ? "disabled" : ""}
              >
                ${this._generatingTheme ? `<div class="spinner" style="width: 14px; height: 14px;"></div> Generating...` : "✨ Generate & Apply"}
              </button>
            </div>
          </div>

          <!-- Custom Saved Themes -->
          ${
            customThemes.length > 0
              ? `
            <div>
              <div style="font-size: 0.76rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--otis-text-muted); margin-bottom: 8px;">
                Custom Generated Themes (${customThemes.length})
              </div>
              <div class="theme-grid" style="margin-bottom: 14px;">
                ${customThemes
                  .map(
                    (th) => `
                  <div class="theme-card" style="border-left: 3px solid ${th.preview.primary};">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                      <span style="font-weight: 700; font-size: 0.85rem; color: var(--otis-text);">${this._escapeHtml(th.title)}</span>
                      <div class="theme-swatches">
                        <span class="theme-swatch" style="background: ${th.preview.primary};" title="Primary"></span>
                        <span class="theme-swatch" style="background: ${th.preview.accent};" title="Accent"></span>
                        <span class="theme-swatch" style="background: ${th.preview.background};" title="Background"></span>
                      </div>
                    </div>
                    <div style="font-size: 0.72rem; color: var(--otis-text-muted);">
                      Radius: ${th.border_radius} • File: ${th.file_name}
                    </div>
                    <div style="display: flex; gap: 6px; margin-top: 4px;">
                      <button type="button" class="btn-modal-primary btn-apply-theme" data-theme-key="${th.theme_key}" style="flex: 1; padding: 4px 8px; font-size: 0.75rem;">
                        ⚡ Apply Live
                      </button>
                      <button type="button" class="btn-toolbar btn-delete-theme" data-theme-key="${th.theme_key}" style="padding: 4px 8px; color: #f43f5e;" title="Delete Theme">
                        🗑️
                      </button>
                    </div>
                  </div>
                `
                  )
                  .join("")}
              </div>
            </div>
          `
              : ""
          }

          <!-- Curated Baseline Presets -->
          <div>
            <div style="font-size: 0.76rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--otis-text-muted); margin-bottom: 8px;">
              Curated Master Presets (Instant 1-Click Generation & Activation)
            </div>
            <div class="theme-grid">
              ${presets
                .map(
                  (p) => `
                <div class="theme-card" style="border-left: 3px solid ${p.preview.primary};">
                  <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; font-size: 0.85rem; color: var(--otis-text);">${this._escapeHtml(p.name)}</span>
                    <div class="theme-swatches">
                      <span class="theme-swatch" style="background: ${p.preview.primary};" title="Primary"></span>
                      <span class="theme-swatch" style="background: ${p.preview.accent};" title="Accent"></span>
                      <span class="theme-swatch" style="background: ${p.preview.background};" title="Background"></span>
                    </div>
                  </div>
                  <div style="font-size: 0.72rem; color: var(--otis-text-muted); line-height: 1.35;">
                    ${this._escapeHtml(p.description || "Master aesthetic profile")}
                  </div>
                  <button type="button" class="btn-modal-secondary btn-generate-preset" data-preset-key="${p.key}" style="padding: 4px 8px; font-size: 0.75rem; margin-top: 4px;">
                    ✨ Generate & Set Live
                  </button>
                </div>
              `
                )
                .join("")}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  async _generateThemeAi(prompt, presetKey = null) {
    if (!this._hass) return;
    this._generatingTheme = true;
    this._render();

    try {
      const payload = {
        prompt: prompt || (presetKey ? `Generate ${presetKey} theme` : "Otis Custom Theme"),
        apply_immediately: true,
      };
      if (presetKey) {
        payload.base_palette = presetKey;
      }
      const res = await this._hass.callService("otis_ai", "generate_theme", payload, undefined, true, true);
      const data = res?.response || res || {};
      if (data.success) {
        this._showToast(`✨ Generated and applying "${data.title}"...`);
        await this._fetchData();
        if (data.theme_key) {
          await this._applyThemeDirect(data.theme_key);
        }
      } else {
        this._showToast(data.error || "Could not generate theme", true);
      }
    } catch (err) {
      console.error("Error generating theme:", err);
      this._showToast("Error generating theme. Check HA logs.", true);
    } finally {
      this._generatingTheme = false;
      this._render();
    }
  }

  async _applyThemeDirect(themeKey, targetUserId = null, applyAllUsers = false) {
    if (!this._hass || !themeKey) return;
    try {
      const isAll = applyAllUsers || this._themeApplyScope === "all";

      // 1. Call backend services
      try {
        await this._hass.callService("frontend", "set_theme", { name: themeKey });
      } catch (_) {}

      try {
        const payload = { name: themeKey };
        if (targetUserId) payload.user_id = targetUserId;
        if (isAll) payload.all_users = true;
        await this._hass.callService("otis_ai", "apply_theme", payload);
      } catch (svcErr) {
        console.warn("Could not call otis_ai.apply_theme:", svcErr);
      }

      // 2. Set user theme directly in Home Assistant per-user profile storage via WebSocket
      if (this._hass.callWS) {
        try {
          await this._hass.callWS({
            type: "frontend/set_user_data",
            key: "theme",
            value: { theme: themeKey },
          });
        } catch (wsErr) {
          console.warn("Could not save theme to user profile via WebSocket:", wsErr);
        }
      }

      // 3. Dispatch standard Home Assistant settheme events to update active browser session immediately
      const setthemeEvent = new CustomEvent("settheme", {
        detail: { theme: themeKey },
        bubbles: true,
        composed: true,
      });
      this.dispatchEvent(setthemeEvent);
      window.dispatchEvent(setthemeEvent);
      const ha = document.querySelector("home-assistant");
      if (ha) {
        ha.dispatchEvent(setthemeEvent);
        ha.dispatchEvent(new CustomEvent("settheme", { detail: themeKey, bubbles: true, composed: true }));
      }

      // 4. Update localStorage if HA tracks selected theme
      try {
        const existing = JSON.parse(localStorage.getItem("selectedTheme") || "{}");
        localStorage.setItem("selectedTheme", JSON.stringify({ ...existing, theme: themeKey }));
      } catch (_) {}

      const scopeDesc = isAll ? "for all users" : "for your profile";
      this._showToast(`🎨 Theme applied ${scopeDesc}: ${themeKey}`);
    } catch (err) {
      console.error("Error applying theme:", err);
      this._showToast("Error applying theme", true);
    }
  }

  async _deleteThemeDirect(themeKey) {
    if (!this._hass || !themeKey) return;
    try {
      await this._hass.callService("otis_ai", "delete_theme", { name: themeKey }, undefined, true, true);
      this._showToast(`Deleted theme ${themeKey}`);
      await this._fetchData();
    } catch (err) {
      console.error("Error deleting theme:", err);
      this._showToast("Error deleting theme", true);
    }
  }

  _bindEvents() {
    const root = this.shadowRoot;

    // Refresh button
    const refreshBtn = root.querySelector("#refresh-btn");
    if (refreshBtn) {
      refreshBtn.onclick = () => this._fetchData();
    }

    // Subview Launchpad
    root.querySelectorAll(".subview-chip").forEach((chip) => {
      if (chip.id === "btn-open-themes") {
        chip.onclick = (e) => {
          e.stopPropagation();
          this._themeModalOpen = true;
          this._render();
        };
        return;
      }
      if (chip.id === "btn-sync-dashboards") {
        chip.onclick = async (e) => {
          e.stopPropagation();
          try {
            this._showToast("🔄 Syncing Studios & Rooms to Command Center...");
            await this._hass.callService("otis_ai", "sync_dashboards", {});
            this._showToast("✨ Studios and Rooms synchronized to Command Center!");
            await this._fetchData();
          } catch (err) {
            console.error("Failed to sync dashboards:", err);
            this._showToast(`Failed to sync dashboards: ${err.message || err}`, true);
          }
        };
        return;
      }
      chip.onclick = () => {
        const path = chip.getAttribute("data-subview");
        if (path) {
          const event = new CustomEvent("hass-navigate", {
            detail: { href: path },
            bubbles: true,
            composed: true,
          });
          window.dispatchEvent(event);
          window.history.pushState(null, "", path);
          window.dispatchEvent(new CustomEvent("location-changed"));
        }
      };
    });

    // Theme Studio Modal Events
    const themeCloseBtn = root.querySelector("#theme-modal-close-btn");
    if (themeCloseBtn) {
      themeCloseBtn.onclick = () => {
        this._themeModalOpen = false;
        this._render();
      };
    }
    const themeBackdrop = root.querySelector("#theme-modal-backdrop");
    if (themeBackdrop) {
      themeBackdrop.onclick = (e) => {
        if (e.target === themeBackdrop) {
          this._themeModalOpen = false;
          this._render();
        }
      };
    }
    const btnGenThemeAi = root.querySelector("#btn-generate-theme-ai");
    const themePromptInput = root.querySelector("#theme-prompt-input");
    if (btnGenThemeAi && themePromptInput) {
      btnGenThemeAi.onclick = () => {
        const p = themePromptInput.value.trim();
        if (p) {
          this._generateThemeAi(p);
        } else {
          this._showToast("Please enter a theme styling prompt", true);
        }
      };
      themePromptInput.onkeydown = (e) => {
        if (e.key === "Enter") {
          const p = themePromptInput.value.trim();
          if (p) this._generateThemeAi(p);
        }
      };
    }
    root.querySelectorAll(".btn-apply-theme").forEach((btn) => {
      btn.onclick = () => {
        const k = btn.getAttribute("data-theme-key");
        if (k) this._applyThemeDirect(k);
      };
    });
    root.querySelectorAll(".btn-delete-theme").forEach((btn) => {
      btn.onclick = () => {
        const k = btn.getAttribute("data-theme-key");
        if (k && confirm(`Delete theme ${k}?`)) this._deleteThemeDirect(k);
      };
    });
    root.querySelectorAll(".btn-generate-preset").forEach((btn) => {
      btn.onclick = () => {
        const pk = btn.getAttribute("data-preset-key");
        if (pk) this._generateThemeAi(`Generate ${pk} preset theme`, pk);
      };
    });

    root.querySelectorAll("input[name='theme-scope']").forEach((radio) => {
      radio.onchange = () => {
        this._themeApplyScope = radio.value;
      };
    });

    // Tabs
    const tabSug = root.querySelector("#tab-suggestions");
    if (tabSug) {
      tabSug.onclick = (e) => {
        if (e) e.preventDefault();
        if (this._isListening) this._stopVoiceRecording();
        this._saveActiveTab("suggestions");
        this._render();
      };
    }

    const tabChat = root.querySelector("#tab-chat");
    if (tabChat) {
      tabChat.onclick = (e) => {
        if (e) e.preventDefault();
        this._saveActiveTab("chat");
        this._render();
        this._scrollChatToBottom();
      };
    }

    const tabCap = root.querySelector("#tab-capabilities");
    if (tabCap) {
      tabCap.onclick = (e) => {
        if (e) e.preventDefault();
        this._saveActiveTab("capabilities");
        this._render();
      };
    }

    const tabFloor = root.querySelector("#tab-floorplan");
    if (tabFloor) {
      tabFloor.onclick = (e) => {
        if (e) e.preventDefault();
        if (this._isListening) this._stopVoiceRecording();
        this._saveActiveTab("floorplan");
        this._render();
        if (this._capabilityMap?.floorplan?.exists && !this._floorplanSvg && !this._loadingFloorplan) {
          this._loadFloorplanSvg(this._capabilityMap.floorplan.url);
        }
      };
    }

    // Category filter pills
    root.querySelectorAll("[data-category-pill]").forEach((pill) => {
      pill.onclick = (e) => {
        const cat = e.currentTarget.getAttribute("data-category-pill") || "all";
        this._selectedCategory = cat;
        this._render();
      };
    });

    // Dismiss buttons
    root.querySelectorAll("[data-dismiss]").forEach((btn) => {
      btn.onclick = (e) => {
        const id = e.currentTarget.getAttribute("data-dismiss");
        this._dismissSuggestion(id);
      };
    });

    // Apply buttons
    root.querySelectorAll("[data-apply]").forEach((btn) => {
      btn.onclick = (e) => {
        const id = e.currentTarget.getAttribute("data-apply");
        const suggestion = (this._suggestions || []).find((s) => s.id === id);
        if (suggestion) {
          this._applySuggestion(suggestion);
        }
      };
    });

    // Clear Chat history button
    const btnClearChat = root.querySelector("#btn-clear-chat");
    if (btnClearChat) {
      btnClearChat.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        this._chatMessages = [];
        this._conversationId = null;
        this._saveChatMessages();
        this._render();
        this._showToast("Conversation history cleared.");
      };
    }

    // Chat chips
    root.querySelectorAll("[data-chip]").forEach((chip) => {
      chip.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const prompt = e.currentTarget.getAttribute("data-chip");
        if (prompt) {
          this._sendChatMessage(prompt);
        }
      };
    });

    // Prompt copy buttons
    root.querySelectorAll(".prompt-copy-btn").forEach((btn) => {
      btn.onclick = async (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const prompt = btn.getAttribute("data-prompt");
        if (prompt) {
          try {
            await navigator.clipboard.writeText(prompt);
          } catch (_) {}
          const input = root.querySelector("#chat-input");
          if (input) {
            input.value = prompt;
            input.focus();
            input.dispatchEvent(new Event("input", { bubbles: true }));
          }
          this._showToast("📋 Copied prompt to input!");
        }
      };
    });

    // Reasoning trace toggle buttons
    root.querySelectorAll(".reasoning-trace-toggle").forEach((btn) => {
      btn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const traceId = btn.getAttribute("data-trace-id");
        if (traceId) {
          if (this._expandedReasoningIds.has(traceId)) {
            this._expandedReasoningIds.delete(traceId);
          } else {
            this._expandedReasoningIds.add(traceId);
          }
          this._render();
        }
      };
    });

    // Voice mic button
    const chatMic = root.querySelector("#chat-mic");
    if (chatMic) {
      chatMic.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        this._toggleVoiceRecording();
      };
    }

    // Chat input & send
    const chatInput = root.querySelector("#chat-input");
    const chatSend = root.querySelector("#chat-send");
    const previewContainer = root.querySelector("#chat-live-preview");
    const previewBody = root.querySelector("#chat-live-preview-body");
    const previewClose = root.querySelector("#chat-preview-close");

    if (chatInput) {
      const updateLivePreview = () => {
        const val = chatInput.value || "";
        this._draftChatText = val;
        if (!val.trim() || this._previewDismissed) {
          if (previewContainer) previewContainer.style.display = "none";
          return;
        }

        // Detect Markdown syntax: headers (#), lists (- or * or + or 1.), bold (**), italics (* or _), code (``` or `), hr (--, ---, ***, ___), quotes (>), tables (|)
        const hasMarkdown = /(?:^|\n)\s*(?:#{1,6}(?:\s+|$)|[-*+](?:\s+|$)|--+|(?:\d+[.)])(?:\s+|$)|```|&gt;|>|\|.+\|)|[*_`~\[\]]/.test(val);
        if (hasMarkdown && previewContainer && previewBody) {
          previewContainer.style.display = "block";
          previewBody.innerHTML = this._renderMarkdown(val);
        } else if (previewContainer) {
          previewContainer.style.display = "none";
        }
      };

      const adjustHeight = () => {
        chatInput.style.height = "auto";
        chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
        updateLivePreview();
      };

      // If existing draft is present, adjust height and populate preview
      if (chatInput.value) {
        adjustHeight();
      }

      chatInput.oninput = () => {
        this._previewDismissed = false;
        adjustHeight();
      };

      if (previewClose && previewContainer) {
        previewClose.onclick = () => {
          previewContainer.style.display = "none";
          this._previewDismissed = true;
        };
      }

      chatInput.onkeydown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
          if (this._isSendingChat) return false;
          const text = chatInput.value;
          chatInput.value = "";
          this._draftChatText = "";
          this._previewDismissed = false;
          adjustHeight();
          if (previewContainer) previewContainer.style.display = "none";
          this._sendChatMessage(text);
          return false;
        }
      };
    }

    if (chatSend && chatInput) {
      chatSend.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        if (this._isSendingChat) return;
        const text = chatInput.value;
        chatInput.value = "";
        this._draftChatText = "";
        this._previewDismissed = false;
        chatInput.style.height = "auto";
        if (previewContainer) previewContainer.style.display = "none";
        this._sendChatMessage(text);
      };
    }

    // Floorplan: Zone filter pills (All Floors vs Ground & Outdoor vs Separate Upper Level)
    const applyZoneFilterToSvg = (zone) => {
      const svgEl = root.querySelector("#floorplan-viewport svg");
      if (!svgEl) return;
      const planGround = svgEl.querySelector("#plan-ground");
      const planUpper = svgEl.querySelector("#plan-upper");
      const fullVb = svgEl.getAttribute("data-full-viewbox") || "0 0 1300 1250";

      if (zone === "main") {
        // Ground floorplan includes outdoor areas; draw separately from Upper Floor
        if (planGround) {
          planGround.style.display = "";
          const gVb = planGround.getAttribute("data-viewbox");
          if (gVb) svgEl.setAttribute("viewBox", gVb);
        }
        if (planUpper) planUpper.style.display = "none";
        svgEl.querySelectorAll("[data-zone]").forEach((el) => {
          el.style.opacity = "1";
          el.style.filter = "none";
        });
      } else if (zone === "upper") {
        // Upper floorplan drawn separately
        if (planGround) planGround.style.display = "none";
        if (planUpper) {
          planUpper.style.display = "";
          const uVb = planUpper.getAttribute("data-viewbox");
          if (uVb) svgEl.setAttribute("viewBox", uVb);
        }
        svgEl.querySelectorAll("[data-zone]").forEach((el) => {
          el.style.opacity = "1";
          el.style.filter = "none";
        });
      } else if (zone === "outdoor") {
        if (planGround) {
          planGround.style.display = "";
          const gVb = planGround.getAttribute("data-viewbox");
          if (gVb) svgEl.setAttribute("viewBox", gVb);
        }
        if (planUpper) planUpper.style.display = "none";
        svgEl.querySelectorAll("[data-zone]").forEach((el) => {
          const elZone = el.getAttribute("data-zone");
          if (elZone === "outdoor") {
            el.style.opacity = "1";
            el.style.filter = "none";
          } else {
            el.style.opacity = "0.22";
            el.style.filter = "grayscale(75%)";
          }
        });
      } else {
        // "all": Show both Ground+Outdoor and Upper Level plans
        if (planGround) planGround.style.display = "";
        if (planUpper) planUpper.style.display = "";
        svgEl.setAttribute("viewBox", fullVb);
        svgEl.querySelectorAll("[data-zone]").forEach((el) => {
          el.style.opacity = "1";
          el.style.filter = "none";
        });
      }
    };

    applyZoneFilterToSvg(this._selectedFloorZone || "all");

    root.querySelectorAll(".zone-pill").forEach((pill) => {
      pill.onclick = (e) => {
        const zone = e.currentTarget.getAttribute("data-zone") || "all";
        this._selectedFloorZone = zone;
        try {
          localStorage.setItem("otis_floorplan_selected_zone", zone);
        } catch (_) {}
        root.querySelectorAll(".zone-pill").forEach((p) => p.classList.toggle("active", p === e.currentTarget));
        applyZoneFilterToSvg(zone);
      };
    });

    // Studio Back to Dashboard Button
    const btnBackDash = root.querySelector("#btn-back-dashboard");
    if (btnBackDash) {
      btnBackDash.onclick = () => {
        const path = "/otis-ai";
        const event = new CustomEvent("hass-navigate", {
          detail: { href: path },
          bubbles: true,
          composed: true,
        });
        window.dispatchEvent(event);
        window.history.pushState(null, "", path);
        window.dispatchEvent(new CustomEvent("location-changed"));
      };
    }

    // Helper to calculate exact SVG viewBox coordinates from mouse/pointer event
    const getSvgPoint = (svg, clientX, clientY) => {
      const pt = svg.createSVGPoint();
      pt.x = clientX;
      pt.y = clientY;
      const ctm = svg.getScreenCTM();
      return ctm ? pt.matrixTransform(ctm.inverse()) : { x: clientX, y: clientY };
    };

    // Floorplan: Interactive SVG entity badges, canvas editor, and room inspection
    const svgViewport = root.querySelector("#floorplan-viewport");
    const svgEl = root.querySelector("#floorplan-viewport svg");
    const editorHud = root.querySelector("#editor-hud");

    if (svgViewport && svgEl) {
      if (this._editorActive) {
        // --- Canvas Editor Active Mode ---

        // 1. Live pointer HUD
        svgEl.onpointermove = (e) => {
          if (!this._draggingBadge && !this._resizingHandle) {
            const p = getSvgPoint(svgEl, e.clientX, e.clientY);
            if (editorHud) {
              editorHud.textContent = `📐 X: ${Math.round(p.x)}, Y: ${Math.round(p.y)}`;
            }
          }
        };

        // 2. Drag & Drop repositioning of entity badges
        svgEl.querySelectorAll(".entity-badge").forEach((badge) => {
          badge.style.cursor = "grab";
          badge.onpointerdown = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const p = getSvgPoint(svgEl, e.clientX, e.clientY);
            const tr = badge.getAttribute("transform") || "";
            const m = tr.match(/translate\(\s*([-\d.]+)[,\s]+([-\d.]+)\s*\)/);
            const curX = m ? parseFloat(m[1]) : p.x;
            const curY = m ? parseFloat(m[2]) : p.y;
            const entityId = badge.getAttribute("data-entity-id");

            this._draggingBadge = {
              el: badge,
              entityId,
              offsetX: p.x - curX,
              offsetY: p.y - curY,
            };
            try { badge.setPointerCapture(e.pointerId); } catch (_) {}
          };

          badge.onpointermove = (e) => {
            if (!this._draggingBadge || this._draggingBadge.el !== badge) return;
            e.preventDefault();
            e.stopPropagation();
            const p = getSvgPoint(svgEl, e.clientX, e.clientY);
            const newX = Math.round(p.x - this._draggingBadge.offsetX);
            const newY = Math.round(p.y - this._draggingBadge.offsetY);

            badge.setAttribute("transform", `translate(${newX}, ${newY})`);
            if (editorHud) {
              editorHud.textContent = `📍 ${this._draggingBadge.entityId} (X: ${newX}, Y: ${newY})`;
            }
            this._dirtyBadges[this._draggingBadge.entityId] = {
              entity_id: this._draggingBadge.entityId,
              x: newX,
              y: newY,
            };
            this._hasUnsavedLayout = true;
            const saveBtn = root.querySelector("#btn-save-layout");
            if (saveBtn) saveBtn.textContent = "💾 Save Changes *";
          };

          badge.onpointerup = (e) => {
            if (this._draggingBadge && this._draggingBadge.el === badge) {
              try { badge.releasePointerCapture(e.pointerId); } catch (_) {}
              this._draggingBadge = null;
            }
          };
          badge.onpointercancel = (e) => {
            if (this._draggingBadge && this._draggingBadge.el === badge) {
              try { badge.releasePointerCapture(e.pointerId); } catch (_) {}
              this._draggingBadge = null;
            }
          };
        });

        // Apply any pending dirty room dimensions onto SVG elements
        Object.entries(this._dirtyRooms).forEach(([roomId, rData]) => {
          const rGrp = svgEl.querySelector(`.room-group[data-area-id="${roomId}"]`);
          if (rGrp) {
            const rBox = rGrp.querySelector(".room-box, .room-rect");
            if (rBox) {
              rBox.setAttribute("x", rData.x);
              rBox.setAttribute("y", rData.y);
              rBox.setAttribute("width", rData.width);
              rBox.setAttribute("height", rData.height);
            }
            const rLbl = rGrp.querySelector(".room-header, .room-label");
            if (rLbl) {
              rLbl.setAttribute("x", rData.x + 14);
              rLbl.setAttribute("y", rData.y + 22);
              if (rData.name) rLbl.textContent = rData.name;
            }
            rGrp.querySelectorAll(".subzone-pill").forEach((pill, sIdx) => {
              pill.setAttribute("x", rData.x + 16);
              pill.setAttribute("y", rData.y + 22 + 18 + sIdx * 16);
            });
            rGrp.querySelectorAll(".entity-badge").forEach((badge, bIdx) => {
              badge.setAttribute("transform", `translate(${rData.x + 16 + bIdx * 24}, ${rData.y + rData.height - 18})`);
            });
          }
        });

        // Apply any pending dirty badge coordinates onto SVG elements
        Object.entries(this._dirtyBadges).forEach(([entityId, bData]) => {
          const bEl = svgEl.querySelector(`[data-entity-id="${entityId}"]`);
          if (bEl) {
            bEl.setAttribute("transform", `translate(${bData.x}, ${bData.y})`);
          }
        });

        // 3. Room group selection for boundary resizing & editing
        svgEl.querySelectorAll(".room-group").forEach((grp) => {
          grp.style.cursor = "pointer";
          grp.onclick = (e) => {
            e.stopPropagation();
            const areaId = grp.getAttribute("data-area-id");
            const roomZone = grp.getAttribute("data-zone") || "main";
            if (this._selectedFloorZone !== "all" && this._selectedFloorZone !== roomZone) {
              if (roomZone === "upper" || (roomZone === "main" && this._selectedFloorZone === "upper") || (roomZone === "outdoor" && this._selectedFloorZone === "upper")) {
                this._selectedFloorZone = roomZone;
                try { localStorage.setItem("otis_floorplan_selected_zone", roomZone); } catch (_) {}
                applyZoneFilterToSvg(roomZone);
                root.querySelectorAll(".zone-pill").forEach((p) => p.classList.toggle("active", p.getAttribute("data-zone") === roomZone));
              }
            }
            if (this._selectedEditorRoomId === areaId) return;
            this._selectedEditorRoomId = areaId;
            this._render();
          };
        });

        // 4. Inject interactive 8-point resize handles and move support onto selected room
        if (this._selectedEditorRoomId) {
          const selGrp = svgEl.querySelector(`.room-group[data-area-id="${this._selectedEditorRoomId}"]`);
          if (selGrp) {
            const rect = selGrp.querySelector(".room-box, .room-rect");
            if (rect) {
              rect.style.stroke = "var(--otis-primary)";
              rect.style.strokeWidth = "2.5";
              rect.style.strokeDasharray = "4,4";

              const dirty = this._dirtyRooms[this._selectedEditorRoomId];
              const rx = dirty ? dirty.x : parseFloat(rect.getAttribute("x") || 0);
              const ry = dirty ? dirty.y : parseFloat(rect.getAttribute("y") || 0);
              const rw = dirty ? dirty.width : parseFloat(rect.getAttribute("width") || 160);
              const rh = dirty ? dirty.height : parseFloat(rect.getAttribute("height") || 120);

              // Blueprint boundary detection for clamping
              const planGroup = selGrp.closest("[data-plan]") || selGrp.closest(".floor-zone") || svgEl;
              const planFrame = planGroup.querySelector(".plan-frame");
              let minX = 40;
              let maxX = 1260;
              let minY = 30;
              let maxY = 1400;
              if (planFrame) {
                const fx = parseFloat(planFrame.getAttribute("x") || 40);
                const fy = parseFloat(planFrame.getAttribute("y") || 30);
                const fw = parseFloat(planFrame.getAttribute("width") || 1220);
                const fh = parseFloat(planFrame.getAttribute("height") || 650);
                minX = Math.round(fx + 5);
                maxX = Math.round(fx + fw - 5);
                minY = Math.round(fy + 34);
                maxY = Math.round(fy + fh - 5);
              }

              // Magnetic Snapping Guides: Gather all other room boundaries in this plan frame
              const otherRooms = [];
              planGroup.querySelectorAll(`.room-group:not([data-area-id="${this._selectedEditorRoomId}"])`).forEach((ogrp) => {
                const oRect = ogrp.querySelector(".room-box, .room-rect");
                if (oRect) {
                  const ox = parseFloat(oRect.getAttribute("x") || 0);
                  const oy = parseFloat(oRect.getAttribute("y") || 0);
                  const ow = parseFloat(oRect.getAttribute("width") || 160);
                  const oh = parseFloat(oRect.getAttribute("height") || 120);
                  otherRooms.push({ x: ox, y: oy, width: ow, height: oh, r: ox + ow, b: oy + oh });
                }
              });

              let snapLayer = svgEl.querySelector(".snap-guides-layer");
              if (!snapLayer) {
                snapLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
                snapLayer.setAttribute("class", "snap-guides-layer");
                svgEl.appendChild(snapLayer);
              }

              const clearSnapGuides = () => {
                if (snapLayer) snapLayer.innerHTML = "";
              };

              const snapCoordinates = (candX, candY, candW, candH, isMove = true) => {
                const snapDist = 12;
                let sx = candX;
                let sy = candY;
                let sw = candW;
                let sh = candH;
                let guides = [];

                for (const o of otherRooms) {
                  if (isMove) {
                    // Left edge snaps
                    if (Math.abs(candX - o.x) <= snapDist) {
                      sx = o.x;
                      guides.push(`<line x1="${o.x}" y1="${Math.min(candY, o.y) - 30}" x2="${o.x}" y2="${Math.max(candY + candH, o.b) + 30}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    } else if (Math.abs(candX - o.r) <= snapDist) {
                      sx = o.r;
                      guides.push(`<line x1="${o.r}" y1="${Math.min(candY, o.y) - 30}" x2="${o.r}" y2="${Math.max(candY + candH, o.b) + 30}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }
                    // Right edge snaps
                    else if (Math.abs(candX + candW - o.r) <= snapDist) {
                      sx = o.r - candW;
                      guides.push(`<line x1="${o.r}" y1="${Math.min(candY, o.y) - 30}" x2="${o.r}" y2="${Math.max(candY + candH, o.b) + 30}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    } else if (Math.abs(candX + candW - o.x) <= snapDist) {
                      sx = o.x - candW;
                      guides.push(`<line x1="${o.x}" y1="${Math.min(candY, o.y) - 30}" x2="${o.x}" y2="${Math.max(candY + candH, o.b) + 30}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }

                    // Top edge snaps
                    if (Math.abs(candY - o.y) <= snapDist) {
                      sy = o.y;
                      guides.push(`<line x1="${Math.min(candX, o.x) - 30}" y1="${o.y}" x2="${Math.max(candX + candW, o.r) + 30}" y2="${o.y}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    } else if (Math.abs(candY - o.b) <= snapDist) {
                      sy = o.b;
                      guides.push(`<line x1="${Math.min(candX, o.x) - 30}" y1="${o.b}" x2="${Math.max(candX + candW, o.r) + 30}" y2="${o.b}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }
                    // Bottom edge snaps
                    else if (Math.abs(candY + candH - o.b) <= snapDist) {
                      sy = o.b - candH;
                      guides.push(`<line x1="${Math.min(candX, o.x) - 30}" y1="${o.b}" x2="${Math.max(candX + candW, o.r) + 30}" y2="${o.b}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    } else if (Math.abs(candY + candH - o.y) <= snapDist) {
                      sy = o.y - candH;
                      guides.push(`<line x1="${Math.min(candX, o.x) - 30}" y1="${o.y}" x2="${Math.max(candX + candW, o.r) + 30}" y2="${o.y}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }
                  } else {
                    // Resizing edge snaps
                    if (Math.abs(candX - o.x) <= snapDist) {
                      sx = o.x;
                      sw = (candX + candW) - sx;
                      guides.push(`<line x1="${o.x}" y1="${Math.min(candY, o.y) - 30}" x2="${o.x}" y2="${Math.max(candY + candH, o.b) + 30}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }
                    if (Math.abs(candX + candW - o.r) <= snapDist) {
                      sw = o.r - candX;
                      guides.push(`<line x1="${o.r}" y1="${Math.min(candY, o.y) - 30}" x2="${o.r}" y2="${Math.max(candY + candH, o.b) + 30}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }
                    if (Math.abs(candY - o.y) <= snapDist) {
                      sy = o.y;
                      sh = (candY + candH) - sy;
                      guides.push(`<line x1="${Math.min(candX, o.x) - 30}" y1="${o.y}" x2="${Math.max(candX + candW, o.r) + 30}" y2="${o.y}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }
                    if (Math.abs(candY + candH - o.b) <= snapDist) {
                      sh = o.b - candY;
                      guides.push(`<line x1="${Math.min(candX, o.x) - 30}" y1="${o.b}" x2="${Math.max(candX + candW, o.r) + 30}" y2="${o.b}" stroke="#38bdf8" stroke-dasharray="4,4" stroke-width="1.8" />`);
                    }
                  }
                }

                if (snapLayer) snapLayer.innerHTML = guides.join("");
                return { x: sx, y: sy, width: sw, height: sh };
              };

              // Ensure rect attributes match dirty state
              rect.setAttribute("x", rx);
              rect.setAttribute("y", ry);
              rect.setAttribute("width", rw);
              rect.setAttribute("height", rh);

              // Update Inspector fields if rendered
              const inpX = root.querySelector("#inspector-room-x");
              const inpY = root.querySelector("#inspector-room-y");
              const inpW = root.querySelector("#inspector-room-w");
              const inpH = root.querySelector("#inspector-room-h");
              if (inpX) inpX.value = Math.round(rx);
              if (inpY) inpY.value = Math.round(ry);
              if (inpW) inpW.value = Math.round(rw);
              if (inpH) inpH.value = Math.round(rh);

              // Render 8 handles overlay layer (corners + edges)
              let handleGrp = selGrp.querySelector(".handles-layer");
              if (!handleGrp) {
                handleGrp = document.createElementNS("http://www.w3.org/2000/svg", "g");
                handleGrp.setAttribute("class", "handles-layer");
                selGrp.appendChild(handleGrp);
              }
              handleGrp.innerHTML = `
                <circle class="room-resize-handle" data-handle="nw" cx="${rx}" cy="${ry}" r="7" />
                <circle class="room-resize-handle" data-handle="n" cx="${rx + rw / 2}" cy="${ry}" r="6" />
                <circle class="room-resize-handle" data-handle="ne" cx="${rx + rw}" cy="${ry}" r="7" />
                <circle class="room-resize-handle" data-handle="e" cx="${rx + rw}" cy="${ry + rh / 2}" r="6" />
                <circle class="room-resize-handle" data-handle="se" cx="${rx + rw}" cy="${ry + rh}" r="7" />
                <circle class="room-resize-handle" data-handle="s" cx="${rx + rw / 2}" cy="${ry + rh}" r="6" />
                <circle class="room-resize-handle" data-handle="sw" cx="${rx}" cy="${ry + rh}" r="7" />
                <circle class="room-resize-handle" data-handle="w" cx="${rx}" cy="${ry + rh / 2}" r="6" />
              `;

              const updateRoomElements = (nx, ny, nw, nh, areaName) => {
                rect.setAttribute("x", nx);
                rect.setAttribute("y", ny);
                rect.setAttribute("width", nw);
                rect.setAttribute("height", nh);

                // Update all 8 handles
                const hNw = handleGrp.querySelector('[data-handle="nw"]');
                const hN  = handleGrp.querySelector('[data-handle="n"]');
                const hNe = handleGrp.querySelector('[data-handle="ne"]');
                const hE  = handleGrp.querySelector('[data-handle="e"]');
                const hSe = handleGrp.querySelector('[data-handle="se"]');
                const hS  = handleGrp.querySelector('[data-handle="s"]');
                const hSw = handleGrp.querySelector('[data-handle="sw"]');
                const hW  = handleGrp.querySelector('[data-handle="w"]');
                if (hNw) { hNw.setAttribute("cx", nx); hNw.setAttribute("cy", ny); }
                if (hN)  { hN.setAttribute("cx", nx + nw / 2); hN.setAttribute("cy", ny); }
                if (hNe) { hNe.setAttribute("cx", nx + nw); hNe.setAttribute("cy", ny); }
                if (hE)  { hE.setAttribute("cx", nx + nw); hE.setAttribute("cy", ny + nh / 2); }
                if (hSe) { hSe.setAttribute("cx", nx + nw); hSe.setAttribute("cy", ny + nh); }
                if (hS)  { hS.setAttribute("cx", nx + nw / 2); hS.setAttribute("cy", ny + nh); }
                if (hSw) { hSw.setAttribute("cx", nx); hSw.setAttribute("cy", ny + nh); }
                if (hW)  { hW.setAttribute("cx", nx); hW.setAttribute("cy", ny + nh / 2); }

                // Resolve clean room title
                const lbl = selGrp.querySelector(".room-header, .room-label");
                const rawName = areaName || this._capabilityMap?.areas?.[this._selectedEditorRoomId]?.name || this._dirtyRooms[this._selectedEditorRoomId]?.name || lbl?.textContent || this._selectedEditorRoomId;
                const cleanName = String(rawName).replace(/^(?:\s*(?:x|y)="[^"]*"[>\s]*)+/g, "").trim();

                if (lbl) {
                  lbl.setAttribute("x", nx + 14);
                  lbl.setAttribute("y", ny + 22);
                  lbl.textContent = cleanName;
                }

                // Update architectural subzone pills in sync
                selGrp.querySelectorAll(".subzone-pill").forEach((pill, pIdx) => {
                  pill.setAttribute("x", nx + 16);
                  pill.setAttribute("y", ny + 22 + 18 + pIdx * 16);
                  if (pill.textContent) {
                    pill.textContent = pill.textContent.replace(/^(?:\s*(?:x|y)="[^"]*"[>\s]*)+/g, "").trim();
                  }
                });

                // Update internal entity badges in sync
                selGrp.querySelectorAll(".entity-badge").forEach((badge, bIdx) => {
                  badge.setAttribute("transform", `translate(${nx + 16 + bIdx * 24}, ${ny + nh - 18})`);
                });

                // Update stairs if present
                const stairsBox = selGrp.querySelector('rect[fill*="rgba(56, 189, 248"]');
                if (stairsBox) {
                  const sx = nx + nw - 58;
                  const sy = ny + nh - 42;
                  stairsBox.setAttribute("x", sx);
                  stairsBox.setAttribute("y", sy);
                  selGrp.querySelectorAll(".stairs-step").forEach((line, sIdx) => {
                    const lx = sx + (sIdx + 1) * 9;
                    line.setAttribute("x1", lx);
                    line.setAttribute("y1", sy);
                    line.setAttribute("x2", lx);
                    line.setAttribute("y2", sy + 28);
                  });
                }

                // Update door-cut if present
                const doorCut = selGrp.querySelector(".door-cut");
                if (doorCut) {
                  doorCut.setAttribute("x1", nx + nw - 34);
                  doorCut.setAttribute("y1", ny + nh);
                  doorCut.setAttribute("x2", nx + nw - 12);
                  doorCut.setAttribute("y2", ny + nh);
                }

                if (inpX) inpX.value = Math.round(nx);
                if (inpY) inpY.value = Math.round(ny);
                if (inpW) inpW.value = Math.round(nw);
                if (inpH) inpH.value = Math.round(nh);

                this._dirtyRooms[this._selectedEditorRoomId] = {
                  id: this._selectedEditorRoomId,
                  x: Math.round(nx),
                  y: Math.round(ny),
                  width: Math.round(nw),
                  height: Math.round(nh),
                  name: cleanName,
                };
                this._hasUnsavedLayout = true;
                const saveBtn = root.querySelector("#btn-save-layout");
                if (saveBtn) saveBtn.textContent = "💾 Save Changes *";
              };

              // Make room body draggable (type: "move") with magnetic snapping
              rect.style.cursor = "move";
              rect.onpointerdown = (e) => {
                e.preventDefault();
                e.stopPropagation();
                const p = getSvgPoint(svgEl, e.clientX, e.clientY);
                const curX = parseFloat(rect.getAttribute("x") || 0);
                const curY = parseFloat(rect.getAttribute("y") || 0);
                const curW = parseFloat(rect.getAttribute("width") || 160);
                const curH = parseFloat(rect.getAttribute("height") || 120);
                this._resizingHandle = {
                  type: "move",
                  startPoint: p,
                  initX: curX,
                  initY: curY,
                  initW: curW,
                  initH: curH,
                  minX, maxX, minY, maxY,
                };
                try { rect.setPointerCapture(e.pointerId); } catch (_) {}
              };

              rect.onpointermove = (e) => {
                if (!this._resizingHandle || this._resizingHandle.type !== "move") return;
                e.preventDefault();
                e.stopPropagation();
                const p = getSvgPoint(svgEl, e.clientX, e.clientY);
                const dx = p.x - this._resizingHandle.startPoint.x;
                const dy = p.y - this._resizingHandle.startPoint.y;
                let nx = Math.max(minX, Math.min(Math.round(this._resizingHandle.initX + dx), maxX - this._resizingHandle.initW));
                let ny = Math.max(minY, Math.min(Math.round(this._resizingHandle.initY + dy), maxY - this._resizingHandle.initH));
                const snapped = snapCoordinates(nx, ny, this._resizingHandle.initW, this._resizingHandle.initH, true);
                nx = Math.max(minX, Math.min(snapped.x, maxX - this._resizingHandle.initW));
                ny = Math.max(minY, Math.min(snapped.y, maxY - this._resizingHandle.initH));
                updateRoomElements(nx, ny, this._resizingHandle.initW, this._resizingHandle.initH);
              };

              rect.onpointerup = (e) => {
                if (this._resizingHandle && this._resizingHandle.type === "move") {
                  try { rect.releasePointerCapture(e.pointerId); } catch (_) {}
                  this._resizingHandle = null;
                  clearSnapGuides();
                }
              };
              rect.onpointercancel = (e) => {
                if (this._resizingHandle && this._resizingHandle.type === "move") {
                  try { rect.releasePointerCapture(e.pointerId); } catch (_) {}
                  this._resizingHandle = null;
                  clearSnapGuides();
                }
              };

              // Attach event handlers to all 8 handles with boundary clamping & snapping
              handleGrp.querySelectorAll(".room-resize-handle").forEach((handle) => {
                handle.onpointerdown = (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const p = getSvgPoint(svgEl, e.clientX, e.clientY);
                  const handleType = handle.getAttribute("data-handle");
                  const curX = parseFloat(rect.getAttribute("x") || 0);
                  const curY = parseFloat(rect.getAttribute("y") || 0);
                  const curW = parseFloat(rect.getAttribute("width") || 160);
                  const curH = parseFloat(rect.getAttribute("height") || 120);
                  this._resizingHandle = {
                    type: handleType,
                    startPoint: p,
                    initX: curX,
                    initY: curY,
                    initW: curW,
                    initH: curH,
                    minX, maxX, minY, maxY,
                  };
                  try { handle.setPointerCapture(e.pointerId); } catch (_) {}
                };

                handle.onpointermove = (e) => {
                  if (!this._resizingHandle || this._resizingHandle.type === "move") return;
                  e.preventDefault();
                  e.stopPropagation();
                  const p = getSvgPoint(svgEl, e.clientX, e.clientY);
                  const dx = p.x - this._resizingHandle.startPoint.x;
                  const dy = p.y - this._resizingHandle.startPoint.y;
                  const initX = this._resizingHandle.initX;
                  const initY = this._resizingHandle.initY;
                  const initW = this._resizingHandle.initW;
                  const initH = this._resizingHandle.initH;
                  const hType = this._resizingHandle.type;

                  let nx = initX;
                  let ny = initY;
                  let nw = initW;
                  let nh = initH;

                  if (hType === "e") {
                    nw = Math.max(60, Math.min(Math.round(initW + dx), maxX - initX));
                  } else if (hType === "w") {
                    const propX = Math.max(minX, Math.min(Math.round(initX + dx), initX + initW - 60));
                    nx = propX;
                    nw = (initX + initW) - nx;
                  } else if (hType === "s") {
                    nh = Math.max(50, Math.min(Math.round(initH + dy), maxY - initY));
                  } else if (hType === "n") {
                    const propY = Math.max(minY, Math.min(Math.round(initY + dy), initY + initH - 50));
                    ny = propY;
                    nh = (initY + initH) - ny;
                  } else if (hType === "se") {
                    nw = Math.max(60, Math.min(Math.round(initW + dx), maxX - initX));
                    nh = Math.max(50, Math.min(Math.round(initH + dy), maxY - initY));
                  } else if (hType === "sw") {
                    const propX = Math.max(minX, Math.min(Math.round(initX + dx), initX + initW - 60));
                    nx = propX;
                    nw = (initX + initW) - nx;
                    nh = Math.max(50, Math.min(Math.round(initH + dy), maxY - initY));
                  } else if (hType === "ne") {
                    nw = Math.max(60, Math.min(Math.round(initW + dx), maxX - initX));
                    const propY = Math.max(minY, Math.min(Math.round(initY + dy), initY + initH - 50));
                    ny = propY;
                    nh = (initY + initH) - ny;
                  } else if (hType === "nw") {
                    const propX = Math.max(minX, Math.min(Math.round(initX + dx), initX + initW - 60));
                    const propY = Math.max(minY, Math.min(Math.round(initY + dy), initY + initH - 50));
                    nx = propX;
                    ny = propY;
                    nw = (initX + initW) - nx;
                    nh = (initY + initH) - ny;
                  }

                  const snapped = snapCoordinates(nx, ny, nw, nh, false);
                  nx = Math.max(minX, snapped.x);
                  ny = Math.max(minY, snapped.y);
                  nw = Math.max(60, Math.min(snapped.width, maxX - nx));
                  nh = Math.max(50, Math.min(snapped.height, maxY - ny));

                  updateRoomElements(nx, ny, nw, nh);
                };

                handle.onpointerup = (e) => {
                  if (this._resizingHandle && this._resizingHandle.type !== "move") {
                    try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
                    this._resizingHandle = null;
                    clearSnapGuides();
                  }
                };
                handle.onpointercancel = (e) => {
                  if (this._resizingHandle && this._resizingHandle.type !== "move") {
                    try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
                    this._resizingHandle = null;
                    clearSnapGuides();
                  }
                };
              });
            }
          }
        }
      } else {
        // --- Normal Interactive Viewer Mode ---
        svgViewport.querySelectorAll("[data-entity-id]").forEach((badge) => {
          badge.style.cursor = "pointer";
          badge.onclick = (e) => {
            e.stopPropagation();
            const entityId = badge.getAttribute("data-entity-id");
            if (!entityId || !this._hass) return;
            const domain = entityId.split(".")[0];
            if (domain === "light" || domain === "switch") {
              this._hass.callService("homeassistant", "toggle", { entity_id: entityId });
              const st = this._hass.states[entityId];
              const newState = st?.state === "on" ? "off" : "on";
              this._showToast(`${st?.attributes?.friendly_name || entityId} turned ${newState}`);
            } else {
              const ev = new CustomEvent("hass-more-info", {
                detail: { entityId },
                bubbles: true,
                composed: true,
              });
              this.dispatchEvent(ev);
              window.dispatchEvent(ev);
            }
          };
        });

        svgViewport.querySelectorAll(".room-group").forEach((grp) => {
          grp.style.cursor = "pointer";
          grp.onclick = () => {
            const areaId = grp.getAttribute("data-area-id");
            const area = this._capabilityMap?.areas?.[areaId];
            if (area) {
              const slug = areaId.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "room";
              this._selectedRoomInfo = {
                areaId,
                name: area.name || areaId,
                slug,
                zone: grp.getAttribute("data-zone") || "indoor",
                entities: area.entities || [],
              };
              this._render();
            }
          };
        });

        svgViewport.querySelectorAll(".room-header").forEach((hdr) => {
          hdr.style.cursor = "pointer";
          hdr.onclick = (e) => {
            e.stopPropagation();
            const grp = hdr.closest(".room-group");
            const areaId = grp?.getAttribute("data-area-id");
            if (areaId) {
              const slug = areaId.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "room";
              const path = `/otis-ai/area_${slug}`;
              window.history.pushState(null, "", path);
              window.dispatchEvent(new CustomEvent("location-changed"));
            }
          };
        });
      }
    }

    // Room Info and Inspector Close Buttons
    const btnCloseRoomInfo = root.querySelector("#btn-close-room-info");
    if (btnCloseRoomInfo) {
      btnCloseRoomInfo.onclick = () => {
        this._selectedRoomInfo = null;
        this._render();
      };
    }

    // Room Info Quick Toggles & Navigation
    root.querySelectorAll(".btn-quick-toggle").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const eid = btn.getAttribute("data-entity-id");
        if (!eid || !this._hass) return;
        const domain = eid.split(".")[0];
        if (domain === "light" || domain === "switch") {
          this._hass.callService("homeassistant", "toggle", { entity_id: eid });
          const st = this._hass.states[eid];
          const newState = st?.state === "on" ? "off" : "on";
          this._showToast(`${st?.attributes?.friendly_name || eid} turned ${newState}`);
        } else {
          const ev = new CustomEvent("hass-more-info", {
            detail: { entityId: eid },
            bubbles: true,
            composed: true,
          });
          this.dispatchEvent(ev);
          window.dispatchEvent(ev);
        }
      };
    });

    root.querySelectorAll(".btn-nav-room").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const p = btn.getAttribute("data-room-path");
        if (p) {
          window.dispatchEvent(new CustomEvent("hass-navigate", { detail: { href: p }, bubbles: true, composed: true }));
          window.history.pushState(null, "", p);
          window.dispatchEvent(new CustomEvent("location-changed"));
        }
      };
    });

    // Sentinel Alert Ignore Actions
    root.querySelectorAll(".btn-ignore-alert").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const aId = btn.getAttribute("data-ignore-id");
        if (!aId) return;
        this._dismissSuggestion(aId);
        try {
          await this._hass.callService("otis_ai", "ignore_sentinel_alert", { anomaly_id: aId });
          this._showToast("Alert ignored");
          await this._fetchData();
        } catch (_) {}
      };
    });

    root.querySelectorAll(".btn-ignore-category").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const cat = btn.getAttribute("data-ignore-cat");
        if (!cat) return;
        (this._suggestions || []).forEach((s) => {
          if (s.anomaly_type === cat || s.action_payload?.category === cat) {
            this._dismissedIds.add(s.id);
          }
        });
        this._saveDismissedIds();
        this._render();
        try {
          await this._hass.callService("otis_ai", "ignore_sentinel_alert", { category: cat, all_in_category: true });
          const catName = cat === "battery" ? "low battery" : cat === "offline_node" ? "offline node" : cat;
          this._showToast(`All ${catName} alerts ignored`);
          await this._fetchData();
        } catch (_) {}
      };
    });
    const btnCloseInspector = root.querySelector("#btn-close-inspector");
    if (btnCloseInspector) {
      btnCloseInspector.onclick = () => {
        this._selectedEditorRoomId = null;
        this._render();
      };
    }

    // Draggable Area Boundary Editor (Inspector) Card
    const inspectorEl = root.querySelector("#room-inspector");
    const inspectorHeader = root.querySelector("#inspector-header");
    if (inspectorEl && inspectorHeader) {
      let isDraggingInspector = false;
      let startX = 0;
      let startY = 0;
      let startLeft = 0;
      let startTop = 0;

      inspectorHeader.onpointerdown = (e) => {
        if (e.target && e.target.id === "btn-close-inspector") return;
        e.preventDefault();
        e.stopPropagation();
        isDraggingInspector = true;
        startX = e.clientX;
        startY = e.clientY;
        const parentRect = (inspectorEl.parentElement || root).getBoundingClientRect();
        const rect = inspectorEl.getBoundingClientRect();
        startLeft = rect.left - parentRect.left;
        startTop = rect.top - parentRect.top;
        try { inspectorHeader.setPointerCapture(e.pointerId); } catch (_) {}
      };

      inspectorHeader.onpointermove = (e) => {
        if (!isDraggingInspector) return;
        e.preventDefault();
        e.stopPropagation();
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        const parentRect = (inspectorEl.parentElement || root).getBoundingClientRect();
        const maxLeft = Math.max(0, parentRect.width - inspectorEl.offsetWidth);
        const maxTop = Math.max(0, parentRect.height - inspectorEl.offsetHeight);
        const newLeft = Math.max(0, Math.min(startLeft + dx, maxLeft));
        const newTop = Math.max(0, Math.min(startTop + dy, maxTop));
        inspectorEl.style.left = `${newLeft}px`;
        inspectorEl.style.top = `${newTop}px`;
        inspectorEl.style.right = "auto";
        inspectorEl.style.bottom = "auto";
        this._inspectorX = Math.round(newLeft);
        this._inspectorY = Math.round(newTop);
      };

      const endDragInspector = (e) => {
        if (isDraggingInspector) {
          try { inspectorHeader.releasePointerCapture(e.pointerId); } catch (_) {}
          isDraggingInspector = false;
        }
      };
      inspectorHeader.onpointerup = endDragInspector;
      inspectorHeader.onpointercancel = endDragInspector;
    }

    // Boundary Inspector: Area Rebinding & Direct Numerical Dimensions
    const btnApplyDim = root.querySelector("#btn-apply-inspector-dim");
    if (btnApplyDim && this._selectedEditorRoomId) {
      btnApplyDim.onclick = () => {
        const rid = this._selectedEditorRoomId;
        const selArea = root.querySelector("#editor-area-select")?.value || rid;
        let nx = Math.round(parseFloat(root.querySelector("#inspector-room-x")?.value || 0));
        let ny = Math.round(parseFloat(root.querySelector("#inspector-room-y")?.value || 0));
        let nw = Math.max(60, Math.round(parseFloat(root.querySelector("#inspector-room-w")?.value || 160)));
        let nh = Math.max(50, Math.round(parseFloat(root.querySelector("#inspector-room-h")?.value || 120)));

        const areaName = this._capabilityMap?.areas?.[selArea]?.name;

        // Blueprint plan clamping
        const selGrp = svgEl ? svgEl.querySelector(`.room-group[data-area-id="${rid}"]`) : null;
        let minX = 40;
        let maxX = 1260;
        let minY = 30;
        let maxY = 1400;
        if (selGrp) {
          const planGroup = selGrp.closest("[data-plan]") || selGrp.closest(".floor-zone") || svgEl;
          const planFrame = planGroup.querySelector(".plan-frame");
          if (planFrame) {
            const fx = parseFloat(planFrame.getAttribute("x") || 40);
            const fy = parseFloat(planFrame.getAttribute("y") || 30);
            const fw = parseFloat(planFrame.getAttribute("width") || 1220);
            const fh = parseFloat(planFrame.getAttribute("height") || 650);
            minX = Math.round(fx + 5);
            maxX = Math.round(fx + fw - 5);
            minY = Math.round(fy + 34);
            maxY = Math.round(fy + fh - 5);
          }
        }

        nx = Math.max(minX, Math.min(nx, maxX - 60));
        ny = Math.max(minY, Math.min(ny, maxY - 50));
        nw = Math.max(60, Math.min(nw, maxX - nx));
        nh = Math.max(50, Math.min(nh, maxY - ny));

        // Update SVG DOM directly without re-rendering to prevent snap-back
        if (selGrp) {
          const rect = selGrp.querySelector(".room-box, .room-rect");
          if (rect) {
            rect.setAttribute("x", nx);
            rect.setAttribute("y", ny);
            rect.setAttribute("width", nw);
            rect.setAttribute("height", nh);
          }
          const lbl = selGrp.querySelector(".room-header, .room-label");
          if (lbl) {
            lbl.setAttribute("x", nx + 14);
            lbl.setAttribute("y", ny + 22);
            if (areaName) lbl.textContent = areaName;
          }
          const handleGrp = selGrp.querySelector(".handles-layer");
          if (handleGrp) {
            const hNw = handleGrp.querySelector('[data-handle="nw"]');
            const hN  = handleGrp.querySelector('[data-handle="n"]');
            const hNe = handleGrp.querySelector('[data-handle="ne"]');
            const hE  = handleGrp.querySelector('[data-handle="e"]');
            const hSe = handleGrp.querySelector('[data-handle="se"]');
            const hS  = handleGrp.querySelector('[data-handle="s"]');
            const hSw = handleGrp.querySelector('[data-handle="sw"]');
            const hW  = handleGrp.querySelector('[data-handle="w"]');
            if (hNw) { hNw.setAttribute("cx", nx); hNw.setAttribute("cy", ny); }
            if (hN)  { hN.setAttribute("cx", nx + nw / 2); hN.setAttribute("cy", ny); }
            if (hNe) { hNe.setAttribute("cx", nx + nw); hNe.setAttribute("cy", ny); }
            if (hE)  { hE.setAttribute("cx", nx + nw); hE.setAttribute("cy", ny + nh / 2); }
            if (hSe) { hSe.setAttribute("cx", nx + nw); hSe.setAttribute("cy", ny + nh); }
            if (hS)  { hS.setAttribute("cx", nx + nw / 2); hS.setAttribute("cy", ny + nh); }
            if (hSw) { hSw.setAttribute("cx", nx); hSw.setAttribute("cy", ny + nh); }
            if (hW)  { hW.setAttribute("cx", nx); hW.setAttribute("cy", ny + nh / 2); }
          }

          // Update subzone pills
          selGrp.querySelectorAll(".subzone-pill").forEach((pill, pIdx) => {
            pill.setAttribute("x", nx + 16);
            pill.setAttribute("y", ny + 22 + 18 + pIdx * 16);
          });

          // Update entity badges
          selGrp.querySelectorAll(".entity-badge").forEach((badge, bIdx) => {
            badge.setAttribute("transform", `translate(${nx + 16 + bIdx * 24}, ${ny + nh - 18})`);
          });

          // Update stairs if present
          const stairsBox = selGrp.querySelector('rect[fill*="rgba(56, 189, 248"]');
          if (stairsBox) {
            const sx = nx + nw - 58;
            const sy = ny + nh - 42;
            stairsBox.setAttribute("x", sx);
            stairsBox.setAttribute("y", sy);
            selGrp.querySelectorAll(".stairs-step").forEach((line, sIdx) => {
              const lx = sx + (sIdx + 1) * 9;
              line.setAttribute("x1", lx);
              line.setAttribute("y1", sy);
              line.setAttribute("x2", lx);
              line.setAttribute("y2", sy + 28);
            });
          }

          // Update door cut if present
          const doorCut = selGrp.querySelector(".door-cut");
          if (doorCut) {
            doorCut.setAttribute("x1", nx + nw - 34);
            doorCut.setAttribute("y1", ny + nh);
            doorCut.setAttribute("x2", nx + nw - 12);
            doorCut.setAttribute("y2", ny + nh);
          }
        }

        const inpX = root.querySelector("#inspector-room-x");
        const inpY = root.querySelector("#inspector-room-y");
        const inpW = root.querySelector("#inspector-room-w");
        const inpH = root.querySelector("#inspector-room-h");
        if (inpX) inpX.value = nx;
        if (inpY) inpY.value = ny;
        if (inpW) inpW.value = nw;
        if (inpH) inpH.value = nh;

        this._dirtyRooms[rid] = {
          id: rid,
          x: nx,
          y: ny,
          width: nw,
          height: nh,
          name: areaName,
        };
        this._hasUnsavedLayout = true;
        const saveBtn = root.querySelector("#btn-save-layout");
        if (saveBtn) saveBtn.textContent = "💾 Save Changes *";
        this._showToast(`Boundary updated for ${areaName || rid}! Click Save Layout to persist.`);
      };
    }

    const btnDeleteRoom = root.querySelector("#btn-delete-inspector-room");
    if (btnDeleteRoom && this._selectedEditorRoomId) {
      btnDeleteRoom.onclick = async (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const rid = this._selectedEditorRoomId;
        const areaName = this._capabilityMap?.areas?.[rid]?.name || rid;
        if (!confirm(`Are you sure you want to delete room "${areaName}" (${rid}) from the floor plan?`)) {
          return;
        }
        try {
          this._showToast(`Deleting room ${areaName}...`);
          const res = await this._hass.callService("otis_ai", "update_floorplan_layout", {
            deleted_rooms: [rid],
          });
          this._selectedEditorRoomId = null;
          delete this._dirtyRooms[rid];
          this._showToast(`Room "${areaName}" removed from floor plan.`);
          if (res?.url) {
            await this._loadFloorplanSvg(res.url);
          } else if (this._capabilityMap?.floorplan?.url) {
            await this._loadFloorplanSvg(this._capabilityMap.floorplan.url);
          }
          await this._fetchData();
          this._render();
        } catch (err) {
          console.error("Failed to delete room:", err);
          this._showToast(`Failed to delete room: ${err.message || err}`, true);
        }
      };
    }

    // Canvas Editor Toolbar Controls
    const btnToggleEditor = root.querySelector("#btn-toggle-editor");
    if (btnToggleEditor) {
      btnToggleEditor.onclick = () => {
        this._editorActive = !this._editorActive;
        if (!this._editorActive) {
          this._selectedEditorRoomId = null;
        }
        this._render();
      };
    }
    const btnExitEditor = root.querySelector("#btn-exit-editor");
    if (btnExitEditor) {
      btnExitEditor.onclick = () => {
        this._editorActive = false;
        this._selectedEditorRoomId = null;
        this._render();
      };
    }

    // Save Layout Button
    const btnSaveLayout = root.querySelector("#btn-save-layout");
    if (btnSaveLayout) {
      btnSaveLayout.onclick = async (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const badgesPayload = Object.values(this._dirtyBadges);
        const roomsPayload = Object.values(this._dirtyRooms);
        if (badgesPayload.length === 0 && roomsPayload.length === 0) {
          this._showToast("No layout changes to save.");
          return;
        }
        this._savingLayout = true;
        this._render();
        try {
          const res = await this._hass.callService(
            "otis_ai",
            "update_floorplan_layout",
            { badges: badgesPayload, rooms: roomsPayload },
            undefined,
            true,
            true
          );
          const data = res?.response || res || {};
          if (data.success) {
            this._showToast(data.message || "Floor plan layout saved & synced to Command Center!");
            this._dirtyBadges = {};
            this._dirtyRooms = {};
            this._hasUnsavedLayout = false;
            if (data.url) {
              await this._loadFloorplanSvg(data.url);
            }
            await this._fetchData();
          } else {
            this._showToast(data.error || "Failed to update layout", true);
          }
        } catch (err) {
          console.error("Error saving floorplan layout:", err);
          this._showToast("Error updating layout. Check HA logs.", true);
        } finally {
          this._savingLayout = false;
          this._render();
        }
      };
    }

    // Add Pin Modal & Selection
    const btnOpenAddMarker = root.querySelector("#btn-open-add-marker");
    if (btnOpenAddMarker) {
      btnOpenAddMarker.onclick = () => {
        this._addMarkerModalOpen = true;
        this._render();
      };
    }
    const addMarkerCloseBtn = root.querySelector("#add-marker-close-btn");
    if (addMarkerCloseBtn) {
      addMarkerCloseBtn.onclick = () => {
        this._addMarkerModalOpen = false;
        this._render();
      };
    }
    root.querySelectorAll(".btn-place-entity-pin").forEach((btn) => {
      btn.onclick = () => {
        const eid = btn.getAttribute("data-entity-id");
        if (eid) {
          this._dirtyBadges[eid] = {
            entity_id: eid,
            x: 320,
            y: 280,
          };
          this._hasUnsavedLayout = true;
          this._addMarkerModalOpen = false;
          this._showToast(`Dropped pin for ${eid}! Drag to position and click Save.`);
          this._render();
        }
      };
    });

    // Floorplan Toolbar Buttons
    const btnOpenWalkthrough = root.querySelector("#btn-open-walkthrough");
    if (btnOpenWalkthrough) {
      btnOpenWalkthrough.onclick = () => {
        this._floorplanModalOpen = true;
        this._render();
      };
    }

    const btnStartWalkthrough = root.querySelector("#btn-start-walkthrough");
    if (btnStartWalkthrough) {
      btnStartWalkthrough.onclick = () => {
        this._floorplanModalOpen = true;
        this._render();
      };
    }

    const btnCopyLovelace = root.querySelector("#btn-copy-lovelace");
    if (btnCopyLovelace) {
      btnCopyLovelace.onclick = () => this._copyLovelaceYaml();
    }

    const btnBannerWalkthrough = root.querySelector("#btn-banner-walkthrough");
    if (btnBannerWalkthrough) {
      btnBannerWalkthrough.onclick = () => {
        this._floorplanModalOpen = true;
        this._render();
      };
    }

    const btnQuickGen = root.querySelector("#btn-quick-generate");
    if (btnQuickGen) {
      btnQuickGen.onclick = () => this._generateFloorplanDirect(this._spokenOrderOverride);
    }

    const btnInstantGenModal = root.querySelector("#btn-instant-generate-modal");
    if (btnInstantGenModal) {
      btnInstantGenModal.onclick = () => this._generateFloorplanDirect(this._spokenOrderOverride);
    }

    // Walkthrough Modal: Close, Dropzone, and Upload
    const modalBackdrop = root.querySelector("#walkthrough-modal-backdrop");
    const modalCloseBtn = root.querySelector("#modal-close-btn");
    if (modalCloseBtn) {
      modalCloseBtn.onclick = () => {
        this._floorplanModalOpen = false;
        this._render();
      };
    }
    if (modalBackdrop) {
      modalBackdrop.onclick = (e) => {
        if (e.target === modalBackdrop) {
          this._floorplanModalOpen = false;
          this._render();
        }
      };
    }

    const fileInput = root.querySelector("#walkthrough-file-input");
    const dropzone = root.querySelector("#walkthrough-dropzone");
    const dropzoneText = root.querySelector("#dropzone-selected-filename");
    const submitBtn = root.querySelector("#btn-submit-walkthrough");
    const spokenInput = root.querySelector("#spoken-order-input");

    if (spokenInput) {
      spokenInput.oninput = (e) => {
        this._spokenOrderOverride = e.target.value;
      };
    }

    if (dropzone && fileInput) {
      const updateSelectedFiles = (fileList) => {
        const files = Array.from(fileList || []);
        if (files.length === 0) return;
        this._selectedWalkthroughFiles = files;
        const totalMB = (files.reduce((acc, f) => acc + f.size, 0) / (1024 * 1024)).toFixed(1);
        if (dropzoneText) {
          dropzoneText.textContent =
            files.length === 1
              ? `📹 ${files[0].name} (${totalMB} MB)`
              : `📹 ${files.length} videos selected (${totalMB} MB): ${files.map((f) => f.name).join(", ")}`;
        }
        if (submitBtn) submitBtn.disabled = false;
      };

      dropzone.onclick = () => fileInput.click();
      dropzone.ondragover = (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
      };
      dropzone.ondragleave = () => dropzone.classList.remove("dragover");
      dropzone.ondrop = (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer?.files?.length > 0) {
          updateSelectedFiles(e.dataTransfer.files);
        }
      };

      fileInput.onchange = (e) => {
        if (e.target.files?.length > 0) {
          updateSelectedFiles(e.target.files);
        }
      };
    }

    if (submitBtn) {
      submitBtn.onclick = () => {
        const filesToUpload = this._selectedWalkthroughFiles || [];
        if (filesToUpload.length > 0) {
          this._uploadWalkthroughVideo(filesToUpload, this._spokenOrderOverride);
        }
      };
    }
  }
}

// Visual Card Editor for Lovelace UI Dashboard Builder
class OtisCompanionCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = {
      title: "Otis AI Companion",
      theme_preset: "cyberpunk",
      show_chat: true,
      show_suggestions: true,
      show_stats: true,
      max_suggestions: 5,
      ...config,
    };
    this._render();
  }

  _render() {
    if (!this.shadowRoot) return;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 8px 0;
          font-family: var(--ha-card-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
          color: var(--primary-text-color, #e2e8f0);
        }
        .editor-container {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .form-row {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .form-row.checkbox-row {
          flex-direction: row;
          align-items: center;
          justify-content: space-between;
          padding: 6px 0;
          border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.06));
        }
        label {
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--primary-text-color, #e2e8f0);
        }
        .sub-label {
          font-size: 0.74rem;
          color: var(--secondary-text-color, #94a3b8);
          line-height: 1.3;
        }
        input[type="text"], input[type="number"], select {
          width: 100%;
          padding: 9px 12px;
          background: var(--card-background-color, rgba(15, 23, 42, 0.6));
          border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.15));
          border-radius: 8px;
          color: var(--primary-text-color, #f8fafc);
          font-size: 0.85rem;
          box-sizing: border-box;
          outline: none;
        }
        input[type="text"]:focus, input[type="number"]:focus, select:focus {
          border-color: var(--primary-color, #38bdf8);
        }
        select option {
          background: #1e293b;
          color: #f8fafc;
        }
        input[type="checkbox"] {
          width: 18px;
          height: 18px;
          cursor: pointer;
          accent-color: var(--primary-color, #38bdf8);
        }
        .cardmod-badge {
          background: rgba(56, 189, 248, 0.08);
          border: 1px solid rgba(56, 189, 248, 0.22);
          border-radius: 10px;
          padding: 10px 14px;
          font-size: 0.76rem;
          line-height: 1.4;
          color: var(--primary-text-color, #e2e8f0);
          margin-top: 4px;
        }
        .cardmod-badge code {
          background: rgba(0, 0, 0, 0.35);
          padding: 2px 5px;
          border-radius: 4px;
          color: #38bdf8;
          font-family: monospace;
        }
      </style>

      <div class="editor-container">
        <div class="form-row">
          <label for="cfg-title">Card Title</label>
          <input type="text" id="cfg-title" data-config="title" value="${this._escapeHtml(this._config.title || "Otis AI Companion")}">
        </div>

        <div class="form-row">
          <label for="cfg-theme">Theme Preset</label>
          <div class="sub-label">Select visual aesthetic preset or sync with Home Assistant Lovelace themes</div>
          <select id="cfg-theme" data-config="theme_preset">
            <option value="ha_native" ${(!this._config.theme_preset || this._config.theme_preset === "ha_native") ? "selected" : ""}>Home Assistant System Theme (Default - Follows Active HA Theme)</option>
            <option value="cyberpunk" ${this._config.theme_preset === "cyberpunk" ? "selected" : ""}>Cyberpunk Neon (Cyan & Lavender Glow)</option>
            <option value="midnight" ${this._config.theme_preset === "midnight" ? "selected" : ""}>Midnight Navy (Deep Obsidian & Cobalt)</option>
            <option value="emerald" ${this._config.theme_preset === "emerald" ? "selected" : ""}>Emerald Matrix (Forest Dark & Cyber Mint)</option>
            <option value="sunset" ${this._config.theme_preset === "sunset" ? "selected" : ""}>Sunset Amber (Velvet Twilight & Coral)</option>
            <option value="light_frost" ${this._config.theme_preset === "light_frost" ? "selected" : ""}>Light Frost (Crisp Pearl White Frosted Glass)</option>
          </select>
        </div>

        <div class="form-row checkbox-row">
          <div>
            <label for="cfg-stats">Quick Intelligence Stats</label>
            <div class="sub-label">Display summary chips for areas, entities, and automations</div>
          </div>
          <input type="checkbox" id="cfg-stats" data-config="show_stats" ${this._config.show_stats !== false ? "checked" : ""}>
        </div>

        <div class="form-row checkbox-row">
          <div>
            <label for="cfg-suggestions">Proactive Suggestions Feed</label>
            <div class="sub-label">Show automated suggestions with 1-click execution</div>
          </div>
          <input type="checkbox" id="cfg-suggestions" data-config="show_suggestions" ${this._config.show_suggestions !== false ? "checked" : ""}>
        </div>

        <div class="form-row checkbox-row">
          <div>
            <label for="cfg-chat">Assist Co-Pilot Chat</label>
            <div class="sub-label">Embedded chat interface for conversational actions</div>
          </div>
          <input type="checkbox" id="cfg-chat" data-config="show_chat" ${this._config.show_chat !== false ? "checked" : ""}>
        </div>

        <div class="form-row">
          <label for="cfg-max">Max Suggestions Displayed</label>
          <input type="number" id="cfg-max" data-config="max_suggestions" min="1" max="20" value="${this._config.max_suggestions || 5}">
        </div>

        <div class="cardmod-badge">
          ✨ <strong>Card-mod & Custom Theme Ready:</strong> The card wraps in <code>ha-card</code> and supports <code>lovelace-card-mod</code>. Target <code>ha-card</code> to adjust tokens like <code>--otis-primary</code>, <code>--otis-bg</code>, or standard Home Assistant variables.
        </div>
      </div>
    `;

    this._bindEvents();
  }

  _loadActiveTab() {
    try {
      const saved = sessionStorage.getItem("otis_active_tab");
      if (saved && ["suggestions", "chat", "capabilities", "floorplan"].includes(saved)) {
        return saved;
      }
    } catch (_) {}
    return "suggestions";
  }

  _saveActiveTab(tab) {
    if (["suggestions", "chat", "capabilities", "floorplan"].includes(tab)) {
      this._activeTab = tab;
      try {
        sessionStorage.setItem("otis_active_tab", tab);
      } catch (_) {}
    }
  }

  _loadChatMessages() {
    try {
      const saved = sessionStorage.getItem("otis_chat_messages");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch (_) {}
    return [];
  }

  _saveChatMessages() {
    try {
      sessionStorage.setItem("otis_chat_messages", JSON.stringify(this._chatMessages.slice(-50)));
    } catch (_) {}
  }

  _escapeHtml(str) {
    return String(str).replace(/"/g, "&quot;");
  }

  _bindEvents() {
    const inputs = this.shadowRoot.querySelectorAll("[data-config]");
    inputs.forEach((input) => {
      input.onchange = (e) => this._handleChange(e);
      if (input.tagName === "INPUT" && input.type === "text") {
        input.oninput = (e) => this._handleChange(e);
      }
    });
  }

  _handleChange(e) {
    if (!this._config) return;
    const target = e.target;
    const key = target.getAttribute("data-config");
    let val;
    if (target.type === "checkbox") {
      val = target.checked;
    } else if (target.type === "number") {
      val = parseInt(target.value, 10) || 5;
    } else {
      val = target.value;
    }

    this._config = {
      ...this._config,
      [key]: val,
    };

    const event = new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }
}

customElements.define("otis-companion-card", OtisCompanionCard);
customElements.define("otis-companion-card-editor", OtisCompanionCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "otis-companion-card",
  name: "Otis AI Companion Card",
  description: "Interactive smart home co-pilot card with proactive suggestions, quick actions, and Assist chat.",
  preview: true,
  documentationURL: "https://github.com/OtisPresley/otis-ai-companion",
});
