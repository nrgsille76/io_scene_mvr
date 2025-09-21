# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#                         2020 Hugo Aboud
#                         2020 Vanous
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Import is based on using information from BlenderDMX source-code
# (https://github.com/open-stage/blender-dmx)


import os
import bpy
import copy
import math
import pygdtf
import random
import mathutils
import uuid as pyuid
from types import SimpleNamespace
from io_scene_3ds.import_3ds import load_3ds
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from pathlib import Path


rangeData = {}
targetData = {}
channelData = {}
movingHead = {"Pan", "Tilt"}
colorMix = {"R", "G", "B", "C", "M", "Y"}


class FixtureMode(object):
    """Class is representing a fixture mode."""

    def __init__(self, profile, number):
        mode_list = profile.dmx_modes.as_dict()
        self._name = next(
            (md.get("name") for md in mode_list if md.get("name")
             and md.get("mode_id") == number), "Standard")

    @property
    def name(self):
        return self._name

    def __str__(self):
        return f"{self.name}"


def get_folder_path():
    """Get the path to asset folder."""
    folder_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(folder_path, "assets", "gdtf")


def remove_suffix(name):
    """Remove file suffix from name."""
    free_name = f"{name}"
    if (isinstance(name, str) and
        len(name) >= 5 and name[-5] == "." or
        len(name) >= 4 and name[-4] == "."
    ):
        dot_split = name.split(".")
        if len(dot_split) > 2:
            free_name = ".".join(dot_split[:-1])
        else:
            free_name = dot_split[0]

    return free_name


def cleanup_name(geometry):
    """Clean up spaces and underscores."""
    name = geometry.name.replace(" ", "_")
    root_name = ""
    if hasattr(geometry, "reference_root"):
        root_name = f"{geometry.reference_root.replace(' ', '_')}_"
    return f"{root_name}{name}"


def create_fixture_name(name, space="@"):
    """Create a proper fixture name."""
    if "@" not in name:
        return Path(name).stem
    split_name = name.split("@")
    if len(split_name) > 2:
        manufacturer = split_name[0]
        fixture_name = split_name[1]
        clean_name = manufacturer + space + fixture_name
    elif len(split_name) > 1:
        manufacturer = split_name[0]
        clean_name = Path(split_name[1]).stem
    else:
        clean_name = Path(split_name[0]).stem
    return clean_name


def create_fixture_id(item, fixture_id):
    """Create a fixture ID."""
    item["Fixture ID"] = fixture_id
    item.id_properties_ensure()
    item_property = item.id_properties_ui("Fixture ID")
    item_property.update(default=0, min=0, max=4096, soft_min=0, soft_max=4096)


def get_fixture_address(fixture_id):
    """Get a free address from fixture ID."""
    dmx_break = 0
    universe = abs((int(fixture_id) - 1)) // 512 + 1
    address = abs((int(fixture_id) - 1)) % 512 + 1

    return dmx_break, universe, address


def create_gdtf_props(item, name):
    """Create GDTF custom properties."""
    split_name = name.split("@")
    if len(split_name) > 2:
        item["Company"] = split_name[0]
        fixture_name = split_name[1]
    elif len(split_name) > 1:
        item["Company"] = split_name[0]
        fixture_name = remove_suffix(split_name[1])
    else:
        item["Company"] = "Custom"
        fixture_name = remove_suffix(name)
    item["Fixture Name"] = fixture_name


def create_dimmer_driver(item, target, power):
    """Create a driver for dimmer intensity."""
    dimmer_val = "energy" if item.type == 'SPOT' else "default_value"
    dimmer_curve = item.driver_add(dimmer_val)
    dimmer_drive = dimmer_curve.driver
    dimmer_drive.type = 'SCRIPTED'
    dimmer_var = dimmer_drive.variables.new()
    dimmer_var.name = "dim"
    dimmer_target = dimmer_var.targets[0]
    dimmer_target.id = target
    dimmer_target.data_path = '["Intensity"]'
    dimmer_drive.expression = "power * dim * 0.01" if item.type == 'SPOT' else "dim * 0.01"
    if item.type == 'SPOT':
        energy_var = dimmer_drive.variables.new()
        energy_var.name = "power"
        energy_target = energy_var.targets[0]
        energy_target.id = power
        energy_target.data_path = '["Power"]'


def create_color_driver(item, target, path):
    """Create a driver for RGB colorpicker."""
    color_val = "color" if item.type == 'SPOT' else "default_value"
    red_curve = item.driver_add(color_val, 0)
    green_curve = item.driver_add(color_val, 1)
    blue_curve = item.driver_add(color_val, 2)
    red_drive = red_curve.driver
    green_drive = green_curve.driver
    blue_drive = blue_curve.driver
    red_drive.type = green_drive.type = blue_drive.type = 'AVERAGE'
    red_var = red_drive.variables.new()
    green_var = green_drive.variables.new()
    blue_var = blue_drive.variables.new()
    red_var.name = "red"
    green_var.name = "green"
    blue_var.name = "blue"
    red_target = red_var.targets[0]
    green_target = green_var.targets[0]
    blue_target = blue_var.targets[0]
    red_target.id = green_target.id = blue_target.id = target
    red_target.data_path = f'["{path}"][0]'
    green_target.data_path = f'["{path}"][1]'
    blue_target.data_path = f'["{path}"][2]'


def create_ctc_driver(item, target):
    """Create a driver for color temperature."""
    item_data = item.data
    temperature = item.get("Temperature")
    ctc_node = item_data.node_tree.nodes.get("Color Temperature")
    ctc_curve = ctc_node.inputs[0].driver_add("default_value")
    ctc_drive = ctc_curve.driver
    ctc_drive.type = 'AVERAGE'
    ctc_var = ctc_drive.variables.new()
    ctc_var.name = "ctc"
    ctc_target = ctc_var.targets[0]
    ctc_target.id = target
    ctc_target.use_fallback_value = True
    ctc_target.fallback_value = temperature
    ctc_target.data_path = '["Light CTC"]'
    if hasattr(item_data, "temperature"):
        item_data.use_temperature = True
        tmp_curve = item_data.driver_add("temperature")
        tmp_drive = tmp_curve.driver
        tmp_drive.type = 'AVERAGE'
        tmp_var = tmp_drive.variables.new()
        tmp_var.name = "ctc"
        tmp_target = tmp_var.targets[0]
        tmp_target.id = target
        tmp_target.use_fallback_value = True
        tmp_target.fallback_value = temperature
        tmp_target.data_path = '["Light CTC"]'


def create_factor_driver(item, target):
    """Create a driver for frost factor."""
    blend_curve = item.data.driver_add("spot_blend")
    blend_drive = blend_curve.driver
    blend_drive.type = 'AVERAGE'
    blend_var = blend_drive.variables.new()
    blend_var.name = "blend"
    blend_target = blend_var.targets[0]
    blend_target.id = target
    blend_target.use_fallback_value = True
    blend_target.data_path = '["Frost Edge"]'


def create_focus_driver(item, target):
    """Create a driver for focus factor."""
    focus_curve = item.data.driver_add("shadow_soft_size")
    focus_drive = focus_curve.driver
    focus_drive.type = 'SCRIPTED'
    factor_var = focus_drive.variables.new()
    radius_var = focus_drive.variables.new()
    factor_var.name = "factor"
    radius_var.name = "radius"
    factor_target = factor_var.targets[0]
    radius_target = radius_var.targets[0]
    factor_target.id = target
    radius_target.id = item
    focus_drive.expression = "(1.0 - factor) * radius * 2"
    factor_target.data_path = '["Focus Factor"]'
    radius_target.data_path = '["Radius"]'


def create_gobo_driver(item, node, target, count):
    """Create a driver for Gobo select and rotate."""
    node.inputs[1].default_value[:2] = [0.5] * 2
    node.rotation_type = 'Z_AXIS'
    node.inputs[1].hide = True
    node.invert = True
    img_user = item.image_user
    img_user.frame_duration = count
    img_user.use_auto_refresh = True
    rota_curve = node.inputs[3].driver_add("default_value")
    seq_curve = img_user.driver_add("frame_offset")
    rota_drive = rota_curve.driver
    seq_drive = seq_curve.driver
    rota_drive.type = seq_drive.type = 'AVERAGE'
    rota_var = rota_drive.variables.new()
    seq_var = seq_drive.variables.new()
    rota_var.name = "rotate"
    seq_var.name = "select"
    seq_target = seq_var.targets[0]
    rota_target = rota_var.targets[0]
    rota_target.id = seq_target.id = target
    seq_target.data_path = f'["{item.name} Select"]'
    rota_target.data_path = f'["{item.name} Rotate"]'


def create_trackball_driver(item, target, prop):
    """Create a driver for position trackball."""
    range_data = item.get("Range")
    min_angle = min(range_data)
    max_angle = max(range_data)
    check_target = target.get("Target")
    check_pan = item.get("Mobile Axis") == "Pan"
    max_val = "max_z" if check_pan else "max_x"
    min_val = "min_z" if check_pan else "min_x"
    path = f'["{prop}"][0]' if check_pan else f'["{prop}"][1]'
    limit = item.constraints.get("Limit Rotation")
    lock = item.constraints.get("Locked Track")
    if limit:
        limit.enabled = check_target
        axis_value = limit.max_z if check_pan else limit.max_x
        max_curve = limit.driver_add(max_val)
        min_curve = limit.driver_add(min_val)
        limit_curve = limit.driver_add("influence")
        max_drive = max_curve.driver
        min_drive = min_curve.driver
        limit_drive = limit_curve.driver
        max_drive.type = 'AVERAGE'
        min_drive.type = limit_drive.type = 'SCRIPTED'
        max_var = max_drive.variables.new()
        min_var = min_drive.variables.new()
        angle_var = min_drive.variables.new()
        limit_var = limit_drive.variables.new()
        max_var.name = "range"
        min_var.name = "track"
        angle_var.name = "angle"
        limit_var.name = "state"
        max_target = max_var.targets[0]
        min_target = min_var.targets[0]
        limit_target = limit_var.targets[0]
        angle_target = angle_var.targets[0]
        max_target.id = angle_target.id = item
        min_target.id = limit_target.id = target
        min_target.data_path = path
        max_target.data_path = '["Range"][0]'
        angle_target.data_path = '["Range"][1]'
        limit_target.data_path = '["Trackball"]'
        max_target.use_fallback_value = True
        angle_target.use_fallback_value = True
        angle_target.fallback_value = max_angle
        min_drive.expression = "track * angle"
        limit_drive.expression = "1.0 if state else 0.0"
        axis_value = max_target.fallback_value = min_angle
    if lock:
        bool_curve = lock.driver_add("enabled")
        lock_curve = lock.driver_add("influence")
        bool_drive = bool_curve.driver
        lock_drive = lock_curve.driver
        bool_drive.type = 'AVERAGE'
        lock_drive.type = 'SCRIPTED'
        bool_var = bool_drive.variables.new()
        lock_var = lock_drive.variables.new()
        bool_var.name = "target"
        lock_var.name = "state"
        bool_target = bool_var.targets[0]
        lock_target = lock_var.targets[0]
        lock_drive.expression = "0.0 if state else 1.0"
        bool_target.id = lock_target.id = target
        lock_target.data_path = '["Trackball"]'
        bool_target.data_path = '["Target"]'


