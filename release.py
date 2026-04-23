#!/usr/bin/env python3

"""
Platform release script.

Iterates through all core repositories located in a local working directory,
and follows the documented release proceedure.

Prerequisites:

    * Go tookchain
    * NPM
    * Git
    * GitHub CLI
"""

# pylint: disable=line-too-long

import argparse
import contextlib
from dataclasses import dataclass, field
import glob
import os
from collections.abc import Callable, Iterator
import subprocess
import time
import re
from typing import TextIO

import semver

@contextlib.contextmanager
def pushd(directory: str) -> Iterator[None]:
    """
    Allows a code block to be temporarily run in a new directory, much
    like how it does in a shell.
    """
    prev = os.getcwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(prev)

def canonical_version(version: semver.Version) -> str:
    """
    Returns the canonical verson, used by tags, from a semanic version.
    """
    return f'v{version.major}.{version.minor}.{version.patch}{"-" + version.prerelease if version.prerelease else ""}{"+" + version.build if version.build else ""}'

def release_branch(version: semver.Version) -> str:
    """
    Returns the release branch for a semanic version in the form vMAJOR.MINOR.x.
    """
    return f'v{version.major}.{version.minor}.x'

def run(*args: str, **kwargs) -> None:
    """
    Run a subprocess and raise if it fails.
    """
    subprocess.check_call(list(args), **kwargs)

def capture(*args: str) -> str:
    """
    Run a subprocess and return stripped stdout.
    """
    return subprocess.check_output(list(args), text=True).strip()

def rewrite_file(path: str, update: Callable[[TextIO], str]) -> None:
    """
    Read a file, transform its content, then write it back.
    """
    with open(path, 'r', encoding='utf-8') as file:
        contents = update(file)

    with open(path, 'w', encoding='utf-8') as file:
        file.write(contents)

