"""§7 local text-to-typed-correction adapter. Audio is supplied by the future §8 chain."""
import math
from pathlib import Path
from .decision import parse_correction


class LocalCorrectionParser:
    def __init__(self,config,model_path=None,agent=None):
        self.config=config
        self.agent=agent
        if model_path is not None:
            path=Path(model_path)
            for name in ('model.onnx','tokenizer.json','edgejev.json'):
                if not (path/name).is_file(): raise RuntimeError('EdgeJev blocked: missing local artifact '+name)
            try: from edgejev import Agent
            except ImportError as exc: raise RuntimeError('EdgeJev blocked: optional edgejev runtime is not installed') from exc
            # Local Agent API documented at https://github.com/yzfly/edgejev .
            self.agent=Agent(str(path))

    def parse(self,text):
        rule=parse_correction(text,self.config)
        if rule['choice']!='Noul' or self.agent is None: return rule
        choices={entity:', '.join(spec.get('aliases',[entity])) for entity,spec in self.config['entities'].items() if spec['role']=='actuator'}
        if not choices: return rule
        questions={
            'intent':dict(type='choice',instructions='识别明确表达的用途，不猜测省略的意图。',criteria={
                'constraint':'明确要求以后禁止某项自动操作','explain':'询问操作原因',
                'memory_changes':'询问最近学到什么','unknown':'其他、不明确或要求修改安全规则'}),
            'device':dict(type='choice',instructions='识别用户明确提到的设备。',criteria={**choices,'unknown':'没有明确设备或提到多个设备'}),
            'action':dict(type='choice',instructions='哪一项自动动作被明确禁止？',criteria={
                'turn_off':'禁止自动关闭','turn_on':'禁止自动打开','unknown':'没有明确禁止的动作'}),
            'scope':dict(type='choice',instructions='约束的时段。',criteria={
                'night':'晚上或夜间','always':'始终','unknown':'不明确'})}
        try:
            answers=self.agent.system_one(text,questions)['answers']
            selected={}; confidences=[]
            for name,q in questions.items():
                answer=answers[name]; choice=answer['choice']; prob=answer['probabilities'][choice]
                if choice not in q['criteria'] or isinstance(prob,bool) or not isinstance(prob,(int,float)) or not math.isfinite(prob) or not 0<=prob<=1:
                    raise ValueError('Invalid typed output')
                selected[name]=choice; confidences.append(prob)
            if selected['intent'] in {'explain','memory_changes'}:
                return dict(intent=selected['intent'],choice='Choice',confidence=min(confidences),source='edgejev')
            if selected['intent']!='constraint' or 'unknown' in selected.values(): return rule
            # Until home-domain calibration, model-only interpretations are visible
            # candidates; they cannot write highest-confidence permanent constraints.
            return dict(intent='constraint_candidate',choice='Choice',entity_id=selected['device'],
                deny_actions=[selected['action']],scope=selected['scope'],reason=text,
                confidence=min(confidences),source='edgejev',requires_explicit_app_acceptance=True)
        except (KeyError,TypeError,ValueError,RuntimeError):
            return dict(intent='unknown',choice='Noul',reason='local model failed or returned invalid types')
