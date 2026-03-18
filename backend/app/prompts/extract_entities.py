# backend/app/prompts/extract_entities.py

WORLDVIEW_PROMPT = """
You are extracting structured world-building knowledge.

Extract:

- world rules
- organizations
- locations
- environmental constraints

Return JSON strictly matching ExtractionResult schema.
"""


SETTINGS_PROMPT = """
You are extracting character settings.

Extract:

- characters
- traits
- relationships
- emotions
- goals/motivations
- owned items

Return JSON strictly matching ExtractionResult schema.
"""


SCENARIO_PROMPT = """
You are extracting screenplay events.

Extract:

- events
- dialogue information flow
- who learns what
- mentions
- lies
- item transfers
- location changes

Return JSON strictly matching ExtractionResult schema.
"""