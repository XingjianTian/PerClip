"""Run inside the pinned candidate image; no external services or credentials used."""
import ast
import asyncio
import copy
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import peewee

ROOT = Path(os.environ.get('RAGFLOW_ROOT', '/ragflow'))


def function_nodes(path, names):
    tree = ast.parse((ROOT / path).read_text())
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]


class Message:
    def __init__(self):
        self.pending = False
        self.delivered = False
        self.ack_failures = 0
        self.acks = 0

    def get_message(self):
        return {'id': 'task', 'doc_id': 'doc'}

    def get_msg_id(self):
        return '1-0'

    def ack(self):
        self.acks += 1
        if self.ack_failures:
            self.ack_failures -= 1
            return False
        self.pending = False
        return True


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.message = Message()
        self.row = NS(progress=0.0, retry_count=0)
        self.lookup_down = False
        self.progress_down = False
        self.exists = True
        self.pipeline_calls = 0
        self.counters = 0
        self.action = 'success'
        self.audit_down = False
        outer = self

        class Tasks:
            @staticmethod
            def get_by_id(task_id):
                if outer.lookup_down:
                    raise OSError('synthetic database unavailable')
                return outer.exists, outer.row if outer.exists else None

            @staticmethod
            def get_task(task_id, *args):
                if not outer.exists:
                    return None
                before = outer.row.retry_count
                outer.row.retry_count += 1
                outer.row.progress = -1.0 if before >= 3 else 0.05
                return None if before >= 3 else {'id': task_id, 'doc_id': 'doc'}

        def pending(*args):
            if self.message.pending:
                yield self.message

        def consume(*args):
            if not self.message.delivered:
                self.message.delivered = self.message.pending = True
                return self.message
            return None

        async def process(*args):
            self.pipeline_calls += 1
            if self.action == 'failure':
                raise ValueError('synthetic invalid file')
            self.counters += 1
            self.row.progress = 1.0

        def progress(task_id, prog=None, msg=''):
            # Reproduce upstream set_progress swallowing a failed database write.
            if not self.progress_down and prog is not None:
                self.row.progress = prog

        def audit(**kwargs):
            if self.audit_down:
                raise OSError('synthetic audit unavailable')

        self.g = dict(asyncio=NS(sleep=AsyncMock()), logging=logging, copy=copy,
                      os=NS(environ={}), json=__import__('json'),
                      exceptiongroup=NS(ExceptionGroup=ExceptionGroup),
                      TaskService=Tasks, REDIS_CONN=NS(get_unacked_iterator=pending, queue_consumer=consume),
                      settings=NS(get_svr_queue_names=lambda _: ['isolated']), TASK_TYPE='common',
                      CONSUMER_NAME='isolated', SVR_CONSUMER_GROUP_NAME='group', UNACKED_ITERATOR=None,
                      DONE_TASKS=0, FAILED_TASKS=0, CURRENT_TASKS={},
                      GRAPH_RAPTOR_FAKE_DOC_ID='graph', CANVAS_DEBUG_DOC_ID='canvas',
                      PipelineTaskType=NS(PARSE='parse', MEMORY='memory'),
                      PIPELINE_SPECIAL_PROGRESS_FREEZE_TASK_TYPES=[], TASK_TYPE_TO_PIPELINE_TASK_TYPE={},
                      has_canceled=lambda _: False, TaskCanceledException=type('TaskCanceledException', (Exception,), {}),
                      set_progress=progress, set_recording_context=lambda _: None, NullRecordingContext=lambda: None,
                      get_recording_context=lambda: NS(save_func_return_value=lambda *args: None),
                      TaskManager=NS(run_refactored_task=process),
                      PipelineOperationLogService=NS(record_pipeline_operation=audit),
                      chat_limiter=None, minio_limiter=None, chunk_limiter=None, embed_limiter=None, kg_limiter=None)
        nodes = function_nodes('rag/svr/task_executor.py', {'collect', 'handle_task'})
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<patched executor>', 'exec'), self.g)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    async def run_delivery(self):
        await self.g['handle_task']()

    async def test_success_acks_and_counts_once(self):
        await self.run_delivery()
        self.assertFalse(self.message.pending)
        self.assertEqual((self.pipeline_calls, self.counters, self.row.retry_count), (1, 1, 1))

    async def test_file_failure_is_terminal_and_not_reprocessed_after_ack_loss(self):
        self.action = 'failure'
        self.message.ack_failures = 1
        await self.run_delivery()
        self.assertEqual(self.row.progress, -1)
        self.assertTrue(self.message.pending)
        await self.run_delivery()  # exhaust the first pending scan
        await self.run_delivery()  # revisit terminal pending, without get_task()
        self.assertFalse(self.message.pending)
        self.assertEqual((self.pipeline_calls, self.row.retry_count), (1, 1))

    async def test_failed_error_write_keeps_message_until_database_recovers(self):
        self.action, self.progress_down = 'failure', True
        await self.run_delivery()
        self.assertTrue(self.message.pending)
        self.assertLess(self.row.progress, 1)
        self.progress_down = False
        self.action = 'success'
        for _ in range(3):
            await self.run_delivery()
            if not self.message.pending:
                break
        self.assertFalse(self.message.pending)
        self.assertEqual((self.counters, self.row.retry_count), (1, 2))

    async def test_lookup_outage_preserves_delivery_without_incrementing_attempts(self):
        self.lookup_down = True
        await self.run_delivery()
        self.assertTrue(self.message.pending)
        self.assertEqual(self.row.retry_count, 0)
        self.lookup_down = False
        await self.run_delivery()
        await self.run_delivery()
        self.assertFalse(self.message.pending)
        self.assertEqual(self.row.retry_count, 1)

    async def test_ack_loss_on_success_does_not_repeat_work_or_counters(self):
        self.message.ack_failures = 1
        await self.run_delivery()
        await self.run_delivery()
        await self.run_delivery()
        self.assertFalse(self.message.pending)
        self.assertEqual((self.pipeline_calls, self.counters, self.row.retry_count), (1, 1, 1))

    async def test_audit_failure_is_recovered_without_reprocessing(self):
        self.audit_down = True
        with self.assertRaises(OSError):
            await self.run_delivery()
        self.assertTrue(self.message.pending)
        self.audit_down = False
        await self.run_delivery()
        await self.run_delivery()
        self.assertFalse(self.message.pending)
        self.assertEqual((self.pipeline_calls, self.counters), (1, 1))

    async def test_existing_retry_limit_is_preserved(self):
        self.row.retry_count = 3
        await self.run_delivery()
        self.assertFalse(self.message.pending)
        self.assertEqual((self.row.progress, self.pipeline_calls), (-1, 0))

    async def test_missing_task_is_discarded_without_processing(self):
        self.exists = False
        await self.run_delivery()
        self.assertFalse(self.message.pending)
        self.assertEqual(self.pipeline_calls, 0)


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = db = peewee.SqliteDatabase(str(Path(self.tmp.name) / 'state.sqlite3'))

        class Base(peewee.Model):
            id = peewee.CharField(primary_key=True)
            class Meta:
                database = db

        class Task(Base):
            progress = peewee.FloatField(default=0.8)

        class Document(Base):
            kb_id = peewee.CharField(default='kb')
            token_num = peewee.IntegerField(default=0)
            chunk_num = peewee.IntegerField(default=0)

        class Knowledgebase(Base):
            token_num = peewee.IntegerField(default=0)
            chunk_num = peewee.IntegerField(default=0)

        self.Task, self.Doc, self.KB = Task, Document, Knowledgebase
        db.create_tables([Task, Document, Knowledgebase])
        Task.create(id='task'); Task.create(id='page2'); Document.create(id='doc'); Knowledgebase.create(id='kb')
        tree = ast.parse((ROOT / 'api/db/services/task_service.py').read_text())
        source = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TaskService')
        method = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'complete_parse_task')
        cls = ast.ClassDef(name='Completion', bases=[], keywords=[], body=[method], decorator_list=[])
        g = dict(DB=db, Document=Document, Knowledgebase=Knowledgebase)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<patched completion>', 'exec'), g)
        self.service = g['Completion']; self.service.model = Task
        db.close()

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def complete(self, task='task', doc='doc', kb='kb'):
        self.service.complete_parse_task(task, doc, kb, 100, 7)

    def test_completion_is_idempotent(self):
        self.complete(); self.complete()
        self.assertEqual(self.Task.get_by_id('task').progress, 1)
        self.assertEqual((self.Doc.get_by_id('doc').chunk_num, self.KB.get_by_id('kb').chunk_num), (7, 7))

    def test_failure_between_counter_writes_rolls_back_terminal_and_both_counters(self):
        with patch.object(self.KB, 'update', side_effect=peewee.OperationalError('synthetic database outage')):
            with self.assertRaises(peewee.OperationalError): self.complete()
        self.assertEqual(self.Task.get_by_id('task').progress, 0.8)
        self.assertEqual((self.Doc.get_by_id('doc').chunk_num, self.KB.get_by_id('kb').chunk_num), (0, 0))
        self.complete()
        self.assertEqual(self.Doc.get_by_id('doc').chunk_num, 7)

    def test_missing_document_rolls_back(self):
        with self.assertRaises(LookupError): self.complete(doc='missing')
        self.assertEqual(self.Task.get_by_id('task').progress, 0.8)
        self.assertEqual(self.KB.get_by_id('kb').chunk_num, 0)

    def test_missing_knowledgebase_rolls_back(self):
        with self.assertRaises(LookupError): self.complete(kb='missing')
        self.assertEqual(self.Task.get_by_id('task').progress, 0.8)

    def test_sibling_pages_count_independently_once(self):
        self.complete(); self.complete('page2'); self.complete('page2')
        self.assertEqual((self.Doc.get_by_id('doc').chunk_num, self.KB.get_by_id('kb').chunk_num), (14, 14))


if __name__ == '__main__':
    unittest.main(verbosity=2)
