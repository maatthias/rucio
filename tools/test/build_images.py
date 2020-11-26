#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2020 CERN
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
# - Benedikt Ziemons <benedikt.ziemons@cern.ch>, 2020

import argparse
import asyncio
import collections
import io
import itertools
import json
import os
import pathlib
import subprocess
import sys
import traceback
from functools import partial
from typing import List, Tuple, Optional

DIST_KEY = "DIST"
BUILD_ARG_KEYS = ["PYTHON"]
BuildArgs = collections.namedtuple('BuildArgs', BUILD_ARG_KEYS)
IMAGE_BUILD_COUNT_LIMIT = 20


def format_args(program, *args):
    return f"{program} {' '.join(map(lambda a: repr(a) if ' ' in a else a, args))}".rstrip()


def imagetag(dist: str, buildargs: "BuildArgs", cache_repo: "Optional[str]" = None) -> str:
    buildargs_tags = '-'.join(map(lambda it: str(it[0]).lower() + str(it[1]).lower(), buildargs._asdict().items()))
    if buildargs_tags:
        buildargs_tags = '-' + buildargs_tags
    tag = f'rucio-autotest:{dist.lower()}{buildargs_tags}'
    if cache_repo:
        tag = cache_repo.lower() + '/' + tag
    return tag


async def build_image(
        name: str,
        dist: str,
        buildargs: "BuildArgs",
        use_podman: bool,
        cache_repo: str,
        no_cache: bool,
        containerfiles_dir: "os.PathLike",
        push_cache: bool,
        logfile=sys.stderr
) -> None:
    cache_args = ()
    if no_cache:
        cache_args = ('--no-cache', '--pull-always' if use_podman else '--pull')
    elif cache_repo:
        args = ('docker', 'pull', name)
        print("Running", format_args(*args), file=logfile, flush=True)
        try:
            await asyncio.create_subprocess_exec(*args, stdout=logfile, stderr=subprocess.STDOUT)
        except Exception:
            traceback.print_exc(file=logfile)
        cache_args = ('--cache-from', name)

    buildfile = pathlib.Path(containerfiles_dir) / f'{dist}.Dockerfile'
    buildargs = map(lambda x: ('--build-arg', f'{x[0]}={x[1]}'), buildargs._asdict().items())
    args = ['docker', 'build', *cache_args, '--file', str(buildfile), '--tag', name, *itertools.chain.from_iterable(buildargs), '.']
    print("Running", format_args('docker', *args), file=logfile, flush=True)
    await asyncio.create_subprocess_exec(*args, stdout=logfile, stderr=subprocess.STDOUT)
    print("Finished building image", name, file=logfile, flush=True)

    if push_cache:
        args = ('docker', 'push', name)
        print("Running", " ".join(args), file=logfile, flush=True)
        await asyncio.create_subprocess_exec(*args, stdout=logfile, stderr=subprocess.STDOUT)


def main():
    loop = asyncio.get_event_loop()
    matrix = json.load(sys.stdin)
    matrix = (matrix,) if isinstance(matrix, dict) else matrix

    parser = argparse.ArgumentParser(description='Build images according to the test matrix read from stdin.')
    parser.add_argument('buildfiles_dir', metavar='build directory', type=str, default='.',
                        help='the directory of Dockerfiles')
    parser.add_argument('-o', '--output', dest='output', type=str, choices=['list', 'dict'], default='dict',
                        help='the output of this command')
    parser.add_argument('-n', '--build-no-cache', dest='build_no_cache', action='store_true',
                        help='build images without cache')
    parser.add_argument('-r', '--cache-repo', dest='cache_repo', type=str, default='ghcr.io/rucio/rucio',
                        help='use the following cache repository, like ghcr.io/USER/REPO')
    parser.add_argument('-p', '--push-cache', dest='push_cache', action='store_true',
                        help='push the images to the cache repo')
    script_args = parser.parse_args()

    filter_build_args = partial(map, lambda argdict: {arg: val for arg, val in argdict.items() if arg in BUILD_ARG_KEYS})
    make_buildargs = partial(map, lambda argdict: BuildArgs(**argdict))
    dist_buildargs_generators = map(lambda t: ((t[0], ba) for ba in set(make_buildargs(filter_build_args(t[1])))),
                                    itertools.groupby(matrix, lambda d: d[DIST_KEY]))
    flattened_dist_buildargs = list(itertools.chain.from_iterable(dist_buildargs_generators))  # type: List[Tuple[str, BuildArgs]]
    use_podman = 'USE_PODMAN' in os.environ and os.environ['USE_PODMAN'] == '1'

    if len(flattened_dist_buildargs) >= IMAGE_BUILD_COUNT_LIMIT:
        print(f"Won't build {len(flattened_dist_buildargs)} images (> {IMAGE_BUILD_COUNT_LIMIT}).\n"
              f"Either there was a problem with the test matrix or the limit should be increased.",
              file=sys.stderr)
        sys.exit(2)

    build_futures = list()
    images = dict()
    for dist, buildargs in flattened_dist_buildargs:
        name = imagetag(dist=dist, buildargs=buildargs, cache_repo=script_args.cache_repo)
        async def wrap_build():
            memlog = io.StringIO()
            try:
                await build_image(
                    name=name,
                    dist=dist,
                    buildargs=buildargs,
                    use_podman=use_podman,
                    cache_repo=script_args.cache_repo,
                    no_cache=script_args.build_no_cache,
                    containerfiles_dir=script_args.buildfiles_dir,
                    push_cache=script_args.push_cache,
                    logfile=memlog,
                )
                error = None
            except Exception as e:
                error = e
            return {'name': name, 'log': memlog, 'error': error}

        build_futures.append(asyncio.ensure_future(wrap_build()))
        images[name] = {DIST_KEY: dist, **buildargs._asdict()}

    async def join():
        for future in asyncio.as_completed(build_futures):
            wrapper_result = await future

            sys.stderr.write(f"\nbuild '{name}' output:\n")
            sys.stderr.writelines(wrapper_result['log'].readlines())
            bufferend = wrapper_result['log'].read()
            if bufferend:
                sys.stderr.write(bufferend)
                if bufferend[-1] != "\n":
                    sys.stderr.write("%\n")
            sys.stderr.flush()
            wrapper_result['log'].close()

            if wrapper_result['error']:
                error = wrapper_result['error']
                print(f"building '{name}' errored with {traceback.format_exception_only(error.__class__, error)}", file=sys.stderr, flush=True)
            else:
                print(f"building '{name}' complete", file=sys.stderr, flush=True)

    loop.run_until_complete(join())

    if script_args.output == 'dict':
        json.dump(images, sys.stdout)
    elif script_args.output == 'list':
        json.dump(list(images.keys()), sys.stdout)


if __name__ == "__main__":
    main()
