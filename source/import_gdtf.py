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
import random
import pygdtf
import mathutils
import uuid as pyuid
from types import SimpleNamespace
from io_scene_3ds.import_3ds import load_3ds
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from pathlib import Path

rangeData = {}
targetData = {}
channelData = {}


class FixtureMode(object):

    def __init__(self, profile):
        self._name = next((md.name for md in profile.dmx_modes if
                           md.name.split(' ')[0] == 'Standard'), 'Standard')

    @property
    def name(self):
        return self._name

    def __str__(self):
        return f"{self.name}"


def get_folder_path():
    folder_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(folder_path, "assets", "gdtf")


def cleanup_name(geometry):
    name = geometry.name.replace(" ", "_")
    root_name = ""
    if hasattr(geometry, "reference_root"):
        root_name = f"{geometry.reference_root.replace(' ', '_')}_"
    return f"{root_name}{name}"


def create_fixture_name(name):
    if '@' not in name:
        return name
    split_name = name.split('@')
    if len(split_name) >= 1:
        manufacturer = split_name[0]
        fixture_name = split_name[1]
        clean_name = manufacturer + '_' + fixture_name
    else:
        clean_name = split_name[0]
    return clean_name


def create_fixture_id(item, fixture_id):
    item['Fixture ID'] = fixture_id
    item.id_properties_ensure()
    item_property = item.id_properties_ui('Fixture ID')
    item_property.update(default=0, min=0, max=4096, soft_min=0, soft_max=4096)


def create_gdtf_props(item, name):
    if '_' in name:
        split_name = name.split('_')
    else:
        split_name = name.split()
    if len(split_name) > 1:
        item['Company'] = split_name[0]
        fixture_name = split_name[1]
    else:
        fixture_name = name
    item['Fixture Name'] = fixture_name


def create_dimmer_driver(item, target, power):
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
    ctc_node = item.data.node_tree.nodes.get('Color Temperature')
    ctc_curve = ctc_node.inputs[0].driver_add("default_value")
    ctc_drive = ctc_curve.driver
    ctc_drive.type = 'AVERAGE'
    ctc_var = ctc_drive.variables.new()
    ctc_var.name = "ctc"
    ctc_target = ctc_var.targets[0]
    ctc_target.id = target
    ctc_target.use_fallback_value = True
    ctc_target.fallback_value = item.get('Temperature')
    ctc_target.data_path = '["Light CTC"]'


def create_factor_driver(item, target):
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
    focus_drive.expression = "factor * radius * 2"
    factor_target.data_path = '["Focus Factor"]'
    radius_target.data_path = '["Radius"]'


def create_gobo_driver(item, node, target, count):
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
    range_data = item.get('Range')
    min_angle = min(range_data)
    max_angle = max(range_data)
    check_target = target.get('Target')
    check_pan = item.get('Mobile Axis') == "Pan"
    max_val = "max_z" if check_pan else "max_x"
    min_val = "min_z" if check_pan else "min_x"
    path = f'["{prop}"][0]' if check_pan else f'["{prop}"][1]'
    limit = item.constraints.get('Limit Rotation')
    lock = item.constraints.get('Locked Track')
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
    if item.id_type == 'LIGHT':
        if prop == 'Focus Zoom':
            zoom_curve = item.driver_add("spot_size")
            zoom_drive = zoom_curve.driver
            zoom_drive.type = 'AVERAGE'
            zoom_var = zoom_drive.variables.new()
            zoom_var.name = "zoom"
            zoom_target = zoom_var.targets[0]
            zoom_target.id = target
            zoom_target.data_path = f'["{prop}"]'
        reference = item if prop == 'Focus' else target
        focus = item.node_tree.nodes.get('Focus Factor')
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
        focus_target.id_type = spec_angle.id_type = 'LIGHT' if prop == 'Focus' else 'OBJECT'
        dif_angle.id_type = vol_angle.id_type = 'LIGHT' if prop == 'Focus' else 'OBJECT'
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
    elif item.id_type == 'OBJECT' and prop == 'Focus Zoom':
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
    rota_var = "%s Rotate" % prop
    item[rota_var] = 0.0
    item.id_properties_ensure()
    angle_property = item.id_properties_ui(rota_var)
    gobo_property = item.id_properties_ui("%s Select" % prop)
    gobo_property.update(default=0, min=0, max=count, soft_min=0, soft_max=count, step=1)
    angle_property.update(default=0.0, min=-360.0, max=360.0, soft_min=-540.0, soft_max=540.0, precision=0, step=1.0, subtype='ANGLE')  


def create_color_property(item, color, prop):
    item[prop] = color
    item.id_properties_ensure()
    color_property = item.id_properties_ui(prop)
    color_property.update(default=color, min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, subtype='COLOR_GAMMA')


def create_ctc_property(item, ctc, prop):
    if ctc:
        item[prop] = ctc
        item.id_properties_ensure()
        ctc_property = item.id_properties_ui(prop)
        ctc_property.update(default=ctc, min=100.0, max=1000000.0, soft_min=100.0, soft_max=100000.0, step=100.0, subtype='TEMPERATURE')


def create_dimmer_property(item, prop, intensity=100):
    item[prop] = intensity
    item.id_properties_ensure()
    dimmer_property = item.id_properties_ui(prop)
    dimmer_property.update(default=100, min=0, max=100, soft_min=0, soft_max=100, subtype='PERCENTAGE')


def create_factor_property(item, prop, factor=0.0):
    item[prop] = factor
    item.id_properties_ensure()
    factor_property = item.id_properties_ui(prop)
    factor_property.update(default=factor, min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, precision=1, step=0.1, subtype='FACTOR')


def create_power_property(item, energy):
    item['Power'] = energy
    item.id_properties_ensure()
    dimmer_property = item.id_properties_ui('Power')
    dimmer_property.update(default=energy, min=0.0, max=1000000.0, soft_min=0.0, soft_max=100000.0, subtype='POWER')


def create_radius_property(item, radius):
    rmin = radius * 0.1
    rnorm = radius * 0.5
    item['Radius'] = rnorm
    item.id_properties_ensure()
    radius_property = item.id_properties_ui('Radius')
    radius_property.update(default=rnorm, min=rmin, max=radius, soft_min=rmin, soft_max=radius, step=0.01, subtype='DISTANCE')


def create_range_property(item, angle, prop, limits=False):
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
    vec = (0.0, 0.0, 1.0)
    item[prop] = vec
    item.id_properties_ensure()
    item['Trackball'] = not targets
    pt_property = item.id_properties_ui(prop)
    pt_property.update(default=vec, min=-1.0, max=1.0, soft_min=-1.0, soft_max=1.0, precision=8, step=0.00001, subtype='DIRECTION')