@dataclass(slots=True)
class Component:
    """
    Wraps up a single component in the system in a generic type.
    """

    name: str
    dependencies: list[str] = field(default_factory=list)
    precommit_hook: Callable[[], None] | None = None

    def validate(self, version: semver.Version) -> None:
        """
        validates whether the git trees are in a sane state.
        TODO: check whether we are at the remote HEAD.
        """
        print(f"\033[32;1mValidating\033[0m {self.name} ...")


        with pushd(self.name):
            # Ensure our view of the remote is up to date...
            run('git', 'fetch', 'origin')

            rel_branch = release_branch(version)
            remote_branch = f'origin/{rel_branch}'

            def remote_branch_exists() -> bool:
                try:
                    run(
                        'git', 'rev-parse', '--verify', '--quiet', f'refs/remotes/{remote_branch}',
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return True
                except subprocess.CalledProcessError:
                    return False

            # We either need to be on the release branch already...
            branch = capture('git', 'branch', '--show-current')
            if branch != rel_branch:
                # Or be an ancestor of main.
                try:
                    run('git', 'merge-base', '--is-ancestor', 'HEAD', 'main')
                except subprocess.CalledProcessError as exc:
                    raise RuntimeError(f'component {self.name} is not checked out to an ancestor of main main or {rel_branch}') from exc

                # If we are on main, create a new branch and push before we make any changes.
                run('git', 'checkout', '-b', rel_branch)
                run('git', 'push', 'origin', rel_branch)
            else:
                # If the remote branch does not exist yet, publish it now so the
                # rest of the release flow can target it.
                if not remote_branch_exists():
                    run('git', 'push', '-u', 'origin', rel_branch)

                # Ensure that the remote is an ancestor of our local branch as we
                # may have cherry-picked commits in it, and don't want to erase history!
                run('git', 'merge-base', '--is-ancestor', remote_branch, 'HEAD')

    def _update_chart_contents(self, file: TextIO, version: semver.Version) -> str:
        """
        Replace the versions in the given chart file.
        """
        lines: list[str] = []

        for line in file:
            m = re.match(r'(version|appVersion):', line)
            if m:
                line = f'{m.group(1)}: {canonical_version(version)[1:]}\n'

            lines.append(line)

        return ''.join(lines)

    def _update_chart(self, path: str, version: semver.Version) -> None:
        """
        Replace the versions in the given chart file.
        """
        rewrite_file(path, lambda chart: self._update_chart_contents(chart, version))

    def _update_openapi_contents(self, file: TextIO, version: semver.Version) -> str:
        """
        Replace the versions in the given openapi file.
        """
        lines: list[str] = []

        for line in file:
            m = re.match(r'(\s+version):\s+\d+(\.\d+){2}', line)
            if m:
                line = f'{m.group(1)}: {version}\n'

            lines.append(line)

        return ''.join(lines)

    def _update_openapi(self, path: str, version: semver.Version) -> None:
        """
        Replace the versions in the given openapi file.
        """
        rewrite_file(path, lambda chart: self._update_openapi_contents(chart, version))

    def release(self, version: semver.Version) -> None:
        """
        Performs a full or release candidate release of the component.
        """
        print(f"\033[32;1mReleasing\033[0m {self.name} ...")

        with pushd(self.name):
            print("\033[1mUpdating Helm\033[0m ...")
            matches = glob.glob(f"charts/{self.name}/Chart.yaml")
            if len(matches) != 1:
                raise RuntimeError(f'failed to find Chart.yaml for component {self.name}')

            self._update_chart(matches[0], version)

            if self.dependencies:
                print("\033[1mUpdating Go Dependencies\033[0m ...")
                for dependency in self.dependencies:
                    run('go', 'get', f'github.com/unikorn-cloud/{dependency}@{canonical_version(version)}')

                run('go', 'mod', 'tidy')

            if not version.prerelease:
                print("\033[1mUpdating OpenAPI\033[0m ...")
                matches = glob.glob('pkg/openapi/*.spec.yaml')
                if len(matches) > 1:
                    raise RuntimeError(f'expected to find 0 or 1 OpenAPI spec.yaml for component {self.name}')
                if matches:
                    self._update_openapi(matches[0], version)
                    run('make', 'validate')

            if self.precommit_hook:
                print("\033[1mCalling Precommit Hook\033[0m ...")
                self.precommit_hook()

            branch = 'bump'
            tag = canonical_version(version)
            title = f'Version {tag}'
            rel_branch = release_branch(version)

            print("\033[1mCommitting Update\033[0m ...")
            run('git', 'checkout', '-b', branch)
            run('git', 'add', '.')
            run('git', 'commit', '-m', title)
            run('git', 'push', '-f', 'origin', branch)
            run('gh', 'pr', 'create', '--base', rel_branch, '--head', branch, '--fill')

            print("\033[1mPerforming Status Checks\033[0m ...")
            # Make sure to give the status checks time to start...
            # If it breaks here, then it's probably due to a change that isn't backards
            # compatible.  You're probably best manually patching it for now and then
            # finishing off the rest of this function by hand and continuing --from the
            # next repository.
            time.sleep(30)
            run('gh', 'pr', 'checks', '--watch')

            print("\033[1mMerge\033[0m ...")
            input("Please get the pull request approved and merged, then hit ENTER to continue")

            print("\033[1mRelease\033[0m ...")
            run('git', 'checkout', rel_branch)
            run('git', 'pull', 'origin', rel_branch)
            run('git', 'tag', tag)
            run('git', 'push', 'origin', tag)
            run('git', 'branch', '-D', branch)

def ui_npm_update():
    """
    Updates the UI with the full release's OpenAPI clients.
    """
    run('npm', 'run', 'openapi:identity')
    run('npm', 'run', 'openapi:region')
    run('npm', 'run', 'openapi:compute')
    run('npm', 'run', 'openapi:kubernetes')


COMPONENTS = [
        Component('core'),
        Component('identity', dependencies=['core']),
        Component('region', dependencies=['core', 'identity']),
        Component('compute', dependencies=['core', 'identity', 'region']),
        Component('kubernetes', dependencies=['core', 'identity', 'region']),
        # If this fails, then someone has probably made a breaking API change
        # that needs to be communicated to every possible client... Realistically
        # that's not going to happen, so talk to the engineer responsible!
        Component('ui', precommit_hook=ui_npm_update),
]

def components_from(step: str | None) -> list[Component]:
    """
    Returns all components from the given step
    """

    if step is None:
        return COMPONENTS

    index = next((i for i, c in enumerate(COMPONENTS) if c.name == step), -1)
    if index == -1:
        raise ValueError(f'unknown component {step}')

    return COMPONENTS[index:]

def main():
    """
    Main entry point.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--from-step', choices=[x.name for x in COMPONENTS])

    args = parser.parse_args()

    version = semver.Version.parse(args.version.removeprefix('v'))

    components = components_from(args.from_step)

    for component in components:
        component.validate(version)

    for component in components:
        component.release(version)

if __name__ == '__main__':
    main()
