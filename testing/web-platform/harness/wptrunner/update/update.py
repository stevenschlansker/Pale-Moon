# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys

from metadata import MetadataUpdateRunner
from sync import SyncFromUpstreamRunner
from tree import GitTree, HgTree, NoVCSTree

from base import Step, StepRunner, exit_clean, exit_unclean
from state import State

def setup_paths(serve_root):
    sys.path.insert(0, os.path.join(serve_root, "tools", "scripts"))

class LoadConfig(Step):
    """Step for loading configuration from the ini file and kwargs."""

    provides = ["sync", "paths", "metadata_path", "tests_path"]

    def create(self, state):
        state.sync = {"remote_url": state.kwargs["remote_url"],
                      "branch": state.kwargs["branch"],
                      "path": state.kwargs["sync_path"]}

        state.paths = state.kwargs["test_paths"]
        state.tests_path = state.paths["/"]["tests_path"]
        state.metadata_path = state.paths["/"]["metadata_path"]

        assert state.tests_path.startswith("/")


class LoadTrees(Step):
    """Step for creating a Tree for the local copy and a GitTree for the
    upstream sync."""

    provides = ["local_tree", "sync_tree"]

    def create(self, state):
        if os.path.exists(state.sync["path"]):
            sync_tree = GitTree(root=state.sync["path"])
        else:
            sync_tree = None

        if GitTree.is_type():
            local_tree = GitTree()
        elif HgTree.is_type():
            local_tree = HgTree()
        else:
            local_tree = NoVCSTree()

        state.update({"local_tree": local_tree,
                      "sync_tree": sync_tree})


class SyncFromUpstream(Step):
    """Step that synchronises a local copy of the code with upstream."""

    def create(self, state):
        if not state.kwargs["sync"]:
            return

        if not state.sync_tree:
            os.mkdir(state.sync["path"])
            state.sync_tree = GitTree(root=state.sync["path"])

        kwargs = state.kwargs
        with state.push(["sync", "paths", "metadata_path", "tests_path", "local_tree", "sync_tree"]):
            state.target_rev = kwargs["rev"]
            state.no_patch = kwargs["no_patch"]
            runner = SyncFromUpstreamRunner(self.logger, state)
            runner.run()


class UpdateMetadata(Step):
    """Update the expectation metadata from a set of run logs"""

    def create(self, state):
        if not state.kwargs["run_log"]:
            return

        kwargs = state.kwargs
        with state.push(["local_tree", "sync_tree", "paths"]):
            state.run_log = kwargs["run_log"]
            state.serve_root = kwargs["serve_root"]
            state.ignore_existing = kwargs["ignore_existing"]
            state.no_patch = kwargs["no_patch"]
            runner = MetadataUpdateRunner(self.logger, state)
            runner.run()


class UpdateRunner(StepRunner):
    """Runner for doing an overall update."""
    steps = [LoadConfig,
             LoadTrees,
             SyncFromUpstream,
             UpdateMetadata]


class WPTUpdate(object):
    def __init__(self, logger, runner_cls=UpdateRunner, **kwargs):
        """Object that controls the running of a whole wptupdate.

        :param runner_cls: Runner subclass holding the overall list of
                           steps to run.
        :param kwargs: Command line arguments
        """
        self.runner_cls = runner_cls
        if kwargs["serve_root"] is None:
            kwargs["serve_root"] = kwargs["test_paths"]["/"]["tests_path"]

        #This must be before we try to reload state
        setup_paths(kwargs["serve_root"])

        self.state = State(logger)
        self.kwargs = kwargs
        self.logger = logger

    def run(self, **kwargs):
        if self.kwargs["abort"]:
            self.abort()
            return exit_clean

        if not self.kwargs["continue"] and not self.state.is_empty():
            self.logger.error("Found existing state. Run with --continue to resume or --abort to clear state")
            return exit_unclean

        if self.kwargs["continue"]:
            if self.state.is_empty():
                self.logger.error("No sync in progress?")
                return exit_clean

            self.kwargs = self.state.kwargs
        else:
            self.state.kwargs = self.kwargs

        update_runner = self.runner_cls(self.logger, self.state)
        rv = update_runner.run()
        if rv in (exit_clean, None):
            self.state.clear()

        return rv

    def abort(self):
        self.state.clear()