def collect_dmx_channels(gdtf_profile, mode):
    dmx_mode = None
    dmx_channels = []
    dmx_mode = pygdtf.utils.get_dmx_mode_by_name(gdtf_profile, mode)

    if dmx_mode:
        root_geometry = pygdtf.utils.get_geometry_by_name(gdtf_profile, dmx_mode.geometry)
    else:
        root_geometry = None
    device_channels = pygdtf.utils.get_channels_for_geometry(gdtf_profile, root_geometry, dmx_mode.dmx_channels, [])

    for channel, geometry in device_channels:
        channel_range = []
        feature = str(channel.logical_channels[0].attribute)
        functions = channel.logical_channels[0].channel_functions
        if len(functions):
            channel_range += [functions[0].physical_from, functions[0].physical_to]
        if channel.offset is None:
            continue
        channel_break = channel.dmx_break
        if isinstance(geometry, pygdtf.GeometryReference) and channel.dmx_break == 'Overwrite':
            if len(geometry.breaks):
                channel_break = geometry.breaks[0].dmx_break
            else:
                channel_break = 1
        if len(dmx_channels) < channel_break:
            dmx_channels = dmx_channels + [[]] * (channel_break - len(dmx_channels))
        break_channels = dmx_channels[channel_break - 1]
        break_addition = 0
        if hasattr(geometry, "breaks"):
            dmx_offset = pygdtf.utils.get_address_by_break(geometry.breaks, channel_break)
            if dmx_offset is not None:
                break_addition = dmx_offset.address - 1
        offset_coarse = channel.offset[0] + break_addition
        offset_fine = 0
        if len(channel.offset) > 1:
            offset_fine = channel.offset[1] + break_addition
        max_offset = max([offset_coarse, offset_fine])
        if len(break_channels) < max_offset:
            break_channels = break_channels + [{'ID': '', 'Geometry': ''}] * (max_offset - len(break_channels))
        break_channels[offset_coarse - 1] = {'ID': feature, 'Geometry': geometry.name,
                                             'Functions': channel.logical_channels[0].channel_functions}
        if offset_fine > 0:
            break_channels[offset_fine - 1] = {'ID': '+' + feature, 'Geometry': geometry.name,
                                               'Functions': channel.logical_channels[0].channel_functions}
        dmx_channels[channel_break - 1] = break_channels
        if feature in {'Pan', 'Tilt'}:
            channelData[geometry.name] = feature
            if len(channel_range) and (channel_range[0] != channel_range[-1]):
                rangeData.setdefault(geometry.name, []).extend(channel_range)

    for index, break_list in enumerate(dmx_channels):
        dmx_channels[index] = [channel for channel in break_list if channel.get('ID', "") != ""]

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
    primitive = str(model.primitive_type)
    if primitive == 'Cube':
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == 'Pigtail':
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == 'Plane':
        bpy.ops.mesh.primitive_plane_add(size=1.0)
    elif primitive == 'Cylinder':
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.5, depth=1.0)
    elif primitive == 'Sphere':
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=16, radius=0.5)
    obj = bpy.context.view_layer.objects.selected[0]
    obj.users_collection[0].objects.unlink(obj)
    obj.data.transform(mathutils.Matrix.Diagonal((model.length, model.width, model.height)).to_4x4())
    return obj


def load_gdtf_primitive(model):
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
    check_spot = item.id_type == 'LIGHT'
    iris_nodes = item.node_tree.nodes
    iris_links = item.node_tree.links
    create_dimmer_property(root, 'Iris', 0)
    add_node = iris_nodes.new('ShaderNodeVectorMath')
    iris_gobo = bpy.data.images.get("open.png", False)
    scale_node = iris_nodes.new('ShaderNodeVectorMath')
    center_node = iris_nodes.new('ShaderNodeVectorMath')
    cord_output = outputnode.outputs[5] if check_spot else outputnode.outputs[2]
    center_node.inputs[1].default_value[:2] = add_node.inputs[1].default_value[:2] = [0.5] * 2
    outputnode.location = (-1720, 400) if check_spot else (-1440, 160)
    center_node.location = (-1540, 180) if check_spot else (-1240, 120)
    scale_node.location = (-1340, 150) if check_spot else (-1040, 150)
    add_node.location = (-1160, 150) if check_spot else (-840, 150)
    irisnode.location = (-700, 150) if check_spot else (-300, 150)
    center_node.inputs[1].hide = add_node.inputs[1].hide = True
    scale_node.label = scale_node.name = 'Iris Size'
    center_node.label = center_node.name = 'Center'
    add_node.label = add_node.name = 'Iris Vector'
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
    irisnode.label = irisnode.name = 'Iris'
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
                media_name = f"{name}_{wheel.name}-{idx:04}.png"
                media_file = str(slot.media_file_name)
                name_split = media_file.split('.')
                if not len(name_split[0]):
                    destination = Path(wheel_path, media_name)
                    destination.write_bytes(open_image.read_bytes())
                    gobo_source = destination.resolve()
                else:
                    extend = name_split[-1]
                    media_name = f"{name}_{wheel.name}-{idx:04}.{extend}"
                    img_path = Path(os.path.join(images_path, str(media_file)))
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
            sequence['Count'] = gobo_count - 1
            sequence.source = 'SEQUENCE'
            gobo_data[wheel.name] = sequence
    return gobo_data


def get_wheel_slot_colors(profile):
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
            obj.name = '2D Symbol'
            if len(obj.users_collection):
                obj.users_collection[0].objects.unlink(obj)
            obj.rotation_euler[0] = math.radians(-90)
    return obj


def join_parts_apply_transforms(objects):
    join = 0
    single = None
    for ob in objects:
        mb = ob.matrix_basis
        if ob.type == 'MESH' and ob.data.vertices.items():
            ob.select_set(True)
            join += 1
            bpy.context.view_layer.objects.active = ob
            single = ob
            if ob.data.get('Model Type') == 'glb':
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
    folder_path = os.path.join(get_folder_path(), name)
    obj_dimension = mathutils.Vector((model.length, model.width, model.height))

    if model.file.extension.lower() == '3ds':
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
        obj.data['Model Type'] = model.file.extension.lower()
    return obj


