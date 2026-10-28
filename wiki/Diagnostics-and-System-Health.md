# 🛡️ Diagnostics, System Health & Maturity Scoring

Otis AI Companion includes an autonomous system diagnostics engine that calculates a comprehensive **Smart Home Maturity Score**, enforces **pre-flight safety gates**, and monitors system health to protect against bootloops and database corruption.

---

## 📊 Smart Home Maturity Score (0–100)

The **Smart Home Maturity Score** measures how well-architected, unified, and resilient your Home Assistant installation is. It evaluates 5 core dimensions, each weighted equally:

```
[ SMART HOME MATURITY SCORE: 94 / 100 ]
┌───────────────────────────┬───────┬────────────────────────────────────────┐
│ Dimension                 │ Score │ Key Metrics Evaluated                  │
├───────────────────────────┼───────┼────────────────────────────────────────┤
│ 🗺️ Spatial Architecture    │ 20/20 │ Areas mapped, zero unassigned devices, │
│                           │       │ floor registry linked, spatial graph.  │
│ 🧹 Entity & Log Hygiene   │ 18/20 │ Zero orphaned entities, clean naming,  │
│                           │       │ recorder batch commit optimizations.   │
│ 🔄 Automation Quality     │ 19/20 │ Queued modes, zero broken entity refs, │
│                           │       │ no template errors, habit routines.    │
│ 🔒 Security & Presence    │ 19/20 │ Alarmo perimeter, lock/garage sync,    │
│                           │       │ bedtime arming, away detection.        │
│ 🔊 Media & Audio Topology │ 18/20 │ Presence speaker routing, matrix idle  │
│                           │       │ guards, cinema coordination.           │
└───────────────────────────┴───────┴────────────────────────────────────────┘
```

### 1-Click Area Auto-Assignment (`auto_assign_areas`)
When unassigned devices or entities are discovered, Otis AI uses entity name tokens and parent device relationships to propose 1-click area assignments, instantly boosting your Spatial Maturity score.

---

## 🧹 Orphan Entity Detection & Safe Cleanup

Over time, adding and removing integrations, blueprints, or testing devices leaves orphaned entity records in Home Assistant's Entity Registry (`core.entity_registry`):

### How Otis AI Identifies True Orphans:
* **Registration Check**: The entity exists in `core.entity_registry`, but its platform or integration is no longer active in Home Assistant.
* **State Check**: The entity reports `restored: true` or has no underlying device state.
* **Safety Protection**:
  > [!IMPORTANT]
  > **Offline Device Protection**  
  > Entities tied to an active, installed integration (`config_entry_id`) are **strictly protected** and never flagged as orphans, even if the physical device is temporarily powered off, sleeping (battery devices), or in setup retry.

### 1-Click Cleanup:
Orphaned entities appear in the Proactive Feed with a single **Clean Up Orphans** button (`action_type: "cleanup_orphans"`), which purges invalid registry entries cleanly without needing manual JSON edits.

---

## 🛡️ Pre-Flight Health Gates & Safe Upgrades

Before performing updates, modifying YAML files, or running heavy maintenance jobs, Otis AI runs automated safety checks:

### 1. Disk Space Verification
* Checks available free disk space on the primary volume.
* Enforces a minimum **10 GB** threshold. If storage is constrained, upgrade actions and floor plan video uploads are blocked with clear warnings.

### 2. SQLite Database Integrity & Lock Auditing
* Scans `home-assistant_v2.db` for uncommitted table locks, WAL journal backlog, or corrupted index nodes.
* Protects against running operations during heavy database compaction or migrations.

### 3. Backup Provider Detection
* Verifies that pre-upgrade backups are active. Automatically recognizes:
  - Native Home Assistant backup configuration in `.storage/backup`.
  - Cloud and remote backup integrations: `pcloud_backup`, `google_drive_backup`, `samba_backup`, `auto_backup`, `onedrive`.

### 4. Supervisor Safe Rollback & Bootloop Watchdog
* When updates are applied, Otis AI monitors Home Assistant startup logs for 5 minutes.
* If a fatal bootloop or critical component crash is detected, the integration can trigger an emergency rollback to the latest pre-flight backup snapshot.
