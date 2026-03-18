from app.models.vertices import Character
from app.models.enums import CharacterTier

char = Character(
    source_id="source-123",
    name="Test Character",
    aliases=["Tester", "Test"],
    tier=CharacterTier.TIER_1,
    description="A test character for system check"
)

print(char.model_dump_json(indent=2))
print(f"Partition key is: {char.partition_key}")
