import json
import unittest
from app.agent import calculate, run, evaluate

def fake(tool, argument):
    return lambda _: {'message': {'content': json.dumps({'tool': tool, 'argument': argument})}, 'eval_count': 12}

class HarnessTests(unittest.TestCase):
    def test_calculator_and_safety(self):
        self.assertEqual(calculate('(12+8)*3'), '60')
        for value in ['__import__("os").system("ls")', '2**1000000', 'True', '1e100', '1/0']:
            with self.assertRaises((ValueError, ZeroDivisionError)):
                calculate(value)
    def test_trace_and_real_tool(self):
        trace = run('7*8', caller=fake('calculator', '7*8'), persist=False)
        self.assertEqual(trace['answer'], '7*8 = 56')
        self.assertEqual(len(trace['spans']), 4)
    def test_guardrail_and_fault(self):
        for fault in ['invalid_tool', 'tool_error']:
            trace = run('7*8', fault, caller=fake('calculator', '7*8'), persist=False)
            self.assertEqual(trace['status'], 'error')
    def test_bad_output(self):
        trace = run('hello', caller=lambda _: {'message': {'content': 'broken'}}, persist=False)
        self.assertEqual(trace['status'], 'error')
    def test_evaluation_detects_wrong_answer(self):
        result = evaluate(caller=fake('calculator', '1+1'), persist=False)
        self.assertEqual(result['passed'], 0)

if __name__ == '__main__':
    unittest.main()