def build_collection(profile, name, fixture_id, uid, mode, BEAMS, TARGETS, CONES):
    """Create model collection."""

    objectDict = {}
    color_channels = set()
    fixturetype_id = profile.fixture_type_id
    collection = bpy.data.collections.new(name)
    dmx_mode = pygdtf.utils.get_dmx_mode_by_name(profile, mode)
    has_gobos = has_iris = zoom_range = False

    if dmx_mode is None:
        dmx_mode = profile.dmx_modes[0]
        mode = dmx_mode.name

    collection['Fixture ID'] = fixture_id
    create_gdtf_props(collection, name)
    collection['UUID'] = uid
    root_geometry = pygdtf.utils.get_geometry_by_name(profile, dmx_mode.geometry)
    dmx_channels = collect_dmx_channels(profile, mode)
    logical_channels = [channel for break_channels in dmx_channels for channel in break_channels]
    virtual_channels = pygdtf.utils.get_virtual_channels(profile, mode)

    for channel in logical_channels:
        if 'Color1' in channel['ID']:
            color_channels.add(channel.get('Geometry'))
        elif 'Color' in channel['ID']:
            color_attribute = channel.get('ID')
            if color_attribute[-1] in {'R','G','B','C','M','Y'}:
                color_channels.add(channel.get('Geometry'))
        if 'Gobo' in channel['ID']:
            has_gobos = True
        if 'Iris' in channel['ID']:
            has_iris = True
        if 'Zoom' in channel['ID']:
            zoom_function = channel.get('Functions')
            zoom_range = zoom_function[0].physical_from, zoom_function[0].physical_to


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
            if any(geometry.beam_type.value == x for x in ['None', 'Glow']):
                geometry_type = 'Glow'
        for ob in data_objects:
            ob.select_set(False)

        if isinstance(geometry, pygdtf.GeometryReference):
            reference = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
            geometry.model = reference.model
            if hasattr(reference, "geometries"):
                for sub_geometry in reference.geometries:
                    setattr(sub_geometry, "reference_root", original_name)
                    if original_name in color_channels:
                        setattr(sub_geometry, "reference_rgb", original_name)
                    load_geometries(sub_geometry)

        if geometry.model is None:
            model = pygdtf.Model(name=f"{geometry}", length=0.0001, width=0.0001, height=0.0001, primitive_type='Cube')
            geometry.model = ""
        else:
            model = copy.deepcopy(pygdtf.utils.get_model_by_name(profile, geometry.model))

        if isinstance(geometry, pygdtf.GeometryReference):
            model.name = f"{geometry}"

        obj = None
        mesh_name = ""
        if model.file:
            mesh_name = model.file.name
        primitive = str(model.primitive_type)
        if primitive[-3:] == '1_1':
            primitive = primitive[:-3]
            model.primitive_type = pygdtf.PrimitiveType(primitive)

        # Prefer File first, as some GDTFs have both File and PrimitiveType
        if primitive == 'Undefined' or (model.file and model.file.name != "" and primitive != 'Pigtail'):
            obj = data_objects.get(geometry_name)
            if obj is None or obj.get('Model Name') != mesh_name or obj.get('Fixture ID') != fixture_id:
                geo = data_meshes.get(mesh_name)
                if geo and geo.get('Model Name') == mesh_name and geo.get('UUID') == fixturetype_id:
                    obj = data_objects.new(geometry_name, geo)
                else:
                    try:
                        obj = load_model(profile, name, model)
                    except Exception as exc:
                        print("Error importing 3D model: %s" % exc)
                        model.primitive_type = 'Cube'
                        obj = load_blender_primitive(model)
        else:
            primesh = data_meshes.get(primitive)
            if primesh and primesh.get('UUID') == fixturetype_id:
                obj = data_objects.new(primitive, primesh)
            elif primitive in ['Base', 'Conventional', 'Head', 'Yoke']:
                obj = load_gdtf_primitive(model)
                obj.data.name = primitive
            else:
                obj = load_blender_primitive(model)
                obj.data.name = primitive

        # If object was created
        if obj is not None:
            if obj.data:
                obj_name = obj.name.split('.')[0]
                if obj.get('UUID') is None:
                    obj.data['Geometry Class'] = geometry_class
                    obj.data['Geometry Type'] = geometry_type
                    obj.data['Original Name'] = obj_name
                    obj.data['Model Name'] = mesh_name
                    obj.data['UUID'] = fixturetype_id
                if obj.data.materials:
                    for mtl in obj.data.materials:
                        mtl_name = mtl.name.split('.')[0]
                        if geometry_class == "GeometryBeam":
                            mtl['Fixture ID'] = fixture_id
                        if obj.get('UUID') is None:
                            create_gdtf_props(mtl, name)
                            mtl['Original Name'] = mtl_name
                            mtl['Model Name'] = mesh_name
                            mtl['UUID'] = fixturetype_id
            obj.name = geometry_name
            create_fixture_id(obj, fixture_id)
            create_gdtf_props(obj, name)

            if geometry_name == cleanup_name(root_geometry):
                obj['Fixture Mode'] = mode
                obj['Use Root'] = True
                obj.hide_select = False
            else:
                obj['Geometry Class'] = geometry_class
                obj['Geometry Type'] = geometry_type
                obj['Original Name'] = original_name
                obj.hide_select = True
                if len(mesh_name):
                    obj['Model Name'] = mesh_name
            if isinstance(geometry, pygdtf.GeometryReference):
                obj['Reference'] = str(geometry.geometry)
                obj['Geometry Type'] = obj.data.get('Geometry Type')
            elif hasattr(geometry, "reference_root"):
                obj['Reference'] = getattr(geometry, "reference_root")
            if str(model.primitive_type) == 'Pigtail':
                obj['Geometry Type'] = 'Pigtail'
            objectDict[geometry_name] = obj
            mb = obj.matrix_basis.copy()
            if obj.data.get('Model Type') == 'glb':
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
            return 'Camera'
        if isinstance(geometry, pygdtf.GeometryBeam):
            return 'Beam'
        if isinstance(geometry, pygdtf.GeometryLaser):
            return 'Laser'
        if isinstance(geometry, pygdtf.GeometryAxis):
            return 'Axis'
        if isinstance(geometry, pygdtf.GeometryReference):
            geometry = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
            return get_geometry_type_as_string(geometry)
        return 'Normal'


    def create_camera(geometry):
        if not cleanup_name(geometry) in objectDict:
            return
        obj_child = objectDict.get(cleanup_name(geometry))
        camera_data = bpy.data.cameras.get(name=f"{obj_child.name}")
        if camera_data is None:
            camera_data = bpy.data.cameras.new(name=f"{obj_child.name}")
        camera_object = bpy.data.objects.new('MediaCamera', camera_data)
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
        childname = obj_child.get('Original Name', obj_child.name.split('.')[0])
        obj_child['Fixture ID'] = obj_child.data['Fixture ID'] = fixture_id
        light_power = max(light_energy * 100, 100.0)
        obj_child.data.name = '%s_Beam' % name
        if len(obj_child.data.materials):
            beam_mtl = obj_child.data.materials[0]
            beam_color = beam_mtl.diffuse_color[:3]
            beam_mtl['Fixture ID'] = fixture_id
            if childname in color_channels:
                beam_mtl['RGB'] = True
            beam_mtl.name = '%s_Beam' % name
        beamname = f"{lightname}_{childname}"
        if not BEAMS or obj_child is None:
            return
        if fixture_id >= 1:
            if obj_child.data.get('Fixture ID') != fixture_id:
                emitter = obj_child.data.copy()
                emitter['Fixture ID'] = fixture_id
                obj_child.data = emitter
            beamname = f"ID{fixture_id}_{lightname}_{childname}"
            obj_child.data.name = f"ID{fixture_id}_{name}_Beam"
            obj_child['Geometry Type'] = obj_child.data['Geometry Type'] = "Beam"
            if len(obj_child.data.materials):
                emit_material = obj_child.data.materials[0]
                emit_material['Fixture ID'] = fixture_id
                emit_material.name = beamname
        if any(geometry.beam_type.value == x for x in ['None', 'Glow']):
            glowname = f"ID{fixture_id}_{name}_Glow" if fixture_id >= 1 else '%s_Glow' % name
            obj_child['Geometry Type'] = obj_child.data['Geometry Type'] = "Glow"
            obj_child.data.name = glowname
            if len(obj_child.data.materials):
                glow_material = obj_child.data.materials[0]
                glow_material.name = glowname
            return
        obj_child.visible_shadow = False
        light_data = data_lights.get(beamname)
        if light_data is None or light_data.get('Fixture Name') != lightname:
            light_data = data_lights.new(beamname, 'SPOT')
            light_data.use_custom_distance = True
            create_gdtf_props(light_data, name)
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
            light_data['Fixture ID'] = fixture_id
            light_data['UUID'] = fixturetype_id
            if CONES:
                light_data.show_cone = True
        light_object = bpy.data.objects.new('Spot', light_data)
        light_object.hide_select = True
        light_object.parent = obj_child
        create_gdtf_props(light_object, name)
        light_object['Geometry Class'] = geometry.__class__.__name__
        light_object['Lamp Type'] = light_data['Lamp Type'] = lamp_type
        light_object['Original Name'] = geometry.name
        create_power_property(obj_child, light_power)
        create_power_property(light_object, light_power)
        create_power_property(light_data, light_power)
        create_radius_property(obj_child, geometry.beam_radius)
        create_radius_property(light_object, geometry.beam_radius)
        create_radius_property(light_data, geometry.beam_radius)
        create_ctc_property(obj_child, ctc, 'Temperature')
        create_ctc_property(light_object, ctc, 'Temperature')
        create_ctc_property(light_data, ctc, 'Temperature')
        if obj_child.get('RGB') or childname in color_channels:
            light_object['RGB'] = True
        if zoom_range:
            create_range_property(obj_child, beam_angle, 'Focus', zoom_range)
            create_range_property(light_object, beam_angle, 'Focus', zoom_range)
            create_range_property(light_data, beam_angle, 'Focus', zoom_range)
            create_range_property(obj_child, zoom_range, 'Range')
            create_range_property(light_object, zoom_range, 'Range')
            create_range_property(light_data, zoom_range, 'Range')
        else:
            create_range_property(obj_child, beam_angle, 'Focus')
            create_range_property(light_object, beam_angle, 'Focus')
            create_range_property(light_data, beam_angle, 'Focus')
        obj_child.matrix_parent_inverse = light_object.matrix_world.inverted()
        collection.objects.link(light_object)

        gobo_radius = 2.2 * 0.01 * math.tan(math.radians(geometry.beam_angle / 2))
        goboGeometry = SimpleNamespace(name=f"Gobo {geometry}", length=gobo_radius, width=gobo_radius,
                                       height=0, primitive_type='Plane', beam_radius=geometry.beam_radius)

        if not light_data.use_nodes:
            light_data.use_nodes = True
            nodes = light_data.node_tree.nodes
            links = light_data.node_tree.links
            emit = nodes.get('Emission')
            emit.label = emit.name = 'Fixture'
            light_mix = nodes.new('ShaderNodeMixRGB')
            gamma_node = nodes.new('ShaderNodeGamma')
            factor_node = nodes.new('ShaderNodeValue')
            lightpath = nodes.new('ShaderNodeLightPath')
            light_normal = nodes.new('ShaderNodeNormal')
            color_temp = nodes.new('ShaderNodeBlackbody')
            fresnel_node = nodes.new('ShaderNodeFresnel')
            light_uv = nodes.new('ShaderNodeNewGeometry')
            layerweight = nodes.new('ShaderNodeLayerWeight')
            lightfalloff = nodes.new('ShaderNodeLightFalloff')
            lightcontrast = nodes.new('ShaderNodeBrightContrast')
            light_mix.label = light_mix.name = 'Light Mix'
            light_uv.label = light_uv.name = 'Light Orientation'
            factor_node.label = factor_node.name = 'Focus Factor'
            color_temp.label = color_temp.name = 'Color Temperature'
            lightcontrast.label = lightcontrast.name = 'Light Contrast'
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
            links.new(lightpath.outputs[9], lightcontrast.inputs[1])
            links.new(lightcontrast.outputs[0], light_mix.inputs[1])
            links.new(lightfalloff.outputs[1], light_mix.inputs[0])
            links.new(lightpath.outputs[7], lightfalloff.inputs[1])
            links.new(light_uv.outputs[1], light_normal.inputs[0])
            links.new(light_uv.outputs[3], layerweight.inputs[1])
            links.new(lightpath.outputs[8], gamma_node.inputs[1])
            links.new(color_temp.outputs[0], light_mix.inputs[2])
            links.new(lightfalloff.outputs[0], emit.inputs[1])
            links.new(light_mix.outputs[0], emit.inputs[0])
            for out in lightpath.outputs[:7]:
                out.hide = True


    def create_laser(geometry):
        if cleanup_name(geometry) not in objectDict:
            return
        obj_child = objectDict[cleanup_name(geometry)]
        if 'Laser' not in obj_child.name.lower():
            obj_child.name = f"Laser {obj_child.name}"
        obj_child['Diameter'] = geometry.beam_diameter
        obj_child.visible_shadow = False
        obj_child.rotation_mode = 'XYZ'


    def create_gobo(geometry, goboGeometry):
        geometry_class = geometry.__class__.__name__
        goboname = f"ID{fixture_id}_{name}_Gobo" if fixture_id >= 1 else f"{name}_Gobo"
        msh = bpy.data.meshes.get(goboname)
        if msh and msh.get('Geometry Type') == 'Gobo' and msh.get('UUID') == fixturetype_id:
            obj = bpy.data.objects.new(goboname, msh)
        else:
            obj = load_blender_primitive(goboGeometry)
            obj.data['UUID'] = fixturetype_id
        create_gdtf_props(obj, name)
        obj['Geometry Class'] = obj.data['Geometry Class'] = geometry_class     
        obj['Geometry Type'] = obj.data['Geometry Type'] = 'Gobo'
        create_radius_property(obj, goboGeometry.beam_radius)
        create_radius_property(obj.data, goboGeometry.beam_radius)
        obj.dimensions = (goboGeometry.length, goboGeometry.width, 0)
        obj.name = obj.data.name = goboGeometry.name
        objectDict[cleanup_name(goboGeometry)] = obj
        constraint_child_to_parent(geometry, goboGeometry)


    def calculate_spot_blend(geometry):
        """Return spot_blend value based on beam_type."""
        beam_type = geometry.beam_type.value
        if not has_gobos and any(beam_type == x for x in ['Wash', 'Fresnel', 'PC']):
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
            obj_parent['RGB'] = True
        if hasattr(child_geometry, "reference_rgb"):
            obj_child['RGB'] = True
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
            reference = copy.deepcopy(pygdtf.utils.get_geometry_by_name(profile, geometry.geometry))
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
            feature = channelData.get(obj.get('Original Name'))
            axisrange = rangeData.get(obj.get('Original Name'))
            if feature == attribute:
                obj['Mobile Axis'] = feature
                obj['Geometry Type'] = 'Axis'
                create_range_property(obj, tuple(axisrange), 'Range')
                axis_objects.append(obj)
        return axis_objects


    def check_center_object(obj):
        return (abs(round(obj.location.x, 1)) == 0.0 and abs(round(obj.location.y, 1)) == 0.0)


    yokes = get_axis_objects('Pan')
    heads = get_axis_objects('Tilt')
    base = next(ob for ob in objectDict.values() if ob.get('Use Root'))
    moving_objects = [ob for ob in objectDict.values() if ob.get('Geometry Type') == 'Axis']

    if TARGETS:
        target_uid = str(pyuid.uuid4())
        data_objects = bpy.data.objects
        main_target = bpy.data.objects.new('Target', None)
        main_target.empty_display_size = 0.4
        collection.objects.link(main_target)
        create_fixture_id(main_target, fixture_id)
        create_gdtf_props(main_target, name)
        main_target['Geometry Type'] = 'Target'
        main_target['UUID'] = target_uid
        targetData[target_uid] = main_target

    for idx, obj in enumerate(moving_objects):
        center_object = check_center_object(obj)
        check_pan = obj.get('Mobile Axis') == 'Pan'
        check_tilt = obj.get('Mobile Axis') == 'Tilt'
        center_parent = obj.parent and check_center_object(obj.parent)
        check_parent = obj.parent and obj.parent.get('Mobile Axis') in {'Pan', 'Tilt'}
        check_master = check_parent and obj.parent.parent and obj.parent.parent.get('Mobile Axis') in {'Pan', 'Tilt'}
        if TARGETS:
            if not len(base.constraints) and (check_pan and not len(obj.children) or (not check_pan and not heads)):
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
                obj['Target ID'] = target_uid
            else:
                if obj.parent and len(obj.parent.children) > 1:
                    if not center_object or (center_object and not center_parent):
                        target_name = 'Target %s' % obj.name
                        obj_target = bpy.data.objects.new(target_name, None)
                        obj_target.empty_display_type = 'SINGLE_ARROW'
                        obj_target.empty_display_size = 0.2
                        obj_target.parent = main_target
                        create_fixture_id(obj_target, fixture_id)
                        create_gdtf_props(obj_target, name)
                        obj_target['Geometry Class'] = 'Target'
                        obj_target['Reference'] = obj.get('Original Name', obj.name)
                        collection.objects.link(obj_target)
                        if not center_object:
                            obj_target.location = (obj.location.x, obj.location.y, 0)
                        elif center_object and not center_parent:
                            obj_target.location = (obj.parent.location.x, obj.parent.location.y, 0)
                        lock_constraint.target = obj_target
        limit_constraint = obj.constraints.new('LIMIT_ROTATION')
        range_min = math.radians(min(rangeData.get(obj.get('Original Name'),(-270, 270))))
        if check_master:
            obj['Sub Axis'] = True
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
        obj['2D Symbol'] = "all"
        objectDict['2D Symbol'] = obj
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


