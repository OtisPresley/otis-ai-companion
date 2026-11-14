import { CARD_STYLES } from "./card-styles.js?v=0.4.0";
import { floorplanMixin } from "./floorplan-3d.js?v=0.4.0";
import { modalsMixin } from "./card-modals.js?v=0.4.0";
import { tabsMixin } from "./card-tabs.js?v=0.4.0";

/**
 * Otis AI Companion - Lovelace Dashboard Card
 * Version: 0.2.4
 * 
 * An interactive, proactive smart home co-pilot card featuring:
 * - Frosted glassmorphism with Sky Cyan & Lavender Purple neon accents
 * - Live AI multi-agent status and health monitoring
 * - Proactive suggestions feed with category filter pills & 1-click coordinator execution
 * - Embedded Assist conversational co-pilot with quick prompt chips
 * - Multimodal Video-to-Floorplan SVG Parser & Interactive Viewer
 * - Phase 4 Visual Floor Plan Boundary & Marker Adjuster on Lovelace Canvas
 * - Smart Home Maturity Score & Media/Security Architecture Inspector
 * - Phase 10 Autonomous Home Commissioning & Multi-Node Federation Hub
 */

const CARD_VERSION = "0.4.0";
console.info(
  `%c OTIS AI COMPANION CARD %c v${CARD_VERSION} `,
  "background: #0ea5e9; color: #fff; font-weight: bold; border-radius: 4px 0 0 4px; padding: 2px 6px;",
  "background: #1e293b; color: #38bdf8; font-weight: bold; border-radius: 0 4px 4px 0; padding: 2px 6px;"
);

const OTIS_ACTIVE_CHAT = {
  isSending: false,
  requestId: 0,
  cancelled: false,
  abortReject: null,
  reasoningStartTime: null,
  reasoningSteps: [],
  activeReasoningStep: 0,
  conversationId: null,
  instances: new Set(),
};

const OTIS_ACTIVE_RULES_STATE = {
  isOpen: false,
  activeTab: "dashboard",
  draft: null,
  wizardState: null,
  wizardStep: 1,
};

const OTIS_SHARED_CACHE = {
  capabilityMap: null,
  capabilityMapHasSuggestions: false,
  mediaStudio: null,
  inFlightCapMap: null,
  inFlightCapMapLight: null,
  inFlightMediaStudio: null,
};

class OtisCompanionCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._isLoading = true;
    this._capabilityMap = null;
    this._suggestions = [];
    this._dismissedIds = this._loadDismissedIds();
    this._hiddenIds = this._loadHiddenIds();
    this._localShowIgnored = false;
    this._loadingSuggestions = false;
    this._applyingIds = new Set();
    this._chatMessages = this._loadChatMessages();
    this._isSendingChat = Boolean(OTIS_ACTIVE_CHAT.isSending);
    this._reasoningSteps = OTIS_ACTIVE_CHAT.isSending ? JSON.parse(JSON.stringify(OTIS_ACTIVE_CHAT.reasoningSteps || [])) : [];
    this._reasoningStartTime = OTIS_ACTIVE_CHAT.isSending ? OTIS_ACTIVE_CHAT.reasoningStartTime : null;
    this._reasoningTimer = null;
    this._activeReasoningStep = OTIS_ACTIVE_CHAT.isSending ? OTIS_ACTIVE_CHAT.activeReasoningStep : 0;
    this._expandedReasoningIds = new Set();
    this._unsubReasoningEvents = null;
    this._pendingAttachments = [];
    this._isListening = false;
    this._recognition = null;
    this._activeTab = this._loadActiveTab(); // 'suggestions' | 'chat' | 'capabilities' | 'floorplan' | 'vision'
    this._selectedCategory = "all"; // 'all' | 'lighting' | 'media' | 'security' | 'cleanup' | 'system'
    try {
      this._conversationId = sessionStorage.getItem("otis_conversation_id") || null;
    } catch (_) {
      this._conversationId = null;
    }
    this._conversationAgentId = null;
    this._cachedAgentId = null;
    this._draftChatText = "";
    this._previewDismissed = false;
    this._chatInitialScrolled = false;

    // Phase 8: Multi-Modal Vision & Presence
    this._cameraAudits = {};
    this._analyzingCamera = null;

    // Phase 6: Floorplan & Walkthrough state
    this._floorplanModalOpen = false;
    this._themeModalOpen = false;
    this._failoverModalOpen = false;
    this._rulesModalOpen = Boolean(OTIS_ACTIVE_RULES_STATE.isOpen);
    this._rulesActiveTab = OTIS_ACTIVE_RULES_STATE.activeTab || "dashboard";
    this._rulesDraft = OTIS_ACTIVE_RULES_STATE.draft ? { ...OTIS_ACTIVE_RULES_STATE.draft } : null;
    this._wizardStep = OTIS_ACTIVE_RULES_STATE.wizardStep || 1;
    try {
      const savedLock = localStorage.getItem("otis_floorplan_orbit_locked");
      this._floorplanOrbitLocked = savedLock !== null ? savedLock !== "false" : true;
    } catch (_) {
      this._floorplanOrbitLocked = true;
    }
    this._wizardState = {
      residents: "",
      workHours: "",
      sleepHabits: "",
      guestLockCode: "",
      guestDelayedOff: "00:00:00",
      guestClimateComfort: true,
      holidaySwitches: true,
      requireDeadboltConfirm: true,
      requireAlarmConfirm: true,
      garageAlertMinutes: 15,
      perimeterCameraAlerts: true,
      matrixRouting: true,
      voiceDucking: true,
      quietHoursStart: "22:00",
      quietHoursEnd: "07:00",
      quietVolume: 25,
    };
    this._savingRules = false;
    this._onboardingDismissed = false;
    this._userRules = null;
    this._isListeningTheme = false;
    this._themeRecognition = null;
    this._draftThemePrompt = "";
    this._viewportResizeObserver = null;
    this._themeApplyScope = "current";
    this._selectedThemeUserId = null;
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
    try {
      this._floorplanViewMode = localStorage.getItem("otis_floorplan_view_mode") || "2d";
    } catch (_) {
      this._floorplanViewMode = "2d";
    }

    // Phase 3: Interactive Floorplan 3D Orbit & Pitch Controls
    try {
      const savedAz = parseFloat(localStorage.getItem("otis_floorplan_orbit_azimuth"));
      this._floorplanAzimuth = !isNaN(savedAz) ? Math.max(0, Math.min(360, savedAz)) : 45;
    } catch (_) {
      this._floorplanAzimuth = 45;
    }
    try {
      const savedPitch = parseFloat(localStorage.getItem("otis_floorplan_pitch_incline"));
      this._floorplanPitch = !isNaN(savedPitch) ? Math.max(30, Math.min(75, savedPitch)) : 58;
    } catch (_) {
      this._floorplanPitch = 58;
    }
    try {
      const savedScale = parseFloat(localStorage.getItem("otis_floorplan_scale"));
      this._floorplanScale = !isNaN(savedScale) ? Math.max(0.6, Math.min(1.8, savedScale)) : 1.0;
    } catch (_) {
      this._floorplanScale = 1.0;
    }
    try {
      this._floorplanWallsEnabled = localStorage.getItem("otis_floorplan_walls_enabled") !== "false";
    } catch (_) {
      this._floorplanWallsEnabled = true;
    }
    try {
      const savedWallH = parseFloat(localStorage.getItem("otis_floorplan_wall_height"));
      this._floorplanWallHeight = !isNaN(savedWallH) ? Math.max(10, Math.min(50, savedWallH)) : 28;
    } catch (_) {
      this._floorplanWallHeight = 28;
    }
    this._floorplanHudCollapsed = false;
    this._previousViewMode = null;
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
    this._dirtyCustomFeatures = {};
    this._selectedEditorRoomId = null;
    this._resizingHandle = null;
    this._hasUnsavedLayout = false;
    this._savingLayout = false;
    this._addMarkerModalOpen = false;
    this._addMarkerFilter = "";
    this._editMarkerModalOpen = false;
    this._selectedEditorEntityId = null;
    this._selectedEditorEntityCoords = { x: 0, y: 0 };
    this._guideModalOpen = false;
    this._currentGuide = null;
    this._lovelaceEditMode = false;

    // Phase 4 (v0.2.3): Media Studio & Source-to-Zone Router + Per-User Favorites
    this._mediaStudioData = null;
    this._selectedMediaZoneId = null;
    this._selectedMediaInput = null;
    this._mediaOptimisticVolumes = {};
    this._mediaOptimisticMutes = {};
    this._mediaOptimisticSources = {};
    this._showAddFavoriteForm = false;
    this._showMediaMappingsEditor = false;
    this._favFormName = "";
    this._favFormInput = "";
    this._favFormCommand = "";
    this._favFormType = "playlist";
    this._favFormShared = false;
    this._mediaBrowseOpen = false;
    this._mediaBrowseType = "playlist";
    this._mediaBrowsePlayerId = "";
    this._mediaBrowseItems = [];
    this._mediaBrowseLoading = false;
    this._mediaBrowseError = null;

    // Phase 5: GitHub Device Flow & Issue Reporter
    this._githubModalOpen = false;
    this._reviewSuggestion = null;
    this._snapshotLightbox = null;
    this._githubModalStep = "review"; // 'review' | 'device_code' | 'submitting' | 'success' | 'error'
    this._githubModalData = null; // { repo, title, body, error_id, domain }
    this._githubDeviceCode = null; // { device_code, user_code, verification_uri, expires_in }
    this._githubCreatedIssue = null; // { number, html_url, title, repo }
    this._githubErrorMsg = null;
    this._githubPollTimer = null;
  }

  set editMode(editMode) {
    this._lovelaceEditMode = Boolean(editMode);
    const isAdmin = Boolean(this._hass?.user?.is_admin || this._hass?.user?.is_owner);
    if (this._lovelaceEditMode && isAdmin) {
      this._editorActive = true;
    } else if (!isAdmin) {
      this._editorActive = false;
    }
    this._render();
  }

  get editMode() {
    return this._lovelaceEditMode;
  }

  _loadActiveTab() {
    try {
      const saved = sessionStorage.getItem("otis_active_tab");
      if (saved && ["suggestions", "chat", "capabilities", "floorplan", "vision", "media"].includes(saved)) {
        return saved;
      }
    } catch (_) { }
    return "suggestions";
  }

  _saveActiveTab(tab) {
    if (["suggestions", "chat", "capabilities", "floorplan", "vision", "media"].includes(tab)) {
      this._activeTab = tab;
      try {
        sessionStorage.setItem("otis_active_tab", tab);
      } catch (_) { }
    }
  }

  _loadChatMessages() {
    try {
      const saved = sessionStorage.getItem("otis_chat_messages");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch (_) { }
    return [];
  }

  _saveChatMessages() {
    try {
      sessionStorage.setItem("otis_chat_messages", JSON.stringify(this._chatMessages.slice(-50)));
      if (this._conversationId) {
        sessionStorage.setItem("otis_conversation_id", this._conversationId);
      } else {
        sessionStorage.removeItem("otis_conversation_id");
      }
    } catch (_) { }
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
      OTIS_ACTIVE_CHAT.instances.add(this);
      this._syncActiveChatState();
      this._fetchData();
      this._subscribeReasoningEvents();
      this._subscribeRuleEvents();
    } else if (hass && this.shadowRoot) {
      if (this._rulesModalOpen || OTIS_ACTIVE_RULES_STATE.isOpen) {
        // Skip background re-renders while the user is actively working in the Rules dialog
        return;
      }
      this._updateFloorplanPinStates();
      if (this._config?.mode === "media_studio" || this._activeTab === "media") {
        const activeEl = this.shadowRoot.activeElement;
        const isEditingInput = activeEl && ["INPUT", "SELECT", "TEXTAREA"].includes(activeEl.tagName);
        if (!isEditingInput && oldHass?.states && hass?.states) {
          let mediaChanged = false;
          for (const k of Object.keys(hass.states)) {
            if (k.startsWith("media_player.") && oldHass.states[k] !== hass.states[k]) {
              mediaChanged = true;
              break;
            }
          }
          if (mediaChanged) {
            this._render();
          }
        }
      } else if (this._config?.mode === "vision" || this._activeTab === "vision") {
        const activeEl = this.shadowRoot.activeElement;
        const isEditingInput = activeEl && ["INPUT", "SELECT", "TEXTAREA"].includes(activeEl.tagName);
        if (!isEditingInput && oldHass?.states && hass?.states) {
          const fusedId = this._resolveOtisEntityId("sensor.otis_fused_presence");
          const sentinelId = this._resolveOtisEntityId("sensor.otis_perimeter_sentinel");
          if (
            oldHass.states[fusedId] !== hass.states[fusedId] ||
            oldHass.states[sentinelId] !== hass.states[sentinelId]
          ) {
            this._render();
          }
        }
      }
    }
  }

  connectedCallback() {
    OTIS_ACTIVE_CHAT.instances.add(this);
    this._chatMessages = this._loadChatMessages();
    this._syncActiveChatState();
    if (this._hass) {
      this._subscribeReasoningEvents();
      this._subscribeRuleEvents();
    }
    this._render();
    if (this._activeTab === "floorplan") {
      this._checkAndResumeRegenProgress();
    }
  }

  _syncActiveChatState() {
    if (OTIS_ACTIVE_CHAT.isSending) {
      this._isSendingChat = true;
      this._reasoningStartTime = OTIS_ACTIVE_CHAT.reasoningStartTime || Date.now();
      this._reasoningSteps = OTIS_ACTIVE_CHAT.reasoningSteps || [];
      this._activeReasoningStep = OTIS_ACTIVE_CHAT.activeReasoningStep || 0;
      if (OTIS_ACTIVE_CHAT.conversationId) {
        this._conversationId = OTIS_ACTIVE_CHAT.conversationId;
      }
      this._startReasoningTimer();
    } else if (this._isSendingChat) {
      this._isSendingChat = false;
      if (this._reasoningTimer) {
        clearInterval(this._reasoningTimer);
        this._reasoningTimer = null;
      }
    }
  }

  _startReasoningTimer() {
    if (this._reasoningTimer) clearInterval(this._reasoningTimer);
    this._reasoningTimer = setInterval(() => {
      if (!OTIS_ACTIVE_CHAT.isSending || !this._isSendingChat || !this._reasoningStartTime) {
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
      OTIS_ACTIVE_CHAT.reasoningSteps = this._reasoningSteps;
      OTIS_ACTIVE_CHAT.activeReasoningStep = this._activeReasoningStep;
      this._updateThinkingDisplay(elapsed);
    }, 200);
  }

  _shouldShowOnboardingBanner() {
    if (this._isLoading || this._loadingSuggestions || !this._capabilityMap || !this._userRules) {
      return false;
    }
    if (this._onboardingDismissed || this._userRules.onboarding_completed) {
      return false;
    }
    const hasCustomInstructions = Boolean(this._userRules.custom_instructions && String(this._userRules.custom_instructions).trim());
    const hasWizardState = Boolean(this._userRules.wizard_state && Object.keys(this._userRules.wizard_state).length > 0);
    const hasPersonProfiles = Boolean(this._userRules.person_profiles && Object.keys(this._userRules.person_profiles).length > 0);
    if (hasCustomInstructions || hasWizardState || hasPersonProfiles) {
      return false;
    }
    return true;
  }

  _getPinActiveColor(entityId) {
    const dom = String(entityId || "").split(".")[0];
    const domainColors = {
      light: "#f59e0b",
      switch: "#a855f7",
      media_player: "#ec4899",
      fan: "#06b6d4",
      climate: "#f97316",
      cover: "#eab308",
      lock: "#10b981",
      vacuum: "#8b5cf6",
      binary_sensor: "#10b981",
    };
    return domainColors[dom] || "#38bdf8";
  }

  _isPinEntityActive(stateObj) {
    const state = String(stateObj?.state || "unknown").toLowerCase();
    return ["on", "playing", "open", "unlocked", "active", "cleaning", "heating", "cooling", "home"].includes(state);
  }

  _updateFloorplanPinStates() {
    if (!this.shadowRoot || !this._hass?.states) return;
    const pinsOverlay = this.shadowRoot.querySelector("#floorplan-pins-overlay");
    if (!pinsOverlay) return;

    pinsOverlay.querySelectorAll(".floorplan-device-pin").forEach((pin) => {
      const eid = pin.getAttribute("data-entity-id");
      if (!eid) return;
      const stateObj = this._hass.states[eid];
      const name = stateObj?.attributes?.friendly_name || eid;
      const state = stateObj?.state || "unknown";
      const isActive = this._isPinEntityActive(stateObj);
      const activeColor = this._getPinActiveColor(eid);
      const pinColor = isActive ? activeColor : "#94a3b8";

      pin.classList.toggle("is-active", isActive);
      pin.setAttribute("title", `${name}: ${state}`);
      pin.style.color = pinColor;
      pin.style.setProperty("--paper-item-icon-color", pinColor);
      pin.style.setProperty("--paper-item-icon-active-color", activeColor);
      pin.style.setProperty("--state-icon-color", pinColor);
      pin.style.setProperty("--state-icon-active-color", activeColor);

      const iconEl = pin.querySelector("ha-state-icon");
      if (iconEl) {
        iconEl.hass = this._hass;
        if (stateObj) {
          iconEl.stateObj = stateObj;
        }
        iconEl.stateColor = true;
        iconEl.style.color = pinColor;
        iconEl.style.setProperty("--paper-item-icon-color", pinColor);
        iconEl.style.setProperty("--paper-item-icon-active-color", activeColor);
        iconEl.style.setProperty("--state-icon-color", pinColor);
        iconEl.style.setProperty("--state-icon-active-color", activeColor);
      }
    });
  }

  disconnectedCallback() {
    OTIS_ACTIVE_CHAT.instances.delete(this);
    if (this._unsubReasoningEvents) {
      try {
        this._unsubReasoningEvents();
      } catch (_) { }
      this._unsubReasoningEvents = null;
    }
    if (this._unsubRuleEvents) {
      try {
        this._unsubRuleEvents();
      } catch (_) { }
      this._unsubRuleEvents = null;
    }
    if (this._reasoningTimer) {
      clearInterval(this._reasoningTimer);
      this._reasoningTimer = null;
    }
    if (this._regenPollTimer) {
      clearInterval(this._regenPollTimer);
      this._regenPollTimer = null;
    }
    if (this._viewportResizeObserver) {
      try {
        this._viewportResizeObserver.disconnect();
      } catch (_) { }
      this._viewportResizeObserver = null;
    }
  }

  async _subscribeRuleEvents() {
    if (this._unsubRuleEvents) return;
    try {
      if (this._hass && this._hass.connection && typeof this._hass.connection.subscribeEvents === "function") {
        this._unsubRuleEvents = await this._hass.connection.subscribeEvents((ev) => {
          if (ev?.data?.rules) {
            this._userRules = ev.data.rules;
            this._rulesDraft = { ...this._userRules };
            this._render();
          }
        }, "otis_ai_rules_updated");
      }
    } catch (e) {
      console.debug("Could not subscribe to otis_ai_rules_updated events:", e);
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
    OTIS_ACTIVE_CHAT.reasoningSteps = this._reasoningSteps;
    OTIS_ACTIVE_CHAT.activeReasoningStep = this._activeReasoningStep;
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
              ${isDone
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
    } else if (config.mode === "floorplan_studio" || config.mode === "floorplan_control") {
      this._activeTab = "floorplan";
      this._saveActiveTab("floorplan");
    } else if (config.mode === "media_studio") {
      this._activeTab = "media";
      this._saveActiveTab("media");
    } else {
      this._activeTab = this._loadActiveTab();
    }
    if (config.view_mode === "3d" || config.view_mode === "2d") {
      this._floorplanViewMode = config.view_mode;
    }
    if (config.floorplan_azimuth !== undefined) {
      this._floorplanAzimuth = parseFloat(config.floorplan_azimuth) || 0;
    }
    if (config.floorplan_pitch !== undefined) {
      this._floorplanPitch = parseFloat(config.floorplan_pitch) || 30;
    }
    if (config.floorplan_wall_height !== undefined) {
      this._floorplanWallHeight = parseFloat(config.floorplan_wall_height) || 36;
    }
    if (config.floorplan_walls_enabled !== undefined) {
      this._floorplanWallsEnabled = config.floorplan_walls_enabled !== false;
    }
    if (config.floorplan_zone) {
      this._selectedFloorZone = config.floorplan_zone;
    }
    if (config.floorplan_scale !== undefined) {
      const sc = parseFloat(config.floorplan_scale);
      if (!isNaN(sc)) this._floorplanScale = Math.max(0.6, Math.min(1.8, sc));
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

  _readSessionCache(storageKey) {
    try {
      const raw = sessionStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  _writeSessionCache(storageKey, data) {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(data));
    } catch (_) {
      // Fallback for large floorplan SVG payloads exceeding sessionStorage quota
      if (data && data.floorplan && data.floorplan.svg) {
        try {
          const lean = { ...data, floorplan: { ...data.floorplan, svg: undefined } };
          sessionStorage.setItem(storageKey, JSON.stringify(lean));
        } catch (__) { }
      }
    }
  }

  _applyCapabilityMap(capMap) {
    if (!capMap || typeof capMap !== "object") return;
    this._capabilityMap = {
      ...(this._capabilityMap || {}),
      ...capMap,
      local_llm:
        capMap.local_llm && Object.keys(capMap.local_llm).length > 0
          ? capMap.local_llm
          : this._capabilityMap?.local_llm || capMap.local_llm,
    };
    if (capMap.conversation_agent_id) {
      this._conversationAgentId = capMap.conversation_agent_id;
    }
    this._userRules = capMap.user_rules || {};
    if (this._userRules.wizard_state && typeof this._userRules.wizard_state === "object") {
      this._wizardState = { ...this._wizardState, ...this._userRules.wizard_state };
    }
    if (!this._rulesModalOpen) {
      this._rulesDraft = { ...this._userRules };
    }
    const isFloorplanControlView = this._config.mode === "floorplan_control";
    if (this._userRules.floorplan_view_mode && (isFloorplanControlView || !localStorage.getItem("otis_floorplan_view_mode"))) {
      this._floorplanViewMode = this._userRules.floorplan_view_mode;
    }
    if (this._userRules.floorplan_azimuth !== undefined && (isFloorplanControlView || !localStorage.getItem("otis_floorplan_orbit_azimuth"))) {
      this._floorplanAzimuth = parseFloat(this._userRules.floorplan_azimuth) || 0;
    }
    if (this._userRules.floorplan_pitch !== undefined && (isFloorplanControlView || !localStorage.getItem("otis_floorplan_pitch_incline"))) {
      this._floorplanPitch = parseFloat(this._userRules.floorplan_pitch) || 30;
    }
    if (this._userRules.floorplan_wall_height !== undefined && (isFloorplanControlView || !localStorage.getItem("otis_floorplan_wall_height"))) {
      this._floorplanWallHeight = parseFloat(this._userRules.floorplan_wall_height) || 36;
    }
    if (this._userRules.floorplan_walls_enabled !== undefined && (isFloorplanControlView || !localStorage.getItem("otis_floorplan_walls_enabled"))) {
      this._floorplanWallsEnabled = this._userRules.floorplan_walls_enabled !== false;
    }
    if (this._userRules.floorplan_zone && (isFloorplanControlView || !localStorage.getItem("otis_floorplan_selected_zone"))) {
      this._selectedFloorZone = this._userRules.floorplan_zone;
    }
    if (this._userRules.floorplan_scale !== undefined && (isFloorplanControlView || !localStorage.getItem("otis_floorplan_scale"))) {
      const sc = parseFloat(this._userRules.floorplan_scale);
      if (!isNaN(sc)) this._floorplanScale = Math.max(0.6, Math.min(1.8, sc));
    }
    if (Array.isArray(this._userRules.dismissed_recommendation_ids)) {
      for (const id of this._userRules.dismissed_recommendation_ids) {
        this._dismissedIds.add(id);
      }
      this._saveDismissedIds();
    }
    if (Array.isArray(this._userRules.hidden_recommendation_ids)) {
      for (const id of this._userRules.hidden_recommendation_ids) {
        this._hiddenIds.add(id);
      }
      this._saveHiddenIds();
    }
    if (Array.isArray(capMap.proactive_suggestions) && capMap.proactive_suggestions.length > 0) {
      this._suggestions = capMap.proactive_suggestions;
    } else if (!this._suggestions?.length && Array.isArray(capMap.proactive_suggestions)) {
      this._suggestions = capMap.proactive_suggestions;
    }
    this._hasWalkthrough = Boolean(capMap.floorplan?.walkthrough_completed);
    this._hasFloorplan = Boolean(capMap.floorplan?.exists);
    if (capMap.floorplan?.svg) {
      this._floorplanSvg = this._cleanAndSanitizeSvg(capMap.floorplan.svg);
      this._floorplanLoadFailed = false;
    }
  }

  _applyMediaStudioData(data) {
    if (!data || !data.success) return;
    this._mediaStudioData = data;
    const zones = data.zones || [];
    const unjoinInput = data.unjoin_input || "None";
    if (!this._selectedMediaZoneId || !zones.some((z) => z.entity_id === this._selectedMediaZoneId)) {
      if (data.default_zone && zones.some((z) => z.entity_id === data.default_zone)) {
        this._selectedMediaZoneId = data.default_zone;
      } else {
        const activeZone = zones.find(
          (z) =>
            (z.state === "playing" || z.state === "on") &&
            z.source &&
            z.source !== unjoinInput
        );
        this._selectedMediaZoneId = activeZone?.entity_id || zones[0]?.entity_id || null;
      }
    }
  }

  async _fetchData() {
    if (!this._hass) return;
    const isSubview = this._isSubviewMode();
    const includeSuggestions = !isSubview || this._config.show_suggestions === true;
    const needsMediaStudio = !isSubview || this._config.mode === "media_studio";
    const isInitialLoad = !this._capabilityMap;

    // Instant paint from shared module cache or sessionStorage before background refresh
    if (isInitialLoad) {
      const cachedCap = OTIS_SHARED_CACHE.capabilityMap || this._readSessionCache("otis_cache_cap_map");
      if (cachedCap && typeof cachedCap === "object") {
        OTIS_SHARED_CACHE.capabilityMap = cachedCap;
        this._applyCapabilityMap(cachedCap);
        if (needsMediaStudio) {
          const cachedMedia = OTIS_SHARED_CACHE.mediaStudio || this._readSessionCache("otis_cache_media_studio");
          if (cachedMedia) {
            OTIS_SHARED_CACHE.mediaStudio = cachedMedia;
            this._applyMediaStudioData(cachedMedia);
          }
        }
        this._isLoading = false;
        this._loadingSuggestions = false;
        this._render();
      } else {
        this._loadingSuggestions = includeSuggestions;
        this._render();
      }
    }

    try {
      const flightKey = includeSuggestions ? "inFlightCapMap" : "inFlightCapMapLight";
      if (!OTIS_SHARED_CACHE[flightKey]) {
        const svcData = includeSuggestions ? {} : { include_suggestions: false };
        OTIS_SHARED_CACHE[flightKey] = this._hass
          .callService("otis_ai", "get_capability_map", svcData, undefined, true, true)
          .finally(() => {
            OTIS_SHARED_CACHE[flightKey] = null;
          });
      }
      const res = await OTIS_SHARED_CACHE[flightKey];
      const capMap = res?.response || res || {};

      // Preserve existing cached suggestions if this was a lightweight studio refresh
      const mergedForCache = includeSuggestions
        ? capMap
        : {
          ...capMap,
          proactive_suggestions:
            OTIS_SHARED_CACHE.capabilityMap?.proactive_suggestions || capMap.proactive_suggestions || [],
        };
      OTIS_SHARED_CACHE.capabilityMap = mergedForCache;
      if (includeSuggestions) {
        OTIS_SHARED_CACHE.capabilityMapHasSuggestions = true;
      }
      this._writeSessionCache("otis_cache_cap_map", mergedForCache);
      this._applyCapabilityMap(capMap);

      if (capMap.floorplan?.exists && !capMap.floorplan?.svg && !this._floorplanSvg && !this._loadingFloorplan) {
        await this._loadFloorplanSvg(capMap.floorplan.url);
      }

      if (needsMediaStudio) {
        await this._fetchMediaStudioState();
      }
    } catch (err) {
      console.warn("Otis Companion Card: Could not fetch capability map directly, attempting get_suggestions:", err);
      if (includeSuggestions) {
        try {
          const sRes = await this._hass.callService("otis_ai", "get_suggestions", {}, undefined, true, true);
          this._suggestions = sRes?.response?.suggestions || [];
        } catch (e2) {
          console.error("Otis Companion Card: Failed to fetch suggestions:", e2);
        }
      }
      if (needsMediaStudio) {
        await this._fetchMediaStudioState();
      }
    } finally {
      this._isLoading = false;
      this._loadingSuggestions = false;
      if (!this._rulesModalOpen && !OTIS_ACTIVE_RULES_STATE.isOpen) {
        this._render();
      }
    }
  }

  async _fetchMediaStudioState() {
    if (!this._hass) return;
    try {
      if (!OTIS_SHARED_CACHE.inFlightMediaStudio) {
        OTIS_SHARED_CACHE.inFlightMediaStudio = (async () => {
          const resp =
            typeof this._hass.fetchWithAuth === "function"
              ? await this._hass.fetchWithAuth("/api/otis_ai/media_studio")
              : await fetch("/api/otis_ai/media_studio");
          if (resp && resp.ok) {
            return await resp.json();
          }
          return null;
        })().finally(() => {
          OTIS_SHARED_CACHE.inFlightMediaStudio = null;
        });
      }
      const data = await OTIS_SHARED_CACHE.inFlightMediaStudio;
      if (data && data.success) {
        OTIS_SHARED_CACHE.mediaStudio = data;
        this._writeSessionCache("otis_cache_media_studio", data);
        this._applyMediaStudioData(data);
      }
    } catch (err) {
      console.debug("Otis Media Studio state fetch warning:", err);
    }
  }

  _cleanAndSanitizeSvg(rawSvg) {
    if (!rawSvg || typeof rawSvg !== "string") return null;
    let clean = rawSvg.replace(
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
    clean = clean.replace(/<g\b[^>]*class="[^"]*entity-badge[^"]*"[^>]*>[\s\S]*?<\/g>\s*/gi, "");
    clean = clean.replace(/(<svg\b[^>]*)\bwidth="[0-9.]+"\s*/i, "$1 ");
    clean = clean.replace(/(<svg\b[^>]*)\bheight="[0-9.]+"\s*/i, "$1 ");
    return clean;
  }

  _positionRoomFeatureSvg(fGrp, featKey, fx, fy) {
    if (!fGrp) return;
    fGrp.setAttribute("data-x", fx);
    fGrp.setAttribute("data-y", fy);
    const fRect = fGrp.querySelector("rect");
    let fw = 170;
    let fh = 64;
    if (fRect) {
      fw = parseFloat(fRect.getAttribute("width") || (featKey === "stairs" ? 44 : featKey === "front_porch" ? 200 : 170));
      fh = parseFloat(fRect.getAttribute("height") || (featKey === "stairs" ? 28 : featKey === "front_porch" ? 20 : 64));
      fRect.setAttribute("x", fx);
      fRect.setAttribute("y", fy);
    }
    if (featKey === "stairs") {
      fGrp.querySelectorAll(".stairs-step").forEach((el, idx) => {
        if (el.tagName && el.tagName.toLowerCase() === "line") {
          const stepNum = idx > 0 ? idx : 1;
          const lx = fx + stepNum * 9;
          el.setAttribute("x1", lx);
          el.setAttribute("y1", fy);
          el.setAttribute("x2", lx);
          el.setAttribute("y2", fy + 28);
        }
      });
    } else {
      const fTxt = fGrp.querySelector("text");
      if (fTxt) {
        fTxt.setAttribute("x", fx + fw / 2);
        fTxt.setAttribute("y", fy + (featKey === "front_porch" ? 13 : fh / 2 + 4));
      }
    }
  }

  async _fetchRegenProgressStatus() {
    const stResp =
      this._hass && typeof this._hass.fetchWithAuth === "function"
        ? await this._hass.fetchWithAuth("/api/otis_ai/upload_walkthrough", { method: "GET", cache: "no-store" })
        : await fetch("/api/otis_ai/upload_walkthrough", { method: "GET", cache: "no-store" });
    if (!stResp || !stResp.ok) return null;
    return await stResp.json();
  }

  _applyRegenProgressToDom(st) {
    if (!st) return;
    if (typeof st.percent === "number") {
      this._regenProgressPercent = st.percent;
    }
    if (st.stage) {
      this._regenProgressText = st.stage;
    }
    if (Array.isArray(st.discovered_areas)) {
      this._regenDiscoveredAreas = st.discovered_areas;
    }
    const rRoot = this.shadowRoot;
    if (rRoot) {
      const barEl = rRoot.querySelector("#regen-progress-bar");
      const pctEl = rRoot.querySelector("#regen-progress-pct");
      const txtEl = rRoot.querySelector("#regen-progress-text");
      const chipsEl = rRoot.querySelector("#regen-discovered-chips");
      if (barEl) barEl.style.width = `${Number(this._regenProgressPercent || 0)}%`;
      if (pctEl) pctEl.textContent = `${Number(this._regenProgressPercent || 0)}%`;
      if (txtEl && st.stage) txtEl.textContent = st.stage;
      if (chipsEl && Array.isArray(st.discovered_areas)) {
        chipsEl.style.marginTop = st.discovered_areas.length ? "8px" : "0px";
        chipsEl.innerHTML = st.discovered_areas
          .map((n) => `<span style="font-size: 0.7rem; padding: 2px 8px; border-radius: 999px; background: rgba(56, 189, 248, 0.18); color: #7dd3fc;">✓ ${this._escapeHtml(n)}</span>`)
          .join("");
      }
    }
  }

  async _finishRegenProgress(errMsg) {
    if (this._regenPollTimer) {
      clearInterval(this._regenPollTimer);
      this._regenPollTimer = null;
    }
    if (errMsg) {
      this._regeneratingFloorplan = false;
      this._showToast(`Regenerate failed: ${errMsg}`, true);
      this._render();
      return;
    }
    this._dirtyBadges = {};
    this._hasUnsavedLayout = false;
    this._floorplanSvg = null;
    await this._fetchData(true);
    await this._loadFloorplanSvg("/api/otis_ai/media/otis_floorplan.svg");
    this._regeneratingFloorplan = false;
    this._regenProgressPercent = 100;
    this._showToast("Floor plan rebuilt from scratch!");
    this._render();
  }

  _startRegenPolling() {
    if (this._regenPollTimer) {
      clearInterval(this._regenPollTimer);
      this._regenPollTimer = null;
    }
    this._regenPollTimer = setInterval(async () => {
      try {
        const st = await this._fetchRegenProgressStatus();
        if (!st) return;
        this._applyRegenProgressToDom(st);
        if (st.error) {
          await this._finishRegenProgress(st.error);
        } else if (!st.active && (st.percent >= 100 || st.stage === "Complete" || st.stage === "Idle")) {
          await this._finishRegenProgress(null);
        }
      } catch (_pollErr) {
        // Ignore transient poll errors during background rebuild
      }
    }, 650);
  }

  async _checkAndResumeRegenProgress() {
    if (this._regenPollTimer) return;
    try {
      const st = await this._fetchRegenProgressStatus();
      if (!st || !st.active) return;
      this._regeneratingFloorplan = true;
      this._applyRegenProgressToDom(st);
      this._render();
      this._startRegenPolling();
    } catch (_err) {
      // Ignore if endpoint unavailable
    }
  }

  async _loadFloorplanSvg(url) {
    if (this._loadingFloorplan) return;
    this._loadingFloorplan = true;
    try {
      let targetUrl = url || "/api/otis_ai/media/otis_floorplan.svg";
      // Never append query parameters to a signed URL as it invalidates the cryptographic signature
      let fetchUrl = targetUrl;
      if (!targetUrl.includes("authSig=")) {
        fetchUrl = targetUrl + (targetUrl.includes("?") ? "&" : "?") + "t=" + Date.now();
      }

      let resp;
      if (this._hass && typeof this._hass.fetchWithAuth === "function") {
        resp = await this._hass.fetchWithAuth(fetchUrl, { cache: "no-store" });
      } else {
        resp = await fetch(fetchUrl, { cache: "no-store" });
      }

      if ((!resp || !resp.ok) && targetUrl.includes("authSig=")) {
        if (this._hass && typeof this._hass.fetchWithAuth === "function") {
          resp = await this._hass.fetchWithAuth(`/api/otis_ai/media/otis_floorplan.svg?t=${Date.now()}`, { cache: "no-store" });
        }
      }

      if (resp && resp.ok) {
        let rawSvg = await resp.text();
        this._floorplanSvg = this._cleanAndSanitizeSvg(rawSvg);
        this._floorplanLoadFailed = false;
      } else {
        this._floorplanLoadFailed = true;
        console.warn("Could not load floorplan SVG, status:", resp?.status);
      }
    } catch (err) {
      this._floorplanLoadFailed = true;
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
            `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:999px;background:rgba(14,165,233,0.16);border:1px solid rgba(56,189,248,0.4);color:#e0f2fe;font-size:0.72rem;font-weight:600;">✓ Discovered ${this._escapeHtml(name)}</span>`
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
        const stResp =
          this._hass && typeof this._hass.fetchWithAuth === "function"
            ? await this._hass.fetchWithAuth("/api/otis_ai/upload_walkthrough", { method: "GET" })
            : await fetch("/api/otis_ai/upload_walkthrough", { method: "GET" });
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

      const resp =
        this._hass && typeof this._hass.fetchWithAuth === "function"
          ? await this._hass.fetchWithAuth("/api/otis_ai/upload_walkthrough", {
            method: "POST",
            body: formData,
          })
          : await fetch("/api/otis_ai/upload_walkthrough", {
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
      const yaml = data.lovelace_yaml || "type: picture-elements\nimage: /api/otis_ai/media/otis_floorplan.svg\nelements: []\n";
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

    if (suggestion.action_type === "open_url" || suggestion.action_type === "read_article") {
      const url = suggestion.action_payload?.url;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      return;
    }

    if (suggestion.action_type === "upload_walkthrough") {
      this._activeTab = "floorplan";
      this._floorplanModalOpen = true;
      this._render();
      return;
    }

    if (suggestion.action_type === "configure_agent") {
      this._failoverModalOpen = true;
      this._render();
      return;
    }

    if (suggestion.action_type === "advisor_guide") {
      this._currentGuide = {
        title: suggestion.title,
        category: suggestion.category,
        description: suggestion.description,
        guide: suggestion.action_payload?.guide || suggestion.description,
        action_payload: suggestion.action_payload,
      };
      this._guideModalOpen = true;
      this._render();
      return;
    }

    if (suggestion.action_type === "install_ollama_addon") {
      const url = suggestion.action_payload?.url || "/hassio/addon/local_otis_ollama";
      window.open(url, "_blank", "noopener,noreferrer");
      this._showToast("Opening Local Otis Ollama in Home Assistant Add-on Store...");
      return;
    }

    this._applyingIds.add(sId);
    if (suggestion.action_type === "switch_local_llm_model") {
      const targetModel = suggestion.action_payload?.model || "recommended model";
      this._showToast(`⚡ Pulling & activating Local Edge AI model (${targetModel})... This may take up to a minute if downloading.`);
    }
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
      } else if (data.action === "open_url" && data.url) {
        window.open(data.url, "_blank", "noopener,noreferrer");
        this._showToast(data.message || `Opening ${data.url}...`);
        await this._hideSuggestion(sId, { silent: true });
        await this._fetchData();
      } else if (data.action === "open_failover_modal") {
        this._failoverModalOpen = true;
      } else if (data.action === "open_chat_prompt") {
        this._draftChatText = data.prompt || "";
        this._activeTab = "chat";
        this._render();
        setTimeout(() => {
          const input = this.shadowRoot.getElementById("chat-input");
          if (input) {
            input.focus();
            if (input.setSelectionRange) {
              input.setSelectionRange(input.value.length, input.value.length);
            }
          }
        }, 100);
      } else if (data.action === "create_ha_automation" && data.automation_config) {
        const autoId = String(data.id || Date.now());
        let apiCreated = false;
        try {
          await this._hass.callApi(
            "POST",
            `config/automation/config/${encodeURIComponent(autoId)}`,
            data.automation_config
          );
          apiCreated = true;
        } catch (apiErr) {
          console.warn("HA config/automation/config API failed, falling back to YAML clipboard:", apiErr);
        }
        if (apiCreated) {
          this._showToast(data.message || `Created automation "${data.automation_config.alias || autoId}" in Home Assistant!`);
        } else {
          if (data.yaml && navigator.clipboard) {
            try {
              await navigator.clipboard.writeText(data.yaml);
            } catch (_) { }
          }
          this._showToast("HA Automation API unavailable; copied automation YAML to clipboard.", true);
        }
        await this._hideSuggestion(sId, { silent: true });
        await this._fetchData();
      } else if (data.action === "show_yaml" || data.yaml) {
        if (data.yaml && navigator.clipboard) {
          try {
            await navigator.clipboard.writeText(data.yaml);
          } catch (_) { }
        }
        this._showToast(data.message || "YAML copied to clipboard!");
        await this._hideSuggestion(sId, { silent: true });
        await this._fetchData();
      } else if (data.success !== false) {
        this._showToast(data.message || `Applied "${suggestion.title}" successfully!`);
        await this._hideSuggestion(sId, { silent: true });
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
    } catch (_) { }
    return new Set();
  }

  _saveDismissedIds() {
    try {
      if (this._dismissedIds && this._dismissedIds.size > 0) {
        localStorage.setItem("otis_dismissed_suggestions", JSON.stringify([...this._dismissedIds]));
      } else {
        localStorage.removeItem("otis_dismissed_suggestions");
      }
    } catch (_) { }
  }

  _loadHiddenIds() {
    try {
      const stored = localStorage.getItem("otis_hidden_suggestions");
      if (stored) {
        return new Set(JSON.parse(stored));
      }
    } catch (_) { }
    return new Set();
  }

  _saveHiddenIds() {
    try {
      if (this._hiddenIds && this._hiddenIds.size > 0) {
        localStorage.setItem("otis_hidden_suggestions", JSON.stringify([...this._hiddenIds]));
      } else {
        localStorage.removeItem("otis_hidden_suggestions");
      }
    } catch (_) { }
  }

  async _hideSuggestion(sId, opts = {}) {
    if (!sId) return;
    this._hiddenIds.add(sId);
    this._saveHiddenIds();
    this._render();
    if (!opts.silent) {
      this._showToast(opts.toast || "Card dismissed.");
    }
    try {
      if (this._hass) {
        await this._hass.callService("otis_ai", "hide_recommendation", { recommendation_id: sId });
      }
    } catch (err) {
      console.warn("Could not persist hidden recommendation to backend:", err);
    }
  }

  async _dismissCardFromFeed(sId) {
    return this._hideSuggestion(sId, { toast: "Card dismissed." });
  }

  async _dismissSuggestion(sId, opts = {}) {
    if (!sId) return;
    this._dismissedIds.add(sId);
    this._saveDismissedIds();
    this._render();
    if (!opts.silent) {
      this._showToast(opts.toast || "Recommendation ignored.");
    }
    try {
      if (this._hass) {
        await this._hass.callService("otis_ai", "dismiss_recommendation", { recommendation_id: sId });
      }
    } catch (err) {
      console.warn("Could not persist dismissed recommendation to backend:", err);
    }
  }

  async _restoreSuggestion(sId) {
    if (!sId) return;
    this._dismissedIds.delete(sId);
    this._saveDismissedIds();
    this._render();
    this._showToast("Recommendation restored.");
    try {
      if (this._hass) {
        await this._hass.callService("otis_ai", "restore_recommendation", { recommendation_id: sId });
      }
    } catch (err) {
      console.warn("Could not restore recommendation on backend:", err);
    }
  }

  async _resetDismissedSuggestions() {
    this._dismissedIds.clear();
    this._saveDismissedIds();
    this._render();
    this._showToast("All ignored recommendations restored.");
    try {
      if (this._hass) {
        await this._hass.callService("otis_ai", "reset_dismissed_recommendations", {});
      }
    } catch (err) {
      console.warn("Could not reset dismissed recommendations on backend:", err);
    }
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

  _handleFilesSelected(files) {
    if (!files || files.length === 0) return;
    if (!this._pendingAttachments) this._pendingAttachments = [];
    const maxFiles = 5;
    const maxFileSize = 10 * 1024 * 1024; // 10MB limit

    Array.from(files).slice(0, maxFiles).forEach((file) => {
      if (file.size > maxFileSize) {
        this._showToast(`File '${file.name}' exceeds 10MB limit.`, true);
        return;
      }
      const isImg = file.type.startsWith("image/");
      const reader = new FileReader();
      if (isImg) {
        reader.onload = (e) => {
          const isDuplicate = this._pendingAttachments.some(
            (att) => att.isImage && att.name === file.name && att.size === file.size && att.data === e.target.result
          );
          if (!isDuplicate) {
            this._pendingAttachments.push({
              name: file.name,
              type: file.type,
              size: file.size,
              isImage: true,
              data: e.target.result,
            });
            this._render();
          }
        };
        reader.readAsDataURL(file);
      } else {
        reader.onload = (e) => {
          const isDuplicate = this._pendingAttachments.some(
            (att) => !att.isImage && att.name === file.name && att.size === file.size && att.content === e.target.result
          );
          if (!isDuplicate) {
            this._pendingAttachments.push({
              name: file.name,
              type: file.type,
              size: file.size,
              isImage: false,
              content: e.target.result,
            });
            this._render();
          }
        };
        reader.readAsText(file);
      }
    });
  }

  _handleClipboardPaste(e) {
    if (!e || !e.clipboardData) return;
    const items = e.clipboardData.items;
    if (!items || items.length === 0) return;

    const imageFiles = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].type && items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile();
        if (file) {
          imageFiles.push(file);
        }
      }
    }

    if (imageFiles.length > 0) {
      e.preventDefault();
      if (e.stopPropagation) e.stopPropagation();
      this._handleFilesSelected(imageFiles);
    }
  }

  _stopChatGeneration() {
    if (!this._isSendingChat && !OTIS_ACTIVE_CHAT.isSending) return;
    OTIS_ACTIVE_CHAT.cancelled = true;
    OTIS_ACTIVE_CHAT.isSending = false;
    if (typeof OTIS_ACTIVE_CHAT.abortReject === "function") {
      try {
        OTIS_ACTIVE_CHAT.abortReject(new Error("__OTIS_STOPPED__"));
      } catch (_) { }
      OTIS_ACTIVE_CHAT.abortReject = null;
    }
    if (this._hass) {
      try {
        this._hass.callService(
          "otis_ai",
          "chat",
          {
            cancel: true,
            conversation_id: this._conversationId || OTIS_ACTIVE_CHAT.conversationId || undefined,
          },
          undefined,
          false,
          true
        );
      } catch (_) { }
    }
  }

  async _sendChatMessage(text, explicitAttachments = null) {
    const userText = (text || "").trim();
    if (explicitAttachments && Array.isArray(explicitAttachments)) {
      this._pendingAttachments = [...explicitAttachments];
    }
    const hasAttachments = this._pendingAttachments && this._pendingAttachments.length > 0;
    if ((!userText && !hasAttachments) || !this._hass || this._isSendingChat || OTIS_ACTIVE_CHAT.isSending) return;

    const attachmentsToSend = this._pendingAttachments ? [...this._pendingAttachments] : [];
    this._pendingAttachments = [];

    this._saveActiveTab("chat");
    const userMsgId = "user_" + Date.now();
    const displayText = userText || (attachmentsToSend.length > 0 ? `[Attached ${attachmentsToSend.length} file(s)]` : "");
    this._chatMessages.push({
      id: userMsgId,
      sender: "user",
      text: displayText,
      attachments: attachmentsToSend,
      timestamp: new Date().toISOString()
    });
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

    const currentReqId = ++OTIS_ACTIVE_CHAT.requestId;
    OTIS_ACTIVE_CHAT.isSending = true;
    OTIS_ACTIVE_CHAT.cancelled = false;
    OTIS_ACTIVE_CHAT.reasoningStartTime = this._reasoningStartTime;
    OTIS_ACTIVE_CHAT.reasoningSteps = this._reasoningSteps;
    OTIS_ACTIVE_CHAT.activeReasoningStep = 0;
    OTIS_ACTIVE_CHAT.conversationId = this._conversationId;

    this._render();
    this._scrollChatToBottom();

    // Start timer for real-time stopwatch & step advancement
    this._startReasoningTimer();

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

    const extractResolvedAgent = (resObj) => {
      if (!resObj || typeof resObj !== "object") return null;
      return resObj.resolved_agent || resObj.response?.resolved_agent || null;
    };

    const isCancelledRes = (resObj) => {
      if (!resObj || typeof resObj !== "object") return false;
      return Boolean(resObj.cancelled || resObj.response?.cancelled);
    };

    const hassRef = this._hass;
    const callPromise = (async () => {
      let speech = "";
      let resolvedAgent = null;
      const directPayload = { text: displayText };
      if (attachmentsToSend.length > 0) {
        directPayload.attachments = attachmentsToSend;
      }
      if (this._conversationId) {
        directPayload.conversation_id = this._conversationId;
      }

      // 1. Direct call to otis_ai.chat service
      try {
        const directRes = await hassRef.callService(
          "otis_ai",
          "chat",
          directPayload,
          undefined,
          true,
          true
        );
        if (isCancelledRes(directRes) || OTIS_ACTIVE_CHAT.cancelled) {
          throw new Error("__OTIS_STOPPED__");
        }
        speech = extractSpeech(directRes);
        const cid = extractConvId(directRes);
        if (cid) {
          this._conversationId = cid;
          OTIS_ACTIVE_CHAT.conversationId = cid;
        }
        const rAgent = extractResolvedAgent(directRes);
        if (rAgent) resolvedAgent = rAgent;
      } catch (serviceErr) {
        if (serviceErr?.message === "__OTIS_STOPPED__" || OTIS_ACTIVE_CHAT.cancelled) {
          throw new Error("__OTIS_STOPPED__");
        }
        console.debug("otis_ai.chat callService failed, attempting callWS:", serviceErr);
      }

      // 2. WebSocket call_service fallback
      if (!speech && !OTIS_ACTIVE_CHAT.cancelled && hassRef.callWS) {
        try {
          const wsRes = await hassRef.callWS({
            type: "call_service",
            domain: "otis_ai",
            service: "chat",
            service_data: directPayload,
            return_response: true,
          });
          if (isCancelledRes(wsRes) || OTIS_ACTIVE_CHAT.cancelled) {
            throw new Error("__OTIS_STOPPED__");
          }
          speech = extractSpeech(wsRes);
          const cid = extractConvId(wsRes);
          if (cid) {
            this._conversationId = cid;
            OTIS_ACTIVE_CHAT.conversationId = cid;
          }
          const rAgent = extractResolvedAgent(wsRes);
          if (rAgent) resolvedAgent = rAgent;
        } catch (wsErr) {
          if (wsErr?.message === "__OTIS_STOPPED__" || OTIS_ACTIVE_CHAT.cancelled) {
            throw new Error("__OTIS_STOPPED__");
          }
          console.debug("otis_ai.chat callWS failed, attempting conversation.process:", wsErr);
        }
      }

      // 3. Fallback to conversation.process
      if (!speech && !OTIS_ACTIVE_CHAT.cancelled) {
        const agentId = await this._getConversationAgentId();
        let promptWithFiles = displayText;
        if (attachmentsToSend.length > 0) {
          const fileTexts = attachmentsToSend
            .filter((a) => !a.isImage && a.content)
            .map((a) => `\n--- Attached File: ${a.name} ---\n${a.content}\n--- End File ---`);
          if (fileTexts.length > 0) promptWithFiles += fileTexts.join("\n");
        }
        const payload = { text: promptWithFiles };
        if (agentId) payload.agent_id = agentId;
        if (this._conversationId) payload.conversation_id = this._conversationId;

        if (hassRef.callWS) {
          try {
            const cRes = await hassRef.callWS({
              type: "conversation/process",
              ...payload,
            });
            speech = extractSpeech(cRes);
            const cid = extractConvId(cRes);
            if (cid) {
              this._conversationId = cid;
              OTIS_ACTIVE_CHAT.conversationId = cid;
            }
          } catch (cErr) {
            console.debug("conversation/process callWS failed:", cErr);
          }
        }

        if (!speech && !OTIS_ACTIVE_CHAT.cancelled) {
          const res = await hassRef.callService(
            "conversation",
            "process",
            payload,
            undefined,
            true,
            true
          );
          speech = extractSpeech(res);
          const cid = extractConvId(res);
          if (cid) {
            this._conversationId = cid;
            OTIS_ACTIVE_CHAT.conversationId = cid;
          }
        }
      }

      if (OTIS_ACTIVE_CHAT.cancelled) {
        throw new Error("__OTIS_STOPPED__");
      }

      return {
        speech: speech || "I'm here to assist, but received an empty response.",
        resolvedAgent,
      };
    })();

    const configuredTimeout = (this._config && this._config.reasoning_timeout) || (this._capabilityMap && this._capabilityMap.reasoning_timeout) || 60;
    const clientTimeoutMs = (configuredTimeout + 15) * 1000;
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(
        () => reject(new Error(`Assist Co-Pilot reasoning timed out after ${configuredTimeout} seconds. Please verify your AI provider or check failover cascades.`)),
        clientTimeoutMs
      )
    );
    const abortPromise = new Promise((_, reject) => {
      OTIS_ACTIVE_CHAT.abortReject = reject;
    });

    const persistChatMsgAcrossInstances = (msgObj) => {
      const latestMessages = this._loadChatMessages();
      latestMessages.push(msgObj);
      try {
        sessionStorage.setItem("otis_chat_messages", JSON.stringify(latestMessages.slice(-50)));
      } catch (_) { }
      this._chatMessages = latestMessages;
      OTIS_ACTIVE_CHAT.instances.forEach((inst) => {
        inst._chatMessages = latestMessages;
      });
    };

    try {
      const { speech, resolvedAgent } = await Promise.race([callPromise, timeoutPromise, abortPromise]);
      if (OTIS_ACTIVE_CHAT.requestId !== currentReqId || OTIS_ACTIVE_CHAT.cancelled) {
        return;
      }
      const startTs = OTIS_ACTIVE_CHAT.reasoningStartTime || this._reasoningStartTime || Date.now();
      const totalElapsedSec = ((Date.now() - startTs) / 1000).toFixed(1);
      const activeSteps = OTIS_ACTIVE_CHAT.reasoningSteps || this._reasoningSteps || [];
      activeSteps.forEach((s) => {
        s.status = "done";
        if (!s.time) s.time = `${totalElapsedSec}s`;
      });
      const isErrorSpeech =
        !speech ||
        speech.includes("experiencing high demand or downtime") ||
        speech.includes("Quota Exhausted") ||
        speech.includes("didn't receive a response");

      if (
        !isErrorSpeech &&
        resolvedAgent &&
        !activeSteps.some((s) => s.id === "agent_resolution" || (s.title && s.title.startsWith("Resolved by")))
      ) {
        activeSteps.push({
          id: "agent_resolution",
          title: `Resolved by ${resolvedAgent}`,
          detail: `Response generated by ${resolvedAgent} (${totalElapsedSec}s)`,
          status: "done",
          time: `${totalElapsedSec}s`,
        });
      } else if (isErrorSpeech && !activeSteps.some((s) => s.id === "agent_exhaustion" || (s.title && s.title.includes("Unavailable")))) {
        activeSteps.push({
          id: "agent_exhaustion",
          title: "All AI Providers Unavailable",
          detail: `Inference timed out or failed across configured local and cloud agents (${totalElapsedSec}s)`,
          status: "failed",
          time: `${totalElapsedSec}s`,
        });
      }

      const otisMsgId = "otis_" + Date.now();
      persistChatMsgAcrossInstances({
        id: otisMsgId,
        sender: "otis",
        text: speech,
        timestamp: new Date().toISOString(),
        reasoning: {
          duration: `${totalElapsedSec}s`,
          steps: JSON.parse(JSON.stringify(activeSteps)),
        },
      });

      if (
        speech &&
        (speech.includes("successfully created and enabled the automation") ||
          speech.includes("successfully created the script") ||
          speech.includes("Applied successfully!"))
      ) {
        this._fetchData();
      }
    } catch (err) {
      const isStopped = err?.message === "__OTIS_STOPPED__" || OTIS_ACTIVE_CHAT.cancelled;
      const startTs = OTIS_ACTIVE_CHAT.reasoningStartTime || this._reasoningStartTime || Date.now();
      const totalElapsedSec = ((Date.now() - startTs) / 1000).toFixed(1);
      const activeSteps = OTIS_ACTIVE_CHAT.reasoningSteps || this._reasoningSteps || [];
      if (isStopped) {
        persistChatMsgAcrossInstances({
          id: "otis_stop_" + Date.now(),
          sender: "otis",
          text: "⏹️ *Reasoning stopped by user.*",
          timestamp: new Date().toISOString(),
          reasoning: {
            duration: `${totalElapsedSec}s (stopped)`,
            steps: JSON.parse(JSON.stringify(activeSteps)),
          },
        });
      } else {
        console.error("Error sending message to Otis:", err);
        persistChatMsgAcrossInstances({
          id: "otis_err_" + Date.now(),
          sender: "otis",
          text: `⚠️ **Assist Co-Pilot:** ${err.message || "Failed to connect to the AI agent. Please try again."}`,
          timestamp: new Date().toISOString(),
          isError: true,
          reasoning: {
            duration: `${totalElapsedSec}s`,
            steps: JSON.parse(JSON.stringify(activeSteps)),
          },
        });
      }
    } finally {
      if (OTIS_ACTIVE_CHAT.requestId === currentReqId) {
        OTIS_ACTIVE_CHAT.isSending = false;
        OTIS_ACTIVE_CHAT.abortReject = null;
      }
      if (this._reasoningTimer) {
        clearInterval(this._reasoningTimer);
        this._reasoningTimer = null;
      }
      this._isSendingChat = false;
      this._render();
      this._scrollChatToBottom();
      OTIS_ACTIVE_CHAT.instances.forEach((inst) => {
        if (inst !== this) {
          inst._syncActiveChatState();
          inst._render();
          inst._scrollChatToBottom();
        }
      });
    }
  }

  _handleRetry(msgId) {
    if (this._isSendingChat) return;
    const msgIdx = this._chatMessages.findIndex((m) => m.id === msgId);
    if (msgIdx === -1) return;

    // Find the closest preceding user message
    let userMsg = null;
    let userIdx = -1;
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (this._chatMessages[i].sender === "user") {
        userMsg = this._chatMessages[i];
        userIdx = i;
        break;
      }
    }
    if (!userMsg) return;

    const promptText = userMsg.text;
    const promptAttachments = userMsg.attachments ? [...userMsg.attachments] : [];

    // Remove the failed turn (user message, assistant response, and anything between/after)
    this._chatMessages.splice(userIdx);
    this._saveChatMessages();
    this._render();

    // Re-dispatch message cleanly
    this._sendChatMessage(promptText, promptAttachments);
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

  _toggleThemeVoiceRecording() {
    if (this._isListeningTheme) {
      this._stopThemeVoiceRecording();
      return;
    }
    this._startThemeVoiceRecording();
  }

  _startThemeVoiceRecording() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      this._showToast("Speech recognition is not supported in this browser. Please type your theme.", true);
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognition.lang = navigator.language || "en-US";
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      this._themeRecognition = recognition;
      this._isListeningTheme = true;
      this._render();

      const input = this.shadowRoot.querySelector("#theme-prompt-input");
      if (input) {
        input.placeholder = "Listening... describe your dream theme";
      }

      recognition.onresult = (event) => {
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          transcript += event.results[i][0].transcript;
        }
        this._draftThemePrompt = transcript;
        if (input) {
          input.value = transcript;
        }
      };

      recognition.onerror = (event) => {
        console.warn("Otis Theme Voice Error:", event.error);
        this._isListeningTheme = false;
        this._themeRecognition = null;
        if (event.error !== "no-speech") {
          this._showToast(`Voice input: ${event.error}`, true);
        }
        this._render();
      };

      recognition.onend = () => {
        this._isListeningTheme = false;
        this._themeRecognition = null;
        this._render();
      };

      recognition.start();
    } catch (err) {
      console.error("Otis Theme Voice failed to start:", err);
      this._isListeningTheme = false;
      this._themeRecognition = null;
      this._showToast("Could not access microphone.", true);
      this._render();
    }
  }

  _stopThemeVoiceRecording() {
    if (this._themeRecognition) {
      try {
        this._themeRecognition.stop();
      } catch (e) { }
      this._themeRecognition = null;
    }
    this._isListeningTheme = false;
    this._render();
  }

  _showToast(msg, isError = false) {
    this._activeToast = {
      msg,
      isError,
      expiresAt: Date.now() + 4000,
    };
    if (this._toastTimer) {
      clearTimeout(this._toastTimer);
    }
    const toast = this.shadowRoot ? this.shadowRoot.querySelector("#toast") : null;
    if (toast) {
      toast.textContent = msg;
      toast.className = isError ? "toast error show" : "toast show";
    }
    this._toastTimer = setTimeout(() => {
      this._activeToast = null;
      const curToast = this.shadowRoot ? this.shadowRoot.querySelector("#toast") : null;
      if (curToast) {
        curToast.className = "toast";
      }
    }, 4000);
  }

  async _copyToClipboard(text, successToast = "Copied to clipboard!") {
    if (!text) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      if (successToast) {
        this._showToast(successToast);
      }
    } catch (_) {
      this._showToast("⚠️ Failed to copy to clipboard", true);
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

    // Auto-close any unclosed code block (e.g. if truncated by token limit or streaming)
    const tripleBackticks = src.match(/```/g);
    if (tripleBackticks && tripleBackticks.length % 2 === 1) {
      src += "\n```";
    }

    // 1. Protect code blocks first
    const codeBlocks = [];
    src = src.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (match, lang, code) => {
      const idx = codeBlocks.length;
      const cleanCode = code.trim();
      const escapedCode = cleanCode
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      const langLabel = lang ? `<span class="code-lang">${lang}</span>` : `<span class="code-lang">code</span>`;
      const encodedCode = this._escapeHtml(cleanCode);
      codeBlocks.push(
        `<div class="code-block-wrapper">` +
        `<div class="code-block-header">` +
        `${langLabel}` +
        `<button type="button" class="code-copy-btn" title="Copy code snippet" data-code="${encodedCode}">` +
        `<svg viewBox="0 0 24 24" class="copy-icon"><path d="M16 1H4C2.9 1 2 1.9 2 3v14h2V3h12V1zm3 4H8C6.9 5 6 5.9 6 7v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>` +
        `<span class="copy-label">Copy</span>` +
        `</button>` +
        `</div>` +
        `<pre><code>${escapedCode}</code></pre>` +
        `</div>`
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
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");

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
    src = src.replace(/^[ \t]*######[ \t]+(.*)$/gm, "\n\n<h6>$1</h6>\n\n");
    src = src.replace(/^[ \t]*#####[ \t]+(.*)$/gm, "\n\n<h5>$1</h5>\n\n");
    src = src.replace(/^[ \t]*####[ \t]+(.*)$/gm, "\n\n<h4>$1</h4>\n\n");
    src = src.replace(/^[ \t]*###[ \t]+(.*)$/gm, "\n\n<h3>$1</h3>\n\n");
    src = src.replace(/^[ \t]*##[ \t]+(.*)$/gm, "\n\n<h2>$1</h2>\n\n");
    src = src.replace(/^[ \t]*#[ \t]+(.*)$/gm, "\n\n<h1>$1</h1>\n\n");

    // 8. Lists (Unordered & Ordered, including • bullets)
    src = src.replace(/(?:^[ \t]*(?:[-*+]|•)[ \t]+[^\n]+(?:\n|$))+/gm, (match) => {
      const items = match
        .trim()
        .split("\n")
        .map((line) => line.replace(/^[ \t]*(?:[-*+]|•)[ \t]+/, "").trim())
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
      return `\n\n<ul>${items}</ul>\n\n`;
    });

    src = src.replace(/(?:^[ \t]*\d+[.)][ \t]+[^\n]+(?:\n|$))+/gm, (match) => {
      const items = match
        .trim()
        .split("\n")
        .map((line) => line.replace(/^[ \t]*\d+[.)][ \t]+/, "").trim())
        .filter(Boolean)
        .map((item) => `<li>${item}</li>`)
        .join("");
      return `\n\n<ol>${items}</ol>\n\n`;
    });

    // 9. Bold, Italic & Strikethrough (word-boundary safe)
    src = src.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
    src = src.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    src = src.replace(/(^|[\s\(\[{])\*([^*\n]+)\*(?=[\s\.,!?:;\)\]}]|$)/g, "$1<em>$2</em>");
    src = src.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    src = src.replace(/(^|[\s\(\[{])_([^_\n]+)_(?=[\s\.,!?:;\)\]}]|$)/g, "$1<em>$2</em>");
    src = src.replace(/~~([^~]+)~~/g, "<del>$1</del>");

    // 10. Links
    src = src.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)"'<>]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

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

  _renderPeopleTrainingSummaryBanner() {
    const profiles = { ...(this._userRules?.person_profiles || {}) };
    const ignored = (this._userRules?.ignored_persons || []).map((x) => String(x).toLowerCase());
    const availUsers = this._getAvailableUsers();

    availUsers.forEach((u) => {
      const pid = u.id.toLowerCase();
      if (!ignored.includes(pid) && !profiles[pid]) {
        profiles[pid] = {
          person_id: pid,
          label: u.name,
          confidence: 0.50,
          samples: 0,
          entity_type: /dexter|charles|dog|cat|pet/i.test(u.name) ? "pet" : (/guest/i.test(u.name) ? "guest" : "resident"),
          training_enabled: true,
          verified_rooms: [],
        };
      }
    });

    const activeList = Object.values(profiles).filter(
      (p) => !ignored.includes(String(p.person_id).toLowerCase()) && p.entity_type !== "ignored" && p.training_enabled !== false
    );
    if (!activeList.length) return "";

    return `
      <div style="margin-bottom: 12px; padding: 12px 14px; background: rgba(14, 165, 233, 0.08); border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 10px; display: flex; flex-direction: column; gap: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <div>
            <div style="font-weight: 700; font-size: 0.85rem; color: var(--otis-primary);">🎯 Identity &amp; Presence Training Progress</div>
            <div style="font-size: 0.73rem; color: var(--otis-text-muted);">Verify room entry snapshots below or click + Verify to reach 5/5 samples (85%+ confidence) for each resident, pet, or guest—powering personalized room comfort, pet-immune security, guest hospitality, and spatial routines.</div>
          </div>
          <button type="button" class="btn-subtle-toggle" id="btn-open-people-rules" style="font-size: 0.72rem; padding: 4px 10px;">
            ⚙️ Manage People &amp; Pets
          </button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px;">
          ${activeList.map((p) => {
      const pid = p.person_id;
      const pType = p.entity_type || (/dexter|charles|pet|dog|cat/i.test(p.label || pid) ? "pet" : (/guest/i.test(p.label || pid) ? "guest" : "resident"));
      const icon = pType === "pet" ? "🐾" : (pType === "guest" ? "👥" : "👤");
      const samples = Number(p.samples || 0);
      const confPct = Math.round((p.confidence || 0.50) * 100);
      const progPct = Math.min(100, Math.round(Math.max((samples / 5) * 100, confPct)));
      const isComplete = samples >= 5 || confPct >= 85;
      const statusText = isComplete ? "🟢 Trained" : (samples > 0 ? "🟡 Calibrating" : "🔵 Needs Samples");
      const barColor = isComplete ? "#10b981" : "#38bdf8";
      const roomsList = Array.isArray(p.verified_rooms) && p.verified_rooms.length
        ? `Rooms: ${p.verified_rooms.map((r) => String(r).replace(/_/g, " ")).join(", ")}`
        : "No room samples verified yet";

      return `
              <div style="padding: 8px 10px; border-radius: 8px; background: rgba(0,0,0,0.25); border: 1px solid var(--otis-surface-border); display: flex; flex-direction: column; gap: 5px;">
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
                  <span style="font-weight: 700; font-size: 0.78rem; color: var(--otis-text);">${icon} ${this._escapeHtml(p.label || pid)}</span>
                  <span style="font-size: 0.68rem; font-weight: 700; color: ${barColor};">${statusText}</span>
                </div>
                <div style="width: 100%; height: 6px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden;">
                  <div style="width: ${progPct}%; height: 100%; background: ${barColor}; transition: width 0.3s ease;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.69rem; color: var(--otis-text-muted);">
                  <span>${samples}/5 camera samples • ${confPct}% conf</span>
                  ${samples > 0 ? `
                    <button type="button" class="btn-reset-person-training" data-person-id="${this._escapeHtml(pid)}" data-person-label="${this._escapeHtml(p.label || pid)}" style="background: rgba(245,158,11,0.15); color: #f59e0b; border: 1px solid rgba(245,158,11,0.35); border-radius: 4px; padding: 1px 6px; font-size: 0.66rem; font-weight: 600; cursor: pointer;" title="Reset training samples for this profile">
                      ↺ Reset
                    </button>
                  ` : `<span style="font-size: 0.65rem; color: var(--otis-text-muted);">📸 Verify via camera card</span>`}
                </div>
                <div style="font-size: 0.66rem; color: var(--otis-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${this._escapeHtml(roomsList)}">
                  📍 ${this._escapeHtml(roomsList)}
                </div>
              </div>
            `;
    }).join("")}
        </div>
      </div>
    `;
  }

  _renderTrainingVerificationMedia(suggestion) {
    if (
      !suggestion ||
      (suggestion.action_type !== "confirm_person_identity" &&
        suggestion.action_type !== "confirm_room_transition")
    ) {
      return "";
    }
    const payload = suggestion.action_payload || {};
    const areaSlug = String(payload.area || payload.from_area || payload.visual_features?.area || "").trim().toLowerCase();
    const areaName = payload.area_name || payload.from_area_name || payload.visual_features?.area_name || areaSlug || "Room";
    const states = this._hass?.states || {};

    const aliases = new Set([areaSlug, String(areaName).toLowerCase().replace(/\s+/g, "_")].filter(Boolean));
    if (areaSlug === "great_room") {
      aliases.add("kitchen");
      aliases.add("living_room");
      aliases.add("greatroom");
    } else if (areaSlug === "foyer") {
      aliases.add("frontdoor");
      aliases.add("front_door");
      aliases.add("entryway");
    } else if (areaSlug === "frontyard") {
      aliases.add("front_doorbell");
      aliases.add("frontdoor");
      aliases.add("driveway");
      aliases.add("porch");
    } else if (areaSlug === "garage") {
      aliases.add("driveway");
    }

    let detEid = payload.detection_image_entity_id || payload.visual_features?.detection_image_entity_id || null;
    let snapEid = payload.snapshot_camera_entity_id || null;
    let camEid = payload.camera_entity_id || payload.visual_features?.camera_entity_id || null;
    let camName = payload.camera_name || areaName;
    let detLabel = payload.detection_label || "Detection";

    // Dynamically discover matching image.* and camera.* from live hass.states if needed
    const allEids = Object.keys(states);
    if (!detEid || !states[detEid] || ["unknown", "unavailable"].includes(String(states[detEid]?.state).toLowerCase())) {
      for (const eid of allEids) {
        const low = eid.toLowerCase();
        if (!low.startsWith("image.")) continue;
        if (!/_(person|dog|cat|pet|animal)$/.test(low)) continue;
        const st = states[eid];
        if (!st || ["unknown", "unavailable", "none", ""].includes(String(st.state).toLowerCase())) continue;
        const matches = Array.from(aliases).some((a) => a && (low.includes(`.${a}_`) || low.includes(`_${a}_`)));
        if (matches) {
          detEid = eid;
          detLabel = low.endsWith("_person") ? "Person" : (low.endsWith("_dog") ? "Dog" : (low.endsWith("_cat") ? "Cat" : "Pet/Animal"));
          break;
        }
      }
    }

    if (!snapEid) {
      for (const eid of allEids) {
        const low = eid.toLowerCase();
        if (!low.startsWith("camera.") || !low.includes("snapshot")) continue;
        const st = states[eid];
        if (!st || String(st.state).toLowerCase() === "unavailable") continue;
        const matches = Array.from(aliases).some((a) => a && low.includes(a));
        if (matches) {
          snapEid = eid;
          break;
        }
      }
    }

    if (!camEid) {
      const topoCams = this._capabilityMap?.vision_topology?.cameras || [];
      for (const c of topoCams) {
        const cArea = String(c.area_id || "").toLowerCase();
        const cLow = String(c.entity_id || "").toLowerCase();
        if (cArea === areaSlug || Array.from(aliases).some((a) => a && cLow.includes(a))) {
          camEid = c.entity_id;
          camName = c.name || camName;
          break;
        }
      }
      if (!camEid) {
        for (const eid of allEids) {
          const low = eid.toLowerCase();
          if (!low.startsWith("camera.") || low.includes("snapshot") || low.includes("map")) continue;
          const st = states[eid];
          if (!st || String(st.state).toLowerCase() === "unavailable") continue;
          if (Array.from(aliases).some((a) => a && low.includes(a))) {
            camEid = eid;
            camName = st.attributes?.friendly_name || camName;
            break;
          }
        }
      }
    }

    const resolvePic = (eid, fallbackPic) => {
      if (eid && states[eid]) {
        const st = states[eid];
        const stVal = String(st.state || "").toLowerCase();
        if (eid.startsWith("image.") && (stVal === "unknown" || stVal === "unavailable")) {
          return null;
        }
        if (stVal === "unavailable") return null;
        if (st.attributes?.entity_picture) return st.attributes.entity_picture;
        if (st.attributes?.access_token) {
          const proxy = eid.startsWith("image.") ? "image_proxy" : "camera_proxy";
          return `/api/${proxy}/${eid}?token=${st.attributes.access_token}`;
        }
      }
      return fallbackPic || null;
    };

    const detPic = resolvePic(detEid, payload.detection_image_picture);
    const snapPic = resolvePic(snapEid, payload.snapshot_camera_picture);
    const camPic = resolvePic(camEid, payload.camera_entity_picture || payload.entity_picture);

    const bestDetPic = detPic || snapPic;
    const bestDetEid = detPic ? detEid : snapEid;
    if (!bestDetPic && !camPic) return "";

    let detTimeStr = "";
    if (detEid && states[detEid]?.state && !["unknown", "unavailable"].includes(String(states[detEid].state).toLowerCase())) {
      const dt = new Date(states[detEid].state);
      if (!isNaN(dt.getTime())) {
        detTimeStr = ` • ${dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
      }
    }

    const showDual = Boolean(bestDetPic && camPic && bestDetPic !== camPic);
    const bbox = payload.detection_bbox;
    let bboxOverlayHtml = "";
    if (
      bbox &&
      Number.isFinite(Number(bbox.ymin)) &&
      Number.isFinite(Number(bbox.xmin)) &&
      Number.isFinite(Number(bbox.ymax)) &&
      Number.isFinite(Number(bbox.xmax))
    ) {
      const topPct = Math.max(0, Math.min(99, Number(bbox.ymin) / 10));
      const leftPct = Math.max(0, Math.min(99, Number(bbox.xmin) / 10));
      const heightPct = Math.max(1, Math.min(100 - topPct, (Number(bbox.ymax) - Number(bbox.ymin)) / 10));
      const widthPct = Math.max(1, Math.min(100 - leftPct, (Number(bbox.xmax) - Number(bbox.xmin)) / 10));
      const boxLbl = this._escapeHtml(bbox.label || detLabel);
      bboxOverlayHtml = `
        <div style="position: absolute; top: ${topPct.toFixed(2)}%; left: ${leftPct.toFixed(2)}%; width: ${widthPct.toFixed(2)}%; height: ${heightPct.toFixed(2)}%; border: 2px solid #fbbf24; border-radius: 4px; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.7), 0 0 10px rgba(251, 191, 36, 0.55); pointer-events: none; box-sizing: border-box;">
          <span style="position: absolute; top: -18px; left: -1px; background: rgba(251, 191, 36, 0.95); color: #0f172a; font-size: 0.60rem; font-weight: 800; padding: 1px 5px; border-radius: 3px; white-space: nowrap; line-height: 1.2;">🎯 ${boxLbl}</span>
        </div>
      `;
    }

    return `
      <div style="display: grid; grid-template-columns: ${showDual ? "repeat(auto-fit, minmax(210px, 1fr))" : "1fr"}; gap: 10px; margin: 10px 0; max-width: ${showDual ? "560px" : "320px"};">
        ${bestDetPic ? `
          <div class="camera-preview-container" data-cam-id="${this._escapeHtml(bestDetEid || camEid || "")}" data-snapshot-pic="${this._escapeHtml(bestDetPic)}" data-snapshot-title="${this._escapeHtml(`${areaName} • ${detLabel} Snapshot${detTimeStr}`)}" data-snapshot-bbox="${this._escapeHtml(bbox ? JSON.stringify(bbox) : "")}" title="Click to enlarge detection snapshot" style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid rgba(56, 189, 248, 0.38); background: #090d16; cursor: pointer; display: flex; align-items: center; justify-content: center; max-height: 195px;">
            <div style="position: relative; display: inline-block; max-width: 100%; max-height: 195px;">
              <img src="${this._escapeHtml(bestDetPic)}" alt="${this._escapeHtml(areaName)} Detection Snapshot" loading="lazy" style="max-width: 100%; max-height: 195px; width: auto; height: auto; display: block;" onerror="${camPic && camPic !== bestDetPic ? `this.onerror=null; this.src='${this._escapeHtml(camPic)}';` : `this.closest('.camera-preview-container').style.display='none';`}" />
              ${bboxOverlayHtml}
            </div>
            <span style="position: absolute; top: 6px; left: 6px; background: rgba(15, 23, 42, 0.86); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.45); border-radius: 6px; padding: 2px 7px; font-size: 0.67rem; font-weight: 700; backdrop-filter: blur(6px);">
              🎯 ${this._escapeHtml(detLabel)} Snapshot${this._escapeHtml(detTimeStr)}
            </span>
            <span style="position: absolute; bottom: 6px; right: 6px; background: rgba(15, 23, 42, 0.78); color: #e2e8f0; border-radius: 5px; padding: 2px 6px; font-size: 0.64rem;">
              🔍 Click to Enlarge
            </span>
          </div>
        ` : ""}
        ${camPic && (!bestDetPic || showDual) ? `
          <div class="camera-preview-container" data-cam-id="${this._escapeHtml(camEid || bestDetEid || "")}" title="Click to open live camera feed" style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid rgba(148, 163, 184, 0.28); background: #090d16; cursor: pointer; aspect-ratio: 16 / 9; max-height: 175px;">
            <img src="${this._escapeHtml(camPic)}" alt="${this._escapeHtml(camName)} Live View" loading="lazy" style="width: 100%; height: 100%; object-fit: cover; display: block;" onerror="this.closest('.camera-preview-container').style.display='none';" />
            <span style="position: absolute; top: 6px; left: 6px; background: rgba(15, 23, 42, 0.86); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.45); border-radius: 6px; padding: 2px 7px; font-size: 0.67rem; font-weight: 700; backdrop-filter: blur(6px);">
              📹 ${this._escapeHtml(camName)} (Live)
            </span>
            <span style="position: absolute; bottom: 6px; right: 6px; background: rgba(15, 23, 42, 0.78); color: #e2e8f0; border-radius: 5px; padding: 2px 6px; font-size: 0.64rem;">
              🔍 Click for Stream
            </span>
          </div>
        ` : ""}
      </div>
    `;
  }

  _matchesCategoryFilter(suggestion, filterKey) {
    if (!filterKey || filterKey === "all") return true;
    const cat = String(suggestion?.category || "automation").toLowerCase();
    const map = {
      news: ["news", "official_news", "announcement"],
      habits: ["habit_routine", "habit_deviation", "habits", "behavioral", "presence"],
      presence: ["presence", "people", "identity"],
      lighting: ["lighting", "automation"],
      migration: ["migration", "automation_migration", "blueprint_migration"],
      media: ["media"],
      security: ["security"],
      dashboard: ["dashboard", "visualization"],
      cleanup: ["cleanup"],
      energy: ["energy"],
      mesh: ["mesh", "network"],
      system: ["system"],
    };
    const allowed = map[filterKey] || [filterKey];
    return allowed.includes(cat);
  }

  _getActionLabel(actionType) {
    switch (actionType) {
      case "open_url":
      case "read_article":
        return "📰 Read Full Article ↗";
      case "create_automation":
        return "⚡ Create Habit Automation";
      case "create_package":
        return "📦 Deploy Coordinator Package";
      case "auto_assign_areas":
        return "📍 Auto-Assign Areas";
      case "auto_commission_entities":
        return "🏠 Auto-Commission Rooms";
      case "confirm_person_identity":
        return "👤 Confirm Identity Profile";
      case "heal_mesh_node":
      case "heal_mesh_network":
        return "📡 Auto-Heal Mesh Routes";
      case "execute_energy_arbitrage":
        return "⚡ Dispatch Energy Arbitrage";
      case "schedule_ev_charging":
        return "🌙 Schedule Off-Peak Charging";
      case "fuse_presence":
        return "🎯 Calibrate Radar Presence";
      case "propose_automation_migration":
        return "🚀 Propose Native Coordinator";
      case "sync_federated_nodes":
        return "🌐 Resync Edge Nodes";
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
      case "load_shed":
        return "⚡ Shed High-Draw Loads";
      case "chat_prompt":
        return "💬 Optimize in Assist";
      case "configure_agent":
        return "⚙️ Configure AI Failover";
      case "install_ollama_addon":
        return "🧠 Open in Add-on Store";
      case "switch_local_llm_model":
        return "⚡ Pull & Activate Model";
      default:
        return "⚡ Apply with 1-Click";
    }
  }

  _render() {
    const showIgnored = Boolean(
      this._localShowIgnored ||
      this._config.show_ignored ||
      this._userRules?.show_ignored_recommendations
    );
    const priorityRank = { critical: 0, high: 1, medium: 2, low: 3 };
    const activeSuggestions = (this._suggestions || [])
      .filter((s) => !this._hiddenIds.has(s.id) && (showIgnored || !this._dismissedIds.has(s.id)))
      .slice()
      .sort((a, b) => {
        const rankA = priorityRank[String(a.priority || "medium").toLowerCase()] ?? 2;
        const rankB = priorityRank[String(b.priority || "medium").toLowerCase()] ?? 2;
        return rankA - rankB;
      });
    const filteredSuggestions = activeSuggestions.filter((s) =>
      this._matchesCategoryFilter(s, this._selectedCategory)
    );
    const maxSuggestionsLimit = this._config.max_suggestions || 5;
    const visibleSuggestions = showIgnored
      ? filteredSuggestions
      : filteredSuggestions.slice(0, maxSuggestionsLimit);

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
    const isMediaStudioMode = this._config.mode === "media_studio";
    const isSecurityMode = this._config.mode === "security";
    const isClimateMode = this._config.mode === "climate";
    const isEnergyMode = this._config.mode === "energy";
    const isRoomMode = this._config.mode === "room_view";
    const isStudioHeaderMode = isSecurityMode || isClimateMode || isEnergyMode || isRoomMode;
    const isAdmin = Boolean(this._hass?.user?.is_admin || this._hass?.user?.is_owner);
    const rawLayout = String(this._userRules?.dashboard_layout || "modern_sections").toLowerCase();
    const layoutClass = rawLayout === "classic_grid" ? "classic" : rawLayout;
    const navClass = String(this._userRules?.navigation_style || "sleek_buttons").toLowerCase();

    const prevChatEl = this.shadowRoot ? this.shadowRoot.querySelector("#chat-history") : null;
    const wasChatScrolledUp = Boolean(
      prevChatEl &&
      (prevChatEl.scrollHeight - prevChatEl.scrollTop - prevChatEl.clientHeight > 60)
    );
    const prevChatScrollTop = prevChatEl ? prevChatEl.scrollTop : 0;

    this.shadowRoot.innerHTML = `
      <style>
      ${CARD_STYLES}
      </style>

      <ha-card class="card-container ${themeClass} layout-${this._escapeHtml(layoutClass)} nav-${this._escapeHtml(navClass)} ${isStudioMode ? "mode-floorplan-studio" : ""} ${isMediaStudioMode ? "mode-media-studio" : ""}">
        ${isMediaStudioMode
        ? `
          <!-- Media Studio Header -->
          <div class="studio-header">
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
              <button type="button" class="btn-toolbar" id="btn-back-dashboard" title="Return to Dashboard">
                ← Back
              </button>
              <div class="title-group">
                <span class="main-title">${this._escapeHtml(this._config.title || "🎵 Media Studio & Source-to-Zone Router")}</span>
                <span class="sub-title">
                  <span class="status-dot"></span>
                  Multi-Room Matrix Routing • Input-to-Player Mapping • Per-User Favorites
                </span>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <button type="button" class="icon-btn" id="btn-open-themes" title="Dynamic AI Theme Studio">
                🎨 Themes
              </button>
            </div>
          </div>
          ${this._renderMediaStudioTab()}
        `
        : isStudioHeaderMode
          ? `
          <!-- Unified Studio / Room Header -->
          <div class="studio-header">
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
              <button type="button" class="btn-toolbar" id="btn-back-dashboard" title="Return to Dashboard">
                ← Back
              </button>
              <div class="title-group">
                <span class="main-title">${this._escapeHtml(this._config.title || (isSecurityMode ? "🛡️ Security Center" : (isClimateMode ? "🌡️ Climate & Pool Studio" : (isEnergyMode ? "⚡ Energy Studio" : "📍 Room View"))))}</span>
                <span class="sub-title">
                  <span class="status-dot"></span>
                  ${this._escapeHtml(
            isSecurityMode
              ? "Perimeter Sentinel • Smart Locks • Motion & Occupancy Security"
              : isClimateMode
                ? "HVAC Dual-Setpoints • Ceiling Fans • Pool & Spa Controls"
                : isEnergyMode
                  ? "Predictive Load Shedding • Solar & Inverter • TOU Tariff Management"
                  : "Live Room Telemetry • Smart Lighting • Environmental Controls"
          )}
                </span>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <button type="button" class="icon-btn" id="btn-open-themes" title="Dynamic AI Theme Studio">
                🎨 Themes
              </button>
            </div>
          </div>
        `
          : isStudioMode
            ? `
          ${!isControlMode
              ? `
          <!-- Studio Header (Full Width Blueprint Workspace) -->
          <div class="studio-header">
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
              <button type="button" class="btn-toolbar" id="btn-back-dashboard" title="Return to Dashboard">
                ← Back
              </button>
              <div class="title-group">
                <span class="main-title">🗺️ Architectural Floor Plan Studio</span>
                <span class="sub-title">
                  <span class="status-dot"></span>
                  ${this._editorActive ? "Canvas Editor Mode Active • Drag pins & resize rooms" : "Interactive Blueprint Viewer"}
                </span>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              ${isAdmin
                ? `
                <button type="button" class="btn-toolbar ${this._editorActive ? 'active' : ''}" id="btn-toggle-editor" style="${this._editorActive ? 'background: var(--otis-primary); color: var(--otis-btn-text, #ffffff); border-color: var(--otis-primary);' : ''}">
                  ${this._editorActive ? "🛠️ Exit Editor" : "✏️ Edit Blueprint"}
                </button>
              `
                : ""
              }
              <button type="button" class="icon-btn" id="btn-open-themes" title="Dynamic AI Theme Studio">
                🎨 Themes
              </button>
            </div>
          </div>
          `
              : ""
            }
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
                <span class="main-title">${this._escapeHtml(this._config.title || "Otis AI Companion")}</span>
                <span class="sub-title">
                  <span class="status-dot"></span>
                  Autonomous Co-Pilot Active
                </span>
              </div>
            </div>
            <div class="header-actions">
              <button type="button" class="icon-btn" id="btn-open-rules" title="Otis Behavioral Rules & Configuration">
                ⚙️ Rules
              </button>
              <button type="button" class="icon-btn" id="btn-open-themes" title="Dynamic AI Theme Studio">
                🎨 Themes
              </button>
              <button type="button" class="icon-btn" id="refresh-btn" title="Refresh intelligence">
                ↻ Refresh
              </button>
            </div>
          </div>

          <!-- Quick Stats Bar -->
          ${this._config.show_stats !== false
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

          <!-- Weather & Calendar Glance Strip -->
          ${this._renderGlanceStrip()}

          <!-- Spatial Migration Pre-Conditioning Status Chip -->
          ${this._renderPreconditioningChip()}

          ${this._shouldShowOnboardingBanner()
              ? `
            <!-- Onboarding Wizard Callout Banner -->
            <div class="onboarding-banner" id="onboarding-banner" style="display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; margin-bottom: 12px; background: linear-gradient(135deg, rgba(14, 165, 233, 0.15), rgba(168, 85, 247, 0.15)); border: 1px solid rgba(56, 189, 248, 0.35); border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.2);">
              <div>
                <div style="display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 0.88rem; color: var(--otis-primary, #38bdf8);">
                  <span>✨ Welcome to Otis AI</span>
                  <span style="font-size: 0.7rem; padding: 1px 6px; border-radius: 4px; background: rgba(56,189,248,0.2); text-transform: uppercase;">Setup</span>
                </div>
                <div style="font-size: 0.78rem; color: var(--otis-text-muted, #94a3b8); margin-top: 2px;">
                  Personalize Otis for your home: choose your assistant's persona, voice guidelines, quiet hours, and custom household rules.
                </div>
              </div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <button type="button" class="subview-chip" id="btn-start-onboarding" style="background: var(--otis-primary, #0ea5e9); color: #fff; font-weight: 600; padding: 6px 14px; border: none;">Start Setup →</button>
                <button type="button" class="modal-close-btn" id="btn-dismiss-onboarding" title="Dismiss" style="font-size: 0.9rem; width: 24px; height: 24px; border: none; background: transparent; cursor: pointer; color: var(--otis-text-muted);">✕</button>
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
              <button type="button" class="subview-chip" data-subview="${dashPrefix}/energy">⚡ Energy Studio</button>
              <button type="button" class="subview-chip" data-subview="${dashPrefix}/floorplan">🗺️ Floor Plan</button>
              ${isAdmin ? `
                <button type="button" class="subview-chip" id="btn-sync-dashboards" title="Sync all Studios & Rooms to Command Center" style="margin-left: auto;">🔄 Sync</button>
                <button type="button" class="subview-chip" id="btn-regenerate-dashboards" title="Regenerate Command Center, all Studios & Rooms from scratch" style="margin-left: 6px; background: rgba(14, 165, 233, 0.15); border-color: rgba(14, 165, 233, 0.4); color: var(--otis-primary);">⚡ Regenerate</button>
              ` : ""}
            </div>
            ${activeAreas.length > 0
              ? `
              <div class="launchpad-row">
                <span class="subviews-label">Rooms:</span>
                ${activeAreas
                .map(
                  (room) => `
                  <button type="button" class="subview-chip room-chip" data-subview="${this._escapeHtml(room.path)}">${this._getRoomEmoji(room.name)} ${this._escapeHtml(room.name)}</button>
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
            ${this._config.show_suggestions !== false
              ? `
              <button type="button" class="tab-btn ${this._activeTab === "suggestions" ? "active" : ""}" id="tab-suggestions">
                Proactive Feed
                ${activeSuggestions.length > 0 ? `<span class="tab-badge">${activeSuggestions.length}</span>` : ""}
              </button>
            `
              : ""
            }
            ${this._config.show_chat !== false
              ? `
              <button type="button" class="tab-btn ${this._activeTab === "chat" ? "active" : ""}" id="tab-chat">
                Assist Co-Pilot
              </button>
            `
              : ""
            }
            <button type="button" class="tab-btn ${this._activeTab === "media" ? "active" : ""}" id="tab-media">
              🎵 Media
            </button>
            <button type="button" class="tab-btn ${this._activeTab === "floorplan" ? "active" : ""}" id="tab-floorplan">
              Floor Plan
              ${this._capabilityMap?.floorplan?.exists ? "" : `<span class="tab-badge" style="background: var(--otis-accent, #a855f7);">New</span>`}
            </button>
            <button type="button" class="tab-btn ${this._activeTab === "vision" ? "active" : ""}" id="tab-vision">
              Vision &amp; Presence
            </button>
            <button type="button" class="tab-btn ${this._activeTab === "capabilities" ? "active" : ""}" id="tab-capabilities">
              Capabilities
            </button>
          </div>

          ${this._activeTab === "suggestions" ? this._renderSuggestionsTab(visibleSuggestions) : ""}
          ${this._activeTab === "chat" ? this._renderChatTab() : ""}
          ${this._activeTab === "media" ? this._renderMediaStudioTab() : ""}
          ${this._activeTab === "capabilities" ? this._renderCapabilitiesTab(stats) : ""}
          ${this._activeTab === "floorplan" ? this._renderFloorplanTab() : ""}
          ${this._activeTab === "vision" ? this._renderVisionTab() : ""}
        `
      }

      </ha-card>

      <!-- Feedback Toast (Rendered outside ha-card so position: fixed anchors to the browser viewport) -->
      <div class="${this._activeToast && Date.now() < this._activeToast.expiresAt ? (this._activeToast.isError ? 'toast error show' : 'toast show') : 'toast'}" id="toast">${this._activeToast && Date.now() < this._activeToast.expiresAt ? this._escapeHtml(this._activeToast.msg) : ""}</div>

      <!-- Viewport Floating Modals (Rendered outside ha-card to prevent backdrop-filter / overflow containment clipping) -->
      ${this._floorplanModalOpen ? this._renderWalkthroughModal() : ""}
      ${this._themeModalOpen ? this._renderThemeModal() : ""}
      ${this._addMarkerModalOpen ? this._renderAddMarkerModal() : ""}
      ${this._editMarkerModalOpen ? this._renderEditMarkerModal() : ""}
      ${this._guideModalOpen ? this._renderGuideModal() : ""}
      ${this._failoverModalOpen ? this._renderFailoverModal() : ""}
      ${this._rulesModalOpen ? this._renderRulesModal() : ""}
      ${this._githubModalOpen ? this._renderGitHubIssueModal() : ""}
      ${this._reviewSuggestion ? this._renderReviewSuggestionModal() : ""}
      ${this._snapshotLightbox ? this._renderSnapshotLightboxModal() : ""}
    `;

    this._bindEvents();

    if (this._activeTab === "chat" && !isStudioMode) {
      const chatHistoryEl = this.shadowRoot.querySelector("#chat-history");
      if (chatHistoryEl) {
        if (!wasChatScrolledUp || !prevChatEl) {
          this._chatInitialScrolled = true;
          chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
          this._scrollChatToBottom();
        } else {
          this._chatInitialScrolled = true;
          const restoreScroll = () => {
            const el = this.shadowRoot ? this.shadowRoot.querySelector("#chat-history") : null;
            if (el) {
              el.scrollTop = prevChatScrollTop;
            }
          };
          chatHistoryEl.scrollTop = prevChatScrollTop;
          requestAnimationFrame(restoreScroll);
          setTimeout(restoreScroll, 60);
          setTimeout(restoreScroll, 180);
        }
      }
    }
  }

  _renderGlanceStrip() {
    if (this._config.show_glance === false) return "";

    // 1. Weather entity
    const weatherEntities = Object.keys(this._hass?.states || {}).filter((k) => k.startsWith("weather."));
    const weatherEid = this._config.weather_entity || weatherEntities[0];
    const weatherObj = weatherEid ? this._hass?.states?.[weatherEid] : null;

    // 2. Calendar entity
    const calendarEntities = Object.keys(this._hass?.states || {}).filter((k) => k.startsWith("calendar."));
    const calendarEid = this._config.calendar_entity || (calendarEntities.includes("calendar.united_states_nc") ? "calendar.united_states_nc" : calendarEntities[0]);
    const calendarObj = calendarEid ? this._hass?.states?.[calendarEid] : null;

    if (!weatherObj && !calendarObj) return "";

    const weatherIcons = {
      "clear-night": "🌙",
      "cloudy": "☁️",
      "exceptional": "⚠️",
      "fog": "🌫️",
      "hail": "🌨️",
      "lightning": "⚡",
      "lightning-rainy": "⛈️",
      "partlycloudy": "⛅",
      "pouring": "🌧️",
      "rainy": "🌧️",
      "snowy": "❄️",
      "snowy-rainy": "🌨️",
      "sunny": "☀️",
      "windy": "💨",
      "windy-variant": "🌬️",
    };

    let weatherHtml = "";
    if (weatherObj) {
      const cond = String(weatherObj.state || "unknown").toLowerCase();
      const icon = weatherIcons[cond] || "🌤️";
      const temp = weatherObj.attributes?.temperature != null ? Math.round(weatherObj.attributes.temperature) : "--";
      const unit = weatherObj.attributes?.temperature_unit || this._hass?.config?.unit_system?.temperature || "°F";
      const cleanCond = cond.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      const hum = weatherObj.attributes?.humidity;
      const wind = weatherObj.attributes?.wind_speed;
      const subtitle = hum != null ? `${hum}% Humidity` : (wind != null ? `${wind} mph Wind` : (weatherObj.attributes?.friendly_name || "Outdoor Weather"));

      weatherHtml = `
        <div class="glance-chip weather-chip" id="glance-weather" data-entity-id="${this._escapeHtml(weatherEid)}" title="Weather: ${this._escapeHtml(cleanCond)} • Tap for detailed forecast">
          <span class="glance-icon">${icon}</span>
          <div class="glance-text">
            <span class="glance-primary">${this._escapeHtml(temp)}°${this._escapeHtml(unit)} • ${this._escapeHtml(cleanCond)}</span>
            <span class="glance-secondary">${this._escapeHtml(subtitle)}</span>
          </div>
        </div>
      `;
    }

    let calendarHtml = "";
    if (calendarObj) {
      const msg = calendarObj.attributes?.message || calendarObj.attributes?.friendly_name || "Calendar";
      const hasEvent = Boolean(calendarObj.attributes?.message);
      let timeText = "No upcoming events scheduled";
      if (hasEvent) {
        const startTime = calendarObj.attributes?.start_time;
        if (startTime) {
          try {
            const dt = new Date(startTime);
            const isToday = dt.toDateString() === new Date().toDateString();
            const timeStr = dt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
            timeText = isToday ? `Today at ${timeStr}` : dt.toLocaleDateString([], { month: "short", day: "numeric" });
          } catch (_) {
            timeText = startTime;
          }
        } else {
          timeText = "Active Agenda";
        }
      }

      calendarHtml = `
        <div class="glance-chip calendar-chip" id="glance-calendar" data-entity-id="${this._escapeHtml(calendarEid)}" title="Calendar: ${this._escapeHtml(msg)} • Tap for agenda view">
          <span class="glance-icon">📅</span>
          <div class="glance-text">
            <span class="glance-primary">${this._escapeHtml(hasEvent ? msg : "Calendar Agenda")}</span>
            <span class="glance-secondary">${this._escapeHtml(timeText)}</span>
          </div>
        </div>
      `;
    }

    return `
      <div class="glance-strip">
        ${weatherHtml}
        ${calendarHtml}
      </div>
    `;
  }

  _resolveOtisEntityId(baseEid) {
    const states = this._hass?.states || {};
    if (states[baseEid]) return baseEid;
    const prefix = `${baseEid}_`;
    const match = Object.keys(states).find((k) => k.startsWith(prefix));
    return match || baseEid;
  }

  _renderPreconditioningChip() {
    const sensorEid = this._resolveOtisEntityId("sensor.otis_spatial_migration");
    const sensor = this._hass?.states?.[sensorEid];
    if (!sensor) return "";
    const pState = sensor.attributes?.preconditioning_state;
    if (pState !== "in_progress") return "";

    const label = sensor.attributes?.preconditioning_label || (
      sensor.state === "movie_night" ? "🎬 Theater Pre-Cooling in progress" :
        sensor.state === "sleep_bedtime" ? "🌙 Master Bedroom Nighttime Pre-Arming in progress" :
          "⚡ Spatial Pre-Conditioning in progress"
    );
    const macroId = sensor.attributes?.preconditioning_macro_id || "";
    const expiresAt = parseFloat(sensor.attributes?.preconditioning_expires_at) || 0;
    const nowSec = Date.now() / 1000;
    const minsLeft = expiresAt > nowSec ? Math.max(1, Math.round((expiresAt - nowSec) / 60)) : 10;
    const actionSummary = sensor.attributes?.action_summary || "";
    const audioActive = Boolean(sensor.attributes?.audio_follow_active);
    const audioTarget = sensor.attributes?.audio_follow_target ? String(sensor.attributes.audio_follow_target).replace(/_/g, " ") : "";

    return `
      <div class="preconditioning-banner" id="preconditioning-banner" style="display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; margin-bottom: 12px; background: linear-gradient(135deg, rgba(14, 165, 233, 0.22), rgba(56, 189, 248, 0.08)); border: 1px solid rgba(56, 189, 248, 0.45); border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.25);">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.15rem; filter: drop-shadow(0 0 8px #38bdf8);">🎬</span>
          <div>
            <div style="font-weight: 700; font-size: 0.85rem; color: #38bdf8; display: flex; align-items: center; gap: 6px;">
              <span>${this._escapeHtml(label)}</span>
              <span style="font-size: 0.65rem; padding: 1px 6px; border-radius: 4px; background: rgba(56,189,248,0.25); color: #e0f2fe; text-transform: uppercase;">Active</span>
              ${audioActive ? `<span style="font-size: 0.65rem; padding: 1px 6px; border-radius: 4px; background: rgba(168,85,247,0.25); border: 1px solid rgba(168,85,247,0.45); color: #f3e8ff; text-transform: uppercase;">🎵 Audio Follow</span>` : ""}
            </div>
            <div style="font-size: 0.73rem; color: var(--otis-text-muted, #94a3b8); margin-top: 2px;">
              ${actionSummary ? `${this._escapeHtml(actionSummary)} • ` : ""}${audioActive ? `🎵 Audio following to ${this._escapeHtml(audioTarget)} • ` : ""}Auto-rollback in ${minsLeft}m if vacant.
            </div>
          </div>
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          ${audioActive ? `
            <button type="button" class="btn-disable-audio-follow subview-chip" title="Disable Spatial Audio Follow-Me" style="background: rgba(168, 85, 247, 0.2); border: 1px solid rgba(168, 85, 247, 0.45); color: #f3e8ff; font-weight: 600; padding: 4px 10px; font-size: 0.74rem; cursor: pointer; border-radius: 6px; white-space: nowrap;">
              🔇 Disable Follow
            </button>
          ` : ""}
          <button type="button" class="btn-cancel-preconditioning subview-chip" data-macro-id="${macroId}" style="background: rgba(239, 68, 68, 0.2); border: 1px solid rgba(239, 68, 68, 0.45); color: #fca5a5; font-weight: 600; padding: 4px 10px; font-size: 0.74rem; cursor: pointer; border-radius: 6px; white-space: nowrap;">
            ✕ Cancel
          </button>
        </div>
      </div>
    `;
  }

  _bindEvents() {
    const root = this.shadowRoot;

    // Header Action buttons
    root.querySelectorAll("#refresh-btn").forEach((btn) => {
      btn.onclick = () => this._fetchData();
    });
    root.querySelectorAll(".btn-repeat-alert-voice").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const msg = this._hass?.states?.["sensor.otis_perimeter_sentinel"]?.attributes?.last_voice_announcement;
          if (msg) {
            this._showToast("📢 Re-announcing visual alert...");
            await this._hass.callService("otis_ai", "announce_visual_alert", {
              message: msg,
              force: true,
            });
            this._showToast("✨ Voice announcement dispatched!");
          }
        } catch (err) {
          this._showToast("Failed to re-announce: " + (err.message || err), true);
        }
      };
    });
    root.querySelectorAll("#btn-open-rules").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this._rulesDraft = { ...(this._userRules || {}) };
        if (this._userRules?.wizard_state && typeof this._userRules.wizard_state === "object") {
          this._wizardState = { ...this._wizardState, ...this._userRules.wizard_state };
        }
        this._rulesModalOpen = true;
        OTIS_ACTIVE_RULES_STATE.isOpen = true;
        OTIS_ACTIVE_RULES_STATE.activeTab = this._rulesActiveTab;
        OTIS_ACTIVE_RULES_STATE.draft = this._rulesDraft;
        OTIS_ACTIVE_RULES_STATE.wizardState = this._wizardState;
        this._render();
      };
    });
    root.querySelectorAll("#btn-open-themes").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this._themeModalOpen = true;
        this._render();
      };
    });

    // Weather & Calendar Glance Chips
    const glanceWeather = root.querySelector("#glance-weather");
    if (glanceWeather) {
      glanceWeather.onclick = () => {
        const eid = glanceWeather.getAttribute("data-entity-id");
        if (eid) {
          const event = new CustomEvent("hass-more-info", {
            detail: { entityId: eid },
            bubbles: true,
            composed: true,
          });
          this.dispatchEvent(event);
        }
      };
    }
    const glanceCalendar = root.querySelector("#glance-calendar");
    if (glanceCalendar) {
      glanceCalendar.onclick = () => {
        const eid = glanceCalendar.getAttribute("data-entity-id");
        if (eid) {
          const event = new CustomEvent("hass-more-info", {
            detail: { entityId: eid },
            bubbles: true,
            composed: true,
          });
          this.dispatchEvent(event);
        }
      };
    }

    // Autonomous Commissioning & Multi-Node Federation Tab Buttons
    const autoCommBtn = root.querySelector("#btn-auto-commission-tab");
    if (autoCommBtn) {
      autoCommBtn.onclick = async (e) => {
        e.stopPropagation();
        try {
          this._showToast("🏠 Commissioning unassigned entities into rooms...");
          const res = await this._hass.callService("otis_ai", "auto_commission_entities", { min_confidence: 0.85 });
          this._showToast(res?.message || "✨ Autonomous commissioning complete!");
          await this._fetchData();
        } catch (err) {
          console.error("Auto commissioning failed:", err);
          this._showToast(`Commissioning failed: ${err.message || err}`, true);
        }
      };
    }

    const syncFedBtn = root.querySelector("#btn-sync-federation-tab");
    if (syncFedBtn) {
      syncFedBtn.onclick = async (e) => {
        e.stopPropagation();
        try {
          this._showToast("🌐 Syncing all federated edge nodes...");
          await this._hass.callService("otis_ai", "sync_federated_nodes", {});
          this._showToast("✨ Edge nodes synchronized!");
          await this._fetchData();
        } catch (err) {
          console.error("Federation sync failed:", err);
          this._showToast(`Federation sync failed: ${err.message || err}`, true);
        }
      };
    }

    // Local Edge AI (Ollama) Add-on & Model Control Buttons
    root.querySelectorAll(".btn-ollama-addon-action").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const act = btn.getAttribute("data-ollama-action") || "status";
        if (act === "install" || act === "start" || act === "stop" || act === "restart" || act === "uninstall") {
          window.open("/hassio/addon/local_otis_ollama", "_blank", "noopener,noreferrer");
          this._showToast("Opening Local Otis Ollama in Home Assistant Add-on Store...");
          return;
        }
        const modelSel = root.querySelector("#ollama-model-select");
        const modelVal = modelSel ? modelSel.value : undefined;
        try {
          const actionLabels = {
            status: "🩺 Refreshing Local Edge AI status & hardware telemetry...",
          };
          this._showToast(actionLabels[act] || `Executing ${act} on Local Edge AI...`);
          const res = await this._hass.callService(
            "otis_ai",
            "manage_local_llm_addon",
            { action: act, model: modelVal },
            undefined,
            true,
            true
          );
          const data = res?.response || res || {};
          if (data.status && this._capabilityMap) {
            this._capabilityMap.local_llm = data.status;
          }
          if (data.success === false) {
            this._showToast(data.error || `Ollama action '${act}' failed`, true);
          } else {
            this._showToast(data.message || `✨ Local Edge AI (${act}) complete!`);
          }
          await this._fetchData();
        } catch (err) {
          console.error("Ollama add-on action failed:", err);
          this._showToast(`Local Edge AI action failed: ${err.message || err}`, true);
        }
      };
    });

    const btnOllamaBench = root.querySelector("#btn-ollama-benchmark");
    if (btnOllamaBench) {
      btnOllamaBench.onclick = async (e) => {
        e.stopPropagation();
        const modelSel = root.querySelector("#ollama-model-select");
        const modelVal = modelSel ? modelSel.value : undefined;
        try {
          this._showToast(`⚡ Benchmarking Local Edge AI (${modelVal || "active model"})...`);
          const res = await this._hass.callService(
            "otis_ai",
            "benchmark_local_llm",
            modelVal ? { model: modelVal } : {},
            undefined,
            true,
            true
          );
          const data = res?.response || res || {};
          if (data.success) {
            this._showToast(`⚡ Benchmark: ${data.tokens_per_second} tok/s (TTFT: ${data.ttft_ms}ms) on ${data.model}`);
          } else {
            this._showToast(data.error || "Benchmark failed — ensure Ollama is online", true);
          }
          await this._fetchData();
        } catch (err) {
          this._showToast(`Benchmark failed: ${err.message || err}`, true);
        }
      };
    }

    const btnOllamaSetModel = root.querySelector("#btn-ollama-set-model");
    if (btnOllamaSetModel) {
      btnOllamaSetModel.onclick = async (e) => {
        e.stopPropagation();
        const modelSel = root.querySelector("#ollama-model-select");
        const modelVal = modelSel ? modelSel.value : "";
        if (!modelVal) return;
        try {
          this._showToast(`✓ Setting active Local Edge AI model to ${modelVal}...`);
          const res = await this._hass.callService(
            "otis_ai",
            "manage_local_llm_addon",
            { action: "set_model", model: modelVal },
            undefined,
            true,
            true
          );
          const data = res?.response || res || {};
          if (data.status && this._capabilityMap) {
            this._capabilityMap.local_llm = data.status;
          }
          this._showToast(data.message || `✨ Active model set to ${modelVal}`);
          await this._fetchData();
        } catch (err) {
          this._showToast(`Failed to set model: ${err.message || err}`, true);
        }
      };
    }

    const btnOllamaPullModel = root.querySelector("#btn-ollama-pull-model");
    if (btnOllamaPullModel) {
      btnOllamaPullModel.onclick = async (e) => {
        e.stopPropagation();
        const modelSel = root.querySelector("#ollama-model-select");
        const modelVal = modelSel ? modelSel.value : "";
        if (!modelVal) return;
        try {
          this._showToast(`⬇️ Pulling model '${modelVal}' into Local Edge AI (this may take a few minutes)...`);
          const res = await this._hass.callService(
            "otis_ai",
            "manage_local_llm_addon",
            { action: "pull_model", model: modelVal },
            undefined,
            true,
            true
          );
          const data = res?.response || res || {};
          if (data.status && this._capabilityMap) {
            this._capabilityMap.local_llm = data.status;
          }
          if (data.success === false) {
            this._showToast(data.error || `Failed to pull ${modelVal}`, true);
          } else {
            this._showToast(data.message || `✨ Model ${modelVal} pulled and activated!`);
          }
          await this._fetchData();
        } catch (err) {
          this._showToast(`Failed to pull model: ${err.message || err}`, true);
        }
      };
    }

    const btnOllamaDeleteModel = root.querySelector("#btn-ollama-delete-model");
    if (btnOllamaDeleteModel) {
      btnOllamaDeleteModel.onclick = async (e) => {
        e.stopPropagation();
        const modelSel = root.querySelector("#ollama-model-select");
        const modelVal = modelSel ? modelSel.value : "";
        if (!modelVal) return;
        if (!confirm(`Delete model '${modelVal}' from Local Edge AI storage?`)) return;
        try {
          this._showToast(`🗑️ Deleting model '${modelVal}'...`);
          const res = await this._hass.callService(
            "otis_ai",
            "manage_local_llm_addon",
            { action: "delete_model", model: modelVal },
            undefined,
            true,
            true
          );
          const data = res?.response || res || {};
          if (data.status && this._capabilityMap) {
            this._capabilityMap.local_llm = data.status;
          }
          if (data.success === false) {
            this._showToast(data.error || `Failed to delete ${modelVal}`, true);
          } else {
            this._showToast(data.message || `🗑️ Deleted model ${modelVal}`);
          }
          await this._fetchData();
        } catch (err) {
          this._showToast(`Failed to delete model: ${err.message || err}`, true);
        }
      };
    }

    // Energy Arbitrage Mode Buttons
    root.querySelectorAll(".btn-arbitrage-mode").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const mode = btn.dataset.mode;
        try {
          this._showToast(`⚡ Switching battery arbitrage mode to ${mode.toUpperCase()}...`);
          await this._hass.callService("otis_ai", "optimize_battery_schedule", { mode });
          this._showToast(`✨ Arbitrage mode updated to ${mode.toUpperCase()}!`);
          await this._fetchData();
        } catch (err) {
          console.error("Arbitrage mode update failed:", err);
          this._showToast(`Failed to update arbitrage mode: ${err.message || err}`, true);
        }
      };
    });

    const optArbitrageBtn = root.querySelector("#btn-optimize-arbitrage-tab");
    if (optArbitrageBtn) {
      optArbitrageBtn.onclick = async (e) => {
        e.stopPropagation();
        try {
          this._showToast("⚡ Optimizing 24-hour battery arbitrage schedule...");
          await this._hass.callService("otis_ai", "optimize_battery_schedule", {});
          this._showToast("✨ Battery schedule re-optimized!");
          await this._fetchData();
        } catch (err) {
          console.error("Arbitrage optimization failed:", err);
          this._showToast(`Arbitrage optimization failed: ${err.message || err}`, true);
        }
      };
    }

    const dispatchArbitrageBtn = root.querySelector("#btn-dispatch-arbitrage-tab");
    if (dispatchArbitrageBtn) {
      dispatchArbitrageBtn.onclick = async (e) => {
        e.stopPropagation();
        try {
          this._showToast("⚡ Dispatching arbitrage and smart EV controls...");
          await this._hass.callService("otis_ai", "execute_energy_arbitrage", { dry_run: false });
          this._showToast("✨ Arbitrage & EV dispatch applied!");
          await this._fetchData();
        } catch (err) {
          console.error("Arbitrage dispatch failed:", err);
          this._showToast(`Failed to dispatch arbitrage: ${err.message || err}`, true);
        }
      };
    }

    // Subview Launchpad
    root.querySelectorAll(".subview-chip").forEach((chip) => {
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
      if (chip.id === "btn-regenerate-dashboards") {
        chip.onclick = async (e) => {
          e.stopPropagation();
          try {
            this._showToast("⚡ Regenerating Command Center, Studios & Rooms...");
            await this._hass.callService("otis_ai", "regenerate_dashboards", {});
            this._showToast("✨ Command Center, Studios & Rooms regenerated successfully!");
            await this._fetchData();
          } catch (err) {
            console.error("Failed to regenerate dashboards:", err);
            this._showToast(`Failed to regenerate dashboards: ${err.message || err}`, true);
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

    // Onboarding Banner Controls
    const btnStartOnboard = root.querySelector("#btn-start-onboarding");
    if (btnStartOnboard) {
      btnStartOnboard.onclick = () => {
        this._rulesDraft = { ...(this._userRules || {}) };
        this._rulesModalOpen = true;
        this._rulesActiveTab = "dashboard";
        OTIS_ACTIVE_RULES_STATE.isOpen = true;
        OTIS_ACTIVE_RULES_STATE.activeTab = "dashboard";
        OTIS_ACTIVE_RULES_STATE.draft = this._rulesDraft;
        OTIS_ACTIVE_RULES_STATE.wizardState = this._wizardState;
        this._render();
      };
    }
    const btnDismissOnboard = root.querySelector("#btn-dismiss-onboarding");
    if (btnDismissOnboard) {
      btnDismissOnboard.onclick = () => {
        this._onboardingDismissed = true;
        this._render();
      };
    }

    // Spatial Migration Pre-Conditioning Cancel Button
    root.querySelectorAll(".btn-cancel-preconditioning").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const macroId = btn.getAttribute("data-macro-id");
        try {
          this._showToast("↺ Cancelling pre-conditioning & restoring states...");
          await this._hass.callService("otis_ai", "cancel_preconditioning", { macro_id: macroId || undefined });
          this._showToast("✨ Pre-conditioning cancelled. States restored.");
        } catch (err) {
          console.warn("Could not cancel pre-conditioning via cancel_preconditioning, attempting rollback_macro:", err);
          try {
            await this._hass.callService("otis_ai", "rollback_macro", { macro_id: macroId || undefined });
            this._showToast("✨ Pre-conditioning macro rolled back successfully.");
          } catch (err2) {
            console.error("Rollback failed:", err2);
            this._showToast("⚠️ Could not roll back macro: " + err2.message);
          }
        }
      };
    });

    // Disable Audio Follow Button
    root.querySelectorAll(".btn-disable-audio-follow").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        try {
          this._showToast("🔇 Disabling audio follow-me...");
          await this._hass.callService("otis_ai", "toggle_audio_follow", { enabled: false });
          this._showToast("✨ Audio follow-me disabled.");
          await this._fetchData();
        } catch (err) {
          console.error("Disable audio follow failed:", err);
          this._showToast("⚠️ Could not disable audio follow: " + (err.message || err));
        }
      };
    });

    // Rules Modal Controls & Navigation
    if (this._rulesModalOpen) {
      const closeRules = () => {
        this._rulesModalOpen = false;
        OTIS_ACTIVE_RULES_STATE.isOpen = false;
        OTIS_ACTIVE_RULES_STATE.draft = null;
        this._render();
      };
      const rulesCloseBtn = root.querySelector("#rules-modal-close-btn");
      if (rulesCloseBtn) rulesCloseBtn.onclick = closeRules;
      const rulesCancelBtn = root.querySelector("#rules-btn-cancel");
      if (rulesCancelBtn) rulesCancelBtn.onclick = closeRules;
      const rulesBackdrop = root.querySelector("#rules-modal-backdrop");
      if (rulesBackdrop) {
        rulesBackdrop.onclick = (e) => {
          if (e.target === rulesBackdrop) closeRules();
        };
        rulesBackdrop.addEventListener("input", () => {
          _harvestAllInputs();
        });
        rulesBackdrop.addEventListener("change", () => {
          _harvestAllInputs();
        });
      }

      // Rules Tab Switching & Input Harvesters
      const _harvestWizardInputs = () => {
        const w = { ...(this._wizardState || {}) };
        const resInput = root.querySelector("#wiz-residents");
        if (resInput) w.residents = resInput.value.trim();
        const workInput = root.querySelector("#wiz-work");
        if (workInput) w.workHours = workInput.value.trim();
        const sleepInput = root.querySelector("#wiz-sleep");
        if (sleepInput) w.sleepHabits = sleepInput.value.trim();

        const codeInput = root.querySelector("#wiz-guest-code");
        if (codeInput) w.guestLockCode = codeInput.value.trim();
        const offInput = root.querySelector("#wiz-guest-off");
        if (offInput) w.guestDelayedOff = offInput.value.trim();
        const guestClimate = root.querySelector("#wiz-guest-climate");
        if (guestClimate) w.guestClimateComfort = guestClimate.checked;
        const guestHoliday = root.querySelector("#wiz-guest-holiday");
        if (guestHoliday) w.holidaySwitches = guestHoliday.checked;

        const deadboltConfirm = root.querySelector("#wiz-deadbolt-confirm");
        if (deadboltConfirm) w.requireDeadboltConfirm = deadboltConfirm.checked;
        const alarmConfirm = root.querySelector("#wiz-alarm-confirm");
        if (alarmConfirm) w.requireAlarmConfirm = alarmConfirm.checked;
        const garageMins = root.querySelector("#wiz-garage-mins");
        if (garageMins) w.garageAlertMinutes = parseInt(garageMins.value, 10) || 15;
        const perimAlerts = root.querySelector("#wiz-perimeter-alerts");
        if (perimAlerts) w.perimeterCameraAlerts = perimAlerts.checked;

        const matrixRouting = root.querySelector("#wiz-matrix-routing");
        if (matrixRouting) w.matrixRouting = matrixRouting.checked;
        const voiceDucking = root.querySelector("#wiz-voice-ducking");
        if (voiceDucking) w.voiceDucking = voiceDucking.checked;
        const quietStart = root.querySelector("#wiz-quiet-start");
        if (quietStart) w.quietHoursStart = quietStart.value;
        const quietEnd = root.querySelector("#wiz-quiet-end");
        if (quietEnd) w.quietHoursEnd = quietEnd.value;
        const quietVol = root.querySelector("#wiz-quiet-vol");
        if (quietVol) w.quietVolume = parseInt(quietVol.value, 10) || 25;

        this._wizardState = w;
        return w;
      };

      const _harvestAllInputs = () => {
        _harvestWizardInputs();

        const focusSelect = root.querySelector("#rules-input-content-focus");
        const toneSelect = root.querySelector("#rules-input-tone");
        const lengthSelect = root.querySelector("#rules-input-length");
        const instArea = root.querySelector("#rules-input-instructions");
        const quietToggle = root.querySelector("#rules-input-quiet-enabled");
        const quietStart = root.querySelector("#rules-input-quiet-start");
        const quietEnd = root.querySelector("#rules-input-quiet-end");
        const quietVol = root.querySelector("#rules-input-quiet-vol");
        const speakerInput = root.querySelector("#rules-input-speaker");
        const showIgnoredCheck = root.querySelector("#rules-input-show-ignored");
        const audioFollowToggle = root.querySelector("#rules-input-audio-follow-enabled");
        const voiceAnnouncementsToggle = root.querySelector("#rules-input-voice-announcements-enabled");
        const voiceFilterToggle = root.querySelector("#rules-input-voice-filter-passersby");
        const presenceCardsToggle = root.querySelector("#rules-input-presence-room-cards");
        const timeoutInput = root.querySelector("#rules-input-reasoning-timeout");

        const draft = { ...(this._rulesDraft || {}) };
        if (focusSelect) draft.primary_content_focus = focusSelect.value;
        if (toneSelect) draft.tone = toneSelect.value;
        if (lengthSelect) draft.response_length = lengthSelect.value;
        if (instArea) draft.custom_instructions = instArea.value;
        if (quietToggle) draft.quiet_hours_enabled = quietToggle.checked;
        if (quietStart) draft.quiet_hours_start = quietStart.value;
        if (quietEnd) draft.quiet_hours_end = quietEnd.value;
        if (quietVol) draft.quiet_hours_volume = parseInt(quietVol.value, 10);
        if (speakerInput) draft.preferred_speaker = speakerInput.value.trim();
        if (audioFollowToggle) draft.audio_follow_enabled = audioFollowToggle.checked;
        if (voiceAnnouncementsToggle) draft.voice_announcements_enabled = voiceAnnouncementsToggle.checked;
        if (voiceFilterToggle) draft.voice_filter_passersby = voiceFilterToggle.checked;
        if (presenceCardsToggle) draft.presence_room_cards = presenceCardsToggle.checked;
        if (showIgnoredCheck) draft.show_ignored_recommendations = showIgnoredCheck.checked;
        if (timeoutInput && timeoutInput.value) draft.reasoning_timeout = parseInt(timeoutInput.value, 10);

        const mappingSelects = root.querySelectorAll(".rules-media-mapping-select");
        if (mappingSelects.length > 0) {
          const mappings = { ...(draft.media_input_mappings || {}) };
          mappingSelects.forEach((sel) => {
            const inpName = sel.getAttribute("data-input-name");
            if (inpName) {
              if (sel.value) {
                mappings[inpName] = sel.value;
              } else {
                delete mappings[inpName];
              }
            }
          });
          draft.media_input_mappings = mappings;
        }
        const mediaUnjoinInput = root.querySelector("#rules-input-media-unjoin");
        if (mediaUnjoinInput) {
          draft.media_unjoin_input = mediaUnjoinInput.value.trim() || "None";
        }
        const mediaDefaultZone = root.querySelector("#rules-input-media-default-zone");
        if (mediaDefaultZone) {
          draft.media_default_zone = mediaDefaultZone.value.trim();
        }

        // If wizard state has any values and instructions are empty or wizard active, synthesize instructions
        const w = this._wizardState || {};
        const hasWizardContent = Boolean(w.residents || w.workHours || w.sleepHabits || w.guestLockCode);
        if (hasWizardContent) {
          const generated = this._generateStructuredRulesText();
          if (generated && (!draft.custom_instructions || this._rulesActiveTab === "wizard")) {
            draft.custom_instructions = generated;
          }
          if (w.requireDeadboltConfirm !== undefined) draft.require_lock_confirmation = w.requireDeadboltConfirm !== false;
          if (w.requireAlarmConfirm !== undefined) draft.require_security_confirmation = w.requireAlarmConfirm !== false;
          if (w.quietHoursStart) draft.quiet_hours_start = w.quietHoursStart;
          if (w.quietHoursEnd) draft.quiet_hours_end = w.quietHoursEnd;
          if (w.quietVolume !== undefined) draft.quiet_hours_volume = w.quietVolume;
        }

        draft.wizard_state = { ...(this._wizardState || {}) };
        draft.person_profiles = { ...(this._userRules?.person_profiles || {}) };
        this._rulesDraft = draft;
        return draft;
      };

      ["wizard", "dashboard", "persona", "safety", "voice", "people", "instructions"].forEach((tab) => {
        const tabBtn = root.querySelector(`#rules-tab-${tab}`);
        if (tabBtn) {
          tabBtn.onclick = () => {
            _harvestAllInputs();
            this._rulesActiveTab = tab;
            this._render();
          };
        }
      });

      // Wizard Stepper Controls
      const launchWizBtn = root.querySelector("#btn-launch-rules-wizard");
      if (launchWizBtn) {
        launchWizBtn.onclick = () => {
          this._rulesActiveTab = "wizard";
          this._wizardStep = 1;
          this._render();
        };
      }

      root.querySelectorAll(".wizard-step-pill[data-step-nav]").forEach((pill) => {
        pill.onclick = () => {
          _harvestWizardInputs();
          const targetStep = parseInt(pill.getAttribute("data-step-nav"), 10);
          if (targetStep >= 1 && targetStep <= 5) {
            this._wizardStep = targetStep;
            this._render();
          }
        };
      });

      const wizPrevBtn = root.querySelector("#wiz-btn-prev");
      if (wizPrevBtn) {
        wizPrevBtn.onclick = () => {
          _harvestWizardInputs();
          if (this._wizardStep > 1) {
            this._wizardStep--;
            this._render();
          }
        };
      }

      const wizNextBtn = root.querySelector("#wiz-btn-next");
      if (wizNextBtn) {
        wizNextBtn.onclick = () => {
          _harvestWizardInputs();
          if (this._wizardStep < 5) {
            this._wizardStep++;
            this._render();
          }
        };
      }

      const wizVolInput = root.querySelector("#wiz-quiet-vol");
      const wizVolLabel = root.querySelector("#wiz-vol-label");
      if (wizVolInput && wizVolLabel) {
        wizVolInput.oninput = () => {
          wizVolLabel.textContent = `${wizVolInput.value}%`;
          this._wizardState = { ...(this._wizardState || {}), quietVolume: parseInt(wizVolInput.value, 10) };
        };
      }

      const wizCopyBtn = root.querySelector("#wiz-btn-copy-instructions");
      if (wizCopyBtn) {
        wizCopyBtn.onclick = () => {
          _harvestWizardInputs();
          const generated = this._generateStructuredRulesText();
          this._rulesDraft = { ...(this._rulesDraft || {}), custom_instructions: generated };
          this._rulesActiveTab = "instructions";
          this._showToast("📋 Inserted wizard rules into Custom Instructions");
          this._render();
        };
      }

      const wizApplySaveBtn = root.querySelector("#wiz-btn-apply-save");
      if (wizApplySaveBtn) {
        wizApplySaveBtn.onclick = async () => {
          if (this._savingRules) return;
          // Harvest latest input values directly from DOM before setting saving flag & re-rendering
          _harvestWizardInputs();
          const generated = this._generateStructuredRulesText();
          const w = { ...(this._wizardState || {}) };

          this._savingRules = true;
          this._render();
          try {
            const draft = {
              ...(this._rulesDraft || {}),
              custom_instructions: generated,
              wizard_state: w,
              require_lock_confirmation: w.requireDeadboltConfirm !== false,
              require_security_confirmation: w.requireAlarmConfirm !== false,
              quiet_hours_enabled: true,
              quiet_hours_start: w.quietHoursStart || "22:00",
              quiet_hours_end: w.quietHoursEnd || "07:00",
              quiet_hours_volume: w.quietVolume !== undefined ? w.quietVolume : 25,
              onboarding_completed: true,
            };

            this._showToast("⚙️ Saving wizard rules & updating preferences...");
            const res = await this._hass.callService("otis_ai", "set_user_rules", { rules: draft });
            const saved = res?.rules || draft;
            this._userRules = saved;
            this._rulesDraft = { ...saved };
            this._rulesModalOpen = false;
            OTIS_ACTIVE_RULES_STATE.isOpen = false;
            OTIS_ACTIVE_RULES_STATE.draft = null;

            this._showToast("✨ Household Rules wizard preferences saved & applied!");
            await this._fetchData();
          } catch (err) {
            console.error("Failed to save wizard rules:", err);
            this._showToast(`Failed to save rules: ${err.message || err}`, true);
          } finally {
            this._savingRules = false;
            this._render();
          }
        };
      }

      // Dashboard Layout & Style Selection Cards
      root.querySelectorAll(".persona-card[data-dashboard-layout]").forEach((card) => {
        card.onclick = () => {
          const l = card.getAttribute("data-dashboard-layout");
          if (l) {
            this._rulesDraft = { ...(this._rulesDraft || {}), dashboard_layout: l };
            this._render();
          }
        };
      });

      root.querySelectorAll(".persona-card[data-navigation-style]").forEach((card) => {
        card.onclick = () => {
          const n = card.getAttribute("data-navigation-style");
          if (n) {
            this._rulesDraft = { ...(this._rulesDraft || {}), navigation_style: n };
            this._render();
          }
        };
      });

      root.querySelectorAll(".persona-card[data-calendar-view]").forEach((card) => {
        card.onclick = () => {
          const c = card.getAttribute("data-calendar-view");
          if (c) {
            this._rulesDraft = { ...(this._rulesDraft || {}), calendar_view: c };
            this._render();
          }
        };
      });

      const focusSelect = root.querySelector("#rules-input-content-focus");
      if (focusSelect) {
        focusSelect.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), primary_content_focus: focusSelect.value };
        };
      }

      // Persona Selection Cards
      root.querySelectorAll(".persona-card[data-persona-id]").forEach((card) => {
        card.onclick = () => {
          const pid = card.getAttribute("data-persona-id");
          if (pid) {
            this._rulesDraft = { ...(this._rulesDraft || {}), persona: pid };
            this._render();
          }
        };
      });

      // Tone & Length Dropdowns
      const toneSelect = root.querySelector("#rules-input-tone");
      if (toneSelect) {
        toneSelect.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), tone: toneSelect.value };
        };
      }
      const lengthSelect = root.querySelector("#rules-input-length");
      if (lengthSelect) {
        lengthSelect.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), response_length: lengthSelect.value };
        };
      }

      // Autonomy Tier Cards
      root.querySelectorAll(".persona-card[data-autonomy-tier]").forEach((card) => {
        card.onclick = () => {
          const tier = card.getAttribute("data-autonomy-tier");
          if (tier) {
            this._rulesDraft = { ...(this._rulesDraft || {}), autonomy_level: tier };
            this._render();
          }
        };
      });

      // Confirmation Toggles
      const lockToggle = root.querySelector("#rules-input-lock-confirm");
      if (lockToggle) {
        lockToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), require_lock_confirmation: lockToggle.checked };
        };
      }
      const secToggle = root.querySelector("#rules-input-sec-confirm");
      if (secToggle) {
        secToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), require_security_confirmation: secToggle.checked };
        };
      }

      // Audio Follow Toggle
      const audioFollowToggle = root.querySelector("#rules-input-audio-follow-enabled");
      if (audioFollowToggle) {
        audioFollowToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), audio_follow_enabled: audioFollowToggle.checked };
        };
      }

      // Voice Announcements Toggles
      const voiceAnnouncementsToggle = root.querySelector("#rules-input-voice-announcements-enabled");
      if (voiceAnnouncementsToggle) {
        voiceAnnouncementsToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), voice_announcements_enabled: voiceAnnouncementsToggle.checked };
        };
      }
      const voiceFilterToggle = root.querySelector("#rules-input-voice-filter-passersby");
      if (voiceFilterToggle) {
        voiceFilterToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), voice_filter_passersby: voiceFilterToggle.checked };
        };
      }

      // Presence Room Cards Toggle
      const presenceCardsToggle = root.querySelector("#rules-input-presence-room-cards");
      if (presenceCardsToggle) {
        presenceCardsToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), presence_room_cards: presenceCardsToggle.checked };
        };
      }

      // Quiet Hours Controls
      const quietToggle = root.querySelector("#rules-input-quiet-enabled");
      if (quietToggle) {
        quietToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), quiet_hours_enabled: quietToggle.checked };
        };
      }
      const quietStart = root.querySelector("#rules-input-quiet-start");
      if (quietStart) {
        quietStart.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), quiet_hours_start: quietStart.value };
        };
      }
      const quietEnd = root.querySelector("#rules-input-quiet-end");
      if (quietEnd) {
        quietEnd.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), quiet_hours_end: quietEnd.value };
        };
      }
      const quietVol = root.querySelector("#rules-input-quiet-vol");
      const volVal = root.querySelector("#rules-vol-val");
      if (quietVol) {
        quietVol.oninput = () => {
          if (volVal) volVal.textContent = `${quietVol.value}%`;
          this._rulesDraft = { ...(this._rulesDraft || {}), quiet_hours_volume: parseInt(quietVol.value, 10) };
        };
      }
      const speakerInput = root.querySelector("#rules-input-speaker");
      if (speakerInput) {
        speakerInput.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), preferred_speaker: speakerInput.value.trim() };
        };
      }

      // Custom Instructions Textarea
      const instArea = root.querySelector("#rules-input-instructions");
      if (instArea) {
        instArea.oninput = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), custom_instructions: instArea.value };
        };
      }

      const showIgnoredToggle = root.querySelector("#rules-input-show-ignored");
      if (showIgnoredToggle) {
        showIgnoredToggle.onchange = () => {
          this._rulesDraft = { ...(this._rulesDraft || {}), show_ignored_recommendations: showIgnoredToggle.checked };
        };
      }

      const resetDismissedBtn = root.querySelector("#rules-btn-reset-dismissed");
      if (resetDismissedBtn) {
        resetDismissedBtn.onclick = async () => {
          await this._resetDismissedSuggestions();
          this._rulesDraft = { ...(this._rulesDraft || {}), dismissed_recommendation_ids: [] };
          this._render();
        };
      }

      const rulesRegenBtn = root.querySelector("#rules-btn-regenerate-dashboards");
      if (rulesRegenBtn) {
        rulesRegenBtn.onclick = async () => {
          try {
            this._showToast("⚡ Regenerating Command Center, Studios & Rooms...");
            await this._hass.callService("otis_ai", "regenerate_dashboards", {});
            this._showToast("✨ Command Center, Studios & Rooms regenerated successfully!");
            await this._fetchData();
          } catch (err) {
            console.error("Failed to regenerate dashboards:", err);
            this._showToast(`Failed to regenerate dashboards: ${err.message || err}`, true);
          }
        };
      }

      // Wizard resident chips
      root.querySelectorAll(".wiz-resident-chip").forEach((chip) => {
        chip.onclick = () => {
          const uName = chip.getAttribute("data-user-name");
          if (!uName) return;
          const curRes = (this._wizardState?.residents || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
          const idx = curRes.findIndex((r) => r.toLowerCase() === uName.toLowerCase());
          if (idx >= 0) {
            curRes.splice(idx, 1);
          } else {
            curRes.push(uName);
          }
          const updated = curRes.join(", ");
          this._wizardState = { ...(this._wizardState || {}), residents: updated };
          const resInput = root.querySelector("#wiz-residents");
          if (resInput) resInput.value = updated;
          chip.classList.toggle("active", idx < 0);
          chip.innerHTML = `${idx < 0 ? "✓ " : "+ "}👤 ${this._escapeHtml(uName)}`;
          if (idx < 0) {
            chip.style.background = "var(--otis-primary)";
            chip.style.color = "#fff";
            chip.style.borderColor = "var(--otis-primary)";
          } else {
            chip.style.background = "";
            chip.style.color = "";
            chip.style.borderColor = "";
          }
        };
      });

      // Real-time input synchronization for Wizard text fields
      const resInp = root.querySelector("#wiz-residents");
      if (resInp) {
        resInp.oninput = () => {
          this._wizardState = { ...(this._wizardState || {}), residents: resInp.value };
        };
      }
      const workInp = root.querySelector("#wiz-work");
      if (workInp) {
        workInp.oninput = () => {
          this._wizardState = { ...(this._wizardState || {}), workHours: workInp.value };
        };
      }
      const sleepInp = root.querySelector("#wiz-sleep");
      if (sleepInp) {
        sleepInp.oninput = () => {
          this._wizardState = { ...(this._wizardState || {}), sleepHabits: sleepInp.value };
        };
      }
      const codeInp = root.querySelector("#wiz-guest-code");
      if (codeInp) {
        codeInp.oninput = () => {
          this._wizardState = { ...(this._wizardState || {}), guestLockCode: codeInp.value };
        };
      }

      // People & Pets Classification Dropdown
      root.querySelectorAll(".profile-type-select").forEach((sel) => {
        sel.onchange = async () => {
          const pid = sel.getAttribute("data-person-id");
          if (!pid || !this._hass) return;
          try {
            await this._hass.callService("otis_ai", "update_person_profile", {
              person_id: pid,
              entity_type: sel.value,
            });
            this._showToast(`Updated classification for ${pid}`);
            await this._fetchData();
          } catch (err) {
            this._showToast(`Failed to update profile: ${err.message || err}`, true);
          }
        };
      });

      // People & Pets Training Toggle
      root.querySelectorAll(".profile-training-toggle").forEach((chk) => {
        chk.onchange = async () => {
          const pid = chk.getAttribute("data-person-id");
          if (!pid || !this._hass) return;
          try {
            await this._hass.callService("otis_ai", "update_person_profile", {
              person_id: pid,
              training_enabled: chk.checked,
            });
            this._showToast(`Recognition training ${chk.checked ? "enabled" : "disabled"} for ${pid}`);
            await this._fetchData();
          } catch (err) {
            this._showToast(`Failed to update training: ${err.message || err}`, true);
          }
        };
      });

      // Save Rules Button
      const saveBtn = root.querySelector("#rules-btn-save");
      if (saveBtn) {
        saveBtn.onclick = async () => {
          if (this._savingRules) return;
          // Harvest latest input values directly from DOM before constructing payload and before re-rendering
          const draft = _harvestAllInputs();
          this._savingRules = true;
          this._render();
          try {
            const payload = {
              ...draft,
              wizard_state: { ...(this._wizardState || {}) },
              onboarding_completed: true,
            };
            this._showToast("⚙️ Saving preferences...");
            const res = await this._hass.callService("otis_ai", "set_user_rules", { rules: payload });
            const saved = res?.rules || payload;
            this._userRules = saved;
            this._rulesDraft = { ...saved };
            this._rulesModalOpen = false;
            OTIS_ACTIVE_RULES_STATE.isOpen = false;
            OTIS_ACTIVE_RULES_STATE.draft = null;

            this._showToast("✨ Preferences saved!");
            await this._fetchData();
          } catch (err) {
            console.error("Failed to save user rules:", err);
            this._showToast(`Failed to save rules: ${err.message || err}`, true);
          } finally {
            this._savingRules = false;
            this._render();
          }
        };
      }
    }

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
      themePromptInput.oninput = (e) => {
        this._draftThemePrompt = e.target.value;
      };
      btnGenThemeAi.onclick = () => {
        const p = (this._draftThemePrompt || themePromptInput.value).trim();
        if (p) {
          this._generateThemeAi(p);
        } else {
          this._showToast("Please enter or speak a theme styling prompt", true);
        }
      };
      themePromptInput.onkeydown = (e) => {
        if (e.key === "Enter") {
          const p = (this._draftThemePrompt || themePromptInput.value).trim();
          if (p) this._generateThemeAi(p);
        }
      };
    }
    const btnThemeVoiceMic = root.querySelector("#btn-theme-voice-mic");
    if (btnThemeVoiceMic) {
      btnThemeVoiceMic.onclick = (e) => {
        if (e) e.preventDefault();
        this._toggleThemeVoiceRecording();
      };
    }

    // Failover Guide Modal Events
    const failoverModal = root.querySelector("#failover-modal-backdrop");
    const failoverClose = root.querySelector("#failover-modal-close-btn");
    const failoverGotIt = root.querySelector("#btn-close-failover-modal");
    const openHaIntegrations = root.querySelector("#btn-open-ha-integrations");

    const closeFailover = () => {
      this._failoverModalOpen = false;
      this._render();
    };

    if (failoverClose) failoverClose.onclick = closeFailover;
    if (failoverGotIt) failoverGotIt.onclick = closeFailover;
    if (failoverModal) {
      failoverModal.onclick = (e) => {
        if (e.target === failoverModal) closeFailover();
      };
    }
    if (openHaIntegrations) {
      openHaIntegrations.onclick = () => {
        closeFailover();
        window.open("/config/integrations", "_blank");
      };
    }

    // Direct Integration Links & URL Copy in Failover Modal
    root.querySelectorAll(".btn-setup-agent, .failover-agent-name").forEach((btn) => {
      btn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const domain = btn.getAttribute("data-domain");
        if (domain) {
          window.open(`/config/integrations/dashboard/add?domain=${encodeURIComponent(domain)}`, "_blank");
        }
      };
    });

    root.querySelectorAll(".btn-copy-base-url").forEach((btn) => {
      btn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const url = btn.getAttribute("data-url");
        if (url) {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(() => {
              this._showToast(`📋 Copied "${url}" to clipboard!`);
            }).catch(() => {
              this._showToast(`Base URL: ${url}`);
            });
          } else {
            this._showToast(`Base URL: ${url}`);
          }
        }
      };
    });

    // Maturity Pills Click Navigation to Proactive Feed
    root.querySelectorAll(".maturity-pill").forEach((pill) => {
      pill.onclick = () => {
        const cat = pill.getAttribute("data-cat");
        this._activeTab = "proactive";
        if (cat === "hygiene" || cat === "spatial") {
          this._feedFilter = "cleanup";
        } else if (cat === "automation") {
          this._feedFilter = "lighting";
        } else if (cat === "security") {
          this._feedFilter = "security";
        } else if (cat === "media") {
          this._feedFilter = "media";
        } else {
          this._feedFilter = "all";
        }
        this._render();
        this._showToast(`Viewing recommendations for ${cat || "smart home"} maturity...`);
      };
    });
    root.querySelectorAll(".btn-apply-theme").forEach((btn) => {
      btn.onclick = () => {
        const k = btn.getAttribute("data-theme-key");
        const isSubview = this._isSubviewMode();
        const isAll = !isSubview && this._themeApplyScope === "all";
        const targetId = isSubview ? this._hass?.user?.id : (isAll ? null : this._themeApplyScope === "specific" ? this._selectedThemeUserId : this._hass?.user?.id);
        if (k) this._applyThemeDirect(k, targetId, isAll);
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
        if (this._themeApplyScope === "specific" && !this._selectedThemeUserId) {
          const avail = this._getAvailableUsers();
          const otherUser = avail.find((u) => u.id !== this._hass?.user?.id) || avail[0];
          if (otherUser) this._selectedThemeUserId = otherUser.id;
        }
        this._render();
      };
    });

    const userSelect = root.querySelector("#theme-user-select");
    if (userSelect) {
      userSelect.onchange = (e) => {
        this._selectedThemeUserId = e.target.value;
      };
    }

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
        this._chatInitialScrolled = false;
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
        if (!this._capabilityMap) {
          this._fetchData();
        }
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
        this._checkAndResumeRegenProgress();
      };
    }

    const tabVision = root.querySelector("#tab-vision");
    if (tabVision) {
      tabVision.onclick = (e) => {
        if (e) e.preventDefault();
        if (this._isListening) this._stopVoiceRecording();
        this._saveActiveTab("vision");
        this._render();
      };
    }

    const tabMedia = root.querySelector("#tab-media");
    if (tabMedia) {
      tabMedia.onclick = (e) => {
        if (e) e.preventDefault();
        if (this._isListening) this._stopVoiceRecording();
        this._saveActiveTab("media");
        this._render();
        this._fetchMediaStudioState();
      };
    }

    // --- Media Studio & Source-to-Zone Router Event Listeners ---
    const btnToggleMappings = root.querySelector("#btn-toggle-media-mappings");
    if (btnToggleMappings) {
      btnToggleMappings.onclick = () => {
        this._showMediaMappingsEditor = !this._showMediaMappingsEditor;
        this._render();
      };
    }

    const btnSaveMappings = root.querySelector("#btn-save-media-mappings");
    if (btnSaveMappings) {
      btnSaveMappings.onclick = async () => {
        const mappings = {};
        root.querySelectorAll(".studio-media-mapping-select").forEach((sel) => {
          const inpName = sel.getAttribute("data-input-name");
          if (inpName && sel.value) {
            mappings[inpName] = sel.value;
          }
        });
        const unjoinVal = root.querySelector("#studio-media-unjoin-input")?.value?.trim() || "None";
        const defaultZoneVal = root.querySelector("#studio-media-default-zone")?.value?.trim() || "";
        this._showToast("💾 Saving Input-to-Player mappings...");
        const res = await this._postMediaStudioAction({
          action: "save_mappings",
          mappings,
          unjoin_input: unjoinVal,
          default_zone: defaultZoneVal,
        });
        if (res && res.success) {
          this._showMediaMappingsEditor = false;
          this._showToast("✨ Input-to-Player mappings saved & synced!");
          await this._fetchData();
        }
      };
    }

    const defaultReturnSelect = root.querySelector("#media-studio-default-return-input");
    if (defaultReturnSelect) {
      defaultReturnSelect.onchange = async (e) => {
        const val = e.target.value || "None";
        const res = await this._postMediaStudioAction({
          action: "save_default_input",
          unjoin_input: val,
        });
        if (res && res.success) {
          if (this._mediaStudioData) this._mediaStudioData.unjoin_input = val;
          if (this._userRules) this._userRules.media_unjoin_input = val;
          this._showToast(`↩️ Default return input set to "${val}"`);
          this._render();
        }
      };
    }

    const mediaZoneSelect = root.querySelector("#media-studio-zone-select");
    if (mediaZoneSelect) {
      mediaZoneSelect.onchange = (e) => {
        const zId = e.target.value;
        this._selectedMediaZoneId = zId;
        const st = this._hass?.states?.[zId];
        const src = st?.attributes?.source || "";
        if (src && src.toLowerCase() !== "none") {
          this._selectedMediaInput = src;
        }
        this._render();
      };
    }

    const mediaInputSelect = root.querySelector("#media-studio-input-select");
    if (mediaInputSelect) {
      mediaInputSelect.onchange = async (e) => {
        const newInput = e.target.value;
        const zId = mediaInputSelect.getAttribute("data-zone-id") || this._selectedMediaZoneId;
        this._selectedMediaInput = newInput;
        if (zId && this._hass) {
          this._mediaOptimisticSources[zId] = newInput;
          this._render();
          try {
            if (newInput.toLowerCase() !== "none") {
              await this._hass.callService("media_player", "turn_on", { entity_id: zId });
            }
            await this._hass.callService("media_player", "select_source", {
              entity_id: zId,
              source: newInput,
            });
            this._showToast(`🔌 Routed "${newInput}" to ${this._hass.states?.[zId]?.attributes?.friendly_name || zId}`);
          } catch (err) {
            this._showToast(`Could not switch source: ${err.message || err}`, true);
          } finally {
            setTimeout(() => {
              delete this._mediaOptimisticSources[zId];
              this._fetchMediaStudioState();
            }, 1500);
          }
        }
      };
    }

    const btnSetDefaultZone = root.querySelector("#btn-media-set-default-zone");
    if (btnSetDefaultZone) {
      btnSetDefaultZone.onclick = async () => {
        const zId = btnSetDefaultZone.getAttribute("data-zone-id");
        if (!zId) return;
        const res = await this._postMediaStudioAction({
          action: "set_default_zone",
          zone_entity_id: zId,
        });
        if (res && res.success) {
          this._showToast("📌 Saved as your default speaker zone!");
        }
      };
    }

    const btnZonePower = root.querySelector("#btn-media-zone-power");
    if (btnZonePower) {
      btnZonePower.onclick = async () => {
        const zId = btnZonePower.getAttribute("data-zone-id");
        const isOn = btnZonePower.getAttribute("data-is-on") === "true";
        if (!zId || !this._hass) return;
        const unjoinInput = this._mediaStudioData?.unjoin_input || this._userRules?.media_unjoin_input || "None";
        try {
          if (isOn) {
            this._mediaOptimisticSources[zId] = unjoinInput;
            this._render();
            try {
              await this._hass.callService("media_player", "select_source", {
                entity_id: zId,
                source: unjoinInput,
              });
            } catch (_) { }
            try {
              await this._hass.callService("media_player", "turn_off", { entity_id: zId });
            } catch (_) { }
            this._showToast(`⏻ Turned off ${this._hass.states?.[zId]?.attributes?.friendly_name || zId}`);
          } else {
            const targetInp = this._selectedMediaInput || "Bridge";
            this._mediaOptimisticSources[zId] = targetInp;
            this._render();
            await this._hass.callService("media_player", "turn_on", { entity_id: zId });
            if (targetInp && targetInp.toLowerCase() !== "none") {
              await this._hass.callService("media_player", "select_source", {
                entity_id: zId,
                source: targetInp,
              });
            }
            this._showToast(`⏻ Turned on ${this._hass.states?.[zId]?.attributes?.friendly_name || zId}`);
          }
        } catch (err) {
          this._showToast(`Zone power toggle failed: ${err.message || err}`, true);
        } finally {
          setTimeout(() => {
            delete this._mediaOptimisticSources[zId];
            this._fetchMediaStudioState();
          }, 1500);
        }
      };
    }

    root.querySelectorAll(".btn-media-transport").forEach((btn) => {
      btn.onclick = async () => {
        const svc = btn.getAttribute("data-transport");
        const playerId = btn.getAttribute("data-player-id");
        if (!svc || !playerId || !this._hass) return;
        try {
          await this._hass.callService("media_player", svc, { entity_id: playerId });
          setTimeout(() => this._fetchMediaStudioState(), 700);
        } catch (err) {
          this._showToast(`Transport command failed: ${err.message || err}`, true);
        }
      };
    });

    const btnBrowsePlayer = root.querySelector("#btn-media-browse-player");
    if (btnBrowsePlayer) {
      btnBrowsePlayer.onclick = () => {
        const playerId = btnBrowsePlayer.getAttribute("data-player-id");
        if (!playerId) return;
        const ev = new CustomEvent("hass-more-info", {
          detail: { entityId: playerId },
          bubbles: true,
          composed: true,
        });
        this.dispatchEvent(ev);
        window.dispatchEvent(ev);
      };
    }

    const btnSaveCurrentTrack = root.querySelector("#btn-media-save-current-track");
    if (btnSaveCurrentTrack) {
      btnSaveCurrentTrack.onclick = () => {
        const title = btnSaveCurrentTrack.getAttribute("data-title") || "";
        const artist = btnSaveCurrentTrack.getAttribute("data-artist") || "";
        const inp = btnSaveCurrentTrack.getAttribute("data-input") || "";
        const cleanTitle = title.replace(/^(?:Ready on|Streaming on)\s+/i, "").trim();
        this._favFormName = cleanTitle && cleanTitle !== "Matrix" ? cleanTitle : "Favorite Station";
        this._favFormInput = inp;
        this._favFormCommand =
          cleanTitle && !cleanTitle.startsWith("Input ")
            ? `play ${cleanTitle}${artist && !artist.includes("(") && !artist.startsWith("Select ") ? ` by ${artist}` : ""}`
            : "";
        this._showAddFavoriteForm = true;
        this._render();
      };
    }

    root.querySelectorAll(".media-zone-vol-slider").forEach((slider) => {
      slider.oninput = (e) => {
        const zId = slider.getAttribute("data-zone-id");
        const pct = parseInt(e.target.value, 10) || 0;
        const lbl = root.querySelector(`.media-vol-label[data-zone-vol-label="${zId}"]`);
        if (lbl) lbl.textContent = `${pct}%`;
      };
      slider.onchange = async (e) => {
        const zId = slider.getAttribute("data-zone-id");
        const pct = parseInt(e.target.value, 10) || 0;
        if (!zId || !this._hass) return;
        const volLevel = Math.max(0, Math.min(1, pct / 100));
        this._mediaOptimisticVolumes[zId] = volLevel;
        try {
          await this._hass.callService("media_player", "volume_set", {
            entity_id: zId,
            volume_level: volLevel,
          });
        } catch (err) {
          this._showToast(`Volume adjustment failed: ${err.message || err}`, true);
        } finally {
          setTimeout(() => {
            delete this._mediaOptimisticVolumes[zId];
          }, 1500);
        }
      };
    });

    root.querySelectorAll(".btn-media-mute-toggle").forEach((btn) => {
      btn.onclick = async () => {
        const zId = btn.getAttribute("data-zone-id");
        const curMuted = btn.getAttribute("data-muted") === "true";
        if (!zId || !this._hass) return;
        const nextMuted = !curMuted;
        this._mediaOptimisticMutes[zId] = nextMuted;
        this._render();
        try {
          await this._hass.callService("media_player", "volume_mute", {
            entity_id: zId,
            is_volume_muted: nextMuted,
          });
        } catch (err) {
          this._showToast(`Mute toggle failed: ${err.message || err}`, true);
        } finally {
          setTimeout(() => {
            delete this._mediaOptimisticMutes[zId];
          }, 1500);
        }
      };
    });

    root.querySelectorAll(".btn-media-link-zone").forEach((btn) => {
      btn.onclick = async () => {
        const zId = btn.getAttribute("data-zone-id");
        const isLinked = btn.getAttribute("data-linked") === "true";
        const targetInp = btn.getAttribute("data-input");
        const unjoinInput = this._mediaStudioData?.unjoin_input || this._userRules?.media_unjoin_input || "None";
        if (!zId || !this._hass) return;
        try {
          if (isLinked) {
            this._mediaOptimisticSources[zId] = unjoinInput;
            this._render();
            const unjoinRes = await this._postMediaStudioAction({
              action: "unjoin_zones",
              zone_entity_ids: [zId],
            });
            if (!unjoinRes || !unjoinRes.success) {
              try {
                await this._hass.callService("media_player", "select_source", {
                  entity_id: zId,
                  source: unjoinInput,
                });
              } catch (_) {
                await this._hass.callService("media_player", "turn_off", { entity_id: zId });
              }
            }
            this._showToast(`Unlinked ${this._hass.states?.[zId]?.attributes?.friendly_name || zId} (returned to ${unjoinInput})`);
          } else if (targetInp) {
            this._mediaOptimisticSources[zId] = targetInp;
            this._render();
            await this._hass.callService("media_player", "turn_on", { entity_id: zId });
            await this._hass.callService("media_player", "select_source", {
              entity_id: zId,
              source: targetInp,
            });
            this._showToast(`🔗 Linked ${this._hass.states?.[zId]?.attributes?.friendly_name || zId} to "${targetInp}"`);
          }
        } catch (err) {
          this._showToast(`Room link toggle failed: ${err.message || err}`, true);
        } finally {
          setTimeout(() => {
            delete this._mediaOptimisticSources[zId];
            this._fetchMediaStudioState();
          }, 1500);
        }
      };
    });

    const btnLinkAll = root.querySelector("#btn-media-link-all");
    if (btnLinkAll) {
      btnLinkAll.onclick = async () => {
        const targetInp = btnLinkAll.getAttribute("data-input");
        const zones = this._mediaStudioData?.zones || this._capabilityMap?.media_topology?.matrix_zones || [];
        if (!targetInp || !this._hass || zones.length === 0) return;
        zones.forEach((z) => {
          this._mediaOptimisticSources[z.entity_id] = targetInp;
        });
        this._render();
        try {
          const eids = zones.map((z) => z.entity_id);
          await this._hass.callService("media_player", "turn_on", { entity_id: eids });
          await this._hass.callService("media_player", "select_source", {
            entity_id: eids,
            source: targetInp,
          });
          this._showToast(`🔗 Linked all ${eids.length} rooms to "${targetInp}"`);
        } catch (err) {
          this._showToast(`Failed to link all rooms: ${err.message || err}`, true);
        } finally {
          setTimeout(() => {
            this._mediaOptimisticSources = {};
            this._fetchMediaStudioState();
          }, 1800);
        }
      };
    }

    const btnUnlinkOthers = root.querySelector("#btn-media-unlink-others");
    if (btnUnlinkOthers) {
      btnUnlinkOthers.onclick = async () => {
        const zones = this._mediaStudioData?.zones || this._capabilityMap?.media_topology?.matrix_zones || [];
        const unjoinInput = this._mediaStudioData?.unjoin_input || this._userRules?.media_unjoin_input || "None";
        const otherEids = zones
          .map((z) => z.entity_id)
          .filter((id) => id && id !== this._selectedMediaZoneId);
        if (otherEids.length === 0 || !this._hass) return;
        otherEids.forEach((id) => {
          this._mediaOptimisticSources[id] = unjoinInput;
        });
        this._render();
        try {
          const unjoinRes = await this._postMediaStudioAction({
            action: "unjoin_zones",
            zone_entity_ids: otherEids,
          });
          if (!unjoinRes || !unjoinRes.success) {
            await this._hass.callService("media_player", "select_source", {
              entity_id: otherEids,
              source: unjoinInput,
            });
          }
          this._showToast(`Unlinked all other speaker rooms (returned to ${unjoinInput})`);
        } catch (err) {
          this._showToast(`Failed to unlink rooms: ${err.message || err}`, true);
        } finally {
          setTimeout(() => {
            this._mediaOptimisticSources = {};
            this._fetchMediaStudioState();
          }, 1800);
        }
      };
    }

    const btnToggleAddFav = root.querySelector("#btn-media-toggle-add-fav");
    if (btnToggleAddFav) {
      btnToggleAddFav.onclick = () => {
        this._showAddFavoriteForm = !this._showAddFavoriteForm;
        this._render();
      };
    }

    const btnCancelFav = root.querySelector("#btn-fav-form-cancel");
    if (btnCancelFav) {
      btnCancelFav.onclick = () => {
        this._showAddFavoriteForm = false;
        this._render();
      };
    }

    const favNameInp = root.querySelector("#fav-form-name");
    if (favNameInp) {
      favNameInp.oninput = (e) => {
        this._favFormName = e.target.value;
      };
    }
    const favInputSel = root.querySelector("#fav-form-input");
    if (favInputSel) {
      favInputSel.onchange = (e) => {
        this._favFormInput = e.target.value;
      };
    }
    const favCmdInp = root.querySelector("#fav-form-command");
    if (favCmdInp) {
      favCmdInp.oninput = (e) => {
        this._favFormCommand = e.target.value;
      };
    }
    const favSharedChk = root.querySelector("#fav-form-shared");
    if (favSharedChk) {
      favSharedChk.onchange = (e) => {
        this._favFormShared = e.target.checked;
      };
    }
    const favTypeSel = root.querySelector("#fav-form-type");
    if (favTypeSel) {
      favTypeSel.onchange = (e) => {
        this._favFormType = e.target.value;
      };
    }
    const btnFavChooseLib = root.querySelector("#btn-fav-choose-library");
    if (btnFavChooseLib) {
      btnFavChooseLib.onclick = () => {
        const selInp = root.querySelector("#fav-form-input")?.value || this._favFormInput || activeInput;
        const pId = effectiveMappings[selInp] || btnFavChooseLib.getAttribute("data-player-id") || mappedPlayerId || "";
        const bType = root.querySelector("#fav-form-type")?.value || this._favFormType || "playlist";
        this._favFormName = root.querySelector("#fav-form-name")?.value || this._favFormName;
        this._favFormCommand = root.querySelector("#fav-form-command")?.value || this._favFormCommand;
        this._favFormShared = Boolean(root.querySelector("#fav-form-shared")?.checked ?? this._favFormShared);
        this._favFormInput = selInp;
        this._favFormType = bType;
        this._fetchMediaLibrary(pId, bType);
      };
    }

    root.querySelectorAll(".fav-picker-item").forEach((itemEl) => {
      itemEl.onclick = () => {
        const id = itemEl.getAttribute("data-id");
        const name = itemEl.getAttribute("data-name");
        const type = itemEl.getAttribute("data-type");
        this._favFormName = name || this._favFormName;
        this._favFormCommand = id || this._favFormCommand;
        this._favFormType = type || this._favFormType;
        this._mediaBrowseOpen = false;
        this._render();
        this._showToast(`Selected "${name}"`);
      };
    });

    root.querySelectorAll(".btn-fav-picker-type").forEach((btn) => {
      btn.onclick = () => {
        const t = btn.getAttribute("data-type");
        const selInp = root.querySelector("#fav-form-input")?.value || this._favFormInput || activeInput;
        const pId = effectiveMappings[selInp] || mappedPlayerId || "";
        this._favFormName = root.querySelector("#fav-form-name")?.value || this._favFormName;
        this._favFormCommand = root.querySelector("#fav-form-command")?.value || this._favFormCommand;
        this._favFormShared = Boolean(root.querySelector("#fav-form-shared")?.checked ?? this._favFormShared);
        this._favFormInput = selInp;
        this._favFormType = t;
        this._fetchMediaLibrary(pId, t);
      };
    });

    const btnFavPickerClose = root.querySelector("#btn-fav-picker-close");
    if (btnFavPickerClose) {
      btnFavPickerClose.onclick = () => {
        this._mediaBrowseOpen = false;
        this._render();
      };
    }

    const btnSubmitFav = root.querySelector("#btn-fav-form-submit");
    if (btnSubmitFav) {
      btnSubmitFav.onclick = async () => {
        const name = (root.querySelector("#fav-form-name")?.value || this._favFormName || "").trim();
        const input = (root.querySelector("#fav-form-input")?.value || this._favFormInput || "").trim();
        const command = (root.querySelector("#fav-form-command")?.value || this._favFormCommand || "").trim();
        const media_content_type = (root.querySelector("#fav-form-type")?.value || this._favFormType || "custom").trim();
        const shared = Boolean(root.querySelector("#fav-form-shared")?.checked ?? this._favFormShared);
        if (!name) {
          this._showToast("Please enter a label for your favorite", true);
          return;
        }
        const res = await this._postMediaStudioAction({
          action: "add_favorite",
          name,
          input,
          command,
          media_content_type,
          shared,
        });
        if (res && res.success) {
          this._showAddFavoriteForm = false;
          this._favFormName = "";
          this._favFormCommand = "";
          this._favFormShared = false;
          this._showToast(`⭐ Saved "${name}" to ${shared ? "household" : "your"} favorites!`);
        }
      };
    }

    const btnBrowseClose = root.querySelector("#btn-media-browse-close");
    if (btnBrowseClose) {
      btnBrowseClose.onclick = () => {
        this._mediaBrowseOpen = false;
        this._render();
      };
    }

    root.querySelectorAll(".btn-browse-type").forEach((btn) => {
      btn.onclick = () => {
        const pId = btn.getAttribute("data-player-id") || mappedPlayerId;
        const bType = btn.getAttribute("data-type") || "playlist";
        this._fetchMediaLibrary(pId, bType);
      };
    });

    root.querySelectorAll(".btn-browse-action").forEach((btn) => {
      btn.onclick = () => {
        const pId = btn.getAttribute("data-player-id") || mappedPlayerId;
        const bType = btn.getAttribute("data-type") || "playlist";
        this._fetchMediaLibrary(pId, bType);
      };
    });

    root.querySelectorAll(".btn-play-library-item").forEach((btn) => {
      btn.onclick = async () => {
        const itemId = btn.getAttribute("data-id");
        const itemName = btn.getAttribute("data-name");
        const itemType = btn.getAttribute("data-type");
        const pId = btn.getAttribute("data-player-id");
        const zId = btn.getAttribute("data-zone-id") || this._selectedMediaZoneId;
        const inp = btn.getAttribute("data-input");
        this._showToast(`▶️ Routing & playing "${itemName}" in ${this._hass?.states?.[zId]?.attributes?.friendly_name || zId}...`);
        const res = await this._postMediaStudioAction({
          action: "play_media",
          zone_entity_id: zId,
          player_entity_id: pId,
          media_content_id: itemId,
          media_content_type: itemType,
          input: inp,
        });
        if (res && res.success) {
          if (res.routed_input) {
            this._selectedMediaInput = res.routed_input;
          }
          this._showToast(`🎵 Now playing "${itemName}"!`);
          setTimeout(() => this._fetchMediaStudioState(), 1200);
        } else {
          this._showToast(`Playback failed: ${res?.error || "Unknown error"}`, true);
        }
      };
    });

    root.querySelectorAll(".btn-fav-library-item").forEach((btn) => {
      btn.onclick = () => {
        const itemId = btn.getAttribute("data-id");
        const itemName = btn.getAttribute("data-name");
        const itemType = btn.getAttribute("data-type");
        const inp = btn.getAttribute("data-input");
        this._favFormName = itemName;
        this._favFormInput = inp;
        this._favFormCommand = itemId;
        this._favFormType = itemType;
        this._showAddFavoriteForm = true;
        this._mediaBrowseOpen = false;
        this._render();
      };
    });

    root.querySelectorAll(".btn-media-play-fav").forEach((btn) => {
      btn.onclick = async () => {
        const favId = btn.getAttribute("data-fav-id");
        const zId = btn.getAttribute("data-zone-id") || this._selectedMediaZoneId;
        if (!favId) return;
        this._showToast("▶️ Routing speaker zone & starting favorite...");
        const res = await this._postMediaStudioAction({
          action: "play_favorite",
          favorite_id: favId,
          zone_entity_id: zId,
        });
        if (res && res.success) {
          if (res.routed_input) {
            this._selectedMediaInput = res.routed_input;
          }
          this._showToast(
            `🎵 Playing "${res.favorite?.name || "Favorite"}" on ${this._hass?.states?.[zId]?.attributes?.friendly_name || zId}!`
          );
          setTimeout(() => this._fetchMediaStudioState(), 1200);
        }
      };
    });

    root.querySelectorAll(".btn-media-delete-fav").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const favId = btn.getAttribute("data-fav-id");
        const scope = btn.getAttribute("data-fav-scope") || "user";
        if (!favId) return;
        const res = await this._postMediaStudioAction({
          action: "remove_favorite",
          favorite_id: favId,
          shared: scope === "shared",
        });
        if (res && res.success) {
          this._showToast("🗑️ Removed favorite");
        }
      };
    });

    const refreshVisionBtn = root.querySelector("#btn-refresh-vision");
    if (refreshVisionBtn) {
      refreshVisionBtn.onclick = async () => {
        this._showToast("🔄 Fusing multimodal presence across BLE, mmWave, Thermal & Acoustic sensors...");
        try {
          if (this._hass) {
            await this._hass.callService("otis_ai", "fuse_presence", { force_refresh: true });
          }
        } catch (err) {
          console.debug("Could not trigger fuse_presence:", err);
        }
        await this._fetchData();
        this._showToast("✨ Multimodal presence fused & telemetry updated!");
      };
    }

    root.querySelectorAll(".btn-analyze-camera").forEach((btn) => {
      btn.onclick = async (e) => {
        const camId = e.currentTarget.getAttribute("data-camera");
        if (!camId || this._analyzingCamera) return;
        this._analyzingCamera = camId;
        this._render();
        this._showToast(`🔍 Analyzing snapshot for ${camId}...`);
        try {
          const res = await this._hass.callService("otis_ai", "analyze_camera", {
            camera_entity_id: camId,
          });
          if (res?.audit) {
            this._cameraAudits[camId] = res.audit;
          }
          this._showToast("✨ Gemini Vision analysis complete!");
          await this._fetchData();
        } catch (err) {
          console.error("Camera analysis failed:", err);
          this._showToast(`Camera analysis failed: ${err.message || err}`, true);
        } finally {
          this._analyzingCamera = null;
          this._render();
        }
      };
    });

    root.querySelectorAll(".camera-preview-container").forEach((el) => {
      el.onclick = () => {
        const camId = el.getAttribute("data-cam-id");
        const snapPic = el.getAttribute("data-snapshot-pic");
        if (snapPic) {
          let parsedBbox = null;
          const rawBbox = el.getAttribute("data-snapshot-bbox");
          if (rawBbox) {
            try {
              parsedBbox = JSON.parse(rawBbox);
            } catch (_) { }
          }
          this._snapshotLightbox = {
            pic: snapPic,
            title: el.getAttribute("data-snapshot-title") || "Detection Snapshot",
            bbox: parsedBbox,
            camId: camId || null,
          };
          this._render();
          return;
        }
        if (camId) {
          const ev = new CustomEvent("hass-more-info", {
            detail: { entityId: camId },
            bubbles: true,
            composed: true,
          });
          this.dispatchEvent(ev);
        }
      };
    });

    const lbBackdrop = root.querySelector("#snapshot-lightbox-backdrop");
    if (lbBackdrop) {
      lbBackdrop.onclick = () => {
        this._snapshotLightbox = null;
        this._render();
      };
    }
    const btnCloseLb = root.querySelector("#btn-close-snapshot-lightbox");
    if (btnCloseLb) {
      btnCloseLb.onclick = () => {
        this._snapshotLightbox = null;
        this._render();
      };
    }
    const btnLbMoreInfo = root.querySelector("#btn-lightbox-more-info");
    if (btnLbMoreInfo && this._snapshotLightbox?.camId) {
      const targetCamId = this._snapshotLightbox.camId;
      btnLbMoreInfo.onclick = () => {
        this._snapshotLightbox = null;
        this._render();
        this.dispatchEvent(new CustomEvent("hass-more-info", {
          detail: { entityId: targetCamId },
          bubbles: true,
          composed: true,
        }));
      };
    }

    root.querySelectorAll(".btn-exclude-shed-load").forEach((btn) => {
      btn.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const eid = e.currentTarget.getAttribute("data-entity-id");
        const ename = e.currentTarget.getAttribute("data-entity-name") || eid;
        if (!eid || !this._hass) return;
        try {
          const currentExcluded = Array.isArray(this._userRules?.excluded_load_shed_entities)
            ? [...this._userRules.excluded_load_shed_entities]
            : [];
          if (!currentExcluded.includes(eid.toLowerCase())) {
            currentExcluded.push(eid.toLowerCase());
          }
          await this._hass.callService("otis_ai", "set_user_rules", {
            rules: { excluded_load_shed_entities: currentExcluded },
          });
          this._showToast(`🚫 Excluded ${ename} from load shedding recommendations.`);
          await this._fetchData();
        } catch (err) {
          this._showToast(`Failed to exclude load: ${err.message || err}`, true);
        }
      };
    });

    // Category filter pills
    root.querySelectorAll("[data-category-pill]").forEach((pill) => {
      pill.onclick = (e) => {
        const cat = e.currentTarget.getAttribute("data-category-pill") || "all";
        this._selectedCategory = cat;
        this._render();
      };
    });

    // Session-only Dismiss (✕) buttons — remove from feed without adding to Ignored
    root.querySelectorAll("[data-session-dismiss]").forEach((btn) => {
      btn.onclick = (e) => {
        const id = e.currentTarget.getAttribute("data-session-dismiss");
        this._dismissCardFromFeed(id);
      };
    });

    // Ignore buttons (add to Ignored list)
    root.querySelectorAll("[data-dismiss]").forEach((btn) => {
      btn.onclick = (e) => {
        const id = e.currentTarget.getAttribute("data-dismiss");
        this._dismissSuggestion(id);
      };
    });

    // Restore buttons
    root.querySelectorAll("[data-restore]").forEach((btn) => {
      btn.onclick = (e) => {
        const id = e.currentTarget.getAttribute("data-restore");
        this._restoreSuggestion(id);
      };
    });

    // Toggle Show Ignored button
    const btnToggleShowIgnored = root.querySelector("#btn-toggle-show-ignored");
    if (btnToggleShowIgnored) {
      btnToggleShowIgnored.onclick = () => {
        this._localShowIgnored = !this._localShowIgnored;
        this._render();
      };
    }

    // Reset Ignored button
    const btnResetIgnored = root.querySelector("#btn-reset-ignored");
    if (btnResetIgnored) {
      btnResetIgnored.onclick = () => {
        this._resetDismissedSuggestions();
      };
    }

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

    root.querySelectorAll(".btn-review-suggestion").forEach((btn) => {
      btn.onclick = (e) => {
        const id = e.currentTarget.getAttribute("data-review");
        const suggestion = (this._suggestions || []).find((s) => s.id === id);
        if (suggestion) {
          this._reviewSuggestion = suggestion;
          this._render();
        }
      };
    });

    const closeReviewBtn = root.querySelector("#btn-close-review-modal");
    if (closeReviewBtn) {
      closeReviewBtn.onclick = () => {
        this._reviewSuggestion = null;
        this._snapshotLightbox = null;
        this._render();
      };
    }
    const reviewBackdrop = root.querySelector("#review-suggestion-backdrop");
    if (reviewBackdrop) {
      reviewBackdrop.onclick = (e) => {
        if (e.target === reviewBackdrop) {
          this._reviewSuggestion = null;
          this._snapshotLightbox = null;
          this._render();
        }
      };
    }
    const copyReviewBtn = root.querySelector("#btn-copy-review-yaml");
    if (copyReviewBtn) {
      copyReviewBtn.onclick = () => {
        if (this._reviewSuggestion) {
          this._copyToClipboard(this._formatSuggestionYaml(this._reviewSuggestion), "YAML copied to clipboard!");
        }
      };
    }
    const applyReviewBtn = root.querySelector("#btn-apply-review-modal");
    if (applyReviewBtn) {
      applyReviewBtn.onclick = () => {
        const suggestion = this._reviewSuggestion;
        this._reviewSuggestion = null;
        this._snapshotLightbox = null;
        this._render();
        if (suggestion) {
          this._applySuggestion(suggestion);
        }
      };
    }

    // GitHub Bug Reporter & Issue Tracker
    root.querySelectorAll(".btn-report-github").forEach((btn) => {
      btn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const sid = e.currentTarget.getAttribute("data-suggestion-id");
        const s = (this._suggestions || []).find((item) => item.id === sid);
        if (s && s.action_payload) {
          const payload = s.action_payload;
          this._githubModalData = {
            repo: payload.target_repo || "OtisPresley/otis-ai-companion",
            title: payload.suggested_title || `[Bug Report] ${payload.domain || 'integration'}: Unhandled Exception`,
            body: payload.sanitized_body || "",
            error_id: payload.error_id,
            domain: payload.domain,
          };
          this._githubModalStep = "review";
          this._githubErrorMsg = null;
          this._githubModalOpen = true;
          this._render();
        }
      };
    });

    root.querySelectorAll(".btn-dismiss-tracked-issue").forEach((btn) => {
      btn.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const trackId = e.currentTarget.getAttribute("data-track-id");
        if (!trackId) return;
        try {
          const resp =
            this._hass && typeof this._hass.fetchWithAuth === "function"
              ? await this._hass.fetchWithAuth("/api/otis_ai/issue_reporter", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "dismiss_issue", track_id: trackId }),
              })
              : await fetch("/api/otis_ai/issue_reporter", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "dismiss_issue", track_id: trackId }),
              });
          this._showToast("Dismissed issue tracking from feed");
          await this._fetchData();
        } catch (_) { }
      };
    });

    const closeGhModal = () => {
      if (this._githubPollTimer) {
        clearInterval(this._githubPollTimer);
        this._githubPollTimer = null;
      }
      this._githubModalOpen = false;
      this._reviewSuggestion = null;
      this._snapshotLightbox = null;
      this._githubErrorMsg = null;
      this._render();
    };

    root.querySelectorAll("#btn-cancel-github-modal, #btn-close-gh-modal-header").forEach((btn) => {
      btn.onclick = closeGhModal;
    });

    const ghBackdrop = root.querySelector("#github-modal-backdrop");
    if (ghBackdrop) {
      ghBackdrop.onclick = (e) => {
        if (e.target === ghBackdrop) closeGhModal();
      };
    }

    const btnProceedGhAuth = root.querySelector("#btn-proceed-github-auth");
    if (btnProceedGhAuth) {
      btnProceedGhAuth.onclick = () => {
        const repoInp = root.querySelector("#gh-modal-repo");
        const titleInp = root.querySelector("#gh-modal-title");
        const bodyInp = root.querySelector("#gh-modal-body");
        if (this._githubModalData) {
          if (repoInp && repoInp.value) this._githubModalData.repo = repoInp.value.trim();
          if (titleInp && titleInp.value) this._githubModalData.title = titleInp.value.trim();
          if (bodyInp && bodyInp.value) this._githubModalData.body = bodyInp.value.trim();
        }
        this._startGitHubDeviceFlow();
      };
    }

    const btnCopyGhCode = root.querySelector("#btn-copy-gh-code");
    if (btnCopyGhCode) {
      btnCopyGhCode.onclick = () => {
        const code = this._githubDeviceCode?.user_code;
        if (code && navigator.clipboard) {
          navigator.clipboard.writeText(code).then(() => {
            this._showToast(`📋 Code ${code} copied to clipboard!`);
          });
        }
      };
    }

    const btnRetryGhFlow = root.querySelector("#btn-retry-github-flow");
    if (btnRetryGhFlow) {
      btnRetryGhFlow.onclick = () => this._startGitHubDeviceFlow();
    }

    const btnCloseGhSuccess = root.querySelector("#btn-close-github-success");
    if (btnCloseGhSuccess) {
      btnCloseGhSuccess.onclick = () => {
        this._githubModalOpen = false;
        this._reviewSuggestion = null;
        this._snapshotLightbox = null;
        this._render();
        this._fetchData();
      };
    }

    // Multi-choice Room Entry Identity Verification buttons
    root.querySelectorAll(".btn-verify-room-candidate").forEach((btn) => {
      btn.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const pid = e.currentTarget.getAttribute("data-person-id");
        const label = e.currentTarget.getAttribute("data-person-label");
        const area = e.currentTarget.getAttribute("data-area");
        const areaName = e.currentTarget.getAttribute("data-area-name") || area;
        const sid = e.currentTarget.getAttribute("data-suggestion-id");
        if (!pid || !this._hass) return;
        const isNotPersonPet = pid === "not_person_pet";
        const matchedSugg = sid ? (this._suggestions || []).find((item) => item.id === sid) : null;
        const snapshotKey = matchedSugg?.action_payload?.snapshot_key || null;
        const detImageEid = matchedSugg?.action_payload?.detection_image_entity_id || null;
        try {
          this._showToast(`👤 Recording ${label} for ${areaName}...`);
          await this._hass.callService("otis_ai", "confirm_person_identity", {
            person_id: pid,
            label,
            confirmed: !isNotPersonPet,
            visual_features: {
              area,
              area_name: areaName,
              classification: pid,
              snapshot_key: snapshotKey,
              detection_image_entity_id: detImageEid,
              suggestion_id: sid,
            },
          });
          if (sid) {
            this._dismissedIds.delete(sid);
            this._saveDismissedIds();
            this._hiddenIds.delete(sid);
            this._suggestions = (this._suggestions || []).filter((item) => item.id !== sid);
            this._render();
          }
          if (pid === "unknown_person") {
            this._showToast(`🕵️ Logged Unknown Person in ${areaName} for security & training calibration.`);
          } else if (pid === "unknown_animal") {
            this._showToast(`🦊 Logged Unknown Animal in ${areaName} — excluded from household pet profiles.`);
          } else if (isNotPersonPet) {
            this._showToast(`🚫 Marked ${areaName} trigger as Not Person/Pet (false positive suppressed).`);
          } else {
            this._showToast(`✨ Verified ${label} in ${areaName}! Training sample recorded.`);
          }
          await this._fetchData();
        } catch (err) {
          this._showToast(`Failed to verify identity: ${err.message || err}`, true);
        }
      };
    });

    // Ambiguous Room Transition Selection buttons
    root.querySelectorAll(".btn-confirm-room-transition").forEach((btn) => {
      btn.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const sid = e.currentTarget.getAttribute("data-suggestion-id");
        const toArea = e.currentTarget.getAttribute("data-to-area");
        const toAreaName = e.currentTarget.getAttribute("data-to-area-name") || toArea;
        if (!sid || !toArea || !this._hass) return;
        try {
          this._showToast(`🚪 Confirming entry into ${toAreaName}...`);
          await this._hass.callService("otis_ai", "apply_suggestion", {
            suggestion_id: sid,
            selected_to_area: toArea,
          });
          this._dismissedIds.delete(sid);
          this._saveDismissedIds();
          this._suggestions = (this._suggestions || []).filter((item) => item.id !== sid);
          this._render();
          this._showToast(`✅ Confirmed room transition into ${toAreaName}.`);
          await this._fetchData();
        } catch (err) {
          this._showToast(`Failed to confirm room transition: ${err.message || err}`, true);
        }
      };
    });

    // Reset Training buttons in People & Pets progress banner and modal
    root.querySelectorAll(".btn-reset-person-training").forEach((btn) => {
      btn.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const pid = e.currentTarget.getAttribute("data-person-id");
        const label = e.currentTarget.getAttribute("data-person-label") || pid;
        if (!pid || !this._hass) return;
        try {
          await this._hass.callService("otis_ai", "confirm_person_identity", {
            person_id: pid,
            label,
            confirmed: false,
            visual_features: { reset: true },
          });
          this._showToast(`↺ Reset recognition training for ${label}. Verify live camera snapshots in Proactive Feed to train.`);
          await this._fetchData();
        } catch (err) {
          this._showToast(`Failed to reset training: ${err.message || err}`, true);
        }
      };
    });

    const btnOpenPeopleRules = root.querySelector("#btn-open-people-rules");
    if (btnOpenPeopleRules) {
      btnOpenPeopleRules.onclick = () => {
        this._rulesActiveTab = "people";
        this._rulesModalOpen = true;
        OTIS_ACTIVE_RULES_STATE.isOpen = true;
        OTIS_ACTIVE_RULES_STATE.activeTab = "people";
        OTIS_ACTIVE_RULES_STATE.draft = this._rulesDraft;
        OTIS_ACTIVE_RULES_STATE.wizardState = this._wizardState;
        this._render();
      };
    }

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
        OTIS_ACTIVE_CHAT.conversationId = null;
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

    // Allow text selection inside chat history without Lovelace drag/gesture interference
    const chatHistoryEl = root.querySelector("#chat-history");
    if (chatHistoryEl) {
      chatHistoryEl.onpointerdown = (e) => {
        e.stopPropagation();
      };
      chatHistoryEl.onmousedown = (e) => {
        e.stopPropagation();
      };
    }

    // Prompt copy buttons
    root.querySelectorAll(".prompt-copy-btn").forEach((btn) => {
      btn.onclick = async (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const prompt = btn.getAttribute("data-prompt");
        if (prompt) {
          await this._copyToClipboard(prompt, "📋 Copied prompt to clipboard & input!");
          const input = root.querySelector("#chat-input");
          if (input) {
            input.value = prompt;
            input.focus();
            input.dispatchEvent(new Event("input", { bubbles: true }));
          }
        }
      };
    });

    // Otis response retry buttons
    root.querySelectorAll(".response-retry-btn").forEach((btn) => {
      btn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const msgId = btn.getAttribute("data-msg-id");
        if (msgId) {
          this._handleRetry(msgId);
        }
      };
    });

    // Otis response copy buttons
    root.querySelectorAll(".response-copy-btn").forEach((btn) => {
      btn.onclick = async (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const text = btn.getAttribute("data-response");
        if (text) {
          await this._copyToClipboard(text, "📋 Response copied to clipboard!");
          const label = btn.querySelector(".copy-label");
          if (label) {
            const old = label.textContent;
            label.textContent = "Copied!";
            setTimeout(() => {
              label.textContent = old;
            }, 1800);
          }
        }
      };
    });

    // Code snippet copy buttons
    root.querySelectorAll(".code-copy-btn").forEach((btn) => {
      btn.onclick = async (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const code = btn.getAttribute("data-code");
        if (code) {
          await this._copyToClipboard(code, "📋 Code snippet copied to clipboard!");
          const label = btn.querySelector(".copy-label");
          if (label) {
            const old = label.textContent;
            label.textContent = "Copied!";
            setTimeout(() => {
              label.textContent = old;
            }, 1800);
          }
        }
      };
    });

    // Reasoning trace toggle buttons (in-place DOM toggle without scroll jumps)
    root.querySelectorAll(".reasoning-trace-toggle").forEach((btn) => {
      btn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const traceId = btn.getAttribute("data-trace-id");
        if (!traceId) return;

        const willExpand = !this._expandedReasoningIds.has(traceId);
        if (willExpand) {
          this._expandedReasoningIds.add(traceId);
          btn.classList.add("expanded");
        } else {
          this._expandedReasoningIds.delete(traceId);
          btn.classList.remove("expanded");
        }

        const container = btn.closest(".reasoning-trace-container");
        if (container) {
          const stepsList = container.querySelector(".reasoning-steps-list");
          if (stepsList) {
            stepsList.style.display = willExpand ? "" : "none";
          }
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

    // Attachment button & file input
    const attachBtn = root.querySelector("#chat-attach-btn");
    const chatFileInput = root.querySelector("#chat-file-input");
    if (attachBtn && chatFileInput) {
      attachBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        chatFileInput.click();
      };
      chatFileInput.onchange = (e) => {
        this._handleFilesSelected(e.target.files);
        chatFileInput.value = "";
      };
    }

    // Attachment removal
    root.querySelectorAll(".chat-attachment-remove").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute("data-remove-att"), 10);
        if (!isNaN(idx) && this._pendingAttachments) {
          this._pendingAttachments.splice(idx, 1);
          this._render();
        }
      };
    });

    // Drag-and-drop file upload on chat input wrapper
    const chatWrapper = root.querySelector(".chat-input-wrapper");
    if (chatWrapper) {
      chatWrapper.ondragover = (e) => {
        e.preventDefault();
        chatWrapper.style.borderColor = "var(--otis-primary)";
      };
      chatWrapper.ondragleave = () => {
        chatWrapper.style.borderColor = "";
      };
      chatWrapper.ondrop = (e) => {
        e.preventDefault();
        chatWrapper.style.borderColor = "";
        if (e.dataTransfer && e.dataTransfer.files) {
          this._handleFilesSelected(e.dataTransfer.files);
        }
      };
      chatWrapper.addEventListener("paste", (e) => this._handleClipboardPaste(e));
    }

    // Chat input & send
    const chatInput = root.querySelector("#chat-input");
    const chatSend = root.querySelector("#chat-send");
    const previewContainer = root.querySelector("#chat-live-preview");
    const previewBody = root.querySelector("#chat-live-preview-body");
    const previewClose = root.querySelector("#chat-preview-close");

    if (chatInput) {
      // NOTE: Clipboard paste is handled at chatWrapper to prevent duplicate event bubbling
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
        if (this._isSendingChat) {
          this._stopChatGeneration();
          return;
        }
        const text = chatInput.value;
        chatInput.value = "";
        this._draftChatText = "";
        this._previewDismissed = false;
        chatInput.style.height = "auto";
        if (previewContainer) previewContainer.style.display = "none";
        this._sendChatMessage(text);
      };
    }

    const btnStopBubble = root.querySelector("#btn-stop-thinking-bubble");
    if (btnStopBubble) {
      btnStopBubble.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._stopChatGeneration();
      };
    }
    const btnStopBanner = root.querySelector("#btn-stop-thinking-banner");
    if (btnStopBanner) {
      btnStopBanner.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._stopChatGeneration();
      };
    }

    // Phase 3: Interactive Floorplan 3D Orbit & Pitch Controls & View Projection
    const floorplanViewport = root.querySelector("#floorplan-viewport");
    const floorplanCanvas = root.querySelector("#floorplan-canvas");
    const hudOrbitReadout = root.querySelector("#hud-orbit-readout");
    const sliderAzimuth = root.querySelector("#slider-orbit-azimuth");
    const sliderPitch = root.querySelector("#slider-pitch-incline");
    const valAzimuth = root.querySelector("#val-orbit-azimuth");
    const valPitch = root.querySelector("#val-pitch-incline");

    const applyCanvas3dTransform = (smooth = false) => {
      if (!floorplanCanvas) return;
      if (this._floorplanViewMode === "3d") {
        if (smooth) {
          floorplanCanvas.style.transition = "transform 0.4s cubic-bezier(0.16, 1, 0.3, 1)";
          floorplanCanvas.querySelectorAll(".floorplan-device-pin").forEach((p) => {
            p.style.transition = "transform 0.4s cubic-bezier(0.16, 1, 0.3, 1)";
          });
        }
        floorplanCanvas.style.transform = `rotateX(${this._floorplanPitch}deg) rotateZ(${this._floorplanAzimuth}deg) scale(${this._floorplanScale || 1})`;
        floorplanCanvas.style.setProperty("--floorplan-azimuth", `${this._floorplanAzimuth}deg`);
        floorplanCanvas.style.setProperty("--floorplan-pitch", `${this._floorplanPitch}deg`);
        floorplanCanvas.style.setProperty("--wall-height", `${this._floorplanWallHeight || 28}px`);
      } else {
        floorplanCanvas.style.transition = "";
        floorplanCanvas.style.transform = "none";
        floorplanCanvas.style.setProperty("--floorplan-azimuth", "0deg");
        floorplanCanvas.style.setProperty("--floorplan-pitch", "0deg");
      }
      if (hudOrbitReadout) {
        hudOrbitReadout.textContent = `${Math.round(this._floorplanAzimuth)}° Az / ${Math.round(this._floorplanPitch)}° Pitch`;
      }
      if (valAzimuth) valAzimuth.textContent = `${Math.round(this._floorplanAzimuth)}°`;
      if (valPitch) valPitch.textContent = `${Math.round(this._floorplanPitch)}°`;
      const valWallH = root.querySelector("#val-wall-height");
      if (valWallH) valWallH.textContent = `${Math.round(this._floorplanWallHeight || 28)}px`;
      if (sliderAzimuth) sliderAzimuth.value = String(Math.round(this._floorplanAzimuth));
      if (sliderPitch) sliderPitch.value = String(Math.round(this._floorplanPitch));
    };

    // Floorplan: 3D Raised Transparent Walls update & positioning
    const updateWallPositions = () => {
      const currentSvgEl = root.querySelector("#floorplan-viewport svg");
      const wallsOverlay = root.querySelector("#floorplan-walls-overlay");
      if (!currentSvgEl || !wallsOverlay) return;

      const curZone = this._selectedFloorZone || "all";
      const is3d = this._floorplanViewMode === "3d";
      wallsOverlay.style.display = is3d && this._floorplanWallsEnabled !== false ? "" : "none";

      const vbAttr = currentSvgEl.getAttribute("viewBox") || "0 0 1300 1250";
      const vbParts = vbAttr.split(/[\s,]+/).map(Number);
      const vbX = !isNaN(vbParts[0]) ? vbParts[0] : 0;
      const vbY = !isNaN(vbParts[1]) ? vbParts[1] : 0;
      const vbW = (!isNaN(vbParts[2]) && vbParts[2] > 0) ? vbParts[2] : 1300;
      const vbH = (!isNaN(vbParts[3]) && vbParts[3] > 0) ? vbParts[3] : 1250;

      wallsOverlay.querySelectorAll(".floorplan-3d-room-shell").forEach((shell) => {
        const sZone = shell.getAttribute("data-zone");
        if (curZone === "main" && sZone === "upper") {
          shell.style.display = "none";
          return;
        }
        if (curZone === "upper" && sZone !== "upper") {
          shell.style.display = "none";
          return;
        }
        if (curZone === "outdoor" && sZone !== "outdoor") {
          shell.style.display = "none";
          return;
        }
        shell.style.display = "";

        const rx = parseFloat(shell.getAttribute("data-x") || 0);
        const ry = parseFloat(shell.getAttribute("data-y") || 0);
        const rw = parseFloat(shell.getAttribute("data-w") || 0);
        const rh = parseFloat(shell.getAttribute("data-h") || 0);

        shell.style.left = `${(((rx - vbX) / vbW) * 100).toFixed(3)}%`;
        shell.style.top = `${(((ry - vbY) / vbH) * 100).toFixed(3)}%`;
        shell.style.width = `${((rw / vbW) * 100).toFixed(3)}%`;
        shell.style.height = `${((rh / vbH) * 100).toFixed(3)}%`;
      });
    };

    // Floorplan: Zero-drift pin positioning and zone filtering
    const updatePinPositions = () => {
      const currentSvgEl = root.querySelector("#floorplan-viewport svg");
      const currentViewport = root.querySelector("#floorplan-viewport");
      const pinsOverlay = root.querySelector("#floorplan-pins-overlay");
      if (!currentSvgEl || !currentViewport || !pinsOverlay) return;

      const curZone = this._selectedFloorZone || "all";
      const planUpper = currentSvgEl.querySelector("#plan-upper");

      let uVbY = 730;
      if (planUpper) {
        const uvb = planUpper.getAttribute("data-viewbox");
        if (uvb) {
          const parts = uvb.split(" ").map(Number);
          if (parts.length >= 2 && !isNaN(parts[1])) uVbY = parts[1];
        }
      }

      const vbAttr = currentSvgEl.getAttribute("viewBox") || "0 0 1300 1250";
      const vbParts = vbAttr.split(/[\s,]+/).map(Number);
      const vbX = !isNaN(vbParts[0]) ? vbParts[0] : 0;
      const vbY = !isNaN(vbParts[1]) ? vbParts[1] : 0;
      const vbW = (!isNaN(vbParts[2]) && vbParts[2] > 0) ? vbParts[2] : 1300;
      const vbH = (!isNaN(vbParts[3]) && vbParts[3] > 0) ? vbParts[3] : 1250;

      pinsOverlay.querySelectorAll(".floorplan-device-pin").forEach((pin) => {
        const bx = parseFloat(pin.getAttribute("data-x") || 300);
        const by = parseFloat(pin.getAttribute("data-y") || 300);
        const isUpperPin = by >= uVbY;

        if (curZone === "main" && isUpperPin) {
          pin.style.display = "none";
          return;
        }
        if (curZone === "upper" && !isUpperPin) {
          pin.style.display = "none";
          return;
        }
        if (curZone === "outdoor") {
          const entityId = pin.getAttribute("data-entity-id") || "";
          const ent = (this._capabilityMap?.entities || []).find((e) => e.entity_id === entityId);
          const areaId = (ent?.area_id || "").toLowerCase();
          const isOutdoor =
            areaId === "frontyard" ||
            areaId === "backyard" ||
            areaId === "pool" ||
            /outdoor|backyard|frontyard|patio|driveway|pool|deck|yard|porch/i.test(entityId);
          if (!isOutdoor || isUpperPin) {
            pin.style.display = "none";
            return;
          }
        }

        pin.style.display = "flex";
        pin.style.opacity = "1";

        const pctX = ((bx - vbX) / vbW) * 100;
        const pctY = ((by - vbY) / vbH) * 100;

        pin.style.left = `${pctX.toFixed(3)}%`;
        pin.style.top = `${pctY.toFixed(3)}%`;
      });
    };

    const applyZoneFilterToSvg = (zone) => {
      const svgEl = root.querySelector("#floorplan-viewport svg");
      if (!svgEl) return;
      const is3d = this._floorplanViewMode === "3d";
      const view2d = svgEl.querySelector("#view-mode-2d");
      const view3d = svgEl.querySelector("#view-mode-3d");

      if (view2d) view2d.style.display = "";
      if (view3d) view3d.style.display = "none";

      const planGround = svgEl.querySelector("#plan-ground");
      const planUpper = svgEl.querySelector("#plan-upper");
      const fullVb = svgEl.getAttribute("data-full-viewbox") || "0 0 1300 1250";

      if (zone === "main") {
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
        if (planGround) planGround.style.display = "";
        if (planUpper) planUpper.style.display = "";
        svgEl.setAttribute("viewBox", fullVb);
        svgEl.querySelectorAll("[data-zone]").forEach((el) => {
          el.style.opacity = "1";
          el.style.filter = "none";
        });
      }

      const activeVb = svgEl.getAttribute("viewBox") || fullVb;
      const vbParts = activeVb.split(/[\s,]+/).map(Number);
      if (floorplanCanvas && vbParts.length === 4 && vbParts[2] > 0 && vbParts[3] > 0) {
        floorplanCanvas.style.aspectRatio = `${vbParts[2]} / ${vbParts[3]}`;
        floorplanCanvas.style.width = "100%";
      }

      applyCanvas3dTransform();
      updateWallPositions();
      updatePinPositions();
    };

    applyZoneFilterToSvg(this._selectedFloorZone || "all");
    requestAnimationFrame(() => {
      updateWallPositions();
      updatePinPositions();
    });
    setTimeout(() => {
      updateWallPositions();
      updatePinPositions();
    }, 60);
    setTimeout(() => {
      updateWallPositions();
      updatePinPositions();
    }, 200);
    setTimeout(() => {
      updateWallPositions();
      updatePinPositions();
    }, 600);

    // 3D Canvas Drag-to-Orbit Pointer Interaction
    if (floorplanViewport && this._floorplanViewMode === "3d" && !this._editorActive) {
      let isOrbiting = false;
      let initialHitTarget = null;
      let startX = 0;
      let startY = 0;
      let startAz = this._floorplanAzimuth;
      let startPitch = this._floorplanPitch;

      floorplanViewport.onpointerdown = (e) => {
        if (this._floorplanViewMode !== "3d" || this._editorActive || this._floorplanOrbitLocked !== false) return;
        if (e.target.closest(".floorplan-device-pin, .floorplan-3d-hud, button, input, select, .room-info-card")) {
          return;
        }
        isOrbiting = true;
        initialHitTarget = e.target;
        startX = e.clientX;
        startY = e.clientY;
        startAz = this._floorplanAzimuth;
        startPitch = this._floorplanPitch;
        floorplanViewport.style.cursor = "grabbing";
        if (floorplanCanvas) {
          floorplanCanvas.style.transition = "none";
          floorplanCanvas.querySelectorAll(".floorplan-device-pin").forEach((p) => {
            p.style.transition = "none";
          });
        }
        try { floorplanViewport.setPointerCapture(e.pointerId); } catch (_) { }
      };

      floorplanViewport.onpointermove = (e) => {
        if (!isOrbiting) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        const sensitivity = 0.5;

        let newAz = Math.round((startAz - dx * sensitivity) % 360);
        if (newAz < 0) newAz += 360;

        let newPitch = Math.round(startPitch + dy * sensitivity);
        newPitch = Math.max(30, Math.min(75, newPitch));

        this._floorplanAzimuth = newAz;
        this._floorplanPitch = newPitch;
        applyCanvas3dTransform(false);
      };

      const finishOrbit = (e) => {
        if (!isOrbiting) return;
        isOrbiting = false;
        floorplanViewport.style.cursor = "";
        try { floorplanViewport.releasePointerCapture(e.pointerId); } catch (_) { }
        try {
          localStorage.setItem("otis_floorplan_orbit_azimuth", String(this._floorplanAzimuth));
          localStorage.setItem("otis_floorplan_pitch_incline", String(this._floorplanPitch));
        } catch (_) { }

        // Disambiguate Tap / Click from Orbit Drag:
        const moveDist = Math.hypot(e.clientX - startX, e.clientY - startY);
        if (moveDist < 6) {
          const hitTarget = initialHitTarget || e.target;
          const roomGrp = hitTarget && hitTarget.closest ? hitTarget.closest(".room-group, .floorplan-3d-room-shell, .floorplan-3d-wall") : null;
          if (roomGrp) {
            const shell = roomGrp.closest(".floorplan-3d-room-shell") || (roomGrp.classList.contains("floorplan-3d-room-shell") ? roomGrp : null);
            const areaId = (shell ? (shell.getAttribute("data-room-id") || shell.getAttribute("data-area-id")) : null) ||
              roomGrp.getAttribute("data-area-id") ||
              roomGrp.getAttribute("data-room-id");
            if (areaId) {
              const area = this._capabilityMap?.areas?.[areaId];
              const slug = areaId.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "room";
              this._selectedRoomInfo = {
                areaId,
                name: area?.name || areaId,
                slug,
                zone: (shell ? shell.getAttribute("data-zone") : null) || roomGrp.getAttribute("data-zone") || "indoor",
                entities: area?.entities || [],
              };
              this._render();
            }
          }
        }
        initialHitTarget = null;
      };

      floorplanViewport.onpointerup = finishOrbit;
      floorplanViewport.onpointercancel = finishOrbit;

      floorplanViewport.onwheel = (e) => {
        if (this._floorplanOrbitLocked !== false) return;
        e.preventDefault();
        const delta = e.deltaY < 0 ? 0.05 : -0.05;
        this._floorplanScale = Math.max(0.6, Math.min(1.8, (this._floorplanScale || 1.0) + delta));
        applyCanvas3dTransform(false);
        try { localStorage.setItem("otis_floorplan_scale", String(this._floorplanScale)); } catch (_) { }
      };
    }

    const btnToggle3dLock = root.querySelector("#btn-toggle-3d-lock");
    if (btnToggle3dLock) {
      btnToggle3dLock.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._floorplanOrbitLocked = this._floorplanOrbitLocked === false ? true : false;
        try {
          localStorage.setItem("otis_floorplan_orbit_locked", String(this._floorplanOrbitLocked));
        } catch (_) { }
        this._render();
      };
    }

    // 3D HUD Controls: Sliders, Steppers, Presets & Reset
    if (sliderAzimuth) {
      sliderAzimuth.oninput = (e) => {
        this._floorplanAzimuth = parseFloat(e.target.value) || 0;
        applyCanvas3dTransform(false);
      };
      sliderAzimuth.onchange = () => {
        try { localStorage.setItem("otis_floorplan_orbit_azimuth", String(this._floorplanAzimuth)); } catch (_) { }
      };
    }

    if (sliderPitch) {
      sliderPitch.oninput = (e) => {
        this._floorplanPitch = Math.max(30, Math.min(75, parseFloat(e.target.value) || 58));
        applyCanvas3dTransform(false);
      };
      sliderPitch.onchange = () => {
        try { localStorage.setItem("otis_floorplan_pitch_incline", String(this._floorplanPitch)); } catch (_) { }
      };
    }

    const btnAzMinus = root.querySelector("#btn-azimuth-step-minus");
    if (btnAzMinus) {
      btnAzMinus.onclick = () => {
        this._floorplanAzimuth = (this._floorplanAzimuth - 15 + 360) % 360;
        applyCanvas3dTransform(true);
        try { localStorage.setItem("otis_floorplan_orbit_azimuth", String(this._floorplanAzimuth)); } catch (_) { }
      };
    }

    const btnAzPlus = root.querySelector("#btn-azimuth-step-plus");
    if (btnAzPlus) {
      btnAzPlus.onclick = () => {
        this._floorplanAzimuth = (this._floorplanAzimuth + 15) % 360;
        applyCanvas3dTransform(true);
        try { localStorage.setItem("otis_floorplan_orbit_azimuth", String(this._floorplanAzimuth)); } catch (_) { }
      };
    }

    const btnPitchMinus = root.querySelector("#btn-pitch-step-minus");
    if (btnPitchMinus) {
      btnPitchMinus.onclick = () => {
        this._floorplanPitch = Math.max(30, this._floorplanPitch - 5);
        applyCanvas3dTransform(true);
        try { localStorage.setItem("otis_floorplan_pitch_incline", String(this._floorplanPitch)); } catch (_) { }
      };
    }

    const btnPitchPlus = root.querySelector("#btn-pitch-step-plus");
    if (btnPitchPlus) {
      btnPitchPlus.onclick = () => {
        this._floorplanPitch = Math.min(75, this._floorplanPitch + 5);
        applyCanvas3dTransform(true);
        try { localStorage.setItem("otis_floorplan_pitch_incline", String(this._floorplanPitch)); } catch (_) { }
      };
    }

    root.querySelectorAll(".btn-preset-pill[data-azimuth]").forEach((btn) => {
      btn.onclick = (e) => {
        if (this._floorplanOrbitLocked !== false) return;
        const az = parseFloat(e.currentTarget.getAttribute("data-azimuth") || "45");
        const pitch = parseFloat(e.currentTarget.getAttribute("data-pitch") || "58");
        this._floorplanAzimuth = az;
        this._floorplanPitch = pitch;
        applyCanvas3dTransform(true);
        try {
          localStorage.setItem("otis_floorplan_orbit_azimuth", String(this._floorplanAzimuth));
          localStorage.setItem("otis_floorplan_pitch_incline", String(this._floorplanPitch));
        } catch (_) { }
        root.querySelectorAll(".btn-preset-pill[data-azimuth]").forEach((p) => p.classList.toggle("active", p === e.currentTarget));
      };
    });

    const btnReset3d = root.querySelector("#btn-reset-3d-view");
    if (btnReset3d) {
      btnReset3d.onclick = () => {
        if (this._floorplanOrbitLocked !== false) return;
        this._floorplanAzimuth = 45;
        this._floorplanPitch = 58;
        applyCanvas3dTransform(true);
        try {
          localStorage.setItem("otis_floorplan_orbit_azimuth", "45");
          localStorage.setItem("otis_floorplan_pitch_incline", "58");
        } catch (_) { }
        root.querySelectorAll(".btn-preset-pill[data-azimuth]").forEach((p) => {
          p.classList.toggle("active", p.getAttribute("data-azimuth") === "45");
        });
      };
    }

    const btnSave3dDash = root.querySelector("#btn-save-3d-dashboard");
    if (btnSave3dDash) {
      btnSave3dDash.onclick = async (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const originalText = btnSave3dDash.textContent;
        btnSave3dDash.disabled = true;
        btnSave3dDash.textContent = "⏳ Saving...";
        try {
          this._showToast("💾 Saving 3D View to Interactive Floor Plan Dashboard...");
          const az = Math.round(this._floorplanAzimuth || 0);
          const pitch = Math.round(this._floorplanPitch || 30);
          const wallH = Math.round(this._floorplanWallHeight || 36);
          const wallsEnabled = this._floorplanWallsEnabled !== false;
          const zone = this._selectedFloorZone || "all";
          const scale = this._floorplanScale || 1.0;
          try {
            localStorage.setItem("otis_floorplan_view_mode", "3d");
            localStorage.setItem("otis_floorplan_orbit_azimuth", String(az));
            localStorage.setItem("otis_floorplan_pitch_incline", String(pitch));
            localStorage.setItem("otis_floorplan_walls_enabled", String(wallsEnabled));
            localStorage.setItem("otis_floorplan_wall_height", String(wallH));
            localStorage.setItem("otis_floorplan_selected_zone", String(zone));
            localStorage.setItem("otis_floorplan_scale", String(scale));
          } catch (_) { }
          await this._hass.callService("otis_ai", "set_user_rules", {
            rules: {
              floorplan_view_mode: "3d",
              floorplan_3d: true,
              floorplan_azimuth: az,
              floorplan_pitch: pitch,
              floorplan_wall_height: wallH,
              floorplan_walls_enabled: wallsEnabled,
              floorplan_zone: zone,
              floorplan_scale: scale,
            },
          });
          await this._hass.callService("otis_ai", "regenerate_dashboards", {});
          btnSave3dDash.textContent = "✅ Saved!";
          this._showToast(`✨ 3D Floor Plan (${az}° Az / ${pitch}° Pitch) saved & synced to Floor Plan dashboard!`);
          await this._fetchData();
        } catch (err) {
          console.error("Failed to save 3D dashboard view:", err);
          btnSave3dDash.disabled = false;
          btnSave3dDash.textContent = originalText;
          this._showToast(`Failed to sync 3D view: ${err.message || err}`, true);
        }
      };
    }

    const btnToggleWalls = root.querySelector("#btn-toggle-3d-walls");
    if (btnToggleWalls) {
      btnToggleWalls.onclick = () => {
        this._floorplanWallsEnabled = this._floorplanWallsEnabled === false ? true : false;
        try { localStorage.setItem("otis_floorplan_walls_enabled", String(this._floorplanWallsEnabled)); } catch (_) { }
        updateWallPositions();
        btnToggleWalls.classList.toggle("active", this._floorplanWallsEnabled);
        btnToggleWalls.textContent = this._floorplanWallsEnabled ? "🏢 Walls ON" : "🏢 Walls OFF";
      };
    }

    const valWallH = root.querySelector("#val-wall-height");
    const btnWallHMinus = root.querySelector("#btn-wall-height-minus");
    if (btnWallHMinus) {
      btnWallHMinus.onclick = () => {
        this._floorplanWallHeight = Math.max(10, (this._floorplanWallHeight || 28) - 4);
        try { localStorage.setItem("otis_floorplan_wall_height", String(this._floorplanWallHeight)); } catch (_) { }
        if (floorplanCanvas) floorplanCanvas.style.setProperty("--wall-height", `${this._floorplanWallHeight}px`);
        if (valWallH) valWallH.textContent = `${this._floorplanWallHeight}px`;
      };
    }

    const btnWallHPlus = root.querySelector("#btn-wall-height-plus");
    if (btnWallHPlus) {
      btnWallHPlus.onclick = () => {
        this._floorplanWallHeight = Math.min(50, (this._floorplanWallHeight || 28) + 4);
        try { localStorage.setItem("otis_floorplan_wall_height", String(this._floorplanWallHeight)); } catch (_) { }
        if (floorplanCanvas) floorplanCanvas.style.setProperty("--wall-height", `${this._floorplanWallHeight}px`);
        if (valWallH) valWallH.textContent = `${this._floorplanWallHeight}px`;
      };
    }

    const btnToggleHud = root.querySelector("#btn-toggle-3d-hud");
    if (btnToggleHud) {
      btnToggleHud.onclick = () => {
        this._floorplanHudCollapsed = !this._floorplanHudCollapsed;
        this._render();
      };
    }

    root.querySelectorAll(".view-mode-pill").forEach((pill) => {
      pill.onclick = (e) => {
        const mode = e.currentTarget.getAttribute("data-view-mode") || "2d";
        this._floorplanViewMode = mode;
        try {
          localStorage.setItem("otis_floorplan_view_mode", mode);
        } catch (_) { }
        root.querySelectorAll(".view-mode-pill").forEach((p) => p.classList.toggle("active", p === e.currentTarget));
        this._render();
      };
    });

    root.querySelectorAll(".zone-pill").forEach((pill) => {
      pill.onclick = (e) => {
        const zone = e.currentTarget.getAttribute("data-zone") || "all";
        this._selectedFloorZone = zone;
        try {
          localStorage.setItem("otis_floorplan_selected_zone", zone);
        } catch (_) { }
        root.querySelectorAll(".zone-pill").forEach((p) => p.classList.toggle("active", p === e.currentTarget));
        applyZoneFilterToSvg(zone);
        updateWallPositions();
        updatePinPositions();
      };
    });

    // Studio Back to Dashboard Button
    const btnBackDash = root.querySelector("#btn-back-dashboard");
    if (btnBackDash) {
      btnBackDash.onclick = () => {
        const path =
          window.location.pathname.startsWith("/command-center") ||
            this._config.dashboard_url_path === "command-center"
            ? "/command-center"
            : "/otis-ai";
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
    const isAdmin = Boolean(this._hass?.user?.is_admin || this._hass?.user?.is_owner);

    if (svgViewport && svgEl) {
      svgViewport.addEventListener("scroll", updatePinPositions, { passive: true });
      if (typeof ResizeObserver !== "undefined") {
        if (this._viewportResizeObserver) {
          try { this._viewportResizeObserver.disconnect(); } catch (_) { }
        }
        this._viewportResizeObserver = new ResizeObserver(() => {
          updatePinPositions();
        });
        this._viewportResizeObserver.observe(svgViewport);
        this._viewportResizeObserver.observe(svgEl);
      }

      // 0. Set up interactive Home Assistant device pins (<ha-state-icon> overlays)
      const pinsOverlay = root.querySelector("#floorplan-pins-overlay");
      if (pinsOverlay) {
        this._updateFloorplanPinStates();
        pinsOverlay.querySelectorAll(".floorplan-device-pin").forEach((pin) => {
          const entityId = pin.getAttribute("data-entity-id");
          if (!entityId) return;

          if (this._editorActive && isAdmin) {
            pin.style.cursor = "grab";
            pin.onpointerdown = (e) => {
              e.preventDefault();
              e.stopPropagation();
              const startPinX = parseFloat(pin.getAttribute("data-x") || 300);
              const startPinY = parseFloat(pin.getAttribute("data-y") || 300);

              this._draggingBadge = {
                el: pin,
                entityId,
                startX: startPinX,
                startY: startPinY,
                startClientX: e.clientX,
                startClientY: e.clientY,
                moved: false,
              };
              try { pin.setPointerCapture(e.pointerId); } catch (_) { }
            };

            pin.onpointermove = (e) => {
              if (!this._draggingBadge || this._draggingBadge.el !== pin) return;
              e.preventDefault();
              e.stopPropagation();

              const pt = getSvgPoint(svgEl, e.clientX, e.clientY);
              const newX = Math.round(pt.x);
              const newY = Math.round(pt.y);

              if (Math.abs(newX - this._draggingBadge.startX) > 3 || Math.abs(newY - this._draggingBadge.startY) > 3) {
                this._draggingBadge.moved = true;
              }

              pin.setAttribute("data-x", newX);
              pin.setAttribute("data-y", newY);
              const oRect = pinsOverlay.getBoundingClientRect();
              pin.style.left = `${Math.round(e.clientX - oRect.left)}px`;
              pin.style.top = `${Math.round(e.clientY - oRect.top)}px`;

              if (editorHud) {
                editorHud.textContent = `📍 ${this._draggingBadge.entityId} (X: ${newX}, Y: ${newY})`;
              }

              this._dirtyBadges[entityId] = {
                entity_id: entityId,
                x: newX,
                y: newY,
              };
              this._hasUnsavedLayout = true;
              const saveBtn = root.querySelector("#btn-save-layout");
              if (saveBtn) saveBtn.textContent = "💾 Save Changes *";
            };

            pin.onpointerup = (e) => {
              if (this._draggingBadge && this._draggingBadge.el === pin) {
                try { pin.releasePointerCapture(e.pointerId); } catch (_) { }
                const wasMoved = this._draggingBadge.moved;
                const curX = parseFloat(pin.getAttribute("data-x") || 300);
                const curY = parseFloat(pin.getAttribute("data-y") || 300);
                this._draggingBadge = null;

                if (wasMoved) {
                  updatePinPositions();
                } else {
                  this._selectedEditorEntityId = entityId;
                  this._selectedEditorEntityCoords = { x: curX, y: curY };
                  this._editMarkerModalOpen = true;
                  this._render();
                }
              }
            };

            pin.onpointercancel = (e) => {
              if (this._draggingBadge && this._draggingBadge.el === pin) {
                try { pin.releasePointerCapture(e.pointerId); } catch (_) { }
                this._draggingBadge = null;
              }
            };
          } else {
            // Normal mode -> Tap to toggle or open more-info
            pin.style.cursor = "pointer";
            pin.onclick = async (e) => {
              e.preventDefault();
              e.stopPropagation();
              const domain = entityId.split(".")[0];
              const stateObj = this._hass?.states?.[entityId];
              const name = stateObj?.attributes?.friendly_name || entityId;
              if (["light", "switch", "fan", "cover"].includes(domain)) {
                try {
                  await this._hass.callService("homeassistant", "toggle", { entity_id: entityId });
                  const st = this._hass.states[entityId];
                  const newState = st?.state === "on" ? "off" : "on";
                  this._showToast(`${name} toggled (${newState})`);
                } catch (err) {
                  this._showToast(`Could not toggle ${name}: ${err.message || err}`, true);
                }
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
          }
        });
      }

      if (this._editorActive && isAdmin) {
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
            const hasContainerBanner = Boolean(rGrp.querySelector(".container-shell, .container-banner"));
            const hdrYOff = hasContainerBanner ? 34 : 22;
            if (rLbl) {
              rLbl.setAttribute("x", rData.x + 14);
              rLbl.setAttribute("y", rData.y + hdrYOff);
              if (rData.name) rLbl.textContent = rData.name;
            }
            if (Array.isArray(rData.sub_zones)) {
              rGrp.querySelectorAll(".subzone-pill").forEach((p) => p.remove());
              rData.sub_zones.forEach((szTxt, sIdx) => {
                const cleanSz = String(szTxt || "").trim();
                if (!cleanSz) return;
                const pillEl = document.createElementNS("http://www.w3.org/2000/svg", "text");
                pillEl.setAttribute("x", rData.x + 16);
                pillEl.setAttribute("y", rData.y + hdrYOff + 18 + sIdx * 16);
                pillEl.setAttribute("class", "subzone-pill");
                pillEl.textContent = `▪ ${cleanSz}`;
                if (rLbl && rLbl.nextSibling) {
                  rGrp.insertBefore(pillEl, rLbl.nextSibling);
                } else {
                  rGrp.appendChild(pillEl);
                }
              });
            } else {
              rGrp.querySelectorAll(".subzone-pill").forEach((pill, sIdx) => {
                pill.setAttribute("x", rData.x + 16);
                pill.setAttribute("y", rData.y + hdrYOff + 18 + sIdx * 16);
              });
            }
            if (rData.features && typeof rData.features === "object") {
              Object.entries(rData.features).forEach(([fKey, fPos]) => {
                if (!fPos || fPos.x === undefined || fPos.y === undefined) return;
                const fGrp = rGrp.querySelector(`.room-feature[data-feature="${fKey}"]`) || svgEl.querySelector(`.room-feature[data-area-id="${roomId}"][data-feature="${fKey}"]`);
                if (fGrp) {
                  this._positionRoomFeatureSvg(fGrp, fKey, Number(fPos.x), Number(fPos.y));
                }
              });
            }
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
            if (e.target && e.target.closest && e.target.closest(".room-feature")) return;
            e.stopPropagation();
            const areaId = grp.getAttribute("data-area-id");
            const roomZone = grp.getAttribute("data-zone") || "main";
            if (this._selectedFloorZone !== "all" && this._selectedFloorZone !== roomZone) {
              if (roomZone === "upper" || (roomZone === "main" && this._selectedFloorZone === "upper") || (roomZone === "outdoor" && this._selectedFloorZone === "upper")) {
                this._selectedFloorZone = roomZone;
                try { localStorage.setItem("otis_floorplan_selected_zone", roomZone); } catch (_) { }
                applyZoneFilterToSvg(roomZone);
                updateWallPositions();
                updatePinPositions();
                root.querySelectorAll(".zone-pill").forEach((p) => p.classList.toggle("active", p.getAttribute("data-zone") === roomZone));
              }
            }
            if (this._selectedEditorRoomId === areaId) return;
            this._selectedEditorRoomId = areaId;
            this._render();
          };
        });

        // Promote .room-feature elements (Stairs, Pool & Patio, Covered Front Porch) above all rooms so neighbors never occlude them
        svgEl.querySelectorAll(".room-feature").forEach((fGrp) => {
          const parentRoom = fGrp.closest(".room-group");
          if (parentRoom) {
            const pRid = parentRoom.getAttribute("data-area-id");
            const pZone = parentRoom.getAttribute("data-zone") || "main";
            if (pRid) fGrp.setAttribute("data-area-id", pRid);
            fGrp.setAttribute("data-zone", pZone);
            const planContainer = parentRoom.closest("#plan-ground, #plan-upper") || parentRoom.parentElement;
            if (planContainer) {
              let overlay = planContainer.querySelector(":scope > .room-features-overlay");
              if (!overlay) {
                overlay = document.createElementNS("http://www.w3.org/2000/svg", "g");
                overlay.setAttribute("class", "room-features-overlay");
                planContainer.appendChild(overlay);
              }
              overlay.appendChild(fGrp);
            }
          }
        });

        // Bind draggable architectural features (Pool & Patio, Stairs, Covered Front Porch & Balcony)
        svgEl.querySelectorAll(".room-feature").forEach((fGrp) => {
          const roomId = fGrp.getAttribute("data-area-id") || fGrp.closest(".room-group")?.getAttribute("data-area-id");
          const parentRoom = roomId ? svgEl.querySelector(`.room-group[data-area-id="${roomId}"]`) : fGrp.closest(".room-group");
          const featKey = fGrp.getAttribute("data-feature");
          if (!roomId || !featKey) return;
          fGrp.style.pointerEvents = "all";
          fGrp.style.cursor = "grab";
          fGrp.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
          };
          fGrp.onpointerdown = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const fRect = fGrp.querySelector("rect");
            const startFx = parseFloat(fGrp.getAttribute("data-x") || fRect?.getAttribute("x") || 0);
            const startFy = parseFloat(fGrp.getAttribute("data-y") || fRect?.getAttribute("y") || 0);
            const startPt = getSvgPoint(svgEl, e.clientX, e.clientY);
            fGrp.style.cursor = "grabbing";
            try { fGrp.setPointerCapture(e.pointerId); } catch (_) { }

            const onFeatMove = (me) => {
              const curPt = getSvgPoint(svgEl, me.clientX, me.clientY);
              const nfx = Math.round((startFx + (curPt.x - startPt.x)) / 5) * 5;
              const nfy = Math.round((startFy + (curPt.y - startPt.y)) / 5) * 5;
              this._positionRoomFeatureSvg(fGrp, featKey, nfx, nfy);
              if (coordsHud) {
                coordsHud.style.display = "block";
                coordsHud.textContent = `📐 ${featKey.replace("_", " ").toUpperCase()} X: ${nfx}, Y: ${nfy}`;
              }
            };

            const onFeatUp = (ue) => {
              window.removeEventListener("pointermove", onFeatMove);
              window.removeEventListener("pointerup", onFeatUp);
              try { if (ue && ue.pointerId !== undefined) fGrp.releasePointerCapture(ue.pointerId); } catch (_) { }
              fGrp.style.cursor = "grab";
              const finalFx = parseFloat(fGrp.getAttribute("data-x") || startFx);
              const finalFy = parseFloat(fGrp.getAttribute("data-y") || startFy);
              const rRect = parentRoom.querySelector(".room-box, .room-rect");
              const rHdr = parentRoom.querySelector(".room-header, .room-label");
              const prevDirty = this._dirtyRooms[roomId] || {};
              this._dirtyRooms[roomId] = {
                ...prevDirty,
                id: roomId,
                x: prevDirty.x ?? Math.round(parseFloat(rRect?.getAttribute("x") || 0)),
                y: prevDirty.y ?? Math.round(parseFloat(rRect?.getAttribute("y") || 0)),
                width: prevDirty.width ?? Math.round(parseFloat(rRect?.getAttribute("width") || 160)),
                height: prevDirty.height ?? Math.round(parseFloat(rRect?.getAttribute("height") || 120)),
                name: prevDirty.name || rHdr?.textContent?.trim() || this._capabilityMap?.areas?.[roomId]?.name || roomId,
                features: {
                  ...(prevDirty.features || {}),
                  [featKey]: { x: Math.round(finalFx), y: Math.round(finalFy) },
                },
              };
              this._hasUnsavedLayout = true;
              const saveBtn = root.querySelector("#btn-save-layout");
              if (saveBtn) saveBtn.textContent = "💾 Save Changes *";
            };

            window.addEventListener("pointermove", onFeatMove);
            window.addEventListener("pointerup", onFeatUp);
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
              const inpName = root.querySelector("#inspector-room-name");
              const inpSubzones = root.querySelector("#inspector-room-subzones");
              if (inpX) inpX.value = Math.round(rx);
              if (inpY) inpY.value = Math.round(ry);
              if (inpW) inpW.value = Math.round(rw);
              if (inpH) inpH.value = Math.round(rh);
              if (inpName) {
                const hdrEl = selGrp.querySelector(".room-header, .room-label");
                inpName.value = dirty?.name || hdrEl?.textContent?.trim() || this._capabilityMap?.areas?.[this._selectedEditorRoomId]?.name || this._selectedEditorRoomId;
              }
              if (inpSubzones) {
                const pillsList = Array.isArray(dirty?.sub_zones)
                  ? dirty.sub_zones
                  : Array.from(selGrp.querySelectorAll(".subzone-pill")).map((p) =>
                    String(p.textContent || "").replace(/^\s*[▪•]\s*/, "").trim()
                  ).filter(Boolean);
                inpSubzones.value = pillsList.join("\n");
              }

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
                const hN = handleGrp.querySelector('[data-handle="n"]');
                const hNe = handleGrp.querySelector('[data-handle="ne"]');
                const hE = handleGrp.querySelector('[data-handle="e"]');
                const hSe = handleGrp.querySelector('[data-handle="se"]');
                const hS = handleGrp.querySelector('[data-handle="s"]');
                const hSw = handleGrp.querySelector('[data-handle="sw"]');
                const hW = handleGrp.querySelector('[data-handle="w"]');
                if (hNw) { hNw.setAttribute("cx", nx); hNw.setAttribute("cy", ny); }
                if (hN) { hN.setAttribute("cx", nx + nw / 2); hN.setAttribute("cy", ny); }
                if (hNe) { hNe.setAttribute("cx", nx + nw); hNe.setAttribute("cy", ny); }
                if (hE) { hE.setAttribute("cx", nx + nw); hE.setAttribute("cy", ny + nh / 2); }
                if (hSe) { hSe.setAttribute("cx", nx + nw); hSe.setAttribute("cy", ny + nh); }
                if (hS) { hS.setAttribute("cx", nx + nw / 2); hS.setAttribute("cy", ny + nh); }
                if (hSw) { hSw.setAttribute("cx", nx); hSw.setAttribute("cy", ny + nh); }
                if (hW) { hW.setAttribute("cx", nx); hW.setAttribute("cy", ny + nh / 2); }

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
                  ...(this._dirtyRooms[this._selectedEditorRoomId] || {}),
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
                if (e.target && e.target.closest && e.target.closest(".room-feature")) return;
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
                try { rect.setPointerCapture(e.pointerId); } catch (_) { }
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
                  try { rect.releasePointerCapture(e.pointerId); } catch (_) { }
                  this._resizingHandle = null;
                  clearSnapGuides();
                }
              };
              rect.onpointercancel = (e) => {
                if (this._resizingHandle && this._resizingHandle.type === "move") {
                  try { rect.releasePointerCapture(e.pointerId); } catch (_) { }
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
                  try { handle.setPointerCapture(e.pointerId); } catch (_) { }
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
                    try { handle.releasePointerCapture(e.pointerId); } catch (_) { }
                    this._resizingHandle = null;
                    clearSnapGuides();
                  }
                };
                handle.onpointercancel = (e) => {
                  if (this._resizingHandle && this._resizingHandle.type !== "move") {
                    try { handle.releasePointerCapture(e.pointerId); } catch (_) { }
                    this._resizingHandle = null;
                    clearSnapGuides();
                  }
                };
              });
            }
          }
        }
      } else {
        // --- Normal Interactive Viewer Mode (Room navigation) ---
        svgViewport.querySelectorAll(".room-group").forEach((grp) => {
          grp.style.cursor = "pointer";
          const areaId = grp.getAttribute("data-area-id") || grp.getAttribute("data-room-id");
          grp.onpointerenter = () => {
            if (!areaId) return;
            const shell = svgViewport.querySelector(`.floorplan-3d-room-shell[data-room-id="${areaId}"]`);
            if (shell) shell.classList.add("is-hovered");
          };
          grp.onpointerleave = () => {
            if (!areaId) return;
            const shell = svgViewport.querySelector(`.floorplan-3d-room-shell[data-room-id="${areaId}"]`);
            if (shell) shell.classList.remove("is-hovered");
          };
          grp.onclick = () => {
            if (areaId) {
              const area = this._capabilityMap?.areas?.[areaId];
              const slug = areaId.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "room";
              this._selectedRoomInfo = {
                areaId,
                name: area?.name || areaId,
                slug,
                zone: grp.getAttribute("data-zone") || "indoor",
                entities: area?.entities || [],
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
              const curPath = typeof window !== "undefined" ? window.location.pathname : "";
              const seg = curPath.split("/").filter(Boolean)[0] || "command-center";
              const path = `/${seg}/area_${slug}`;
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
        } catch (_) { }
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
        } catch (_) { }
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
        try { inspectorHeader.setPointerCapture(e.pointerId); } catch (_) { }
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
          try { inspectorHeader.releasePointerCapture(e.pointerId); } catch (_) { }
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
            const hN = handleGrp.querySelector('[data-handle="n"]');
            const hNe = handleGrp.querySelector('[data-handle="ne"]');
            const hE = handleGrp.querySelector('[data-handle="e"]');
            const hSe = handleGrp.querySelector('[data-handle="se"]');
            const hS = handleGrp.querySelector('[data-handle="s"]');
            const hSw = handleGrp.querySelector('[data-handle="sw"]');
            const hW = handleGrp.querySelector('[data-handle="w"]');
            if (hNw) { hNw.setAttribute("cx", nx); hNw.setAttribute("cy", ny); }
            if (hN) { hN.setAttribute("cx", nx + nw / 2); hN.setAttribute("cy", ny); }
            if (hNe) { hNe.setAttribute("cx", nx + nw); hNe.setAttribute("cy", ny); }
            if (hE) { hE.setAttribute("cx", nx + nw); hE.setAttribute("cy", ny + nh / 2); }
            if (hSe) { hSe.setAttribute("cx", nx + nw); hSe.setAttribute("cy", ny + nh); }
            if (hS) { hS.setAttribute("cx", nx + nw / 2); hS.setAttribute("cy", ny + nh); }
            if (hSw) { hSw.setAttribute("cx", nx); hSw.setAttribute("cy", ny + nh); }
            if (hW) { hW.setAttribute("cx", nx); hW.setAttribute("cy", ny + nh / 2); }
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

        const inpName = root.querySelector("#inspector-room-name");
        const inpSubzones = root.querySelector("#inspector-room-subzones");
        const newName = inpName ? inpName.value.trim() : areaName;
        const newSubzones = inpSubzones
          ? inpSubzones.value
            .split("\n")
            .map((s) => s.replace(/^\s*[▪•]\s*/, "").trim())
            .filter(Boolean)
          : undefined;

        if (selGrp) {
          const rLbl = selGrp.querySelector(".room-header, .room-label");
          const hasContainerBanner = Boolean(selGrp.querySelector(".container-shell, .container-banner"));
          const hdrYOff = hasContainerBanner ? 34 : 22;
          if (rLbl && newName) rLbl.textContent = newName;
          if (Array.isArray(newSubzones)) {
            selGrp.querySelectorAll(".subzone-pill").forEach((p) => p.remove());
            newSubzones.forEach((szTxt, sIdx) => {
              const pillEl = document.createElementNS("http://www.w3.org/2000/svg", "text");
              pillEl.setAttribute("x", nx + 16);
              pillEl.setAttribute("y", ny + hdrYOff + 18 + sIdx * 16);
              pillEl.setAttribute("class", "subzone-pill");
              pillEl.textContent = `▪ ${szTxt}`;
              if (rLbl && rLbl.nextSibling) {
                selGrp.insertBefore(pillEl, rLbl.nextSibling);
              } else {
                selGrp.appendChild(pillEl);
              }
            });
          }
        }

        const prevDirty = this._dirtyRooms[rid] || {};
        this._dirtyRooms[rid] = {
          ...prevDirty,
          id: rid,
          x: nx,
          y: ny,
          width: nw,
          height: nh,
          name: newName || areaName,
          ...(Array.isArray(newSubzones) ? { sub_zones: newSubzones } : {}),
        };
        this._hasUnsavedLayout = true;
        const saveBtn = root.querySelector("#btn-save-layout");
        if (saveBtn) saveBtn.textContent = "💾 Save Changes *";
        this._showToast(`Updated ${newName || areaName || rid}! Click Save Layout to persist.`);
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

    // Recalculate Floor Plan entities & layout (Companion card Floor Plan tab only)
    const btnRecalculateFloorplan = root.querySelector("#btn-recalculate-floorplan");
    if (btnRecalculateFloorplan) {
      btnRecalculateFloorplan.onclick = async () => {
        if (this._recalculatingFloorplan) return;
        this._recalculatingFloorplan = true;
        this._render();
        try {
          await this._hass.callService("otis_ai", "recalculate_floorplan", {
            preserve_custom_pins: true,
          });
          this._dirtyBadges = {};
          this._hasUnsavedLayout = false;
          this._floorplanSvg = null;
          await this._fetchData(true);
          await this._loadFloorplanSvg("/api/otis_ai/media/otis_floorplan.svg");
          this._showToast("Floor plan entities and locations recalculated!");
        } catch (err) {
          console.error("Failed to recalculate floor plan:", err);
          this._showToast(`Recalculate failed: ${err.message || err}`, true);
        } finally {
          this._recalculatingFloorplan = false;
          this._render();
        }
      };
    }

    const btnRegenerateFloorplan = root.querySelector("#btn-regenerate-floorplan");
    if (btnRegenerateFloorplan) {
      btnRegenerateFloorplan.onclick = async () => {
        if (this._regeneratingFloorplan) return;
        this._regeneratingFloorplan = true;
        this._regenProgressPercent = 5;
        this._regenProgressText = "Clearing previous floor plan & starting walkthrough analysis...";
        this._regenDiscoveredAreas = [];
        this._render();

        try {
          const svcRes = await this._hass.callService(
            "otis_ai",
            "generate_floorplan",
            { reset_layout: true, reanalyze_walkthrough: true, background: true },
            undefined,
            true,
            true
          );
          const respData = svcRes?.response || svcRes || {};
          if (!respData.background) {
            await this._finishRegenProgress(null);
            return;
          }
          this._startRegenPolling();
        } catch (err) {
          console.error("Failed to regenerate floor plan:", err);
          await this._finishRegenProgress(err.message || String(err));
        }
      };
    }

    // Canvas Editor Toolbar Controls
    const btnToggleEditor = root.querySelector("#btn-toggle-editor");
    if (btnToggleEditor) {
      btnToggleEditor.onclick = () => {
        this._editorActive = !this._editorActive;
        if (this._editorActive) {
          if (this._floorplanViewMode === "3d") {
            this._previousViewMode = "3d";
            this._floorplanViewMode = "2d";
          }
        } else {
          this._selectedEditorRoomId = null;
          if (this._previousViewMode === "3d") {
            this._floorplanViewMode = "3d";
            this._previousViewMode = null;
          }
        }
        this._render();
      };
    }
    const btnExitEditor = root.querySelector("#btn-exit-editor");
    if (btnExitEditor) {
      btnExitEditor.onclick = () => {
        this._editorActive = false;
        this._selectedEditorRoomId = null;
        if (this._previousViewMode === "3d") {
          this._floorplanViewMode = "3d";
          this._previousViewMode = null;
        }
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

    // Add Device Pin Modal & Search
    const btnOpenAddMarker = root.querySelector("#btn-open-add-marker");
    if (btnOpenAddMarker) {
      btnOpenAddMarker.onclick = () => {
        this._addMarkerModalOpen = true;
        this._addMarkerFilter = "";
        this._render();
      };
    }
    const addMarkerCloseBtn = root.querySelector("#add-marker-close-btn");
    if (addMarkerCloseBtn) {
      addMarkerCloseBtn.onclick = () => {
        this._addMarkerModalOpen = false;
        this._addMarkerFilter = "";
        this._render();
      };
    }
    const addMarkerBackdrop = root.querySelector("#add-marker-modal-backdrop");
    if (addMarkerBackdrop) {
      addMarkerBackdrop.onclick = (e) => {
        if (e.target === addMarkerBackdrop) {
          this._addMarkerModalOpen = false;
          this._addMarkerFilter = "";
          this._render();
        }
      };
    }
    const addMarkerSearch = root.querySelector("#add-marker-search-input");
    if (addMarkerSearch) {
      addMarkerSearch.oninput = (e) => {
        this._addMarkerFilter = e.target.value;
        this._render();
        setTimeout(() => {
          const inp = this.shadowRoot.getElementById("add-marker-search-input");
          if (inp) {
            inp.focus();
            inp.setSelectionRange(inp.value.length, inp.value.length);
          }
        }, 50);
      };
    }
    root.querySelectorAll(".btn-place-entity-pin").forEach((btn) => {
      btn.onclick = () => {
        const eid = btn.getAttribute("data-entity-id");
        if (eid) {
          let targetX = 340;
          let targetY = 260;
          let placedAreaName = "";

          const ent = (this._capabilityMap?.entities || []).find((e) => (typeof e === "string" ? e : e?.entity_id) === eid);
          const areaId = typeof ent === "object" ? ent?.area_id : null;
          if (areaId) {
            const svgEl = root.querySelector("#floorplan-viewport svg");
            const roomEl = svgEl ? (svgEl.querySelector(`#area-${areaId}`) || svgEl.querySelector(`[data-area-id="${areaId}"]`)) : null;
            if (roomEl) {
              const rect = roomEl.querySelector("rect");
              if (rect) {
                const rx = parseFloat(rect.getAttribute("x") || 0);
                const ry = parseFloat(rect.getAttribute("y") || 0);
                const rw = parseFloat(rect.getAttribute("width") || 200);
                const rh = parseFloat(rect.getAttribute("height") || 140);
                targetX = Math.round(rx + rw / 2);
                targetY = Math.round(ry + rh / 2);
                placedAreaName = (typeof ent === "object" && ent?.area_name) ? ent.area_name : areaId;
              }
            }
          }
          if (!placedAreaName && this._selectedFloorZone === "upper") {
            targetX = 600;
            targetY = 950;
          }

          this._dirtyBadges[eid] = {
            entity_id: eid,
            x: targetX,
            y: targetY,
          };
          this._hasUnsavedLayout = true;
          this._addMarkerModalOpen = false;
          this._addMarkerFilter = "";
          const msg = placedAreaName
            ? `📍 Dropped pin for ${eid} into ${placedAreaName}! Drag to fine-tune and click "Save Changes".`
            : `📍 Dropped pin for ${eid}! Drag to position and click "Save Changes".`;
          this._showToast(msg);
          this._render();
        }
      };
    });

    // Edit / Remove Marker Inspector Modal
    const editMarkerCloseBtn = root.querySelector("#edit-marker-close-btn");
    const editMarkerCancelBtn = root.querySelector("#btn-cancel-edit-marker");
    const editMarkerBackdrop = root.querySelector("#edit-marker-modal-backdrop");
    const closeEditMarker = () => {
      this._editMarkerModalOpen = false;
      this._selectedEditorEntityId = null;
      this._render();
    };
    if (editMarkerCloseBtn) editMarkerCloseBtn.onclick = closeEditMarker;
    if (editMarkerCancelBtn) editMarkerCancelBtn.onclick = closeEditMarker;
    if (editMarkerBackdrop) {
      editMarkerBackdrop.onclick = (e) => {
        if (e.target === editMarkerBackdrop) closeEditMarker();
      };
    }

    const btnDeleteMarker = root.querySelector("#btn-delete-marker");
    if (btnDeleteMarker) {
      btnDeleteMarker.onclick = () => {
        const eid = this._selectedEditorEntityId;
        if (eid) {
          this._dirtyBadges[eid] = {
            entity_id: eid,
            delete: true,
          };
          const bEl = svgEl ? svgEl.querySelector(`[data-entity-id="${eid}"]`) : null;
          if (bEl) bEl.remove();
          this._hasUnsavedLayout = true;
          this._editMarkerModalOpen = false;
          this._selectedEditorEntityId = null;
          this._showToast(`🗑️ Removed pin for ${eid}. Click "Save Changes" to persist.`);
          this._render();
        }
      };
    }

    const btnApplyCoordsMarker = root.querySelector("#btn-apply-coords-marker");
    if (btnApplyCoordsMarker) {
      btnApplyCoordsMarker.onclick = () => {
        const inpX = root.querySelector("#input-marker-x");
        const inpY = root.querySelector("#input-marker-y");
        const nx = inpX ? parseFloat(inpX.value) : 340;
        const ny = inpY ? parseFloat(inpY.value) : 260;
        const eid = this._selectedEditorEntityId;
        if (eid) {
          this._dirtyBadges[eid] = { entity_id: eid, x: nx, y: ny };
          const bEl = svgEl ? svgEl.querySelector(`[data-entity-id="${eid}"]`) : null;
          if (bEl) bEl.setAttribute("transform", `translate(${nx}, ${ny})`);
          this._hasUnsavedLayout = true;
          this._editMarkerModalOpen = false;
          this._selectedEditorEntityId = null;
          this._showToast(`Updated coordinates for ${eid}!`);
          this._render();
        }
      };
    }

    // Setup Guide Modal Events
    const guideCloseBtn = root.querySelector("#guide-modal-close-btn");
    const guideGotItBtn = root.querySelector("#btn-close-guide-modal");
    const guideBackdrop = root.querySelector("#guide-modal-backdrop");
    const closeGuide = () => {
      this._guideModalOpen = false;
      this._render();
    };
    if (guideCloseBtn) guideCloseBtn.onclick = closeGuide;
    if (guideGotItBtn) guideGotItBtn.onclick = closeGuide;
    if (guideBackdrop) {
      guideBackdrop.onclick = (e) => {
        if (e.target === guideBackdrop) closeGuide();
      };
    }
    const btnGuideAskAssist = root.querySelector("#btn-guide-ask-assist");
    if (btnGuideAskAssist && this._currentGuide) {
      btnGuideAskAssist.onclick = () => {
        const g = this._currentGuide;
        this._guideModalOpen = false;
        this._draftChatText = `How do I ${g.title.replace(/^Maturity Goal:\s*/i, "")}? Give me step-by-step guidance.`;
        this._activeTab = "chat";
        this._render();
        setTimeout(() => {
          const input = this.shadowRoot.getElementById("chat-input");
          if (input) {
            input.focus();
            if (input.setSelectionRange) input.setSelectionRange(input.value.length, input.value.length);
          }
        }, 100);
      };
    }

    // HACS Direct Links
    root.querySelectorAll(".btn-open-hacs").forEach((btn) => {
      btn.onclick = () => window.open("/hacs/integrations", "_blank");
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

    const walkthroughFileInput = root.querySelector("#walkthrough-file-input");
    const dropzone = root.querySelector("#walkthrough-dropzone");
    const dropzoneText = root.querySelector("#dropzone-selected-filename");
    const submitBtn = root.querySelector("#btn-submit-walkthrough");
    const spokenInput = root.querySelector("#spoken-order-input");

    if (spokenInput) {
      spokenInput.oninput = (e) => {
        this._spokenOrderOverride = e.target.value;
      };
    }

    if (dropzone && walkthroughFileInput) {
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

      dropzone.onclick = () => walkthroughFileInput.click();
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

      walkthroughFileInput.onchange = (e) => {
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
Object.assign(OtisCompanionCard.prototype, floorplanMixin, modalsMixin, tabsMixin);

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
            <label for="cfg-show-ignored">Show Ignored Recommendations</label>
            <div class="sub-label">Include previously dismissed suggestions with restore actions</div>
          </div>
          <input type="checkbox" id="cfg-show-ignored" data-config="show_ignored" ${this._config.show_ignored ? "checked" : ""}>
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
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
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
