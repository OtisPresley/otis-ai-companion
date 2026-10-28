# 🏷️ Services Reference Guide

This page is the definitive technical reference for all services registered by **Otis AI Companion** in Home Assistant (`services.yaml`).

---

## 📋 Service Summary

| Service Name | Description | Response Data |
| :--- | :--- | :--- |
| `otis_ai.chat` | Query the conversational smart home co-pilot with spatial context. | Returns assistant response text and session ID. |
| `otis_ai.get_capability_map` | Retrieve the complete system capability map, maturity score, and suggestions. | Returns structured system capability dictionary. |
| `otis_ai.get_suggestions` | Retrieve currently pending proactive recommendations. | Returns array of suggestion items. |
| `otis_ai.apply_suggestion` | Atomically execute a proactive recommendation (e.g., write automation or clean orphans). | Returns execution status. |
| `otis_ai.get_spatial_map` | Retrieve the spatial adjacency topology graph of all rooms and connections. | Returns graph nodes, edges, and transition types. |
| `otis_ai.update_spatial_map` | Connect or disconnect two physical rooms in the spatial topology. | None. |
| `otis_ai.generate_floorplan` | Synthesize an interactive vector SVG floor plan from spatial graph and walkthrough video. | Returns path to generated SVG and card YAML. |

---

## 1. Service: `otis_ai.chat`

Direct conversation interface with Otis AI, featuring active spatial topology context injection and LLM failover.

### Parameters:
* `text` *(string, required)*: The user sentence or query to evaluate.
* `conversation_id` *(string, optional)*: Session identifier for multi-turn conversational memory.

### YAML Example:
```yaml
action: otis_ai.chat
data:
  text: "What rooms are currently occupied, and are any exterior doors unlocked?"
  conversation_id: "living_room_tablet_session"
```

---

## 2. Service: `otis_ai.get_capability_map`

Generates a complete snapshot of your Home Assistant system: active areas, controllable actuator counts, orphan entities, Smart Home Maturity Score, and proactive recommendations.

### YAML Example:
```yaml
action: otis_ai.get_capability_map
response_variable: otis_capabilities
```

---

## 3. Service: `otis_ai.get_suggestions`

Retrieves all active proactive recommendations discovered by the background engine.

### YAML Example:
```yaml
action: otis_ai.get_suggestions
response_variable: pending_suggestions
```

---

## 4. Service: `otis_ai.apply_suggestion`

Executes a recommendation discovered by Otis AI. This performs atomic file modification (with timestamped pre-flight backup) and triggers dynamic configuration reloads.

### Parameters:
* `suggestion_id` *(string, required)*: The unique ID string of the suggestion (found in the suggestion payload or card feed).

### YAML Example:
```yaml
action: otis_ai.apply_suggestion
data:
  suggestion_id: "habit_morning_coffee_routine"
```

---

## 5. Service: `otis_ai.get_spatial_map`

Returns the active physical room adjacency topology graph, including all room nodes, edge connections, and transition types (`door`, `open`, `hallway`, `stairs`).

### YAML Example:
```yaml
action: otis_ai.get_spatial_map
response_variable: spatial_graph
```

---

## 6. Service: `otis_ai.update_spatial_map`

Creates or removes a physical connection between two rooms in your home.

### Parameters:
* `area_1` *(string, required)*: First room ID or name (e.g. `'foyer'`).
* `area_2` *(string, required)*: Second room ID or name (e.g. `'great_room'`).
* `connected` *(boolean, default: `true`)*: Whether the areas are connected.
* `connection_type` *(select: `door`, `open`, `hallway`, `stairs`, default: `open`)*: Physical transition type.

### YAML Example:
```yaml
action: otis_ai.update_spatial_map
data:
  area_1: "foyer"
  area_2: "study"
  connected: true
  connection_type: "door"
```

---

## 7. Service: `otis_ai.generate_floorplan`

Triggers vector SVG floor plan compilation using your spatial adjacency graph, floor registry, and processed walkthrough video data.

### Parameters:
* `theme` *(select: `cyberpunk`, `blueprint`, `emerald`, default: `cyberpunk`)*: Visual color aesthetic for the floor plan.
* `output_path` *(string, default: `'www/otis_floorplan.svg'`)*: Destination path relative to Home Assistant `/config`.
* `video_path` *(string, optional)*: Path to an uploaded walkthrough video to extract room callouts.

### YAML Example:
```yaml
action: otis_ai.generate_floorplan
data:
  theme: "blueprint"
  output_path: "www/otis_floorplan.svg"
```