def get_fixture_models(profile, name, fixture_id, uid, dmx_mode, BEAMS, TARGETS, CONES):
    collections = bpy.data.collections

    if profile == None:
        return None

    new_collection = collections.get(name)
    if new_collection and len(new_collection.objects) and new_collection.get('Fixture ID') == fixture_id:
        print("Getting collection from cache: %s" % name)
        return new_collection
    else:
        new_collection = build_collection(profile, name, fixture_id, uid, dmx_mode, BEAMS, TARGETS, CONES)
        return new_collection


def get_root_model(model_collection):
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        if obj.get('Use Root', False):
            return obj


def get_tilt(model_collection, channels):
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        for channel in channels:
            if 'Tilt' == channel.get('ID') and channel.get('Geometry') == obj.get('Original Name', 'None'):
                return obj


def get_emit_material(obj, color, name, index, prop):
    obj.hide_select = True
    obj.visible_shadow = False
    emit_color = obj.get('RGB')
    beamname ='ID%d_%s_%s' % (index, name, prop) if index >= 1 else '%s_%s' % (name, prop)
    if len(obj.data.materials):
        emit_material = obj.data.materials[0]
        emit_material['Fixture ID'] = index
        emit_material.name = beamname
    else:
        emit_material = bpy.data.materials.get(beamname)
    if emit_material is None or emit_material.get('Fixture ID') != index or emit_material.get('RGB') != emit_color:
        obj.data.materials.clear()
        emit_material = bpy.data.materials.new(beamname)
        obj.data.materials.append(emit_material)
        if emit_color:
            emit_material['RGB'] = emit_color
    obj.active_material = emit_material
    create_gdtf_props(emit_material, name)
    emit_material['Fixture ID'] = index
    emit_material['Geometry Type'] = 'Beam'
    emit_shader = PrincipledBSDFWrapper(emit_material, is_readonly=False, use_nodes=True)
    emit_shader.emission_strength = 1.0
    emit_shader.emission_color = color[:] if emit_color else emit_shader.base_color[:]



