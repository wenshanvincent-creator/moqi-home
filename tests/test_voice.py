import copy
import tempfile
import unittest
from moqi.voice import LocalCorrectionParser


CONFIG = {'entities': {
    'switch.dining_light': {'role': 'actuator', 'aliases': ['餐厅灯']},
    'switch.fan': {'role': 'actuator', 'aliases': ['风扇']},
}}


class Agent:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    def system_one(self, text, questions):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


def valid_response():
    selected = {'intent': 'constraint', 'device': 'switch.dining_light',
                'action': 'turn_off', 'scope': 'night'}
    return {'answers': {k: {'choice': v, 'probabilities': {v: .9}}
                        for k, v in selected.items()}}


class VoiceContractTests(unittest.TestCase):
    def test_explicit_rule_bypasses_model(self):
        agent = Agent(error=RuntimeError('must not run'))
        result = LocalCorrectionParser(CONFIG, agent=agent).parse('晚上不要自动关餐厅灯')
        self.assertEqual(result['intent'], 'constraint')
        self.assertEqual(result['scope'], 'night')
        self.assertEqual(agent.calls, 0)

    def test_ambiguous_device_without_model_abstains(self):
        parser = LocalCorrectionParser(CONFIG)
        for text in ['不要关那个', '不要关餐厅灯和风扇', '修改安全规则', '']:
            with self.subTest(text=text):
                self.assertEqual(parser.parse(text)['choice'], 'Noul')

    def test_model_constraint_requires_acceptance(self):
        result = LocalCorrectionParser(CONFIG, agent=Agent(valid_response())).parse('我睡下之后灯别自己灭')
        self.assertEqual(result['intent'], 'constraint_candidate')
        self.assertTrue(result['requires_explicit_app_acceptance'])

    def test_invalid_probabilities_abstain(self):
        for probability in [float('nan'), float('inf'), -1, 1.1, '0.99', True]:
            with self.subTest(probability=probability):
                response = valid_response()
                response['answers']['intent']['probabilities']['constraint'] = probability
                result = LocalCorrectionParser(CONFIG, agent=Agent(response)).parse('换个说法')
                self.assertEqual(result['choice'], 'Noul')

    def test_missing_and_outside_choices_abstain(self):
        for response in [{}, {'answers': None}, valid_response()]:
            response = copy.deepcopy(response)
            if response.get('answers'):
                response['answers']['device'] = {'choice': 'switch.unlisted', 'probabilities': {'switch.unlisted': 1}}
            self.assertEqual(LocalCorrectionParser(CONFIG, agent=Agent(response)).parse('换个说法')['choice'], 'Noul')

    def test_unknown_device_abstains(self):
        response = valid_response()
        response['answers']['device'] = {'choice': 'unknown', 'probabilities': {'unknown': .99}}
        self.assertEqual(LocalCorrectionParser(CONFIG, agent=Agent(response)).parse('换个说法')['choice'], 'Noul')

    def test_runtime_error_abstains(self):
        parser = LocalCorrectionParser(CONFIG, agent=Agent(error=RuntimeError('inference failed')))
        self.assertEqual(parser.parse('换个说法')['choice'], 'Noul')

    def test_missing_model_blocks_explicitly(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaisesRegex(RuntimeError, 'missing local artifact model.onnx'):
                LocalCorrectionParser(CONFIG, model_path=path)

    def test_temporary_qualifiers_and_questions_do_not_become_permanent_rules(self):
        parser = LocalCorrectionParser(CONFIG)
        for text in ['不要自动关餐厅灯吗？', '不要关餐厅灯，明天再关', '不要开风扇一分钟']:
            self.assertEqual(parser.parse(text)['choice'], 'Noul')


if __name__ == '__main__':
    unittest.main()