def create_zoom_driver(item, target, prop):
    """Create a driver for zoom feature."""
    if item.id_type == 'LIGHT':
        if prop == "Focus Zoom":
            zoom_curve = item.driver_add("spot_size")
            zoom_drive = zoom_curve.driver
            zoom_drive.type = 'AVERAGE'
            zoom_var = zoom_drive.variables.new()
            zoom_var.name = "zoom"
            zoom_target = zoom_var.targets[0]
            zoom_target.id = target
            zoom_target.data_path = f'["{prop}"]'
        reference = item if prop == "Focus" else target
        focus = item.node_tree.nodes.get("Focus Factor")
        focus_factor = focus.outputs[0].default_value
        diffuse_factor = item.diffuse_factor
        specular_factor = item.specular_factor
        volume_factor = item.volume_factor
        diffuse_curve = item.driver_add("diffuse_factor")
        volume_curve = item.driver_add("volume_factor")
        spec_curve = item.driver_add("specular_factor")
        focus_curve = focus.outputs[0].driver_add("default_value")
        diffuse_drive = diffuse_curve.driver
        volume_drive = volume_curve.driver
        spec_drive = spec_curve.driver
        focus_drive = focus_curve.driver
        diffuse_drive.type = spec_drive.type = 'SCRIPTED'
        volume_drive.type = focus_drive.type = 'SCRIPTED'
        diffuse_ang = diffuse_drive.variables.new()
        diffuse_fac = diffuse_drive.variables.new()
        volume_ang = volume_drive.variables.new()
        volume_fac = volume_drive.variables.new()
        focus_var = focus_drive.variables.new()
        power_var = focus_drive.variables.new()
        spec_ang = spec_drive.variables.new()
        spec_fac = spec_drive.variables.new()
        focus_var.name = spec_ang.name = "angle"
        power_var.name = spec_fac.name = "factor"
        diffuse_ang.name = volume_ang.name = "angle"
        diffuse_fac.name = volume_fac.name = "factor"
        spec_angle = spec_ang.targets[0]
        spec_factor = spec_fac.targets[0]
        vol_angle = volume_ang.targets[0]
        dif_angle = diffuse_ang.targets[0]
        vol_factor = volume_fac.targets[0]
        dif_factor = diffuse_fac.targets[0]
        focus_target = focus_var.targets[0]
        power_target = power_var.targets[0]
        power_target.id_type = spec_factor.id_type = dif_factor.id_type = vol_factor.id_type = 'LIGHT'
        focus_target.id_type = spec_angle.id_type = 'LIGHT' if prop == "Focus" else 'OBJECT'
        dif_angle.id_type = vol_angle.id_type = 'LIGHT' if prop == "Focus" else 'OBJECT'
        focus_target.id = spec_angle.id = dif_angle.id = vol_angle.id = reference
        power_target.id = dif_factor.id = vol_factor.id = spec_factor.id = item
        power_target.use_fallback_value = spec_factor.use_fallback_value = True
        dif_factor.use_fallback_value = vol_factor.use_fallback_value = True
        dif_factor.fallback_value = diffuse_factor
        vol_factor.fallback_value = volume_factor
        power_target.fallback_value = focus_factor
        spec_factor.fallback_value = specular_factor
        formula = "factor / max(pow(degrees(angle), 2), 1e-09)"
        diffuse_drive.expression = f"{formula} * 0.5"
        focus_drive.expression = f"{formula} * 0.1"
        spec_drive.expression = f"{formula} * 0.04"
        volume_drive.expression = f"{formula}"
        dif_factor.data_path = vol_factor.data_path = '["Power"]'
        power_target.data_path = spec_factor.data_path = '["Power"]'
        dif_angle.data_path = vol_angle.data_path = f'["{prop}"]'
        focus_target.data_path = spec_angle.data_path = f'["{prop}"]'
    elif item.id_type == 'OBJECT' and prop == "Focus Zoom":
        x_curve = item.driver_add("scale", 0)
        y_curve = item.driver_add("scale", 1)
        x_drive = x_curve.driver
        y_drive = y_curve.driver
        x_drive.type = y_drive.type = 'SCRIPTED'
        zoom_x = x_drive.variables.new()
        zoom_y = y_drive.variables.new()
        angle_x = x_drive.variables.new()
        angle_y = y_drive.variables.new()
        zoom_x.name = zoom_y.name = "zoom"
        angle_x.name = angle_y.name = "angle"
        zoom_x_target = zoom_x.targets[0]
        zoom_y_target = zoom_y.targets[0]
        angle_x_target = angle_x.targets[0]
        angle_y_target = angle_y.targets[0]
        zoom_x_target.id = zoom_y_target.id = target
        angle_x_target.id = angle_y_target.id = item
        x_drive.expression = "zoom / max(angle, 1e-09)"
        y_drive.expression = "zoom / max(angle, 1e-09)"
        zoom_x_target.data_path = zoom_y_target.data_path = f'["{prop}"]'
        angle_x_target.data_path = angle_y_target.data_path = '["Focus"]'


def create_gobo_property(item, count, prop):
    """Create Gobo select and rotate property."""
    rota_var = "%s Rotate" % prop
    item[rota_var] = 0.0
    item.id_properties_ensure()
    angle_property = item.id_properties_ui(rota_var)
    gobo_property = item.id_properties_ui("%s Select" % prop)
    gobo_property.update(default=0, min=0, max=count, soft_min=0, soft_max=count, step=1)
    angle_property.update(default=0.0, min=-360.0, max=360.0, soft_min=-540.0, soft_max=540.0, precision=0, step=1.0, subtype='ANGLE')  


def create_color_property(item, color, prop):
    """Create a RGB color property."""
    item[prop] = color
    item.id_properties_ensure()
    color_property = item.id_properties_ui(prop)
    color_property.update(default=color, min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, subtype='COLOR_GAMMA')


def create_ctc_property(item, ctc, prop):
    """Create a color temperature property."""
    if ctc:
        item[prop] = ctc
        item.id_properties_ensure()
        ctc_property = item.id_properties_ui(prop)
        ctc_property.update(default=ctc, min=100.0, max=1000000.0, soft_min=100.0, soft_max=100000.0, step=100.0, subtype='TEMPERATURE')


def create_dimmer_property(item, prop, intensity=100):
    """Create a dimmer percentage custom property."""
    item[prop] = intensity
    item.id_properties_ensure()
    dimmer_property = item.id_properties_ui(prop)
    dimmer_property.update(default=100, min=0, max=100, soft_min=0, soft_max=100, subtype='PERCENTAGE')


def create_factor_property(item, prop, factor=0.0):
    """Create a factor custom property."""
    item[prop] = factor
    item.id_properties_ensure()
    factor_property = item.id_properties_ui(prop)
    factor_property.update(default=factor, min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, precision=1, step=0.1, subtype='FACTOR')


def create_patch_property(item, patch):
    """Create universe address and patch break."""
    props = ["Patch Break", "Patch Universe", "Patch Address"]
    for p, number in enumerate(patch):
        item[props[p]] = number
        item.id_properties_ensure()
        patch_property = item.id_properties_ui(props[p])
        patch_property.update(default=number, min=0, max=262144, soft_min=0, soft_max=512)


def create_power_property(item, energy):
    """Create a light power property."""
    item["Power"] = energy
    item.id_properties_ensure()
    dimmer_property = item.id_properties_ui("Power")
    dimmer_property.update(default=energy, min=0.0, max=1000000.0, soft_min=0.0, soft_max=100000.0, subtype='POWER')


def create_radius_property(item, radius):
    """Create a beam radius property."""
    rmin = radius * 0.1
    rnorm = radius * 0.5
    item["Radius"] = rnorm
    item.id_properties_ensure()
    radius_property = item.id_properties_ui("Radius")
    radius_property.update(default=rnorm, min=rmin, max=radius, soft_min=rmin, soft_max=radius, step=0.01, subtype='DISTANCE')


def create_range_property(item, angle, prop, limits=False):
    """Create angle range property."""
    if angle:
        val = angle
        if limits:
            rmin = math.radians(min(limits))
            rmax = math.radians(max(limits))
        elif isinstance(angle, tuple):
            rmin = math.radians(min(angle))
            rmax = math.radians(max(angle))
            val = rmin, rmax
        else:
            rmin = math.radians(1.0)
            rmax = math.radians(160.0)
        item[prop] = val
        item.id_properties_ensure()
        range_property = item.id_properties_ui(prop)
        range_property.update(default=val, min=rmin, max=rmax, soft_min=rmin, soft_max=rmax, precision=1, step=1.0, subtype='ANGLE')


def create_trackball_property(item, prop, targets):
    """Create a trackball custom property."""
    vec = (0.0, 0.0, 1.0)
    item[prop] = vec
    item.id_properties_ensure()
    item["Trackball"] = not targets
    pt_property = item.id_properties_ui(prop)
    pt_property.update(default=vec, min=-1.0, max=1.0, soft_min=-1.0, soft_max=1.0, precision=8, step=0.00001, subtype='DIRECTION')


def collect_dmx_channels(gdtf_profile, mode):
    """Collect the dmx channels and functions."""
    dmx_mode = None
    dmx_channels = []
    dmx_mode = gdtf_profile.dmx_modes.get_mode_by_name(mode)

    if dmx_mode:
        root_geometry = gdtf_profile.geometries.get_geometry_by_name(dmx_mode.geometry)
    else:
        root_geometry = None
    virtual_channels = pygdtf.utils._get_channels_for_geometry(gdtf_profile, root_geometry, dmx_mode.virtual_channels, [])
    fix_channels = pygdtf.utils._get_channels_for_geometry(gdtf_profile, root_geometry, dmx_mode.dmx_channels, virtual_channels)

    for channel, geometry in fix_channels:
        channel_range = []
        feature = str(channel.logical_channels[0].attribute)
        functions = channel.logical_channels[0].channel_functions
        if len(functions):
            channel_range += [functions[0].physical_from.value, functions[0].physical_to.value]
        if channel.offset is None:
            continue
        channel_break = channel.dmx_break
        if isinstance(geometry, pygdtf.GeometryReference) and channel.dmx_break == "Overwrite":
            if len(geometry.breaks):
                channel_break = geometry.breaks[0].dmx_break
            else:
                channel_break = 1
        if len(dmx_channels) < channel_break:
            dmx_channels = dmx_channels + [[]] * (channel_break - len(dmx_channels))
        break_channels = dmx_channels[channel_break - 1]
        break_addition = 0
        if hasattr(geometry, "breaks"):
            dmx_offset = pygdtf.utils._get_address_by_break(geometry.breaks, channel_break)
            if dmx_offset is not None:
                break_addition = dmx_offset.address - 1
        offset_coarse = channel.offset[0] + break_addition
        offset_fine = 0
        if len(channel.offset) > 1:
            offset_fine = channel.offset[1] + break_addition
        max_offset = max([offset_coarse, offset_fine])
        if len(break_channels) < max_offset:
            break_channels = break_channels + [{"ID": "", "Geometry": ""}] * (max_offset - len(break_channels))
        break_channels[offset_coarse - 1] = {"ID": feature, "Geometry": geometry.name,
                                             "Functions": channel.logical_channels[0].channel_functions}
        if offset_fine > 0:
            break_channels[offset_fine - 1] = {"ID": "+" + feature, "Geometry": geometry.name,
                                               "Functions": channel.logical_channels[0].channel_functions}
        dmx_channels[channel_break - 1] = break_channels
        if feature in {"Pan", "Tilt"}:
            channelData[geometry.name] = feature
            if len(channel_range) and (channel_range[0] != channel_range[-1]):
                rangeData.setdefault(geometry.name, []).extend(channel_range)

    for index, break_list in enumerate(dmx_channels):
        dmx_channels[index] = [channel for channel in break_list if channel.get("ID", "") != ""]

    return dmx_channels


