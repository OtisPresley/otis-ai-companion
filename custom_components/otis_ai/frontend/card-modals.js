/** Modal and overlay renderers/handlers mixin for OtisCompanionCard. */
export const modalsMixin = {
  _renderAddMarkerModal() {
    if (!this._addMarkerModalOpen) return "";
    const query = (this._addMarkerFilter || "").toLowerCase().trim();

    // 1. Build a comprehensive map of all entities from capabilityMap and this._hass.states
    const entityMap = new Map();
    const rawEntities = this._capabilityMap?.entities || [];
    rawEntities.forEach((e) => {
      const eid = typeof e === "string" ? e : e?.entity_id;
      if (!eid) return;
      const dom = eid.split(".")[0];
      const aid = typeof e === "object" ? (e.area_id || "") : "";
      const aname = typeof e === "object" ? (e.area_name || "") : "";
      entityMap.set(eid, {
        entity_id: eid,
        name: (typeof e === "object" && e.name) ? e.name : eid,
        domain: dom,
        area_id: aid,
        area_name: aname,
      });
    });

    if (this._hass?.states) {
      Object.entries(this._hass.states).forEach(([eid, sObj]) => {
        if (!eid || eid.startsWith("automation.") || eid.startsWith("scene.") || eid.startsWith("script.")) {
          return;
        }
        if (!entityMap.has(eid)) {
          entityMap.set(eid, {
            entity_id: eid,
            name: sObj?.attributes?.friendly_name || eid,
            domain: eid.split(".")[0],
            area_id: "",
            area_name: "",
          });
        }
      });
    }

    // 2. Resolve room associations via capabilityMap areas and area registries
    const areasMap = this._capabilityMap?.areas || {};
    const entityToAreaId = {};
    const areaIdToName = {};

    Object.entries(areasMap).forEach(([aid, ainfo]) => {
      const aName = ainfo.name || aid.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      areaIdToName[aid] = aName;
      (ainfo.entities || []).forEach((eid) => {
        entityToAreaId[eid] = aid;
      });
    });

    entityMap.forEach((ent) => {
      if (!ent.area_id && entityToAreaId[ent.entity_id]) {
        ent.area_id = entityToAreaId[ent.entity_id];
      }
      if (ent.area_id && areaIdToName[ent.area_id]) {
        ent.area_name = areaIdToName[ent.area_id];
      }
    });

    // 3. Group by Room
    const roomGroups = {};
    Object.entries(areasMap).forEach(([aid, ainfo]) => {
      roomGroups[aid] = {
        id: aid,
        name: ainfo.name || aid.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        entities: [],
      };
    });
    const unassignedEntities = [];

    Array.from(entityMap.values()).forEach((ent) => {
      if (query) {
        const matches =
          ent.entity_id.toLowerCase().includes(query) ||
          ent.name.toLowerCase().includes(query) ||
          ent.domain.toLowerCase().includes(query) ||
          (ent.area_name && ent.area_name.toLowerCase().includes(query));
        if (!matches) return;
      }

      if (ent.area_id && roomGroups[ent.area_id]) {
        roomGroups[ent.area_id].entities.push(ent);
      } else if (ent.area_name) {
        const foundAid = Object.keys(roomGroups).find(
          (k) => roomGroups[k].name.toLowerCase() === ent.area_name.toLowerCase()
        );
        if (foundAid) {
          roomGroups[foundAid].entities.push(ent);
        } else {
          unassignedEntities.push(ent);
        }
      } else {
        unassignedEntities.push(ent);
      }
    });

    const activeRooms = Object.values(roomGroups)
      .filter((r) => r.entities.length > 0)
      .sort((a, b) => a.name.localeCompare(b.name));

    const totalMatching =
      activeRooms.reduce((acc, r) => acc + r.entities.length, 0) + unassignedEntities.length;

    const getDomainIcon = (d) => {
      switch (d) {
        case "light": return "💡";
        case "switch": return "🔌";
        case "climate": return "🌡️";
        case "media_player": return "📺";
        case "camera": return "📹";
        case "binary_sensor": return "🚶";
        case "sensor": return "📊";
        case "cover": return "🪟";
        case "lock": return "🔒";
        case "fan": return "💨";
        default: return "⚡";
      }
    };

    return `
      <div class="modal-overlay" id="add-marker-modal-backdrop">
        <div class="modal-card" style="max-width: 620px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;">
          <div class="modal-header">
            <div>
              <div class="modal-title"><span>➕</span><span>Add Device Pin to Floor Plan</span></div>
              <div class="modal-subtitle">Browse devices grouped by room or search to place on your floor plan (${totalMatching} devices)</div>
            </div>
            <button type="button" class="modal-close-btn" id="add-marker-close-btn">✕</button>
          </div>

          <!-- Real-Time Search Filter -->
          <div style="margin-bottom: 12px;">
            <input
              type="text"
              id="add-marker-search-input"
              placeholder="🔍 Search by room name, device, domain, or entity ID..."
              value="${this._addMarkerFilter || ""}"
              style="width: 100%; box-sizing: border-box; padding: 9px 14px; background: rgba(0,0,0,0.35); border: 1px solid var(--otis-surface-border); border-radius: 8px; color: var(--otis-text); font-size: 0.82rem;"
            />
          </div>

          <div style="overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 12px; padding-right: 4px;">
            ${totalMatching === 0
        ? `<div style="text-align: center; padding: 32px 0; color: var(--otis-text-muted); font-size: 0.82rem;">No devices matching "${this._escapeHtml(query)}".</div>`
        : ""
      }
            ${activeRooms
        .map(
          (r) => `
              <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--otis-surface-border); border-radius: 10px; padding: 10px 12px;">
                <div style="font-size: 0.78rem; font-weight: 700; color: var(--otis-primary); margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <span>${this._getRoomEmoji(r.name)}</span>
                    <span>${this._escapeHtml(r.name)}</span>
                  </div>
                  <span style="color: var(--otis-text-muted); font-size: 0.72rem; font-weight: 500;">${r.entities.length} devices</span>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                  ${r.entities.map(
            (e) => `
                    <button type="button" class="subview-chip btn-place-entity-pin" data-entity-id="${this._escapeHtml(e.entity_id)}" title="${this._escapeHtml(e.entity_id)}" style="font-size: 0.73rem; padding: 5px 9px; display: inline-flex; align-items: center; gap: 5px;">
                      <span>${getDomainIcon(e.domain)}</span>
                      <span style="font-weight: 600;">${this._escapeHtml(e.name !== e.entity_id ? e.name : e.entity_id)}</span>
                    </button>
                  `
          ).join("")}
                </div>
              </div>
            `
        )
        .join("")}

            ${unassignedEntities.length > 0
        ? `
              <div style="background: rgba(255,255,255,0.02); border: 1px dashed var(--otis-surface-border); border-radius: 10px; padding: 10px 12px;">
                <div style="font-size: 0.78rem; font-weight: 700; color: var(--otis-text-muted); margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <span>📦</span>
                    <span>Unassigned Devices</span>
                  </div>
                  <span style="color: var(--otis-text-muted); font-size: 0.72rem; font-weight: 500;">${unassignedEntities.length} devices</span>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                  ${unassignedEntities.slice(0, 100).map(
          (e) => `
                    <button type="button" class="subview-chip btn-place-entity-pin" data-entity-id="${this._escapeHtml(e.entity_id)}" title="${this._escapeHtml(e.entity_id)}" style="font-size: 0.73rem; padding: 5px 9px; display: inline-flex; align-items: center; gap: 5px;">
                      <span>${getDomainIcon(e.domain)}</span>
                      <span style="font-weight: 600;">${this._escapeHtml(e.name !== e.entity_id ? e.name : e.entity_id)}</span>
                    </button>
                  `
        ).join("")}
                </div>
              </div>
            `
        : ""
      }
          </div>
        </div>
      </div>
    `;
  },

  _renderEditMarkerModal() {
    if (!this._editMarkerModalOpen || !this._selectedEditorEntityId) return "";
    const eid = this._selectedEditorEntityId;
    const hassEntity = this._hass?.states?.[eid];
    const friendlyName = hassEntity?.attributes?.friendly_name || eid;
    const stateVal = hassEntity?.state || "active";
    const dirty = this._dirtyBadges[eid];
    const curX = dirty ? dirty.x : this._selectedEditorEntityCoords?.x || 340;
    const curY = dirty ? dirty.y : this._selectedEditorEntityCoords?.y || 260;
    const domain = eid.split(".")[0];

    const getDomainIcon = (d) => {
      switch (d) {
        case "light": return "💡";
        case "switch": return "🔌";
        case "climate": return "🌡️";
        case "media_player": return "📺";
        case "camera": return "📹";
        case "binary_sensor": return "🚶";
        case "sensor": return "📊";
        case "cover": return "🪟";
        case "lock": return "🔒";
        default: return "⚡";
      }
    };

    return `
      <div class="modal-overlay" id="edit-marker-modal-backdrop">
        <div class="modal-card" style="max-width: 440px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;">
          <div class="modal-header">
            <div>
              <div class="modal-title">
                <span>${getDomainIcon(domain)}</span>
                <span>Configure Entity Pin</span>
              </div>
              <div class="modal-subtitle">Adjust coordinates, drag position, or remove from blueprint</div>
            </div>
            <button type="button" class="modal-close-btn" id="edit-marker-close-btn">✕</button>
          </div>

          <div style="display: flex; flex-direction: column; gap: 12px; padding: 4px 0;">
            <!-- Entity Summary -->
            <div style="padding: 10px 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid var(--otis-surface-border); border-radius: 8px;">
              <div style="font-weight: 700; font-size: 0.88rem; color: var(--otis-primary); display: flex; align-items: center; justify-content: space-between;">
                <span>${this._escapeHtml(friendlyName)}</span>
                <span style="font-size: 0.7rem; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: rgba(56, 189, 248, 0.15); color: #38bdf8;">${this._escapeHtml(stateVal)}</span>
              </div>
              <div style="font-size: 0.72rem; color: var(--otis-text-muted); font-family: monospace; margin-top: 4px;">
                ${this._escapeHtml(eid)}
              </div>
            </div>

            <!-- Position Inputs -->
            <div style="display: flex; gap: 10px; align-items: center;">
              <div style="flex: 1;">
                <label style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase; color: var(--otis-text-muted);">X Position (px)</label>
                <input type="number" id="input-marker-x" value="${Math.round(curX)}" style="width: 100%; box-sizing: border-box; padding: 7px 10px; background: rgba(0,0,0,0.35); border: 1px solid var(--otis-surface-border); border-radius: 6px; color: var(--otis-text); font-size: 0.82rem; margin-top: 3px;" />
              </div>
              <div style="flex: 1;">
                <label style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase; color: var(--otis-text-muted);">Y Position (px)</label>
                <input type="number" id="input-marker-y" value="${Math.round(curY)}" style="width: 100%; box-sizing: border-box; padding: 7px 10px; background: rgba(0,0,0,0.35); border: 1px solid var(--otis-surface-border); border-radius: 6px; color: var(--otis-text); font-size: 0.82rem; margin-top: 3px;" />
              </div>
            </div>

            <div style="font-size: 0.73rem; color: var(--otis-text-muted); line-height: 1.4;">
              💡 <em>You can also click and drag this pin directly across any room on the blueprint canvas.</em>
            </div>
          </div>

          <div class="modal-actions" style="display: flex; gap: 8px; justify-content: space-between; margin-top: 8px;">
            <button type="button" class="btn-toolbar" id="btn-delete-marker" style="color: #ef4444; border-color: rgba(239, 68, 68, 0.4); background: rgba(239, 68, 68, 0.1); font-weight: 700;">
              🗑️ Remove Pin
            </button>
            <div style="display: flex; gap: 6px;">
              <button type="button" class="btn-modal-secondary" id="btn-cancel-edit-marker">
                Cancel
              </button>
              <button type="button" class="btn-modal-primary" id="btn-apply-coords-marker">
                Apply Coordinates
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  },

  _renderGuideModal() {
    if (!this._guideModalOpen || !this._currentGuide) return "";
    const g = this._currentGuide;

    return `
      <div class="modal-overlay" id="guide-modal-backdrop">
        <div class="modal-card" style="max-width: 620px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;">
          <div class="modal-header">
            <div>
              <div class="modal-title">
                <span>📖</span>
                <span>${this._escapeHtml(g.title || "Smart Home Setup Guide")}</span>
              </div>
              <div class="modal-subtitle">
                Smart Home Maturity Guidance • Pathway to 20/20 Standard
              </div>
            </div>
            <button type="button" class="modal-close-btn" id="guide-modal-close-btn">✕</button>
          </div>

          <!-- Guide Content -->
          <div class="guide-box" style="line-height: 1.5; font-size: 0.8rem; display: flex; flex-direction: column; gap: 10px;">
            <div>
              <div style="font-weight: 700; color: var(--otis-primary); margin-bottom: 4px;">
                🎯 Objective &amp; Impact:
              </div>
              <div style="color: var(--otis-text); line-height: 1.45;">
                ${g.description || ""}
              </div>
            </div>

            <div>
              <div style="font-weight: 700; color: var(--otis-primary); margin-bottom: 4px;">
                📋 Step-by-Step Implementation Guide:
              </div>
              <div style="color: var(--otis-text-muted); background: rgba(0, 0, 0, 0.25); padding: 10px 12px; border-radius: 8px; border: 1px solid var(--otis-surface-border); line-height: 1.5;">
                ${g.guide || g.description || "Follow the recommendations to complete setup."}
              </div>
            </div>
          </div>

          <div class="modal-actions" style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px;">
            <button type="button" class="btn-modal-secondary" id="btn-close-guide-modal">
              Got It
            </button>
            <button type="button" class="btn-modal-primary" id="btn-guide-ask-assist">
              💬 Ask Otis in Assist Co-Pilot
            </button>
          </div>
        </div>
      </div>
    `;
  },

  _renderWalkthroughModal() {
    return `
      <div class="modal-overlay" id="walkthrough-modal-backdrop">
        <div class="modal-card" style="max-width: 580px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;">
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
              value="${this._escapeHtml(this._spokenOrderOverride || "")}"
            />
          </div>

          ${this._uploadingVideo
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
              `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:999px;background:rgba(14,165,233,0.16);border:1px solid rgba(56,189,248,0.4);color:#e0f2fe;font-size:0.72rem;font-weight:600;">✓ Discovered ${this._escapeHtml(name)}</span>`
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
  },

  _isSubviewMode() {
    const mode = this._config?.mode;
    if (!mode || mode === "command_center") return false;
    return [
      "media_studio",
      "security",
      "climate",
      "energy",
      "room_view",
      "floorplan_studio",
      "floorplan_control",
    ].includes(mode);
  },

  _getAvailableUsers() {
    const userMap = new Map();
    // Strictly discover registered person.* entities from Home Assistant states
    const states = this._hass?.states || {};
    const ignored = new Set((this._userRules?.ignored_persons || []).map((x) => String(x).toLowerCase()));
    const profiles = this._userRules?.person_profiles || {};

    for (const eid in states) {
      if (eid.startsWith("person.")) {
        const cleanEid = eid.toLowerCase();
        if (ignored.has(cleanEid)) continue;
        if ((profiles[cleanEid] || profiles[eid])?.entity_type === "ignored") continue;
        const p = states[eid];
        const name = p.attributes?.friendly_name || eid.replace("person.", "").replace(/_/g, " ");
        userMap.set(cleanEid, { id: eid, name: name });
      }
    }
    return Array.from(userMap.values());
  },

  _renderThemeModal() {
    const isSubview = this._isSubviewMode();
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
        <div class="modal-card" style="max-width: 620px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;">
          <div class="modal-header">
            <div>
              <div class="modal-title">
                <span>🎨</span>
                <span>Dynamic AI Theme Studio</span>
              </div>
              <div class="modal-subtitle">
                ${isSubview ? "Personalize your appearance • Scoped strictly to your profile" : "Collaborative natural language styling & instant live theme application"}
              </div>
            </div>
            <button type="button" class="modal-close-btn" id="theme-modal-close-btn">✕</button>
          </div>

          ${isSubview
        ? `
            <!-- User Scope (Logged In User Only for Dashboard Views & Subviews) -->
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 8px; font-size: 0.78rem;">
              <span style="color: var(--otis-text-muted); font-weight: 600;">Theme Scope:</span>
              <span style="color: var(--otis-primary); font-weight: 700; display: inline-flex; align-items: center; gap: 5px;">
                👤 Current User (${this._escapeHtml(this._hass?.user?.name || "Logged In User")})
              </span>
            </div>
          `
        : `
            <!-- User Scope Selector (Otis AI Command Center Card: Available for All Uses) -->
            <div style="display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 8px; font-size: 0.78rem;">
              <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <span style="color: var(--otis-text-muted); font-weight: 600;">Apply Scope:</span>
                <div style="display: flex; gap: 14px; align-items: center; flex-wrap: wrap;">
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; color: var(--otis-text);">
                    <input type="radio" name="theme-scope" id="scope-current" value="current" ${this._themeApplyScope === "current" || !this._themeApplyScope ? "checked" : ""} />
                    Current User (${this._escapeHtml(this._hass?.user?.name || "Me")})
                  </label>
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; color: var(--otis-text);">
                    <input type="radio" name="theme-scope" id="scope-specific" value="specific" ${this._themeApplyScope === "specific" ? "checked" : ""} />
                    Specific User...
                  </label>
                  <label style="cursor: pointer; display: flex; align-items: center; gap: 6px; color: var(--otis-text);">
                    <input type="radio" name="theme-scope" id="scope-all" value="all" ${this._themeApplyScope === "all" ? "checked" : ""} />
                    All Users (Global Profile Sync)
                  </label>
                </div>
              </div>
              ${this._themeApplyScope === "specific"
          ? `
                <div style="display: flex; align-items: center; gap: 10px; margin-top: 4px; padding-top: 8px; border-top: 1px solid var(--otis-surface-border);">
                  <span style="color: var(--otis-text-muted); font-size: 0.75rem; font-weight: 600;">Select User:</span>
                  <select id="theme-user-select" style="flex: 1; padding: 6px 10px; border-radius: 6px; border: 1px solid var(--otis-surface-border); background: var(--otis-card-bg); color: var(--otis-text); font-size: 0.80rem;">
                    ${this._getAvailableUsers()
            .map(
              (u) => `
                      <option value="${this._escapeHtml(u.id)}" ${u.id === this._selectedThemeUserId ? "selected" : ""}>
                        👤 ${this._escapeHtml(u.name)}${u.id === this._hass?.user?.id ? " (You)" : ""}
                      </option>
                    `
            )
            .join("")}
                  </select>
                </div>
              `
          : ""
        }
            </div>
          `
      }

          <!-- AI Natural Language Generator Prompt -->
          <div class="guide-box" style="display: flex; flex-direction: column; gap: 8px;">
            <div style="font-weight: 700; font-size: 0.85rem; color: var(--otis-primary);">
              ✨ Collaborative AI Theme Generator
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
              <input
                type="text"
                id="theme-prompt-input"
                value="${this._escapeHtml(this._draftThemePrompt || '')}"
                placeholder="${this._isListeningTheme ? 'Listening... describe your dream theme' : 'e.g. Glowing neon cyan and purple with dark slate cards and 16px radius...'}"
                style="flex: 1; padding: 8px 12px; border-radius: 8px; border: 1px solid var(--otis-surface-border); background: var(--otis-surface); color: var(--otis-text); font-size: 0.82rem;"
              />
              ${this._isListeningTheme
        ? `
                <div class="voice-equalizer" title="Listening to speech..." style="margin-right: 4px;">
                  <span class="equalizer-bar"></span>
                  <span class="equalizer-bar"></span>
                  <span class="equalizer-bar"></span>
                  <span class="equalizer-bar"></span>
                  <span class="equalizer-bar"></span>
                </div>
              `
        : ""
      }
              <button type="button"
                class="btn-toolbar btn-theme-mic"
                id="btn-theme-voice-mic"
                title="${this._isListeningTheme ? 'Stop microphone' : 'Speak your theme prompt'}"
                style="padding: 7px 11px; border-radius: 8px; font-size: 0.80rem; display: inline-flex; align-items: center; gap: 5px; ${this._isListeningTheme ? 'background: #ef4444; border-color: #f87171; color: white;' : ''}"
              >
                <svg viewBox="0 0 24 24" style="width: 14px; height: 14px; fill: currentColor;"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>
                <span>${this._isListeningTheme ? 'Stop' : 'Speak'}</span>
              </button>
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
          ${customThemes.length > 0
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
  },

  _renderRulesModal() {
    const rules = this._rulesDraft || this._userRules || {
      persona: "concierge",
      tone: "friendly",
      response_length: "balanced",
      autonomy_level: "balanced",
      require_lock_confirmation: true,
      require_security_confirmation: true,
      quiet_hours_enabled: true,
      quiet_hours_start: "22:00",
      quiet_hours_end: "07:00",
      quiet_hours_volume: 25,
      preferred_speaker: "",
      custom_instructions: "",
      dashboard_layout: "modern_sections",
      navigation_style: "sleek_buttons",
      calendar_view: "listDay",
      primary_content_focus: "balanced",
    };

    const activeTab = this._rulesActiveTab || "dashboard";

    return `
      <div class="modal-overlay" id="rules-modal-backdrop">
        <div class="modal-card" style="max-width: 660px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;">
          <div class="modal-header">
            <div>
              <div class="modal-title">
                <span>⚙️</span>
                <span>Otis Persona & Household Rules</span>
              </div>
              <div class="modal-subtitle">
                Configure your smart home AI assistant's personality, autonomy safeguards, voice etiquette, and custom guidelines.
              </div>
            </div>
            <button type="button" class="modal-close-btn" id="rules-modal-close-btn">✕</button>
          </div>

          <!-- Tabs Navigation -->
          <div style="display: flex; gap: 8px; border-bottom: 1px solid var(--otis-surface-border); padding: 0 0 10px 0; margin-bottom: 16px; overflow-x: auto;">
            <button type="button" class="tab-btn ${activeTab === "wizard" ? "active" : ""}" id="rules-tab-wizard" style="font-size: 0.78rem; padding: 6px 12px; white-space: nowrap; font-weight: 600; border-color: ${activeTab === "wizard" ? "var(--otis-primary)" : "rgba(14,165,233,0.3)"}; background: ${activeTab === "wizard" ? "var(--otis-primary)" : "rgba(14,165,233,0.1)"}; color: ${activeTab === "wizard" ? "#fff" : "var(--otis-primary)"};">🧙‍♂️ Rules Wizard</button>
            <button type="button" class="tab-btn ${activeTab === "dashboard" ? "active" : ""}" id="rules-tab-dashboard" style="font-size: 0.78rem; padding: 6px 12px; white-space: nowrap;">📱 Dashboard & Layout</button>
            <button type="button" class="tab-btn ${activeTab === "persona" ? "active" : ""}" id="rules-tab-persona" style="font-size: 0.78rem; padding: 6px 12px; white-space: nowrap;">🎭 Persona & Tone</button>
            <button type="button" class="tab-btn ${activeTab === "safety" ? "active" : ""}" id="rules-tab-safety" style="font-size: 0.78rem; padding: 6px 12px; white-space: nowrap;">🛡️ Autonomy & Safety</button>
            <button type="button" class="tab-btn ${activeTab === "voice" ? "active" : ""}" id="rules-tab-voice" style="font-size: 0.78rem; padding: 6px 12px; white-space: nowrap;">🔊 Voice & Quiet Hours</button>
            <button type="button" class="tab-btn ${activeTab === "people" ? "active" : ""}" id="rules-tab-people" style="font-size: 0.78rem; padding: 6px 12px; white-space: nowrap;">👥 People & Pets</button>
            <button type="button" class="tab-btn ${activeTab === "instructions" ? "active" : ""}" id="rules-tab-instructions" style="font-size: 0.78rem; padding: 6px 12px; white-space: nowrap;">📝 Custom Instructions</button>
          </div>

          <!-- Tab Content (Scrollable) -->
          <div style="overflow-y: auto; flex: 1; padding-right: 4px; display: flex; flex-direction: column; gap: 14px;">
            ${activeTab === "wizard" ? this._renderRulesWizardTab(rules) : ""}
            ${activeTab === "dashboard" ? this._renderRulesDashboardTab(rules) : ""}
            ${activeTab === "persona" ? this._renderRulesPersonaTab(rules) : ""}
            ${activeTab === "safety" ? this._renderRulesSafetyTab(rules) : ""}
            ${activeTab === "voice" ? this._renderRulesVoiceTab(rules) : ""}
            ${activeTab === "people" ? this._renderRulesPeopleTab(rules) : ""}
            ${activeTab === "instructions" ? this._renderRulesInstructionsTab(rules) : ""}
          </div>

          <!-- Modal Footer -->
          <div style="display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding-top: 16px; margin-top: 10px; border-top: 1px solid var(--otis-surface-border);">
            <button type="button" class="subview-chip" id="rules-btn-cancel" style="padding: 6px 14px;">Cancel</button>
            <button type="button" class="subview-chip" id="rules-btn-save" style="background: var(--otis-primary, #0ea5e9); color: #fff; font-weight: 600; padding: 6px 18px; border: none;">
              ${this._savingRules ? "Saving..." : "Save Preferences"}
            </button>
          </div>
        </div>
      </div>
    `;
  },

  _renderRulesDashboardTab(rules) {
    const rawLayout = rules.dashboard_layout || "modern_sections";
    const currentLayout = rawLayout === "classic_grid" ? "classic" : rawLayout;
    const currentNav = rules.navigation_style || "sleek_buttons";
    const currentCal = rules.calendar_view || "listDay";
    const currentFocus = rules.primary_content_focus || "balanced";

    const layouts = [
      {
        id: "modern_sections",
        emoji: "📱",
        name: "Modern Responsive Sections",
        desc: "Adaptive mobile-first layout. Single touch-friendly column on phones, 2 columns on tablets, multi-column on desktop.",
      },
      {
        id: "compact",
        emoji: "⚡",
        name: "Compact High-Density Sections",
        desc: "Dense 4-column section grid with tighter card spacing and studio headers for power-user screens.",
      },
      {
        id: "classic",
        emoji: "📊",
        name: "Classic Card Grid",
        desc: "Traditional multi-column card grid for users who prefer standard Home Assistant masonry columns.",
      },
    ];

    const navStyles = [
      {
        id: "sleek_buttons",
        emoji: "🔘",
        name: "Sleek Touch Buttons",
        desc: "Balanced 2-column touch-friendly navigation buttons with contextual room icons.",
      },
      {
        id: "standard_grid",
        emoji: "🗂️",
        name: "Standard Grid Cards",
        desc: "Square 3-column grid buttons across rooms and studios.",
      },
      {
        id: "compact_pills",
        emoji: "💊",
        name: "Compact Navigation Pills",
        desc: "High-density 4-column compact buttons and rounded pill chips in Studio headers.",
      },
    ];

    const calViews = [
      {
        id: "listDay",
        emoji: "📋",
        name: "Agenda Daily List",
        desc: "Readable list of upcoming events and times. Scales cleanly on mobile phones without overlapping numbers.",
      },
      {
        id: "month",
        emoji: "📅",
        name: "Full Month Grid",
        desc: "Traditional calendar month matrix with day indicators.",
      },
    ];

    return `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div>
          <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">Select Dashboard Layout:</div>
          <div style="font-size: 0.74rem; color: var(--otis-text-muted); margin-top: 2px;">
            Choose how your Home Command Center and Studio dashboards adapt across phone, tablet, and desktop screens.
          </div>
        </div>

        <div class="persona-grid">
          ${layouts
        .map(
          (l) => `
            <div class="persona-card ${currentLayout === l.id ? "selected" : ""}" data-dashboard-layout="${l.id}">
              <div class="persona-title">
                <span>${l.emoji}</span>
                <span>${l.name}</span>
              </div>
              <div class="persona-desc">${l.desc}</div>
            </div>
          `
        )
        .join("")}
        </div>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 4px;">Navigation Button Style:</div>
        <div class="persona-grid">
          ${navStyles
        .map(
          (n) => `
            <div class="persona-card ${currentNav === n.id ? "selected" : ""}" data-navigation-style="${n.id}">
              <div class="persona-title">
                <span>${n.emoji}</span>
                <span>${n.name}</span>
              </div>
              <div class="persona-desc">${n.desc}</div>
            </div>
          `
        )
        .join("")}
        </div>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 4px;">Schedule & Calendar Display:</div>
        <div class="persona-grid">
          ${calViews
        .map(
          (c) => `
            <div class="persona-card ${currentCal === c.id ? "selected" : ""}" data-calendar-view="${c.id}">
              <div class="persona-title">
                <span>${c.emoji}</span>
                <span>${c.name}</span>
              </div>
              <div class="persona-desc">${c.desc}</div>
            </div>
          `
        )
        .join("")}
        </div>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 4px;">Content Priority:</div>
        <div class="rules-setting-row">
          <div>
            <div class="rules-setting-label">Primary Dashboard Focus</div>
            <div class="rules-setting-desc">Sets the arrangement order of studios, schedule, and room controls.</div>
          </div>
          <select id="rules-input-content-focus" style="padding: 6px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.8rem;">
            <option value="balanced" ${currentFocus === "balanced" ? "selected" : ""}>Balanced (Launchpad, Schedule, Rooms)</option>
            <option value="studios_first" ${currentFocus === "studios_first" ? "selected" : ""}>Quick Navigation First</option>
            <option value="glance_first" ${currentFocus === "glance_first" ? "selected" : ""}>Schedule & Weather First</option>
          </select>
        </div>

        <div class="rules-setting-row" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid var(--otis-surface-border); border-radius: 8px;">
          <div>
            <div class="rules-setting-label">Contextual Room Occupancy Cards</div>
            <div class="rules-setting-desc">Display dynamic room presence & activity cards in Command Center when areas are occupied.</div>
          </div>
          <input type="checkbox" id="rules-input-presence-room-cards" ${rules.presence_room_cards !== false ? "checked" : ""} style="cursor: pointer; width: 18px; height: 18px; accent-color: var(--otis-primary);">
        </div>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 6px;">Proactive Recommendations & Feed:</div>
        <div class="rules-setting-row" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid var(--otis-surface-border); border-radius: 8px;">
          <div>
            <div class="rules-setting-label">Show Ignored Recommendations</div>
            <div class="rules-setting-desc">Display previously dismissed recommendations in the feed with a restore action.</div>
          </div>
          <input type="checkbox" id="rules-input-show-ignored" ${rules.show_ignored_recommendations ? "checked" : ""} style="cursor: pointer; width: 18px; height: 18px; accent-color: var(--otis-primary);">
        </div>
        <div class="rules-setting-row" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid var(--otis-surface-border); border-radius: 8px;">
          <div>
            <div class="rules-setting-label">Dismissed Recommendations</div>
            <div class="rules-setting-desc">Currently hiding <strong>${(rules.dismissed_recommendation_ids || []).length}</strong> recommendation(s) across your home.</div>
          </div>
          <button type="button" class="btn-subtle-toggle" id="rules-btn-reset-dismissed" ${(rules.dismissed_recommendation_ids || []).length === 0 ? "disabled" : ""}>
            ↺ Reset All Ignored
          </button>
        </div>

        <div style="margin-top: 6px; padding: 12px; background: rgba(14, 165, 233, 0.08); border: 1px solid rgba(14, 165, 233, 0.25); border-radius: 8px; display: flex; align-items: center; justify-content: space-between;">
          <div>
            <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">Regenerate All Dashboards</div>
            <div style="font-size: 0.74rem; color: var(--otis-text-muted); margin-top: 2px;">
              Rebuild Command Center, all Studios, and Room subviews from scratch using active layout preferences.
            </div>
          </div>
          <button type="button" class="subview-chip" id="rules-btn-regenerate-dashboards" style="background: var(--otis-primary); color: #fff; font-weight: 600; padding: 7px 14px; border: none; white-space: nowrap; cursor: pointer;">
            ⚡ Regenerate Now
          </button>
        </div>
      </div>
    `;
  },

  _renderRulesPersonaTab(rules) {
    const currentPersona = rules.persona || "concierge";
    const currentTone = rules.tone || "friendly";
    const currentLength = rules.response_length || "balanced";

    const personas = [
      {
        id: "concierge",
        emoji: "🛎️",
        name: "Friendly Concierge",
        desc: "Warm, proactive, and thoughtful. Suggests helpful automation tips and guides you through smart home enhancements.",
      },
      {
        id: "butler",
        emoji: "🎩",
        name: "Professional Butler",
        desc: "Formal, discreet, and impeccably polite. Dedicated to perfection, privacy, and understated execution.",
      },
      {
        id: "minimalist",
        emoji: "⚡",
        name: "Technical Minimalist",
        desc: "Ultra-concise, direct, and telegraphic. Delivers raw answers and fast actions with zero conversational fluff.",
      },
      {
        id: "custom",
        emoji: "🛠️",
        name: "Custom Persona",
        desc: "Tailored directly by your personal household instructions, quirks, nicknames, and behavioral rules.",
      },
    ];

    return `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">Select Assistant Persona:</div>
        <div class="persona-grid">
          ${personas
        .map(
          (p) => `
            <div class="persona-card ${currentPersona === p.id ? "selected" : ""}" data-persona-id="${p.id}">
              <div class="persona-title">
                <span>${p.emoji}</span>
                <span>${p.name}</span>
              </div>
              <div class="persona-desc">${p.desc}</div>
            </div>
          `
        )
        .join("")}
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 6px;">
          <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start;">
            <div class="rules-setting-label">Conversational Tone:</div>
            <select id="rules-input-tone" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);">
              <option value="friendly" ${currentTone === "friendly" ? "selected" : ""}>Warm & Friendly</option>
              <option value="formal" ${currentTone === "formal" ? "selected" : ""}>Formal & Respectful</option>
              <option value="concise" ${currentTone === "concise" ? "selected" : ""}>Ultra-Concise</option>
              <option value="witty" ${currentTone === "witty" ? "selected" : ""}>Witty & Lighthearted</option>
            </select>
          </div>

          <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start;">
            <div class="rules-setting-label">Response Length:</div>
            <select id="rules-input-length" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);">
              <option value="concise" ${currentLength === "concise" ? "selected" : ""}>Concise (1-2 sentences)</option>
              <option value="balanced" ${currentLength === "balanced" ? "selected" : ""}>Balanced (Default)</option>
              <option value="detailed" ${currentLength === "detailed" ? "selected" : ""}>Detailed & Explanatory</option>
            </select>
          </div>
        </div>
      </div>
    `;
  },

  _renderRulesSafetyTab(rules) {
    const autonomy = rules.autonomy_level || "balanced";
    const requireLock = rules.require_lock_confirmation !== false;
    const requireSec = rules.require_security_confirmation !== false;

    const tiers = [
      {
        id: "high",
        badge: "🟢 High Autonomy",
        desc: "Acts immediately on all requests. Executes state changes, locks, and routines with zero redundant confirmation.",
      },
      {
        id: "balanced",
        badge: "🟡 Balanced with Safeguards",
        desc: "Proactively controls lighting, media, and climate, but requires explicit confirmation before deadbolts or alarm panel changes.",
      },
      {
        id: "strict",
        badge: "🔴 Strict Confirmation",
        desc: "Always asks for explicit confirmation before changing any device states or firing automations.",
      },
    ];

    return `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">Autonomy & Safety Policy:</div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          ${tiers
        .map(
          (t) => `
            <div class="persona-card ${autonomy === t.id ? "selected" : ""}" data-autonomy-tier="${t.id}">
              <div class="persona-title">${t.badge}</div>
              <div class="persona-desc">${t.desc}</div>
            </div>
          `
        )
        .join("")}
        </div>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 6px;">Confirmation Guardrails:</div>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <label class="rules-setting-row" style="cursor: pointer;">
            <div>
              <div class="rules-setting-label">Require confirmation for Door Deadbolts</div>
              <div class="rules-setting-desc">Otis asks before locking or unlocking smart deadbolts.</div>
            </div>
            <input type="checkbox" id="rules-input-lock-confirm" ${requireLock ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
          </label>

          <label class="rules-setting-row" style="cursor: pointer;">
            <div>
              <div class="rules-setting-label">Require confirmation for Perimeter Security & Alarms</div>
              <div class="rules-setting-desc">Otis asks before arming or disarming Alarmo / security panels.</div>
            </div>
            <input type="checkbox" id="rules-input-sec-confirm" ${requireSec ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
          </label>
        </div>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 8px;">Assist Co-Pilot Reasoning Timeout:</div>
        <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 8px;">
          <div>
            <div class="rules-setting-label">Reasoning &amp; Failover Timeout</div>
            <div class="rules-setting-desc">Maximum seconds Otis will wait for cloud LLM reasoning before transparently cascading to the next agent or local edge LLM.</div>
          </div>
          <div style="display: flex; align-items: center; gap: 10px; width: 100%;">
            <input type="number" id="rules-input-reasoning-timeout" min="10" max="300" step="5" value="${rules.reasoning_timeout || (this._capabilityMap && this._capabilityMap.reasoning_timeout) || (this._config && this._config.reasoning_timeout) || 60}" style="width: 90px; padding: 6px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
            <span style="font-size: 0.78rem; color: var(--otis-text-muted);">seconds (default: 60s)</span>
          </div>
          <div style="font-size: 0.72rem; color: var(--otis-text-muted);">
            Configurable system-wide in <em>Settings ➔ Devices &amp; Services ➔ Otis AI Companion ➔ Configure</em>.
          </div>
        </div>
      </div>
    `;
  },

  _renderRulesVoiceTab(rules) {
    const quietEnabled = rules.quiet_hours_enabled !== false;
    const quietStart = rules.quiet_hours_start || "22:00";
    const quietEnd = rules.quiet_hours_end || "07:00";
    const quietVol = rules.quiet_hours_volume !== undefined ? rules.quiet_hours_volume : 25;
    const preferredSpeaker = rules.preferred_speaker || "";
    const audioFollowEnabled = rules.audio_follow_enabled !== false;
    const voiceAnnouncementsEnabled = rules.voice_announcements_enabled !== false;
    const voiceFilterPassersby = rules.voice_filter_passersby !== false;

    return `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">Proactive Voice Announcements & Camera Intelligence:</div>

        <label class="rules-setting-row" style="cursor: pointer;">
          <div>
            <div class="rules-setting-label">Proactive Voice Announcements</div>
            <div class="rules-setting-desc">Spoken alerts on speakers for arriving visitors, perimeter security alerts, and door opening events.</div>
          </div>
          <input type="checkbox" id="rules-input-voice-announcements-enabled" ${voiceAnnouncementsEnabled ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
        </label>

        <label class="rules-setting-row" style="cursor: pointer;">
          <div>
            <div class="rules-setting-label">Filter Sidewalk & Street Passersby</div>
            <div class="rules-setting-desc">Suppress voice announcements for pedestrian tracks moving across perimeter cameras without lingering or entering.</div>
          </div>
          <input type="checkbox" id="rules-input-voice-filter-passersby" ${voiceFilterPassersby ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
        </label>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 4px;">Spatial Audio Follow-Me:</div>

        <label class="rules-setting-row" style="cursor: pointer;">
          <div>
            <div class="rules-setting-label">Enable Audio Follow-Me</div>
            <div class="rules-setting-desc">Automatically migrates active music playback to whichever room you walk into based on multi-sensor presence tracking.</div>
          </div>
          <input type="checkbox" id="rules-input-audio-follow-enabled" ${audioFollowEnabled ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
        </label>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 6px;">Quiet Hours Etiquette:</div>

        <label class="rules-setting-row" style="cursor: pointer;">
          <div>
            <div class="rules-setting-label">Enable Quiet Hours</div>
            <div class="rules-setting-desc">Ducks voice announcements and lowers audio playback volume during sleeping hours.</div>
          </div>
          <input type="checkbox" id="rules-input-quiet-enabled" ${quietEnabled ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
        </label>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start;">
            <div class="rules-setting-label">Quiet Hours Start:</div>
            <input type="time" id="rules-input-quiet-start" value="${this._escapeHtml(quietStart)}" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
          </div>

          <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start;">
            <div class="rules-setting-label">Quiet Hours End:</div>
            <input type="time" id="rules-input-quiet-end" value="${this._escapeHtml(quietEnd)}" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
          </div>
        </div>

        <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 8px;">
          <div style="display: flex; justify-content: space-between; width: 100%; align-items: center;">
            <div class="rules-setting-label">Max Spoken Volume during Quiet Hours:</div>
            <span id="rules-vol-val" style="font-weight: 700; font-size: 0.82rem; color: var(--otis-primary);">${quietVol}%</span>
          </div>
          <input type="range" id="rules-input-quiet-vol" min="5" max="100" value="${quietVol}" style="width: 100%; cursor: pointer;" />
        </div>

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 6px;">Voice Endpoint:</div>
        <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start;">
          <div class="rules-setting-label">Preferred Spoken Speaker / Room:</div>
          <div class="rules-setting-desc">Primary speaker used for proactive vocal alerts (e.g., media_player.great_room or Great Room). Leave blank for auto.</div>
          <input type="text" id="rules-input-speaker" value="${this._escapeHtml(preferredSpeaker)}" placeholder="e.g. media_player.great_room or Study" style="width: 100%; padding: 6px 8px; margin-top: 6px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
        </div>

        ${(() => {
        const mediaTopo = this._capabilityMap?.media_topology || {};
        const studioData = this._mediaStudioData || {};
        const sharedSources = studioData.shared_sources || mediaTopo.shared_sources || [];
        const candidatePlayers = this._getResolvedCandidatePlayers(studioData, mediaTopo);
        const effectiveMappings = {
          ...(mediaTopo.input_mappings || {}),
          ...(studioData.effective_mappings || {}),
          ...(rules.media_input_mappings || {}),
        };
        const unjoinInput = rules.media_unjoin_input || studioData.unjoin_input || "None";
        const filteredInputs = sharedSources.filter((s) => s && s.toLowerCase() !== unjoinInput.toLowerCase());
        if (filteredInputs.length === 0) return "";
        return `
            <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 8px;">🔗 Matrix Input-to-Player Mapping (Separate Speakers &amp; Streamers):</div>
            <div style="font-size: 0.73rem; color: var(--otis-text-muted); line-height: 1.4;">
              Map physical amplifier/matrix inputs (Control4 Matrix Amp, Sonos, Heos, etc.) to the upstream streaming media player connected to each input (Music Assistant, Alexa Bridge, Plex, VLC, etc.).
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px; background: rgba(0,0,0,0.18); padding: 10px; border-radius: 8px; border: 1px solid var(--otis-surface-border);">
              ${filteredInputs
            .map((inpName) => {
              const mappedEid = effectiveMappings[inpName] || "";
              return `
                    <div style="display: grid; grid-template-columns: minmax(120px, 1fr) 2fr; gap: 10px; align-items: center;">
                      <span style="font-size: 0.78rem; font-weight: 600; color: var(--otis-text);">🔌 ${this._escapeHtml(inpName)}</span>
                      <select class="rules-media-mapping-select" data-input-name="${this._escapeHtml(inpName)}" style="width: 100%; padding: 5px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;">
                        <option value="">-- Unmapped / Auto-Detect --</option>
                        ${candidatePlayers
                  .map(
                    (cp) => `
                          <option value="${this._escapeHtml(cp.entity_id)}" ${mappedEid === cp.entity_id ? "selected" : ""}>
                            🎵 ${this._escapeHtml(cp.name)} (${this._escapeHtml(cp.entity_id)})
                          </option>
                        `
                  )
                  .join("")}
                      </select>
                    </div>
                  `;
            })
            .join("")}
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06);">
                <div>
                  <div style="font-size: 0.72rem; color: var(--otis-text-muted); margin-bottom: 3px;">Unjoin / Idle Input Name:</div>
                  <input type="text" id="rules-input-media-unjoin" value="${this._escapeHtml(unjoinInput)}" placeholder="None" style="width: 100%; box-sizing: border-box; padding: 5px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;" />
                </div>
                <div>
                  <div style="font-size: 0.72rem; color: var(--otis-text-muted); margin-bottom: 3px;">Household Default Zone:</div>
                  <select id="rules-input-media-default-zone" style="width: 100%; padding: 5px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;">
                    <option value="">-- Auto (Active Zone) --</option>
                    ${(() => {
            const zoneMap = new Map();
            (studioData.zones || mediaTopo.matrix_zones || []).forEach((z) => {
              const eid = typeof z === "string" ? z : z.entity_id;
              if (eid) zoneMap.set(eid, z.name || eid);
            });
            if (this._hass && this._hass.states) {
              Object.keys(this._hass.states).forEach((eid) => {
                if (eid.startsWith("media_player.") && !zoneMap.has(eid)) {
                  const st = this._hass.states[eid];
                  const fn = st?.attributes?.friendly_name || eid;
                  if (fn.toLowerCase().includes("zone") || eid.includes("zone_")) {
                    zoneMap.set(eid, fn);
                  }
                }
              });
            }
            return Array.from(zoneMap.entries())
              .map(
                ([zeid, zname]) => `
                        <option value="${this._escapeHtml(zeid)}" ${(rules.media_default_zone || studioData.household_default_zone) === zeid ? "selected" : ""}>
                          🔊 ${this._escapeHtml(zname)}
                        </option>
                      `
              )
              .join("");
          })()}
                  </select>
                </div>
              </div>
            </div>
          `;
      })()}

        <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary); margin-top: 10px;">Multi-Agent Specialists & Voice Satellites:</div>
        <div style="background: rgba(14,165,233,0.06); border: 1px solid rgba(14,165,233,0.2); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 8px;">
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem;">
            <span style="font-weight: 600;">Active Specialists:</span>
            <span style="color: var(--otis-primary); font-weight: bold;">5 Coordinated Personas</span>
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 6px;">
            <span class="badge" style="background: rgba(14,165,233,0.15); color: var(--otis-primary); padding: 2px 8px; border-radius: 4px; font-size: 0.72rem;">👑 Executive Butler</span>
            <span class="badge" style="background: rgba(239,68,68,0.15); color: #ef4444; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem;">🛡️ Sentinel Security</span>
            <span class="badge" style="background: rgba(34,197,94,0.15); color: #22c55e; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem;">⚡ Energy Architect</span>
            <span class="badge" style="background: rgba(168,85,247,0.15); color: #a855f7; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem;">🎵 Spatial Media</span>
            <span class="badge" style="background: rgba(245,158,11,0.15); color: #f59e0b; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem;">⚙️ Automation Engineer</span>
          </div>
          <div style="font-size: 0.74rem; color: var(--otis-text-secondary); margin-top: 4px;">
            Acoustic presence-fused arbitration deduplicates simultaneous voice triggers across satellites using BLE, mmWave, and RSSI metrics.
          </div>
        </div>
      </div>
    `;
  },

  _generateStructuredRulesText() {
    const w = this._wizardState || {};
    const lines = [];

    lines.push("### Household & Schedule");
    if (w.residents) lines.push(`- Primary Residents: ${w.residents}.`);
    if (w.workHours) lines.push(`- Work-from-Home Routine: ${w.workHours}.`);
    if (w.sleepHabits) lines.push(`- Sleep & Bed Navigation: ${w.sleepHabits}.`);

    lines.push("\n### Guest Mode & Entertaining");
    lines.push("- When Guest Mode is ON:");
    if (w.guestLockCode) lines.push(`  * Add temporary code '${w.guestLockCode}' to exterior deadbolts for guest access.`);
    if (w.guestDelayedOff) lines.push(`  * Delay automatic bedtime lighting turn-off until ${w.guestDelayedOff}.`);
    if (w.guestClimateComfort) lines.push("  * Maintain comfortable ambient climate in guest suites.");
    if (w.holidaySwitches) lines.push("  * Coordinate holiday lighting & seasonal outlets.");
    lines.push("- When Guest Mode is OFF:");
    if (w.guestLockCode) lines.push(`  * Delete temporary guest code '${w.guestLockCode}' from deadbolts.`);

    lines.push("\n### Security & Perimeter Safeguards");
    if (w.requireDeadboltConfirm) lines.push("- Always require explicit spoken confirmation before unlocking exterior deadbolts.");
    if (w.requireAlarmConfirm) lines.push("- Always require explicit spoken confirmation before changing alarm control panel arm states.");
    if (w.garageAlertMinutes) lines.push(`- Alert if garage door remains open longer than ${w.garageAlertMinutes} minutes after sunset.`);
    if (w.perimeterCameraAlerts) lines.push("- Monitor perimeter cameras for unrecognized evening activity.");

    lines.push("\n### Audio & Matrix Media");
    if (w.matrixRouting) lines.push("- Multi-zone audio: Route upstream bridge streamers (media_player.bridge) to active room zones.");
    if (w.voiceDucking) lines.push("- Spatially duck background music zones during Voice Assist or vocal announcements.");
    lines.push(`- Enforce quiet hours between ${w.quietHoursStart || "22:00"} and ${w.quietHoursEnd || "07:00"} with maximum volume capped at ${w.quietVolume || 25}%.`);

    return lines.join("\n");
  },

  _renderRulesWizardTab(rules) {
    const step = this._wizardStep || 1;
    const w = this._wizardState || {};

    const steps = [
      { num: 1, label: "🏡 Household & Habits" },
      { num: 2, label: "👥 Guest Mode" },
      { num: 3, label: "🔒 Security & Perimeter" },
      { num: 4, label: "🎵 Audio & Media" },
      { num: 5, label: "✨ Review & Apply" },
    ];

    return `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <!-- Wizard Stepper Indicator -->
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 8px 12px; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid var(--otis-surface-border); overflow-x: auto;">
          ${steps
        .map(
          (s) => `
            <div class="wizard-step-pill" data-step-nav="${s.num}" style="display: flex; align-items: center; gap: 6px; font-size: 0.74rem; font-weight: ${step === s.num ? "700" : "500"}; color: ${step === s.num ? "#fff" : step > s.num ? "var(--otis-primary)" : "var(--otis-text-muted)"}; background: ${step === s.num ? "var(--otis-primary)" : "transparent"}; padding: 4px 10px; border-radius: 6px; cursor: pointer; white-space: nowrap;">
              <span>${step > s.num ? "✓" : s.num}</span>
              <span>${s.label}</span>
            </div>
          `
        )
        .join("")}
        </div>

        <!-- Step 1: Household & Habits -->
        ${step === 1
        ? `
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div style="font-size: 0.88rem; font-weight: 700; color: var(--otis-primary);">Step 1: Household Members & Daily Habits</div>
            <div style="font-size: 0.75rem; color: var(--otis-text-muted);">Define who lives in the home and their primary schedules so Otis can coordinate rooms and routines contextually.</div>

            <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 8px;">
              <div class="rules-setting-label">Primary Residents / Household Members:</div>
              <div style="font-size: 0.72rem; color: var(--otis-text-muted);">Select active residents from Home Assistant users or enter names below:</div>
              <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                ${(() => {
          const avail = this._getAvailableUsers();
          const curRes = (w.residents || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
          return avail
            .map((u) => {
              const cleanName = u.name || u.id;
              const isSel = curRes.some(r => r === cleanName.toLowerCase() || r === u.id.toLowerCase() || cleanName.toLowerCase().includes(r) || r.includes(cleanName.toLowerCase()));
              return `
                        <button type="button" class="subview-chip wiz-resident-chip ${isSel ? 'active' : ''}" data-user-name="${this._escapeHtml(cleanName)}" style="padding: 4px 10px; font-size: 0.75rem; border-radius: 16px; cursor: pointer; ${isSel ? 'background: var(--otis-primary); color: #fff; border-color: var(--otis-primary);' : ''}">
                          ${isSel ? '✓ ' : '+ '}👤 ${this._escapeHtml(cleanName)}
                        </button>
                      `;
            })
            .join("");
        })()}
              </div>
              <input type="text" id="wiz-residents" value="${this._escapeHtml(w.residents || "")}" placeholder="e.g. Alice, Bob" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
            </div>

            <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 6px;">
              <div class="rules-setting-label">Work-From-Home Rooms & Active Hours:</div>
              <input type="text" id="wiz-work" value="${this._escapeHtml(w.workHours || "")}" placeholder="e.g. Primary resident works in Study from 9:00 AM to 5:00 PM" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
            </div>

            <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 6px;">
              <div class="rules-setting-label">Sleep & Bed Navigation Preferences:</div>
              <input type="text" id="wiz-sleep" value="${this._escapeHtml(w.sleepHabits || "")}" placeholder="e.g. Nighttime lights-off triggers when everyone is in bed" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
            </div>
          </div>
        `
        : ""
      }

        <!-- Step 2: Guest Mode & Entertaining -->
        ${step === 2
        ? `
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div style="font-size: 0.88rem; font-weight: 700; color: var(--otis-primary);">Step 2: Guest Mode & Entertaining</div>
            <div style="font-size: 0.75rem; color: var(--otis-text-muted);">Specify automated behaviors when guests or visitors are staying in the home.</div>

            <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 6px;">
              <div class="rules-setting-label">Temporary Guest Door Lock Code:</div>
              <div class="rules-setting-desc">Auto-programmed to exterior deadbolts when Guest Mode is turned ON, and auto-deleted when OFF.</div>
              <input type="text" id="wiz-guest-code" value="${this._escapeHtml(w.guestLockCode || "")}" placeholder="e.g. 4411" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
            </div>

            <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 6px;">
              <div class="rules-setting-label">Guest Bedtime Lighting Delayed Shutoff Time:</div>
              <div class="rules-setting-desc">Extends living area lighting past normal bedtime when guests are visiting.</div>
              <input type="time" step="1" id="wiz-guest-off" value="${this._escapeHtml(w.guestDelayedOff || "00:00:00")}" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
            </div>

            <label class="rules-setting-row" style="cursor: pointer;">
              <div>
                <div class="rules-setting-label">Guest Suite Climate Comfort</div>
                <div class="rules-setting-desc">Automatically maintain conditioned climate in guest rooms when guest mode is active.</div>
              </div>
              <input type="checkbox" id="wiz-guest-climate" ${w.guestClimateComfort !== false ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
            </label>

            <label class="rules-setting-row" style="cursor: pointer;">
              <div>
                <div class="rules-setting-label">Coordinate Holiday & Festive Lighting</div>
                <div class="rules-setting-desc">Synchronize decorative tree, seasonal outlets, and foyer accent lighting.</div>
              </div>
              <input type="checkbox" id="wiz-guest-holiday" ${w.holidaySwitches !== false ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
            </label>
          </div>
        `
        : ""
      }

        <!-- Step 3: Security & Perimeter Safeguards -->
        ${step === 3
        ? `
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div style="font-size: 0.88rem; font-weight: 700; color: var(--otis-primary);">Step 3: Security & Perimeter Safeguards</div>
            <div style="font-size: 0.75rem; color: var(--otis-text-muted);">Set strict guardrails on physical access points, exterior deadbolts, and perimeter alarms.</div>

            <label class="rules-setting-row" style="cursor: pointer;">
              <div>
                <div class="rules-setting-label">Require Confirmation for Door Deadbolts</div>
                <div class="rules-setting-desc">Otis will never unlock exterior doors without explicit user confirmation.</div>
              </div>
              <input type="checkbox" id="wiz-deadbolt-confirm" ${w.requireDeadboltConfirm !== false ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
            </label>

            <label class="rules-setting-row" style="cursor: pointer;">
              <div>
                <div class="rules-setting-label">Require Confirmation for Security Alarm</div>
                <div class="rules-setting-desc">Explicit confirmation required before disarming alarm panels.</div>
              </div>
              <input type="checkbox" id="wiz-alarm-confirm" ${w.requireAlarmConfirm !== false ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
            </label>

            <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 6px;">
              <div class="rules-setting-label">Garage Open Alert Threshold (Minutes):</div>
              <div class="rules-setting-desc">Time before alert is triggered if garage door remains open after sunset.</div>
              <input type="number" id="wiz-garage-mins" min="5" max="120" value="${w.garageAlertMinutes || 15}" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
            </div>

            <label class="rules-setting-row" style="cursor: pointer;">
              <div>
                <div class="rules-setting-label">Perimeter Camera Presence Alerts</div>
                <div class="rules-setting-desc">Audit unfamiliar perimeter motion or vehicle activity during night hours.</div>
              </div>
              <input type="checkbox" id="wiz-perimeter-alerts" ${w.perimeterCameraAlerts !== false ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
            </label>
          </div>
        `
        : ""
      }

        <!-- Step 4: Audio & Matrix Media -->
        ${step === 4
        ? `
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div style="font-size: 0.88rem; font-weight: 700; color: var(--otis-primary);">Step 4: Audio & Matrix Media Preferences</div>
            <div style="font-size: 0.75rem; color: var(--otis-text-muted);">Configure multi-zone audio streaming, voice assist ducking, and quiet hours.</div>

            <label class="rules-setting-row" style="cursor: pointer;">
              <div>
                <div class="rules-setting-label">Multi-Zone Matrix Audio Coordination</div>
                <div class="rules-setting-desc">Automatically route upstream streamer inputs to occupied room zones and media players.</div>
              </div>
              <input type="checkbox" id="wiz-matrix-routing" ${w.matrixRouting !== false ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
            </label>

            <label class="rules-setting-row" style="cursor: pointer;">
              <div>
                <div class="rules-setting-label">Voice Assist Spatial Audio Ducking</div>
                <div class="rules-setting-desc">Temporarily duck active music playback volume when Voice Assist or Otis speaks.</div>
              </div>
              <input type="checkbox" id="wiz-voice-ducking" ${w.voiceDucking !== false ? "checked" : ""} style="width: 18px; height: 18px; cursor: pointer;" />
            </label>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
              <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start;">
                <div class="rules-setting-label">Quiet Hours Start:</div>
                <input type="time" id="wiz-quiet-start" value="${this._escapeHtml(w.quietHoursStart || "22:00")}" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
              </div>
              <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start;">
                <div class="rules-setting-label">Quiet Hours End:</div>
                <input type="time" id="wiz-quiet-end" value="${this._escapeHtml(w.quietHoursEnd || "07:00")}" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border);" />
              </div>
            </div>

            <div class="rules-setting-row" style="flex-direction: column; align-items: flex-start; gap: 8px;">
              <div style="display: flex; justify-content: space-between; width: 100%; align-items: center;">
                <div class="rules-setting-label">Quiet Hours Spoken Volume Limit:</div>
                <span id="wiz-vol-label" style="font-weight: 700; color: var(--otis-primary);">${w.quietVolume || 25}%</span>
              </div>
              <input type="range" id="wiz-quiet-vol" min="5" max="100" value="${w.quietVolume || 25}" style="width: 100%; cursor: pointer;" />
            </div>
          </div>
        `
        : ""
      }

        <!-- Step 5: Review & Synthesize -->
        ${step === 5
        ? `
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div style="font-size: 0.88rem; font-weight: 700; color: var(--otis-primary);">Step 5: Synthesized Household Instructions</div>
            <div style="font-size: 0.75rem; color: var(--otis-text-muted);">Here is the structured markdown generated from your wizard responses. Clicking "Apply to Custom Instructions & Save" will store this directly in Otis's cognitive prompt context.</div>

            <pre style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; border: 1px solid var(--otis-surface-border); font-family: monospace; font-size: 0.74rem; white-space: pre-wrap; color: var(--otis-text); max-height: 240px; overflow-y: auto;">${this._escapeHtml(this._generateStructuredRulesText())}</pre>

            <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 6px; flex-wrap: wrap;">
              <button type="button" class="subview-chip" id="wiz-btn-copy-instructions" style="padding: 6px 14px; font-size: 0.76rem;">
                ✏️ Edit in Textarea
              </button>
              <button type="button" class="subview-chip" id="wiz-btn-apply-save" style="background: var(--otis-primary, #0ea5e9); color: #fff; font-weight: 700; padding: 6px 18px; border: none; font-size: 0.76rem; cursor: pointer;">
                ✨ Apply to Custom Instructions & Save
              </button>
            </div>
          </div>
        `
        : ""
      }

        <!-- Wizard Navigation Footer -->
        <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 10px; border-top: 1px solid var(--otis-surface-border); margin-top: 6px;">
          <div>
            ${step > 1
        ? `<button type="button" class="subview-chip" id="wiz-btn-prev" style="padding: 6px 14px; font-size: 0.76rem; cursor: pointer;">◀ Previous</button>`
        : `<span></span>`
      }
          </div>
          <div>
            ${step < 5
        ? `<button type="button" class="subview-chip" id="wiz-btn-next" style="background: var(--otis-primary, #0ea5e9); color: #fff; font-weight: 600; padding: 6px 16px; border: none; font-size: 0.76rem; cursor: pointer;">${step === 4 ? "Generate & Review ▶" : "Next Step ▶"}</button>`
        : ""
      }
          </div>
        </div>
      </div>
    `;
  },

  _renderRulesPeopleTab(rules) {
    const profiles = { ...(this._userRules?.person_profiles || {}) };
    const ignored = (this._userRules?.ignored_persons || []).map((x) => String(x).toLowerCase());
    const availUsers = this._getAvailableUsers();

    // Ensure registered person entities from Home Assistant are represented unless explicitly ignored
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
          tracks: [],
          features: {},
        };
      }
    });

    const profileList = Object.values(profiles).filter((p) => !ignored.includes(String(p.person_id).toLowerCase()));

    return `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
          <div>
            <div style="font-size: 0.88rem; font-weight: 700; color: var(--otis-primary);">👥 Recognized Household Members, Pets &amp; Guests</div>
            <div style="font-size: 0.75rem; color: var(--otis-text-muted);">Manage who Otis identifies across cameras, presence sensors, security rules, room comfort, and spatial audio. Classify residents, pets, or guests, enable/disable recognition training, or remove profiles.</div>
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 10px;">
          ${profileList.map((p) => {
      const pid = p.person_id;
      const pType = p.entity_type || (/dexter|charles|pet|dog|cat/i.test(p.label || pid) ? "pet" : (/guest/i.test(p.label || pid) ? "guest" : "resident"));
      const typeIcon = pType === "pet" ? "🐾" : (pType === "guest" ? "👥" : (pType === "ignored" ? "🚫" : "👤"));
      const confPct = Math.round((p.confidence || 0.50) * 100);
      const samples = Number(p.samples || 0);
      const progPct = Math.min(100, Math.round(Math.max((samples / 5) * 100, confPct)));
      const isTrained = samples >= 5 || confPct >= 85;
      const isTraining = p.training_enabled !== false && pType !== "ignored";
      const stageLabel = pType === "ignored" ? "🚫 Excluded" : (!isTraining ? "⏸️ Paused" : (isTrained ? "🟢 Trained" : (samples > 0 ? "🟡 Calibrating" : "🔵 Needs Samples")));
      const barColor = isTrained ? "#10b981" : "#38bdf8";
      const roomsVerified = Array.isArray(p.verified_rooms) && p.verified_rooms.length
        ? p.verified_rooms.map((r) => String(r).replace(/_/g, " ")).join(", ")
        : "None yet";

      return `
              <div class="rules-setting-row" style="padding: 10px 14px; border-radius: 8px; background: rgba(0,0,0,0.18); border: 1px solid var(--otis-surface-border); display: flex; flex-direction: column; gap: 8px;" data-profile-card="${this._escapeHtml(pid)}">
                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; flex-wrap: wrap; gap: 8px;">
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.3rem;">${typeIcon}</span>
                    <div>
                      <div style="font-weight: 700; font-size: 0.85rem; color: var(--otis-text);">${this._escapeHtml(p.label || pid)}</div>
                      <div style="font-size: 0.70rem; color: var(--otis-text-muted); font-family: monospace;">${this._escapeHtml(pid)} • Verified Rooms: ${this._escapeHtml(roomsVerified)}</div>
                    </div>
                  </div>
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 0.72rem; padding: 2px 8px; border-radius: 12px; background: ${isTrained ? 'rgba(16,185,129,0.2)' : 'rgba(56,189,248,0.2)'}; color: ${isTrained ? '#10b981' : 'var(--otis-primary)'}; font-weight: 600;">
                      ${stageLabel} • ${confPct}% Confidence (${samples}/5 camera samples)
                    </span>
                    ${samples > 0 ? `
                      <button type="button" class="btn-reset-person-training" data-person-id="${this._escapeHtml(pid)}" data-person-label="${this._escapeHtml(p.label || pid)}" style="background: rgba(245,158,11,0.16); color: #f59e0b; border: 1px solid rgba(245,158,11,0.38); border-radius: 6px; padding: 2px 8px; font-size: 0.70rem; font-weight: 600; cursor: pointer;" title="Reset training samples and confidence back to baseline">
                        ↺ Reset Training
                      </button>
                    ` : ""}
                  </div>
                </div>

                ${pType !== "ignored" ? `
                <div style="width: 100%; display: flex; flex-direction: column; gap: 3px;">
                  <div style="width: 100%; height: 6px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden;">
                    <div style="width: ${progPct}%; height: 100%; background: ${barColor}; transition: width 0.3s ease;"></div>
                  </div>
                </div>
                ` : ""}

                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 8px; gap: 12px; flex-wrap: wrap;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 0.74rem; color: var(--otis-text-muted);">Classification:</span>
                    <select class="profile-type-select" data-person-id="${this._escapeHtml(pid)}" style="background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 6px; padding: 3px 8px; font-size: 0.74rem;">
                      <option value="resident" ${pType === "resident" ? "selected" : ""}>👤 Primary Resident</option>
                      <option value="pet" ${pType === "pet" ? "selected" : ""}>🐾 Pet / Domestic Animal</option>
                      <option value="guest" ${pType === "guest" ? "selected" : ""}>👥 Guest / Visitor</option>
                      <option value="ignored" ${pType === "ignored" ? "selected" : ""}>🚫 Exclude / Do Not Track</option>
                    </select>
                  </div>

                  <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; margin: 0;">
                    <span style="font-size: 0.74rem; color: var(--otis-text-muted);">Recognition Training:</span>
                    <input type="checkbox" class="profile-training-toggle" data-person-id="${this._escapeHtml(pid)}" ${isTraining ? "checked" : ""} style="width: 16px; height: 16px; cursor: pointer;" />
                  </label>
                </div>
              </div>
            `;
    }).join("")}
        </div>
      </div>
    `;
  },

  _renderRulesInstructionsTab(rules) {
    const customInst = rules.custom_instructions || "";

    return `
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <!-- Wizard Launcher Banner -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: rgba(14, 165, 233, 0.1); border: 1px solid rgba(14, 165, 233, 0.3); border-radius: 8px; gap: 10px; flex-wrap: wrap;">
          <div>
            <div style="font-weight: 700; font-size: 0.82rem; color: var(--otis-primary);">🧙‍♂️ Interactive Household Rules Wizard</div>
            <div style="font-size: 0.74rem; color: var(--otis-text-muted);">Step-by-step guidance for household habits, guest mode, security, and matrix audio.</div>
          </div>
          <button type="button" class="subview-chip" id="btn-launch-rules-wizard" style="background: var(--otis-primary, #0ea5e9); color: #fff; font-size: 0.76rem; font-weight: 600; padding: 6px 14px; border: none; cursor: pointer;">
            Launch Wizard ➔
          </button>
        </div>

        <div>
          <div style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">Custom Household Rules & Persona Guidelines:</div>
          <div style="font-size: 0.74rem; color: var(--otis-text-muted); margin-top: 2px;">
            Specify unique house rules, resident preferences, nicknames, or room guidelines. These instructions are injected directly into every conversation turn.
          </div>
        </div>

        <textarea
          id="rules-input-instructions"
          rows="8"
          placeholder="e.g.:
- Primary resident works in the Study from 9:00 AM to 5:00 PM.
- Always keep the Great Room cooler than the rest of the house.
- When guests are staying over, never arm the guest room motion sensors.
- Refer to the backyard patio as 'The Oasis'."
          style="width: 100%; box-sizing: border-box; padding: 10px; border-radius: 8px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-family: monospace; font-size: 0.8rem; resize: vertical;"
        >${this._escapeHtml(customInst)}</textarea>

        <div style="font-size: 0.72rem; color: var(--otis-text-muted); line-height: 1.4; background: rgba(56, 189, 248, 0.08); padding: 8px 10px; border-radius: 6px; border-left: 3px solid var(--otis-primary);">
          💡 <strong>Tip:</strong> You can also speak or chat naturally with Otis anytime (e.g. <em>\"Otis, remember that I like the theater temperature at 68 degrees\"</em>) and Otis will adapt.
        </div>
      </div>
    `;
  },

  _renderFailoverModal() {
    return `
      <div class="modal-overlay" id="failover-modal-backdrop">
        <div class="modal-card" style="max-width: 680px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;">
          <div class="modal-header">
            <div>
              <div class="modal-title">
                <span>🛡️</span>
                <span>AI Multi-Agent Routing &amp; Failover Guide</span>
              </div>
              <div class="modal-subtitle">
                Paid-First Dynamic Priority • Live Health &amp; Latency Scoring • Continuous Self-Learning
              </div>
            </div>
            <button type="button" class="modal-close-btn" id="failover-modal-close-btn">✕</button>
          </div>

          <div style="overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-right: 4px;">
            <!-- Explanation Box -->
            <div class="guide-box" style="display: flex; flex-direction: column; gap: 8px;">
              <div style="font-weight: 700; font-size: 0.86rem; color: var(--otis-primary); display: flex; align-items: center; gap: 6px;">
                <span>⚡</span> How Otis Dynamically Orders &amp; Tunes Conversation Agents
              </div>
              <div style="font-size: 0.77rem; line-height: 1.5; color: var(--otis-text);">
                Otis continuously monitors <strong>API tier status (Paid vs. Free)</strong>, <strong>response latency</strong>, <strong>429/503 availability</strong>, and <strong>YAML accuracy</strong> across all installed conversation integrations. Agents are automatically reordered in real time:
              </div>
              <div style="display: flex; align-items: center; justify-content: center; gap: 6px; padding: 10px; background: rgba(0,0,0,0.3); border-radius: 8px; font-size: 0.72rem; font-weight: 700; flex-wrap: wrap;">
                <span style="padding: 4px 9px; border-radius: 6px; background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(16, 185, 129, 0.45); color: #10b981;">1. Paid Cloud APIs</span>
                <span>➔</span>
                <span style="padding: 4px 9px; border-radius: 6px; background: rgba(56, 189, 248, 0.2); border: 1px solid rgba(56, 189, 248, 0.45); color: #38bdf8;">2. Healthy Standard Cloud</span>
                <span>➔</span>
                <span style="padding: 4px 9px; border-radius: 6px; background: rgba(168, 85, 247, 0.2); border: 1px solid rgba(168, 85, 247, 0.45); color: #c084fc;">3. Local LAN LLM (Ollama)</span>
                <span>➔</span>
                <span style="padding: 4px 9px; border-radius: 6px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); color: #f87171;">4. Restricted Free Tiers (Last Resort)</span>
              </div>
            </div>

            <!-- Tier 1: Paid & Local Providers (Recommended) -->
            <div>
              <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #10b981; margin-bottom: 8px;">
                ✅ Priority 1 &amp; 2: Recommended Paid Cloud &amp; Local Offline Agents
              </div>
              <div style="display: flex; flex-direction: column; gap: 8px;">

                <!-- Anthropic Claude -->
                <div style="padding: 10px 14px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 10px; border-left: 3px solid #10b981;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px;">
                    <span class="failover-agent-name" data-domain="anthropic" style="font-weight: 700; font-size: 0.84rem; color: #10b981; cursor: pointer; text-decoration: underline; text-underline-offset: 3px;" title="Click to add Anthropic integration">
                      🏆 Anthropic Claude (Claude 3.7 / 3.5 Sonnet &amp; Haiku) ↗
                    </span>
                    <div style="display: flex; align-items: center; gap: 6px;">
                      <span style="font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);">PAID PRIORITY #1</span>
                      <button type="button" class="btn-setup-agent" data-domain="anthropic" style="font-size: 0.7rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); cursor: pointer;">
                        + Add in HA ↗
                      </button>
                    </div>
                  </div>
                  <div style="font-size: 0.74rem; color: var(--otis-text-muted); line-height: 1.4;">
                    Best-in-class Home Assistant YAML synthesis, zero hallucination adherence, and 200K context window. Always routed first when configured.
                  </div>
                </div>

                <!-- OpenAI -->
                <div style="padding: 10px 14px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 10px; border-left: 3px solid #a855f7;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px;">
                    <span class="failover-agent-name" data-domain="openai_conversation" style="font-weight: 700; font-size: 0.84rem; color: #c084fc; cursor: pointer; text-decoration: underline; text-underline-offset: 3px;" title="Click to add OpenAI Conversation integration">
                      🤖 OpenAI (GPT-4o / GPT-4o-mini) ↗
                    </span>
                    <div style="display: flex; align-items: center; gap: 6px;">
                      <span style="font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4);">PAID MICRO-COST</span>
                      <button type="button" class="btn-setup-agent" data-domain="openai_conversation" style="font-size: 0.7rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); cursor: pointer;">
                        + Add in HA ↗
                      </button>
                    </div>
                  </div>
                  <div style="font-size: 0.74rem; color: var(--otis-text-muted); line-height: 1.4;">
                    High-reliability Paid API with fast tool execution and huge context window (~$0.15 / 1M tokens on <code>gpt-4o-mini</code>). Automatically prioritized ahead of free tiers.
                  </div>
                </div>

                <!-- OpenRouter -->
                <div style="padding: 10px 14px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 10px; border-left: 3px solid #38bdf8;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px;">
                    <span class="failover-agent-name" data-domain="open_router" style="font-weight: 700; font-size: 0.84rem; color: #38bdf8; cursor: pointer; text-decoration: underline; text-underline-offset: 3px;" title="Click to add OpenRouter integration">
                      🔀 OpenRouter (Paid Credits vs. Free Router) ↗
                    </span>
                    <div style="display: flex; align-items: center; gap: 6px;">
                      <span style="font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4);">USE PAID MODELS ONLY</span>
                      <button type="button" class="btn-setup-agent" data-domain="open_router" style="font-size: 0.7rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); cursor: pointer;">
                        + Add in HA ↗
                      </button>
                    </div>
                  </div>
                  <div style="font-size: 0.74rem; color: var(--otis-text-muted); line-height: 1.4;">
                    <strong>Paid Models Recommended:</strong> Selecting paid models (e.g. <code>anthropic/claude-3.5-sonnet</code>, <code>openai/gpt-4o-mini</code>, <code>x-ai/grok-3</code>) gives you Priority 1 routing. <strong style="color: #f87171;">Avoid <code>openrouter/free</code> (Free Models Router):</strong> Free community models suffer from 20–45s queue delays, leaked DSML tags, and frequent rate limits (automatically demoted behind Local LLM).
                  </div>
                </div>

                <!-- Google Generative AI (Gemini) -->
                <div style="padding: 10px 14px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 10px; border-left: 3px solid #f59e0b;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px;">
                    <span class="failover-agent-name" data-domain="google_generative_ai_conversation" style="font-weight: 700; font-size: 0.84rem; color: #fbbf24; cursor: pointer; text-decoration: underline; text-underline-offset: 3px;" title="Click to add Google Generative AI integration">
                      🌟 Google Gemini (Paid Billing vs. Busy Free Tier) ↗
                    </span>
                    <div style="display: flex; align-items: center; gap: 6px;">
                      <span style="font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4);">FREE TIER OFTEN BUSY (429/503)</span>
                      <button type="button" class="btn-setup-agent" data-domain="google_generative_ai_conversation" style="font-size: 0.7rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); cursor: pointer;">
                        + Add in HA ↗
                      </button>
                    </div>
                  </div>
                  <div style="font-size: 0.74rem; color: var(--otis-text-muted); line-height: 1.4;">
                    Fast and capable with large 1M token context, but the <strong>Google AI Studio Free Tier is frequently congested (<code>RESOURCE_EXHAUSTED</code> / HTTP 429 / 503)</strong>. Use <code>models/gemini-3.5-flash-lite</code> or enable Pay-As-You-Go billing in Google AI Studio for reliable uptime.
                  </div>
                </div>

                <!-- Ollama Local LLM -->
                <div style="padding: 10px 14px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 10px; border-left: 3px solid #10b981;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px;">
                    <span class="failover-agent-name" data-domain="ollama" style="font-weight: 700; font-size: 0.84rem; color: #10b981; cursor: pointer; text-decoration: underline; text-underline-offset: 3px;" title="Click to add Ollama integration">
                      🏠 Ollama Local Edge AI (Qwen 2.5 / Llama 3.1 on LAN) ↗
                    </span>
                    <div style="display: flex; align-items: center; gap: 6px;">
                      <span style="font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);">100% FREE &amp; OFFLINE</span>
                      <button type="button" class="btn-setup-agent" data-domain="ollama" style="font-size: 0.7rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); cursor: pointer;">
                        + Add in HA ↗
                      </button>
                    </div>
                  </div>
                  <div style="font-size: 0.74rem; color: var(--otis-text-muted); line-height: 1.4;">
                    Runs locally on your LAN GPU/CPU server with zero cloud rate limits, total privacy, and instant failover before any restricted free-tier cloud router.
                  </div>
                </div>

                <!-- Groq (HACS Integration) Free Tier Warning -->
                <div style="padding: 10px 14px; background: rgba(239, 68, 68, 0.06); border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 10px; border-left: 3px solid #ef4444;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px;">
                    <span class="failover-agent-name" data-domain="groq" style="font-weight: 700; font-size: 0.84rem; color: #f87171; cursor: pointer; text-decoration: underline; text-underline-offset: 3px;" title="Open Groq integration in Home Assistant">
                      🚫 Groq (HACS Integration — Free Tier Not Recommended) ↗
                    </span>
                    <span style="font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4);">REMOVE FROM ROTATION ON FREE TIER</span>
                  </div>
                  <div style="font-size: 0.74rem; color: var(--otis-text-muted); line-height: 1.4;">
                    The HACS <strong>Groq</strong> integration's Free Tier enforces a strict <strong>6,000–12,000 Tokens-Per-Minute (<code>protect_free_tier</code>) cap</strong>, which is too small for a smart home capability map and causes HTTP 413/429 rejections. Remove Groq from the Assist rotation in <em>Settings → Devices &amp; Services → Groq</em> (or switch to a Paid Groq tier and uncheck <em>Protect free tier</em>).
                  </div>
                </div>

              </div>
            </div>

            <!-- Step-by-Step Instructions -->
            <div style="padding: 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid var(--otis-surface-border); border-radius: 10px; font-size: 0.76rem; line-height: 1.5;">
              <div style="font-weight: 700; color: var(--otis-primary); margin-bottom: 6px;">
                🧠 Continuous Self-Learning &amp; Anti-Hallucination Active:
              </div>
              <ul style="margin: 0; padding-left: 18px; color: var(--otis-text-muted);">
                <li><strong>Ask-Before-Guessing:</strong> If a command or room target is ambiguous, Otis asks you to clarify rather than guessing entity IDs.</li>
                <li><strong>Autonomous Rule Tuning:</strong> When you correct Otis (e.g., <em>"Remember that..."</em>, <em>"Always use..."</em>, <em>"Never touch..."</em>), Otis automatically saves the rule into your Custom Instructions.</li>
                <li><strong>Local HA Version Grounding:</strong> All generated YAML is verified against your live entity registry and upgraded to modern Home Assistant syntax (<code>triggers:</code>, <code>actions:</code>, <code>action:</code>).</li>
              </ul>
            </div>
          </div>

          <!-- Modal Actions -->
          <div class="modal-actions" style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px;">
            <button type="button" class="btn-modal-secondary" id="btn-close-failover-modal">
              Got It
            </button>
            <button type="button" class="btn-modal-primary" id="btn-open-ha-integrations">
              ⚙️ Open Home Assistant Integrations
            </button>
          </div>
        </div>
      </div>
    `;
  },

  async _generateThemeAi(prompt, presetKey = null) {
    if (!this._hass) return;
    this._generatingTheme = true;
    this._render();

    try {
      const isSubview = this._isSubviewMode();
      const isAll = !isSubview && this._themeApplyScope === "all";
      const targetId = isSubview ? this._hass?.user?.id : (isAll ? null : this._themeApplyScope === "specific" ? this._selectedThemeUserId : this._hass?.user?.id);
      const payload = {
        prompt: prompt || (presetKey ? `Generate ${presetKey} theme` : "Otis Custom Theme"),
        apply_immediately: true,
        user_id: isAll ? "all" : targetId,
      };
      if (presetKey) {
        payload.base_palette = presetKey;
      }
      const res = await this._hass.callService("otis_ai", "generate_theme", payload, undefined, true, true);
      const data = res?.response || res || {};
      if (data.success) {
        this._draftThemePrompt = "";
        this._showToast(`✨ Generated and applying "${data.title}"...`);
        await this._fetchData();
        if (data.theme_key) {
          await this._applyThemeDirect(data.theme_key, targetId, isAll);
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
  },

  async _applyThemeDirect(themeKey, targetUserId = null, applyAllUsers = false) {
    if (!this._hass || !themeKey) return;
    try {
      const isSubview = this._isSubviewMode();
      const curUserId = this._hass?.user?.id;
      const isAll = !isSubview && Boolean(applyAllUsers || this._themeApplyScope === "all");
      const targetId = isSubview ? curUserId : (targetUserId || curUserId);

      // 1. Call backend services
      try {
        await this._hass.callService("frontend", "set_theme", { name: themeKey });
      } catch (_) { }

      try {
        const payload = { name: themeKey, user_id: isAll ? "all" : targetId };
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
      } catch (_) { }

      const users = this._getAvailableUsers();
      const targetUser = targetId ? users.find((u) => u.id === targetId) : null;
      const scopeDesc = isAll ? "for all users (Global Sync)" : targetUser ? `for ${targetUser.name}` : "for your profile";
      this._showToast(`🎨 Theme applied ${scopeDesc}: ${themeKey}`);
    } catch (err) {
      console.error("Error applying theme:", err);
      this._showToast("Error applying theme", true);
    }
  },

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
  },

  async _postMediaStudioAction(payload) {
    if (!this._hass) return null;
    try {
      const opts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      };
      const resp =
        typeof this._hass.fetchWithAuth === "function"
          ? await this._hass.fetchWithAuth("/api/otis_ai/media_studio", opts)
          : await fetch("/api/otis_ai/media_studio", opts);
      if (!resp) return null;
      let data = {};
      const ct = resp.headers?.get?.("content-type") || "";
      if (ct.includes("application/json")) {
        data = await resp.json();
      } else {
        const text = await resp.text();
        try {
          data = JSON.parse(text);
        } catch {
          data = { error: text || `HTTP ${resp.status}` };
        }
      }
      if (!resp.ok || data.error) {
        this._showToast(data.error || `Media Studio error (${resp.status})`, true);
        return null;
      }
      if (data.zones) {
        this._mediaStudioData = data;
      } else {
        await this._fetchMediaStudioState();
      }
      this._render();
      return data;
    } catch (err) {
      console.error("Media Studio API error:", err);
      this._showToast(`Media Studio request failed: ${err.message || err}`, true);
      return null;
    }
  },

  async _fetchMediaLibrary(playerId = "", mediaType = "playlist") {
    if (!this._hass) return;
    this._mediaBrowseLoading = true;
    this._mediaBrowseError = null;
    this._mediaBrowseItems = [];
    this._mediaBrowseType = mediaType;
    this._mediaBrowsePlayerId = playerId;
    this._mediaBrowseOpen = true;
    this._render();

    try {
      const opts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "browse_library",
          player_entity_id: playerId,
          media_type: mediaType,
          limit: 50,
        }),
      };
      const resp =
        typeof this._hass.fetchWithAuth === "function"
          ? await this._hass.fetchWithAuth("/api/otis_ai/media_studio", opts)
          : await fetch("/api/otis_ai/media_studio", opts);

      if (!resp) throw new Error("No response from server");
      let data = {};
      const ct = resp.headers?.get?.("content-type") || "";
      if (ct.includes("application/json")) {
        data = await resp.json();
      } else {
        const text = await resp.text();
        try {
          data = JSON.parse(text);
        } catch {
          data = { error: text || `HTTP ${resp.status}` };
        }
      }
      if (!resp.ok || !data.success) {
        throw new Error(data.error || `HTTP ${resp.status}`);
      }
      this._mediaBrowseItems = Array.isArray(data.items) ? data.items : [];
    } catch (err) {
      console.warn("[Otis AI] Failed to browse media library:", err);
      this._mediaBrowseError = err.message || String(err);
    } finally {
      this._mediaBrowseLoading = false;
      this._render();
    }
  },

  _getResolvedCandidatePlayers(studioData = {}, mediaTopo = {}) {
    const rawCandidates = [
      ...(studioData.candidate_players || []),
      ...(mediaTopo.candidate_players || []),
    ];
    const candMap = new Map();
    rawCandidates.forEach((c) => {
      if (c && c.entity_id) candMap.set(c.entity_id, c);
    });

    const rawZones = studioData.zones || mediaTopo.matrix_zones || [];
    const matrixZoneIds = new Set(
      rawZones.map((z) => (typeof z === "string" ? z : z.entity_id)).filter(Boolean)
    );

    if (this._hass && this._hass.states) {
      Object.keys(this._hass.states).forEach((eid) => {
        if (eid.startsWith("media_player.") && !candMap.has(eid)) {
          const st = this._hass.states[eid];
          candMap.set(eid, {
            entity_id: eid,
            name: st?.attributes?.friendly_name || eid,
            state: st?.state || "unknown",
          });
        }
      });
    }

    return Array.from(candMap.values()).sort((a, b) =>
      (a.name || a.entity_id).localeCompare(b.name || b.entity_id)
    );
  },

  _hasReviewableCode(s) {
    if (!s) return false;
    const p = s.action_payload || {};
    const at = String(s.action_type || "").toLowerCase();
    if (
      p.yaml ||
      p.blueprint_yaml ||
      p.triggers ||
      p.trigger ||
      p.actions ||
      p.action ||
      p.sequence ||
      p.blueprint ||
      p.automation ||
      p.script
    ) {
      return true;
    }
    return (
      at.includes("automation") ||
      at.includes("script") ||
      at.includes("blueprint") ||
      at.includes("habit") ||
      at.includes("energy_guard") ||
      at.includes("circadian")
    );
  },

  _toYamlString(val, indent = 0) {
    const pad = "  ".repeat(indent);
    if (val === null || val === undefined) return "null";
    if (typeof val === "boolean" || typeof val === "number") return String(val);
    if (typeof val === "string") {
      if (val.includes("\n")) {
        return "|\n" + val.split("\n").map((l) => pad + "  " + l).join("\n");
      }
      if (val === "" || /[:#{}[\],&*!|>'"%@`]/.test(val) || /^\s|\s$/.test(val)) {
        return JSON.stringify(val);
      }
      return val;
    }
    if (Array.isArray(val)) {
      if (val.length === 0) return "[]";
      return val
        .map((item) => {
          if (item && typeof item === "object" && !Array.isArray(item)) {
            const entries = Object.entries(item);
            if (entries.length === 0) return `${pad}- {}`;
            const [fk, fv] = entries[0];
            const firstRendered = this._toYamlString(fv, indent + 2);
            const firstLine =
              fv && typeof fv === "object" && ((Array.isArray(fv) && fv.length > 0) || (!Array.isArray(fv) && Object.keys(fv).length > 0))
                ? `${pad}- ${fk}:\n${firstRendered}`
                : `${pad}- ${fk}: ${firstRendered}`;
            const rest = entries.slice(1).map(([k, v]) => {
              const r = this._toYamlString(v, indent + 2);
              if (v && typeof v === "object" && ((Array.isArray(v) && v.length > 0) || (!Array.isArray(v) && Object.keys(v).length > 0))) {
                return `${pad}  ${k}:\n${r}`;
              }
              return `${pad}  ${k}: ${r}`;
            });
            return [firstLine, ...rest].join("\n");
          }
          return `${pad}- ${this._toYamlString(item, indent + 1)}`;
        })
        .join("\n");
    }
    if (typeof val === "object") {
      const entries = Object.entries(val);
      if (entries.length === 0) return "{}";
      return entries
        .map(([k, v]) => {
          const r = this._toYamlString(v, indent + 1);
          if (v && typeof v === "object" && ((Array.isArray(v) && v.length > 0) || (!Array.isArray(v) && Object.keys(v).length > 0))) {
            return `${pad}${k}:\n${r}`;
          }
          return `${pad}${k}: ${r}`;
        })
        .join("\n");
    }
    return String(val);
  },

  _formatSuggestionYaml(s) {
    const p = s?.action_payload || {};
    if (typeof p.yaml === "string" && p.yaml.trim()) return p.yaml.trim();
    if (typeof p.blueprint_yaml === "string" && p.blueprint_yaml.trim()) return p.blueprint_yaml.trim();
    if (typeof s?.yaml === "string" && s.yaml.trim()) return s.yaml.trim();
    const target = p.automation || p.script || p.blueprint || p;
    return this._toYamlString(target, 0);
  },

  _renderSnapshotLightboxModal() {
    const lb = this._snapshotLightbox;
    if (!lb) return "";
    let bboxHtml = "";
    if (
      lb.bbox &&
      Number.isFinite(Number(lb.bbox.ymin)) &&
      Number.isFinite(Number(lb.bbox.xmin)) &&
      Number.isFinite(Number(lb.bbox.ymax)) &&
      Number.isFinite(Number(lb.bbox.xmax))
    ) {
      const topPct = Math.max(0, Math.min(99, Number(lb.bbox.ymin) / 10));
      const leftPct = Math.max(0, Math.min(99, Number(lb.bbox.xmin) / 10));
      const heightPct = Math.max(1, Math.min(100 - topPct, (Number(lb.bbox.ymax) - Number(lb.bbox.ymin)) / 10));
      const widthPct = Math.max(1, Math.min(100 - leftPct, (Number(lb.bbox.xmax) - Number(lb.bbox.xmin)) / 10));
      const boxLbl = this._escapeHtml(lb.bbox.label || "Subject");
      bboxHtml = `
        <div style="position: absolute; top: ${topPct.toFixed(2)}%; left: ${leftPct.toFixed(2)}%; width: ${widthPct.toFixed(2)}%; height: ${heightPct.toFixed(2)}%; border: 3px solid #fbbf24; border-radius: 5px; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.75), 0 0 14px rgba(251, 191, 36, 0.6); pointer-events: none; box-sizing: border-box;">
          <span style="position: absolute; top: -22px; left: -1px; background: rgba(251, 191, 36, 0.95); color: #0f172a; font-size: 0.72rem; font-weight: 800; padding: 2px 7px; border-radius: 4px; white-space: nowrap;">🎯 ${boxLbl}</span>
        </div>
      `;
    }
    return `
      <div class="modal-overlay" id="snapshot-lightbox-backdrop" style="z-index: 10050;">
        <div class="modal-card" style="max-width: 780px; width: 92vw; padding: 16px;" onclick="event.stopPropagation()">
          <div class="modal-header" style="margin-bottom: 12px;">
            <div class="modal-title" style="font-weight: 700; font-size: 0.95rem;">${this._escapeHtml(lb.title || "Detection Snapshot")}</div>
            <div style="display: flex; gap: 8px; align-items: center;">
              ${lb.camId ? `<button type="button" class="btn-toolbar" id="btn-lightbox-more-info" style="padding: 4px 10px; font-size: 0.75rem;">📹 Live Entity</button>` : ""}
              <button type="button" class="modal-close-btn" id="btn-close-snapshot-lightbox" title="Close">✕</button>
            </div>
          </div>
          <div style="display: flex; justify-content: center; align-items: center; background: #090d16; border-radius: 10px; overflow: hidden; border: 1px solid rgba(56, 189, 248, 0.35);">
            <div style="position: relative; display: inline-block; max-width: 100%; max-height: 75vh;">
              <img src="${this._escapeHtml(lb.pic)}" alt="Enlarged Detection Snapshot" style="max-width: 100%; max-height: 75vh; width: auto; height: auto; display: block;" />
              ${bboxHtml}
            </div>
          </div>
        </div>
      </div>
    `;
  },

  _renderReviewSuggestionModal() {
    const s = this._reviewSuggestion;
    if (!s) return "";
    const yamlText = this._formatSuggestionYaml(s);
    const btnLabel = this._getActionLabel(s.action_type);
    return `
      <div class="modal-overlay" id="review-suggestion-backdrop">
        <div class="modal-card" style="max-width: 720px; width: 94%; max-height: 85vh; display: flex; flex-direction: column;">
          <div class="modal-header">
            <div class="modal-title">👁️ Review Proposed Configuration</div>
            <button type="button" class="modal-close-btn" id="btn-close-review-modal" title="Close">✕</button>
          </div>
          <div style="padding: 12px 18px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 10px;">
            <div style="font-weight: 700; color: var(--otis-text); font-size: 0.92rem;">${this._escapeHtml(s.title || "Automation Preview")}</div>
            ${s.description ? `<div style="font-size: 0.8rem; color: var(--otis-text-muted);">${this._escapeHtml(s.description)}</div>` : ""}
            <pre style="margin: 0; padding: 12px; border-radius: 8px; background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(148, 163, 184, 0.2); color: #e2e8f0; font-size: 0.76rem; line-height: 1.45; overflow-x: auto; white-space: pre-wrap; word-break: break-word;"><code>${this._escapeHtml(yamlText)}</code></pre>
          </div>
          <div style="padding: 12px 18px; border-top: 1px solid rgba(148, 163, 184, 0.16); display: flex; justify-content: flex-end; gap: 8px;">
            <button type="button" class="btn-toolbar" id="btn-copy-review-yaml" style="padding: 6px 12px; font-size: 0.78rem;">📋 Copy YAML</button>
            <button type="button" class="apply-btn" id="btn-apply-review-modal" style="padding: 6px 14px; font-size: 0.78rem;">${this._escapeHtml(btnLabel)}</button>
          </div>
        </div>
      </div>
    `;
  },

  _renderGitHubIssueModal() {
    const data = this._githubModalData || {};
    const step = this._githubModalStep || "review";
    const repo = data.repo || "OtisPresley/otis-ai-companion";
    const title = data.title || "[Bug Report]";
    const body = data.body || "";
    const errorMsg = this._githubErrorMsg || "";
    const dc = this._githubDeviceCode || {};

    let contentHtml = "";

    if (step === "review") {
      contentHtml = `
        <div class="modal-subtitle" style="margin-bottom: 12px;">
          Otis AI detected an actionable integration bug in Home Assistant logs. Review the automatically sanitized bug report below before authorizing GitHub submission.
        </div>
        <div style="background: rgba(14, 165, 233, 0.08); border: 1px solid var(--otis-primary); border-radius: 8px; padding: 10px; margin-bottom: 12px; font-size: 0.76rem; color: #38bdf8; display: flex; gap: 8px; align-items: center;">
          <span style="font-size: 1.1rem;">🔒</span>
          <div><strong>Privacy Guard Active:</strong> All internal IP addresses, access tokens, and local filesystem paths have been stripped from this report.</div>
        </div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div>
            <label style="font-size: 0.74rem; font-weight: 600; color: var(--otis-text-muted); display: block; margin-bottom: 4px;">Target GitHub Repository:</label>
            <input type="text" id="gh-modal-repo" value="${this._escapeHtml(repo)}" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.8rem; font-family: monospace;" />
          </div>
          <div>
            <label style="font-size: 0.74rem; font-weight: 600; color: var(--otis-text-muted); display: block; margin-bottom: 4px;">Issue Title:</label>
            <input type="text" id="gh-modal-title" value="${this._escapeHtml(title)}" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.8rem;" />
          </div>
          <div>
            <label style="font-size: 0.74rem; font-weight: 600; color: var(--otis-text-muted); display: block; margin-bottom: 4px;">Sanitized Report Body (Markdown):</label>
            <textarea id="gh-modal-body" rows="9" style="width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem; font-family: monospace; resize: vertical;">${this._escapeHtml(body)}</textarea>
          </div>
        </div>
        ${errorMsg ? `<div style="margin-top: 10px; color: #f87171; font-size: 0.76rem;">${this._escapeHtml(errorMsg)}</div>` : ""}
        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px;">
          <button type="button" class="btn-toolbar" id="btn-cancel-github-modal">Cancel</button>
          <button type="button" class="apply-btn" id="btn-proceed-github-auth" style="background: linear-gradient(135deg, #24292e 0%, #0ea5e9 100%);">
            ⚡ Continue to GitHub Verification
          </button>
        </div>
      `;
    } else if (step === "device_code") {
      const userCode = dc.user_code || "FETCHING...";
      const uri = dc.verification_uri || "https://github.com/login/device";
      contentHtml = `
        <div class="modal-subtitle" style="margin-bottom: 14px;">
          Authenticate with GitHub using the official Device Flow. No Personal Access Token or manual permissions setup needed!
        </div>
        <div style="background: rgba(0,0,0,0.35); border: 1px dashed var(--otis-primary); border-radius: 12px; padding: 18px; text-align: center; margin-bottom: 14px;">
          <div style="font-size: 0.74rem; color: var(--otis-text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;">Your One-Time Device Code:</div>
          <div id="gh-user-code-display" style="font-family: monospace; font-size: 1.8rem; font-weight: 800; letter-spacing: 5px; color: #38bdf8; margin-bottom: 12px; user-select: all;">
            ${this._escapeHtml(userCode)}
          </div>
          <div style="display: flex; justify-content: center; gap: 10px;">
            <button type="button" class="btn-toolbar" id="btn-copy-gh-code" style="padding: 6px 14px; font-size: 0.76rem;">
              📋 Copy Code
            </button>
            <a href="${this._escapeHtml(uri)}" target="_blank" rel="noopener noreferrer" class="apply-btn" style="text-decoration: none; padding: 6px 14px; font-size: 0.76rem; background: #0284c7; color: #fff;">
              🌐 Open github.com/login/device ↗
            </a>
          </div>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.75rem; color: var(--otis-text-muted); background: rgba(255,255,255,0.03); padding: 12px; border-radius: 8px;">
          <div>1. Click <strong>Copy Code</strong> above.</div>
          <div>2. Click <strong>Open github.com/login/device</strong> to open GitHub in a new tab.</div>
          <div>3. Paste the code and click <strong>Authorize</strong> on GitHub.</div>
          <div style="margin-top: 4px; color: #38bdf8; display: flex; align-items: center; gap: 8px;">
            <div class="spinner" style="width: 14px; height: 14px; border-width: 2px;"></div>
            <span>Waiting for your authorization on GitHub... (polling automatically)</span>
          </div>
        </div>
        ${errorMsg ? `<div style="margin-top: 10px; color: #f87171; font-size: 0.76rem;">${this._escapeHtml(errorMsg)}</div>` : ""}
        <div style="display: flex; justify-content: flex-end; margin-top: 16px;">
          <button type="button" class="btn-toolbar" id="btn-cancel-github-modal">Cancel</button>
        </div>
      `;
    } else if (step === "submitting") {
      contentHtml = `
        <div style="text-align: center; padding: 32px 16px; display: flex; flex-direction: column; align-items: center; gap: 14px;">
          <div class="spinner" style="width: 32px; height: 32px; border-width: 3px;"></div>
          <div style="font-size: 0.95rem; font-weight: 600; color: var(--otis-text);">Submitting Sanitized Bug Report to GitHub...</div>
          <div style="font-size: 0.76rem; color: var(--otis-text-muted);">Opening issue on ${this._escapeHtml(repo)} and registering tracking.</div>
        </div>
      `;
    } else if (step === "success") {
      const issue = this._githubCreatedIssue || {};
      contentHtml = `
        <div style="text-align: center; padding: 20px 10px; display: flex; flex-direction: column; align-items: center; gap: 12px;">
          <div style="font-size: 2.4rem;">🎉</div>
          <div style="font-size: 1.05rem; font-weight: 700; color: #34d399;">GitHub Issue Opened Successfully!</div>
          <div style="font-size: 0.8rem; color: var(--otis-text);">
            <strong>Issue #${this._escapeHtml(String(issue.number || ""))}</strong> on <code>${this._escapeHtml(repo)}</code>
          </div>
          <div style="font-size: 0.74rem; color: var(--otis-text-muted); max-width: 400px; line-height: 1.4;">
            Otis AI will now track the status of this issue directly in your Proactive Feed and notify you when resolved by developers.
          </div>
          <div style="display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; justify-content: center;">
            <a href="${this._escapeHtml(issue.html_url || '#')}" target="_blank" rel="noopener noreferrer" class="apply-btn" style="text-decoration: none; padding: 7px 16px; background: #0284c7; color: #fff;">
              🔗 View on GitHub ↗
            </a>
            <button type="button" class="btn-toolbar" id="btn-close-github-success" style="padding: 7px 16px;">
              Done &amp; Track in Feed
            </button>
          </div>
        </div>
      `;
    } else if (step === "error") {
      contentHtml = `
        <div style="text-align: center; padding: 20px 10px; display: flex; flex-direction: column; align-items: center; gap: 12px;">
          <div style="font-size: 2.2rem; color: #f87171;">❌</div>
          <div style="font-size: 1.0rem; font-weight: 700; color: #f87171;">Submission Failed</div>
          <div style="font-size: 0.76rem; color: var(--otis-text-muted); max-width: 400px; line-height: 1.4;">
            ${this._escapeHtml(errorMsg || "An error occurred communicating with GitHub.")}
          </div>
          <div style="display: flex; gap: 10px; margin-top: 14px;">
            <button type="button" class="apply-btn" id="btn-retry-github-flow">↺ Retry</button>
            <button type="button" class="btn-toolbar" id="btn-cancel-github-modal">Cancel</button>
          </div>
        </div>
      `;
    }

    return `
      <div class="modal-overlay" id="github-modal-backdrop">
        <div class="modal-card" style="max-width: 580px;">
          <div class="modal-header">
            <div class="modal-title">
              <span>🐙</span>
              <span>GitHub Issue Reporter</span>
            </div>
            <button type="button" class="modal-close-btn" id="btn-close-gh-modal-header" title="Close">✕</button>
          </div>
          ${contentHtml}
        </div>
      </div>
    `;
  },

  async _startGitHubDeviceFlow() {
    this._githubModalStep = "device_code";
    this._githubErrorMsg = null;
    this._render();

    try {
      const resp =
        this._hass && typeof this._hass.fetchWithAuth === "function"
          ? await this._hass.fetchWithAuth("/api/otis_ai/issue_reporter", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "request_device_code" }),
          })
          : await fetch("/api/otis_ai/issue_reporter", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "request_device_code" }),
          });

      if (!resp.ok) {
        throw new Error(`Server returned HTTP ${resp.status}`);
      }
      const data = await resp.json();
      if (!data.success || !data.device_code) {
        throw new Error(data.error || "Failed to retrieve GitHub device code");
      }

      this._githubDeviceCode = data;
      this._render();

      if (this._githubPollTimer) {
        clearInterval(this._githubPollTimer);
        this._githubPollTimer = null;
      }

      const pollInterval = (data.interval || 5) * 1000;
      const deviceCode = data.device_code;
      const startTime = Date.now();
      const maxDuration = (data.expires_in || 900) * 1000;

      this._githubPollTimer = setInterval(async () => {
        if (!this._githubModalOpen || this._githubModalStep !== "device_code") {
          clearInterval(this._githubPollTimer);
          this._githubPollTimer = null;
          return;
        }

        if (Date.now() - startTime > maxDuration) {
          clearInterval(this._githubPollTimer);
          this._githubPollTimer = null;
          this._githubModalStep = "error";
          this._githubErrorMsg = "Device code expired. Please retry.";
          this._render();
          return;
        }

        try {
          const chkResp =
            this._hass && typeof this._hass.fetchWithAuth === "function"
              ? await this._hass.fetchWithAuth("/api/otis_ai/issue_reporter", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "check_device_token", device_code: deviceCode }),
              })
              : await fetch("/api/otis_ai/issue_reporter", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "check_device_token", device_code: deviceCode }),
              });

          if (chkResp.ok) {
            const chkData = await chkResp.json();
            if (chkData.status === "success" && chkData.token) {
              clearInterval(this._githubPollTimer);
              this._githubPollTimer = null;
              await this._submitGitHubIssueWithToken(chkData.token);
            } else if (chkData.status === "expired" || chkData.status === "error") {
              clearInterval(this._githubPollTimer);
              this._githubPollTimer = null;
              this._githubModalStep = "error";
              this._githubErrorMsg = chkData.error || "GitHub authorization failed";
              this._render();
            }
          }
        } catch (_) { }
      }, pollInterval);
    } catch (err) {
      this._githubModalStep = "error";
      this._githubErrorMsg = err.message || String(err);
      this._render();
    }
  },

  async _submitGitHubIssueWithToken(token) {
    this._githubModalStep = "submitting";
    this._render();

    const data = this._githubModalData || {};
    try {
      const payload = {
        action: "submit_issue",
        token: token,
        repo: data.repo || "OtisPresley/otis-ai-companion",
        title: data.title,
        body: data.body,
        error_id: data.error_id,
      };

      const resp =
        this._hass && typeof this._hass.fetchWithAuth === "function"
          ? await this._hass.fetchWithAuth("/api/otis_ai/issue_reporter", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          })
          : await fetch("/api/otis_ai/issue_reporter", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });

      const resData = await resp.json();
      if (resp.ok && resData.success && resData.issue) {
        this._githubCreatedIssue = resData.issue;
        this._githubModalStep = "success";
        this._showToast(`🎉 GitHub Issue #${resData.issue.number} created!`);
        await this._fetchData();
      } else {
        this._githubModalStep = "error";
        this._githubErrorMsg = resData.error || "Failed to create issue on GitHub";
      }
    } catch (err) {
      this._githubModalStep = "error";
      this._githubErrorMsg = err.message || String(err);
    }
    this._render();
  },

};
