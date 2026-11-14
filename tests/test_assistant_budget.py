"""Runtime context limits without losing card actions or splitting tool exchanges."""

import io
import json
import unittest
from unittest.mock import patch

import test_assistant_agent as protocol
from test_assistant_drawer import backend, event_stream


class PromptBudgetTests(unittest.TestCase):
    def test_image_transport_bytes_do_not_consume_text_context(self):
        with patch.object(backend, 'get_json', return_value={}):
            budget = backend.PromptBudget(
                'http://localhost:13305', dict(id='local', target='local')
            )
        payload = dict(
            messages=[
                dict(role='system', content='Describe the image.'),
                dict(
                    role='user',
                    content=[
                        dict(type='text', text='What is this?'),
                        dict(
                            type='image_url',
                            image_url={'url': 'data:image/png;base64,' + 'a' * 1000000},
                        ),
                    ],
                ),
            ]
        )
        budget.fit(payload)
        self.assertLess(budget.tokens(payload), 4000)
        self.assertEqual(
            len(payload['messages'][-1]['content'][-1]['image_url']['url']), 1000022
        )

    def test_real_rounds_exclude_ui_payloads_but_save_them_for_followups(self):
        streams = [
            protocol.tool_stream(
                protocol.tool_call(
                    'search_spaces',
                    {'kind': 'movie', 'query': 'Mars'},
                    identifier=f'call-{index}',
                )
            )
            for index in range(5)
        ]
        streams.append(
            event_stream(
                [
                    {
                        'choices': [
                            {
                                'delta': {'content': 'Here are the movies.'},
                                'finish_reason': 'stop',
                            }
                        ]
                    }
                ]
            )
        )
        result = dict(
            items=[
                dict(
                    ref='space_' + 'a' * 32,
                    kind='movie',
                    title='The Martian',
                    metadata={'year': 2015},
                    payload={
                        'title': {
                            'id': 'tt3659388',
                            'plot': 'A long provider description. ' * 180,
                        }
                    },
                )
            ]
        )
        with (
            protocol.AssistantAgentTests().agent(streams) as (chat, emitted, sent),
            patch.object(
                backend,
                'execute_tool',
                side_effect=lambda *_args: json.loads(json.dumps(result)),
            ),
        ):
            chat()
        self.assertEqual(len(sent), 6)
        self.assertFalse(any(row['type'] == 'error' for row in emitted))
        for request in sent:
            for row in request['messages']:
                if row['role'] == 'tool':
                    self.assertNotIn(
                        'payload',
                        json.loads(row['content'])['untrusted_tool_result']['items'][0],
                    )
        saved = emitted[-1]['tool_context']
        backend.validate_tool_context(saved)
        backend.restore_space_results(saved)
        self.assertEqual(
            backend.SPACE_RESULTS['space_' + 'a' * 32]['payload']['title']['id'],
            'tt3659388',
        )

    def test_budget_uses_slot_size_and_template_including_tools(self):
        entry = dict(id='local', target='local')
        health = dict(
            all_models_loaded=[
                dict(
                    model_name='local',
                    recipe='llamacpp',
                    max_context_window=1048576,
                    recipe_options={'ctx_size': 16000},
                    backend_url='http://127.0.0.1:8001/v1',
                )
            ]
        )
        props = dict(default_generation_settings=dict(n_ctx=15360))
        sent = []

        def request(url, payload=None, **_kwargs):
            sent.append((url, payload))
            result = (
                {'prompt': 'full template with tools'}
                if url.endswith('/apply-template')
                else {'tokens': [1, 2, 3]}
            )
            return io.BytesIO(json.dumps(result).encode())

        with (
            patch.object(backend, 'get_json', side_effect=[health, props]),
            patch.object(backend, 'request', side_effect=request),
        ):
            budget = backend.PromptBudget('http://localhost:13305', entry)
            payload = dict(
                model='local',
                stream=True,
                messages=[dict(role='user', content='Hello')],
                tools=backend.TOOLS,
            )
            budget.fit(payload)
        self.assertEqual(budget.context, 15360)
        self.assertEqual(sent[0][1]['tools'], backend.TOOLS)
        self.assertEqual(sent[1][1]['content'], 'full template with tools')

    def test_history_trimming_keeps_whole_exchanges_and_current_request(self):
        with patch.object(backend, 'get_json', return_value={}):
            budget = backend.PromptBudget(
                'http://localhost:13305', dict(id='local', target='local')
            )
        budget.context = 4096
        messages = [
            dict(role='system', content='System'),
            dict(role='user', content='Old ' * 8000),
            dict(
                role='assistant',
                content=None,
                tool_calls=[
                    dict(
                        id='old', function={'name': 'inspect_system', 'arguments': '{}'}
                    )
                ],
            ),
            dict(role='tool', tool_call_id='old', content='{}'),
            dict(role='assistant', content='Done'),
            dict(role='user', content='Find jazz radio'),
        ]
        payload = dict(messages=messages)
        budget.fit(payload)
        self.assertEqual([row['role'] for row in messages], ['system', 'user'])
        self.assertEqual(messages[-1]['content'], 'Find jazz radio')

    def test_oversized_current_request_fails_before_inference(self):
        with patch.object(backend, 'get_json', return_value={}):
            budget = backend.PromptBudget(
                'http://localhost:13305', dict(id='local', target='local')
            )
        with self.assertRaisesRegex(backend.AgentLimit, 'loaded model'):
            budget.fit(
                dict(
                    messages=[
                        dict(role='system', content='System'),
                        dict(role='user', content='x' * 100000),
                    ]
                )
            )

    def test_server_context_rejection_recovers_without_repeating_tools(self):
        error = backend.urllib.error.HTTPError(
            'http://localhost',
            400,
            'Bad Request',
            {},
            io.BytesIO(
                b'{"error":{"message":"request (18589 tokens) exceeds the available context size (15360 tokens), try increasing it"}}'
            ),
        )
        final = event_stream(
            [
                {
                    'choices': [
                        {'delta': {'content': 'Recovered.'}, 'finish_reason': 'stop'}
                    ]
                }
            ]
        )
        with (
            protocol.AssistantAgentTests().agent([final]) as (chat, emitted, _sent),
            patch.object(
                backend,
                'stream_completion',
                side_effect=[error, ('stop', [], 'Recovered.')],
            ) as stream,
            patch.object(backend, 'execute_tool') as execute,
            patch.object(
                backend.PromptBudget,
                'refresh',
                lambda budget: setattr(budget, 'context', 65536),
            ),
        ):
            backend.chat(
                dict(
                    model='local',
                    messages=[
                        dict(role='user', content='Older conversation. ' * 2000),
                        dict(role='assistant', content='Done'),
                        dict(role='user', content='Find jazz radio'),
                    ],
                )
            )
        self.assertEqual(stream.call_count, 2)
        execute.assert_not_called()
        self.assertEqual(emitted[-1]['type'], 'done')
