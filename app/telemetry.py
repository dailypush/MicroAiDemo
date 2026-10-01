"""Export the recorded run as OTLP/HTTP JSON to local Langfuse.

No SDK is needed for this tiny demo. Production apps should use an OTEL or
Langfuse SDK for batching, retries, and automatic context propagation.
"""
import base64
import json
import os
import urllib.request
import uuid


def attributes(values):
    return [{'key': key, 'value': {'stringValue': value if isinstance(value, str) else json.dumps(value)}}
            for key, value in values.items()]


def payload(trace, system_prompt):
    root_id = uuid.uuid4().hex[:16]
    common = {'langfuse.trace.name': 'agent.run', 'langfuse.environment': 'local',
              'langfuse.trace.metadata.fault': trace['fault'],
              'langfuse.trace.metadata.run_id': trace['id'],
              'langfuse.trace.metadata.status': trace['status']}
    for key in ('scenario','policy_version','original_run_id','approval_id'):
        if key in trace: common['langfuse.trace.metadata.'+key]=trace[key]
    def make(name, start, end, values, parent=None, error=None):
        span = {'traceId': trace['id'], 'spanId': root_id if parent is None else uuid.uuid4().hex[:16],
                'name': name, 'kind': 1, 'startTimeUnixNano': str(start), 'endTimeUnixNano': str(end),
                'attributes': attributes({**common, **values}),
                'status': {'code': 2 if error else 1}}
        if parent:
            span['parentSpanId'] = parent
        if error:
            span['status']['message'] = error
            span['attributes'] += attributes({'langfuse.observation.level':'ERROR', 'langfuse.observation.status_message':error})
        return span
    start_ns = int(trace['timestamp'] * 1e9)
    end_ns = start_ns + int(trace['duration_ms'] * 1e6)
    spans = [make('agent.run', start_ns, end_ns,
                  {'langfuse.observation.type':'agent', 'langfuse.observation.input':json.dumps(trace['prompt']),
                   'langfuse.observation.output':json.dumps(trace['answer'])}, error=trace.get('error'))]
    if trace['status'] in ('blocked','awaiting_approval','rejected','expired'):
        spans[0]['attributes']+=attributes({'langfuse.observation.level':'WARNING'})
    for item in trace['spans']:
        values = {'langfuse.observation.type':item.get('observation_type','span'),
                  'langfuse.observation.metadata.agent':item.get('agent','default'),
                  'langfuse.observation.output':json.dumps(item.get('output', item.get('action', item.get('error'))))}
        if 'input' in item: values['langfuse.observation.input']=json.dumps(item['input'])
        name = item['name']
        if name.startswith('model.'):
            values.update({'langfuse.observation.type':'generation', 'gen_ai.request.model':trace['model'],
                           'langfuse.observation.input':json.dumps([{'role':'system','content':item.get('system_prompt',system_prompt)},{'role':'user','content':item.get('input',trace['prompt'])}]),
                           'langfuse.observation.usage_details':json.dumps({'input':item['input_tokens'],'output':item['output_tokens']}),
                           'langfuse.observation.model.parameters':json.dumps({'temperature':0,'num_ctx':2048,'num_predict':180})})
        elif name.startswith('tool.'):
            values.update({'langfuse.observation.type':'tool', 'langfuse.observation.input':json.dumps(item.get('input',trace.get('action')))})
        elif name == 'harness.validate':
            values.update({'langfuse.observation.type':'guardrail', 'langfuse.observation.input':json.dumps(item['action'])})
        began = start_ns + int(item['start_offset_ms'] * 1e6)
        child=make(name, began, began + int(item['duration_ms']*1e6), values, item.get('parent_id',root_id), item.get('error'))
        if 'id' in item: child['spanId']=item['id']
        outcome=item.get('output',{}).get('outcome') if isinstance(item.get('output'),dict) else None
        if outcome in ('deny','blocked','rejected','expired','approval_required'):
            child['attributes']+=attributes({'langfuse.observation.level':'WARNING'})
        spans.append(child)
    return {'resourceSpans':[{'resource':{'attributes':attributes({'service.name':'micro-agent-demo'})},
                             'scopeSpans':[{'scope':{'name':'micro-agent-harness','version':'1.0'},'spans':spans}]}]}


def export_trace(trace, system_prompt):
    base = os.getenv('LANGFUSE_BASE_URL')
    if not base:
        return {'status':'disabled'}
    try:
        auth = base64.b64encode(f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
        request = urllib.request.Request(base + '/api/public/otel/v1/traces', json.dumps(payload(trace, system_prompt)).encode(),
            {'Content-Type':'application/json','Authorization':'Basic '+auth,'x-langfuse-ingestion-version':'4'})
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.load(response)
        partial = result.get('partialSuccess', {})
        if int(partial.get('rejectedSpans', 0)):
            raise RuntimeError('Langfuse rejected one or more spans.')
        ui = os.getenv('LANGFUSE_UI_URL','http://localhost:3000')
        return {'status':'accepted','url':f"{ui}/project/{os.getenv('LANGFUSE_PROJECT_ID','micro-ai-demo')}/traces/{trace['id']}"}
    except Exception as error:
        return {'status':'error','error':f'{type(error).__name__}: {error}'}
