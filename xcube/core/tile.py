# The MIT License (MIT)
# Copyright (c) 2019 by the xcube development team and contributors
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

import logging
from typing import Any, Mapping, MutableMapping, Sequence, Hashable, Type, Dict, Optional, Tuple, Union

import numpy as np
import pandas as pd
import xarray as xr

from xcube.core.mldataset import MultiLevelDataset
from xcube.core.schema import get_dataset_xy_var_names
from xcube.util.cache import Cache
from xcube.util.perf import measure_time_cm
from xcube.util.tiledimage import ColorMappedRgbaImage
from xcube.util.tiledimage import ColorMappedRgbaImage2
from xcube.util.tiledimage import DEFAULT_COLOR_MAP_NAME
from xcube.util.tiledimage import DEFAULT_COLOR_MAP_VALUE_RANGE
from xcube.util.tiledimage import NdarrayImage
from xcube.util.tiledimage import TiledImage
from xcube.util.tiledimage import TransformArrayImage

_LOG = logging.getLogger('xcube')


def get_ml_dataset_tile(ml_dataset: MultiLevelDataset,
                        var_name: str,
                        x: int,
                        y: int,
                        z: int,
                        labels: Mapping[str, Any] = None,
                        labels_are_indices: bool = False,
                        cmap_name: Union[str, Sequence[str]] = None,
                        cmap_vmin: Union[float, Sequence[float]] = None,
                        cmap_vmax: Union[float, Sequence[float]] = None,
                        image_cache: MutableMapping[str, TiledImage] = None,
                        tile_cache: Cache = None,
                        tile_comp_mode: int = 0,
                        trace_perf: bool = False,
                        exception_type: Type[Exception] = ValueError):
    measure_time = measure_time_cm(logger=_LOG, disabled=not trace_perf)

    dataset = ml_dataset.get_dataset(ml_dataset.num_levels - 1 - z)
    var = dataset[var_name]

    labels = labels or {}

    ds_id = hex(id(ml_dataset))
    image_id = '-'.join(map(str, [ds_id, z, var_name, cmap_name, cmap_vmin, cmap_vmax]
                            + [f'{dim_name}={dim_value}' for dim_name, dim_value in labels.items()]))

    if image_cache and image_id in image_cache:
        image = image_cache[image_id]
    else:
        no_data_value = var.attrs.get('_FillValue')
        valid_range = get_var_valid_range(var)
        cmap_name, cmap_vmin, cmap_vmax = get_var_cmap_params(var, cmap_name, cmap_vmin, cmap_vmax, valid_range)
        array = get_var_2d_array(var, labels, labels_are_indices, exception_type, ml_dataset.ds_id)
        tile_grid = ml_dataset.tile_grid

        if not tile_comp_mode:
            image = NdarrayImage(array.values,
                                 image_id=f'ndai-{image_id}',
                                 tile_size=tile_grid.tile_size,
                                 trace_perf=trace_perf)
            image = TransformArrayImage(image,
                                        image_id=f'tai-{image_id}',
                                        flip_y=tile_grid.inv_y,
                                        force_masked=True,
                                        no_data_value=no_data_value,
                                        valid_range=valid_range,
                                        trace_perf=trace_perf)
            image = ColorMappedRgbaImage(image,
                                         image_id=f'rgb-{image_id}',
                                         cmap_range=(cmap_vmin, cmap_vmax),
                                         cmap_name=cmap_name,
                                         encode=True,
                                         format='PNG',
                                         tile_cache=tile_cache,
                                         trace_perf=trace_perf)
        else:
            image = ColorMappedRgbaImage2(array.values,
                                          image_id=f'rgb-{image_id}',
                                          tile_size=tile_grid.tile_size,
                                          cmap_range=(cmap_vmin, cmap_vmax),
                                          cmap_name=cmap_name,
                                          encode=True,
                                          format='PNG',
                                          flip_y=tile_grid.inv_y,
                                          no_data_value=no_data_value,
                                          valid_range=valid_range,
                                          tile_cache=tile_cache,
                                          trace_perf=trace_perf)

        if image_cache:
            image_cache[image_id] = image

        if trace_perf:
            _LOG.info(f'Created tiled image {image_id!r} of size {image.size} with tile grid:')
            _LOG.info(f'  num_levels: {tile_grid.num_levels}')
            _LOG.info(f'  num_level_zero_tiles: {tile_grid.num_tiles(0)}')
            _LOG.info(f'  tile_size: {tile_grid.tile_size}')
            _LOG.info(f'  geo_extent: {tile_grid.geo_extent}')
            _LOG.info(f'  inv_y: {tile_grid.inv_y}')

    if trace_perf:
        _LOG.info(f'>>> tile {image_id}/{z}/{y}/{x}')

    with measure_time() as measured_time:
        tile = image.get_tile(x, y)

    if trace_perf:
        _LOG.info(f'<<< tile {image_id}/{z}/{y}/{x}: took ' + '%.2f seconds' % measured_time.duration)

    return tile