def fixture_build(context, filename, mscale, name, position, focus_point, fixture_id,
                  gelcolor, collect, fixture, TARGETS=True, BEAMS=True, CONES=False):

    viewlayer = context.view_layer
    object_data = bpy.data.objects
    data_collect = bpy.data.collections
    layer_collect = viewlayer.layer_collection
    gdtf_profile = pygdtf.FixtureType(filename)
    has_focus = has_iris = zoom_range = False
    fixture_name = create_fixture_name(name)
    uid = gdtf_profile.fixture_type_id
    gobo_material = random_gobo = None
    mode = FixtureMode(gdtf_profile)
    has_gobos = has_blend = False
    color_controller = set()
    channels = []
    wheels = []

    if fixture:
        mode = fixture.gdtf_mode
        color = convert_color(gelcolor)
        gelcolor = list(i for i in color[:3])
        fixture_name = create_fixture_name(fixture.gdtf_spec)


    def index_name(device):
        device_name = device
        if fixture_id > 0:
            device_name = 'ID%d %s' % (fixture_id, device.split('.')[0])
        return device_name

    # Remove Collection if same index
    index_collection = next((col for col in data_collect if col.get('Fixture ID') == fixture_id), False)
    if index_collection:
        for obj in index_collection.objects:
            if obj.get('Use Root'):
                position = obj.matrix_world.copy()
            if obj.get('Geometry Type') == 'Target':
                focus_point = obj.matrix_world.copy()
            object_data.remove(obj)
        data_collect.remove(index_collection)

    # Import Fixture Model Collection
    model_collection = get_fixture_models(gdtf_profile, fixture_name, fixture_id, uid, mode, BEAMS, TARGETS, CONES)
    if model_collection:
        model_collection.name = index_name(fixture_name)
        if collect and model_collection.name not in collect.children:
            collect.children.link(model_collection)

    # Build DMX channels cache
    if not any(mode == md.name for md in gdtf_profile.dmx_modes):
        mode = gdtf_profile.dmx_modes[0].name
    dmx_channels = collect_dmx_channels(gdtf_profile, mode)
    channels += [channel for break_channels in dmx_channels for channel in break_channels]
    virtual_channels = pygdtf.utils.get_virtual_channels(gdtf_profile, mode)

    for channel in channels:
        if 'Color1' in channel['ID']:
            color_controller.add(channel.get('Geometry'))
        elif 'Color' in channel['ID']:
            color_attribute = channel.get('ID')
            if color_attribute[-1] in {'R','G','B','C','M','Y'}:
                color_controller.add(channel.get('Geometry'))
        if 'Gobo' in channel['ID']:
            gobo_functions = channel.get('Functions')
            for function in gobo_functions:
                wheel_function = str(function.wheel)
                if wheel_function != 'None' and wheel_function not in wheels:
                    wheels.append(wheel_function)
        if 'Focus' in channel['ID']:
            has_focus = True
        if 'Frost' in channel['ID']:
            has_blend = True
        if 'Iris' in channel['ID']:
            has_iris = True
        if 'Pan' in channel['ID']:
            pan_functions = channel.get('Functions')
            pan_range = pan_functions[0].physical_from, pan_functions[0].physical_to
        if 'Tilt' in channel['ID']:
            tilt_functions = channel.get('Functions')
            tilt_range = tilt_functions[0].physical_from, tilt_functions[0].physical_to
        if 'Zoom' in channel['ID']:
            zoom_functions = channel.get('Functions')
            zoom_range = zoom_functions[0].physical_from, zoom_functions[0].physical_to

    for virtual in virtual_channels:
        if 'Color1' in virtual['id']:
            color_controller.add(channel.get('Geometry'))
        elif 'Color' in virtual['id']:
            color_attribute = virtual.get('id')
            if color_attribute[-1] in {'R','G','B','C','M','Y'}:
                color_controller.add(virtual.get('Geometry'))
        if 'Gobo' in virtual['id']:
            gobo_functions = virtual.get('Functions')
            for function in gobo_functions:
                wheel_function = str(function.wheel)
                if wheel_function != 'None' and wheel_function not in wheels:
                    wheels.append(wheel_function)
        if 'Focus' in virtual['id']:
            has_focus = True
        if 'Frost' in virtual['id']:
            has_blend = True
        if 'Iris' in virtual['id']:
            has_iris = True
        if 'Pan' in virtual['id']:
            pan_functions = virtual.get('functions')
            pan_range = pan_functions[0].physical_from, pan_functions[0].physical_to
        if 'Tilt' in virtual['id']:
            tilt_functions = virtual.get('functions')
            tilt_range = tilt_functions[0].physical_from, tilt_functions[0].physical_to
        if 'Zoom' in virtual['id']:
            zoom_functions = virtual.get('functions')
            zoom_range = zoom_functions[0].physical_from, zoom_functions[0].physical_to

    linkDict = {}
    start_gobo = None
    wheel_count = False
    base = get_root_model(model_collection)
    head = get_tilt(model_collection, channels)
    random_glow = [random.uniform(0.0, 1.0) for _ in range(3)]
    if len(wheels):
        has_gobos = True
        gobo_data = extract_gobos(gdtf_profile, fixture_id, fixture_name, wheels)
        wheel_count = len(gobo_data.keys())
        check_wheels = wheel_count > 1
        start_gobo = gobo_data.get(wheels[0])
        gobo_count = start_gobo.get('Count')
        wheel_name = 'Gobo 1' if check_wheels else 'Gobo'
        random_gobo = random.randint(0, gobo_count)
    elif has_iris:
        check_wheels = False
        wheel_name = 'Iris'

    if model_collection:
        root_object = None
        zoom_angle = False
        collection_name = model_collection.get('Fixture Name')
        if collect is None:
            if model_collection.name not in layer_collect.collection.children:
                layer_collect.collection.children.link(model_collection)
            active_layer = layer_collect.children.get(model_collection.name)
        print("creating fixture... %s" % model_collection.name)
        for obj in model_collection.objects:
            linkDict[obj.name] = obj
            viewlayer.objects.active = obj
            if TARGETS and len(obj.constraints):
                target = obj.get('Target ID')
                locked = obj.constraints.get('Locked Track')
                if locked is not None:
                    for child in obj.children:
                        locked_child = child.constraints.get('Locked Track')
                        if locked_child and locked_child.target is None:
                            locked_child.target = obj.constraints[0].target
                    if target:
                        locked.target = targetData.get(target)
            if obj.type == 'LIGHT':
                obj.hide_select = True
                zoom_angle = obj.get('Focus')
                obj.matrix_world = obj.matrix_world @ obj.parent.matrix_local.inverted()
                obj['UUID'] = uid
            if obj.get('Use Root'):
                root_object = obj
                if has_blend:
                    create_factor_property(obj, 'Frost Edge')
                if has_focus:
                    create_factor_property(obj, 'Focus Factor', 0.5)
                if has_gobos:
                    obj['%s Select' % wheel_name] = random_gobo
                    create_gobo_property(obj, gobo_count, wheel_name)
                create_dimmer_property(obj, 'Intensity')
                obj['Target'] = TARGETS
                obj.id_properties_ensure()
                target_property = obj.id_properties_ui('Target')
                target_property.update(default=TARGETS)
                ob_name = fixture_name if fixture is None else name
                obj.matrix_world = position @ obj.matrix_world.copy()
                obj.name = index_name(ob_name)
                obj['UUID'] = uid
            elif obj.get('Geometry Type') == 'Gobo':
                obj.select_set(False)
                obj.scale = [1.0] * 3
                obj.hide_select = True
                wheelname = 'ID%d_%s_Wheel' % (fixture_id, fixture_name) if fixture_id >=1 else '%s_Wheel' % fixture_name
                if len(obj.data.materials):
                    wheel_material = obj.data.materials[0]
                    wheel_material.name = wheelname
                else:
                    wheel_material = bpy.data.materials.get(wheelname)
                if wheel_material is None or wheel_material.get('Fixture ID') != fixture_id:
                    wheel_material = bpy.data.materials.new(wheelname)
                    obj.data.materials.append(wheel_material)
                obj.active_material = wheel_material
                create_gdtf_props(wheel_material, fixture_name)
                wheel_material['Geometry Type'] = 'Gobo'
                wheel_material['Fixture ID'] = fixture_id
                wheel_material['UUID'] = uid
                wheel_material.blend_method = 'BLEND'
            elif obj.get('Geometry Type') == 'Beam' and obj.type == 'MESH':
                get_emit_material(obj, gelcolor, fixture_name, fixture_id, 'Beam')
            elif obj.get('Geometry Type') == 'Glow' and obj.type == 'MESH':
                get_emit_material(obj, gelcolor, fixture_name, fixture_id, 'Glow')
            elif obj.get('Geometry Type') == 'Target':
                obj.name = index_name(obj.name)
                obj.matrix_world = focus_point
            elif obj.get('2D Symbol', None) == "all":
                obj.name = index_name('2D Symbol')
                obj.hide_viewport = True
                obj.hide_render = True
                obj.hide_set(True)

        for obj in model_collection.objects:
            check_color = obj.get('RGB')
            rgb_beam = root_object.get('RGB Beam')
            for child in obj.children:
                if child.name in linkDict:
                    linkDict[child.name].parent = obj
                    if check_color:
                        linkDict[child.name]['RGB'] = True
                child.name = index_name(child.name)
            if obj.type == 'LIGHT':
                zoom_angle = obj.get('Focus')
                nodes = obj.data.node_tree.nodes
                links = obj.data.node_tree.links
                gamma_node = nodes.get('Gamma')
                emit_node = nodes.get('Fixture')
                light_mix = nodes.get('Light Mix')
                light_path = nodes.get('Light Path')
                focus_node = nodes.get('Focus Factor')
                light_output = nodes.get('Light Output')
                lightfalloff = nodes.get('Light Falloff')
                light_uv = nodes.get('Light Orientation')
                light_temperature = obj.get('Temperature')
                lightcontrast = nodes.get('Light Contrast')
                color_temp = nodes.get('Color Temperature')
                create_dimmer_driver(obj.data, root_object, obj)
                if check_color:
                    if rgb_beam is None:
                        create_color_property(root_object, gelcolor, 'RGB Beam')
                    create_color_driver(obj.data, root_object, 'RGB Beam')
                if has_blend:
                    create_factor_driver(obj, root_object)
                if has_focus:
                    create_focus_driver(obj, root_object)
                if root_object and light_temperature:
                    create_ctc_property(root_object, light_temperature, 'Light CTC')
                    create_ctc_driver(obj, root_object)
                if zoom_range and zoom_angle:
                    check_zoom = root_object.get('Focus Zoom', False)
                    if not check_zoom:
                        create_range_property(root_object, zoom_angle, 'Focus Zoom', zoom_range)
                    create_zoom_driver(obj.data, root_object, 'Focus Zoom')
                elif zoom_angle:
                    create_zoom_driver(obj.data, root_object, 'Focus')
                if has_iris:
                    obj.data.use_soft_falloff = False
                    iris_node = nodes.new('ShaderNodeTexImage')
                    iris_out = iris_node
                    if has_gobos:
                        iris_mix = nodes.new('ShaderNodeMixRGB')
                        links.new(iris_node.outputs[0], iris_mix.inputs[2])
                        links.new(light_path.outputs[7], iris_mix.inputs[0])
                        iris_mix.label = iris_mix.name = 'Iris Mix'
                        iris_mix.blend_type = 'DARKEN'
                        iris_mix.location = (-500, 340)
                        iris_out = iris_mix
                    else:
                        obj.location[2] += 0.01
                    links.new(light_path.outputs[9], lightcontrast.inputs[1])
                    create_iris_nodes(obj.data, root_object, iris_node, light_uv)
                    emit_node.location = (300, 300)
                    light_mix.location = (100, 340)
                    color_temp.location = (-100, 200)
                    focus_node.location = (-500, 150)
                    gamma_node.location = (-300, 340)
                    light_output.location = (500, 300)
                    lightfalloff.location = (-300, 220)
                    lightcontrast.location = (-100, 360)
                if has_gobos and start_gobo is not None:
                    obj.data.shadow_buffer_clip_start = 0.001
                    obj.location[2] += 0.01
                    wheel_node = nodes.new('ShaderNodeTexImage')
                    wheel_rota = nodes.new('ShaderNodeVectorRotate')
                    wheel_node.image = start_gobo
                    wheel_node.extension = 'EXTEND'
                    wheel_node.label = wheel_node.name = wheel_name
                    wheel_rota.label = wheel_rota.name = '%s Rotate' % wheel_name
                    wheel_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                    wheel_node.location = (-980, 440)
                    wheel_rota.location = (-1160, 310)
                    emit_node.inputs[0].default_value[:3] = gelcolor[:]
                    create_gobo_driver(wheel_node, wheel_rota, root_object, gobo_count)
                    links.new(light_uv.outputs[5], wheel_rota.inputs[0])
                    links.new(wheel_rota.outputs[0], wheel_node.inputs[0])
                    links.new(wheel_node.outputs[0], gamma_node.inputs[0])
                    pre_node = wheel_node
                    if check_wheels:
                        for idx, wheel in enumerate(list(gobo_data.keys())[1:], 2):
                            start = gobo_data.get(wheel)
                            gobo_name = 'Gobo %d' % idx
                            align_x = int((idx - 2) * 280)
                            align_y = int((idx - 2) * -160)
                            slot_count = start.get('Count')
                            gobo_mix = nodes.new('ShaderNodeMixRGB')
                            gobo_node = nodes.new('ShaderNodeTexImage')
                            rota_node = nodes.new('ShaderNodeVectorRotate')
                            root_object['%s Select' % gobo_name] = 0
                            gobo_node.image = start
                            gobo_mix.blend_type = 'DARKEN'
                            gobo_node.extension = 'EXTEND'
                            gobo_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                            mix_name = 'Gobo %d Mix' % (idx - 1) if idx > 2 else 'Gobo Mix'
                            gobo_mix.label = gobo_mix.name = mix_name
                            rota_node.label = rota_node.name = '%s Rotate' % gobo_name
                            gobo_node.label = gobo_node.name = gobo_name
                            create_gobo_property(root_object, slot_count, gobo_name)
                            create_gobo_driver(gobo_node, rota_node, root_object, slot_count)
                            gobo_mix.location = (-700 + align_x, 340)
                            gobo_node.location = (-980 + align_x, 40)
                            rota_node.location = (-1160, 40 + align_y)
                            emit_node.location = (300 + align_x, 320) if has_iris else (100 + align_x, 320)
                            light_mix.location = (100 + align_x, 360) if has_iris else (-100 + align_x, 360)
                            color_temp.location = (-100 + align_x, 220) if has_iris else (-300 + align_x, 220)
                            gamma_node.location = (-300 + align_x, 340) if has_iris else (-500 + align_x, 340)
                            focus_node.location = (-500 + align_x, 150) if has_iris else (-300 + align_x, 150)
                            light_output.location = (500 + align_x, 300) if has_iris else (300 + align_x, 300)
                            lightfalloff.location = (-300 + align_x, 220) if has_iris else (-500 + align_x, 220)
                            lightcontrast.location = (-100 + align_x, 360) if has_iris else (-300 + align_x, 360)
                            if has_iris:
                                iris_mix.location = (-500 + align_x, 340)
                                iris_node.location = (-700 + align_x, 150)
                            gobo_mix.inputs[1].default_value[:3] = [1.0] * 3
                            gobo_mix.inputs[2].default_value[:3] = [1.0] * 3
                            links.new(pre_node.outputs[0], gobo_mix.inputs[1])
                            links.new(gobo_node.outputs[0], gobo_mix.inputs[2])
                            links.new(light_uv.outputs[5], rota_node.inputs[0])
                            links.new(light_path.outputs[7], gobo_mix.inputs[0])
                            links.new(rota_node.outputs[0], gobo_node.inputs[0])
                            links.new(gobo_mix.outputs[0], gamma_node.inputs[0])
                            pre_node = gobo_mix
                else:
                    gradient_node = nodes.new('ShaderNodeTexGradient')
                    gradient_node.label = gradient_node.name = 'Gradient'
                    gradient_node.gradient_type = 'RADIAL'
                    gradient_node.location = (-700, 300)
                    links.new(light_uv.outputs[5], gradient_node.inputs[0])
                    links.new(gradient_node.outputs[0], gamma_node.inputs[0])
                    if obj.parent and obj.parent.parent and obj.parent.parent.dimensions.z < 0.05:
                        obj.location[2] += -0.02
                if has_iris:
                    links.new(iris_out.outputs[0], gamma_node.inputs[0])
                    if has_gobos:
                        links.new(pre_node.outputs[0], iris_mix.inputs[1])
            elif obj.type == 'MESH' and len(obj.data.materials):
                if obj.get('Geometry Type') == 'Beam':
                    emit_color = obj.get('RGB', False)
                    beam_material = obj.data.materials[0]
                    beam_material.use_nodes = True
                    principled_node = beam_material.node_tree.nodes.get('Principled BSDF')
                    if emit_color:
                        if rgb_beam is None:
                            create_color_property(root_object, gelcolor, 'RGB Beam')
                        create_color_driver(principled_node.inputs['Emission Color'], root_object, 'RGB Beam')
                    create_dimmer_driver(principled_node.inputs['Emission Strength'], root_object, obj)
                elif obj.get('Geometry Type') == 'Glow':
                    glow_color = obj.get('RGB', False)
                    glow_material = obj.data.materials[0]
                    glow_material.use_nodes = True
                    principled_node = glow_material.node_tree.nodes.get('Principled BSDF')
                    if glow_color:
                        create_color_property(root_object, random_glow, 'RGB Glow')
                        create_color_driver(principled_node.inputs['Emission Color'], root_object, 'RGB Glow')
                    create_dimmer_driver(principled_node.inputs['Emission Strength'], root_object, obj)   
                elif obj.get('Geometry Type') == 'Gobo':
                    gobo_material = obj.data.materials[0]
                    if zoom_range and zoom_angle:
                        check_zoom = root_object.get('Focus Zoom', False) 
                        if not check_zoom:
                            create_range_property(root_object, zoom_angle, 'Focus Zoom', zoom_range)
                        create_range_property(obj, zoom_angle, 'Focus', zoom_range)
                        create_zoom_driver(obj, root_object, 'Focus Zoom')
                    if not gobo_material.use_nodes:
                        gobo_material.use_nodes = True
                        gobo_nodes = gobo_material.node_tree.nodes
                        gobo_links = gobo_material.node_tree.links
                        material_node = gobo_nodes.get('Material Output')
                        principled_bsdf = gobo_nodes.get('Principled BSDF')
                        gobo_nodes.remove(principled_bsdf)
                        gobo_cord = gobo_nodes.new('ShaderNodeTexCoord')
                        gobo_cord.label = gobo_cord.name = 'Gobo Coordinate'
                        opacity_node = gobo_nodes.new('ShaderNodeBsdfTransparent')
                        opacity_node.label = opacity_node.name = 'Wheel Shader'
                        previous_node = None
                        if has_gobos:
                            wheel_node = gobo_nodes.new('ShaderNodeTexImage')
                            wheel_rota = gobo_nodes.new('ShaderNodeVectorRotate')
                            wheel_rota.label = wheel_rota.name = '%s Rotate' % wheel_name
                            wheel_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                            wheel_node.label = wheel_node.name = wheel_name
                            wheel_node.location = (-620, 460)
                            wheel_rota.location = (-840, 310)
                            wheel_node.extension = 'EXTEND'
                            wheel_node.image = start_gobo
                            gobo_links.new(gobo_cord.outputs[0], wheel_rota.inputs[0])
                            gobo_links.new(wheel_rota.outputs[0], wheel_node.inputs[0])
                            gobo_links.new(wheel_node.outputs[0], opacity_node.inputs[0])
                            create_gobo_driver(wheel_node, wheel_rota, root_object, gobo_count)
                            previous_node = wheel_node
                        gobo_cord.location = (-1040, 90)
                        opacity_node.location = (100, 300)
                        gobo_links.new(opacity_node.outputs[0], material_node.inputs[0])
                        if check_wheels:
                            for idx, wheel in enumerate(list(gobo_data.keys())[1:], 2):
                                start = gobo_data.get(wheel)
                                gobo_name = 'Gobo %d' % idx
                                align_x = int((idx - 2) * 280)
                                align_y = int((idx - 2) * -150)
                                slot_count = start.get('Count')
                                gobo_mix = gobo_nodes.new('ShaderNodeMixRGB')
                                gobo_node = gobo_nodes.new('ShaderNodeTexImage')
                                rota_node = gobo_nodes.new('ShaderNodeVectorRotate')
                                light_fall = gobo_nodes.get('Light Falloff', False)
                                if not light_fall:
                                    light_path = gobo_nodes.new('ShaderNodeLightPath')
                                    light_fall = gobo_nodes.new('ShaderNodeLightFalloff')
                                    light_fall.location = (-840, 460)
                                    light_path.location = (-1040, 460)
                                    gobo_links.new(light_path.outputs[1], light_fall.inputs[0])
                                    gobo_links.new(light_path.outputs[8], light_fall.inputs[1])
                                gobo_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                                root_object['%s Select' % gobo_name] = 0
                                gobo_mix.blend_type = 'MULTIPLY'
                                gobo_node.extension = 'EXTEND'
                                gobo_node.image = start
                                mix_name = 'Gobo %d Mix' % (idx - 1) if idx > 2 else 'Gobo Mix'
                                gobo_mix.label = gobo_mix.name = mix_name
                                rota_node.label = rota_node.name = '%s Rotate' % gobo_name
                                gobo_node.label = gobo_node.name = gobo_name
                                gobo_node.location = (-620 + align_x, 40)
                                rota_node.location = (-840, 40 + align_y)
                                opacity_node.location = (100 + align_x, 300)
                                material_node.location = (300 + align_x, 300)
                                gobo_mix.location = (-300 + align_x, 340) if has_iris else (-100 + align_x, 340)
                                gobo_mix.inputs[1].default_value[:3] = [1.0] * 3
                                gobo_mix.inputs[2].default_value[:3] = gelcolor[:]
                                create_gobo_driver(gobo_node, rota_node, root_object, slot_count)
                                gobo_links.new(light_fall.outputs[0], gobo_mix.inputs[0])
                                gobo_links.new(previous_node.outputs[0], gobo_mix.inputs[1])
                                gobo_links.new(gobo_mix.outputs[0], opacity_node.inputs[0])
                                gobo_links.new(gobo_cord.outputs[0], rota_node.inputs[0])
                                gobo_links.new(rota_node.outputs[0], gobo_node.inputs[0])
                                gobo_links.new(gobo_node.outputs[0], gobo_mix.inputs[2])
                                previous_node = gobo_mix
                        if has_iris:
                            light_fall = gobo_nodes.get('Light Falloff', False)
                            iris_node = gobo_nodes.new('ShaderNodeTexImage')
                            if not light_fall:
                                light_path = gobo_nodes.new('ShaderNodeLightPath')
                                light_fall = gobo_nodes.new('ShaderNodeLightFalloff')
                                light_fall.location = (-840, 460)
                                light_path.location = (-1040, 460)
                                gobo_links.new(light_path.outputs[1], light_fall.inputs[0])
                                gobo_links.new(light_path.outputs[8], light_fall.inputs[1])
                            if previous_node is not None:
                                iris_mix = gobo_nodes.new('ShaderNodeMixRGB')
                                iris_mix.label = iris_mix.name = 'Iris Mix'
                                iris_mix.blend_type = 'MULTIPLY'
                                iris_mix.location = (-100 + max(wheel_count - 2, 0) * 200, 340)
                                gobo_links.new(iris_node.outputs[0], iris_mix.inputs[2])
                                gobo_links.new(previous_node.outputs[0], iris_mix.inputs[1])
                                gobo_links.new(light_fall.outputs[0], iris_mix.inputs[0])
                            else:
                                iris_mix = iris_node
                            create_iris_nodes(gobo_material, root_object, iris_node, gobo_cord)
                            if check_wheels:
                                iris_mix.location = (-100 + max(wheel_count - 2, 0) * 200, 340)
                                iris_node.location = (-300 + max(wheel_count - 2, 0) * 200, 150)
                                opacity_node.location = (100 + max(wheel_count - 2, 0) * 200, 320)
                                material_node.location = (300 + max(wheel_count - 2, 0) * 200, 300)
                            gobo_links.new(iris_mix.outputs[0], opacity_node.inputs[0])
                else:
                    for mtl in obj.data.materials:
                        obj_name = obj.get('Fixture Name', obj.name)
                        split_name = mtl.name.split('.')[0]
                        mtl_name = split_name.split('_')[-1]
                        mtl.name = '%s_%s' % (obj_name, mtl_name)
            if obj.get('Use Root'):
                for parents in obj.children_recursive:
                    if len(parents.children) > 1:
                        for idx, childs in enumerate(parents.children, 1):
                            if len(childs.children) > 1:
                                parents.visible_shadow = False
                                for i, child in enumerate(childs.children, 1):
                                    child_name = child.name.split('.')[0]
                                    child.name = '%s %d' % (child_name, i)
                            else:
                                for child in childs.children_recursive:
                                    child_name = child.name.split('.')[0]
                                    child.name = '%s %d' % (child_name, idx)
            if obj.get('Geometry Type') == 'Axis':
                mobile_axis = obj.get('Mobile Axis')
                check_sub_axis = obj.get('Sub Axis')
                if root_object and mobile_axis in {'Pan', 'Tilt'}:
                    if check_sub_axis:
                        create_trackball_property(root_object, 'Position', TARGETS)
                        create_trackball_driver(obj, root_object, 'Position')
                    else:
                        create_trackball_property(root_object, 'Movement', TARGETS)
                        create_trackball_driver(obj, root_object, 'Movement')
                obj.hide_select = True
                obj['UUID'] = uid

        for obj in layer_collect.collection.all_objects:
            if obj.get('UUID') == uid or (obj.get('Geometry Type') == 'Target' and obj.get('Fixture Name') == collection_name):
                obj.select_set(False) if obj.hide_select else obj.select_set(True)

    linkDict.clear()


