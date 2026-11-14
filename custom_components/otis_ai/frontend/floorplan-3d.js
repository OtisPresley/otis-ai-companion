/** Floorplan 2D/3D and room inspector mixin for OtisCompanionCard. */
export const floorplanMixin = {
  _renderFloorplanTab() {
    const isControlOnly = this._config.mode === "floorplan_control";
    const isAdmin = Boolean(this._hass?.user?.is_admin || this._hass?.user?.is_owner);

    if (!this._floorplanSvg && !this._loadingFloorplan) {
      setTimeout(() => this._loadFloorplanSvg(this._capabilityMap?.floorplan?.url), 0);
    }

    return `
      <div class="floorplan-panel">
        ${this._renderPreconditioningChip()}
        <div class="floorplan-toolbar">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <div class="view-mode-pills">
              <button type="button" class="view-mode-pill ${this._floorplanViewMode === "2d" ? "active" : ""}" data-view-mode="2d" title="2D Orthogonal Blueprint">📐 2D</button>
              <button type="button" class="view-mode-pill ${this._floorplanViewMode === "3d" ? "active" : ""}" data-view-mode="3d" title="Multi-Floor 3D Isometric View">🧊 3D</button>
            </div>
            <div class="zone-pills">
              <button type="button" class="zone-pill ${this._selectedFloorZone === "all" ? "active" : ""}" data-zone="all">All Floors</button>
              <button type="button" class="zone-pill ${this._selectedFloorZone === "main" ? "active" : ""}" data-zone="main">Ground &amp; Outdoor</button>
              <button type="button" class="zone-pill ${this._selectedFloorZone === "upper" ? "active" : ""}" data-zone="upper">Upper Level</button>
              <button type="button" class="zone-pill ${this._selectedFloorZone === "outdoor" ? "active" : ""}" data-zone="outdoor">Outdoor Only</button>
            </div>
          </div>
          <div class="floorplan-actions">
            ${!isControlOnly
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
            ${isAdmin && !isControlOnly
        ? `
              <button type="button"
                class="btn-toolbar"
                id="btn-recalculate-floorplan"
                ${this._recalculatingFloorplan ? "disabled" : ""}
                title="Recalculate all room entities, center-outward pin placements, and SVG floor plan layout"
              >
                ${this._recalculatingFloorplan ? "⏳ Recalculating..." : "🔄 Recalculate"}
              </button>
              <button type="button"
                class="btn-toolbar"
                id="btn-regenerate-floorplan"
                ${this._regeneratingFloorplan ? "disabled" : ""}
                title="Regenerate the vector SVG floor plan from areas, walkthrough data, and spatial graph"
              >
                ${this._regeneratingFloorplan ? "⏳ Regenerating..." : "✨ Regenerate"}
              </button>
              <button type="button" 
                class="btn-toolbar ${this._editorActive ? 'active' : ''}" 
                id="btn-toggle-editor"
                style="${this._editorActive ? 'background: var(--otis-primary); color: var(--otis-btn-text, #ffffff); border-color: var(--otis-primary);' : ''}"
                title="Toggle Interactive Floor Plan Edit Mode to drag pins, add/remove devices, and adjust boundaries"
              >
                ${this._editorActive ? "🛠️ Exit Edit Mode" : "✏️ Edit Floor Plan"}
              </button>
            `
        : ""
      }
          </div>
        </div>

        ${this._editorActive && isAdmin && !isControlOnly
        ? `
          <div class="editor-toolbar-strip">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="font-weight: 700; color: var(--otis-primary);">🛠️ Floor Plan Edit Mode:</span>
              <span style="color: var(--otis-text-muted); font-size: 0.73rem;">Drag pins to position • Click any pin to inspect/remove • Drag walls to resize</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
              <button type="button" class="btn-toolbar" id="btn-open-add-marker" style="padding: 4px 9px;" title="Add a device entity pin to the floor plan">
                ➕ Add Entity
              </button>
              <button type="button" class="btn-toolbar" id="btn-add-custom-stairs" style="padding: 4px 9px;" title="Add an independent draggable staircase">
                🪜 + Stairs
              </button>
              <button type="button" class="btn-toolbar" id="btn-add-custom-box" style="padding: 4px 9px;" title="Add an independent labeled dashed box (e.g. Reading Nook, Patio)">
                ⬜ + Box
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

        ${this._regeneratingFloorplan
        ? `
          <div id="regen-progress-banner" style="margin-bottom: 10px; padding: 12px 14px; border-radius: 10px; background: rgba(14, 165, 233, 0.12); border: 1px solid rgba(56, 189, 248, 0.35);">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <div class="spinner" style="width: 14px; height: 14px;"></div>
                <span id="regen-progress-text" style="font-size: 0.82rem; font-weight: 600; color: var(--otis-text);">${this._escapeHtml(this._regenProgressText || "Rebuilding floor plan from scratch...")}</span>
              </div>
              <span id="regen-progress-pct" style="font-size: 0.8rem; font-weight: 700; color: var(--otis-primary);">${Number(this._regenProgressPercent || 5)}%</span>
            </div>
            <div style="width: 100%; height: 7px; border-radius: 999px; background: rgba(148, 163, 184, 0.22); overflow: hidden;">
              <div id="regen-progress-bar" style="width: ${Number(this._regenProgressPercent || 5)}%; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #0ea5e9, #38bdf8, #818cf8); transition: width 0.35s ease;"></div>
            </div>
            <div id="regen-discovered-chips" style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: ${this._regenDiscoveredAreas?.length ? "8px" : "0px"};">
              ${(this._regenDiscoveredAreas || []).map((name) => `<span style="font-size: 0.7rem; padding: 2px 8px; border-radius: 999px; background: rgba(56, 189, 248, 0.18); color: #7dd3fc;">✓ ${this._escapeHtml(name)}</span>`).join("")}
            </div>
          </div>
        `
        : ""
      }

        ${!isControlOnly && !this._hasWalkthrough && this._floorplanSvg && !this._editorActive
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

        ${this._loadingFloorplan
        ? `<div class="empty-state"><div class="spinner" style="margin: 0 auto 8px auto; width: 24px; height: 24px;"></div>Rendering vector floor plan...</div>`
        : this._floorplanSvg
          ? `
            <div class="floorplan-svg-viewport ${this._editorActive && isAdmin && !isControlOnly ? 'editor-mode' : ''} ${this._floorplanViewMode === '3d' ? 'view-3d-active' : ''}" id="floorplan-viewport">
              ${this._editorActive && isAdmin && !isControlOnly ? `<div class="editor-hud" id="editor-hud">📐 Pointer: --, --</div>` : ''}
              ${this._floorplanViewMode === '3d' && (!this._editorActive || isControlOnly) ? this._renderFloorplan3dControls(isControlOnly) : ''}
              <div class="floorplan-3d-stage" id="floorplan-3d-stage">
                <div class="floorplan-3d-canvas" id="floorplan-canvas" style="--floorplan-azimuth: ${this._floorplanAzimuth}deg; --floorplan-pitch: ${this._floorplanPitch}deg; --wall-height: ${this._floorplanWallHeight || 28}px; aspect-ratio: ${this._selectedFloorZone === 'main' ? '1300 / 713' : (this._selectedFloorZone === 'upper' ? '1300 / 488' : '1300 / 1250')};">
                  ${this._floorplanSvg}
                  <div class="floorplan-walls-overlay" id="floorplan-walls-overlay" style="${this._floorplanViewMode === '3d' && this._floorplanWallsEnabled !== false ? '' : 'display: none;'}">
                    ${this._renderFloorplan3dWalls()}
                  </div>
                  ${this._renderFloorplanPins()}
                </div>
              </div>
              ${this._editorActive && isAdmin && !isControlOnly && this._selectedEditorRoomId ? this._renderRoomInspector() : ""}
            </div>
            ${!this._editorActive && this._selectedRoomInfo
            ? `
              <div class="room-info-card" style="padding: 12px 16px; border-radius: 12px; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); margin-top: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                  <div>
                    <div style="font-weight: 700; color: var(--otis-primary); font-size: 0.95rem;">📍 ${this._escapeHtml(this._selectedRoomInfo.name)}</div>
                    <div style="font-size: 0.74rem; color: var(--otis-text-muted);">
                      ${(() => {
              const presEid = `binary_sensor.otis_presence_${this._selectedRoomInfo.slug}`;
              const presState = this._hass?.states?.[presEid];
              const isOccupied = presState?.state === "on";
              const prob = presState?.attributes?.probability ? Math.round(presState.attributes.probability * 100) : null;
              const presBadge = isOccupied
                ? `<span style="color: #10b981; font-weight: 700;">🟢 Active (${prob || 85}%)</span>`
                : `<span style="color: #94a3b8;">⚪ Vacant</span>`;
              return `Zone: ${String(this._selectedRoomInfo.zone).toUpperCase()} • ${this._selectedRoomInfo.entities.length} Devices • ${presBadge}`;
            })()}
                    </div>
                  </div>
                  <div style="display: flex; gap: 8px;">
                    ${this._selectedRoomInfo.slug ? (() => {
              const curPath = typeof window !== "undefined" ? window.location.pathname : "";
              const seg = curPath.split("/").filter(Boolean)[0] || "command-center";
              const navPath = `/${seg}/area_${this._selectedRoomInfo.slug}`;
              return `
                      <button type="button" class="btn-toolbar btn-nav-room" data-room-path="${navPath}" style="padding: 4px 10px; font-size: 0.75rem;">
                        Open Room Controls →
                      </button>
                      `;
            })() : ""}
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
                      <button type="button" class="subview-chip btn-quick-toggle" data-entity-id="${this._escapeHtml(eid)}" style="${isOn ? 'background: var(--otis-primary); color: #fff; border-color: var(--otis-primary);' : ''}">
                        ${this._escapeHtml(icon)} ${this._escapeHtml(st.attributes?.friendly_name || eid.split(".")[1])} (${this._escapeHtml(st.state)})
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
  },

  _renderFloorplan3dControls(isControlOnly = false) {
    if (this._editorActive) return "";
    const isCollapsed = Boolean(this._floorplanHudCollapsed);
    const isLocked = this._floorplanOrbitLocked !== false;
    const disabledAttr = isLocked ? "disabled" : "";
    const disabledStyle = isLocked ? "opacity: 0.45; pointer-events: none;" : "";

    return `
      <div class="floorplan-3d-hud ${isCollapsed ? 'collapsed' : ''}" id="floorplan-3d-hud">
        <div class="hud-header">
          <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
            <span class="hud-icon">🧭</span>
            <span class="hud-title">3D Orbit &amp; Pitch Controls</span>
            <span class="hud-badge" id="hud-orbit-readout">${Math.round(this._floorplanAzimuth)}° Az / ${Math.round(this._floorplanPitch)}° Pitch</span>
          </div>
          <div style="display: flex; align-items: center; gap: 6px;">
            <button type="button" class="btn-lock-pill ${isLocked ? 'active' : ''}" id="btn-toggle-3d-lock" title="${isLocked ? 'Unlock to adjust 3D Orbit & Pitch' : 'Lock 3D Orbit & Pitch to prevent accidental movement'}" style="padding: 3px 10px; font-size: 0.72rem; border-radius: 6px; border: 1px solid; cursor: pointer; ${isLocked ? 'background: rgba(245, 158, 11, 0.22); border-color: rgba(245, 158, 11, 0.65); color: #fbbf24; font-weight: 700;' : 'background: rgba(16, 185, 129, 0.22); border-color: rgba(16, 185, 129, 0.65); color: #34d399; font-weight: 700;'}">
              ${isLocked ? '🔒 Locked' : '🔓 Unlocked'}
            </button>
            <button type="button" class="btn-hud-toggle" id="btn-toggle-3d-hud" title="${isCollapsed ? 'Expand 3D Controls' : 'Collapse 3D Controls'}">
              ${isCollapsed ? '▾' : '▴'}
            </button>
          </div>
        </div>
        ${!isCollapsed ? `
        <div class="hud-body">
          <div class="hud-row" style="${disabledStyle}">
            <span class="hud-label">Orbit Azimuth:</span>
            <div class="hud-slider-wrap">
              <button type="button" class="btn-hud-step" id="btn-azimuth-step-minus" title="Rotate -15°" ${disabledAttr}>⟲</button>
              <input type="range" min="0" max="360" step="1" value="${Math.round(this._floorplanAzimuth)}" id="slider-orbit-azimuth" class="hud-slider" ${disabledAttr} />
              <button type="button" class="btn-hud-step" id="btn-azimuth-step-plus" title="Rotate +15°" ${disabledAttr}>⟳</button>
              <span class="hud-val" id="val-orbit-azimuth">${Math.round(this._floorplanAzimuth)}°</span>
            </div>
          </div>
          <div class="hud-row" style="${disabledStyle}">
            <span class="hud-label">Pitch Incline:</span>
            <div class="hud-slider-wrap">
              <button type="button" class="btn-hud-step" id="btn-pitch-step-minus" title="Lower Incline -5°" ${disabledAttr}>▼</button>
              <input type="range" min="30" max="75" step="1" value="${Math.round(this._floorplanPitch)}" id="slider-pitch-incline" class="hud-slider" ${disabledAttr} />
              <button type="button" class="btn-hud-step" id="btn-pitch-step-plus" title="Steepen Incline +5°" ${disabledAttr}>▲</button>
              <span class="hud-val" id="val-pitch-incline">${Math.round(this._floorplanPitch)}°</span>
            </div>
          </div>
          <div class="hud-row" style="${disabledStyle}">
            <span class="hud-label">3D Glass Walls:</span>
            <div style="display: flex; align-items: center; gap: 6px; flex: 1;">
              <button type="button" class="btn-preset-pill ${this._floorplanWallsEnabled !== false ? 'active' : ''}" id="btn-toggle-3d-walls" title="Toggle Raised 3D Glass Walls" ${disabledAttr}>
                ${this._floorplanWallsEnabled !== false ? '🏢 Walls ON' : '🏢 Walls OFF'}
              </button>
              <button type="button" class="btn-hud-step" id="btn-wall-height-minus" title="Lower Wall Height -4px" ${disabledAttr}>▼</button>
              <span class="hud-val" id="val-wall-height" style="min-width: 44px; text-align: center;">${Math.round(this._floorplanWallHeight || 28)}px</span>
              <button type="button" class="btn-hud-step" id="btn-wall-height-plus" title="Raise Wall Height +4px" ${disabledAttr}>▲</button>
            </div>
          </div>
          <div class="hud-row presets-row">
            <span class="hud-label">Presets:</span>
            <div class="hud-presets-wrap">
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 0 ? 'active' : ''}" data-azimuth="0" data-pitch="55" title="North (Front)" style="${disabledStyle}" ${disabledAttr}>0° N</button>
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 45 ? 'active' : ''}" data-azimuth="45" data-pitch="58" title="Isometric NE" style="${disabledStyle}" ${disabledAttr}>45° NE</button>
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 90 ? 'active' : ''}" data-azimuth="90" data-pitch="55" title="East" style="${disabledStyle}" ${disabledAttr}>90° E</button>
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 135 ? 'active' : ''}" data-azimuth="135" data-pitch="58" title="Isometric SE" style="${disabledStyle}" ${disabledAttr}>135° SE</button>
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 180 ? 'active' : ''}" data-azimuth="180" data-pitch="55" title="South (Rear)" style="${disabledStyle}" ${disabledAttr}>180° S</button>
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 225 ? 'active' : ''}" data-azimuth="225" data-pitch="58" title="Isometric SW" style="${disabledStyle}" ${disabledAttr}>225° SW</button>
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 270 ? 'active' : ''}" data-azimuth="270" data-pitch="55" title="West" style="${disabledStyle}" ${disabledAttr}>270° W</button>
              <button type="button" class="btn-preset-pill ${Math.round(this._floorplanAzimuth) === 315 ? 'active' : ''}" data-azimuth="315" data-pitch="58" title="Isometric NW" style="${disabledStyle}" ${disabledAttr}>315° NW</button>
              <button type="button" class="btn-preset-reset" id="btn-reset-3d-view" title="Reset to Default Isometric Projection" style="${disabledStyle}" ${disabledAttr}>↺ Reset</button>
              ${!isControlOnly ? `<button type="button" class="btn-preset-reset" id="btn-save-3d-dashboard" title="Save current 3D camera angles, walls &amp; zone to the Interactive Floor Plan dashboard view" style="background: rgba(14, 165, 233, 0.22); border-color: rgba(56, 189, 248, 0.55); color: #38bdf8; font-weight: 700;">💾 Save 3D to Dashboard</button>` : ""}
            </div>
          </div>
          <div class="hud-hint">
            <span>${isLocked ? '🔒 3D Orbit & Pitch locked for clean clicking • Click 🔒 Locked above to unlock' : '🖱️ Drag canvas to orbit freely • Scroll/pinch to zoom'}</span>
          </div>
        </div>
        ` : ''}
      </div>
    `;
  },

  _getFloorplanRooms() {
    const rooms = [];
    if (!this._floorplanSvg) return rooms;
    const gRegex = /<g\b[^>]*\bclass="[^"]*room-group[^"]*"[^>]*\bdata-area-id="([^"]+)"[^>]*\bdata-zone="([^"]+)"[^>]*>([\s\S]*?)<\/g>/gi;
    let gMatch;
    while ((gMatch = gRegex.exec(this._floorplanSvg)) !== null) {
      const rid = gMatch[1];
      const zone = gMatch[2];
      // Only indoor rooms have raised 3D glass walls - skip outdoor perimeter
      if (zone === "outdoor") continue;
      const inner = gMatch[3];
      const rectMatch = /<rect\b[^>]*>/i.exec(inner);
      if (rectMatch) {
        const tag = rectMatch[0];
        const xMatch = tag.match(/\bx="([^"]+)"/);
        const yMatch = tag.match(/\by="([^"]+)"/);
        const wMatch = tag.match(/\bwidth="([^"]+)"/);
        const hMatch = tag.match(/\bheight="([^"]+)"/);
        if (xMatch && yMatch && wMatch && hMatch) {
          rooms.push({
            id: rid,
            zone,
            x: parseFloat(xMatch[1]),
            y: parseFloat(yMatch[1]),
            width: parseFloat(wMatch[1]),
            height: parseFloat(hMatch[1]),
          });
        }
      }
    }
    return rooms;
  },

  _renderFloorplan3dWalls() {
    const rooms = this._getFloorplanRooms();
    if (!rooms.length) return "";

    const curZone = this._selectedFloorZone || "all";
    let vbX = 0, vbY = 0, vbW = 1300, vbH = 1250;
    if (curZone === "main") {
      vbX = 0; vbY = 17; vbW = 1300; vbH = 713;
    } else if (curZone === "upper") {
      vbX = 0; vbY = 737; vbW = 1300; vbH = 488;
    } else {
      const vbMatch = /viewBox="([^"]+)"/i.exec(this._floorplanSvg || "");
      if (vbMatch) {
        const parts = vbMatch[1].split(/[\s,]+/).map(Number);
        if (parts.length === 4 && !isNaN(parts[2]) && parts[2] > 0) {
          vbX = parts[0];
          vbY = parts[1];
          vbW = parts[2];
          vbH = parts[3];
        }
      }
    }

    return rooms
      .map((r) => {
        const isHidden = (curZone === "main" && r.zone === "upper") ||
          (curZone === "upper" && r.zone !== "upper") ||
          (curZone === "outdoor" && r.zone !== "outdoor");
        const pctX = ((r.x - vbX) / vbW) * 100;
        const pctY = ((r.y - vbY) / vbH) * 100;
        const pctW = (r.width / vbW) * 100;
        const pctH = (r.height / vbH) * 100;

        const presEid = `binary_sensor.otis_presence_${r.id.toLowerCase().replace(/[^a-z0-9_]/g, "_")}`;
        const presState = this._hass?.states?.[presEid];
        const isOccupied = presState?.state === "on";

        return `
          <div
            class="floorplan-3d-room-shell ${isOccupied ? "is-occupied" : ""}"
            data-room-id="${this._escapeHtml(r.id)}"
            data-zone="${this._escapeHtml(r.zone)}"
            data-x="${r.x}"
            data-y="${r.y}"
            data-w="${r.width}"
            data-h="${r.height}"
            style="${isHidden ? "display: none; " : ""}left: ${pctX.toFixed(3)}%; top: ${pctY.toFixed(3)}%; width: ${pctW.toFixed(3)}%; height: ${pctH.toFixed(3)}%;"
          >
            <div class="floorplan-3d-wall floorplan-3d-wall-north"></div>
            <div class="floorplan-3d-wall floorplan-3d-wall-south"></div>
            <div class="floorplan-3d-wall floorplan-3d-wall-west"></div>
            <div class="floorplan-3d-wall floorplan-3d-wall-east"></div>
          </div>
        `;
      })
      .join("");
  },

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
            ${allAreas.map(a => `<option value="${this._escapeHtml(a.id)}" ${a.id === rid ? "selected" : ""}>${this._escapeHtml(a.name)} (${this._escapeHtml(a.id)})</option>`).join("")}
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
        <div style="display: flex; flex-direction: column; gap: 4px; margin-top: 4px;">
          <label style="font-size: 0.68rem; color: var(--otis-text-muted);">Room Label:</label>
          <input type="text" id="inspector-room-name" style="width: 100%; box-sizing: border-box; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 4px; padding: 4px 6px; font-size: 0.74rem;" />
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 0.68rem; color: var(--otis-text-muted);">Sub-Labels (one per line, clear to remove):</label>
          <textarea id="inspector-room-subzones" rows="3" placeholder="e.g. Fitness Zone&#10;Leave empty to remove all sub-labels" style="width: 100%; box-sizing: border-box; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); border-radius: 4px; padding: 4px 6px; font-size: 0.72rem; resize: vertical; font-family: inherit;"></textarea>
        </div>
        <div style="display: flex; gap: 6px; margin-top: 6px;">
          <button type="button" class="btn-modal-primary" id="btn-apply-inspector-dim" style="flex: 1; padding: 5px 8px; font-size: 0.74rem;">
            ✓ Update Boundary
            ✓ Update Room
          </button>
          <button type="button" class="btn-toolbar" id="btn-delete-inspector-room" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.35); padding: 5px 10px; font-size: 0.74rem; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 4px;">
            <span>🗑️</span><span>Delete Room</span>
          </button>
        </div>
      </div>
    `;
  },

  _projectToIso(x, y) {
    const originX = 650.0;
    const originY = 640.0;
    const scale = 0.58;
    const cx = 680.0;
    const cy = 385.0;
    const cos30 = 0.866025;
    const sin30 = 0.500000;
    const isUpper = y >= 720;
    const yLoc = isUpper ? y - 720 : y;
    const z = isUpper ? 320.0 : (y >= 580 ? -6.0 : 0.0);
    const dx = (x - cx) * scale;
    const dy = (yLoc - cy) * scale;
    const ix = originX + (dx - dy) * cos30;
    const iy = originY + (dx + dy) * sin30 - z;
    return { x: Math.round(ix * 10) / 10, y: Math.round(iy * 10) / 10, isUpper };
  },

  _renderFloorplanPins() {
    const rawBadges = this._capabilityMap?.floorplan?.custom_layout?.badges || [];
    const badgesMap = {};
    rawBadges.forEach((b) => {
      if (!b || !b.entity_id) return;
      if (b.delete || b.deleted) {
        delete badgesMap[b.entity_id];
      } else {
        badgesMap[b.entity_id] = { ...b };
      }
    });
    Object.entries(this._dirtyBadges || {}).forEach(([eid, b]) => {
      if (b.delete) delete badgesMap[eid];
      else badgesMap[eid] = { ...badgesMap[eid], ...b };
    });

    const badges = Object.values(badgesMap);
    if (!badges.length) return "";

    return `
      <div class="floorplan-pins-overlay" id="floorplan-pins-overlay">
        ${badges
        .map((b) => {
          const eid = b.entity_id;
          const stateObj = this._hass?.states?.[eid];
          const name = stateObj?.attributes?.friendly_name || eid;
          const state = stateObj?.state || "unknown";
          const isActive = this._isPinEntityActive(stateObj);
          const activeColor = this._getPinActiveColor(eid);
          const pinColor = isActive ? activeColor : "#94a3b8";
          const bx = parseFloat(b.x || 300);
          const by = parseFloat(b.y || 300);
          const isoPt = this._projectToIso(bx, by);

          return `
              <div
                class="floorplan-device-pin ${isActive ? "is-active" : ""} ${this._editorActive ? "is-draggable" : ""}"
                data-entity-id="${this._escapeHtml(eid)}"
                data-x="${bx}"
                data-y="${by}"
                data-iso-x="${isoPt.x}"
                data-iso-y="${isoPt.y}"
                data-is-upper="${isoPt.isUpper ? "1" : "0"}"
                title="${this._escapeHtml(name)}: ${this._escapeHtml(state)}"
                style="display: none; top: 0px; left: 0px; --paper-item-icon-color: ${pinColor}; --paper-item-icon-active-color: ${activeColor}; --state-icon-color: ${pinColor}; --state-icon-active-color: ${activeColor}; color: ${pinColor};"
              >
                <ha-state-icon style="color: ${pinColor}; --paper-item-icon-color: ${pinColor}; --state-icon-color: ${pinColor};"></ha-state-icon>
              </div>
            `;
        })
        .join("")}
      </div>
    `;
  },

};
