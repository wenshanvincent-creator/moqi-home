import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .core import Store, normalize
from .ha import collect
from .memory import dt, predict, reflect, due, snapshot


def main():
    parser = argparse.ArgumentParser(description="Moqi structured memory and shadow decisions")
    parser.add_argument("--config", default="config.local.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect")
    commands.add_parser("run")
    commands.add_parser('memory-status')
    commands.add_parser('memory-history')
    commands.add_parser('weekly-summary')
    commands.add_parser('decide')
    undo = commands.add_parser('memory-rollback')
    undo.add_argument('revision')
    proposed = commands.add_parser('hypothesis')
    proposed.add_argument('input')
    constraint_cmd = commands.add_parser('constraint')
    constraint_cmd.add_argument('entity')
    constraint_cmd.add_argument('--deny',nargs='+',required=True)
    constraint_cmd.add_argument('--scope',choices=['always','night'],default='always')
    constraint_cmd.add_argument('--reason',required=True)
    constraint_cmd.add_argument('--source',choices=['app','voice'],default='app')
    annotate = commands.add_parser('annotate')
    annotate.add_argument('event_key')
    annotate.add_argument('--source', choices=['human','device','unknown'], required=True)
    annotate.add_argument('--reason', required=True)
    for name in ('predict', 'reflect'):
        cmd = commands.add_parser(name)
        cmd.add_argument('--at', help='Timezone-aware timestamp; defaults to current UTC')
    dashboard = commands.add_parser('serve')
    dashboard.add_argument('--port', type=int, default=8877)
    html = commands.add_parser('dashboard-export')
    html.add_argument('output')
    replay = commands.add_parser("replay")
    replay.add_argument("input")
    export = commands.add_parser("export")
    export.add_argument("output")
    commands.add_parser("status")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    if not config.get("site") or not config.get("entities"):
        parser.error("Configure site and a nonempty entities allowlist")
    for spec in config["entities"].values():
        if spec.get("role") not in {"motion", "contact", "leak", "actuator", "power", "energy", "temperature", "presence", "light", "co2", "sleep"} or not spec.get("room"):
            parser.error("Each entity needs a supported role and room")
    store = Store(config["database"])
    try:
        if args.command in {'memory-status','memory-history','memory-rollback','constraint','weekly-summary','hypothesis','decide'}:
            from .memory_store import history,rollback,commit
            from .understanding import constraint,weekly_summary,proposal,write_understanding
            from .decision import decide
            now=datetime.now(timezone.utc)
            directory=config.get('memory_directory','data/memory')
            if args.command=='memory-status': result=snapshot(store,config,now)
            elif args.command=='memory-history': result=history(directory)
            elif args.command=='weekly-summary': result=weekly_summary(store,config,now)
            elif args.command=='hypothesis': result=proposal(store,json.loads(Path(args.input).read_text(encoding='utf-8-sig')),now)
            elif args.command=='decide': result=decide(store,config,now)
            elif args.command=='constraint':
                result=constraint(store,config,args.entity,args.deny,args.scope,args.reason,args.source,now)
                write_understanding(store,config,now,directory,import_edits=False)
                commit(store,directory,now.isoformat(),'Explicit household constraint')
            else:
                backup=rollback(store,directory,args.revision,now.isoformat())
                write_understanding(store,config,now,directory,import_edits=False)
                result=dict(backup=str(backup),revision=commit(store,directory,now.isoformat(),'Restore memory '+args.revision))
            print(json.dumps(result,indent=2,ensure_ascii=False))
        elif args.command == 'annotate':
            store.annotate(args.event_key, args.source, args.reason)
            print('Evidence annotation saved; original event preserved')
        elif args.command in ('predict','reflect'):
            at = dt(args.at) if args.at else datetime.now(timezone.utc)
            result = predict(store, config, at) if args.command == 'predict' else reflect(
                store, config, at, config.get('memory_directory','data/memory'))
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.command == 'serve':
            from .dashboard import serve
            serve(store, config, args.port)
        elif args.command == 'dashboard-export':
            from .dashboard import export_html
            export_html(store,config,args.output)
            print(f'Saved private dashboard snapshot: {args.output}')
        elif args.command == "replay":
            count = 0
            with open(args.input, encoding="utf-8-sig") as source:
                for line in source:
                    if line.strip():
                        count += store.add(normalize(json.loads(line), config))
            print(f"Stored {count} new events")
        elif args.command == "export":
            if Path(args.output).resolve() == Path(config["database"]).resolve():
                parser.error("Export path cannot be the database")
            with open(args.output, "x", encoding="utf-8") as output:
                store.export(output)
        elif args.command == "status":
            print(json.dumps(store.summary(), indent=2, ensure_ascii=False))
        else:
            token = os.environ.get("HA_TOKEN")
            if not token:
                parser.error("Set HA_TOKEN in your environment (do not put it in config)")
            logging.basicConfig(level=logging.INFO)
            if args.command == 'run':
                last = [0]
                def tick():
                    if time.monotonic() - last[0] >= 60:
                        at = datetime.now(timezone.utc)
                        if due(store,config,at):
                            reflect(store,config,at,config.get('memory_directory','data/memory'))
                        from .memory import evaluate
                        with store.db:
                            evaluate(store,at)
                        predict(store, config, at)
                        last[0] = time.monotonic()
                collect(config, token, store, tick)
            else:
                collect(config, token, store)
    except ValueError as exc:
        parser.error(str(exc))
    except RuntimeError as exc:
        parser.exit(1, str(exc)+'\n')
    except OSError:
        parser.exit(1, 'Network listener or file operation failed; check the host runtime, port and file permissions.\n')
    except KeyboardInterrupt:
        pass
    finally:
        store.close()


if __name__ == "__main__":
    main()
