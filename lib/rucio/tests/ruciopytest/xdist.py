# -*- coding: utf-8 -*-
# Copyright 2021 CERN
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Authors:
# - Benedikt Ziemons <benedikt.ziemons@cern.ch>, 2021

import json
import os
import traceback
import warnings
from typing import TYPE_CHECKING

import py
import pytest
import xdist
import xdist.plugin
from xdist.scheduler.load import LoadScheduling

if TYPE_CHECKING:
    from typing import Union, Sequence


class NoParallelAndLoadScheduling(LoadScheduling):
    def __init__(self, config, log=None):
        super(NoParallelAndLoadScheduling, self).__init__(config=config, log=log)
        self.first_send_tests = True
        self.noparallel_tests_done = False
        self.test_queue = []
        self.noparallel_node = 0

    def _send_tests(self, node, num):
        if self.first_send_tests:
            self.first_send_tests = False
            try:
                config_dict = json.loads(self.collection[0])
                assert type(config_dict) == dict and 'noparallel_tests' in config_dict
                self.pending.pop(0)
                self.config.noparallel_tests = config_dict['noparallel_tests']
                self.noparallel_tests_done = self.config.noparallel_tests == 0
            except (json.JSONDecodeError, TypeError, AssertionError):
                warnings.warn(f"No configuration in first element: {self.collection[0]}")
                traceback.print_exc()
                self.noparallel_tests_done = True

            if not self.noparallel_tests_done:
                self.noparallel_node = node
                # +1 because for remote: only run if we have an item and a next item
                count = min(1 + self.config.noparallel_tests, len(self.pending))
                super(NoParallelAndLoadScheduling, self)._send_tests(node=self.noparallel_node, num=count)
                return

        if not self.noparallel_tests_done:
            self.test_queue.append(dict(node=node, num=num))
            return

        super(NoParallelAndLoadScheduling, self)._send_tests(node=node, num=num)

    def empty_test_queue(self):
        if len(self.test_queue) > 0:
            for kwargs in self.test_queue:
                self._send_tests(**kwargs)
            self.test_queue = []

    def mark_test_complete(self, node, item_index, duration=0):
        if self.noparallel_tests_done:
            super(NoParallelAndLoadScheduling, self).mark_test_complete(node=node, item_index=item_index, duration=duration)
        elif node != self.noparallel_node:
            warnings.warn(f"mark_test_complete on {node} (item {item_index}), but noparallel tests not ready", RuntimeWarning)
            super(NoParallelAndLoadScheduling, self).mark_test_complete(node=node, item_index=item_index, duration=duration)
        else:
            self.node2pending[node].remove(item_index)
            # 1 because +1 above
            if len(self.node2pending[node]) <= 1:
                # resume regular operation
                self.noparallel_tests_done = True
                self.empty_test_queue()
                # for node in self.nodes:
                #     self.check_schedule(node=node)

    def __str__(self):
        ex = super(NoParallelAndLoadScheduling, self).__str__()
        if self.first_send_tests:
            ex += ", initializing"
        else:
            if self.noparallel_tests_done:
                ex += ", parallel tests"
            else:
                ex += f", serial tests (n: {self.config.noparallel_tests}, node: {self.noparallel_node}, queue: {self.node2pending[self.noparallel_node]})"
            if self.test_queue:
                ex += f", parallel test queue: {self.test_queue}"
        if self.pending:
            ex += f", {len(self.pending)} pending test(s)"
        else:
            ex += ", no pending tests"
        return ex


class NoParallelXDist:
    def __init__(self, config):
        self.log = py.log.Producer("noparallelxdist")
        self.config = config
        if not config.option.debug:
            py.log.setconsumer(self.log._keywords, None)

    def pytest_collection_modifyitems(self, config, items: "Sequence[Union[pytest.Item, pytest.Collector]]"):
        if hasattr(config, "workerinput") or config.getoption("numprocesses", 0) > 1:
            # then xdist is running tests parallel
            config.noparallel_tests = 0

            def count_and_sort_noparallel(node: "Union[pytest.Item, pytest.Collector]"):
                # sort noparallel tests before any other
                noparallelmark = list(node.iter_markers("noparallel"))
                if len(noparallelmark) > 0:
                    self.log('found noparallel test:', '; '.join(map(lambda mark: mark.kwargs['reason'], noparallelmark)), node)
                    config.noparallel_tests += 1
                    return 0
                else:
                    return 1

            # write noparallel tests first into items sequence
            items[:] = sorted(items, key=count_and_sort_noparallel)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_finish(self, session):
        if xdist.is_xdist_worker(self):
            config_str = json.dumps({'noparallel_tests': self.config.noparallel_tests})
            config_item = pytest.Item.from_parent(parent=session, name='configuration item', nodeid=config_str)
            session.items[:] = [config_item] + session.items
        yield

    def pytest_xdist_auto_num_workers(self):
        if os.environ.get('GITHUB_ACTIONS', '') == 'true':
            return 4
        return xdist.plugin.pytest_xdist_auto_num_workers()
