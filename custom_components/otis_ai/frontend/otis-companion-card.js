/**
 * Otis AI Companion - Lovelace Dashboard Card
 * Version: 1.5.8
 * 
 * An interactive, proactive smart home co-pilot card featuring:
 * - Frosted glassmorphism with Sky Cyan & Lavender Purple neon accents
 * - Live AI multi-agent status and health monitoring
 * - Proactive suggestions feed with category filter pills & 1-click coordinator execution
 * - Embedded Assist conversational co-pilot with quick prompt chips
 * - Multimodal Video-to-Floorplan SVG Parser & Interactive Viewer
 * - Smart Home Maturity Score & Media/Security Architecture Inspector
 */

const CARD_VERSION = "1.5.8";
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
    this._dismissedIds = new Set();
    this._loadingSuggestions = false;
    this._applyingIds = new Set();
    this._chatMessages = [];
    this._isSendingChat = false;
    this._isListening = false;
    this._recognition = null;
    this._activeTab = "suggestions"; // 'suggestions' | 'chat' | 'capabilities' | 'floorplan'
    this._selectedCategory = "all"; // 'all' | 'lighting' | 'media' | 'security' | 'cleanup' | 'system'
    this._conversationId = null;
    this._conversationAgentId = null;
    this._cachedAgentId = null;
    this._draftChatText = "";
    this._previewDismissed = false;

    // Phase 6: Floorplan & Walkthrough state
    this._floorplanModalOpen = false;
    this._themeModalOpen = false;
    this._generatingTheme = false;
    this._uploadingVideo = false;
    this._uploadProgressText = "";
    this._floorplanSvg = null;
    this._loadingFloorplan = false;
    this._selectedFloorZone = "all"; // 'all' | 'main' | 'upper' | 'outdoor'
    this._selectedRoomInfo = null;
    this._spokenOrderOverride = "";
    this._selectedWalkthroughFiles = [];
    this._discoveredWalkthroughAreas = [];
    this._hasWalkthrough = false;
    this._hasFloorplan = false;
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

  _ensureValidActiveTab() {
    if (this._activeTab === "suggestions" && this._config.show_suggestions === false) {
      this._activeTab = this._config.show_chat !== false ? "chat" : "floorplan";
    } else if (this._activeTab === "chat" && this._config.show_chat === false) {
      this._activeTab = this._config.show_suggestions !== false ? "suggestions" : "floorplan";
    }
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Load initial capability map and suggestions if not loaded
    if (!oldHass && hass) {
      this._fetchData();
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
        this._floorplanSvg = await resp.text();
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

  _dismissSuggestion(sId) {
    this._dismissedIds.add(sId);
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

    this._chatMessages.push({ sender: "user", text: userText, timestamp: new Date() });
    this._isSendingChat = true;
    this._render();

    try {
      let speech = "";

      // 1. First attempt direct otis_ai.chat service
      try {
        const directPayload = { text: userText };
        if (this._conversationId) {
          directPayload.conversation_id = this._conversationId;
        }
        const directRes = await this._hass.callService(
          "otis_ai",
          "chat",
          directPayload,
          undefined,
          true,
          true
        );
        const data = directRes?.response || directRes;
        if (data && data.response) {
          speech = data.response;
          if (data.conversation_id) {
            this._conversationId = data.conversation_id;
          }
        }
      } catch (serviceErr) {
        console.warn("otis_ai.chat service call unhandled or unavailable, falling back to conversation.process:", serviceErr);
      }

      // 2. Fallback: conversation.process with resolved agent_id & conversation_id
      if (!speech) {
        const agentId = await this._getConversationAgentId();
        const payload = { text: userText };
        if (agentId) {
          payload.agent_id = agentId;
        }
        if (this._conversationId) {
          payload.conversation_id = this._conversationId;
        }

        const res = await this._hass.callService(
          "conversation",
          "process",
          payload,
          undefined,
          true,
          true
        );

        speech =
          res?.response?.response?.speech?.plain?.speech ||
          res?.response?.speech?.plain?.speech ||
          res?.speech?.plain?.speech ||
          "I'm here to assist, but received an empty response.";

        const returnedConvId = res?.response?.conversation_id || res?.conversation_id;
        if (returnedConvId) {
          this._conversationId = returnedConvId;
        }
      }

      this._chatMessages.push({
        sender: "otis",
        text: speech,
        timestamp: new Date(),
      });

      if (
        speech &&
        (speech.includes("successfully created and enabled the automation") ||
          speech.includes("successfully created the script"))
      ) {
        this._fetchData();
      }
    } catch (err) {
      console.error("Error sending message to Otis:", err);
      this._chatMessages.push({
        sender: "otis",
        text: "I encountered an error connecting to the AI agent. Please check system logs or fallback configuration.",
        timestamp: new Date(),
        isError: true,
      });
    } finally {
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
    setTimeout(() => {
      const container = this.shadowRoot.querySelector("#chat-history");
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }, 50);
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
    const priorityRank = { high: 0, medium: 1, low: 2 };
    const activeSuggestions = (this._suggestions || [])
      .filter((s) => !this._dismissedIds.has(s.id))
      .slice()
      .sort((a, b) => {
        const rankA = priorityRank[String(a.priority || "medium").toLowerCase()] ?? 1;
        const rankB = priorityRank[String(b.priority || "medium").toLowerCase()] ?? 1;
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
          path: `/otis-ai/area_${slug}`,
        });
      }
    }
    activeAreas.sort((a, b) => a.name.localeCompare(b.name));

    const preset = this._config.theme_preset || this._config.theme || "ha_native";
    const themeClass = `theme-${preset.replace(/_/g, "-")}`;

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
          align-self: flex-end;
          background: var(--otis-user-bubble-bg);
          color: var(--otis-user-bubble-text);
          border-bottom-right-radius: 3px;
          border: 1px solid var(--otis-surface-border);
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
          max-height: 480px;
          display: flex;
          justify-content: center;
          align-items: center;
          position: relative;
          box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.5);
        }

        .floorplan-svg-viewport svg {
          width: 100%;
          height: auto;
          max-height: 450px;
          filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.4));
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

      <ha-card class="card-container ${themeClass}">
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
            <button class="icon-btn" id="refresh-btn" title="Refresh intelligence">
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
            <button class="subview-chip" data-subview="/otis-ai/media">🎵 Media Studio</button>
            <button class="subview-chip" data-subview="/otis-ai/security">🛡️ Security Center</button>
            <button class="subview-chip" data-subview="/otis-ai/climate">🌡️ Climate & Pool</button>
            <button class="subview-chip" data-subview="/otis-ai/floorplan">🗺️ Floor Plan</button>
            <button class="subview-chip" id="btn-open-themes" style="margin-left: auto;">🎨 Themes</button>
          </div>
          ${
            activeAreas.length > 0
              ? `
            <div class="launchpad-row">
              <span class="subviews-label">Rooms:</span>
              ${activeAreas
                .map(
                  (room) => `
                <button class="subview-chip room-chip" data-subview="${room.path}">📍 ${this._escapeHtml(room.name)}</button>
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
            <button class="tab-btn ${this._activeTab === "suggestions" ? "active" : ""}" id="tab-suggestions">
              Proactive Feed
              ${activeSuggestions.length > 0 ? `<span class="tab-badge">${activeSuggestions.length}</span>` : ""}
            </button>
          `
              : ""
          }
          ${
            this._config.show_chat !== false
              ? `
            <button class="tab-btn ${this._activeTab === "chat" ? "active" : ""}" id="tab-chat">
              Assist Co-Pilot
            </button>
          `
              : ""
          }
          <button class="tab-btn ${this._activeTab === "floorplan" ? "active" : ""}" id="tab-floorplan">
            Floor Plan
            ${this._capabilityMap?.floorplan?.exists ? "" : `<span class="tab-badge" style="background: var(--otis-accent, #a855f7);">New</span>`}
          </button>
          <button class="tab-btn ${this._activeTab === "capabilities" ? "active" : ""}" id="tab-capabilities">
            Capabilities
          </button>
        </div>

        ${this._activeTab === "suggestions" ? this._renderSuggestionsTab(visibleSuggestions) : ""}
        ${this._activeTab === "chat" ? this._renderChatTab() : ""}
        ${this._activeTab === "capabilities" ? this._renderCapabilitiesTab(stats) : ""}
        ${this._activeTab === "floorplan" ? this._renderFloorplanTab() : ""}
        ${this._floorplanModalOpen ? this._renderWalkthroughModal() : ""}
        ${this._themeModalOpen ? this._renderThemeModal() : ""}

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
          <button class="category-pill ${this._selectedCategory === c.key ? "active" : ""}" data-category-pill="${c.key}">
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
                        <button class="dismiss-btn" data-dismiss="${s.id}" title="Dismiss recommendation">✕</button>
                      </div>
                      <div class="suggestion-title">${s.title}</div>
                      <div class="suggestion-desc">${s.description}</div>
                      <div class="suggestion-actions">
                        <button class="apply-btn" data-apply="${s.id}" ${isApplying ? "disabled" : ""}>
                          ${isApplying ? `<div class="spinner"></div> Applying...` : btnLabel}
                        </button>
                      </div>
                    </div>
                  `;
                })
                .join("")
        }
      </div>
    `;
  }

  _renderChatTab() {
    return `
      <div class="chat-container">
        <div class="chat-chips">
          <button class="chip-btn" data-chip="Suggest automations for my active areas">💡 Suggest automations</button>
          <button class="chip-btn" data-chip="What can I improve in my smart home?">🔍 Improvement audit</button>
          <button class="chip-btn" data-chip="Clean up orphaned entities">🧹 Clean orphans</button>
          <button class="chip-btn" data-chip="Create an evening bedtime routine">🌙 Goodnight routine</button>
        </div>
        <div class="chat-history" id="chat-history">
          ${
            this._chatMessages.length === 0
              ? `<div class="empty-state" style="padding: 16px;">Ask Otis anything about your automations, devices, or areas.</div>`
              : this._chatMessages
                  .map(
                    (m) => `
                <div class="chat-bubble ${m.sender} ${m.isError ? "error" : ""}">
                  ${this._renderMarkdown(m.text)}
                </div>
              `
                  )
                  .join("")
          }
          ${
            this._isSendingChat
              ? `<div class="chat-bubble otis"><div class="spinner" style="display:inline-block; vertical-align:middle; margin-right:6px;"></div> Thinking...</div>`
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
            <button class="preview-close-btn" id="chat-preview-close" title="Dismiss preview">✕</button>
          </div>
          <div class="chat-live-preview-body" id="chat-live-preview-body"></div>
        </div>
        <div class="chat-input-bar">
          <div class="chat-input-wrapper ${this._isListening ? "listening" : ""}">
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
              placeholder="${this._isListening ? "Listening... speak now" : "Ask Otis or give a voice/text command... (Shift+Enter for newline)"}"
            >${this._draftChatText || ""}</textarea>
          </div>
          <button class="mic-btn ${this._isListening ? "listening" : ""}" id="chat-mic" title="${this._isListening ? "Listening... click to stop" : "Voice command"}" ${this._isSendingChat ? "disabled" : ""}>
            <svg viewBox="0 0 24 24" class="mic-icon">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
          </button>
          <button class="send-btn" id="chat-send" ${this._isSendingChat ? "disabled" : ""}>Send</button>
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
    return `
      <div class="floorplan-panel">
        <div class="floorplan-toolbar">
          <div class="zone-pills">
            <button class="zone-pill ${this._selectedFloorZone === "all" ? "active" : ""}" data-zone="all">All Floors</button>
            <button class="zone-pill ${this._selectedFloorZone === "main" ? "active" : ""}" data-zone="main">Ground &amp; Outdoor</button>
            <button class="zone-pill ${this._selectedFloorZone === "upper" ? "active" : ""}" data-zone="upper">Upper Level</button>
            <button class="zone-pill ${this._selectedFloorZone === "outdoor" ? "active" : ""}" data-zone="outdoor">Outdoor Only</button>
          </div>
          <div class="floorplan-actions">
            <button class="btn-toolbar" id="btn-open-walkthrough" title="Record video walkthrough to generate or update floor plan">
              📹 Walkthrough
            </button>
            <button 
              class="btn-toolbar ${!this._hasWalkthrough ? 'disabled' : ''}" 
              id="btn-copy-lovelace" 
              ${!this._hasWalkthrough ? "disabled" : ""}
              title="${this._hasWalkthrough ? 'Copy Lovelace Dashboard YAML for picture-elements card' : 'Complete a video walkthrough first to unlock Lovelace YAML export'}"
            >
              📋 Lovelace YAML
            </button>
          </div>
        </div>

        ${
          !this._hasWalkthrough && this._floorplanSvg
            ? `
          <div class="walkthrough-pending-banner">
            <div class="walkthrough-pending-text">
              <span style="font-size: 1rem;">📹</span>
              <span><strong>Walkthrough Pending:</strong> Current layout is an initial area estimate. Record or upload a video walkthrough calling out rooms to calibrate dimensions and unlock Lovelace YAML.</span>
            </div>
            <button class="btn-banner-walkthrough" id="btn-banner-walkthrough">Start Walkthrough</button>
          </div>
        `
            : ""
        }

        ${
          this._loadingFloorplan
            ? `<div class="empty-state"><div class="spinner" style="margin: 0 auto 8px auto; width: 24px; height: 24px;"></div>Rendering vector floor plan...</div>`
            : this._floorplanSvg
            ? `
            <div class="floorplan-svg-viewport" id="floorplan-viewport">
              ${this._floorplanSvg}
            </div>
            ${
              this._selectedRoomInfo
                ? `
              <div class="room-info-card">
                <div>
                  <div style="font-weight: 700; color: var(--otis-primary); font-size: 0.85rem;">${this._selectedRoomInfo.name}</div>
                  <div style="font-size: 0.72rem; color: var(--otis-text-muted);">
                    Zone: ${String(this._selectedRoomInfo.zone).toUpperCase()} • Entities: ${this._selectedRoomInfo.entities.length}
                  </div>
                </div>
                <button class="btn-toolbar" id="btn-close-room-info" style="padding: 2px 8px;">✕</button>
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
                <button class="btn-modal-primary" id="btn-start-walkthrough">
                  📹 Record / Upload Walkthrough
                </button>
                <button class="btn-modal-secondary" id="btn-quick-generate">
                  ⚡ Instant Generate from Registered Areas
                </button>
              </div>
            </div>
          `
        }
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
            <button class="modal-close-btn" id="modal-close-btn">✕</button>
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
              <button class="btn-modal-primary" id="btn-submit-walkthrough" disabled>
                🚀 Parse Video & Generate Floor Plan
              </button>
              <button class="btn-modal-secondary" id="btn-instant-generate-modal">
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
            <button class="modal-close-btn" id="theme-modal-close-btn">✕</button>
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
              <button
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
                      <button class="btn-modal-primary btn-apply-theme" data-theme-key="${th.theme_key}" style="flex: 1; padding: 4px 8px; font-size: 0.75rem;">
                        ⚡ Apply Live
                      </button>
                      <button class="btn-toolbar btn-delete-theme" data-theme-key="${th.theme_key}" style="padding: 4px 8px; color: #f43f5e;" title="Delete Theme">
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
                  <button class="btn-modal-secondary btn-generate-preset" data-preset-key="${p.key}" style="padding: 4px 8px; font-size: 0.75rem; margin-top: 4px;">
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
        this._showToast(`✨ Generated and applied "${data.title}"!`);
        await this._fetchData();
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

  async _applyThemeDirect(themeKey) {
    if (!this._hass || !themeKey) return;
    try {
      await this._hass.callService("frontend", "set_theme", { name: themeKey });
      await this._hass.callService("otis_ai", "apply_theme", { name: themeKey });
      this._showToast(`Switched active theme to ${themeKey}`);
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

    // Tabs
    const tabSug = root.querySelector("#tab-suggestions");
    if (tabSug) {
      tabSug.onclick = () => {
        if (this._isListening) this._stopVoiceRecording();
        this._activeTab = "suggestions";
        this._render();
      };
    }

    const tabChat = root.querySelector("#tab-chat");
    if (tabChat) {
      tabChat.onclick = () => {
        this._activeTab = "chat";
        this._render();
        this._scrollChatToBottom();
      };
    }

    const tabCap = root.querySelector("#tab-capabilities");
    if (tabCap) {
      tabCap.onclick = () => {
        this._activeTab = "capabilities";
        this._render();
      };
    }

    const tabFloor = root.querySelector("#tab-floorplan");
    if (tabFloor) {
      tabFloor.onclick = () => {
        if (this._isListening) this._stopVoiceRecording();
        this._activeTab = "floorplan";
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

    // Chat chips
    root.querySelectorAll("[data-chip]").forEach((chip) => {
      chip.onclick = (e) => {
        const prompt = e.currentTarget.getAttribute("data-chip");
        this._sendChatMessage(prompt);
      };
    });

    // Voice mic button
    const chatMic = root.querySelector("#chat-mic");
    if (chatMic) {
      chatMic.onclick = () => this._toggleVoiceRecording();
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
          const text = chatInput.value;
          chatInput.value = "";
          this._draftChatText = "";
          this._previewDismissed = false;
          adjustHeight();
          if (previewContainer) previewContainer.style.display = "none";
          this._sendChatMessage(text);
        }
      };
    }

    if (chatSend && chatInput) {
      chatSend.onclick = () => {
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
        root.querySelectorAll(".zone-pill").forEach((p) => p.classList.toggle("active", p === e.currentTarget));
        applyZoneFilterToSvg(zone);
      };
    });

    // Floorplan: Interactive SVG entity badges and room inspection
    const svgViewport = root.querySelector("#floorplan-viewport");
    if (svgViewport) {
      svgViewport.querySelectorAll("[data-entity-id]").forEach((badge) => {
        badge.style.cursor = "pointer";
        badge.onclick = (e) => {
          e.stopPropagation();
          const entityId = badge.getAttribute("data-entity-id");
          if (entityId && this._hass) {
            this._hass.callService("homeassistant", "toggle", { entity_id: entityId });
            this._showToast(`Toggled ${entityId}`);
          }
        };
      });

      svgViewport.querySelectorAll(".room-group").forEach((grp) => {
        grp.style.cursor = "pointer";
        grp.onclick = () => {
          const areaId = grp.getAttribute("data-area-id");
          const area = this._capabilityMap?.areas?.[areaId];
          if (area) {
            this._selectedRoomInfo = {
              areaId,
              name: area.name || areaId,
              zone: grp.getAttribute("data-zone") || "indoor",
              entities: area.entities || [],
            };
            this._render();
          }
        };
      });
    }

    const btnCloseRoomInfo = root.querySelector("#btn-close-room-info");
    if (btnCloseRoomInfo) {
      btnCloseRoomInfo.onclick = () => {
        this._selectedRoomInfo = null;
        this._render();
      };
    }

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