def convert_color(color_cie):
    """As blender needs RGBA, which we later strip anyways, we just add 100 for Alpha"""
    x = color_cie.x
    y = color_cie.y
    Y = color_cie.Y
    if not x or not y or not Y:
        return (0, 0, 0, 0)

    # convert to XYZ
    X = x * (Y / y)
    Z = (1 - x - y) * (Y / y)
    var_X = X / 100
    var_Y = Y / 100
    var_Z = Z / 100

    # XYZ to RGB
    var_R = var_X * 3.2406 + var_Y * -1.5372 + var_Z * -0.4986
    var_G = var_X * -0.9689 + var_Y * 1.8758 + var_Z * 0.0415
    var_B = var_X * 0.0557 + var_Y * -0.204 + var_Z * 1.057

    if var_R > 0.0031308:
        var_R = 1.055 * math.pow(var_R, 1 / 2.4) - 0.055
    else:
        var_R = 12.92 * var_R
    if var_G > 0.0031308:
        var_G = 1.055 * math.pow(var_G, 1 / 2.4) - 0.055
    else:
        var_G = 12.92 * var_G
    if var_B > 0.0031308:
        var_B = 1.055 * math.pow(var_B, 1 / 2.4) - 0.055
    else:
        var_B = 12.92 * var_B
    return (var_R, var_G, var_B, 0)


def load_blender_primitive(model):
    """Load a blender primitive mesh."""
    primitive = str(model.primitive_type)
    if primitive == "Cube":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == "Pigtail":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == "Plane":
        bpy.ops.mesh.primitive_plane_add(size=1.0)
    elif primitive == "Cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.5, depth=1.0)
    elif primitive == "Sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=16, radius=0.5)
    obj = bpy.context.view_layer.objects.selected[0]
    obj.users_collection[0].objects.unlink(obj)
    obj.data.transform(mathutils.Matrix.Diagonal((model.length, model.width, model.height)).to_4x4())
    return obj


def load_gdtf_primitive(model):
    """Load primitive mesh from assets."""
    primitive = str(model.primitive_type)
    path = os.path.join(get_folder_path(), f"{primitive}.3ds")
    load_3ds(path, bpy.context, FILTER={'MESH'}, KEYFRAME=False, APPLY_MATRIX=False)
    obj = bpy.context.view_layer.objects.selected[0]
    obj.users_collection[0].objects.unlink(obj)
    obj.data.transform(mathutils.Matrix.Diagonal((model.length / obj.dimensions.x,
                                                  model.width / obj.dimensions.y,
                                                  model.height / obj.dimensions.z)).to_4x4())
    return obj


def create_iris_nodes(item, root, irisnode, outputnode):
    """Create iris shader node setup."""
    check_spot = item.id_type == 'LIGHT'
    iris_nodes = item.node_tree.nodes
    iris_links = item.node_tree.links
    create_dimmer_property(root, "Iris", 0)
    add_node = iris_nodes.new("ShaderNodeVectorMath")
    iris_gobo = bpy.data.images.get("open.png", False)
    scale_node = iris_nodes.new("ShaderNodeVectorMath")
    center_node = iris_nodes.new("ShaderNodeVectorMath")
    cord_output = outputnode.outputs[5] if check_spot else outputnode.outputs[2]
    center_node.inputs[1].default_value[:2] = add_node.inputs[1].default_value[:2] = [0.5] * 2
    outputnode.location = (-1720, 400) if check_spot else (-1440, 160)
    center_node.location = (-1540, 180) if check_spot else (-1240, 120)
    scale_node.location = (-1340, 150) if check_spot else (-1040, 150)
    add_node.location = (-1160, 150) if check_spot else (-840, 150)
    irisnode.location = (-660, 150) if check_spot else (-260, 150)
    center_node.inputs[1].hide = add_node.inputs[1].hide = True
    scale_node.label = scale_node.name = "Iris Size"
    center_node.label = center_node.name = "Center"
    add_node.label = add_node.name = "Iris Vector"
    center_node.operation = 'SUBTRACT'
    scale_node.operation = 'SCALE'
    add_node.operation = 'ADD'
    if not iris_gobo:
        gobo_path = os.path.join(get_folder_path(), "open.png")
        iris_gobo = bpy.data.images.load(gobo_path)
        iris_gobo.alpha_mode = 'CHANNEL_PACKED'
    irisnode.image = iris_gobo
    irisnode.outputs[1].hide = True
    irisnode.show_options = False
    irisnode.extension = 'EXTEND'
    irisnode.height = 100
    irisnode.width = 140
    irisnode.label = irisnode.name = "Iris"
    iris_links.new(cord_output, center_node.inputs[0])
    iris_links.new(center_node.outputs[0], scale_node.inputs[0])
    iris_links.new(scale_node.outputs[0], add_node.inputs[0])
    iris_links.new(add_node.outputs[0], irisnode.inputs[0])
    scale_curve = scale_node.inputs[3].driver_add("default_value")
    scale_drive = scale_curve.driver
    scale_drive.type = 'SCRIPTED'
    scale_var = scale_drive.variables.new()
    scale_var.name = "scale"
    scale_target = scale_var.targets[0]
    scale_target.id = root
    scale_drive.expression = "scale * 0.1"
    scale_target.data_path = '["Iris"]'


def extract_gobos(profile, fid, fixturename, wheels):
    """Extract gobo images from zip file."""
    gobo_data = {}
    name = create_fixture_name(fixturename)
    gdtf_path = os.path.join(get_folder_path(), name)
    open_path = os.path.join(get_folder_path(), "open.png")
    images_path = os.path.join(gdtf_path, "wheels")
    gobos_path = os.path.join(gdtf_path, "gobos")
    open_image = Path(open_path)
    for image_name in profile._package.namelist():
        if image_name.startswith("wheels"):
            profile._package.extract(image_name, gdtf_path)
    if not os.path.isdir(gobos_path):
        os.makedirs(gobos_path)
    for wheel in profile.wheels:
        if wheel.name in wheels:
            gobos = []
            gobo_count = 0
            wheel_path = os.path.join(gobos_path, wheel.name)
            if not os.path.isdir(wheel_path):
                os.makedirs(wheel_path)
            for idx, slot in enumerate(wheel.wheel_slots, 1):
                media_file = str(slot.media_file_name.name)
                media_name = f"{name}_{wheel.name}-{idx:04}.png"
                name_split = media_file.split(".")
                if not len(name_split[0]):
                    destination = Path(wheel_path, media_name)
                    destination.write_bytes(open_image.read_bytes())
                    gobo_source = destination.resolve()
                else:
                    extend = str(slot.media_file_name.extension)
                    media_name = f"{name}_{wheel.name}-{idx:04}.{extend}"
                    img_path = Path(os.path.join(images_path, str(slot.media_file_name)))
                    destination = Path(wheel_path, media_name)
                    if os.path.isfile(img_path):
                        destination.write_bytes(img_path.read_bytes())
                    else:
                        destination.write_bytes(open_image.read_bytes()) 
                    gobo_source = destination.resolve()
                if idx == 1:
                    first_gobo = str(gobo_source)
                gobo_count = idx
            first_name = f"ID{fid}_{name}_{wheel.name}-0001.png" if fid > 0 else f"{name}_{wheel.name}-0001.png"
            if first_name in bpy.data.images:
                sequence = bpy.data.images.get(first_name)
            else:
                sequence = bpy.data.images.load(first_gobo)
                sequence.name = first_name
            sequence.alpha_mode = 'CHANNEL_PACKED'
            sequence["Count"] = gobo_count - 1
            sequence.source = 'SEQUENCE'
            gobo_data[wheel.name] = sequence
    return gobo_data


def get_wheel_slot_colors(profile):
    """Get color slots from colorwheels."""
    colors = []
    for wheel in profile.wheels:
        for slot in wheel.wheel_slots:
            try:
                color = convert_color(slot.color)
            except:
                color = None
            if color is not None and color not in colors:
                colors.append(color)
    return colors


def load_2d(profile, name):
    """Load svg thumbnail."""
    folder_path = os.path.join(get_folder_path(), name, "symbols")
    filename = f"{profile.thumbnail}.svg"
    obj = None
    if filename in profile._package.namelist():
        profile._package.extract(filename, folder_path)
        filepath = os.path.join(folder_path, filename)
        try:
            bpy.ops.wm.gpencil_import_svg(filepath=filepath, scale=1)
        except:
            bpy.ops.wm.grease_pencil_import_svg(filepath=filepath, scale=1)
        if len(bpy.context.view_layer.objects.selected):
            obj = bpy.context.view_layer.objects.selected[0]
        if obj is not None:
            obj.name = "2D Symbol"
            if len(obj.users_collection):
                obj.users_collection[0].objects.unlink(obj)
            obj.rotation_euler[0] = math.radians(-90)
    return obj


def join_parts_apply_transforms(objects):
    """Join meshes wich belong to a geometry."""
    join = 0
    single = None
    for ob in objects:
        mb = ob.matrix_basis
        if ob.type == 'MESH' and ob.data.vertices.items():
            ob.select_set(True)
            join += 1
            bpy.context.view_layer.objects.active = ob
            single = ob
            if ob.data.get("Model Type") == "glb":
                ob.data.transform(mb)
        ob.matrix_basis.identity()
    if join > 0:
        bpy.ops.object.join()
        objects = list(bpy.context.view_layer.objects.selected)
    for obj in objects:
        obj.users_collection[0].objects.unlink(obj)
    if join == 1:
        objects = [single]
    for ob in objects:
        if ob.type == 'MESH':
            obj = ob
            break

    return obj


def load_model(profile, name, model):
    """Load 3ds or glb model files."""
    folder_path = os.path.join(get_folder_path(), name)
    obj_dimension = mathutils.Vector((model.length, model.width, model.height))

    if model.file.extension.lower() == "3ds":
        inside_zip_path = f"models/3ds/{model.file.name}.{model.file.extension}"
        file_name = os.path.join(folder_path, inside_zip_path)
        try:
            profile._package.extract(inside_zip_path, folder_path)
            load_3ds(file_name, bpy.context, FILTER={'MESH'}, KEYFRAME=False, APPLY_MATRIX=False)   
        except:
            alternative = load_blender_primitive(model)
            bpy.context.view_layer.active_layer_collection.collection.objects.link(alternative)
            alternative.select_set(True)
    else:
        inside_zip_path = f"models/gltf/{model.file.name}.{model.file.extension}"
        profile._package.extract(inside_zip_path, folder_path)
        file_name = os.path.join(folder_path, inside_zip_path)
        bpy.ops.import_scene.gltf(filepath=file_name)
    objects = list(bpy.context.selected_objects)

    # if the model is made up of multiple parts we must join them
    obj = join_parts_apply_transforms(objects)
    obj.rotation_mode = 'XYZ'
    scale_vector = obj.scale * obj_dimension
    factor = mathutils.Vector([scale_vector[val] / max(obj.dimensions[val], 1e-09) for val in range(3)])
    if model.file.extension.lower() == "3ds":
        if obj.data:
            obj.data.transform(mathutils.Matrix.Diagonal(factor).to_4x4())
    else:
        obj.scale = factor
    if obj.data:
        obj.data.name = model.file.name
        obj.data["Model Type"] = model.file.extension.lower()
    return obj


