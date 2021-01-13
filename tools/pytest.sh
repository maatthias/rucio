#!/usr/bin/env bash
# Copyright 2021 CERN for the benefit of the ATLAS collaboration.
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

RUCIO_LIB="$(dirname "$0")/../lib"
cd "$RUCIO_LIB/rucio/tests"
if [ -z "$@" ]; then
  echo "Running pytest in lib/rucio/tests"
  ARGS="."
else
  echo "Running pytest with extra arguments: $@"
  ARGS="$@"
fi
export PYTHONPATH="$RUCIO_LIB"
exec python -bb -m pytest -r fExX -p xdist -p ruciopytest.plugin --dist=rucio --numprocesses=auto --timeout=60 "$ARGS"
