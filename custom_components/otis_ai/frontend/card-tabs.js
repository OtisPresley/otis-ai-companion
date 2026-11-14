/** Tab renderers (Suggestions, Chat, Capabilities, Media Studio, Vision) for OtisCompanionCard. */
export const tabsMixin = {
  _renderSuggestionsTab(visibleSuggestions) {
    const showIgnored = Boolean(
      this._localShowIgnored ||
      this._config.show_ignored ||
      this._userRules?.show_ignored_recommendations
    );
    const activeIgnored = (this._suggestions || []).filter((s) => this._dismissedIds.has(s.id));
    const ignoredCount = activeIgnored.length;
    const categories = [
      { key: "all", label: "All" },
      { key: "presence", label: "👥 People & Pets" },
      { key: "migration", label: "🚀 Migrations" },
      { key: "news", label: "📰 Official News" },
      { key: "habits", label: "Habits & Routines" },
      { key: "lighting", label: "Lighting & Auto" },
      { key: "media", label: "Media" },
      { key: "security", label: "Security" },
      { key: "energy", label: "Energy" },
      { key: "mesh", label: "Mesh & Zigbee" },
      { key: "dashboard", label: "Dashboards" },
      { key: "cleanup", label: "Cleanup" },
      { key: "system", label: "System" },
    ];
    return `
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; flex-wrap: wrap;">
        <div class="category-pills" style="margin-bottom: 0;">
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
        ${this._dismissedIds && this._dismissedIds.size > 0
        ? `
          <div style="display: flex; align-items: center; gap: 6px; margin-left: auto;">
            <button type="button" class="btn-subtle-toggle ${showIgnored ? "active" : ""}" id="btn-toggle-show-ignored" title="${showIgnored ? "Hide dismissed suggestions" : "Show dismissed suggestions"}">
              ${showIgnored ? "👁️ Hide Ignored" : `👁️ Show Ignored (${ignoredCount})`}
            </button>
            <button type="button" class="btn-subtle-toggle" id="btn-reset-ignored" title="Restore all ignored suggestions">
              ↺ Reset
            </button>
          </div>
        `
        : ""
      }
      </div>
      ${this._selectedCategory === "presence" ? this._renderPeopleTrainingSummaryBanner() : ""}
      <div class="suggestions-list">
        ${this._loadingSuggestions
        ? `<div class="empty-state"><div class="spinner" style="margin: 0 auto 8px auto; width: 20px; height: 20px;"></div>Analyzing home capabilities...</div>`
        : visibleSuggestions.length === 0
          ? `<div class="empty-state"><div class="empty-icon">✨</div>${this._selectedCategory === "all"
            ? "Your smart home is running optimally! No proactive recommendations right now."
            : `No active recommendations in the "${this._selectedCategory}" category.`
          }</div>`
          : visibleSuggestions
            .map((s) => {
              const isApplying = this._applyingIds.has(s.id);
              const btnLabel = this._getActionLabel(s.action_type);
              const isDismissed = this._dismissedIds.has(s.id);
              return `
                    <div class="suggestion-card ${isDismissed ? "is-ignored" : ""}" data-id="${this._escapeHtml(s.id)}">
                      <div class="suggestion-top">
                        <div class="suggestion-badge-group">
                          <span class="badge-category">${this._escapeHtml(s.category || "automation")}</span>
                          <span class="badge-priority ${this._escapeHtml(s.priority || "medium")}">${this._escapeHtml(s.priority || "medium")}</span>
                          ${isDismissed ? `<span class="badge-priority ignored">Ignored</span>` : ""}
                        </div>
                        ${isDismissed
                  ? `<button type="button" class="dismiss-btn" data-restore="${this._escapeHtml(s.id)}" title="Restore recommendation">↺</button>`
                  : `<button type="button" class="dismiss-btn" data-session-dismiss="${this._escapeHtml(s.id)}" title="Dismiss card from feed">✕</button>`
                }
                      </div>
                      <div class="suggestion-title">${this._escapeHtml(s.title || "")}</div>
                      <div class="suggestion-desc">${this._escapeHtml(s.description || "").replace(/\n/g, "<br>")}</div>
                      ${s.action_type === "confirm_person_identity" || s.action_type === "confirm_room_transition" ? this._renderTrainingVerificationMedia(s) : ""}
                      <div class="suggestion-actions">
                        ${s.action_type === "sentinel_alert_actions"
                  ? `
                          <div style="display: flex; gap: 8px; flex-wrap: wrap; width: 100%;">
                            ${isDismissed
                    ? `<button type="button" class="btn-toolbar btn-restore" data-restore="${this._escapeHtml(s.id)}">↺ Restore Alert</button>`
                    : `
                                <button type="button" class="btn-toolbar btn-ignore-alert" data-ignore-id="${this._escapeHtml(s.id)}" style="padding: 6px 12px; font-size: 0.76rem;">
                                  ${this._escapeHtml(s.action_payload?.dismiss_single_label || "Ignore this alert")}
                                </button>
                                <button type="button" class="btn-toolbar btn-ignore-category" data-ignore-cat="${this._escapeHtml(s.action_payload?.category || s.anomaly_type || 'battery')}" style="padding: 6px 12px; font-size: 0.76rem; color: var(--otis-primary); border-color: var(--otis-primary);">
                                  ${this._escapeHtml(s.action_payload?.dismiss_category_label || "Ignore all alerts in this category")}
                                </button>
                              `
                  }
                          </div>
                        `
                  : s.action_type === "confirm_person_identity" && Array.isArray(s.action_payload?.candidates) && s.action_payload.candidates.length > 0
                    ? `
                          <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
                            <div style="font-size: 0.73rem; font-weight: 600; color: var(--otis-primary);">Tap who entered ${this._escapeHtml(s.action_payload.area_name || s.action_payload.area || "this room")}:</div>
                            <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center;">
                              ${s.action_payload.candidates.map((cand) => {
                      const cIcon = cand.entity_type === "pet" ? "🐾" : (cand.entity_type === "guest" ? "👥" : "👤");
                      return `
                                  <button type="button" class="apply-btn btn-verify-room-candidate" data-suggestion-id="${this._escapeHtml(s.id)}" data-person-id="${this._escapeHtml(cand.person_id)}" data-person-label="${this._escapeHtml(cand.label)}" data-area="${this._escapeHtml(s.action_payload.area || "")}" data-area-name="${this._escapeHtml(s.action_payload.area_name || "")}" style="padding: 5px 11px; font-size: 0.75rem;">
                                    ${cIcon} ${this._escapeHtml(cand.label)} (${Math.round((cand.confidence || 0.5) * 100)}%)
                                  </button>
                                `;
                    }).join("")}
                              <button type="button" class="btn-toolbar btn-verify-room-candidate" data-suggestion-id="${this._escapeHtml(s.id)}" data-person-id="unknown_person" data-person-label="Unknown Person" data-area="${this._escapeHtml(s.action_payload.area || "")}" data-area-name="${this._escapeHtml(s.action_payload.area_name || "")}" title="Log as an unknown visitor, delivery person, or passerby" style="padding: 5px 10px; font-size: 0.74rem; background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.45); color: #fbbf24; border-radius: 6px; cursor: pointer;">
                                🕵️ Unknown Person
                              </button>
                              <button type="button" class="btn-toolbar btn-verify-room-candidate" data-suggestion-id="${this._escapeHtml(s.id)}" data-person-id="unknown_animal" data-person-label="Unknown Animal" data-area="${this._escapeHtml(s.action_payload.area || "")}" data-area-name="${this._escapeHtml(s.action_payload.area_name || "")}" title="Log as wildlife or a non-household animal" style="padding: 5px 10px; font-size: 0.74rem; background: rgba(16, 185, 129, 0.14); border: 1px solid rgba(16, 185, 129, 0.45); color: #34d399; border-radius: 6px; cursor: pointer;">
                                🦊 Unknown Animal
                              </button>
                              <button type="button" class="btn-toolbar btn-verify-room-candidate" data-suggestion-id="${this._escapeHtml(s.id)}" data-person-id="not_person_pet" data-person-label="Not Person/Pet" data-area="${this._escapeHtml(s.action_payload.area || "")}" data-area-name="${this._escapeHtml(s.action_payload.area_name || "")}" title="Mark as false positive (wind, shadows, foliage, or object)" style="padding: 5px 10px; font-size: 0.74rem; background: rgba(239, 68, 68, 0.14); border: 1px solid rgba(239, 68, 68, 0.45); color: #f87171; border-radius: 6px; cursor: pointer;">
                                🚫 Not Person/Pet
                              </button>
                              ${isDismissed
                      ? `<button type="button" class="btn-restore" data-restore="${this._escapeHtml(s.id)}">↺ Restore</button>`
                      : `<button type="button" class="btn-dismiss-card" data-dismiss="${this._escapeHtml(s.id)}" title="Dismiss this room prompt">Ignore</button>`
                    }
                            </div>
                          </div>
                        `
                    : s.action_type === "confirm_room_transition" && Array.isArray(s.action_payload?.candidate_rooms) && s.action_payload.candidate_rooms.length > 0
                      ? `
                          <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
                            <div style="font-size: 0.73rem; font-weight: 600; color: var(--otis-primary);">${s.action_payload.direction === "leaving" ? `Select which room the ${this._escapeHtml(s.action_payload.subject || "person")} went to from ${this._escapeHtml(s.action_payload.from_area_name || s.action_payload.from_area || "this area")}:` : `Select which room the ${this._escapeHtml(s.action_payload.subject || "person")} came from into ${this._escapeHtml(s.action_payload.from_area_name || s.action_payload.from_area || "this area")}:`}</div>
                            <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center;">
                              ${s.action_payload.candidate_rooms.map((rm) => `
                                <button type="button" class="apply-btn btn-confirm-room-transition" data-suggestion-id="${this._escapeHtml(s.id)}" data-to-area="${this._escapeHtml(rm.area_id)}" data-to-area-name="${this._escapeHtml(rm.area_name || rm.area_id)}" style="padding: 5px 11px; font-size: 0.75rem;">
                                  🚪 ${this._escapeHtml(rm.area_name || rm.area_id)}
                                </button>
                              `).join("")}
                              <button type="button" class="btn-toolbar btn-confirm-room-transition" data-suggestion-id="${this._escapeHtml(s.id)}" data-to-area="__other__" data-to-area-name="Other / Exterior" style="padding: 5px 10px; font-size: 0.73rem;" title="Came from or went to another room or outdoors">
                                🤷 Other / Exterior
                              </button>
                              <button type="button" class="btn-toolbar btn-confirm-room-transition" data-suggestion-id="${this._escapeHtml(s.id)}" data-to-area="__not_a_person__" data-to-area-name="Not a Person" style="padding: 5px 10px; font-size: 0.73rem; border-color: rgba(239, 68, 68, 0.45); color: #fca5a5;" title="False detection or no person visible">
                                🚫 Not a Person
                              </button>
                              ${isDismissed
                        ? `<button type="button" class="btn-restore" data-restore="${this._escapeHtml(s.id)}">↺ Restore</button>`
                        : `<button type="button" class="btn-dismiss-card" data-dismiss="${this._escapeHtml(s.id)}" title="Dismiss this room transition prompt">Ignore</button>`
                      }
                            </div>
                          </div>
                        `
                      : s.action_type === "github_report_issue"
                        ? `
                          <div style="display: flex; gap: 8px; flex-wrap: wrap; width: 100%;">
                            <button type="button" class="apply-btn btn-report-github" data-suggestion-id="${this._escapeHtml(s.id)}" style="padding: 5px 12px; font-size: 0.76rem; background: linear-gradient(135deg, #1f2937 0%, #0284c7 100%); color: #fff; border: 1px solid rgba(255,255,255,0.2);">
                              🚀 Report to GitHub
                            </button>
                            ${isDismissed
                          ? `<button type="button" class="btn-restore" data-restore="${this._escapeHtml(s.id)}">↺ Restore</button>`
                          : `<button type="button" class="btn-dismiss-card" data-dismiss="${this._escapeHtml(s.id)}" title="Ignore this error">Ignore</button>`
                        }
                          </div>
                        `
                        : s.action_type === "tracked_github_issue"
                          ? `
                          <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; width: 100%;">
                            <a href="${this._escapeHtml(s.action_payload?.issue_url || '#')}" target="_blank" rel="noopener noreferrer" class="apply-btn" style="text-decoration: none; display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; font-size: 0.76rem; background: rgba(14, 165, 233, 0.15); border: 1px solid var(--otis-primary); color: #38bdf8;">
                              🔗 View on GitHub ↗
                            </a>
                            <button type="button" class="btn-toolbar btn-dismiss-tracked-issue" data-track-id="${this._escapeHtml(s.action_payload?.track_id || '')}" style="padding: 5px 10px; font-size: 0.74rem;">
                              ✕ Dismiss Tracking
                            </button>
                          </div>
                        `
                          : s.action_type === "dismiss_self_healing_alert"
                            ? `
                          <div style="display: flex; gap: 8px; width: 100%;">
                            <button type="button" class="btn-dismiss-card" data-dismiss="${this._escapeHtml(s.id)}">Acknowledge</button>
                          </div>
                        `
                            : `
                          <button type="button" class="apply-btn" data-apply="${this._escapeHtml(s.id)}" ${isApplying ? "disabled" : ""}>
                            ${isApplying ? `<div class="spinner"></div> Applying...` : this._escapeHtml(btnLabel)}
                          </button>
                          ${s.action_type === "configure_agent" && s.action_payload?.domain
                              ? `<a href="/config/integrations/integration/${this._escapeHtml(encodeURIComponent(s.action_payload.domain))}" target="_blank" rel="noopener noreferrer" class="btn-toolbar" style="text-decoration: none; padding: 6px 12px; font-size: 0.76rem; display: inline-flex; align-items: center; gap: 5px;" title="Open integration settings directly in Home Assistant">🔗 Open Integration ↗</a>`
                              : ""
                            }
                          ${this._hasReviewableCode(s)
                              ? `<button type="button" class="btn-toolbar btn-review-suggestion" data-review="${this._escapeHtml(s.id)}" style="padding: 6px 12px; font-size: 0.76rem;" title="Review the automation, script, or blueprint YAML before applying">👁️ Review</button>`
                              : ""
                            }
                          ${isDismissed
                              ? `<button type="button" class="btn-restore" data-restore="${this._escapeHtml(s.id)}" title="Restore to active recommendations">↺ Restore</button>`
                              : `<button type="button" class="btn-dismiss-card" data-dismiss="${this._escapeHtml(s.id)}" title="Ignore this recommendation">Ignore this</button>`
                            }
                          ${s.action_type === "load_shed" && Array.isArray(s.action_payload?.candidates) && s.action_payload.candidates.length > 0
                              ? `<div style="display: flex; gap: 6px; flex-wrap: wrap; width: 100%; margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(148, 163, 184, 0.14);">
                                  <span style="font-size: 0.70rem; color: var(--otis-text-muted); align-self: center;">Exclude from shedding:</span>
                                  ${s.action_payload.candidates.map((c) => `
                                    <button type="button" class="btn-toolbar btn-exclude-shed-load" data-entity-id="${this._escapeHtml(c.entity_id)}" data-entity-name="${this._escapeHtml(c.name || c.entity_id)}" style="padding: 3px 8px; font-size: 0.70rem; color: #cbd5e1;" title="Never recommend shedding ${this._escapeHtml(c.name || c.entity_id)}">
                                      🚫 ${this._escapeHtml(c.name || c.entity_id)}
                                    </button>
                                  `).join("")}
                                </div>`
                              : ""
                            }
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
  },

  _renderChatActionButtons(m) {
    if (m.sender !== "otis" || m.isError) return "";
    const txt = m.text || "";
    const hasRemovedYaml = txt.includes("Removed draft YAML block");
    const hasYamlBlock = /```yaml[\s\S]*?```/i.test(txt);
    const hasConfirmPrompt =
      /Say\s+(?:['"`*]+)?yes(?:['"`*]+)?\s+or\s+(?:['"`*]+)?(?:apply|confirm)(?:['"`*]+)?/i.test(txt) ||
      txt.includes("Would you like me to deploy and enable") ||
      txt.includes("Would you like me to create and enable");
    if (hasRemovedYaml) return "";
    if (
      hasYamlBlock && (
        txt.includes("Would you like me to update and deploy this blueprint") ||
        txt.includes("Would you like me to update this blueprint") ||
        txt.includes("Would you like me to create this blueprint") ||
        (txt.toLowerCase().includes("blueprint") && hasConfirmPrompt)
      )
    ) {
      return `
        <div class="chat-macro-actions">
          <button type="button" class="macro-action-btn confirm" data-chip="apply">🚀 Deploy & Update Blueprint</button>
          <button type="button" class="macro-action-btn cancel" data-chip="cancel">✕ Cancel</button>
        </div>
      `;
    }
    if (
      hasYamlBlock && (
        txt.includes("Would you like me to create and enable this automation") ||
        txt.includes("Would you like me to deploy and enable") ||
        ((txt.toLowerCase().includes("automation") || /```yaml[\s\S]*?(?:trigger|triggers):[\s\S]*?(?:action|actions):/i.test(txt)) && hasConfirmPrompt)
      )
    ) {
      return `
        <div class="chat-macro-actions">
          <button type="button" class="macro-action-btn confirm" data-chip="apply">🚀 Deploy & Enable Automation</button>
          <button type="button" class="macro-action-btn cancel" data-chip="cancel">✕ Cancel</button>
        </div>
      `;
    }
    if (
      hasYamlBlock && (
        txt.includes("Would you like me to create this script") ||
        (txt.toLowerCase().includes("script") && hasConfirmPrompt)
      )
    ) {
      return `
        <div class="chat-macro-actions">
          <button type="button" class="macro-action-btn confirm" data-chip="apply">🚀 Deploy & Enable Script</button>
          <button type="button" class="macro-action-btn cancel" data-chip="cancel">✕ Cancel</button>
        </div>
      `;
    }
    if (hasConfirmPrompt) {
      return `
        <div class="chat-macro-actions">
          <button type="button" class="macro-action-btn confirm" data-chip="apply">✅ Confirm & Deploy</button>
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
  },

  _renderReasoningTrace(m) {
    const traceId = m.id || m.timestamp || m.text;
    const isExpanded = this._expandedReasoningIds.has(traceId);
    const steps = (m.reasoning && m.reasoning.steps) || [];

    // Check if an agent_resolution step exists
    const resStep = steps.find((s) => s.id === "agent_resolution" || (s.title && s.title.startsWith("Resolved by")));
    const failStep = steps.find((s) => s.id === "agent_exhaustion" || (s.title && s.title.includes("Unavailable")));
    const learnedStep = steps.find((s) => s.id === "learned_rules" || (s.title && s.title.startsWith("Applied ")));
    let agentBadge = "";
    if (resStep) {
      const isLocal = resStep.title.toLowerCase().includes("local") || resStep.title.toLowerCase().includes("edge");
      const icon = isLocal ? "⚡" : "☁️";
      const cleanTitle = resStep.title.replace("Resolved by ", "").trim();
      agentBadge = ` • <span class="reasoning-agent-pill ${isLocal ? 'edge' : 'cloud'}" title="${this._escapeHtml(resStep.detail || cleanTitle)}">${icon} ${this._escapeHtml(cleanTitle)}</span>`;
    } else if (failStep) {
      agentBadge = ` • <span class="reasoning-agent-pill failed" title="${this._escapeHtml(failStep.detail || 'All AI Providers Unavailable')}">⚠️ Unavailable</span>`;
    }
    let learnedBadge = "";
    if (learnedStep) {
      learnedBadge = ` • <span class="reasoning-agent-pill learned" title="${this._escapeHtml(learnedStep.detail || learnedStep.title)}">📚 ${this._escapeHtml(learnedStep.title)}</span>`;
    }

    return `
      <div class="reasoning-trace-container">
        <button type="button" class="reasoning-trace-toggle ${isExpanded ? "expanded" : ""}" data-trace-id="${this._escapeHtml(traceId)}">
          <span class="reasoning-brain-icon">🧠</span>
          <span class="reasoning-summary-text">Thought for ${this._escapeHtml(m.reasoning.duration || "a moment")} (${steps.length} steps)${agentBadge}${learnedBadge}</span>
          <svg class="reasoning-chevron" viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
        </button>
        <div class="reasoning-steps-list" style="${isExpanded && steps.length > 0 ? "" : "display: none;"}">
          ${steps
        .map(
          (s) => {
            const isResolution = s.id === "agent_resolution" || (s.title && s.title.startsWith("Resolved by"));
            const isExhaustion = s.id === "agent_exhaustion" || (s.title && s.title.includes("Unavailable"));
            const isLearned = s.id === "learned_rules" || (s.title && s.title.startsWith("Applied "));
            const isLocal = isResolution && (s.title.toLowerCase().includes("local") || s.title.toLowerCase().includes("edge"));
            const checkIcon = isExhaustion ? "⚠️" : isResolution ? (isLocal ? "⚡" : "☁️") : isLearned ? "📚" : "✓";
            const itemClass = isExhaustion ? "reasoning-step-item failed exhaustion" : isResolution ? "reasoning-step-item done resolution" : "reasoning-step-item done";
            return `
            <div class="${itemClass}">
              <span class="step-check">${checkIcon}</span>
              <div class="step-content">
                <div class="step-title">${this._escapeHtml(s.title || "Step")}</div>
                <div class="step-detail">${this._escapeHtml(s.detail || "")}</div>
              </div>
              <span class="step-time">${this._escapeHtml(s.time || "")}</span>
            </div>
          `;
          }
        )
        .join("")}
        </div>
      </div>
    `;
  },

  _renderChatTab() {
    return `
      <div class="chat-container">
        <div class="chat-chips">
          <button type="button" class="chip-btn" data-chip="Prep home for movie night">🎬 Movie Night</button>
          <button type="button" class="chip-btn" data-chip="Goodnight routine">🌙 Goodnight</button>
          <button type="button" class="chip-btn" data-chip="Party mode">🥂 Party Mode</button>
          <button type="button" class="chip-btn" data-chip="Lockdown home">🛡️ Lockdown</button>
          <button type="button" class="chip-btn" data-chip="Energy summary">⚡ Energy Summary</button>
          <button type="button" class="chip-btn" data-chip="Shed non-essential loads">📉 Shed Loads</button>
          <button type="button" class="chip-btn" data-chip="Handoff audio to study">🎵 Audio Handoff</button>
          <button type="button" class="chip-btn" data-chip="Release idle sources">🔇 Idle Guard</button>
          <button type="button" class="chip-btn" data-chip="Suggest automations for my active areas">💡 Automations</button>
          <button type="button" class="chip-btn" data-chip="Clean up orphaned entities">🧹 Clean orphans</button>
          <button type="button" class="chip-btn" data-chip="Undo last macro">↺ Undo</button>
          <button type="button" class="chip-btn" id="btn-clear-chat" title="Clear conversation history">🗑️ Clear</button>
        </div>
        <div class="chat-history" id="chat-history">
          ${this._chatMessages.length === 0
        ? `<div class="empty-state" style="padding: 16px;">Ask Otis anything about your automations, devices, or areas.</div>`
        : this._chatMessages
          .map(
            (m) => `
                <div class="chat-bubble ${m.sender} ${m.isError ? "error" : ""}">
                  ${m.sender === "user"
                ? `
                    <button type="button" class="prompt-copy-btn" title="Copy prompt to input" data-prompt="${this._escapeHtml(m.text)}">
                      <svg viewBox="0 0 24 24" class="copy-icon">
                        <path d="M16 1H4C2.9 1 2 1.9 2 3v14h2V3h12V1zm3 4H8C6.9 5 6 5.9 6 7v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                      </svg>
                    </button>
                  `
                : `
                    <div class="bubble-actions-group">
                      <button type="button" class="response-retry-btn" title="Retry this turn" data-msg-id="${this._escapeHtml(m.id || "")}">
                        <svg viewBox="0 0 24 24" class="copy-icon">
                          <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
                        </svg>
                        <span class="retry-label">Retry</span>
                      </button>
                      <button type="button" class="response-copy-btn" title="Copy response to clipboard" data-response="${this._escapeHtml(m.text)}">
                        <svg viewBox="0 0 24 24" class="copy-icon">
                          <path d="M16 1H4C2.9 1 2 1.9 2 3v14h2V3h12V1zm3 4H8C6.9 5 6 5.9 6 7v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                        </svg>
                        <span class="copy-label">Copy</span>
                      </button>
                    </div>
                  `
              }
                  ${m.attachments && m.attachments.length > 0
                ? `
                    <div class="bubble-attachments">
                      ${m.attachments
                  .map((att) =>
                    att.isImage
                      ? `<img src="${att.data}" class="bubble-attachment-img" alt="${this._escapeHtml(att.name)}" title="${this._escapeHtml(att.name)}" />`
                      : `<div class="bubble-attachment-file"><span>📄</span> ${this._escapeHtml(att.name)}</div>`
                  )
                  .join("")}
                    </div>
                  `
                : ""
              }
                  ${m.sender === "otis" && m.reasoning && m.reasoning.steps && m.reasoning.steps.length
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
          ${this._isSendingChat
        ? `
            <div class="chat-bubble otis thinking-bubble" id="active-thinking-bubble">
              <div class="thinking-bubble-header">
                <span class="otis-badge">🤖 Otis</span>
                <span class="thinking-status-pill">
                  <span class="pill-pulse-dot"></span>
                  <span id="thinking-pill-text">Reasoning</span>
                </span>
                <span class="thinking-timer" id="thinking-elapsed-timer">⏱️ 0.0s</span>
                <button type="button" class="chat-stop-btn" id="btn-stop-thinking-bubble" title="Stop reasoning">⏹️ Stop</button>
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
        ${this._isSendingChat
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
            <button type="button" class="chat-stop-btn" id="btn-stop-thinking-banner" title="Stop reasoning">⏹️ Stop</button>
          </div>
        `
        : ""
      }
        ${this._pendingAttachments && this._pendingAttachments.length > 0
        ? `
          <div class="chat-attachments-tray">
            ${this._pendingAttachments
          .map(
            (att, i) => `
              <div class="chat-attachment-item">
                ${att.isImage
                ? `<img src="${att.data}" class="chat-attachment-thumb" alt="${this._escapeHtml(att.name)}" />`
                : `<span>📄</span>`
              }
                <span class="chat-attachment-name" title="${this._escapeHtml(att.name)}">${this._escapeHtml(att.name)}</span>
                <button type="button" class="chat-attachment-remove" data-remove-att="${i}" title="Remove file">✕</button>
              </div>
            `
          )
          .join("")}
          </div>
        `
        : ""
      }
        <div class="chat-input-bar">
          <input type="file" id="chat-file-input" accept="image/*,.txt,.yaml,.yml,.json,.csv,.log,.svg" multiple style="display:none;" />
          <button type="button" class="attach-btn" id="chat-attach-btn" title="Attach file or image" ${this._isSendingChat ? "disabled" : ""}>
            <svg viewBox="0 0 24 24" style="width: 18px; height: 18px; fill: currentColor;">
              <path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5a2.5 2.5 0 0 1 5 0v10.5c0 .83-.67 1.5-1.5 1.5s-1.5-.67-1.5-1.5V6H9v9.5a3 3 0 0 0 6 0V5a4 4 0 0 0-8 0v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/>
            </svg>
          </button>
          <div class="chat-input-wrapper ${this._isListening ? "listening" : ""} ${this._isSendingChat ? "sending" : ""}">
            ${this._isListening
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
          <button type="button" class="send-btn ${this._isSendingChat ? "sending" : ""}" id="chat-send" title="${this._isSendingChat ? "Stop in-flight reasoning" : "Send message"}">
            ${this._isSendingChat
        ? "⏹️ Stop"
        : "Send"
      }
          </button>
        </div>
      </div>
    `;
  },

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

    const comm = this._capabilityMap?.commissioning || {};
    const fed = this._capabilityMap?.federation || {};

    const categories = [
      { key: "spatial", label: "Spatial", max: 20 },
      { key: "hygiene", label: "Hygiene", max: 20 },
      { key: "automation", label: "Automations", max: 20 },
      { key: "security", label: "Security", max: 20 },
      { key: "media", label: "Media", max: 20 },
    ];
    const tips = maturity.tips || {};

    const getMaturityTip = (key, val) => {
      if (tips[key]) return tips[key];
      if (val >= 20) return "20/20 (Perfect) • Fully mature smart home standard achieved.";
      switch (key) {
        case "spatial":
          return `${val}/20 • To reach 20/20: Add at least 3 areas, assign entities to rooms, and create an interactive Floor Plan or walkthrough video.`;
        case "hygiene":
          return `${val}/20 • To reach 20/20: Clean up orphaned entities and auto-commission unassigned devices to their rooms.`;
        case "automation":
          return `${val}/20 • To reach 20/20: Create essential room occupancy lighting, climate guards, and daily routines to reach 5+ automations/scripts.`;
        case "security":
          return `${val}/20 • To reach 20/20: Install an alarm panel (e.g. Alarmo), configure smart locks, and set up presence/occupancy detection.`;
        case "media":
          return `${val}/20 • To reach 20/20: Deploy a multi-zone audio router, configure speaker grouping, or pair Music Assistant for whole-home audio.`;
        default:
          return `${val}/20 • Complete recommendations in the Proactive Feed to reach 20/20 maturity.`;
      }
    };

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
            ${categories
        .map((c) => {
          const val = bd[c.key] ?? 0;
          const tip = getMaturityTip(c.key, val);
          const isMax = val >= 20;
          return `
                  <div class="maturity-pill ${isMax ? "maturity-pill-max" : "maturity-pill-improve"}"
                       data-cat="${c.key}"
                       title="${tip.replace(/"/g, "&quot;")}">
                    <span class="maturity-pill-val">
                      ${val}/20 ${isMax ? '<span style="color:#10b981; font-size:0.65rem;">✓</span>' : '<span style="color:#f59e0b; font-size:0.65rem;">↑</span>'}
                    </span>
                    <span class="maturity-pill-lbl">${c.label}</span>
                    <div class="maturity-tooltip">
                      <div class="maturity-tooltip-header">
                        <span>${c.label} (${val}/20)</span>
                        <span class="maturity-tooltip-badge ${isMax ? "badge-max" : "badge-improve"}">
                          ${isMax ? "✓ Mature" : "Improve +"}
                        </span>
                      </div>
                      <div class="maturity-tooltip-body">
                        ${tip}
                      </div>
                      ${!isMax
              ? `<div class="maturity-tooltip-action">💡 Click to view recommendations in Feed ➔</div>`
              : ""
            }
                    </div>
                  </div>
                `;
        })
        .join("")}
          </div>
          ${inferredCount > 0
        ? `<div style="margin-top: 8px; font-size: 0.72rem; color: #fbbf24;">📍 ${inferredCount} unassigned device(s)/entities can be auto-assigned to rooms via the Proactive Feed.</div>`
        : ""
      }
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>Media &amp; Matrix Audio Architecture</span>
            <span>${mediaTopo.matrix_amp_detected
        ? `${this._escapeHtml(mediaTopo.matrix_preset_name || "Matrix Amp")} (${matrixZones.length} Zones)`
        : `${mediaTopo.total_media_players || 0} Media Players`
      }</span>
          </div>
          <div style="font-size: 0.75rem; line-height: 1.4;">
            ${mediaTopo.matrix_amp_detected
        ? `
                  <div><strong>Hardware Profile:</strong> ${this._escapeHtml(mediaTopo.matrix_preset_name || "Universal Multi-Zone Matrix")}</div>
                  <div style="margin-top: 3px;"><strong>Output Zones:</strong> ${matrixZones.map((z) => this._escapeHtml(z.name)).join(", ")}</div>
                  ${sharedSources.length > 0
          ? `<div style="margin-top: 3px;"><strong>Shared Inputs:</strong> ${sharedSources.map((s) => this._escapeHtml(s)).join(", ")}</div>`
          : ""
        }
                  ${inputStreamers.length > 0
          ? `<div style="margin-top: 3px;"><strong>Upstream Streamers:</strong> ${inputStreamers.map((s) => this._escapeHtml(s.name)).join(", ")}</div>`
          : ""
        }
                `
        : `<div>No multi-zone matrix audio amplifier detected.</div>`
      }
            ${tvZones.length > 0
        ? `<div style="margin-top: 3px;"><strong>Cinema / TV Displays:</strong> ${tvZones.map((t) => this._escapeHtml(t.name)).join(", ")}</div>`
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
            ${namedAdj.length === 0
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
          <div>${stats.orphans === 0
        ? "Registry is clean! Zero orphaned entities detected."
        : `${stats.orphans} stale or disconnected entities found. Use the Proactive Feed to clean them up.`
      }</div>
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>Autonomous Home Commissioning</span>
            <span style="color: var(--otis-primary); font-weight: 700;">
              ${comm.high_confidence_count ?? 0} Eligible / ${comm.total_unassigned_entities ?? 0} Unassigned
            </span>
          </div>
          <div style="font-size: 0.75rem; line-height: 1.4;">
            ${(comm.total_unassigned_entities ?? 0) === 0
        ? `<div style="color: #4ade80;">✨ All entities and devices are mapped to physical rooms!</div>`
        : `
                  <div>Found <strong>${comm.total_unassigned_entities}</strong> unassigned entities (${comm.high_confidence_count} high-confidence matches).</div>
                  <div style="margin-top: 6px;">
                    <button type="button" class="btn-toolbar" id="btn-auto-commission-tab" style="padding: 4px 10px; font-size: 0.72rem; color: var(--otis-primary); border-color: var(--otis-primary);">
                      ⚡ 1-Click Auto Commission
                    </button>
                  </div>
                `
      }
          </div>
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>🌐 Multi-Node Federation &amp; Cluster Sync</span>
            <span style="color: var(--otis-secondary); font-weight: 700;">
              ${fed.health_score !== undefined ? `${fed.health_score}% Health • ` : ""}${fed.online_nodes ?? 0} / ${fed.total_nodes ?? 0} Online (${fed.avg_latency_ms ?? 0}ms avg)
            </span>
          </div>
          <div style="font-size: 0.75rem; line-height: 1.4;">
            ${(fed.total_nodes ?? 0) === 0
        ? `<div>No remote edge nodes registered yet. Register satellite Home Assistant instances to federate states.</div>`
        : `
                  <div style="display: flex; flex-direction: column; gap: 4px; margin-bottom: 6px;">
                    ${(fed.nodes || [])
          .map(
            (n) => `
                        <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); padding: 4px 8px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center;">
                          <div>
                            <span style="color: ${n.status === "online" ? "#4ade80" : "#f87171"}; font-weight: bold; margin-right: 4px;">●</span>
                            <strong>${this._escapeHtml(n.name)}</strong> <span style="font-size: 0.70rem; color: var(--otis-text-muted);">(${this._escapeHtml(n.host)}:${this._escapeHtml(n.port)})</span>
                            <span class="topo-tag" style="font-size: 0.65rem; margin-left: 4px; background: rgba(56, 189, 248, 0.1); color: var(--otis-primary);">${this._escapeHtml((n.role || "satellite").toUpperCase())}</span>
                          </div>
                          <div style="display: flex; align-items: center; gap: 6px;">
                            <span style="font-size: 0.70rem; color: var(--otis-text-muted);">${Number(n.entities_count) || 0} ents</span>
                            <span style="font-size: 0.70rem; color: var(--otis-text-muted); font-weight: 600;">${n.latency_ms > 0 ? Number(n.latency_ms) + "ms" : this._escapeHtml(n.status)}</span>
                          </div>
                        </div>
                      `
          )
          .join("")}
                  </div>
                  <div style="display: flex; gap: 8px;">
                    <button type="button" class="btn-toolbar" id="btn-sync-federation-tab" style="padding: 4px 10px; font-size: 0.72rem; color: var(--otis-secondary); border-color: var(--otis-secondary);">
                      🔄 Sync All Edge Nodes
                    </button>
                  </div>
                `
      }
          </div>
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>🧠 Local Edge AI (Ollama) &amp; Add-on Control</span>
            <span style="font-weight: 700; color: ${this._capabilityMap?.local_llm?.online ? '#4ade80' : (this._capabilityMap?.local_llm?.suitability?.addon_installed ? '#fbbf24' : 'var(--otis-text-muted)')};">
              ${(() => {
        const llm = this._capabilityMap?.local_llm || {};
        const suit = llm.suitability || {};
        if (llm.online) {
          return `🟢 Online (${llm.latency_ms ?? 0}ms) • ${this._escapeHtml(llm.active_model || "qwen2.5:3b")}`;
        }
        if (suit.addon_installed) {
          return `🟡 Add-on ${this._escapeHtml((suit.addon_state || "stopped").toUpperCase())}`;
        }
        return "⚪ Offline / Add-on Not Installed";
      })()}
            </span>
          </div>
          <div style="font-size: 0.75rem; line-height: 1.45;">
            ${(() => {
        const llm = this._capabilityMap?.local_llm || {};
        const suit = llm.suitability || {};
        const statsObj = llm.addon_stats || {};
        const runningModels = Array.isArray(llm.running_models) ? llm.running_models : [];
        const availModels = Array.isArray(llm.available_models) ? llm.available_models : [];
        const defaultChoices = ["qwen2.5:3b", "qwen2.5:1.5b", "llama3.2-vision:latest"];
        const modelOptions = Array.from(new Set([...availModels, ...defaultChoices, llm.active_model || "qwen2.5:3b"])).filter(Boolean);
        const activeModel = llm.active_model || suit.recommended_model || "qwen2.5:3b";
        const gpuBadge = suit.gpu_detected
          ? `🎮 GPU/iGPU (${(suit.gpu_devices || []).map((d) => this._escapeHtml(d)).join(", ") || "DRI"})`
          : "💻 CPU Inference";
        const suitBadgeColor = suit.can_run && suit.recommended ? "#4ade80" : (suit.can_run ? "#fbbf24" : "#f87171");
        const suitLabel = suit.can_run && suit.recommended
          ? "✅ Host Hardware Verified & Recommended"
          : (suit.can_run ? "⚠️ Host Capable (Lightweight Model Recommended)" : "❌ Host Below Minimum Ollama Specs");

        return `
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 6px; padding: 6px 8px; margin-bottom: 8px;">
                  <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 4px;">
                    <strong style="color: ${suitBadgeColor};">${suitLabel}</strong>
                    <span class="topo-tag" style="font-size: 0.66rem;">${gpuBadge}</span>
                  </div>
                  <div style="color: var(--otis-text-muted); font-size: 0.71rem; margin-top: 3px;">
                    <strong>CPU:</strong> ${this._escapeHtml(suit.cpu_model || "Detected Host CPU")} (${suit.cpu_cores || 0} threads) •
                    <strong>RAM:</strong> ${suit.ram_avail_gb ?? 0} GB free / ${suit.ram_total_gb ?? 0} GB total •
                    <strong>Disk:</strong> ${suit.disk_free_gb ?? 0} GB free
                  </div>
                </div>

                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 6px; margin-bottom: 8px;">
                  <div style="background: rgba(14, 165, 233, 0.06); border: 1px solid rgba(56, 189, 248, 0.16); border-radius: 6px; padding: 5px 8px;">
                    <div style="font-size: 0.68rem; color: var(--otis-text-muted);">Endpoint &amp; Add-on State</div>
                    <div style="font-weight: 600; color: var(--otis-text); word-break: break-all;">
                      ${this._escapeHtml(llm.endpoint_url || "http://127.0.0.1:11434")}
                    </div>
                    <div style="font-size: 0.69rem; color: var(--otis-text-muted); margin-top: 2px;">
                      Add-on: <strong>${suit.addon_installed ? `${this._escapeHtml(suit.addon_slug || "local_otis_ollama")} (${this._escapeHtml(suit.addon_state || "stopped")})` : "Not Installed"}</strong>
                      ${statsObj.memory_mb !== undefined ? ` • CPU ${statsObj.cpu_percent ?? 0}% • RAM ${statsObj.memory_mb} MB` : ""}
                    </div>
                  </div>
                  <div style="background: rgba(168, 85, 247, 0.06); border: 1px solid rgba(168, 85, 247, 0.16); border-radius: 6px; padding: 5px 8px;">
                    <div style="font-size: 0.68rem; color: var(--otis-text-muted);">Active Memory (/api/ps) &amp; Installed Models</div>
                    <div style="font-weight: 600; color: var(--otis-text);">
                      ${runningModels.length > 0
            ? runningModels.map((rm) => `${this._escapeHtml(rm.name)} (${rm.size_mb} MB • ${this._escapeHtml(rm.processor || "CPU")})`).join(", ")
            : "Idle (0 MB in RAM — loads on demand)"}
                    </div>
                    <div style="font-size: 0.69rem; color: var(--otis-text-muted); margin-top: 2px;">
                      Pulled (${availModels.length}): ${availModels.length > 0 ? availModels.map((m) => this._escapeHtml(m)).join(", ") : "None"}
                      ${llm.last_benchmark?.tokens_per_second ? ` • ⚡ ${llm.last_benchmark.tokens_per_second} tok/s` : ""}
                    </div>
                  </div>
                </div>

                <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 8px;">
                  ${!suit.addon_installed && suit.supervisor_available && suit.can_run ? `
                    <button type="button" class="btn-toolbar btn-ollama-addon-action" data-ollama-action="install" style="padding: 4px 10px; font-size: 0.72rem; color: #38bdf8; border-color: #38bdf8; font-weight: 700;">
                      📦 Install &amp; Start Add-on
                    </button>
                  ` : ""}
                  <button type="button" class="btn-toolbar btn-ollama-addon-action" data-ollama-action="start" style="padding: 4px 9px; font-size: 0.71rem; color: #4ade80; border-color: rgba(74, 222, 128, 0.45);">
                    ▶️ Start
                  </button>
                  <button type="button" class="btn-toolbar btn-ollama-addon-action" data-ollama-action="stop" style="padding: 4px 9px; font-size: 0.71rem; color: #f87171; border-color: rgba(248, 113, 113, 0.45);">
                    ⏹️ Stop
                  </button>
                  <button type="button" class="btn-toolbar btn-ollama-addon-action" data-ollama-action="restart" style="padding: 4px 9px; font-size: 0.71rem; color: #fbbf24; border-color: rgba(251, 191, 36, 0.45);">
                    🔄 Restart
                  </button>
                  <button type="button" class="btn-toolbar btn-ollama-addon-action" data-ollama-action="status" style="padding: 4px 9px; font-size: 0.71rem;">
                    🩺 Refresh Status
                  </button>
                  <button type="button" class="btn-toolbar" id="btn-ollama-benchmark" style="padding: 4px 9px; font-size: 0.71rem; color: var(--otis-primary); border-color: var(--otis-primary);">
                    ⚡ Benchmark
                  </button>
                </div>

                <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center;">
                  <select id="ollama-model-select" style="background: rgba(15, 23, 42, 0.75); color: var(--otis-text); border: 1px solid rgba(148, 163, 184, 0.3); border-radius: 6px; padding: 4px 8px; font-size: 0.72rem; flex: 1; min-width: 150px;">
                    ${modelOptions.map((m) => `
                      <option value="${this._escapeHtml(m)}" ${m === activeModel ? "selected" : ""}>
                        ${this._escapeHtml(m)}${availModels.includes(m) ? " (Installed)" : " (Available to Pull)"}
                      </option>
                    `).join("")}
                  </select>
                  <button type="button" class="btn-toolbar" id="btn-ollama-set-model" style="padding: 4px 9px; font-size: 0.71rem;">
                    ✓ Set Active
                  </button>
                  <button type="button" class="btn-toolbar" id="btn-ollama-pull-model" style="padding: 4px 9px; font-size: 0.71rem; color: #38bdf8; border-color: rgba(56, 189, 248, 0.45);">
                    ⬇️ Pull Model
                  </button>
                  <button type="button" class="btn-toolbar" id="btn-ollama-delete-model" style="padding: 4px 9px; font-size: 0.71rem; color: #f87171; border-color: rgba(248, 113, 113, 0.35);">
                    🗑️ Delete
                  </button>
                </div>
              `;
      })()}
          </div>
        </div>

        <div class="cap-block">
          <div class="cap-title">
            <span>⚡ Context-Aware Energy Arbitrage &amp; Battery Scheduling</span>
            <span style="color: var(--otis-primary); font-weight: 700;">
              ${this._capabilityMap?.energy_topology?.arbitrage_plan?.current_soc_pct !== undefined ? `${this._capabilityMap.energy_topology.arbitrage_plan.current_soc_pct}% SoC` : "Ready"} • Mode: ${(this._capabilityMap?.energy_topology?.arbitrage_plan?.mode || "auto").toUpperCase()}
            </span>
          </div>
          <div class="energy-arbitrage-container" style="font-size: 0.75rem; line-height: 1.4;">
            ${(() => {
        const energyTopo = this._capabilityMap?.energy_topology || {};
        const arbitrage = energyTopo.arbitrage_plan || {};
        const solarInfo = energyTopo.solar || {};
        return `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px;">
                  <div>
                    <strong>Current Action:</strong>
                    <span class="topo-tag" style="background: rgba(14, 165, 233, 0.15); color: var(--otis-primary); font-weight: bold; margin-left: 4px;">
                      ${arbitrage.current_action ? arbitrage.current_action.replace(/_/g, " ").toUpperCase() : "OPTIMIZED"}
                    </span>
                    <span style="color: var(--otis-text-muted); font-size: 0.70rem; margin-left: 6px;">
                      (${arbitrage.current_battery_flow_kw > 0 ? `📥 Charging +${arbitrage.current_battery_flow_kw}kW` : (arbitrage.current_battery_flow_kw < 0 ? `📤 Discharging ${Math.abs(arbitrage.current_battery_flow_kw)}kW` : "⏸️ Idle / Holding")})
                    </span>
                  </div>
                  <div style="font-size: 0.72rem; color: #10b981; font-weight: 600;">
                    💰 Est. Savings: $${(arbitrage.projected_savings_usd || 0).toFixed(2)}/day
                  </div>
                </div>

                <!-- Mode Switcher Pills -->
                <div style="display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap;">
                  <button type="button" class="btn-toolbar btn-arbitrage-mode ${arbitrage.mode === 'auto' ? 'active' : ''}" data-mode="auto" style="padding: 3px 8px; font-size: 0.70rem;">⚡ Auto</button>
                  <button type="button" class="btn-toolbar btn-arbitrage-mode ${arbitrage.mode === 'peak_arbitrage' ? 'active' : ''}" data-mode="peak_arbitrage" style="padding: 3px 8px; font-size: 0.70rem;">🔥 Peak Shave</button>
                  <button type="button" class="btn-toolbar btn-arbitrage-mode ${arbitrage.mode === 'self_consumption' ? 'active' : ''}" data-mode="self_consumption" style="padding: 3px 8px; font-size: 0.70rem;">☀️ Solar Soak</button>
                  <button type="button" class="btn-toolbar btn-arbitrage-mode ${arbitrage.mode === 'backup_reserve' ? 'active' : ''}" data-mode="backup_reserve" style="padding: 3px 8px; font-size: 0.70rem;">🛡️ Backup (100%)</button>
                </div>

                <!-- 24-Hour Hourly Timeline Strip -->
                ${arbitrage.schedule && arbitrage.schedule.length > 0 ? `
                  <div style="margin-bottom: 6px;">
                    <div style="font-size: 0.68rem; color: var(--otis-text-muted); margin-bottom: 3px; display: flex; justify-content: space-between;">
                      <span>24-Hour Horizon Schedule &amp; Tariff Periods</span>
                      <span>Peak Shaved: ${(arbitrage.projected_peak_shave_kwh || 0).toFixed(1)} kWh</span>
                    </div>
                    <div style="display: flex; gap: 2px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: thin;">
                      ${arbitrage.schedule.map((step) => {
          const isPeak = step.tariff_period === 'peak';
          const isShoulder = step.tariff_period === 'shoulder';
          const bg = isPeak ? 'rgba(239, 68, 68, 0.25)' : (isShoulder ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.15)');
          const border = isPeak ? '#ef4444' : (isShoulder ? '#f59e0b' : '#10b981');
          const flowSymbol = step.battery_flow_kw > 0 ? '📥' : (step.battery_flow_kw < 0 ? '📤' : '•');
          return `
                          <div style="flex: 1; min-width: 32px; background: ${bg}; border: 1px solid ${border}; border-radius: 4px; padding: 3px 2px; text-align: center; font-size: 0.62rem;" title="${step.time_label} [${step.tariff_period.toUpperCase()} @ $${step.rate_per_kwh.toFixed(2)}/kWh]: ${step.action} (${step.battery_flow_kw}kW) - Ending SoC: ${step.ending_soc_pct}%">
                            <div style="font-weight: 600; color: var(--otis-text);">${step.hour}:00</div>
                            <div style="font-size: 0.60rem; margin: 1px 0;">${flowSymbol}</div>
                            <div style="color: var(--otis-text-muted); font-size: 0.58rem;">${Math.round(step.ending_soc_pct)}%</div>
                          </div>
                        `;
        }).join('')}
                    </div>
                  </div>
                ` : ""}

                <!-- Smart EV Charging Section (Phase 7 - shown only when EV is integrated) -->
                ${arbitrage.ev_charging_plan && Boolean(arbitrage.has_ev) ? `
                  <div style="margin-top: 8px; margin-bottom: 8px; padding: 6px 8px; background: rgba(14, 165, 233, 0.08); border-radius: 6px; border: 1px solid rgba(14, 165, 233, 0.2);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                      <span style="font-weight: 600; font-size: 0.70rem; color: var(--otis-primary);">
                        🚗 Smart EV Charging (${arbitrage.ev_charging_plan.current_soc_pct}% ➔ ${arbitrage.ev_charging_plan.target_soc_pct}% target by ${arbitrage.ev_charging_plan.target_departure_hour}:00)
                      </span>
                      <span style="font-size: 0.68rem; color: #10b981; font-weight: 600;">
                        Est. EV Cost: $${(arbitrage.ev_charging_plan.projected_cost_usd || 0).toFixed(2)}
                      </span>
                    </div>
                    <div style="font-size: 0.68rem; color: var(--otis-text-muted); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px;">
                      <span>⚡ Status: <strong>${arbitrage.ev_charging_plan.current_action ? arbitrage.ev_charging_plan.current_action.replace(/_/g, " ").toUpperCase() : "IDLE"}</strong> (${arbitrage.ev_charging_plan.current_ev_charge_kw || 0} kW)</span>
                      <span>☀️ Solar Used: <strong>${(arbitrage.ev_charging_plan.solar_kwh_utilized || 0).toFixed(1)} kWh</strong> • Grid Off-Peak: <strong>${(arbitrage.ev_charging_plan.grid_kwh_utilized || 0).toFixed(1)} kWh</strong></span>
                    </div>
                  </div>
                ` : ""}

                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px; flex-wrap: wrap; gap: 6px;">
                  <div style="font-size: 0.70rem; color: var(--otis-text-muted);">
                    Solar Forecast: <strong>${(arbitrage.daily_solar_forecast_kwh || (solarInfo.production_w ? (solarInfo.production_w * 6 / 1000) : 24.0)).toFixed(1)} kWh</strong> • Baseline Load: <strong>${arbitrage.baseline_load_kw || 1.0} kW</strong>
                  </div>
                  <div>
                    <button type="button" class="btn-toolbar" id="btn-optimize-arbitrage-tab" style="padding: 4px 10px; font-size: 0.72rem; color: var(--otis-primary); border-color: var(--otis-primary);">
                      ⚡ Re-Optimize
                    </button>
                    <button type="button" class="btn-toolbar" id="btn-dispatch-arbitrage-tab" style="padding: 4px 10px; font-size: 0.72rem; color: #10b981; border-color: #10b981; margin-left: 4px;">
                      ⚡ Apply Dispatch
                    </button>
                  </div>
                </div>
              `;
      })()}
          </div>
        </div>
      </div>
    `;
  },


  _renderMediaStudioTab() {
    const mediaTopo = this._capabilityMap?.media_topology || {};
    const studioData = this._mediaStudioData || {};
    const rawZones =
      (studioData.zones && studioData.zones.length > 0 ? studioData.zones : mediaTopo.matrix_zones) || [];
    const candidatePlayers = this._getResolvedCandidatePlayers(studioData, mediaTopo);
    const effectiveMappings = {
      ...(mediaTopo.input_mappings || {}),
      ...(studioData.effective_mappings || {}),
      ...(this._userRules?.media_input_mappings || {}),
    };
    const unjoinInput =
      studioData.unjoin_input || this._userRules?.media_unjoin_input || "None";
    const userName = studioData.user_name || this._hass?.user?.name || "Resident";
    const isAdmin = Boolean(this._hass?.user?.is_admin || this._hass?.user?.is_owner);

    // Enrich zones with live Home Assistant states and optimistic overrides
    const zones = rawZones.map((z) => {
      const eid = z.entity_id;
      const st = this._hass?.states?.[eid];
      const liveSource =
        this._mediaOptimisticSources[eid] !== undefined
          ? this._mediaOptimisticSources[eid]
          : st?.attributes?.source ?? z.source ?? "";
      const liveVol =
        this._mediaOptimisticVolumes[eid] !== undefined
          ? this._mediaOptimisticVolumes[eid]
          : st?.attributes?.volume_level !== undefined
            ? Number(st.attributes.volume_level)
            : z.volume_level !== undefined && z.volume_level !== null
              ? Number(z.volume_level)
              : 0.25;
      const liveMuted =
        this._mediaOptimisticMutes[eid] !== undefined
          ? this._mediaOptimisticMutes[eid]
          : Boolean(st?.attributes?.is_volume_muted ?? z.is_volume_muted);
      const liveState = st?.state || z.state || "off";
      const sourceList = st?.attributes?.source_list || z.source_list || studioData.shared_sources || mediaTopo.shared_sources || [];
      return {
        ...z,
        entity_id: eid,
        name: (st?.attributes?.friendly_name || z.name || eid).replace(/^Matrix Amp \d+\s+/i, ""),
        full_name: st?.attributes?.friendly_name || z.name || eid,
        state: liveState,
        source: liveSource,
        source_list: sourceList,
        volume_level: liveVol,
        is_volume_muted: liveMuted,
      };
    });

    if (zones.length === 0) {
      return `
        <div style="padding: 28px; text-align: center; background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 14px; color: var(--otis-text-muted);">
          <div style="font-size: 2rem; margin-bottom: 8px;">🎵</div>
          <div style="font-weight: 700; color: var(--otis-text); font-size: 0.95rem;">No Multi-Zone Audio Amplifiers Discovered</div>
          <div style="font-size: 0.8rem; margin-top: 4px;">Connect a matrix amplifier or multi-room speaker system (Control4, Sonos, Heos, Music Assistant) to enable Source-to-Zone routing.</div>
        </div>
      `;
    }

    let selectedZone =
      zones.find((z) => z.entity_id === this._selectedMediaZoneId) ||
      zones.find((z) => z.entity_id === studioData.default_zone) ||
      zones[0];
    if (selectedZone && this._selectedMediaZoneId !== selectedZone.entity_id) {
      this._selectedMediaZoneId = selectedZone.entity_id;
    }

    const allInputs = Array.from(
      new Set([
        ...(selectedZone?.source_list || []),
        ...(studioData.shared_sources || []),
        ...(mediaTopo.shared_sources || []),
      ])
    ).filter(Boolean);

    const activeInput =
      this._selectedMediaInput ||
      (selectedZone?.source && selectedZone.source.toLowerCase() !== "none" ? selectedZone.source : "") ||
      allInputs.find((inp) => inp.toLowerCase() !== "none" && effectiveMappings[inp]) ||
      allInputs.find((inp) => inp.toLowerCase() !== "none") ||
      allInputs[0] ||
      "";

    const mappedPlayerId = activeInput ? effectiveMappings[activeInput] || "" : "";
    const mappedSt = mappedPlayerId ? this._hass?.states?.[mappedPlayerId] : null;
    const fallbackMappedInfo = (studioData.mapped_players_state || {})[activeInput] || {};
    const serviceProfile =
      fallbackMappedInfo.service_profile ||
      candidatePlayers.find((c) => c.entity_id === mappedPlayerId)?.service_profile ||
      {};
    const serviceProvider = serviceProfile.display_name || serviceProfile.provider || "Media Player";
    const supportsBrowse = Boolean(serviceProfile.supports_browse || serviceProfile.provider === "music_assistant");
    const hasMassInHome =
      supportsBrowse ||
      candidatePlayers.some(
        (c) =>
          c.service_profile?.provider === "music_assistant" ||
          (c.entity_id && (c.entity_id.includes("mass") || c.entity_id.includes("music_assistant")))
      ) ||
      Boolean(
        this._hass &&
        Object.keys(this._hass.states || {}).some(
          (k) => k.startsWith("media_player.") && (k.includes("mass") || k.includes("music_assistant"))
        )
      );
    const canBrowse = supportsBrowse || hasMassInHome;
    const supportsVoice = Boolean(serviceProfile.supports_voice || serviceProfile.provider === "alexa_media");
    const supportedTypes = serviceProfile.supported_media_types || ["custom", "music", "playlist", "radio"];
    const playerState = mappedSt?.state || fallbackMappedInfo.state || selectedZone?.state || "idle";
    const playerName =
      mappedSt?.attributes?.friendly_name ||
      fallbackMappedInfo.friendly_name ||
      fallbackMappedInfo.name ||
      (mappedPlayerId ? mappedPlayerId : "Unmapped Matrix Input");
    const mediaTitle =
      mappedSt?.attributes?.media_title ||
      fallbackMappedInfo.media_title ||
      (this._hass?.states?.[selectedZone.entity_id]?.attributes?.media_title) ||
      (playerState === "playing" ? `Streaming on ${activeInput}` : `Ready on ${activeInput || "Matrix"}`);
    const mediaArtist =
      mappedSt?.attributes?.media_artist ||
      mappedSt?.attributes?.media_album_name ||
      fallbackMappedInfo.media_artist ||
      (mappedPlayerId ? `${playerName} (${playerState})` : "Select an input or favorite to start playback");
    const entityPic =
      mappedSt?.attributes?.entity_picture ||
      fallbackMappedInfo.entity_picture ||
      this._hass?.states?.[selectedZone.entity_id]?.attributes?.entity_picture ||
      "";

    // Linked zones currently routed to the same activeInput
    const isZoneLinked = (z) =>
      Boolean(
        activeInput &&
        activeInput.toLowerCase() !== "none" &&
        z.state !== "off" &&
        z.state !== "unavailable" &&
        String(z.source || "").toLowerCase() === activeInput.toLowerCase()
      );

    const mixerZones = [
      selectedZone,
      ...zones.filter((z) => z.entity_id !== selectedZone.entity_id && isZoneLinked(z)),
    ];

    const favorites = studioData.favorites || [];
    const isDefaultZone = studioData.default_zone === selectedZone.entity_id;
    const isZoneOn =
      selectedZone.state !== "off" &&
      selectedZone.state !== "unavailable" &&
      String(selectedZone.source || "").toLowerCase() !== "none";

    return `
      <div class="media-studio-wrapper" style="display: flex; flex-direction: column; gap: 16px;">
        ${this._mediaBrowseOpen
        ? `
          <!-- Agnostic Media Provider Library Browser Panel -->
          <div class="media-library-browser-panel" style="background: var(--otis-surface); border: 1px solid var(--otis-primary); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; box-shadow: 0 8px 32px rgba(0,0,0,0.35);">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;">
              <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                <span style="font-size: 0.84rem; font-weight: 700; color: var(--otis-primary);">
                  🎵 ${this._escapeHtml(serviceProvider)} Library
                </span>
                <div style="display: flex; gap: 4px;">
                  ${["playlist", "radio", "artist", "album"]
          .map(
            (t) => `
                    <button type="button" class="btn-toolbar btn-browse-type ${this._mediaBrowseType === t ? "active" : ""}" data-type="${t}" data-player-id="${this._escapeHtml(mappedPlayerId)}" style="padding: 2px 8px; font-size: 0.68rem; text-transform: capitalize; ${this._mediaBrowseType === t ? "background: var(--otis-primary); color: #fff; border-color: var(--otis-primary);" : ""}">
                      ${t === "playlist" ? "🎵 Playlists" : t === "radio" ? "📻 Radio" : t === "artist" ? "🎤 Artists" : "💿 Albums"}
                    </button>
                  `
          )
          .join("")}
                </div>
              </div>
              <button type="button" class="btn-toolbar" id="btn-media-browse-close" style="padding: 2px 8px; font-size: 0.72rem;">✕ Close</button>
            </div>

            ${this._mediaBrowseLoading
          ? `
              <div style="padding: 20px; text-align: center; color: var(--otis-text-muted); font-size: 0.8rem;">
                <span style="display: inline-block; animation: otis-spin 0.8s linear infinite; margin-right: 8px;">🔄</span>
                Loading ${this._escapeHtml(this._mediaBrowseType)}s from ${this._escapeHtml(serviceProvider)}...
              </div>
            `
          : this._mediaBrowseError
            ? `
              <div style="padding: 12px; border-radius: 8px; background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); color: #fca5a5; font-size: 0.76rem;">
                ⚠️ ${this._escapeHtml(this._mediaBrowseError)}
              </div>
            `
            : this._mediaBrowseItems.length === 0
              ? `
              <div style="padding: 16px; text-align: center; color: var(--otis-text-muted); font-size: 0.76rem;">
                No items found in ${this._escapeHtml(serviceProvider)} for category "${this._escapeHtml(this._mediaBrowseType)}".
              </div>
            `
              : `
              <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 8px; max-height: 280px; overflow-y: auto; padding-right: 4px;">
                ${this._mediaBrowseItems
                .map(
                  (item) => `
                  <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 10px; border-radius: 8px; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06);">
                    <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
                      <span style="font-size: 0.76rem; font-weight: 600; color: var(--otis-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${this._escapeHtml(item.name)}">
                        ${this._escapeHtml(item.name)}
                      </span>
                      ${item.artist
                      ? `
                        <span style="font-size: 0.66rem; color: var(--otis-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                          ${this._escapeHtml(item.artist)}
                        </span>
                      `
                      : ""
                    }
                    </div>
                    <div style="display: flex; align-items: center; gap: 4px; flex-shrink: 0;">
                      <button type="button" class="btn-toolbar btn-play-library-item" data-id="${this._escapeHtml(item.id)}" data-name="${this._escapeHtml(item.name)}" data-type="${this._escapeHtml(item.media_type || this._mediaBrowseType)}" data-player-id="${this._escapeHtml(mappedPlayerId)}" data-zone-id="${this._escapeHtml(selectedZone.entity_id)}" data-input="${this._escapeHtml(activeInput)}" title="Play now in ${this._escapeHtml(selectedZone.name)}" style="padding: 3px 8px; font-size: 0.68rem; background: var(--otis-primary); color: #fff; border-color: var(--otis-primary);">
                        ▶️ Play
                      </button>
                      <button type="button" class="btn-toolbar btn-fav-library-item" data-id="${this._escapeHtml(item.id)}" data-name="${this._escapeHtml(item.name)}" data-type="${this._escapeHtml(item.media_type || this._mediaBrowseType)}" data-input="${this._escapeHtml(activeInput)}" title="Save as favorite" style="padding: 3px 6px; font-size: 0.68rem;">
                        ⭐
                      </button>
                    </div>
                  </div>
                `
                )
                .join("")}
              </div>
            `
        }
          </div>
        `
        : ""
      }

        <!-- Main 2-Column Media Studio Grid -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 16px; align-items: start;">
          <!-- Left Column: Now Playing + Active Zone Volume Mixer -->
          <div style="display: flex; flex-direction: column; gap: 14px;">
            <!-- Now Playing & Streamer Transport Card -->
            <div style="background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 14px; position: relative; overflow: hidden;">
              <div style="display: flex; align-items: center; gap: 14px;">
                <div style="width: 78px; height: 78px; border-radius: 12px; background: linear-gradient(135deg, rgba(14,165,233,0.22), rgba(168,85,247,0.22)); border: 1px solid rgba(56,189,248,0.35); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; box-shadow: 0 4px 14px rgba(0,0,0,0.3);">
                  ${entityPic
        ? `<img src="${this._escapeHtml(entityPic)}" alt="Album Art" style="width: 100%; height: 100%; object-fit: cover;" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex';" />`
        : ""
      }
                  <span style="display: ${entityPic ? "none" : "flex"}; font-size: 2rem;">🎵</span>
                </div>
                <div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px;">
                  <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                    <span style="font-size: 0.68rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: rgba(56, 189, 248, 0.16); border: 1px solid rgba(56, 189, 248, 0.35); color: var(--otis-primary);">
                      🔌 ${this._escapeHtml(activeInput || "No Input")} ➔ 🎵 ${this._escapeHtml(playerName)}
                    </span>
                    <span style="font-size: 0.65rem; font-weight: 700; padding: 2px 7px; border-radius: 6px; background: rgba(168, 85, 247, 0.18); border: 1px solid rgba(168, 85, 247, 0.4); color: #c084fc;">
                      ${this._escapeHtml(serviceProvider)}
                    </span>
                    <span style="font-size: 0.66rem; font-weight: 700; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; background: ${playerState === "playing" ? "rgba(16,185,129,0.2)" : "rgba(255,255,255,0.07)"}; color: ${playerState === "playing" ? "#34d399" : "var(--otis-text-muted)"};">
                      ${this._escapeHtml(playerState)}
                    </span>
                  </div>
                  <div style="font-size: 1rem; font-weight: 700; color: var(--otis-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${this._escapeHtml(mediaTitle)}">
                    ${this._escapeHtml(mediaTitle)}
                  </div>
                  <div style="font-size: 0.78rem; color: var(--otis-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${this._escapeHtml(mediaArtist)}">
                    ${this._escapeHtml(mediaArtist)}
                  </div>
                </div>
              </div>

              <!-- Transport Controls Row -->
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.07);">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <button type="button" class="btn-toolbar btn-media-transport" data-transport="media_previous_track" data-player-id="${this._escapeHtml(mappedPlayerId || selectedZone.entity_id)}" title="Previous Track" style="padding: 6px 12px; font-size: 0.85rem;">
                    ⏮️
                  </button>
                  <button type="button" class="btn-toolbar btn-media-transport" data-transport="media_play_pause" data-player-id="${this._escapeHtml(mappedPlayerId || selectedZone.entity_id)}" title="Play / Pause" style="padding: 6px 16px; font-size: 0.9rem; background: var(--otis-primary); color: #fff; border-color: var(--otis-primary);">
                    ${playerState === "playing" ? "⏸️ Pause" : "▶️ Play"}
                  </button>
                  <button type="button" class="btn-toolbar btn-media-transport" data-transport="media_next_track" data-player-id="${this._escapeHtml(mappedPlayerId || selectedZone.entity_id)}" title="Next Track" style="padding: 6px 12px; font-size: 0.85rem;">
                    ⏭️
                  </button>
                </div>
                <div style="display: flex; align-items: center; gap: 6px;">
                  <button type="button" class="btn-toolbar" id="btn-media-save-current-track" data-title="${this._escapeHtml(mediaTitle)}" data-artist="${this._escapeHtml(mediaArtist)}" data-input="${this._escapeHtml(activeInput)}" title="Save currently playing track or station to your personal favorites" style="padding: 5px 10px; font-size: 0.72rem;">
                    ⭐ Save Track
                  </button>
                  <button type="button" class="btn-toolbar" id="btn-media-browse-player" data-player-id="${this._escapeHtml(mappedPlayerId || selectedZone.entity_id)}" title="Open Media Browser & Player Controls" style="padding: 5px 10px; font-size: 0.72rem;">
                    📂 Controls
                  </button>
                </div>
              </div>

              <!-- Provider Capability Shortcuts Row -->
              ${supportsBrowse
        ? `
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.07);">
                  <span style="font-size: 0.71rem; color: var(--otis-text-muted); font-weight: 600;">
                    ${this._escapeHtml(serviceProvider)}:
                  </span>
                  <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap;">
                    <button type="button" class="btn-toolbar btn-browse-action" data-type="playlist" data-player-id="${this._escapeHtml(mappedPlayerId)}" style="padding: 3px 8px; font-size: 0.68rem;">
                      🎵 Playlists
                    </button>
                    <button type="button" class="btn-toolbar btn-browse-action" data-type="radio" data-player-id="${this._escapeHtml(mappedPlayerId)}" style="padding: 3px 8px; font-size: 0.68rem;">
                      📻 Radio
                    </button>
                    <button type="button" class="btn-toolbar btn-browse-action" data-type="artist" data-player-id="${this._escapeHtml(mappedPlayerId)}" style="padding: 3px 8px; font-size: 0.68rem;">
                      🎤 Artists
                    </button>
                    <button type="button" class="btn-toolbar btn-browse-action" data-type="album" data-player-id="${this._escapeHtml(mappedPlayerId)}" style="padding: 3px 8px; font-size: 0.68rem;">
                      💿 Albums
                    </button>
                  </div>
                </div>
              `
        : supportsVoice
          ? `
                <div style="padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.07); font-size: 0.71rem; color: var(--otis-text-muted);">
                  🗣️ <em>Accepts voice phrases via ${this._escapeHtml(serviceProvider)} (e.g. "play smooth jazz on Spotify", "play BBC news")</em>
                </div>
              `
          : ""
      }
            </div>

            <!-- Active Zone & Linked Rooms Volume Mixer -->
            <div style="background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px;">
              <div style="display: flex; align-items: center; justify-content: space-between;">
                <span style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">🎚️ Active Zone &amp; Multi-Room Volume Mixer</span>
                <span style="font-size: 0.7rem; color: var(--otis-text-muted);">${mixerZones.length} ${mixerZones.length === 1 ? "room" : "rooms"} active</span>
              </div>
              <div style="display: flex; flex-direction: column; gap: 10px;">
                ${mixerZones
        .map((mz) => {
          const volPct = Math.round(Math.max(0, Math.min(1, Number(mz.volume_level || 0))) * 100);
          const isPrimary = mz.entity_id === selectedZone.entity_id;
          return `
                      <div style="display: flex; flex-direction: column; gap: 5px; padding: 8px 10px; border-radius: 10px; background: rgba(0,0,0,0.2); border: 1px solid ${isPrimary ? "rgba(56,189,248,0.35)" : "rgba(255,255,255,0.06)"};">
                        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                          <div style="display: flex; align-items: center; gap: 6px;">
                            <span>${this._getRoomEmoji(mz.name)}</span>
                            <span style="font-size: 0.8rem; font-weight: 700; color: var(--otis-text);">${this._escapeHtml(mz.name)}</span>
                            <span style="font-size: 0.64rem; padding: 1px 6px; border-radius: 4px; background: ${isPrimary ? "rgba(56,189,248,0.18)" : "rgba(16,185,129,0.18)"}; color: ${isPrimary ? "var(--otis-primary)" : "#34d399"}; font-weight: 700;">
                              ${isPrimary ? "PRIMARY" : "LINKED"}
                            </span>
                          </div>
                          <div style="display: flex; align-items: center; gap: 8px;">
                            <button type="button" class="btn-toolbar btn-media-mute-toggle" data-zone-id="${this._escapeHtml(mz.entity_id)}" data-muted="${mz.is_volume_muted ? "true" : "false"}" title="${mz.is_volume_muted ? "Unmute" : "Mute"}" style="padding: 2px 7px; font-size: 0.76rem; ${mz.is_volume_muted ? "background: rgba(239,68,68,0.22); border-color: rgba(239,68,68,0.5); color: #f87171;" : ""}">
                              ${mz.is_volume_muted ? "🔇 Muted" : "🔊"}
                            </button>
                            <span class="media-vol-label" data-zone-vol-label="${this._escapeHtml(mz.entity_id)}" style="font-size: 0.76rem; font-weight: 700; color: var(--otis-primary); min-width: 34px; text-align: right;">
                              ${volPct}%
                            </span>
                          </div>
                        </div>
                        <input type="range" class="media-zone-vol-slider" data-zone-id="${this._escapeHtml(mz.entity_id)}" min="0" max="100" value="${volPct}" style="width: 100%; cursor: pointer; accent-color: var(--otis-primary);" />
                      </div>
                    `;
        })
        .join("")}
              </div>
            </div>
          </div>

          <!-- Right Column: Zone & Input Routing + Multi-Room Link Grid + Per-User Favorites -->
          <div style="display: flex; flex-direction: column; gap: 14px;">
            <!-- Speaker Zone & Input Source Routing Card -->
            <div style="background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px;">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;">
                <span style="font-size: 0.82rem; font-weight: 700; color: var(--otis-primary);">🔊 Speaker Zone &amp; Matrix Source Routing</span>
                <div style="display: flex; align-items: center; gap: 6px;">
                  <button type="button" class="btn-toolbar" id="btn-toggle-media-mappings" title="Configure matrix input-to-player mappings" style="padding: 3px 8px; font-size: 0.7rem; ${this._showMediaMappingsEditor ? "background: rgba(14,165,233,0.22); border-color: rgba(56,189,248,0.5); color: var(--otis-primary);" : ""}">
                    ${this._showMediaMappingsEditor ? "✕ Close Mappings" : "⚙️ Input Mappings"}
                  </button>
                  <button type="button" class="btn-toolbar" id="btn-media-set-default-zone" data-zone-id="${this._escapeHtml(selectedZone.entity_id)}" title="Save this room as your personal default zone" style="padding: 3px 8px; font-size: 0.7rem; ${isDefaultZone ? "background: rgba(16,185,129,0.2); border-color: rgba(16,185,129,0.45); color: #34d399;" : ""}">
                    ${isDefaultZone ? "✓ My Default Zone" : "📌 Set as My Default"}
                  </button>
                  <button type="button" class="btn-toolbar" id="btn-media-zone-power" data-zone-id="${this._escapeHtml(selectedZone.entity_id)}" data-is-on="${isZoneOn ? "true" : "false"}" style="padding: 3px 9px; font-size: 0.72rem; ${isZoneOn ? "background: rgba(16,185,129,0.22); border-color: rgba(16,185,129,0.5); color: #34d399;" : "background: rgba(239,68,68,0.15); border-color: rgba(239,68,68,0.35); color: #f87171;"}">
                    ⏻ ${isZoneOn ? "Zone ON" : "Zone OFF"}
                  </button>
                </div>
              </div>

              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <div style="display: flex; flex-direction: column; gap: 4px;">
                  <label style="font-size: 0.72rem; color: var(--otis-text-muted); font-weight: 600;">Target Speaker Zone:</label>
                  <select id="media-studio-zone-select" style="width: 100%; padding: 8px 10px; border-radius: 8px; background: rgba(0,0,0,0.3); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.8rem; font-weight: 600;">
                    ${zones
        .map((z) => {
          const zOn = z.state !== "off" && z.state !== "unavailable" && String(z.source || "").toLowerCase() !== unjoinInput.toLowerCase();
          return `
                          <option value="${this._escapeHtml(z.entity_id)}" ${z.entity_id === selectedZone.entity_id ? "selected" : ""}>
                            ${this._getRoomEmoji(z.name)} ${this._escapeHtml(z.name)} ${zOn && z.source ? `(${this._escapeHtml(z.source)})` : "(Off)"}
                          </option>
                        `;
        })
        .join("")}
                  </select>
                </div>

                <div style="display: flex; flex-direction: column; gap: 4px;">
                  <label style="font-size: 0.72rem; color: var(--otis-text-muted); font-weight: 600;">Matrix Input Source:</label>
                  <select id="media-studio-input-select" data-zone-id="${this._escapeHtml(selectedZone.entity_id)}" style="width: 100%; padding: 8px 10px; border-radius: 8px; background: rgba(0,0,0,0.3); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.8rem; font-weight: 600;">
                    ${allInputs
        .map((inp) => {
          const mpId = effectiveMappings[inp];
          const mpName = mpId
            ? this._hass?.states?.[mpId]?.attributes?.friendly_name ||
            candidatePlayers.find((c) => c.entity_id === mpId)?.name ||
            mpId
            : "";
          return `
                          <option value="${this._escapeHtml(inp)}" ${inp === activeInput ? "selected" : ""}>
                            🔌 ${this._escapeHtml(inp)}${mpName ? ` ➔ ${this._escapeHtml(mpName)}` : ""}
                          </option>
                        `;
        })
        .join("")}
                  </select>
                </div>
              </div>

              <!-- Default / Return Input (used when unjoined or input playback stops) -->
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06);">
                <div style="display: flex; flex-direction: column; gap: 1px;">
                  <span style="font-size: 0.74rem; font-weight: 600; color: var(--otis-text-muted);">
                    ↩️ Default / Return Input
                  </span>
                  <span style="font-size: 0.66rem; color: var(--otis-text-muted); opacity: 0.85;">
                    Zones automatically return here when unjoined or when input playback stops.
                  </span>
                </div>
                ${isAdmin
        ? `
                  <select id="media-studio-default-return-input" style="min-width: 150px; padding: 6px 10px; border-radius: 8px; background: rgba(0,0,0,0.3); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.78rem; font-weight: 600;">
                    <option value="None" ${unjoinInput.toLowerCase() === "none" ? "selected" : ""}>None (Off / Mute)</option>
                    ${allInputs
          .filter((inp) => inp.toLowerCase() !== "none")
          .map(
            (inp) => `
                      <option value="${this._escapeHtml(inp)}" ${inp.toLowerCase() === unjoinInput.toLowerCase() ? "selected" : ""}>
                        🔌 ${this._escapeHtml(inp)}
                      </option>
                    `
          )
          .join("")}
                  </select>
                `
        : `
                  <span style="font-size: 0.74rem; font-weight: 600; padding: 4px 10px; border-radius: 8px; background: rgba(0,0,0,0.24); border: 1px solid var(--otis-surface-border); color: var(--otis-text);">
                    🔌 ${this._escapeHtml(unjoinInput)}
                  </span>
                `
      }
              </div>

              <!-- Multi-Room Linked Zones Grid -->
              <div style="display: flex; flex-direction: column; gap: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06);">
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px;">
                  <span style="font-size: 0.75rem; font-weight: 700; color: var(--otis-text-muted);">
                    🔗 Link Additional Rooms to "${this._escapeHtml(activeInput || "Input")}":
                  </span>
                  <div style="display: flex; gap: 6px;">
                    <button type="button" class="btn-toolbar" id="btn-media-link-all" data-input="${this._escapeHtml(activeInput)}" style="padding: 2px 8px; font-size: 0.68rem;">
                      + Link All
                    </button>
                    <button type="button" class="btn-toolbar" id="btn-media-unlink-others" style="padding: 2px 8px; font-size: 0.68rem;">
                      ✕ Unlink Others
                    </button>
                  </div>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                  ${zones
        .filter((z) => z.entity_id !== selectedZone.entity_id)
        .map((z) => {
          const linked = isZoneLinked(z);
          return `
                        <button type="button" class="subview-chip btn-media-link-zone ${linked ? "active" : ""}" data-zone-id="${this._escapeHtml(z.entity_id)}" data-linked="${linked ? "true" : "false"}" data-input="${this._escapeHtml(activeInput)}" style="padding: 5px 10px; font-size: 0.74rem; border-radius: 8px; ${linked ? "background: rgba(16, 185, 129, 0.22); border-color: #10b981; color: #34d399; font-weight: 700;" : ""}">
                          ${linked ? "✓ " : "+ "}${this._getRoomEmoji(z.name)} ${this._escapeHtml(z.name)}
                        </button>
                      `;
        })
        .join("")}
                </div>
              </div>
            </div>
            ${isAdmin && this._showMediaMappingsEditor
        ? `
              <div style="background: var(--otis-surface); border: 1px solid var(--otis-primary); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                  <div>
                    <div style="font-size: 0.84rem; font-weight: 700; color: var(--otis-primary);">
                      🔗 Physical Matrix Input-to-Player Mappings
                    </div>
                    <div style="font-size: 0.72rem; color: var(--otis-text-muted);">
                      Map physical matrix amplifier inputs to upstream streaming players (Music Assistant, Alexa, VLC, Plex, etc.).
                    </div>
                  </div>
                  <button type="button" class="btn-toolbar" id="btn-save-media-mappings" style="background: var(--otis-primary); color: #fff; border-color: var(--otis-primary); font-weight: 700; padding: 5px 14px; font-size: 0.74rem;">
                    💾 Save Mappings
                  </button>
                </div>

                <div style="display: flex; flex-direction: column; gap: 8px; max-height: 280px; overflow-y: auto; padding-right: 4px;">
                  ${allInputs
          .filter((inp) => inp.toLowerCase() !== "none")
          .map((inpName) => {
            const mappedEid = effectiveMappings[inpName] || "";
            return `
                        <div style="display: grid; grid-template-columns: minmax(130px, 1fr) 2fr; gap: 8px; align-items: center; background: rgba(0,0,0,0.22); padding: 8px 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06);">
                          <span style="font-size: 0.76rem; font-weight: 600; color: var(--otis-text);">🔌 ${this._escapeHtml(inpName)}</span>
                          <select class="studio-media-mapping-select" data-input-name="${this._escapeHtml(inpName)}" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;">
                            <option value="">-- Unmapped / Auto-Detect --</option>
                            ${candidatePlayers
                .map(
                  (p) => `
                              <option value="${this._escapeHtml(p.entity_id)}" ${p.entity_id === mappedEid ? "selected" : ""}>
                                ${this._escapeHtml(p.name)} (${this._escapeHtml(p.entity_id)}) [${this._escapeHtml(p.service_profile?.display_name || p.platform || "Player")}]
                              </option>
                            `
                )
                .join("")}
                          </select>
                        </div>
                      `;
          })
          .join("")}
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06);">
                  <div style="display: flex; flex-direction: column; gap: 4px;">
                    <label style="font-size: 0.7rem; color: var(--otis-text-muted); font-weight: 600;">Unjoin / Mute Input Source:</label>
                    <select id="studio-media-unjoin-input" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;">
                      <option value="None" ${unjoinInput === "None" ? "selected" : ""}>None</option>
                      ${allInputs
          .map(
            (inp) => `
                        <option value="${this._escapeHtml(inp)}" ${inp.toLowerCase() === unjoinInput.toLowerCase() ? "selected" : ""}>
                          ${this._escapeHtml(inp)}
                        </option>
                      `
          )
          .join("")}
                    </select>
                  </div>

                  <div style="display: flex; flex-direction: column; gap: 4px;">
                    <label style="font-size: 0.7rem; color: var(--otis-text-muted); font-weight: 600;">Default Speaker Zone:</label>
                    <select id="studio-media-default-zone" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;">
                      <option value="">-- Auto-Select First Zone --</option>
                      ${zones
          .map(
            (z) => `
                        <option value="${this._escapeHtml(z.entity_id)}" ${z.entity_id === (studioData.default_zone || selectedZone.entity_id) ? "selected" : ""}>
                          ${this._escapeHtml(z.name)} (${this._escapeHtml(z.entity_id)})
                        </option>
                      `
          )
          .join("")}
                    </select>
                  </div>
                </div>
              </div>
            `
        : ""
      }

            <!-- Per-User & Household Favorites Card -->
            <div style="background: var(--otis-surface); border: 1px solid var(--otis-surface-border); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px;">
              <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 0.84rem; font-weight: 700; color: var(--otis-primary);">⭐ ${this._escapeHtml(userName)}'s Favorites &amp; Stations</span>
                    <span style="font-size: 0.64rem; padding: 1px 6px; border-radius: 999px; background: rgba(168,85,247,0.18); border: 1px solid rgba(168,85,247,0.4); color: #c084fc; font-weight: 700;">
                      Per-User Synced
                    </span>
                  </div>
                  <div style="font-size: 0.71rem; color: var(--otis-text-muted);">1-click routes "${this._escapeHtml(selectedZone.name)}" to the saved input &amp; starts your station or playlist.</div>
                </div>
                <button type="button" class="btn-toolbar" id="btn-media-toggle-add-fav" style="background: rgba(14,165,233,0.18); border-color: rgba(56,189,248,0.45); color: var(--otis-primary); font-size: 0.74rem; padding: 5px 10px;">
                  ${this._showAddFavoriteForm ? "✕ Close" : "+ Add Favorite"}
                </button>
              </div>

              ${this._showAddFavoriteForm
        ? `
                <!-- Inline Add Favorite Form (Non-Admin Safe & Agnostic Provider Types) -->
                <div style="background: rgba(0,0,0,0.28); border: 1px solid rgba(56,189,248,0.35); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 10px;">
                  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                    <div>
                      <label style="font-size: 0.7rem; color: var(--otis-text-muted); display: block; margin-bottom: 3px;">Favorite Label *</label>
                      <input type="text" id="fav-form-name" value="${this._escapeHtml(this._favFormName)}" placeholder="e.g. Smooth Jazz, NPR, 80s Rock" style="width: 100%; box-sizing: border-box; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;" />
                    </div>
                    <div>
                      <label style="font-size: 0.7rem; color: var(--otis-text-muted); display: block; margin-bottom: 3px;">Matrix Input Source *</label>
                      <select id="fav-form-input" style="width: 100%; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;">
                        ${allInputs
          .filter((inp) => inp.toLowerCase() !== "none")
          .map(
            (inp) => `
                          <option value="${this._escapeHtml(inp)}" ${(this._favFormInput || activeInput) === inp ? "selected" : ""}>
                            🔌 ${this._escapeHtml(inp)}
                          </option>
                        `
          )
          .join("")}
                      </select>
                    </div>
                  </div>
                  ${this._mediaBrowseOpen
          ? `
                    <div style="padding: 8px; border-radius: 8px; background: rgba(15, 23, 42, 0.55); border: 1px solid var(--otis-surface-border);">
                      ${this._mediaBrowseLoading
            ? `
                        <div style="padding: 12px; text-align: center; color: var(--otis-text-muted); font-size: 0.74rem;">
                          <span style="display: inline-block; animation: otis-spin 0.8s linear infinite; margin-right: 6px;">🔄</span>
                          Loading ${this._escapeHtml(this._mediaBrowseType)}s...
                        </div>
                      `
            : this._mediaBrowseError
              ? `
                        <div style="padding: 8px; border-radius: 6px; background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); color: #fca5a5; font-size: 0.72rem;">
                          ⚠️ ${this._escapeHtml(this._mediaBrowseError)}
                        </div>
                      `
              : this._mediaBrowseItems.length === 0
                ? `
                        <div style="padding: 10px; text-align: center; color: var(--otis-text-muted); font-size: 0.72rem;">
                          No items found for "${this._escapeHtml(this._mediaBrowseType)}".
                        </div>
                      `
                : `
                        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 6px; max-height: 200px; overflow-y: auto; padding-right: 2px;">
                          ${this._mediaBrowseItems
                  .map(
                    (item) => `
                            <div class="fav-picker-item" data-id="${this._escapeHtml(item.id)}" data-name="${this._escapeHtml(item.name)}" data-type="${this._escapeHtml(item.media_type || this._mediaBrowseType)}" style="cursor: pointer; padding: 6px 8px; border-radius: 6px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; gap: 2px; transition: background 0.15s ease;" title="Click to select ${this._escapeHtml(item.name)}">
                              <span style="font-size: 0.74rem; font-weight: 600; color: var(--otis-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                🎵 ${this._escapeHtml(item.name)}
                              </span>
                              ${item.artist
                        ? `<span style="font-size: 0.64rem; color: var(--otis-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${this._escapeHtml(item.artist)}</span>`
                        : ""
                      }
                            </div>
                          `
                  )
                  .join("")}
                        </div>
                      `
          }
                    </div>
                  `
          : ""
        }
                  <div>
                    <label style="font-size: 0.7rem; color: var(--otis-text-muted); display: block; margin-bottom: 3px;">Station / Playlist / Voice Command</label>
                    <input type="text" id="fav-form-command" value="${this._escapeHtml(this._favFormCommand)}" placeholder="${supportsVoice ? 'e.g. play smooth jazz on Spotify, NPR News' : 'e.g. Playlist or Station URI / Name'}" style="width: 100%; box-sizing: border-box; padding: 6px 8px; border-radius: 6px; background: var(--otis-surface); color: var(--otis-text); border: 1px solid var(--otis-surface-border); font-size: 0.76rem;" />
                  </div>
                  <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                    ${isAdmin
          ? `
                      <label style="display: flex; align-items: center; gap: 6px; font-size: 0.73rem; color: var(--otis-text-muted); cursor: pointer;">
                        <input type="checkbox" id="fav-form-shared" ${this._favFormShared ? "checked" : ""} style="cursor: pointer;" />
                        <span>🏠 Share with all household users</span>
                      </label>
                    `
          : `<span></span>`
        }
                    <div style="display: flex; gap: 6px;">
                      <button type="button" class="btn-toolbar" id="btn-fav-form-cancel" style="padding: 5px 10px; font-size: 0.73rem;">Cancel</button>
                      <button type="button" class="btn-toolbar" id="btn-fav-form-submit" style="background: var(--otis-primary); color: #fff; border-color: var(--otis-primary); font-weight: 700; padding: 5px 14px; font-size: 0.73rem;">
                        ⭐ Save Favorite
                      </button>
                    </div>
                  </div>
                </div>
              `
        : ""
      }

              ${favorites.length === 0
        ? `
                <div style="padding: 16px; text-align: center; border-radius: 10px; background: rgba(0,0,0,0.16); border: 1px dashed rgba(255,255,255,0.12); font-size: 0.76rem; color: var(--otis-text-muted);">
                  No favorites saved yet for ${this._escapeHtml(userName)}. Click <strong>+ Add Favorite</strong> or <strong>⭐ Save Track</strong> while music is playing!
                </div>
              `
        : `
                <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap: 8px;">
                  ${favorites
          .map((fav) => {
            const canDelete = fav.scope === "user" || isAdmin;
            return `
                        <div class="media-fav-card" style="position: relative; display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 8px 10px; border-radius: 10px; background: rgba(0,0,0,0.22); border: 1px solid var(--otis-surface-border); transition: all 0.15s ease;">
                          <button type="button" class="btn-media-play-fav" data-fav-id="${this._escapeHtml(fav.id)}" data-zone-id="${this._escapeHtml(selectedZone.entity_id)}" title="Play ${this._escapeHtml(fav.name)} on ${this._escapeHtml(selectedZone.name)} (Input: ${this._escapeHtml(fav.input || activeInput)})" style="background: transparent; border: none; color: var(--otis-text); text-align: left; cursor: pointer; flex: 1; min-width: 0; padding: 0; display: flex; flex-direction: column; gap: 2px;">
                            <div style="font-size: 0.78rem; font-weight: 700; color: var(--otis-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                              ▶️ ${this._escapeHtml(fav.name)}
                            </div>
                            <div style="font-size: 0.66rem; color: var(--otis-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                              🔌 ${this._escapeHtml(fav.input || "Auto")}${fav.scope === "shared" ? " • 🏠 Shared" : ""}
                            </div>
                          </button>
                          ${canDelete
                ? `
                            <button type="button" class="btn-media-delete-fav" data-fav-id="${this._escapeHtml(fav.id)}" data-fav-scope="${this._escapeHtml(fav.scope || "user")}" title="Remove favorite" style="background: transparent; border: none; color: var(--otis-text-muted); cursor: pointer; font-size: 0.75rem; padding: 2px 4px; border-radius: 4px;">
                              ✕
                            </button>
                          `
                : ""
              }
                        </div>
                      `;
          })
          .join("")}
                </div>
              `
      }
            </div>
          </div>
        </div>
      </div>
    `;
  },

  _renderVisionTab() {
    const fusedSensorId = this._resolveOtisEntityId("sensor.otis_fused_presence");
    const fusedSensor = this._hass?.states?.[fusedSensorId];
    const fusedAttrs = fusedSensor?.attributes || {};
    const visionTopo = this._capabilityMap?.vision_topology || {};
    const pres = fusedAttrs.rooms ? fusedAttrs : (visionTopo.presence || {});
    const rooms = pres.rooms || {};
    const cameras = visionTopo.cameras || [];
    const recentAudits = visionTopo.recent_audits || [];
    const occCount = pres.occupied_count ?? 0;
    const microCount = pres.micro_presence_count ?? 0;
    const likelyCount = pres.likely_count ?? 0;
    const vacantCount = pres.vacant_count ?? 0;
    const roomEntries = Object.values(rooms);
    const sentinelSensorId = this._resolveOtisEntityId("sensor.otis_perimeter_sentinel");
    const lastVoiceAnnouncement = this._hass?.states?.[sentinelSensorId]?.attributes?.last_voice_announcement;

    return `
      <div class="vision-panel">
        ${this._renderPreconditioningChip()}
        ${lastVoiceAnnouncement
        ? `
            <div style="margin-bottom: 12px; padding: 10px 14px; border-radius: 10px; background: rgba(14, 165, 233, 0.12); border: 1px solid rgba(14, 165, 233, 0.35); font-size: 0.8rem; display: flex; align-items: center; justify-content: space-between; gap: 10px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 1.15rem;">🔊</span>
                <div>
                  <div style="font-weight: 700; color: var(--otis-primary, #38bdf8);">Latest Proactive Voice Alert:</div>
                  <div style="color: var(--otis-text); margin-top: 2px;">
                    "${this._escapeHtml(lastVoiceAnnouncement)}"
                  </div>
                </div>
              </div>
              <button type="button" class="subview-chip btn-repeat-alert-voice" title="Re-broadcast announcement across household speakers" style="padding: 4px 10px; font-size: 0.72rem; white-space: nowrap; cursor: pointer; background: rgba(14, 165, 233, 0.25); border: 1px solid rgba(14, 165, 233, 0.45); color: #fff;">
                📢 Re-announce
              </button>
            </div>
            `
        : ""
      }
        <div class="vision-overview-card">
          <div class="vision-stats-row">
            <span style="font-weight: 700; font-size: 0.88rem; color: var(--otis-primary);">👁️ Presence Status:</span>
            <span class="vision-stat-chip ${pres.household_present !== false ? 'occupied' : 'vacant'}">
              ${pres.household_present !== false ? "🏠 Household Present" : "🚪 Away Mode"}
            </span>
            <span class="vision-stat-chip occupied">🟢 ${occCount} Occupied</span>
            ${microCount > 0 ? `<span class="vision-stat-chip micro_presence">🟣 ${microCount} Micro-Presence</span>` : ""}
            ${likelyCount > 0 ? `<span class="vision-stat-chip likely">🟡 ${likelyCount} Likely</span>` : ""}
            <span class="vision-stat-chip vacant">⚪ ${vacantCount} Vacant</span>
          </div>
          <button type="button" class="btn-toolbar" id="btn-refresh-vision" style="font-size: 0.76rem; padding: 4px 10px;">
            🔄 Fuse Presence
          </button>
        </div>

        <div class="vision-section-title">
          <span>📡 Multimodal Presence Fusion (BLE Trilateration + mmWave Radar + Thermal + Acoustic)</span>
        </div>

        <div class="presence-grid">
          ${roomEntries.length === 0
        ? `<div style="grid-column: 1/-1; padding: 20px; text-align: center; color: var(--otis-text-muted);">
                  Scanning presence sensors and spatial areas...
                </div>`
        : roomEntries
          .map((r) => {
            const statusClass = r.status || "vacant";
            const pct = r.confidence_percent ?? 0;
            const s = r.modalities || r.sensors || {};
            const mmwave = s.mmwave || {};
            const thermal = s.thermal || {};
            const ble = s.ble || s.ble_beacon || {};
            const acoustic = s.acoustic || {};
            const pir = s.pir || {};
            const media = s.media || {};
            const lightsOn = s.lights_on || 0;

            let badgeText = "⚪ VACANT";
            if (statusClass === "micro_presence") {
              badgeText = "🟣 MICRO-PRESENCE";
            } else if (statusClass === "occupied") {
              badgeText = "🟢 OCCUPIED";
            } else if (statusClass === "likely_occupied" || statusClass === "likely") {
              badgeText = "🟡 LIKELY";
            }

            let pirText = pir.active ? "Motion Active" : pir.seconds_since_motion ? `${Math.round(pir.seconds_since_motion / 60) || 1}m ago` : "Idle";

            return `
                    <div class="presence-card">
                      <div class="presence-card-head">
                        <span class="presence-room-name">
                          ${this._escapeHtml(r.area_name)}
                          ${r.attributed_user ? `<span style="font-size: 0.72rem; color: #38bdf8; margin-left: 6px; font-weight: 600;">👤 ${this._escapeHtml(r.attributed_user)}</span>` : ""}
                        </span>
                        <span class="presence-badge ${statusClass}">
                          ${badgeText} • ${pct}%
                        </span>
                      </div>
                      <div class="presence-bar-track">
                        <div class="presence-bar-fill ${statusClass}" style="width: ${Math.max(4, pct)}%;"></div>
                      </div>
                      <div class="presence-sensors-row">
                        <span class="presence-sensor-pill ${mmwave.active ? 'active' : ''}" title="mmWave Micro-movement Radar (breathing / stationary / moving targets)">
                          📡 mmWave: ${mmwave.mode && mmwave.mode !== 'clear' ? mmwave.mode : (mmwave.active ? 'Active' : 'Idle')}
                        </span>
                        <span class="presence-sensor-pill ${thermal.detected ? 'active' : ''}" title="Thermal Infrared Heat Signature (human body vs pets/appliances)">
                          🌡️ Thermal: ${thermal.detected ? `Body Heat (${thermal.delta_c ? '+' + thermal.delta_c + '°C' : 'Human'})` : (thermal.target_type === 'pet_or_appliance' ? 'Pet Filtered' : 'None')}
                        </span>
                        ${ble.active || r.attributed_user ? `
                        <span class="presence-sensor-pill active" title="BLE Beacon Proximity &amp; Trilateration">
                          📍 BLE: ${this._escapeHtml(r.attributed_user || ble.user || (ble.distance_m ? ble.distance_m + 'm' : 'Near'))}
                        </span>` : ""}
                        ${acoustic.detected ? `
                        <span class="presence-sensor-pill active" title="Acoustic Footprinting (speech / footsteps / decibel spike)">
                          🎙️ Sound: ${this._escapeHtml(acoustic.event_type || 'Active')}
                        </span>` : ""}
                        <span class="presence-sensor-pill ${pir.active ? 'active' : ''}" title="PIR Motion Sensor">
                          🏃 PIR: ${pirText}
                        </span>
                        <span class="presence-sensor-pill ${media.playing || media.active ? 'active' : ''}" title="Audio/Video Playback Presence">
                          🎵 Media: ${media.playing || media.active ? 'Playing' : 'Off'}
                        </span>
                        ${lightsOn > 0 ? `<span class="presence-sensor-pill active" title="Lights On">💡 ${lightsOn} On</span>` : ""}
                      </div>
                    </div>
                  `;
          })
          .join("")
      }
        </div>

        <div class="vision-section-title" style="margin-top: 10px;">
          <span>📷 Security Cameras &amp; Gemini Vision Anomaly Analysis</span>
        </div>

        <div class="camera-grid">
          ${cameras.length === 0
        ? `<div style="grid-column: 1/-1; padding: 20px; text-align: center; color: var(--otis-text-muted);">
                  No security cameras discovered in Home Assistant.
                </div>`
        : cameras
          .map((cam) => {
            const audit = this._cameraAudits[cam.entity_id] || recentAudits.find((a) => a.camera === cam.entity_id);
            const isAnalyzing = this._analyzingCamera === cam.entity_id;
            const tagList = audit?.detected_objects || [];

            const camState = this._hass?.states?.[cam.entity_id];
            const token = camState?.attributes?.access_token || cam.access_token;
            const entityPic = camState?.attributes?.entity_picture || cam.entity_picture;
            let imgSrc = entityPic;
            if (!imgSrc && token) {
              imgSrc = `/api/camera_proxy/${cam.entity_id}?token=${token}&time=${Date.now()}`;
            }

            return `
                    <div class="camera-card">
                      <div class="camera-preview-container" data-cam-id="${this._escapeHtml(cam.entity_id)}" title="Click to view live stream" style="cursor: pointer;">
                        ${imgSrc
                ? `<img class="camera-preview-img" 
                                   src="${imgSrc}" 
                                   alt="${this._escapeHtml(cam.name)}" 
                                   loading="lazy" 
                                   onerror="this.style.display='none'; if (this.nextElementSibling) this.nextElementSibling.style.display='flex';" />`
                : ""
              }
                        <div class="camera-preview-fallback" style="display: ${imgSrc ? "none" : "flex"}; align-items: center; justify-content: center; height: 100%; min-height: 140px; background: #0f172a; color: var(--otis-text-muted);">
                          <span>📹 Live Camera Ready</span>
                        </div>
                        <span class="camera-cam-badge">
                          ${cam.is_doorbell ? "🔔 Doorbell" : cam.is_perimeter ? "🛡️ Perimeter" : "📹 Interior"}
                        </span>
                      </div>
                      <div class="camera-card-body">
                        <div class="camera-card-title">
                          <span>${this._escapeHtml(cam.name)}</span>
                          <span style="font-size: 0.72rem; color: var(--otis-text-muted);">${this._escapeHtml(cam.area_name || "")}</span>
                        </div>
                        <button type="button" 
                                class="btn-analyze-camera" 
                                data-camera="${this._escapeHtml(cam.entity_id)}" 
                                ${isAnalyzing ? "disabled" : ""}>
                          ${isAnalyzing ? "⏳ Analyzing Frame..." : "✨ Analyze with Gemini Vision"}
                        </button>
                        ${audit
                ? `
                            <div class="vision-audit-result">
                              <div style="display: flex; align-items: center; justify-content: space-between;">
                                <strong style="color: ${audit.status === 'normal' ? '#34d399' : '#fbbf24'};">
                                  ${this._escapeHtml(audit.status?.toUpperCase() || 'AUDIT')}
                                </strong>
                                <span style="font-size: 0.66rem; color: var(--otis-text-muted);">
                                  ${new Date(audit.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </span>
                              </div>
                              <div>${this._escapeHtml(audit.summary || audit.safety_assessment || '')}</div>
                              ${tagList.length > 0
                  ? `<div style="display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px;">
                                      ${tagList.map((t) => `<span class="tag-pill">${t === 'package' ? '📦 package' : t === 'person' ? '👤 person' : t === 'vehicle' ? '🚗 vehicle' : t}</span>`).join('')}
                                    </div>`
                  : ''
                }
                            </div>
                          `
                : ""
              }
                      </div>
                    </div>
                  `;
          })
          .join("")
      }
        </div>
      </div>
    `;
  },

};