def collect_attributes(channels, logic=False):
    """Collect fixture preset types and attributes."""
    has_blend = has_focus = has_gobos = has_iris = zoom_range = False
    pan_range = tilt_range = None
    wheels = []

    for channel in channels:
        if "Gobo" in channel["ID"]:
            has_gobos = True
            if not logic:
                gobo_functions = channel.get("Functions")
                for function in gobo_functions:
                    wheel_function = str(function.wheel)
                    if wheel_function != "None" and wheel_function not in wheels:
                        wheels.append(wheel_function)
        if "Zoom" in channel["ID"]:
            zoom_functions = channel.get("Functions")
            zoom_range = zoom_functions[0].physical_from.value, zoom_functions[0].physical_to.value
        if "Iris" in channel["ID"]:
            has_iris = True
        if not logic:
            if "Focus" in channel["ID"]:
                has_focus = True
            if "Frost" in channel["ID"]:
                has_blend = True
            if "Pan" in channel["ID"]:
                pan_functions = channel.get("Functions")
                pan_range = pan_functions[0].physical_from.value, pan_functions[0].physical_to.value
            if "Tilt" in channel["ID"]:
                tilt_functions = channel.get("Functions")
                tilt_range = tilt_functions[0].physical_from.value, tilt_functions[0].physical_to.value


    if logic:
        return has_gobos, has_iris, zoom_range
    else:
        return has_blend, has_focus, has_iris, zoom_range, wheels


