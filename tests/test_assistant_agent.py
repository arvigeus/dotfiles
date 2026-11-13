"""Adversarial agent protocol, permission and process-lifetime boundaries."""

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import support
from test_assistant_drawer import backend, event_stream, model


def tool_call(name='inspect_system', arguments=None, identifier='call-1', index=0):
    return {
        'index': index,
        'id': identifier,
        'type': 'function',
        'function': {
            'name': name,
            'arguments': json.dumps(arguments or {'query': 'machine'}),
        },
    }


def tool_stream(*calls, finish='tool_calls', done=True):
    data = event_stream(
        [
            {
                'choices': [
                    {
                        'index': 0,
                        'delta': {'tool_calls': list(calls)},
                        'finish_reason': finish,
                    }
                ]
            }
        ]
    ).getvalue()
    return io.BytesIO(data if done else data.removesuffix(b'data: [DONE]\n\n'))


class AssistantAgentTests(unittest.TestCase):
    def test_stream_batching_preserves_reasoning_and_text_phase_order(self):
        stream = event_stream(
            [
                {'choices': [{'delta': {'reasoning_content': 'First thought.'}}]},
                {'choices': [{'delta': {'content': 'A preface.'}}]},
                {
                    'choices': [
                        {
                            'delta': {
                                'reasoning_content': 'Second thought.',
                                'content': 'The answer.',
                            },
                            'finish_reason': 'stop',
                        }
                    ]
                },
            ]
        )
        with (
            self.agent([stream]) as (chat, emitted, _sent),
            patch.object(backend.time, 'monotonic', return_value=0),
        ):
            chat()
        self.assertEqual(
            [
                (row['reasoning'], row['text'])
                for row in emitted
                if row['type'] == 'delta'
            ],
            [
                ('First thought.', ''),
                ('', 'A preface.'),
                ('Second thought.', ''),
                ('', 'The answer.'),
            ],
        )

    def test_empty_final_answer_after_tools_is_explicit_and_keeps_results(self):
        first = event_stream(
            [
                {
                    'choices': [
                        {
                            'delta': {
                                'content': 'I will check.',
                                'reasoning_content': 'Inspect the machine.',
                                'tool_calls': [tool_call()],
                            },
                            'finish_reason': 'tool_calls',
                        }
                    ]
                }
            ]
        )
        final = event_stream(
            [
                {
                    'choices': [
                        {
                            'delta': {'reasoning_content': 'The result is available.'},
                            'finish_reason': 'stop',
                        }
                    ]
                }
            ]
        )
        with (
            self.agent([first, final]) as (chat, emitted, sent),
            patch.object(
                backend,
                'execute_tool',
                return_value={'stdout': 'Linux 7.2', 'exit_code': 0},
            ),
        ):
            chat()
        self.assertTrue(emitted[-1]['empty_answer'])
        self.assertIn('I will check.', ''.join(row.get('text', '') for row in emitted))
        self.assertEqual(
            ''.join(row.get('reasoning', '') for row in emitted),
            'Inspect the machine.The result is available.',
        )
        self.assertIn('Linux 7.2', sent[1]['messages'][-1]['content'])
        self.assertEqual(emitted[-1]['tool_context'][-1]['content'], '')
        backend.validate_tool_context(emitted[-1]['tool_context'])

    def test_file_preparation_deadline_fails_before_requesting_approval(self):
        deadline = backend.time_limit
        emitted = []
        with (
            patch.object(
                backend,
                'time_limit',
                side_effect=lambda _seconds, message: deadline(0.05, message),
            ),
            patch.object(
                backend, 'write_snapshot', side_effect=lambda _args: time.sleep(2)
            ),
            patch.object(backend, 'wait_for_approval') as approve,
            patch.object(backend, 'execute_tool') as execute,
            patch.object(backend, 'emit', side_effect=emitted.append),
        ):
            result = backend.call_tool(
                tool_call('write_file', {'path': '/tmp/example', 'content': 'new'}), 1
            )
        approve.assert_not_called()
        execute.assert_not_called()
        self.assertIn('preparation limit', result['content'])
        self.assertEqual(emitted[-1]['activity']['state'], 'failed')

    def test_wall_clock_limit_interrupts_blocked_work_and_restores_signal_handler(self):
        previous = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, 'test deadline'):
            with backend.time_limit(0.05, 'test deadline'):
                time.sleep(2)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0, 0))

    def test_inspection_uses_system_binary_and_shell_ignores_startup_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'executed'
            startup = root / 'startup'
            startup.write_text(f'touch {marker}\n')
            fake = root / 'uname'
            fake.write_text(f'#!/bin/sh\ntouch {marker}\n')
            fake.chmod(0o700)
            with patch.dict(
                os.environ,
                PATH=str(root) + os.pathsep + os.defpath,
                BASH_ENV=str(startup),
            ):
                result = backend.inspect_system({'query': 'machine'})
                self.assertIn('Linux', result['stdout'])
                result = backend.bounded_process(
                    ['/bin/bash', '--noprofile', '--norc', '-c', 'printf inspected']
                )
                self.assertEqual(result['stdout'], 'inspected')
            self.assertFalse(marker.exists())

    @contextlib.contextmanager
    def agent(self, streams, **options):
        emitted, sent = [], []
        replies = iter(streams)

        def request(_url, payload=None, **_kwargs):
            sent.append(json.loads(json.dumps(payload)))
            return next(replies)

        with (
            patch.object(backend, 'service', return_value=('user', {})),
            patch.object(backend, 'server_url', return_value='http://localhost:13305'),
            patch.object(
                backend,
                'get_json',
                return_value={'data': [model() | {'labels': ['chat', 'tool-calling']}]},
            ),
            patch.object(backend, 'request', side_effect=request),
            patch.object(backend, 'emit', side_effect=emitted.append),
        ):
            yield (
                lambda: backend.chat(
                    dict(
                        model='local',
                        messages=[{'role': 'user', 'content': 'Investigate'}],
                        **options,
                    )
                ),
                emitted,
                sent,
            )

    def test_truncated_or_unfinished_tool_calls_never_execute(self):
        for finish, done in [
            ('length', True),
            ('stop', True),
            ('tool_calls', False),
            (None, False),
        ]:
            with (
                self.subTest(finish=finish, done=done),
                self.agent([tool_stream(tool_call(), finish=finish, done=done)]) as (
                    chat,
                    emitted,
                    _sent,
                ),
                patch.object(backend, 'execute_tool') as execute,
            ):
                if finish == 'length':
                    chat()
                    self.assertTrue(emitted[-1]['limited'])
                else:
                    with self.assertRaises(ValueError):
                        chat()
                execute.assert_not_called()

    def test_malformed_stream_fragment_cannot_execute_an_earlier_valid_call(self):
        for fragment in [
            None,
            {'index': -1},
            {'index': 16},
            {'index': True},
            {'index': 1, 'function': []},
            {'index': 1, 'function': {'arguments': {}}},
        ]:
            stream = tool_stream(tool_call(), fragment)
            with (
                self.subTest(fragment=fragment),
                self.agent([stream]) as (chat, _emitted, _sent),
                patch.object(backend, 'execute_tool') as execute,
            ):
                with self.assertRaises(ValueError):
                    chat()
                execute.assert_not_called()

    def test_interleaved_calls_keep_argument_order_and_unique_result_ids(self):
        first = event_stream(
            [
                {
                    'choices': [
                        {
                            'delta': {
                                'tool_calls': [
                                    tool_call(arguments={'query': 'memory'}, index=1),
                                    {
                                        'index': 0,
                                        'id': 'call-1',
                                        'function': {
                                            'name': 'inspect_',
                                            'arguments': '{"query":',
                                        },
                                    },
                                ]
                            }
                        }
                    ]
                },
                {
                    'choices': [
                        {
                            'delta': {
                                'tool_calls': [
                                    {
                                        'index': 0,
                                        'function': {
                                            'name': 'system',
                                            'arguments': '"disks"}',
                                        },
                                    }
                                ]
                            },
                            'finish_reason': 'tool_calls',
                        }
                    ]
                },
            ]
        )
        final = event_stream(
            [
                {
                    'choices': [
                        {
                            'delta': {'content': 'Actual results.'},
                            'finish_reason': 'stop',
                        }
                    ]
                }
            ]
        )
        with (
            self.agent([first, final]) as (chat, emitted, sent),
            patch.object(
                backend,
                'execute_tool',
                return_value={'stdout': 'observed', 'exit_code': 0},
            ) as execute,
        ):
            chat()
        self.assertEqual(
            [call.args[1]['query'] for call in execute.call_args_list],
            ['disks', 'memory'],
        )
        calls = sent[1]['messages'][-3]['tool_calls']
        self.assertEqual(len({row['id'] for row in calls}), 2)
        self.assertEqual(
            [row['tool_call_id'] for row in sent[1]['messages'][-2:]],
            [row['id'] for row in calls],
        )
        self.assertEqual(
            [
                row['activity']['batch_index']
                for row in emitted
                if row.get('type') == 'tool' and row['activity']['state'] == 'completed'
            ],
            [1, 2],
        )

    def test_unknown_and_invalid_tools_return_errors_then_continue(self):
        calls = [
            tool_call('unknown'),
            tool_call('run_command', {'command': 'echo safe', 'extra': True}, index=1),
        ]
        with (
            self.agent(
                [
                    tool_stream(*calls),
                    event_stream(
                        [
                            {
                                'choices': [
                                    {
                                        'delta': {
                                            'content': 'Could not run those operations.'
                                        },
                                        'finish_reason': 'stop',
                                    }
                                ]
                            }
                        ]
                    ),
                ]
            ) as (chat, emitted, sent),
            patch.object(backend, 'execute_tool') as execute,
            patch.object(backend, 'wait_for_approval') as approve,
        ):
            chat()
        execute.assert_not_called()
        approve.assert_not_called()
        self.assertEqual(
            [row['activity']['state'] for row in emitted if row.get('type') == 'tool'],
            ['failed', 'failed'],
        )
        self.assertTrue(
            all(
                'error' in json.loads(row['content'])['untrusted_tool_result']
                for row in sent[1]['messages'][-2:]
            )
        )

    def test_approvals_use_fresh_execution_ids_even_if_the_model_repeats_ids(self):
        call = tool_call('run_command', {'command': 'true'})
        events = []
        with (
            patch.object(backend, 'emit', side_effect=events.append),
            patch.object(
                backend, 'wait_for_approval', return_value=(False, 'rejected')
            ) as approve,
            patch.object(backend, 'execute_tool') as execute,
        ):
            backend.call_tool(call, 1)
            backend.call_tool(call, 2)
        identifiers = [row.args[0] for row in approve.call_args_list]
        self.assertEqual(len(set(identifiers)), 2)
        self.assertNotIn(call['id'], identifiers)
        execute.assert_not_called()

    def test_closed_expired_and_wrong_approval_channels_do_not_execute(self):
        for data in [
            '',
            '{bad}\n[]\n'
            + json.dumps({'type': 'approval', 'id': 'other', 'approved': True})
            + '\n',
            json.dumps({'type': 'approval', 'id': 'this', 'approved': 'true'}) + '\n',
        ]:
            with (
                self.subTest(data=data),
                patch.object(backend.sys, 'stdin', io.StringIO(data)),
                patch.object(
                    backend.select,
                    'select',
                    side_effect=lambda readers, *_: (readers, [], []),
                ),
            ):
                approved, reason = backend.wait_for_approval('this')
                self.assertFalse(approved)
                self.assertTrue(reason)
        with patch.object(backend, 'APPROVAL_SECONDS', 0):
            self.assertEqual(backend.wait_for_approval('expired')[0], False)

    def test_cancelled_or_disconnected_workflow_keeps_completed_tool_results(self):
        for failure in [backend.Cancelled(), ValueError('model disconnected')]:
            first = tool_stream(tool_call())
            with (
                self.subTest(failure=type(failure).__name__),
                self.agent([first]) as (chat, emitted, _sent),
                patch.object(
                    backend,
                    'stream_completion',
                    side_effect=[
                        (
                            'tool_calls',
                            [{k: v for k, v in tool_call().items() if k != 'index'}],
                            'Checking.',
                        ),
                        failure,
                    ],
                ),
                patch.object(
                    backend,
                    'execute_tool',
                    return_value={'stdout': 'confirmed state', 'exit_code': 0},
                ),
            ):
                with self.assertRaises(type(failure)):
                    chat()
            saved = emitted[-1]['tool_context']
            self.assertEqual(emitted[-1]['type'], 'context')
            self.assertIn('confirmed state', saved[1]['content'])
            self.assertEqual(backend.validate_tool_context(saved), saved)

    def test_cancelled_batch_closes_unexecuted_calls_in_saved_context(self):
        with (
            self.agent(
                [tool_stream(tool_call(), tool_call(index=1, identifier='call-2'))]
            ) as (chat, emitted, _sent),
            patch.object(backend, 'execute_tool', side_effect=backend.Cancelled()),
        ):
            with self.assertRaises(backend.Cancelled):
                chat()
        saved = emitted[-1]['tool_context']
        self.assertIn('side effects may have occurred', saved[1]['content'])
        self.assertIn('not executed', saved[2]['content'])
        backend.validate_tool_context(saved)

    def test_round_call_and_context_limits_stop_further_execution(self):
        for limit, value, expected_calls in [
            ('MAX_AGENT_ROUNDS', 2, 2),
            ('MAX_TOOL_CALLS', 1, 1),
            ('MAX_AGENT_CONTEXT', 100, 0),
        ]:
            with (
                self.subTest(limit=limit),
                patch.object(backend, limit, value),
                self.agent([tool_stream(tool_call()) for _ in range(3)]) as (
                    chat,
                    emitted,
                    _sent,
                ),
                patch.object(
                    backend,
                    'execute_tool',
                    return_value={'stdout': 'checked', 'exit_code': 0},
                ) as execute,
            ):
                chat()
                self.assertEqual(execute.call_count, expected_calls)
                self.assertEqual(emitted[-1], {'type': 'done', 'limited': True})
                self.assertTrue(
                    any(
                        row.get('type') == 'error' and 'limit' in row['error']
                        for row in emitted
                    )
                )

    def test_output_and_sse_limits_bound_backend_memory_before_actions(self):
        for field, limit in [
            ('content', 'MAX_STREAM_TEXT'),
            ('reasoning_content', 'MAX_STREAM_REASONING'),
        ]:
            stream = event_stream([{'choices': [{'delta': {field: 'x' * 30}}]}])
            with (
                self.subTest(field=field),
                patch.object(backend, limit, 20),
                self.agent([stream]) as (chat, emitted, _sent),
            ):
                chat()
                self.assertTrue(emitted[-1]['limited'])
                self.assertEqual(
                    sum(
                        len(row.get('text', '') + row.get('reasoning', ''))
                        for row in emitted
                    ),
                    20,
                )
        with self.assertRaisesRegex(ValueError, 'oversized'):
            list(
                backend.events(
                    io.BytesIO(b'data: ' + b'x' * (backend.MAX_SSE_EVENT + 1))
                )
            )
        with (
            patch.object(backend.time, 'monotonic', return_value=2),
            self.assertRaisesRegex(ValueError, 'time limit'),
        ):
            list(backend.events(io.BytesIO(b': heartbeat\n'), deadline=1))

    def test_invalid_saved_context_cannot_orphan_tool_results(self):
        valid = [
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{k: v for k, v in tool_call().items() if k != 'index'}],
            },
            {'role': 'tool', 'tool_call_id': 'call-1', 'content': '{}'},
            {'role': 'assistant', 'content': 'Done'},
        ]
        for context in [
            [valid[1], valid[2]],
            [valid[0], valid[2]],
            valid[:-1],
            valid + [valid[1]],
            [valid[0], valid[1], valid[1], valid[2]],
        ]:
            with self.subTest(context=context), self.assertRaises(ValueError):
                backend.validate_tool_context(context)
        self.assertEqual(backend.validate_tool_context(valid), valid)

    def test_read_only_search_cannot_run_ripgrep_preprocessor_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'executed'
            pre = root / 'pre'
            pre.write_text(f'#!/bin/sh\ntouch {marker}\ncat "$1"\n')
            pre.chmod(0o700)
            config = root / 'rg-config'
            config.write_text(f'--pre={pre}\n')
            (root / 'target.txt').write_text('needle')
            with patch.dict(os.environ, RG_CONFIG_PATH=str(config)):
                result = backend.search_files(
                    {'path': str(root), 'mode': 'content', 'pattern': 'needle'}
                )
            self.assertEqual(result['exit_code'], 0)
            self.assertIn('target.txt', result['stdout'])
            self.assertFalse(
                marker.exists(), 'read-only search executed a config program'
            )

    def test_unit_option_injection_never_starts_a_process(self):
        with patch.object(backend, 'bounded_process') as run:
            with self.assertRaises(ValueError):
                backend.inspect_system({'query': 'service', 'service_name': '--host'})
            run.assert_not_called()

    def test_directory_replacement_during_approval_cannot_redirect_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, other = root / 'original', root / 'other'
            parent.mkdir()
            other.mkdir()
            (parent / 'config').write_text('original')
            (other / 'config').write_text('protected')
            snapshot = backend.write_snapshot(
                {'path': str(parent / 'config'), 'content': 'new'}
            )
            parent.rename(root / 'moved')
            parent.symlink_to(other, target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                backend.write_file(snapshot)
            self.assertEqual((other / 'config').read_text(), 'protected')
            self.assertEqual((root / 'moved/config').read_text(), 'original')

    def test_child_inheriting_pipes_cannot_outlive_the_command_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            try:
                started = time.monotonic()
                result = backend.bounded_process(
                    ['/bin/bash', '-c', f'sleep 60 & echo $! > {pidfile}'], timeout=0.2
                )
                self.assertTrue(result['timed_out'])
                self.assertLess(time.monotonic() - started, 3)
                self.assert_not_running(int(pidfile.read_text()))
            finally:
                self.kill_fixture(pidfile)

    def test_real_signal_cancellation_reaps_a_running_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            script = f"""import sys, signal, pathlib
sys.path.insert(0, {str(support.DESKTOP / 'drawers/assistant')!r})
import backend
signal.signal(signal.SIGTERM, backend.cancel_signal)
try:
    backend.bounded_process(['/bin/bash', '-c', 'sleep 60 & echo $! > {pidfile}; wait'], timeout=60)
except backend.Cancelled:
    print('cancelled', flush=True)
"""
            process = subprocess.Popen(
                [sys.executable, '-u', '-c', script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 3
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists(), 'fixture failed to start')
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn('cancelled', stdout)
                self.assert_not_running(int(pidfile.read_text()))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                self.kill_fixture(pidfile)

    def test_output_limit_and_timeout_are_visible_in_tool_state(self):
        result = backend.bounded_process(
            [
                sys.executable,
                '-c',
                'import sys; sys.stdout.write("x"*100000); sys.stderr.write("y"*100000)',
            ],
            output_limit=100,
        )
        self.assertEqual(len(result['stdout']), 100)
        self.assertEqual(len(result['stderr']), 100)
        self.assertTrue(result['truncated'])
        emitted = []
        with (
            patch.object(
                backend,
                'execute_tool',
                return_value={'stdout': '', 'exit_code': 0, 'timed_out': True},
            ),
            patch.object(backend, 'emit', side_effect=emitted.append),
        ):
            backend.call_tool(tool_call(), 1)
        self.assertEqual(emitted[-1]['activity']['state'], 'failed')
        self.assertIn('Timed out', emitted[-1]['activity']['summary'])

    def assert_not_running(self, pid):
        # Group signals also target orphaned descendants, but the kernel may
        # schedule their exit just after the reaped group leader returns.
        deadline = time.monotonic() + 1
        while True:
            try:
                state = Path(f'/proc/{pid}/stat').read_text().split(') ')[1][0]
            except FileNotFoundError:
                return
            if state == 'Z':
                return
            if time.monotonic() >= deadline:
                self.fail(f'child {pid} is still running')
            time.sleep(0.01)

    @staticmethod
    def kill_fixture(pidfile):
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
