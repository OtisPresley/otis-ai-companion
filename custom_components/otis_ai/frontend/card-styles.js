/** Extracted stylesheet for OtisCompanionCard. */
export const CARD_STYLES = `
        :host {
          display: block;
          width: 100%;
          box-sizing: border-box;
          font-family: var(--ha-card-font-family, 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
        }

        /* Base Card Styling with Token Architecture for Card-Mod & Custom Themes */
        :host,
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
        }

        ha-card.card-container {
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

        ha-card.card-container.layout-compact {
          padding: 14px 16px;
        }

        ha-card.card-container.layout-compact .studio-header {
          margin-bottom: 10px;
          padding-bottom: 8px;
          gap: 8px;
        }

        ha-card.card-container.nav-sleek_buttons .launchpad-row .subview-chip {
          border-radius: 10px;
          padding: 7px 14px;
          font-size: 0.76rem;
          font-weight: 500;
        }

        ha-card.card-container.nav-compact_pills .launchpad-row .subview-chip {
          border-radius: 999px;
          padding: 3px 10px;
          font-size: 0.70rem;
          gap: 4px;
        }

        ha-card.card-container.nav-standard_grid .launchpad-row {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(145px, 1fr));
          gap: 8px;
          align-items: stretch;
        }

        ha-card.card-container.nav-standard_grid .launchpad-row .subviews-label {
          grid-column: 1 / -1;
        }

        ha-card.card-container.nav-standard_grid .launchpad-row .subview-chip {
          border-radius: 10px;
          padding: 10px 12px;
          font-weight: 600;
          justify-content: center;
          text-align: center;
          min-height: 40px;
          margin-left: 0 !important;
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
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.08);
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

        /* Weather & Calendar Glance Strip */
        .glance-strip {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
          gap: 10px;
          margin-bottom: 14px;
        }

        .glance-chip {
          display: flex;
          align-items: center;
          gap: 12px;
          background: var(--otis-surface);
          border: 1px solid var(--otis-surface-border);
          border-radius: 12px;
          padding: 10px 14px;
          cursor: pointer;
          transition: all 0.25s ease;
          user-select: none;
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }

        .glance-chip:hover {
          border-color: var(--otis-primary);
          background: color-mix(in srgb, var(--otis-primary) 8%, var(--otis-surface));
          transform: translateY(-1px);
          box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28), 0 0 12px var(--otis-glow);
        }

        .glance-icon {
          font-size: 1.5rem;
          line-height: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .glance-text {
          display: flex;
          flex-direction: column;
          gap: 2px;
          overflow: hidden;
        }

        .glance-primary {
          font-size: 0.85rem;
          font-weight: 700;
          color: var(--otis-text);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .glance-secondary {
          font-size: 0.72rem;
          color: var(--otis-text-muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
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
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06);
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

        /* Persona & Behavioral Rules Modal */
        .persona-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
          gap: 10px;
        }

        .persona-card {
          background: color-mix(in srgb, var(--otis-surface) 80%, transparent);
          border: 1px solid var(--otis-surface-border);
          border-radius: 12px;
          padding: 12px;
          cursor: pointer;
          display: flex;
          flex-direction: column;
          gap: 6px;
          transition: all 0.15s ease;
        }

        .persona-card:hover {
          border-color: var(--otis-primary);
          transform: translateY(-1px);
        }

        .persona-card.selected {
          border-color: var(--otis-primary);
          background: color-mix(in srgb, var(--otis-primary) 12%, var(--otis-surface));
          box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
        }

        .persona-title {
          font-weight: 700;
          font-size: 0.88rem;
          display: flex;
          align-items: center;
          gap: 8px;
          color: var(--otis-text);
        }

        .persona-desc {
          font-size: 0.74rem;
          color: var(--otis-text-muted);
          line-height: 1.35;
        }

        .rules-setting-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 12px;
          background: color-mix(in srgb, var(--otis-surface) 60%, transparent);
          border: 1px solid var(--otis-surface-border);
          border-radius: 10px;
          gap: 12px;
        }

        .rules-setting-label {
          font-weight: 600;
          font-size: 0.82rem;
          color: var(--otis-text);
        }

        .rules-setting-desc {
          font-size: 0.72rem;
          color: var(--otis-text-muted);
          margin-top: 2px;
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
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06);
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
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06);
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

        .badge-priority.ignored {
          background: rgba(148, 163, 184, 0.12);
          color: #94a3b8;
          border: 1px dashed rgba(148, 163, 184, 0.45);
        }

        .suggestion-card.is-ignored {
          opacity: 0.68;
          border-style: dashed;
        }

        .suggestion-card.is-ignored:hover {
          opacity: 0.95;
        }

        .btn-subtle-toggle {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid var(--otis-surface-border, rgba(255, 255, 255, 0.1));
          border-radius: 8px;
          color: var(--otis-text-muted);
          font-size: 0.74rem;
          font-weight: 500;
          padding: 5px 11px;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 5px;
          transition: all 0.2s ease;
        }

        .btn-subtle-toggle:hover {
          background: rgba(255, 255, 255, 0.1);
          color: var(--otis-text);
          border-color: rgba(255, 255, 255, 0.2);
        }

        .btn-subtle-toggle.active {
          background: rgba(56, 189, 248, 0.16);
          border-color: rgba(56, 189, 248, 0.4);
          color: var(--otis-primary, #38bdf8);
          font-weight: 600;
        }

        .btn-dismiss-card {
          background: transparent;
          border: 1px solid var(--otis-surface-border, rgba(255, 255, 255, 0.15));
          border-radius: 8px;
          color: var(--otis-text-muted);
          font-size: 0.76rem;
          font-weight: 500;
          padding: 6px 12px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }

        .btn-dismiss-card:hover {
          background: rgba(244, 63, 94, 0.12);
          border-color: rgba(244, 63, 94, 0.35);
          color: #f43f5e;
        }

        .btn-restore {
          background: rgba(56, 189, 248, 0.1);
          border: 1px solid rgba(56, 189, 248, 0.3);
          border-radius: 8px;
          color: var(--otis-primary, #38bdf8);
          font-size: 0.76rem;
          font-weight: 500;
          padding: 6px 12px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }

        .btn-restore:hover {
          background: rgba(56, 189, 248, 0.2);
          border-color: var(--otis-primary, #38bdf8);
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
          flex-wrap: wrap;
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
          user-select: text !important;
          -webkit-user-select: text !important;
          -moz-user-select: text !important;
        }

        .chat-bubble {
          position: relative;
          max-width: 90%;
          padding: 10px 14px;
          border-radius: 14px;
          font-size: 0.82rem;
          line-height: 1.5;
          word-break: break-word;
          user-select: text !important;
          -webkit-user-select: text !important;
          -moz-user-select: text !important;
          cursor: text;
        }

        .chat-bubble *,
        .reasoning-steps-list,
        .reasoning-steps-list * {
          user-select: text !important;
          -webkit-user-select: text !important;
          -moz-user-select: text !important;
        }

        .chat-bubble button,
        .chat-bubble .prompt-copy-btn,
        .chat-bubble .response-copy-btn,
        .chat-bubble .response-retry-btn,
        .chat-bubble .code-copy-btn {
          user-select: none !important;
          -webkit-user-select: none !important;
          cursor: pointer;
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
          margin: 10px 0;
          border-radius: 8px;
          overflow: hidden;
          background: rgba(15, 23, 42, 0.9);
          border: 1px solid var(--otis-surface-border);
        }

        .code-block-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 4px 10px;
          background: rgba(0, 0, 0, 0.45);
          border-bottom: 1px solid var(--otis-surface-border);
        }

        .code-block-header .code-lang {
          font-size: 0.68rem;
          color: var(--otis-primary);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-family: ui-monospace, monospace;
          font-weight: 600;
        }

        .code-copy-btn {
          background: rgba(255, 255, 255, 0.06);
          border: 1px solid rgba(255, 255, 255, 0.18);
          color: var(--otis-text-muted);
          border-radius: 4px;
          height: 22px;
          padding: 0 8px;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          cursor: pointer;
          transition: all 0.15s ease;
          font-size: 0.68rem;
          font-weight: 500;
        }

        .code-copy-btn:hover {
          color: #ffffff;
          background: color-mix(in srgb, var(--otis-primary) 30%, transparent);
          border-color: var(--otis-primary);
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
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.08);
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

        .bubble-actions-group {
          position: absolute;
          top: 6px;
          right: 6px;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          z-index: 2;
        }

        .response-retry-btn,
        .response-copy-btn {
          background: rgba(0, 0, 0, 0.4);
          border: 1px solid rgba(255, 255, 255, 0.18);
          color: var(--otis-text-muted);
          border-radius: 4px;
          height: 22px;
          padding: 0 6px;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          cursor: pointer;
          transition: all 0.15s ease;
          font-size: 0.68rem;
          font-weight: 500;
          opacity: 0.7;
        }

        .chat-bubble.otis {
          position: relative;
          align-self: flex-start;
          background: var(--otis-surface);
          color: var(--otis-text);
          border-bottom-left-radius: 3px;
          border: 1px solid color-mix(in srgb, var(--otis-primary) 20%, transparent);
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.08);
          padding-top: 26px;
        }

        .chat-bubble.otis:hover .response-retry-btn,
        .chat-bubble.otis:hover .response-copy-btn,
        .response-retry-btn:hover,
        .response-copy-btn:hover {
          opacity: 1;
          color: #ffffff;
          background: color-mix(in srgb, var(--otis-primary) 30%, transparent);
          border-color: var(--otis-primary);
        }

        .response-retry-btn:hover svg {
          transform: rotate(45deg);
        }

        .response-retry-btn svg {
          transition: transform 0.2s ease;
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

        .reasoning-agent-pill {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          padding: 1px 6px;
          border-radius: 999px;
          font-size: 0.65rem;
          font-weight: 600;
          vertical-align: middle;
          margin-left: 4px;
        }

        .reasoning-agent-pill.cloud {
          background: rgba(59, 130, 246, 0.2);
          color: #93c5fd;
          border: 1px solid rgba(59, 130, 246, 0.4);
        }

        .reasoning-agent-pill.edge {
          background: rgba(16, 185, 129, 0.2);
          color: #6ee7b7;
          border: 1px solid rgba(16, 185, 129, 0.4);
        }

        .reasoning-agent-pill.failed {
          background: rgba(239, 68, 68, 0.2);
          color: #fca5a5;
          border: 1px solid rgba(239, 68, 68, 0.4);
        }

        .reasoning-step-item.resolution {
          background: rgba(255, 255, 255, 0.04);
          border-left: 2px solid #38bdf8;
          padding: 4px 6px 4px 8px;
          border-radius: 4px;
        }

        .reasoning-step-item.exhaustion {
          background: rgba(239, 68, 68, 0.08);
          border-left: 2px solid #ef4444;
          padding: 4px 6px 4px 8px;
          border-radius: 4px;
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
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06);
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
          background: linear-gradient(135deg, rgba(239, 68, 68, 0.28) 0%, rgba(225, 29, 72, 0.35) 100%);
          border: 1px solid rgba(248, 113, 113, 0.65);
          color: #fecaca;
          opacity: 1 !important;
          cursor: pointer !important;
          gap: 6px;
          padding: 8px 12px;
        }

        .send-btn.sending:hover {
          background: linear-gradient(135deg, rgba(239, 68, 68, 0.45) 0%, rgba(225, 29, 72, 0.5) 100%);
          border-color: #f87171;
          color: #ffffff;
        }

        .chat-stop-btn {
          margin-left: auto;
          background: rgba(239, 68, 68, 0.18);
          border: 1px solid rgba(248, 113, 113, 0.5);
          color: #fecaca;
          font-size: 0.72rem;
          font-weight: 600;
          padding: 3px 9px;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.18s ease;
          white-space: nowrap;
        }

        .chat-stop-btn:hover {
          background: rgba(239, 68, 68, 0.35);
          border-color: #f87171;
          color: #ffffff;
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

        .attach-btn {
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
        }

        .attach-btn:hover {
          background: color-mix(in srgb, var(--otis-primary) 15%, transparent);
          color: var(--otis-primary);
          border-color: color-mix(in srgb, var(--otis-primary) 30%, transparent);
        }

        .attach-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .chat-attachments-tray {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-bottom: 8px;
          padding: 6px 10px;
          background: rgba(0, 0, 0, 0.2);
          border-radius: 8px;
          border: 1px dashed var(--otis-chip-border);
        }

        .chat-attachment-item {
          display: flex;
          align-items: center;
          gap: 6px;
          background: var(--otis-surface);
          border: 1px solid var(--otis-surface-border);
          border-radius: 6px;
          padding: 4px 8px;
          font-size: 0.76rem;
          color: var(--otis-text);
        }

        .chat-attachment-thumb {
          width: 30px;
          height: 30px;
          border-radius: 4px;
          object-fit: cover;
        }

        .chat-attachment-name {
          max-width: 140px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .chat-attachment-remove {
          cursor: pointer;
          background: none;
          border: none;
          color: #f43f5e;
          font-weight: bold;
          font-size: 0.85rem;
          padding: 0 3px;
        }

        .bubble-attachments {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          margin-bottom: 8px;
        }

        .bubble-attachment-img {
          max-width: 200px;
          max-height: 140px;
          border-radius: 8px;
          object-fit: cover;
          border: 1px solid rgba(255, 255, 255, 0.15);
          cursor: pointer;
        }

        .bubble-attachment-file {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 6px;
          font-size: 0.74rem;
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
          position: relative;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.07);
          border-radius: 8px;
          padding: 6px 4px;
          text-align: center;
          display: flex;
          flex-direction: column;
          gap: 2px;
          cursor: pointer;
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .maturity-pill:hover {
          background: rgba(255, 255, 255, 0.08);
          border-color: var(--otis-primary);
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
          z-index: 50;
        }

        .maturity-pill-max {
          border-color: rgba(16, 185, 129, 0.35);
        }

        .maturity-pill-improve {
          border-color: rgba(245, 158, 11, 0.35);
        }

        .maturity-pill-val {
          font-size: 0.78rem;
          font-weight: 700;
          color: var(--otis-primary);
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 3px;
        }

        .maturity-pill-lbl {
          font-size: 0.62rem;
          text-transform: uppercase;
          color: var(--otis-text-muted);
        }

        .maturity-tooltip {
          visibility: hidden;
          opacity: 0;
          position: absolute;
          bottom: calc(100% + 8px);
          left: 50%;
          transform: translateX(-50%);
          width: 240px;
          background: #0f172a;
          color: #f1f5f9;
          text-align: left;
          border-radius: 8px;
          padding: 8px 10px;
          font-size: 0.72rem;
          line-height: 1.4;
          border: 1px solid rgba(56, 189, 248, 0.4);
          box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.85);
          z-index: 1000;
          pointer-events: none;
          transition: opacity 0.2s ease, visibility 0.2s ease;
          white-space: normal;
        }

        .maturity-pill:hover .maturity-tooltip {
          visibility: visible;
          opacity: 1;
        }

        .maturity-pill:first-child .maturity-tooltip {
          left: 0;
          transform: none;
        }

        .maturity-pill:last-child .maturity-tooltip {
          left: auto;
          right: 0;
          transform: none;
        }

        .maturity-tooltip-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-weight: 700;
          font-size: 0.76rem;
          color: #38bdf8;
          margin-bottom: 4px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          padding-bottom: 3px;
        }

        .maturity-tooltip-badge {
          font-size: 0.62rem;
          padding: 1px 6px;
          border-radius: 4px;
          font-weight: 600;
        }

        .badge-max {
          background: rgba(16, 185, 129, 0.2);
          color: #10b981;
          border: 1px solid rgba(16, 185, 129, 0.4);
        }

        .badge-improve {
          background: rgba(245, 158, 11, 0.2);
          color: #fbbf24;
          border: 1px solid rgba(245, 158, 11, 0.4);
        }

        .maturity-tooltip-body {
          font-size: 0.7rem;
          color: #cbd5e1;
          line-height: 1.35;
        }

        .maturity-tooltip-action {
          margin-top: 5px;
          font-size: 0.65rem;
          color: #38bdf8;
          font-weight: 600;
          border-top: 1px solid rgba(255, 255, 255, 0.08);
          padding-top: 4px;
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
          position: fixed;
          bottom: 24px;
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
          z-index: 10000;
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
          gap: 10px;
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

        .view-mode-pills {
          display: inline-flex;
          background: rgba(15, 23, 42, 0.65);
          border: 1px solid var(--otis-surface-border, rgba(56, 189, 248, 0.22));
          border-radius: 9px;
          padding: 2px;
          gap: 2px;
        }

        .view-mode-pill {
          background: transparent;
          border: none;
          color: var(--otis-text-muted, #94a3b8);
          font-size: 0.72rem;
          font-weight: 700;
          padding: 4px 9px;
          border-radius: 7px;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .view-mode-pill:hover {
          color: #fff;
        }

        .view-mode-pill.active {
          background: var(--otis-primary, #0ea5e9);
          color: #fff;
          box-shadow: 0 0 8px rgba(14, 165, 233, 0.45);
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
          padding: 8px 12px 12px 12px;
          overflow: hidden;
          min-height: 440px;
          display: flex;
          justify-content: center;
          align-items: center;
          position: relative;
          box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.5);
          user-select: none;
        }

        .floorplan-svg-viewport.view-3d-active {
          touch-action: none;
          cursor: grab;
        }

        .floorplan-svg-viewport.view-3d-active:active {
          cursor: grabbing;
        }

        .floorplan-svg-viewport.editor-mode {
          background-image: radial-gradient(rgba(56, 189, 248, 0.15) 1px, transparent 1px);
          background-size: 24px 24px;
          border-color: var(--otis-primary);
        }

        .floorplan-svg-viewport .entity-badge {
          display: none !important;
        }

        .floorplan-svg-viewport svg .room-group,
        .floorplan-svg-viewport svg .room-feature,
        .floorplan-svg-viewport svg .room-feature * {
          pointer-events: all !important;
        }
        .floorplan-svg-viewport svg .room-feature:hover rect {
          stroke-width: 2 !important;
          filter: brightness(1.3);
        }
        .floorplan-svg-viewport svg .room-box,
        .floorplan-svg-viewport svg .room-rect,
        .floorplan-svg-viewport svg .room-polygon {
          cursor: pointer !important;
          pointer-events: auto !important;
        }

        .floorplan-svg-viewport svg .room-group:hover .room-box,
        .floorplan-svg-viewport svg .room-group:hover .room-rect,
        .floorplan-svg-viewport svg .room-group:hover .room-polygon,
        .floorplan-svg-viewport svg .room-box:hover,
        .floorplan-svg-viewport svg .room-rect:hover,
        .floorplan-svg-viewport svg .room-polygon:hover {
          fill-opacity: 1 !important;
          stroke: var(--otis-primary, #38bdf8) !important;
          filter: drop-shadow(0 0 14px var(--otis-primary, #38bdf8)) !important;
        }

        .floorplan-svg-viewport.view-3d-active svg .room-group:hover,
        .floorplan-svg-viewport.view-3d-active svg .room-box:hover,
        .floorplan-svg-viewport.view-3d-active svg .room-rect:hover,
        .floorplan-svg-viewport.view-3d-active svg .room-polygon:hover {
          cursor: pointer !important;
        }

        .floorplan-svg-viewport svg .plan-frame,
        .floorplan-svg-viewport svg .container-shell,
        .floorplan-svg-viewport svg .container-banner,
        .floorplan-svg-viewport svg .zone-title,
        .floorplan-svg-viewport svg .zone-subtitle,
        .floorplan-svg-viewport svg .subzone-pill,
        .floorplan-svg-viewport svg .door-cut,
        .floorplan-svg-viewport svg .door-leaf,
        .floorplan-svg-viewport svg .door-swing,
        .floorplan-svg-viewport svg .door-garage,
        .floorplan-svg-viewport svg .door-sliding,
        .floorplan-svg-viewport svg .window-cut,
        .floorplan-svg-viewport svg .window-sill,
        .floorplan-svg-viewport svg .window-pane,
        .floorplan-svg-viewport svg .window-cap {
          pointer-events: none !important;
        }

        /* 3D Stage & Canvas Projection */
        .floorplan-3d-stage {
          perspective: 1200px;
          perspective-origin: 50% 50%;
          transform-style: flat;
          pointer-events: none;
          width: 100%;
          height: 100%;
          min-height: 420px;
          display: flex;
          justify-content: center;
          align-items: center;
          position: relative;
          overflow: visible;
        }

        .floorplan-3d-canvas {
          position: relative;
          display: inline-block;
          max-width: 100%;
          max-height: 100%;
          transform-style: preserve-3d;
          transform-origin: 50% 50%;
          pointer-events: none;
          will-change: transform;
          transition: transform 0.08s ease-out;
        }

        /* 3D Raised Transparent Walls - Illuminated Architectural Glass */
        .floorplan-walls-overlay {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          pointer-events: none !important;
          z-index: 6;
          transform-style: preserve-3d;
          backface-visibility: visible;
          -webkit-backface-visibility: visible;
        }

        .floorplan-3d-room-shell {
          position: absolute;
          transform-style: preserve-3d;
          pointer-events: none !important;
          background: rgba(14, 165, 233, 0.04);
          transition: background 0.2s ease, opacity 0.2s ease;
          backface-visibility: visible;
          -webkit-backface-visibility: visible;
        }

        .floorplan-3d-wall {
          position: absolute;
          pointer-events: none !important;
          background: linear-gradient(to top, rgba(14, 165, 233, 0.15) 0%, rgba(56, 189, 248, 0.38) 60%, rgba(56, 189, 248, 0.75) 100%);
          border-left: 2px solid rgba(56, 189, 248, 0.85);
          border-right: 2px solid rgba(56, 189, 248, 0.85);
          box-shadow: 0 0 14px rgba(56, 189, 248, 0.45), inset 0 0 10px rgba(56, 189, 248, 0.25);
          transform-style: preserve-3d;
          backface-visibility: visible !important;
          -webkit-backface-visibility: visible !important;
          transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
        }

        .floorplan-3d-room-shell.is-hovered .floorplan-3d-wall,
        .floorplan-3d-room-shell:hover .floorplan-3d-wall,
        .floorplan-3d-wall:hover {
          background: linear-gradient(to top, rgba(56, 189, 248, 0.35) 0%, rgba(56, 189, 248, 0.70) 60%, rgba(56, 189, 248, 1.0) 100%) !important;
          border-color: #38bdf8 !important;
          box-shadow: 0 0 22px #38bdf8, inset 0 0 14px rgba(56, 189, 248, 0.5) !important;
        }

        .door-cut,
        .door-leaf,
        .door-swing,
        .door-garage,
        .door-sliding,
        .window-cut,
        .window-sill,
        .window-pane,
        .window-cap,
        .stairs-step {
          pointer-events: none !important;
        }

        .floorplan-3d-wall-north {
          top: 0;
          left: 0;
          width: 100%;
          height: var(--wall-height, 36px);
          transform-origin: top center;
          transform: rotateX(90deg);
          border-bottom: 3px solid #38bdf8;
          box-shadow: 0 0 14px #38bdf8;
        }

        .floorplan-3d-wall-south {
          bottom: 0;
          left: 0;
          width: 100%;
          height: var(--wall-height, 36px);
          transform-origin: bottom center;
          transform: rotateX(-90deg);
          border-top: 3px solid #38bdf8;
          box-shadow: 0 0 14px #38bdf8;
        }

        .floorplan-3d-wall-west {
          top: 0;
          left: 0;
          width: var(--wall-height, 36px);
          height: 100%;
          transform-origin: left center;
          transform: rotateY(-90deg);
          border-right: 3px solid #38bdf8;
          box-shadow: 0 0 14px #38bdf8;
        }

        .floorplan-3d-wall-east {
          top: 0;
          right: 0;
          width: var(--wall-height, 36px);
          height: 100%;
          transform-origin: right center;
          transform: rotateY(90deg);
          border-left: 3px solid #38bdf8;
          box-shadow: 0 0 14px #38bdf8;
        }

        .floorplan-3d-room-shell[data-zone="outdoor"] {
          display: none !important;
        }

        /* Contextual presence glow on room walls */
        .floorplan-3d-room-shell.is-occupied .floorplan-3d-wall {
          background: linear-gradient(to top, rgba(16, 185, 129, 0.20) 0%, rgba(52, 211, 153, 0.45) 60%, rgba(52, 211, 153, 0.85) 100%);
          border-left-color: rgba(52, 211, 153, 0.95);
          border-right-color: rgba(52, 211, 153, 0.95);
        }
        .floorplan-3d-room-shell.is-occupied .floorplan-3d-wall-north,
        .floorplan-3d-room-shell.is-occupied .floorplan-3d-wall-south {
          border-color: #34d399;
          box-shadow: 0 0 16px #34d399;
        }
        .floorplan-3d-room-shell.is-occupied .floorplan-3d-wall-west,
        .floorplan-3d-room-shell.is-occupied .floorplan-3d-wall-east {
          border-color: #34d399;
          box-shadow: 0 0 16px #34d399;
        }

        .floorplan-pins-overlay {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          pointer-events: none;
          z-index: 10;
          transform-style: preserve-3d;
        }

        .floorplan-device-pin {
          position: absolute;
          transform: translate3d(-50%, -50%, 14px) rotateZ(calc(-1 * var(--floorplan-azimuth, 0deg))) rotateX(calc(-1 * var(--floorplan-pitch, 0deg)));
          transform-origin: 50% 50%;
          transform-style: preserve-3d;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: transform 0.08s ease-out;
          z-index: 20;
          pointer-events: auto;
          width: 26px;
          height: 26px;
          --mdc-icon-size: 22px;
          color: #94a3b8;
          user-select: none;
        }

        .floorplan-device-pin:hover {
          transform: translate3d(-50%, -50%, 14px) rotateZ(calc(-1 * var(--floorplan-azimuth, 0deg))) rotateX(calc(-1 * var(--floorplan-pitch, 0deg))) scale(1.3);
          z-index: 35;
        }

        .floorplan-device-pin ha-state-icon {
          color: inherit !important;
          --paper-item-icon-color: currentColor !important;
          --state-icon-color: currentColor !important;
          transition: color 0.18s ease, filter 0.18s ease;
        }

        .floorplan-device-pin.is-active ha-state-icon {
          filter: drop-shadow(0 0 8px currentColor);
        }

        .floorplan-device-pin.is-draggable {
          cursor: grab !important;
        }

        .floorplan-device-pin.is-draggable:active {
          cursor: grabbing !important;
        }

        .floorplan-svg-viewport svg {
          width: 100%;
          height: 100%;
          filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.4));
          display: block;
          pointer-events: auto;
        }

        .floorplan-svg-viewport.view-3d-active svg {
          filter: none;
        }

        /* 3D Orbit & Pitch Controls HUD */
        .floorplan-3d-hud {
          position: absolute;
          top: 10px;
          right: 10px;
          z-index: 40;
          background: rgba(15, 23, 42, 0.88);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          border: 1px solid rgba(56, 189, 248, 0.35);
          border-radius: 10px;
          padding: 8px 12px;
          max-width: 380px;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.55);
          font-size: 0.74rem;
          color: var(--otis-text, #f1f5f9);
          user-select: none;
          pointer-events: auto;
          transition: all 0.2s ease;
        }

        .floorplan-3d-hud.collapsed {
          padding: 5px 10px;
        }

        .floorplan-3d-hud .hud-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }

        .floorplan-3d-hud .hud-title {
          font-weight: 700;
          color: var(--otis-primary, #38bdf8);
          font-size: 0.76rem;
        }

        .floorplan-3d-hud .hud-badge {
          background: rgba(56, 189, 248, 0.15);
          border: 1px solid rgba(56, 189, 248, 0.3);
          border-radius: 4px;
          padding: 1px 6px;
          font-size: 0.68rem;
          font-weight: 600;
          color: #93c5fd;
        }

        .floorplan-3d-hud .btn-hud-toggle {
          background: transparent;
          border: none;
          color: var(--otis-text-muted, #94a3b8);
          font-size: 0.76rem;
          cursor: pointer;
          padding: 2px 4px;
          border-radius: 4px;
        }

        .floorplan-3d-hud .btn-hud-toggle:hover {
          color: #fff;
          background: rgba(255, 255, 255, 0.1);
        }

        .floorplan-3d-hud .hud-body {
          margin-top: 8px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          border-top: 1px solid rgba(255, 255, 255, 0.08);
          padding-top: 6px;
        }

        .floorplan-3d-hud .hud-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }

        .floorplan-3d-hud .hud-label {
          color: var(--otis-text-muted, #94a3b8);
          font-size: 0.7rem;
          min-width: 82px;
        }

        .floorplan-3d-hud .hud-slider-wrap {
          display: flex;
          align-items: center;
          gap: 6px;
          flex: 1;
        }

        .floorplan-3d-hud .hud-slider {
          flex: 1;
          height: 4px;
          background: rgba(255, 255, 255, 0.15);
          border-radius: 2px;
          outline: none;
          -webkit-appearance: none;
          appearance: none;
        }

        .floorplan-3d-hud .hud-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 13px;
          height: 13px;
          border-radius: 50%;
          background: var(--otis-primary, #38bdf8);
          cursor: pointer;
          box-shadow: 0 0 6px rgba(56, 189, 248, 0.6);
        }

        .floorplan-3d-hud .btn-hud-step {
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: #cbd5e1;
          font-size: 0.68rem;
          border-radius: 4px;
          padding: 2px 6px;
          cursor: pointer;
          transition: all 0.15s;
        }

        .floorplan-3d-hud .btn-hud-step:hover {
          background: rgba(56, 189, 248, 0.25);
          border-color: rgba(56, 189, 248, 0.45);
          color: #fff;
        }

        .floorplan-3d-hud .hud-val {
          font-variant-numeric: tabular-nums;
          font-size: 0.7rem;
          min-width: 32px;
          text-align: right;
          color: #e2e8f0;
          font-weight: 600;
        }

        .floorplan-3d-hud .presets-row {
          align-items: flex-start;
          margin-top: 2px;
        }

        .floorplan-3d-hud .hud-presets-wrap {
          display: flex;
          flex-wrap: wrap;
          gap: 3px;
          flex: 1;
        }

        .floorplan-3d-hud .btn-preset-pill {
          background: rgba(15, 23, 42, 0.7);
          border: 1px solid rgba(255, 255, 255, 0.12);
          color: #94a3b8;
          font-size: 0.65rem;
          padding: 2px 5px;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.15s;
        }

        .floorplan-3d-hud .btn-preset-pill:hover {
          color: #fff;
          border-color: rgba(56, 189, 248, 0.4);
        }

        .floorplan-3d-hud .btn-preset-pill.active {
          background: rgba(56, 189, 248, 0.2);
          border-color: var(--otis-primary, #38bdf8);
          color: #fff;
          font-weight: 700;
        }

        .floorplan-3d-hud .btn-preset-reset {
          background: rgba(168, 85, 247, 0.15);
          border: 1px solid rgba(168, 85, 247, 0.35);
          color: #c084fc;
          font-size: 0.65rem;
          padding: 2px 6px;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.15s;
          margin-left: auto;
        }

        .floorplan-3d-hud .btn-preset-reset:hover {
          background: rgba(168, 85, 247, 0.3);
          color: #fff;
        }

        .floorplan-3d-hud .hud-hint {
          font-size: 0.64rem;
          color: var(--otis-text-muted, #94a3b8);
          text-align: center;
          margin-top: 4px;
          font-style: italic;
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

        /* Modals & Dialogs (Full-Viewport Floating Overlays) */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          width: 100vw;
          height: 100vh;
          background: rgba(0, 0, 0, 0.75);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          display: flex;
          justify-content: center;
          align-items: center;
          z-index: 99999;
          padding: 24px;
          box-sizing: border-box;
          overflow-y: auto;
        }

        .modal-card {
          background: var(--otis-bg, #0f172a);
          border: 1px solid var(--otis-primary);
          box-shadow: 0 16px 48px rgba(0, 0, 0, 0.75), 0 0 28px rgba(14, 165, 233, 0.25);
          border-radius: 16px;
          width: 100%;
          max-width: 520px;
          max-height: calc(100vh - 48px);
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 20px;
          position: relative;
          color: var(--otis-text, #f8fafc);
          box-sizing: border-box;
          margin: auto;
        }

        @media (max-width: 600px) {
          .modal-overlay {
            padding: 12px;
          }
          .modal-card {
            max-height: calc(100vh - 24px);
            padding: 16px;
          }
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

        /* Phase 8: Multi-Modal Vision & Presence Studio Styles */
        .vision-panel {
          display: flex;
          flex-direction: column;
          gap: 16px;
          margin-top: 14px;
        }

        .vision-overview-card {
          background: color-mix(in srgb, var(--otis-surface) 90%, transparent);
          border: 1px solid var(--otis-surface-border);
          border-radius: 14px;
          padding: 14px 18px;
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .vision-stats-row {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
        }

        .vision-stat-chip {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.76rem;
          font-weight: 600;
          padding: 4px 10px;
          border-radius: 8px;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.1);
        }

        .vision-stat-chip.occupied {
          background: rgba(16, 185, 129, 0.15);
          border-color: rgba(16, 185, 129, 0.4);
          color: #34d399;
        }

        .vision-stat-chip.micro_presence {
          background: rgba(168, 85, 247, 0.15);
          border-color: rgba(168, 85, 247, 0.4);
          color: #c084fc;
        }

        .vision-stat-chip.likely {
          background: rgba(245, 158, 11, 0.15);
          border-color: rgba(245, 158, 11, 0.4);
          color: #fbbf24;
        }

        .vision-stat-chip.vacant {
          color: var(--otis-text-muted);
        }

        .vision-section-title {
          font-size: 0.88rem;
          font-weight: 700;
          color: var(--otis-text);
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 6px;
        }

        .presence-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 12px;
        }

        .presence-card {
          background: color-mix(in srgb, var(--otis-surface) 80%, transparent);
          border: 1px solid var(--otis-surface-border);
          border-radius: 12px;
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          transition: transform 0.15s ease, border-color 0.15s ease;
        }

        .presence-card:hover {
          transform: translateY(-2px);
          border-color: var(--otis-primary);
        }

        .presence-card-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .presence-room-name {
          font-weight: 700;
          font-size: 0.85rem;
          color: var(--otis-text);
        }

        .presence-badge {
          font-size: 0.68rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          padding: 2px 8px;
          border-radius: 6px;
        }

        .presence-badge.occupied {
          background: rgba(16, 185, 129, 0.2);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.4);
        }

        .presence-badge.micro_presence {
          background: rgba(168, 85, 247, 0.25);
          color: #c084fc;
          border: 1px solid rgba(168, 85, 247, 0.5);
          box-shadow: 0 0 8px rgba(168, 85, 247, 0.3);
        }

        .presence-badge.likely_occupied {
          background: rgba(245, 158, 11, 0.2);
          color: #fbbf24;
          border: 1px solid rgba(245, 158, 11, 0.4);
        }

        .presence-badge.vacant {
          background: rgba(255, 255, 255, 0.05);
          color: var(--otis-text-muted);
          border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .presence-bar-track {
          width: 100%;
          height: 6px;
          background: rgba(255, 255, 255, 0.08);
          border-radius: 4px;
          overflow: hidden;
        }

        .presence-bar-fill {
          height: 100%;
          border-radius: 4px;
          transition: width 0.3s ease;
        }

        .presence-bar-fill.occupied {
          background: linear-gradient(90deg, #10b981, #059669);
          box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
        }

        .presence-bar-fill.micro_presence {
          background: linear-gradient(90deg, #a855f7, #7c3aed);
          box-shadow: 0 0 10px rgba(168, 85, 247, 0.5);
        }

        .presence-bar-fill.likely_occupied {
          background: linear-gradient(90deg, #f59e0b, #d97706);
        }

        .presence-bar-fill.vacant {
          background: rgba(255, 255, 255, 0.2);
        }

        .presence-sensors-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          font-size: 0.70rem;
        }

        .presence-sensor-pill {
          padding: 2px 6px;
          border-radius: 4px;
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid rgba(255, 255, 255, 0.08);
          color: var(--otis-text-muted);
        }

        .presence-sensor-pill.active {
          background: rgba(14, 165, 233, 0.15);
          border-color: rgba(14, 165, 233, 0.4);
          color: #38bdf8;
          font-weight: 600;
        }

        .camera-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 14px;
        }

        .camera-card {
          background: color-mix(in srgb, var(--otis-surface) 85%, transparent);
          border: 1px solid var(--otis-surface-border);
          border-radius: 14px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .camera-preview-container {
          position: relative;
          width: 100%;
          height: 180px;
          background: #090d16;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
        }

        .camera-preview-img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .camera-cam-badge {
          position: absolute;
          top: 8px;
          left: 8px;
          background: rgba(0, 0, 0, 0.65);
          backdrop-filter: blur(4px);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #ffffff;
          padding: 2px 8px;
          border-radius: 6px;
          font-size: 0.70rem;
          font-weight: 600;
        }

        .camera-card-body {
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .camera-card-title {
          font-weight: 700;
          font-size: 0.85rem;
          color: var(--otis-text);
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .btn-analyze-camera {
          background: linear-gradient(135deg, var(--otis-primary), color-mix(in srgb, var(--otis-primary) 70%, #9333ea));
          color: var(--otis-btn-text, #ffffff);
          border: none;
          border-radius: 8px;
          padding: 6px 12px;
          font-size: 0.76rem;
          font-weight: 600;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: filter 0.15s ease;
        }

        .btn-analyze-camera:hover:not(:disabled) {
          filter: brightness(1.15);
        }

        .btn-analyze-camera:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .vision-audit-result {
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 8px;
          padding: 8px 10px;
          font-size: 0.74rem;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .tag-pill {
          display: inline-block;
          padding: 1px 6px;
          border-radius: 4px;
          font-size: 0.68rem;
          font-weight: 600;
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: var(--otis-text);
        }

        /* Compact Embedded Media Studio (Tablet / Kitchen) */
        .mode-compact.mode-media-studio {
          padding: 10px 12px !important;
        }
        .mode-compact.mode-media-studio .studio-header {
          padding: 0 0 8px 0 !important;
          margin-bottom: 8px !important;
          min-height: 0 !important;
        }
        .mode-compact.mode-media-studio .studio-header .main-title {
          font-size: 0.95rem !important;
        }
        .mode-compact.mode-media-studio .media-studio-wrapper {
          gap: 10px !important;
        }
        .mode-compact.mode-media-studio .media-studio-wrapper > div {
          padding: 10px !important;
          border-radius: 12px !important;
        }
        .mode-compact.mode-media-studio .btn-media-transport {
          padding: 4px 10px !important;
          font-size: 0.8rem !important;
        }
        .mode-compact.mode-media-studio .media-fav-card {
          padding: 6px 8px !important;
        }
        .mode-compact.mode-media-studio .subview-chip {
          padding: 3px 8px !important;
          font-size: 0.7rem !important;
        }
        .compact-media-tabs {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 4px;
          padding: 4px;
          border-radius: 10px;
          background: rgba(0, 0, 0, 0.28);
          border: 1px solid var(--otis-surface-border);
        }
        .compact-media-tab {
          background: transparent;
          border: 1px solid transparent;
          color: var(--otis-text-muted);
          border-radius: 7px;
          padding: 6px 4px;
          font-size: 0.72rem;
          font-weight: 600;
          cursor: pointer;
          text-align: center;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          transition: all 0.15s ease;
        }
        .compact-media-tab.active {
          background: rgba(56, 189, 248, 0.18);
          border-color: rgba(56, 189, 248, 0.45);
          color: var(--otis-primary);
          font-weight: 700;
        }
        .compact-media-tab-panel {
          max-height: 365px;
          overflow-y: auto;
        }
        select option {
          background: var(--otis-card-bg, #0f172a);
          color: var(--otis-text, #f1f5f9);
        }
`;