def build_collection(profile, fixturename, fixture_id, uid, target_id, mode, BEAMS, TARGETS, CONES, MODE_NR):
    """Create model collection."""
    objectDict = {}
    color_channels = set()
    name = create_fixture_name(fixturename)
    profile_cls = profile.__class__.__name__
    fixturetype_id = profile.fixture_type_id
    collection = bpy.data.collections.new(name)
    dmx_mode = profile.dmx_modes.get_mode_by_name(mode)
    has_gobos = has_iris = zoom_range = False

    if dmx_mode is None:
        if MODE_NR == 0:
            dmx_mode = profile.dmx_modes[MODE_NR]
        else:
            dmx_mode = profile.dmx_modes[min(MODE_NR, len(profile.dmx_modes)) - 1]
        mode = dmx_mode.name

    collection["UUID"] = uid
    collection["Fixture ID"] = fixture_id
    collection["MVR Type"] = profile_cls
    create_gdtf_props(collection, fixturename)
    dmx_channels = collect_dmx_channels(profile, mode)
    root_geometry = profile.geometries.get_geometry_by_name(dmx_mode.geometry)
    logical_channels = [channel for break_channels in dmx_channels for channel in break_channels]
    virtual_channels = pygdtf.utils.get_virtual_channels(profile, mode)
    has_gobos, has_iris, zoom_range = collect_attributes(logical_channels, True)

    for channel in logical_channels:
        if "Color1" in channel["ID"]:
            color_channels.add(channel.get("Geometry"))
        elif "Color" in channel["ID"]:
            color_attribute = channel.get("ID")
            if color_attribute[-1] in colorMix:
                color_channels.add(channel.get("Geometry"))

    def load_geometries(geometry):
        """Load 3d models, primitives and shapes"""
        data_meshes = bpy.data.meshes
        data_objects = bpy.data.objects
        original_name = str(geometry.name)
        geometry_name = cleanup_name(geometry)
        geometry_class = geometry.__class__.__name__
        geometry_type = get_geometry_type_as_string(geometry)
        if original_name in color_channels:
            setattr(geometry, "reference_rgb", original_name)
        if geometry_class == 'GeometryBeam':
            if any(geometry.beam_type.value == x for x in ["None", "Glow"]):
                geometry_type = "Glow"
        for ob in data_objects:
            ob.select_set(False)

        if isinstance(geometry, pygdtf.GeometryReference):
            reference = profile.geometries.get_geometry_by_name(geometry.geometry)
            geometry.model = reference.model
            if hasattr(reference, "geometries"):
                for sub_geometry in reference.geometries:
                    setattr(sub_geometry, "reference_root", original_name)
                    if original_name in color_channels:
                        setattr(sub_geometry, "reference_rgb", original_name)
                    load_geometries(sub_geometry)
        if geometry.model is None:
            model = pygdtf.Model(name=f"{geometry}", length=0.0001, width=0.0001,
                                 height=0.0001, primitive_type="Cube")
            geometry.model = ""
        else:
            model = copy.deepcopy(profile.models.get_model_by_name(geometry.model))
        if isinstance(geometry, pygdtf.GeometryReference):
            model.name = f"{geometry}"

        obj = None
        mesh_name = ""
        if model.file:
            mesh_name = model.file.name
        primitive = str(model.primitive_type)
        if primitive[-3:] == "1_1":
            primitive = primitive[:-3]
            model.primitive_type = pygdtf.PrimitiveType(primitive)

        # Prefer File first, as some GDTFs have both File and PrimitiveType
        if (primitive == "Undefined" or
            (model.file and
             model.file.name != "" and
             primitive != "Pigtail")
        ):
            obj = data_objects.get(geometry_name)
            if (obj is None or obj.get("Model Name") != mesh_name or
                obj.get("Fixture ID") != fixture_id
            ):
                geo = data_meshes.get(mesh_name)
                if (geo and geo.get("Model Name") == mesh_name and
                    geo.get("UUID") == fixturetype_id
                ):
                    obj = data_objects.new(geometry_name, geo)
                else:
                    try:
                        obj = load_model(profile, name, model)
                    except Exception as exc:
                        print("Error importing 3D model: %s" % exc)
                        model.primitive_type = "Cube"
                        obj = load_blender_primitive(model)
        else:
            primesh = data_meshes.get(primitive)
            if primesh and primesh.get("UUID") == fixturetype_id:
                obj = data_objects.new(primitive, primesh)
            elif primitive in ["Base", "Conventional", "Head", "Yoke"]:
                obj = load_gdtf_primitive(model)
                obj.data.name = primitive
            else:
                obj = load_blender_primitive(model)
                obj.data.name = primitive

        # If object was created
        if obj is not None:
            if obj.data:
                obj_name = remove_suffix(obj.name)
                if obj.get("UUID") is None:
                    obj.data["Geometry Class"] = geometry_class
                    obj.data["Geometry Type"] = geometry_type
                    obj.data["Original Name"] = obj_name
                    obj.data["Model Name"] = mesh_name
                    obj.data["UUID"] = fixturetype_id
                if obj.data.materials:
                    for mtl in obj.data.materials:
                        mtl_name = remove_suffix(mtl.name)
                        if geometry_class == "GeometryBeam":
                            mtl["Fixture ID"] = fixture_id
                        if obj.get("UUID") is None:
                            create_gdtf_props(mtl, fixturename)
                            mtl["Original Name"] = mtl_name
                            mtl["Model Name"] = mesh_name
                            mtl["UUID"] = fixturetype_id
            obj.name = geometry_name
            create_fixture_id(obj, fixture_id)
            create_gdtf_props(obj, fixturename)
            if geometry_name == cleanup_name(root_geometry):
                obj["Fixture Mode"] = mode
                obj["Use Root"] = True
                obj.hide_select = False
            else:
                obj["Geometry Class"] = geometry_class
                obj["Geometry Type"] = geometry_type
                obj["Original Name"] = original_name
                obj.hide_select = True
                if len(mesh_name):
                    obj["Model Name"] = mesh_name
            if isinstance(geometry, pygdtf.GeometryReference):
                obj["Reference"] = str(geometry.geometry)
                obj["Geometry Type"] = obj.data.get("Geometry Type")
            elif hasattr(geometry, "reference_root"):
                obj["Reference"] = getattr(geometry, "reference_root")
            if str(model.primitive_type) == "Pigtail":
                obj["Geometry Type"] = "Pigtail"
            objectDict[geometry_name] = obj
            mb = obj.matrix_basis.copy()
            if obj.data.get("Model Type") == "glb":
                obj.data.transform(mb) 
            for cld in obj.children:
                cld.matrix_local = mb @ cld.matrix_local
            obj.matrix_basis.identity()
        if hasattr(geometry, "geometries"):
            for sub_geometry in geometry.geometries:
                if hasattr(geometry, "reference_root"):
                    root_reference = getattr(geometry, "reference_root")
                    setattr(sub_geometry, "reference_root", root_reference)
                if original_name in color_channels:
                    setattr(sub_geometry, "reference_rgb", original_name)
                load_geometries(sub_geometry)

    def get_geometry_type_as_string(geometry):
        if isinstance(geometry, pygdtf.GeometryMediaServerCamera):
            return "Camera"
        if isinstance(geometry, pygdtf.GeometryBeam):
            return "Beam"
        if isinstance(geometry, pygdtf.GeometryLaser):
            return "Laser"
        if isinstance(geometry, pygdtf.GeometryAxis):
            return "Axis"
        if isinstance(geometry, pygdtf.GeometryReference):
            geometry = profile.geometries.get_geometry_by_name(geometry.geometry)
            return get_geometry_type_as_string(geometry)
        return "Normal"

    def create_camera(geometry):
        if not cleanup_name(geometry) in objectDict:
            return
        obj_child = objectDict.get(cleanup_name(geometry))
        camera_data = bpy.data.cameras.get(name=f"{obj_child.name}")
        if camera_data is None:
            camera_data = bpy.data.cameras.new(name=f"{obj_child.name}")
        camera_object = bpy.data.objects.new("MediaCamera", camera_data)
        camera_object.hide_select = True
        camera_object.parent = obj_child
        camera_object.matrix_parent_inverse = obj_child.matrix_world.inverted()
        camera_object.rotation_euler[0] += math.radians(90)
        collection.objects.link(camera_object)

    def create_beam(geometry):
        beam_color = [1.0] * 3
        lightname = name.split()[-1]
        data_lights = bpy.data.lights
        lamp_type = str(geometry.lamp_type)
        ctc = float(geometry.color_temperature)
        beam_angle = math.radians(geometry.beam_angle)
        obj_child = objectDict.get(cleanup_name(geometry))
        light_energy = geometry.luminous_flux / pow(max(geometry.beam_angle, 10), 2)
        childname = obj_child.get("Original Name", remove_suffix(obj_child.name))
        obj_child["Fixture ID"] = obj_child.data["Fixture ID"] = fixture_id
        light_power = max(light_energy * 100, 100.0)
        obj_child.data.name = "%s_Beam" % name
        if len(obj_child.data.materials):
            beam_mtl = obj_child.data.materials[0]
            beam_color = beam_mtl.diffuse_color[:3]
            beam_mtl["Fixture ID"] = fixture_id
            if childname in color_channels:
                beam_mtl["RGB"] = True
            beam_mtl.name = "%s_Beam" % name
        beamname = f"{lightname}_{childname}"
        if not BEAMS or obj_child is None:
            return
        if fixture_id >= 1:
            if obj_child.data.get("Fixture ID") != fixture_id:
                emitter = obj_child.data.copy()
                emitter["Fixture ID"] = fixture_id
                obj_child.data = emitter
            beamname = f"ID{fixture_id}_{lightname}_{childname}"
            obj_child.data.name = f"ID{fixture_id}_{name}_Beam"
            obj_child["Geometry Type"] = obj_child.data["Geometry Type"] = "Beam"
            if len(obj_child.data.materials):
                emit_material = obj_child.data.materials[0]
                emit_material["Fixture ID"] = fixture_id
                emit_material.name = beamname
        if any(geometry.beam_type.value == x for x in ["None", "Glow"]):
            glowname = f"ID{fixture_id}_{name}_Glow" if fixture_id >= 1 else "%s_Glow" % name
            obj_child["Geometry Type"] = obj_child.data["Geometry Type"] = "Glow"
            obj_child.data.name = glowname
            if len(obj_child.data.materials):
                glow_material = obj_child.data.materials[0]
                glow_material.name = glowname
            return
        obj_child.visible_shadow = False
        light_data = data_lights.get(beamname)
        if light_data is None or light_data.get("Fixture Name") != lightname:
            light_data = data_lights.new(beamname, 'SPOT')
            light_data.use_custom_distance = True
            create_gdtf_props(light_data, fixturename)
            light_data.spot_size = beam_angle
            light_data.energy = light_power
            light_data.color = beam_color
            light_data.cutoff_distance = 23
            light_data.volume_factor = light_energy * 0.5
            light_data.diffuse_factor = light_energy * 0.1
            light_data.specular_factor = light_energy * 0.05
            light_data.transmission_factor = light_energy * 0.01
            light_data.spot_blend = calculate_spot_blend(geometry)
            light_data.shadow_soft_size = geometry.beam_radius * 0.5
            light_data.shadow_buffer_clip_start = 0.02
            light_data["Fixture ID"] = fixture_id
            light_data["UUID"] = fixturetype_id
            if CONES:
                light_data.show_cone = True
        light_object = bpy.data.objects.new("Spot", light_data)
        light_object.hide_select = True
        light_object.parent = obj_child
        create_gdtf_props(light_object, fixturename)
        light_object["Geometry Class"] = geometry.__class__.__name__
        light_object["Lamp Type"] = light_data["Lamp Type"] = lamp_type
        light_object["Original Name"] = geometry.name
        create_power_property(obj_child, light_power)
        create_power_property(light_object, light_power)
        create_power_property(light_data, light_power)
        create_radius_property(obj_child, geometry.beam_radius)
        create_radius_property(light_object, geometry.beam_radius)
        create_radius_property(light_data, geometry.beam_radius)
        create_ctc_property(obj_child, ctc, "Temperature")
        create_ctc_property(light_object, ctc, "Temperature")
        create_ctc_property(light_data, ctc, "Temperature")
        if obj_child.get("RGB") or childname in color_channels:
            light_object["RGB"] = True
        if zoom_range:
            create_range_property(obj_child, beam_angle, "Focus", zoom_range)
            create_range_property(light_object, beam_angle, "Focus", zoom_range)
            create_range_property(light_data, beam_angle, "Focus", zoom_range)
            create_range_property(obj_child, zoom_range, "Range")
            create_range_property(light_object, zoom_range, "Range")
            create_range_property(light_data, zoom_range, "Range")
        else:
            create_range_property(obj_child, beam_angle, "Focus")
            create_range_property(light_object, beam_angle, "Focus")
            create_range_property(light_data, beam_angle, "Focus")
        obj_child.matrix_parent_inverse = light_object.matrix_world.inverted()
        collection.objects.link(light_object)
        gobo_radius = 2.2 * 0.01 * math.tan(math.radians(geometry.beam_angle / 2))
        goboGeometry = SimpleNamespace(name=f"Gobo {geometry}", length=gobo_radius, width=gobo_radius,
                                       height=0, primitive_type="Plane", beam_radius=geometry.beam_radius)
        if not light_data.use_nodes:
            light_data.use_nodes = True
            nodes = light_data.node_tree.nodes
            links = light_data.node_tree.links
            emit = nodes.get("Emission")
            emit.label = emit.name = "Fixture"
            light_mix = nodes.new("ShaderNodeMixRGB")
            gamma_node = nodes.new("ShaderNodeGamma")
            factor_node = nodes.new("ShaderNodeValue")
            lightpath = nodes.new("ShaderNodeLightPath")
            light_normal = nodes.new("ShaderNodeNormal")
            color_temp = nodes.new('ShaderNodeBlackbody')
            fresnel_node = nodes.new("ShaderNodeFresnel")
            light_uv = nodes.new("ShaderNodeNewGeometry")
            layerweight = nodes.new("ShaderNodeLayerWeight")
            lightfalloff = nodes.new("ShaderNodeLightFalloff")
            lightcontrast = nodes.new("ShaderNodeBrightContrast")
            light_mix.label = light_mix.name = "Light Mix"
            light_uv.label = light_uv.name = "Light Orientation"
            factor_node.label = factor_node.name = "Focus Factor"
            color_temp.label = color_temp.name = "Color Temperature"
            lightcontrast.label = lightcontrast.name = "Light Contrast"
            focus_factor = light_power / max(pow(geometry.beam_angle, 2), 1e-09)
            light_mix.blend_type = 'MULTIPLY'
            emit.location = (100, 320)
            light_mix.location = (-100, 360)
            gamma_node.location = (-500, 340)
            color_temp.location = (-300, 220)
            factor_node.location = (-700, 150)
            lightfalloff.location = (-500, 220)
            lightcontrast.location = (-300, 360)
            if has_gobos or has_iris:
                light_data.shadow_soft_size = geometry.beam_radius * 0.2
                create_gobo(geometry, goboGeometry)
            color_temp.inputs[0].default_value = ctc
            emit.inputs[0].default_value[:3] = [1.0] * 3
            light_mix.inputs[1].default_value[:3] = [1.0] * 3
            light_mix.inputs[2].default_value[:3] = [1.0] * 3
            factor_node.outputs[0].default_value = focus_factor
            lightpath.location = (-1340, 320) if has_gobos else (-900, 320)
            light_uv.location = (-1720, 300) if has_gobos else (-1300, 300)
            layerweight.location = (-1160, 440) if has_gobos else (-700, 440)
            fresnel_node.location = (-1340, 420) if has_gobos else (-900, 420)
            light_normal.location = (-1540, 400) if has_gobos else (-1100, 400)
            links.new(light_normal.outputs[0], fresnel_node.inputs[1])
            links.new(light_normal.outputs[1], fresnel_node.inputs[0])
            links.new(layerweight.outputs[0], lightcontrast.inputs[2])
            links.new(layerweight.outputs[1], lightfalloff.inputs[1])
            links.new(gamma_node.outputs[0], lightcontrast.inputs[0])
            links.new(factor_node.outputs[0], lightfalloff.inputs[0])
            links.new(fresnel_node.outputs[0], layerweight.inputs[0])
            links.new(lightpath.outputs[10], lightcontrast.inputs[1])
            links.new(lightcontrast.outputs[0], light_mix.inputs[1])
            links.new(lightpath.outputs[9], lightfalloff.inputs[1])
            links.new(lightfalloff.outputs[1], light_mix.inputs[0])
            links.new(light_uv.outputs[1], light_normal.inputs[0])
            links.new(light_uv.outputs[3], layerweight.inputs[1])
            links.new(lightpath.outputs[8], gamma_node.inputs[1])
            links.new(color_temp.outputs[0], light_mix.inputs[2])
            links.new(lightfalloff.outputs[0], emit.inputs[1])
            links.new(light_mix.outputs[0], emit.inputs[0])
            out_distance = (lightpath.outputs[:8]
                            if len(lightpath.outputs) >= 14
                            else lightpath.outputs[:7])
            for out in out_distance:
                out.hide = True

    def create_laser(geometry):
        if cleanup_name(geometry) not in objectDict:
            return
        obj_child = objectDict[cleanup_name(geometry)]
        if "Laser" not in obj_child.name.lower():
            obj_child.name = f"Laser {obj_child.name}"
        obj_child["Diameter"] = geometry.beam_diameter
        obj_child.visible_shadow = False
        obj_child.rotation_mode = 'XYZ'

    def create_gobo(geometry, goboGeometry):
        geometry_class = geometry.__class__.__name__
        goboname = f"ID{fixture_id}_{name}_Gobo" if fixture_id >= 1 else f"{name}_Gobo"
        msh = bpy.data.meshes.get(goboname)
        if msh and msh.get("Geometry Type") == "Gobo" and msh.get("UUID") == fixturetype_id:
            obj = bpy.data.objects.new(goboname, msh)
        else:
            obj = load_blender_primitive(goboGeometry)
            obj.data["UUID"] = fixturetype_id
        create_gdtf_props(obj, fixturename)
        obj["Geometry Class"] = obj.data["Geometry Class"] = geometry_class     
        obj["Geometry Type"] = obj.data["Geometry Type"] = "Gobo"
        create_radius_property(obj, goboGeometry.beam_radius)
        create_radius_property(obj.data, goboGeometry.beam_radius)
        obj.dimensions = (goboGeometry.length, goboGeometry.width, 0)
        obj.name = obj.data.name = goboGeometry.name
        objectDict[cleanup_name(goboGeometry)] = obj
        constraint_child_to_parent(geometry, goboGeometry)

    def calculate_spot_blend(geometry):
        """Return spot_blend value based on beam_type."""
        beam_type = geometry.beam_type.value
        if not has_gobos and any(beam_type == x for x in ["Wash", "Fresnel", "PC"]):
            return 1.0
        return 0.0

    def add_child_position(geometry):
        """Add a child position."""
        obj_child = objectDict.get(cleanup_name(geometry))
        geometry_mtx = mathutils.Matrix(geometry.position.matrix)
        translate = geometry_mtx.to_translation()
        rotation = geometry_mtx.to_3x3().inverted()
        scale = geometry_mtx.to_scale()
        obj_child.matrix_local = mathutils.Matrix.LocRotScale(translate, rotation, scale)

    def constraint_child_to_parent(parent_geometry, child_geometry):
        if not cleanup_name(parent_geometry) in objectDict:
            return
        if not cleanup_name(child_geometry) in objectDict:
            return
        obj_parent = objectDict.get(cleanup_name(parent_geometry))
        obj_child = objectDict.get(cleanup_name(child_geometry))
        if hasattr(parent_geometry, "reference_rgb"):
            obj_parent["RGB"] = True
        if hasattr(child_geometry, "reference_rgb"):
            obj_child["RGB"] = True
        obj_child.parent = obj_parent
        obj_child.matrix_parent_inverse = obj_parent.matrix_world.inverted()

    def update_geometry(geometry):
        """Recursively update objects position, rotation and scale."""
        if not isinstance(geometry, pygdtf.GeometryReference):
            add_child_position(geometry)
        if isinstance(geometry, pygdtf.GeometryBeam):
            create_beam(geometry)
        if isinstance(geometry, pygdtf.GeometryLaser):
            create_laser(geometry)
        elif isinstance(geometry, (pygdtf.GeometryMediaServerCamera)):
            create_camera(geometry)
        elif isinstance(geometry, pygdtf.GeometryReference):
            reference = copy.deepcopy(profile.geometries.get_geometry_by_name(geometry.geometry))
            reference.name = cleanup_name(geometry)
            add_child_position(reference)
            reference.position = geometry.position
            add_child_position(reference)
            if isinstance(reference, pygdtf.GeometryBeam):
                create_beam(reference)
            if isinstance(reference, pygdtf.GeometryLaser):
                create_laser(reference)
            elif isinstance(reference, (pygdtf.GeometryMediaServerCamera)):
                create_camera(reference)
            if hasattr(reference, "geometries"):
                if len(reference.geometries) > 0:
                    for child_geometry in reference.geometries:
                        setattr(child_geometry, "reference_root", str(reference.name))
                        if hasattr(geometry, "reference_rgb"):
                            rgb_reference = getattr(geometry, "reference_rgb")
                            setattr(child_geometry, "reference_rgb", rgb_reference)
                        constraint_child_to_parent(reference, child_geometry)
                        update_geometry(child_geometry)
            return

        if hasattr(geometry, "geometries"):
            if len(geometry.geometries) > 0:
                for child_geometry in geometry.geometries:
                    if hasattr(geometry, "reference_root"):
                        root_reference = getattr(geometry, "reference_root")
                        setattr(child_geometry, "reference_root", root_reference)
                    if hasattr(geometry, "reference_rgb"):
                        rgb_reference = getattr(geometry, "reference_rgb")
                        setattr(child_geometry, "reference_rgb", rgb_reference)
                    constraint_child_to_parent(geometry, child_geometry)
                    update_geometry(child_geometry)

    load_geometries(root_geometry)
    update_geometry(root_geometry)


    def get_axis_objects(attribute):
        axis_objects = []
        for obj in objectDict.values():
            feature = channelData.get(obj.get("Original Name"))
            axisrange = rangeData.get(obj.get("Original Name"))
            if feature == attribute:
                obj["Mobile Axis"] = feature
                obj["Geometry Type"] = "Axis"
                create_range_property(obj, tuple(axisrange), "Range")
                axis_objects.append(obj)
        return axis_objects


    def check_center_object(obj):
        return (abs(round(obj.location.x, 1)) == 0.0 and
                abs(round(obj.location.y, 1)) == 0.0)


    yokes = get_axis_objects("Pan")
    heads = get_axis_objects("Tilt")
    base = next(ob for ob in objectDict.values() if ob.get("Use Root"))
    moving_objects = [ob for ob in objectDict.values() if ob.get("Geometry Type") == "Axis"]

    if TARGETS:
        data_objects = bpy.data.objects
        main_target = bpy.data.objects.new("Target", None)
        main_target.empty_display_size = 0.4
        collection.objects.link(main_target)
        create_fixture_id(main_target, fixture_id)
        create_gdtf_props(main_target, fixturename)
        main_target["Geometry Type"] = "Target"
        main_target["MVR Type"] = profile_cls
        main_target["UUID"] = target_id
        targetData[target_id] = main_target
    for idx, obj in enumerate(moving_objects):
        center_object = check_center_object(obj)
        check_pan = obj.get("Mobile Axis") == "Pan"
        check_tilt = obj.get("Mobile Axis") == "Tilt"
        center_parent = obj.parent and check_center_object(obj.parent)
        check_parent = obj.parent and obj.parent.get("Mobile Axis") in movingHead
        check_master = (check_parent and obj.parent.parent and
                        obj.parent.parent.get("Mobile Axis") in movingHead)
        if TARGETS:
            if (not len(base.constraints) and
                (check_pan and not len(obj.children) or
                 (not check_pan and not heads))
            ):
                track_constraint = base.constraints.new('TRACK_TO')
                track_constraint.target = main_target
                continue
            else:
                lock_constraint = obj.constraints.new('LOCKED_TRACK')
            if check_tilt or check_master:
                lock_constraint.track_axis = 'TRACK_NEGATIVE_Z'
                if check_tilt:
                    lock_constraint.lock_axis = 'LOCK_X'
                else:
                    lock_constraint.lock_axis = 'LOCK_Y'
            else:
                lock_constraint.track_axis = 'TRACK_NEGATIVE_Y'
                lock_constraint.lock_axis = 'LOCK_Z'
            if center_object and center_parent:
                lock_constraint.target = main_target
                obj["Target ID"] = target_id
            else:
                if obj.parent and len(obj.parent.children) > 1:
                    if not center_object or (center_object and not center_parent):
                        target_name = "Target %s" % obj.name
                        obj_target = bpy.data.objects.new(target_name, None)
                        obj_target.empty_display_type = 'SINGLE_ARROW'
                        obj_target.empty_display_size = 0.2
                        obj_target.parent = main_target
                        create_fixture_id(obj_target, fixture_id)
                        create_gdtf_props(obj_target, fixturename)
                        obj_target["Geometry Class"] = "Target"
                        main_target["MVR Type"] = profile_cls
                        obj_target["Reference"] = obj.get("Original Name", obj.name)
                        collection.objects.link(obj_target)
                        if not center_object:
                            obj_target.location = (obj.location.x, obj.location.y, 0)
                        elif center_object and not center_parent:
                            obj_target.location = (obj.parent.location.x, obj.parent.location.y, 0)
                        lock_constraint.target = obj_target
        limit_constraint = obj.constraints.new('LIMIT_ROTATION')
        range_min = math.radians(min(rangeData.get(obj.get("Original Name"),(-270, 270))))
        if check_master:
            obj["Sub Axis"] = True
            limit_constraint.owner_space = 'LOCAL'
        if check_tilt:
            limit_constraint.use_limit_x = True
            limit_constraint.max_x = range_min
        else:
            limit_constraint.use_limit_z = True
            limit_constraint.max_z = range_min
    if TARGETS and not yokes and not heads and not len(base.constraints):
        track_constraint = base.constraints.new('TRACK_TO')
        track_constraint.target = main_target
    
    # 2D thumbnail planning symbol
    obj = load_2d(profile, name)
    if obj is not None:
        obj["2D Symbol"] = "all"
        objectDict["2D Symbol"] = obj
        obj.show_in_front = True
        if obj.active_material and obj.active_material.grease_pencil:
            obj.active_material.grease_pencil.show_stroke = True

        # Add constraints
        constraint_copyLocation = obj.constraints.new(type='COPY_LOCATION')
        constraint_copyRotation = obj.constraints.new(type='COPY_ROTATION')
        constraint_copyLocation.target = base
        constraint_copyRotation.target = base
        constraint_copyRotation.use_z = True
        constraint_copyRotation.use_x = False
        constraint_copyRotation.use_y = False

    # Link objects to collection
    for name, obj in objectDict.items():
        if obj.name not in collection.objects:
            collection.objects.link(obj)
    
    objectDict.clear()
    return collection


