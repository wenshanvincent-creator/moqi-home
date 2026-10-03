"""Create synthetic verified evidence and coverage, never mix with a household DB."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import Store, normalize
from .memory import predict, reflect, consolidate


def build(directory):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=False)
    config = dict(site='SYNTHETIC-DEMO', timezone='Asia/Shanghai', holidays=[],
                  database=str(folder/'demo.sqlite3'), memory_directory=str(folder/'memory'),
                  ha_url='http://127.0.0.1:8123', entities={
                      'switch.dining_lamp':dict(role='actuator',room='dining_room'),
                      'binary_sensor.dining_motion':dict(role='motion',room='dining_room'),
                      'person.synthetic_home':dict(role='presence',room='home',boundary='home',feature='mobile_home')})
    store = Store(config['database'])
    def add(at, before, after, source=None):
        row = normalize(dict(event_type='state_changed',time_fired=at.isoformat(),data=dict(
            entity_id='switch.dining_lamp',old_state=None if before is None else dict(state=before),
            new_state=dict(state=after,context=dict(id=at.isoformat())))),config)
        store.add(row)
        if source:
            store.annotate(row['event_key'],source,'Synthetic demonstration evidence; not a real household')
    def home(at,before,after):
        store.add(normalize(dict(event_type='state_changed',time_fired=at.isoformat(),data=dict(
            entity_id='person.synthetic_home',old_state=None if before is None else dict(state=before),
            new_state=dict(state=after))),config))
    try:
        start = datetime.now(timezone.utc).replace(hour=2,minute=0,second=0,microsecond=0)
        for i in range(1,12):
            day = start - timedelta(days=i)
            if day.weekday() >= 5:
                continue
            home(day-timedelta(minutes=2),None,'not_home')
            home(day,'not_home','home')
            add(day,None,'off')
            add(day+timedelta(minutes=5),'off','on','human')
            add(day+timedelta(minutes=20),'on','off','device')
            home(day+timedelta(minutes=30),'home','not_home')
            with store.db:
                store.db.execute('INSERT INTO sessions(started_at,ended_at,status) VALUES (?,?,?)',
                                 (day.isoformat(),(day+timedelta(minutes=30)).isoformat(),'synthetic'))
        # Latest weekday time context for a historical prediction, without future evidence.
        at = start
        while at.weekday() >= 5:
            at -= timedelta(days=1)
        add(at,None,'off')
        consolidate(store,config,at)
        predict(store,config,at)
        reflect(store,config,start+timedelta(hours=1),config['memory_directory'])
    finally:
        store.close()
    (folder/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print(f'Synthetic demo prepared. Run: python -m moqi.cli --config {folder}/config.json serve')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/system-demo')
    build(parser.parse_args().output)
