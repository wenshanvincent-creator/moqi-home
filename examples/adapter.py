"""Minimal synthetic adapter example: no HA, tokens, or physical devices."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from moqi import HomeMemory, Observation

config = {'site': 'SYNTHETIC-ADAPTER', 'timezone': 'Asia/Shanghai', 'entities': {
    'switch.lamp': {'role': 'actuator', 'room': 'dining', 'risk': 'low', 'category': 'light'}}}
output = Path('data/adapter-example')
output.mkdir(parents=True, exist_ok=False)  # Never mix an example into real data.
at = datetime(2026, 3, 2, 10, tzinfo=timezone.utc)
with HomeMemory(config, str(output/'events.sqlite3')) as memory:
    memory.ingest(Observation('switch.lamp', at, 'off'))
    memory.ingest(Observation('switch.lamp', at+timedelta(minutes=5), 'on', 'off',
                              source='human', evidence='Synthetic example button event'))
    memory.observe_interval(at, at+timedelta(minutes=30))
    memory.learn(at+timedelta(minutes=31))
    print(memory.inspect(at+timedelta(minutes=31))['habits'])  # One example is not a habit.