def create_beam_features(assembly, blend, focus, iris, gobo_data, gobo_count, start, gel,
                         wheels, wheelname, wheel_count, zoom_angle, zoom_range, root_obj):

    """Create the beam effect attributes."""
    rgb_beam = root_obj.get("RGB Beam")
    check_color = assembly.get("RGB")
    random_glow = [random.uniform(0.0, 1.0) for _ in range(3)]

    if assembly.type == 'LIGHT':
        zoom_angle = assembly.get("Focus")
        nodes = assembly.data.node_tree.nodes
        links = assembly.data.node_tree.links
        gamma_node = nodes.get("Gamma")
        emit_node = nodes.get("Fixture")
        light_mix = nodes.get("Light Mix")
        light_path = nodes.get("Light Path")
        focus_node = nodes.get("Focus Factor")
        light_output = nodes.get("Light Output")
        lightfalloff = nodes.get("Light Falloff")
        light_uv = nodes.get("Light Orientation")
        light_temperature = assembly.get("Temperature")
        lightcontrast = nodes.get("Light Contrast")
        color_temp = nodes.get("Color Temperature")
        create_dimmer_driver(assembly.data, root_obj, assembly)
        if check_color:
            if rgb_beam is None:
                create_color_property(root_obj, gel, "RGB Beam")
            create_color_driver(assembly.data, root_obj, "RGB Beam")
        if blend:
            create_factor_driver(assembly, root_obj)
        if focus:
            create_focus_driver(assembly, root_obj)
        if root_obj and light_temperature:
            create_ctc_property(root_obj, light_temperature, "Light CTC")
            create_ctc_driver(assembly, root_obj)
        if zoom_range and zoom_angle:
            check_zoom = root_obj.get("Focus Zoom", False)
            if not check_zoom:
                create_range_property(root_obj, zoom_angle, "Focus Zoom", zoom_range)
            create_zoom_driver(assembly.data, root_obj, "Focus Zoom")
        elif zoom_angle:
            create_zoom_driver(assembly.data, root_obj, "Focus")
        if iris:
            assembly.data.use_soft_falloff = False
            iris_node = nodes.new("ShaderNodeTexImage")
            iris_out = iris_node
            if gobo_data:
                iris_mix = nodes.new("ShaderNodeMixRGB")
                links.new(iris_node.outputs[0], iris_mix.inputs[2])
                links.new(light_path.outputs[8], iris_mix.inputs[0])
                iris_mix.label = iris_mix.name = "Iris Mix"
                iris_mix.blend_type = 'DARKEN'
                iris_mix.location = (-500, 340)
                iris_out = iris_mix
            else:
                assembly.location[2] += 0.01
            links.new(light_path.outputs[9], lightcontrast.inputs[1])
            create_iris_nodes(assembly.data, root_obj, iris_node, light_uv)
            emit_node.location = (300, 300)
            light_mix.location = (100, 340)
            color_temp.location = (-100, 200)
            focus_node.location = (-500, 150)
            gamma_node.location = (-300, 340)
            light_output.location = (500, 300)
            lightfalloff.location = (-300, 220)
            lightcontrast.location = (-100, 360)
        if gobo_data and start is not None:
            assembly.data.shadow_buffer_clip_start = 0.001
            assembly.location[2] += 0.01
            wheel_node = nodes.new("ShaderNodeTexImage")
            wheel_rota = nodes.new("ShaderNodeVectorRotate")
            wheel_node.image = start
            wheel_node.extension = 'EXTEND'
            wheel_node.label = wheel_node.name = wheelname
            wheel_rota.label = wheel_rota.name = "%s Rotate" % wheelname
            wheel_node.color_mapping.blend_type = 'LINEAR_LIGHT'
            wheel_node.location = (-980, 440)
            wheel_rota.location = (-1160, 310)
            emit_node.inputs[0].default_value[:3] = gel[:]
            create_gobo_driver(wheel_node, wheel_rota, root_obj, gobo_count)
            links.new(light_uv.outputs[5], wheel_rota.inputs[0])
            links.new(wheel_rota.outputs[0], wheel_node.inputs[0])
            links.new(wheel_node.outputs[0], gamma_node.inputs[0])
            pre_node = wheel_node
            if wheels:
                for idx, wheel in enumerate(list(gobo_data.keys())[1:], 2):
                    start = gobo_data.get(wheel)
                    gobo_name = "Gobo %d" % idx
                    align_x = int((idx - 2) * 280)
                    align_y = int((idx - 2) * -160)
                    slot_count = start.get("Count")
                    gobo_mix = nodes.new("ShaderNodeMixRGB")
                    gobo_node = nodes.new("ShaderNodeTexImage")
                    rota_node = nodes.new("ShaderNodeVectorRotate")
                    root_obj["%s Select" % gobo_name] = 0
                    gobo_node.image = start
                    gobo_mix.blend_type = 'DARKEN'
                    gobo_node.extension = 'EXTEND'
                    gobo_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                    mix_name = "Gobo %d Mix" % (idx - 1) if idx > 2 else "Gobo Mix"
                    gobo_mix.label = gobo_mix.name = mix_name
                    rota_node.label = rota_node.name = "%s Rotate" % gobo_name
                    gobo_node.label = gobo_node.name = gobo_name
                    create_gobo_property(root_obj, slot_count, gobo_name)
                    create_gobo_driver(gobo_node, rota_node, root_obj, slot_count)
                    gobo_mix.location = (-700 + align_x, 340)
                    gobo_node.location = (-980 + align_x, 40)
                    rota_node.location = (-1160, 40 + align_y)
                    emit_node.location = (300 + align_x, 320) if iris else (100 + align_x, 320)
                    light_mix.location = (100 + align_x, 360) if iris else (-100 + align_x, 360)
                    color_temp.location = (-100 + align_x, 220) if iris else (-300 + align_x, 220)
                    gamma_node.location = (-300 + align_x, 340) if iris else (-500 + align_x, 340)
                    focus_node.location = (-500 + align_x, 150) if iris else (-300 + align_x, 150)
                    light_output.location = (500 + align_x, 300) if iris else (300 + align_x, 300)
                    lightfalloff.location = (-300 + align_x, 220) if iris else (-500 + align_x, 220)
                    lightcontrast.location = (-100 + align_x, 360) if iris else (-300 + align_x, 360)
                    if iris:
                        iris_mix.location = (-500 + align_x, 340)
                        iris_node.location = (-700 + align_x, 150)
                    gobo_mix.inputs[1].default_value[:3] = [1.0] * 3
                    gobo_mix.inputs[2].default_value[:3] = [1.0] * 3
                    links.new(pre_node.outputs[0], gobo_mix.inputs[1])
                    links.new(gobo_node.outputs[0], gobo_mix.inputs[2])
                    links.new(light_uv.outputs[5], rota_node.inputs[0])
                    links.new(rota_node.outputs[0], gobo_node.inputs[0])
                    links.new(gobo_mix.outputs[0], gamma_node.inputs[0])
                    links.new(light_path.outputs[8], gobo_mix.inputs[0])
                    pre_node = gobo_mix
        else:
            gradient_node = nodes.new("ShaderNodeTexGradient")
            gradient_node.label = gradient_node.name = "Gradient"
            gradient_node.gradient_type = 'RADIAL'
            gradient_node.location = (-700, 300)
            links.new(light_uv.outputs[5], gradient_node.inputs[0])
            links.new(gradient_node.outputs[0], gamma_node.inputs[0])
            if assembly.parent and assembly.parent.parent and assembly.parent.parent.dimensions.z < 0.05:
                assembly.location[2] += -0.02
        if iris:
            links.new(iris_out.outputs[0], gamma_node.inputs[0])
            if gobo_data:
                links.new(pre_node.outputs[0], iris_mix.inputs[1])
    elif assembly.type == 'MESH' and len(assembly.data.materials):
        if assembly.get("Geometry Type") == "Beam":
            emit_color = assembly.get("RGB", False)
            beam_material = assembly.data.materials[0]
            beam_material.use_nodes = True
            principled_node = beam_material.node_tree.nodes.get("Principled BSDF")
            if emit_color:
                if rgb_beam is None:
                    create_color_property(root_obj, gel, "RGB Beam")
                create_color_driver(principled_node.inputs["Emission Color"], root_obj, "RGB Beam")
            create_dimmer_driver(principled_node.inputs["Emission Strength"], root_obj, assembly)
        elif assembly.get("Geometry Type") == "Glow":
            glow_color = assembly.get("RGB", False)
            glow_material = assembly.data.materials[0]
            glow_material.use_nodes = True
            principled_node = glow_material.node_tree.nodes.get("Principled BSDF")
            if glow_color:
                create_color_property(root_obj, random_glow, "RGB Glow")
                create_color_driver(principled_node.inputs["Emission Color"], root_obj, "RGB Glow")
            create_dimmer_driver(principled_node.inputs["Emission Strength"], root_obj, assembly)   
        elif assembly.get("Geometry Type") == "Gobo":
            gobo_material = assembly.data.materials[0]
            if zoom_range and zoom_angle:
                check_zoom = root_obj.get("Focus Zoom", False) 
                if not check_zoom:
                    create_range_property(root_obj, zoom_angle, "Focus Zoom", zoom_range)
                create_range_property(assembly, zoom_angle, "Focus", zoom_range)
                create_zoom_driver(assembly, root_obj, "Focus Zoom")
            if not gobo_material.use_nodes:
                gobo_material.use_nodes = True
                gobo_nodes = gobo_material.node_tree.nodes
                gobo_links = gobo_material.node_tree.links
                material_node = gobo_nodes.get("Material Output")
                principled_bsdf = gobo_nodes.get("Principled BSDF")
                gobo_nodes.remove(principled_bsdf)
                gobo_cord = gobo_nodes.new("ShaderNodeTexCoord")
                gobo_cord.label = gobo_cord.name = "Gobo Coordinate"
                opacity_node = gobo_nodes.new("ShaderNodeBsdfTransparent")
                opacity_node.label = opacity_node.name = "Wheel Shader"
                previous_node = None
                if gobo_count:
                    wheel_node = gobo_nodes.new("ShaderNodeTexImage")
                    wheel_rota = gobo_nodes.new("ShaderNodeVectorRotate")
                    wheel_rota.label = wheel_rota.name = "%s Rotate" % wheelname
                    wheel_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                    wheel_node.label = wheel_node.name = wheelname
                    wheel_node.location = (-620, 460)
                    wheel_rota.location = (-840, 310)
                    wheel_node.extension = 'EXTEND'
                    wheel_node.image = start
                    gobo_links.new(gobo_cord.outputs[0], wheel_rota.inputs[0])
                    gobo_links.new(wheel_rota.outputs[0], wheel_node.inputs[0])
                    gobo_links.new(wheel_node.outputs[0], opacity_node.inputs[0])
                    create_gobo_driver(wheel_node, wheel_rota, root_obj, gobo_count)
                    previous_node = wheel_node
                gobo_cord.location = (-1040, 90)
                opacity_node.location = (100, 300)
                gobo_links.new(opacity_node.outputs[0], material_node.inputs[0])
                if wheels:
                    for idx, wheel in enumerate(list(gobo_data.keys())[1:], 2):
                        start = gobo_data.get(wheel)
                        gobo_name = "Gobo %d" % idx
                        align_x = int((idx - 2) * 280)
                        align_y = int((idx - 2) * -150)
                        slot_count = start.get("Count")
                        gobo_mix = gobo_nodes.new("ShaderNodeMixRGB")
                        gobo_node = gobo_nodes.new("ShaderNodeTexImage")
                        rota_node = gobo_nodes.new("ShaderNodeVectorRotate")
                        light_fall = gobo_nodes.get("Light Falloff", False)
                        if not light_fall:
                            light_path = gobo_nodes.new("ShaderNodeLightPath")
                            light_fall = gobo_nodes.new("ShaderNodeLightFalloff")
                            light_fall.location = (-840, 460)
                            light_path.location = (-1040, 460)
                            gobo_links.new(light_path.outputs[1], light_fall.inputs[0])
                            gobo_links.new(light_path.outputs[9], light_fall.inputs[1])
                        gobo_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                        root_obj["%s Select" % gobo_name] = 0
                        gobo_mix.blend_type = 'MULTIPLY'
                        gobo_node.extension = 'EXTEND'
                        gobo_node.image = start
                        mix_name = "Gobo %d Mix" % (idx - 1) if idx > 2 else "Gobo Mix"
                        gobo_mix.label = gobo_mix.name = mix_name
                        rota_node.label = rota_node.name = "%s Rotate" % gobo_name
                        gobo_node.label = gobo_node.name = gobo_name
                        gobo_node.location = (-620 + align_x, 40)
                        rota_node.location = (-840, 40 + align_y)
                        opacity_node.location = (120 + align_x, 300)
                        material_node.location = (320 + align_x, 300)
                        gobo_mix.location = (-340 + align_x, 340) if iris else (-140 + align_x, 340)
                        gobo_mix.inputs[1].default_value[:3] = [1.0] * 3
                        gobo_mix.inputs[2].default_value[:3] = gel[:]
                        create_gobo_driver(gobo_node, rota_node, root_obj, slot_count)
                        gobo_links.new(light_fall.outputs[0], gobo_mix.inputs[0])
                        gobo_links.new(previous_node.outputs[0], gobo_mix.inputs[1])
                        gobo_links.new(gobo_mix.outputs[0], opacity_node.inputs[0])
                        gobo_links.new(gobo_cord.outputs[0], rota_node.inputs[0])
                        gobo_links.new(rota_node.outputs[0], gobo_node.inputs[0])
                        gobo_links.new(gobo_node.outputs[0], gobo_mix.inputs[2])
                        previous_node = gobo_mix
                if iris:
                    light_fall = gobo_nodes.get("Light Falloff", False)
                    iris_node = gobo_nodes.new("ShaderNodeTexImage")
                    if not light_fall:
                        light_path = gobo_nodes.new("ShaderNodeLightPath")
                        light_fall = gobo_nodes.new("ShaderNodeLightFalloff")
                        light_fall.location = (-840, 460)
                        light_path.location = (-1040, 460)
                        gobo_links.new(light_path.outputs[1], light_fall.inputs[0])
                        gobo_links.new(light_path.outputs[9], light_fall.inputs[1])
                    if previous_node is not None:
                        iris_mix = gobo_nodes.new("ShaderNodeMixRGB")
                        iris_mix.label = iris_mix.name = "Iris Mix"
                        iris_mix.blend_type = 'MULTIPLY'
                        iris_mix.location = (-60 + max(wheel_count - 2, 0) * 200, 340)
                        gobo_links.new(iris_node.outputs[0], iris_mix.inputs[2])
                        gobo_links.new(previous_node.outputs[0], iris_mix.inputs[1])
                        gobo_links.new(light_fall.outputs[0], iris_mix.inputs[0])
                    else:
                        iris_mix = iris_node
                    create_iris_nodes(gobo_material, root_obj, iris_node, gobo_cord)
                    if wheels:
                        iris_mix.location = (-60 + max(wheel_count - 2, 0) * 200, 340)
                        iris_node.location = (-260 + max(wheel_count - 2, 0) * 200, 150)
                        opacity_node.location = (140 + max(wheel_count - 2, 0) * 200, 320)
                        material_node.location = (340 + max(wheel_count - 2, 0) * 200, 300)
                    gobo_links.new(iris_mix.outputs[0], opacity_node.inputs[0])
        else:
            for mtl in assembly.data.materials:
                obj_name = assembly.get("Fixture Name", assembly.name)
                split_name = remove_suffix(mtl.name)
                mtl_name = split_name.split("_")[-1]
                mtl.name = "%s_%s" % (obj_name, mtl_name)


