# Behavioral Signals API Contract


## 1. Request Payload (JSON Structure)

```json
{
  "user_id": "usr_10293",
  "session_id": "sess_88392",
  "session_start": 1694123000000,
  "session_end": 1694124500000,
  "sections": [
    {
      "section_id": "S003",
      "concept_id": "C008",
      "section_start_time": 1694123456789,
      "section_end_time": 1694123501789,
      "time_spent_seconds": 45.0,
      "reading_speed_wpm": 180.5,
      "scroll_speed_avg_px_per_sec": 220.0,
      "scroll_direction_changes": 3,
      "content_progression_pct": 90.0,
      "section_revisit_count": 2,
      "interaction_count": 5,
      "micro_challenges": [
        {
          "question_id": "Q12",
          "response_time_seconds": 12.0,
          "is_correct": false
        }
      ],
      "background_count": 1,
      "total_background_seconds": 8.0,
      "tab_hidden_count": 0
    }
  ]
}


```
## 2. Data Dictionary
## 1. Top-Level Object (`SessionPayload`)
 
| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | Yes | Unique identifier of the learner |
| `session_id` | string | Yes | Unique identifier of this learning session |
| `session_start` | integer (unix ms) | Yes | Timestamp when the session began |
| `session_end` | integer (unix ms) | Yes | Timestamp when the session ended |
| `sections` | array of `Section` | Yes | List of all sections visited during the session (see §3). Can contain duplicate `section_id` if the user re-entered a section — see `section_revisit_count` |
 
---
 
## 2. `Section` Object
 
Represents one continuous or aggregated visit record for a content section within the session.
 
| Field | Type | Required | Unit / Range | Description |
|---|---|---|---|---|
| `section_id` | string | Yes | — | Identifier of the content section |
| `concept_id` | string | Yes | — | Identifier of the learning concept this section belongs to (used for adaptive decisions downstream) |
| `section_start_time` | integer (unix ms) | Yes | — | First entry timestamp into this section |
| `section_end_time` | integer (unix ms) | Yes | — | Last exit timestamp from this section |
| `time_spent_seconds` | float | Yes | seconds, ≥ 0 | Total accumulated time spent in this section (sum across all visits, not just last one) |
| `reading_speed_wpm` | float | Yes | words/minute, ≥ 0 | Average reading speed = (words read ÷ time spent in minutes) |
| `scroll_speed_avg_px_per_sec` | float | Yes | pixels/second, ≥ 0 | Average scroll velocity across the section. **Raw number, not a label** |
| `scroll_direction_changes` | integer | Yes | count, ≥ 0 | Number of times scroll direction flipped (down→up or up→down). Used to detect erratic/hesitant scrolling |
| `content_progression_pct` | float | Yes | 0–100 | Max scroll/content depth reached in the section |
| `section_revisit_count` | integer | Yes | count, ≥ 0 | Number of times the user re-entered this section after leaving it once |
| `interaction_count` | integer | Yes | count, ≥ 0 | Total discrete interactions (taps, highlights, notes, etc.) during the section |
| `micro_challenges` | array of `MicroChallenge` | No | — | List of micro-challenge (MCQ) attempts tied to this section. Can be empty if no challenge was shown |
| `background_count` | integer | Yes | count, ≥ 0 | Number of times the app went to background while in this section |
| `total_background_seconds` | float | Yes | seconds, ≥ 0 | Total time app spent in background while in this section |
| `tab_hidden_count` | integer | No | count, ≥ 0 | Number of times the browser tab became hidden (web only — omit or 0 on mobile) |
 
---
 
## 3. `MicroChallenge` Object
 
| Field | Type | Required | Unit / Range | Description |
|---|---|---|---|---|
| `question_id` | string | Yes | — | Identifier of the micro-challenge question |
| `response_time_seconds` | float | Yes | seconds, ≥ 0 | Time taken from question shown to answer submitted |
| `is_correct` | boolean | Yes | true/false | Whether the answer was correct |
 