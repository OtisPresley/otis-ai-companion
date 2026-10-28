# 🗺️ Spatial Topology & Vector Floor Plan Engine

Otis AI Companion includes a topological spatial engine and a multimodal video walkthrough pipeline that turns smartphone video into an architectural, interactive vector SVG floor plan.

---

## 🧭 Spatial Adjacency Graph

Traditional smart home platforms treat rooms as isolated metadata tags. Otis AI models your home as an **undirected adjacency graph** where nodes represent physical areas and edges represent physical pathways (doors, open transitions, hallways, staircases).

<p align="center">
  <img alt="Spatial Adjacency Graph" src="https://raw.githubusercontent.com/wiki/OtisPresley/otis-ai-companion/images/spatial-adjacency-graph.png" width="850" />
</p>

### Key Graph Capabilities:
* **Breadth-First Search (BFS) Pathfinding**: Determines the exact transit path between any two rooms in your home.
* **Contextual Pathway Lighting**: If presence is detected in the `Foyer` and the next intended destination is the `Kitchen`, Otis can illuminate the connecting `Hallway` low-intensity courtesy lights automatically.
* **Spatial Services**:
  - `otis_ai.get_spatial_map`: Retrieves all registered room nodes, transition types, and connection pairs.
  - `otis_ai.update_spatial_map`: Connects or disconnects rooms programmatically.

---

## 🎥 Walkthrough Video-to-FloorPlan Pipeline

Instead of manually drawing SVG vectors or aligning complex CAD files, Otis AI creates your floor plan through multimodal video analysis:

<p align="center">
  <img alt="Walkthrough Video-to-FloorPlan Pipeline" src="https://raw.githubusercontent.com/wiki/OtisPresley/otis-ai-companion/images/walkthrough-pipeline.png" width="850" />
</p>

---

## 📱 How to Record Your Walkthrough

To ensure high-accuracy layout synthesis:

1. **Continuous Video**: Record a continuous, steady video walking through your home. (You can also select and upload multiple video clips in a single batch).
2. **Call Out Room Names**: As you cross doorways or transition zones, speak the room name clearly out loud (e.g. *"Entering the Foyer... moving into the Kitchen... stepping out to the Backyard Deck"*).
3. **Pacing**: Walk at a natural, steady pace. Pause for 1–2 seconds at central room thresholds.
4. **Supported Formats**: `.mp4`, `.mov`, `.webm`.

---

## 📤 Uploading Walkthrough Videos

1. Open the **Otis AI** dashboard at `/otis-ai` (or your custom card).
2. Switch to the **Floor Plan** tab.
3. If no walkthrough has been processed, click **Upload Walkthrough**.
4. Drag and drop your video file(s) into the modal window.

<!-- IMAGE PLACEHOLDER: [Walkthrough video upload modal showing drag-and-drop video dropzone and spoken room sequence override field] -->

5. *(Optional)* Provide a spoken room order override if you wish to enforce an explicit sequence.
6. Click **Process Walkthrough**.
7. Live progress badges indicate:
   - `Uploading video batch...`
   - `Extracting audio with FFmpeg...`
   - `Transcribing room transitions with Gemini...`
   - `Generating contiguous vector SVG...`
   - `Floor plan updated successfully!`

<!-- IMAGE PLACEHOLDER: [Live processing badges displaying progress through video upload, FFmpeg extraction, Gemini transcription, and SVG compilation] -->

> [!TIP]
> **Disk Space Conservation**  
> Otis AI automatically purges uploaded video and intermediate audio files from `/config/www/` once transcription and SVG compilation are completed, keeping your storage clean.

---

## 📐 Architectural SVG Layout Engine

The floor plan layout engine organizes your home into unified, contiguous architectural zones:

### 1. Ground / Main Floor & Open-Concept Great Room
* **Great Room Architecture**: Models modern open floor plans by grouping the **Living Area**, **Kitchen**, and **Breakfast Nook** inside a single shared architectural boundary with interior partition cuts rather than isolated boxes.
* **Shared Walls**: Adjacent rooms snap to shared boundary walls, preserving physical door cuts and room scale.

### 2. Multi-Floor Views & Staircase Markers
* **Upper Level Suites**: Secondary floor bedrooms, guest suites, offices, and bonus rooms render in an aligned, secondary zone with directional staircase links (`Back Stairs UP ↗ / DN ↙`).
* **Floor Plan Tabs**: The Lovelace viewer lets you isolate views using zone pills:
  - `All Floors`
  - `Ground & Outdoor`
  - `Upper Level`
  - `Outdoor Only`

### 3. Outdoor & Perimeter Zone
* **Driveway & Front Entry**: Aligns with front perimeter access points.
* **Backyard Deck, Patio & Pool**: Stylized water basin styling for pools and spas with perimeter lighting badges.

---

## 🎛️ Interactive SVG & Lovelace YAML Export

<!-- IMAGE PLACEHOLDER: [Interactive vector SVG floor plan rendered in Lovelace, showing glowing clickable room light badges, boundary outlines, and zone selection pills] -->

The generated SVG is fully interactive:
* **Interactive Badges**: Light and switch entities rendered as clickable glowing badges. Tapping a badge toggles the physical entity immediately.
* **Room Inspection Drawers**: Clicking any room boundary opens an inspection drawer showing all active devices, sensors, temperature readings, and occupancy states for that area.

<!-- IMAGE PLACEHOLDER: [Room inspection drawer open after clicking an architectural room boundary, showing live temperature, occupancy sensors, and light switches] -->

* **Copy Lovelace YAML**: Click the **Lovelace YAML** button in the card toolbar to copy a ready-to-paste `picture-elements` card definition for any custom dashboard.