def get_fixture_models(profile, name, fix_id, uid, target,
                       dmx, BEAMS, TARGETS, CONES, MODE_NR):
    """Get the fixture models."""
    collections = bpy.data.collections
    if profile == None:
        return None

    new_collection = collections.get(name)
    if (new_collection and
        len(new_collection.objects) and
        new_collection.get("Fixture ID") == fix_id
    ):
        print("Getting collection from cache: %s" % name)
        return new_collection
    else:
        new_collection = build_collection(profile, name, fix_id, uid, target,
                                          dmx, BEAMS, TARGETS, CONES, MODE_NR)
        return new_collection


def get_root_model(model_collection):
    """Get the root base model."""
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        if obj.get("Use Root", False):
            return obj


def get_tilt(model_collection, channels):
    """Get the tilt model."""
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        for channel in channels:
            if ("Tilt" == channel.get("ID") and
                channel.get("Geometry") ==
                obj.get("Original Name", "None")
            ):
                return obj


def get_emit_material(obj, color, fixturename, index, prop):
    """Get a emitter material."""
    obj.hide_select = True
    obj.visible_shadow = False
    emit_color = obj.get("RGB")
    bname = create_fixture_name(fixturename)
    beamname ="ID%d_%s_%s" % (index, bname, prop) if index >= 1 else "%s_%s" % (bname, prop)
    if len(obj.data.materials):
        emit_material = obj.data.materials[0]
        emit_material["Fixture ID"] = index
        emit_material.name = beamname
    else:
        emit_material = bpy.data.materials.get(beamname)
    if (emit_material is None or
        emit_material.get("Fixture ID") != index or
        emit_material.get("RGB") != emit_color
    ):
        obj.data.materials.clear()
        emit_material = bpy.data.materials.new(beamname)
        obj.data.materials.append(emit_material)
        if emit_color:
            emit_material["RGB"] = emit_color
    obj.active_material = emit_material
    create_gdtf_props(emit_material, fixturename)
    emit_material["Fixture ID"] = index
    emit_material["Geometry Type"] = "Beam"
    emit_shader = PrincipledBSDFWrapper(emit_material, is_readonly=False, use_nodes=True)
    emit_shader.emission_strength = 1.0
    emit_shader.emission_color = color[:] if emit_color else emit_shader.base_color[:]



