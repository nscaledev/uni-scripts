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
import glob
import os
import subprocess
import time
import typing
import re
from typing import TextIO

import semver

@contextlib.contextmanager
def pushd(directory: str) -> None:
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
    return f'v{version.major}.{version.minor}.{version.patch}{"-" + version.prerelease if version.prerelease else ""}'

class Component:
    """
    Wraps up a single component in the system in a generic type.
    """

    def __init__(self, name: str, dependencies: list[str] = None, precommit_hook: typing.Callable[[], None] = None) -> None:
        self.name = name
        self.dependencies = dependencies if dependencies else []
        self.precommit_hook = precommit_hook

    def validate(self) -> None:
        """
        validates whether the git trees are in a sane state.
        TODO: check whether we are at the remote HEAD.
        """
        print(f"\033[32;1mValidating\033[0m {self.name} ...")

        with pushd(self.name):
            branch = subprocess.check_output(['git', 'branch', '--show-current']).decode('utf-8').strip()
            if branch != 'main':
                raise RuntimeError(f'component {self.name} is not checked out to main')

    def _update_chart_contents(self, file: TextIO, version: semver.Version) -> str:
        """
        Replace the versions in the given chart file.
        """
        lines: list[str] = []

        while True:
            line = file.readline()
            if not line:
                break

            m = re.match(r'(version|appVersion):', line)
            if m:
                line = f'{m.group(1)}: {canonical_version(version)}\n'

            lines.append(line)

        return ''.join(lines)

    def _update_chart(self, path: str, version: semver.Version) -> None:
        """
        Replace the versions in the given chart file.
        """
        with open(path, 'r', encoding="utf-8") as chart:
            contents = self._update_chart_contents(chart, version)

        with open(path, 'w', encoding="utf-8") as chart:
            chart.write(contents)

    def _update_openapi_contents(self, file: TextIO, version: semver.Version) -> str:
        """
        Replace the versions in the given openapi file.
        """
        lines: list[str] = []

        while True:
            line = file.readline()
            if not line:
                break

            m = re.match(r'(\s+version):\s+\d+(\.\d+){2}', line)
            if m:
                line = f'{m.group(1)}: {str(version)}\n'

            lines.append(line)

        return ''.join(lines)

    def _update_openapi(self, path: str, version: semver.Version) -> None:
        """
        Replace the versions in the given openapi file.
        """
        with open(path, 'r', encoding="utf-8") as chart:
            contents = self._update_openapi_contents(chart, version)

        with open(path, 'w', encoding="utf-8") as chart:
            chart.write(contents)

    def release(self, version: semver.Version) -> None:
        """
        Performs a full or release candidate release of the component.
        """
        print(f"\033[32;1mReleasing\033[0m {self.name} ...")

        with pushd(self.name):
            print("\033[1mUpdating Helm\033[0m ...")
            matches = glob.glob('charts/**/Chart.yaml')
            if len(matches) != 1:
                raise RuntimeError(f'failed to find Chart.yaml for component {self.name}')

            self._update_chart(matches[0], version)

            if self.dependencies:
                print("\033[1mUpdating Go Dependencies\033[0m ...")
                for dependency in self.dependencies:
                    subprocess.check_call(['go', 'get', f'github.com/unikorn-cloud/{dependency}@{canonical_version(version)}'])

                subprocess.check_call(['go', 'mod', 'tidy'])

            if not version.prerelease:
                print("\033[1mUpdating OpenAPI\033[0m ...")
                matches = glob.glob('pkg/openapi/*.spec.yaml')
                if len(matches) > 1:
                    raise RuntimeError(f'expected to find 0 or 1 OpenAPI spec.yaml for component {self.name}')
                if matches:
                    self._update_openapi(matches[0], version)
                    subprocess.check_call(['make', 'validate'])

                if self.precommit_hook:
                    print("\033[1mCalling Precommit Hook\033[0m ...")
                    self.precommit_hook()

            branch = 'bump'
            tag = canonical_version(version)
            title = f'Version {tag}'

            print("\033[1mCommitting Update\033[0m ...")
            subprocess.check_call(['git', 'checkout', '-b', branch])
            subprocess.check_call(['git', 'add', '.'])
            subprocess.check_call(['git', 'commit', '-m', title])
            subprocess.check_call(['git', 'push', '-f', 'origin', branch])
            subprocess.check_call(['gh', 'pr', 'create', '--head', branch, '--title', title, '--body', ''])

            print("\033[1mMerge\033[0m ...")
            input("Please get the pull request approved and merged, then hit ENTER to continue")

            print("\033[1mRelease\033[0m ...")
            subprocess.check_call(['git', 'checkout', 'main'])
            subprocess.check_call(['git', 'pull'])
            subprocess.check_call(['git', 'tag', tag])
            subprocess.check_call(['git', 'push', 'origin', tag])
            subprocess.check_call(['git', 'branch', '-D', branch])

def ui_npm_update():
    """
    Updates the UI with the full release's OpenAPI clients.
    """
    subprocess.check_call(['npm', 'run', 'openapi:identity'])
    subprocess.check_call(['npm', 'run', 'openapi:region'])
    subprocess.check_call(['npm', 'run', 'openapi:compute'])
    subprocess.check_call(['npm', 'run', 'openapi:kubernetes'])


COMPONENTS = [
        Component('core'),
        Component('identity', dependencies=['core']),
        Component('region', dependencies=['core', 'identity']),
        Component('compute', dependencies=['core', 'identity', 'region']),
        Component('kubernetes', dependencies=['core', 'identity', 'region']),
        Component('ui', precommit_hook=ui_npm_update),
]

def components_from(step: str) -> list[Component]:
    """
    Returns all components from the given step
    """

    if step == None:
        return COMPONENTS

    index = next((i for i, c in enumerate(COMPONENTS) if c.name == step), -1)

    return COMPONENTS[index:]


class SemverNormalizeAction(argparse.Action):
    """
    Semvers should start with 'v', unless you are python...
    """
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        if values[0] == 'v':
            values = values[1:]
        setattr(namespace, self.dest, values)

def main():
    """
    Main entry point.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True, action=SemverNormalizeAction)
    parser.add_argument('--from-step', choices=[x.name for x in COMPONENTS])

    args = parser.parse_args()

    version = semver.Version.parse(args.version)

    components = components_from(args.from_step)

    for component in components:
        component.validate()

    for component in components:
        component.release(version)

if __name__ == '__main__':
    main()