def load_gdtf(context, filename, mscale, name, position, focus_point, fixture_id,
              gelcolor, collect, fixture, TARGETS=True, BEAMS=True, CONES=False):

    rangeData.clear()
    targetData.clear()
    channelData.clear()

    context.scene.cycles.preview_pause = True
    fixture_build(context, filename, mscale, name, position, focus_point,
                  fixture_id, gelcolor, collect, fixture, TARGETS, BEAMS, CONES)

    rangeData.clear()
    targetData.clear()
    channelData.clear()
    context.scene.cycles.preview_pause = False


def load_prepare(context, filename, global_matrix, collect, align_objects, align_axis, scale_objects,
                 fixture_index, fixture_count, gel_color, device_position, TARGETS, BEAMS, CONES):

    name = Path(filename).stem
    mscale = mathutils.Matrix.Scale(scale_objects, 4)

    if global_matrix is not None:
        mscale = global_matrix @ mscale

    for idx in range(fixture_index, fixture_index + fixture_count):
        count = idx - fixture_index
        distribution = count * align_objects
        align = 0.5 * (fixture_count * align_objects) - (0.5 * align_objects)
        spread = (device_position[0] + (distribution - align), device_position[1], device_position[2])
        if align_axis == 'Y':
            spread = (device_position[0], device_position[1] + (distribution - align), device_position[2])
        elif align_axis == 'Z':
            spread = (device_position[0], device_position[1], device_position[2] + (distribution - align))
        position = mathutils.Matrix.Translation(spread)
        focus_point = mathutils.Matrix.Translation((spread[0], spread[1], 0))
        load_gdtf(context, filename, mscale, name, position, focus_point,
                  idx, gel_color, collect, None, TARGETS, BEAMS, CONES)


def load(operator, context, files=[], directory="", filepath="", fixture_index=0, fixture_count=1,
         align_axis={'X'}, align_objects=1.0, scale_objects=1.0, gel_color=[1.0, 1.0, 1.0], device_position=None,
         use_collection=False, use_targets=True, use_beams=True, use_show_cone=False, global_matrix=None):

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
                     TARGETS=use_targets, BEAMS=use_beams, CONES=use_show_cone)

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
