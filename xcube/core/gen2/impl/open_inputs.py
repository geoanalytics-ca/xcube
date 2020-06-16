# The MIT License (MIT)
# Copyright (c) 2020 by the xcube development team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
from typing import Sequence, Optional, Callable

from xcube.core.gen2.request import InputConfig
from xcube.core.gen2.request import GenConfig
from xcube.core.store import new_data_opener
from xcube.core.store import new_data_store
from xcube.util.extension import ExtensionRegistry


def open_inputs(input_configs: Sequence[InputConfig],
                gen_config: GenConfig,
                progress_monitor: Callable,
                extension_registry: Optional[ExtensionRegistry] = None):
    data_resources = []
    if input_configs:
        gen_params = gen_config.gen_params if gen_config else {}
        for input_config in input_configs:
            open_params = {}
            if input_config.store_id:
                opener = new_data_store(input_config.store_id,
                                        **input_config.store_params,
                                        extension_registry=extension_registry)
                open_params.update(opener_id=input_config.opener_id,
                                   **input_config.open_params)
            else:
                opener = new_data_opener(input_config.opener_id,
                                         extension_registry=extension_registry)
                open_params.update(**input_config.store_params,
                                   **input_config.open_params)
            open_params_schema = opener.get_open_data_params_schema(input_config.data_id)
            gen_params_subset = {k: v for k, v in gen_params.items() if k in open_params_schema.properties}
            data = opener.open_data(input_config.data_id, **open_params, **gen_params_subset)
            data_resources.append(data)

    return data_resources