def fixture_build(context, filename, mscale, fixname, position, focus_point, fix_id, gelcolor,
                  collect, fixture, TARGETS=True, BEAMS=True, CONES=False, MODE_NR=0):

    """Create fixture collection."""
    viewlayer = context.view_layer
    object_data = bpy.data.objects
    data_collect = bpy.data.collections
    layer_collect = viewlayer.layer_collection
    gdtf_profile = pygdtf.FixtureType(filename)
    uid = gdtf_profile.fixture_type_id
    random_gobo = None
    has_gobos = False
    channels = []

    if fixture:
        color = convert_color(gelcolor)
        gelcolor = list(i for i in color[:3])
        name = fixture.gdtf_spec
        mode = fixture.gdtf_mode
        fixture_name = fixname
        target_id = str(pyuid.uuid4()) if fixture.focus is None else fixture.focus
    else:
        name = fixname
        mode = FixtureMode(gdtf_profile, MODE_NR)
        fixture_name = create_fixture_name(fixname, " ")
        target_id = str(pyuid.uuid4())


    def index_name(device):
        device_name = device
        if fix_id > 0:
            device_name = "ID%d %s" % (fix_id, remove_suffix(device))
        return device_name


    # Remove Collection if same index
    index_collection = next((col for col in data_collect if col.get("Fixture ID") == fix_id), False)
    if index_collection:
        for obj in index_collection.objects:
            if obj.get("Use Root"):
                position = obj.matrix_world.copy()
            if obj.get("Geometry Type") == "Target":
                focus_point = obj.matrix_world.copy()
            object_data.remove(obj)
        data_collect.remove(index_collection)

    # Import Fixture Model Collection
    model_collection = get_fixture_models(gdtf_profile, name, fix_id, uid, target_id,
                                          mode, BEAMS, TARGETS, CONES, MODE_NR)
    if model_collection:
        patch = get_fixture_address(fix_id)
        if not fixture:
            model_collection["GDTF Spec"] = name
        else:
            model_collection["GDTF Spec"] = fixture.gdtf_spec
            if len(fixture.addresses.address):
                numbers = fixture.addresses.address[0]
                patch = numbers.dmx_break, numbers.universe, numbers.address
        model_collection.name = index_name(fixture_name)
        create_patch_property(model_collection, patch)
        if TARGETS:
            model_collection["Target ID"] = target_id
        if collect and model_collection.name not in collect.children:
            collect.children.link(model_collection)

    # Build DMX channels cache
    if not any(mode == md.name for md in gdtf_profile.dmx_modes):
        if MODE_NR == 0:
            mode = gdtf_profile.dmx_modes[MODE_NR].name
        else:
            mode = gdtf_profile.dmx_modes[min(MODE_NR, len(gdtf_profile.dmx_modes)) - 1].name
    dmx_channels = collect_dmx_channels(gdtf_profile, mode)
    channels += [channel for break_channels in dmx_channels for channel in break_channels]
    has_blend, has_focus, has_iris, zoom_range, wheels = collect_attributes(channels)

    linkDict = {}
    wheel_name = ""
    gobo_data = start_gobo = None
    base = get_root_model(model_collection)
    head = get_tilt(model_collection, channels)
    gobo_count = wheel_count = check_wheels = False
    random_glow = [random.uniform(0.0, 1.0) for _ in range(3)]
    if len(wheels):
        has_gobos = True
        gobo_data = extract_gobos(gdtf_profile, fix_id, fixture_name, wheels)
        wheel_count = len(gobo_data.keys())
        check_wheels = wheel_count > 1
        start_gobo = gobo_data.get(wheels[0])
        gobo_count = start_gobo.get("Count")
        wheel_name = "Gobo 1" if check_wheels else "Gobo"
        random_gobo = random.randint(0, gobo_count)
    elif has_iris:
        check_wheels = False
        wheel_name = "Iris"

    if model_collection:
        root_object = None
        zoom_angle = False
        collection_name = model_collection.get("Fixture Name")
        if collect is None:
            if model_collection.name not in layer_collect.collection.children:
                layer_collect.collection.children.link(model_collection)
            active_layer = layer_collect.children.get(model_collection.name)
        print("creating Fixture... %s" % model_collection.name)
        for obj in model_collection.objects:
            linkDict[obj.name] = obj
            viewlayer.objects.active = obj
            if TARGETS and len(obj.constraints):
                target = obj.get("Target ID")
                locked = obj.constraints.get("Locked Track")
                if locked is not None:
                    for child in obj.children:
                        locked_child = child.constraints.get("Locked Track")
                        if locked_child and locked_child.target is None:
                            locked_child.target = obj.constraints[0].target
                    if target is not None:
                        locked.target = targetData.get(target)
            if obj.type == 'LIGHT':
                obj.hide_select = True
                zoom_angle = obj.get("Focus")
                obj.matrix_world = obj.matrix_world @ obj.parent.matrix_local.inverted()
                obj["UUID"] = uid
            if obj.get("Use Root"):
                root_object = obj
                if has_blend:
                    create_factor_property(obj, "Frost Edge")
                if has_focus:
                    create_factor_property(obj, "Focus Factor", 0.5)
                if has_gobos:
                    obj["%s Select" % wheel_name] = random_gobo
                    create_gobo_property(obj, gobo_count, wheel_name)
                create_dimmer_property(obj, "Intensity")
                obj["Target"] = TARGETS
                obj.id_properties_ensure()
                target_property = obj.id_properties_ui("Target")
                target_property.update(default=TARGETS)
                ob_name = fixture_name.replace("@", "-")
                obj.matrix_world = position @ obj.matrix_world.copy()
                obj.name = index_name(ob_name)
                obj["UUID"] = uid
            elif obj.get("Geometry Type") == "Gobo":
                obj.select_set(False)
                obj.scale = [1.0] * 3
                obj.hide_select = True
                fix_name = fixture_name.replace("@", "-")
                wheelname = "ID%d_%s_Wheel" % (fix_id, fix_name) if fix_id >= 1 else "%s_Wheel" % fix_name
                if len(obj.data.materials):
                    wheel_material = obj.data.materials[0]
                    wheel_material.name = wheel_name
                else:
                    wheel_material = bpy.data.materials.get(wheelname)
                if wheel_material is None or wheel_material.get("Fixture ID") != fix_id:
                    wheel_material = bpy.data.materials.new(wheelname)
                    obj.data.materials.append(wheel_material)
                obj.active_material = wheel_material
                create_gdtf_props(wheel_material, name)
                wheel_material["Geometry Type"] = "Gobo"
                wheel_material["Fixture ID"] = fix_id
                wheel_material["UUID"] = uid
                wheel_material.blend_method = 'BLEND'
            elif obj.get("Geometry Type") == "Beam" and obj.type == 'MESH':
                get_emit_material(obj, gelcolor, fixture_name, fix_id, "Beam")
            elif obj.get("Geometry Type") == "Glow" and obj.type == 'MESH':
                get_emit_material(obj, gelcolor, fixture_name, fix_id, "Glow")
            elif obj.get("Geometry Type") == "Target":
                obj.name = index_name(obj.name)
                obj.matrix_world = focus_point
            elif obj.get("2D Symbol", None) == "all":
                obj.name = index_name("2D Symbol")
                obj.hide_viewport = True
                obj.hide_render = True
                obj.hide_set(True)

        for obj in model_collection.objects:
            check_color = obj.get("RGB")
            rgb_beam = root_object.get("RGB Beam")
            for child in obj.children:
                if child.name in linkDict:
                    linkDict[child.name].parent = obj
                    if check_color:
                        linkDict[child.name]["RGB"] = True
                child.name = index_name(child.name)
            create_beam_features(obj, has_blend, has_focus, has_iris, gobo_data, gobo_count, start_gobo, gelcolor,
                                 check_wheels, wheel_name, wheel_count, zoom_angle, zoom_range, root_object)

            if obj.get("Use Root"):
                for parents in obj.children_recursive:
                    if len(parents.children) > 1:
                        for idx, childs in enumerate(parents.children, 1):
                            if len(childs.children) > 1:
                                parents.visible_shadow = False
                                for i, child in enumerate(childs.children, 1):
                                    child_name = remove_suffix(child.name)
                                    child.name = "%s %d" % (child_name, i)
                            else:
                                for child in childs.children_recursive:
                                    child_name = remove_suffix(child.name)
                                    child.name = "%s %d" % (child_name, idx)
            if obj.get("Geometry Type") == "Axis":
                mobile_axis = obj.get("Mobile Axis")
                check_sub_axis = obj.get("Sub Axis")
                if root_object and mobile_axis in movingHead:
                    if check_sub_axis:
                        create_trackball_property(root_object, "Position", TARGETS)
                        create_trackball_driver(obj, root_object, "Position")
                    else:
                        create_trackball_property(root_object, "Movement", TARGETS)
                        create_trackball_driver(obj, root_object, "Movement")
                obj.hide_select = True
                obj["UUID"] = uid

        for obj in layer_collect.collection.all_objects:
            if obj.get("UUID") == uid or (obj.get("Geometry Type") == "Target" and obj.get("Fixture Name") == collection_name):
                obj.select_set(False) if obj.hide_select else obj.select_set(True)

    linkDict.clear()
    rangeData.clear()
    targetData.clear()
    channelData.clear()


def load_gdtf(context, filename, mscale, name, position, focus_point, fix_id,
              gelcolor, collect, TARGETS=True, BEAMS=True, CONES=False, MODE_NR=0):
    """Load gdtf file."""
    rangeData.clear()
    targetData.clear()
    channelData.clear()

    context.scene.cycles.preview_pause = True
    fixture_build(context, filename, mscale, name, position, focus_point, fix_id,
                  gelcolor, collect, None, TARGETS, BEAMS, CONES, MODE_NR)

    context.scene.cycles.preview_pause = False


def load_prepare(context, filename, global_matrix, collect, align_objects, align_axis, scale_objects,
                 fix_index, fix_count, gel_color, device_position, TARGETS, BEAMS, CONES, MODE_NR):
    """Prepare and align fixtures."""
    name = Path(filename).name
    mscale = mathutils.Matrix.Scale(scale_objects, 4)

    if global_matrix is not None:
        mscale = global_matrix @ mscale

    for idx in range(fix_index, fix_index + fix_count):
        count = idx - fix_index
        distribution = count * align_objects
        align = 0.5 * (fix_count * align_objects) - (0.5 * align_objects)
        spread = (device_position[0] + (distribution - align), device_position[1], device_position[2])
        if align_axis == "Y":
            spread = (device_position[0], device_position[1] + (distribution - align), device_position[2])
        elif align_axis == "Z":
            spread = (device_position[0], device_position[1], device_position[2] + (distribution - align))
        position = mathutils.Matrix.Translation(spread)
        focus_point = mathutils.Matrix.Translation((spread[0], spread[1], 0))
        load_gdtf(context, filename, mscale, name, position, focus_point,
                  idx, gel_color, collect, TARGETS, BEAMS, CONES, MODE_NR)


def load(operator, context, files=[], directory="", filepath="", fixture_index=0, fixture_count=1, fixture_mode=1,
         align_axis={"X"}, align_objects=1.0, scale_objects=1.0, gel_color=[1.0, 1.0, 1.0], device_position=None,
         use_collection=False, use_targets=True, use_beams=True, use_show_cone=False, global_matrix=None):

    """Load gdtf file into blender scene."""
    context.window.cursor_set('WAIT')
    default_layer = context.view_layer.active_layer_collection.collection
    if device_position is None:
        device_position = [0.0, 0.0, 1.0]

    if not len(files):
        files = [Path(filepath)]
        directory = Path(filepath).parent

    for fl in files:
        collect = None
        if use_collection:
            collect = bpy.data.collections.new(Path(fl.name).stem)
            context.scene.collection.children.link(collect)
            context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collect.name]
        load_prepare(context, os.path.join(directory, fl.name), global_matrix, collect, align_objects,
                     align_axis, scale_objects, fixture_index, fixture_count, gel_color, device_position,
                     TARGETS=use_targets, BEAMS=use_beams, CONES=use_show_cone, MODE_NR=fixture_mode)

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