def get_var_2d_array(var: xr.DataArray,
                     labels: Dict[str, Any],
                     labels_are_indices: bool,
                     exception_type: Type[Exception],
                     ds_id: str) -> xr.DataArray:
    # Make sure we work with 2D image arrays only
    if var.ndim == 2:
        assert len(labels) == 0
        array = var
    elif var.ndim > 2:
        assert len(labels) == var.ndim - 2
        if labels_are_indices:
            array = var.isel(**labels)
        else:
            array = var.sel(method='nearest', **labels)
    else:
        raise exception_type(f'Variable "{var.name}" of dataset "{ds_id}" '
                             'must be an N-D Dataset with N >= 2, '
                             f'but "{var.name}" is only {var.ndim}-D')
    array.load()
    return array


def get_var_cmap_params(var: xr.DataArray,
                        cmap_name: Optional[str],
                        cmap_vmin: Optional[float],
                        cmap_vmax: Optional[float],
                        valid_range: Optional[Tuple[float, float]]):
    if cmap_name is None:
        cmap_name = var.attrs.get('color_bar_name')
        if cmap_name is None:
            cmap_name = DEFAULT_COLOR_MAP_NAME
    if cmap_vmin is None:
        cmap_vmin = var.attrs.get('color_value_min')
        if cmap_vmin is None and valid_range is not None:
            cmap_vmin = valid_range[0]
        if cmap_vmin is None:
            cmap_vmin = DEFAULT_COLOR_MAP_VALUE_RANGE[0]
    if cmap_vmax is None:
        cmap_vmax = var.attrs.get('color_value_max')
        if cmap_vmax is None and valid_range is not None:
            cmap_vmax = valid_range[1]
        if cmap_vmax is None:
            cmap_vmax = DEFAULT_COLOR_MAP_VALUE_RANGE[1]
    return cmap_name, cmap_vmin, cmap_vmax


def get_var_valid_range(var: xr.DataArray) -> Optional[Tuple[float, float]]:
    valid_min = None
    valid_max = None
    valid_range = var.attrs.get('valid_range')
    if valid_range:
        try:
            valid_min, valid_max = map(float, valid_range)
        except (TypeError, ValueError):
            pass
    if valid_min is None:
        valid_min = var.attrs.get('valid_min')
    if valid_max is None:
        valid_max = var.attrs.get('valid_max')
    if valid_min is None and valid_max is None:
        valid_range = None
    elif valid_min is not None and valid_max is not None:
        valid_range = valid_min, valid_max
    elif valid_min is None:
        valid_range = -np.inf, valid_max
    else:
        valid_range = valid_min, +np.inf
    return valid_range


def parse_non_spatial_labels(raw_labels: Mapping[str, str],
                             dims: Sequence[Hashable],
                             coords: Mapping[Hashable, xr.DataArray],
                             allow_slices: bool = False,
                             exception_type: type = ValueError) -> Mapping[str, Any]:
    xy_var_names = get_dataset_xy_var_names(coords, must_exist=False)
    if xy_var_names is None:
        raise exception_type(f'missing spatial coordinates')
    xy_dims = set(coords[xy_var_name].dims[0] for xy_var_name in xy_var_names)

    def to_datetime(datetime_str: str, dim_var: xr.DataArray):
        if datetime_str == 'current':
            return dim_var[-1]
        else:
            return pd.to_datetime(datetime_str)

    parsed_labels = {}
    for dim in dims:
        if dim in xy_dims:
            continue
        dim_var = coords[dim]
        label_str = raw_labels.get(dim)
        try:
            if label_str is None:
                label = dim_var.values[0]
            elif label_str == 'current':
                label = dim_var.values[-1]
            else:
                if '/' in label_str:
                    label_strs = tuple(label_str.split('/', maxsplit=1))
                else:
                    label_strs = (label_str,)
                if np.issubdtype(dim_var.dtype, np.floating):
                    labels = tuple(map(float, label_strs))
                elif np.issubdtype(dim_var.dtype, np.integer):
                    labels = tuple(map(int, label_strs))
                elif np.issubdtype(dim_var.dtype, np.datetime64):
                    labels = tuple(to_datetime(label, dim_var) for label in label_strs)
                else:
                    raise exception_type(f'unable to parse value {label_str!r} into a {dim_var.dtype!r}')
                if len(labels) == 1:
                    label = labels[0]
                else:
                    if allow_slices:
                        label = slice(labels[0], labels[1])
                    elif np.issubdtype(dim_var.dtype, np.integer):
                        label = labels[0] + (labels[1] - labels[0]) // 2
                    else:
                        label = labels[0] + (labels[1] - labels[0]) / 2
            parsed_labels[str(dim)] = label
        except ValueError as e:
            raise exception_type(f'{label_str!r} is not a valid value for dimension {dim!r}') from e

    return parsed_labels
