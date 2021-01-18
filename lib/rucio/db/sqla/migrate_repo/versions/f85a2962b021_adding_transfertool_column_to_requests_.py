# Copyright 2013-2020 CERN for the benefit of the ATLAS collaboration.
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
# - John Doe <john.doe@asdf.com>, 2020

''' adding transfertool column to requests table '''

import sqlalchemy as sa

from alembic import context
from alembic.op import execute

# Alembic revision identifiers
revision = 'f85a2962b021'
down_revision = 'd23453595260'


def upgrade():
    '''
    Upgrade the database to this revision
    '''

    if context.get_context().dialect.name in ['oracle', 'postgresql', 'mysql']:
        schema = context.get_context().version_table_schema + '.' if context.get_context().version_table_schema else ''
        add_column('requests', sa.Column('transfer_tool', sa.String(64)), schema=schema)


def downgrade():
    '''
    Downgrade the database to the previous revision
    '''

    if context.get_context().dialect.name in ['oracle', 'postgresql', 'mysql']:
        schema = context.get_context().version_table_schema + '.' if context.get_context().version_table_schema else ''
        drop_column('requests', 'transfer_tool', schema=schema)
