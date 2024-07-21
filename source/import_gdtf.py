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
import hashlib
import pathlib
import tempfile
import mathutils
import traceback
from . import pygdtf
from types import SimpleNamespace
from .io_scene_3ds.import_3ds import load_3ds


class ProfileGDTF:

    @staticmethod
    def get_temp_path():
        TEMP_PATH = tempfile.TemporaryDirectory()
        return TEMP_PATH.name

    @staticmethod
    def get_profile_list(manufacturer):
        profiles = []
        for file in os.listdir(ProfileGDTF.get_temp_path()):
            # Parse info from file name: Company@Model.gdtf
            if "@" not in file:
                file = os.path.join(ProfileGDTF.get_temp_path(), file)
                fixture_type = pygdtf.FixtureType(file)
                info = [f"{fixture_type.manufacturer}", f"{fixture_type.long_name}", ""]
            else:
                info = file.split("@")
            if info[0] == manufacturer:
                # Remove ".gdtf" from the end of the string
                if info[-1][-5:].lower() == ".gdtf":
                    info[-1] = info[-1][:-5]
                # Add to list (identifier, short name, full name)
                profiles.append((file, info[1], (info[2] if len(info) > 2 else "")))

        return tuple(profiles)

    @staticmethod
    def get_modes(profile):
        """Returns an array, keys are mode names, value is channel count"""
        gdtf_profile = ProfileGDTF.load_profile(profile)
        modes = {}
        for mode in gdtf_profile.dmx_modes:
            dmx_channels = pygdtf.utils.get_dmx_channels(gdtf_profile, mode.name)
            dmx_channels_flattened = [channel for break_channels in dmx_channels for channel in break_channels]
            modes[mode.name] = len(dmx_channels_flattened)
        return modes

    @staticmethod
    def load_profile(filename):
        path = os.path.join(ProfileGDTF.get_temp_path(), filename)
        profile = pygdtf.FixtureType(path)
        return profile

    @staticmethod
    def load_blender_primitive(model):
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
        obj.scale = (model.length, model.width, model.height)
        return obj

    @staticmethod
    def load_gdtf_primitive(model):
        primitive = str(model.primitive_type)
        path = os.path.join(ProfileGDTF.get_temp_path(), f"{primitive}.glb")
        bpy.ops.import_scene.gltf(filepath=path)
        obj = bpy.context.view_layer.objects.selected[0]
        obj.users_collection[0].objects.unlink(obj)
        obj.rotation_euler = mathutils.Euler((0, 0, 0), "XYZ")
        obj.scale = (model.length / obj.dimensions.x, model.width / obj.dimensions.y, model.height / obj.dimensions.z)
        return obj

    @staticmethod
    def extract_gobos(profile):
        """now unused as we need sequences for keyframe animating"""
        gobos = []
        current_path = os.path.dirname(os.path.realpath(__file__))
        extract_to_folder_path = os.path.join(current_path, "models", profile.fixture_type_id)
        for image_name in profile._package.namelist():
            if image_name.startswith("wheels"):
                short_name = image_name.replace("wheels/", "", 1)
                if short_name in bpy.data.images:
                    image = bpy.data.images[short_name]
                else:
                    profile._package.extract(image_name, extract_to_folder_path)
                    image_path = os.path.join(extract_to_folder_path, image_name)
                    image = bpy.data.images.load(image_path)
                image["content_type"] = "image"
                # TODO: we could add gobo names from Wheels
                gobo = {"name": image_name, "image": image}
                gobos.append(gobo)

        return gobos

    @staticmethod
    def get_wheel_slot_colors(profile):
        colors = []
        for wheel in profile.wheels:
            for slot in wheel.wheel_slots:
                try:
                    color = xyY2rgbaa(slot.color)
                except:
                    color = None
                if color is not None and color not in colors:
                    colors.append(color)
        return colors

    @staticmethod
    def extract_gobos_as_sequence(profile):
        current_path = os.path.dirname(os.path.realpath(__file__))
        gdtf_path = os.path.join(current_path, "models", profile.fixture_type_id)
        images_path = os.path.join(gdtf_path, "wheels")
        sequence_path = os.path.join(gdtf_path, "sequence")

        # TODO: do the extracting and renaming in one step by renaming filename in zipfile infolist
        for image_name in profile._package.namelist():
            if image_name.startswith("wheels"):
                profile._package.extract(image_name, gdtf_path)

        if not os.path.isdir(sequence_path):
            os.makedirs(sequence_path)
        first = ""
        count = 0
        for idx, image in enumerate(pathlib.Path(images_path).rglob("*"), start=1):
            destination = pathlib.Path(sequence_path, f"image_{idx:04}{image.suffix}")
            if idx == 1:
                first = str(destination.resolve())
            if idx == 256:  # more gobos then values on a channel, must stop
                break
            destination.write_bytes(image.read_bytes())
            count = idx
        if first:
            sequence = bpy.data.images.load(first)
        else:
            return None

        sequence["count"] = count
        return sequence

    @staticmethod
    def load_2d(profile):
        current_path = os.path.dirname(os.path.realpath(__file__))
        extract_to_folder_path = os.path.join(current_path, "models", profile.fixture_type_id)
        filename = f"{profile.thumbnail}.svg"
        obj = None
        if filename in profile._package.namelist():
            profile._package.extract(filename, extract_to_folder_path)
        else:
            # default 2D
            extract_to_folder_path = os.path.join(current_path, "primitives")
            filename = "thumbnail.svg"

        bpy.ops.wm.gpencil_import_svg(filepath="", directory=extract_to_folder_path, files=[{"name": filename}], scale=1)
        if len(bpy.context.view_layer.objects.selected):
            obj = bpy.context.view_layer.objects.selected[0]
        if obj is not None:
            obj.name = "2D symbol"
            obj.users_collection[0].objects.unlink(obj)
            obj.rotation_euler[0] = -90 * (math.pi / 180)
        return obj

    @staticmethod
    def load_model(profile, model):
        current_path = os.path.dirname(os.path.realpath(__file__))
        extract_to_folder_path = os.path.join(current_path, "models", profile.fixture_type_id)

        if model.file.extension.lower() == "3ds":
            inside_zip_path = f"models/3ds/{model.file.name}.{model.file.extension}"
            profile._package.extract(inside_zip_path, extract_to_folder_path)
            file_name = os.path.join(extract_to_folder_path, inside_zip_path)
            try:
                load_3ds(file_name, bpy.context, FILTER={'MESH'}, KEYFRAME=False, APPLY_MATRIX=False)
                for ob in bpy.context.selected_objects:
                    ob.data.transform(mathutils.Matrix.Scale(0.001, 4))
            except Exception as e:
                bpy.ops.mesh.primitive_cube_add(size=0.1)
        else:
            inside_zip_path = f"models/gltf/{model.file.name}.{model.file.extension}"
            profile._package.extract(inside_zip_path, extract_to_folder_path)
            file_name = os.path.join(extract_to_folder_path, inside_zip_path)
            bpy.ops.import_scene.gltf(filepath=file_name)

        objs = list(bpy.context.selected_objects)

        # if the model is made up of multiple parts we must join them
        obj = ProfileGDTF.join_parts_apply_transforms(objs)

        # we should not set rotation to 0, models might be pre-rotated
        # obj.rotation_euler = mathutils.Euler((0, 0, 0), 'XYZ')

        dim_x = obj.dimensions.x or 1
        dim_y = obj.dimensions.y or 1
        dim_z = obj.dimensions.z or 1

        obj.scale = (obj.scale.x * model.length / dim_x, obj.scale.y * model.width / dim_y, obj.scale.z * model.height / dim_z)
        return obj

    @staticmethod
    def join_parts_apply_transforms(objs):

        join = 0
        single = None
        for ob in objs:
            mb = ob.matrix_basis  # apply some transforms
            if ob.type == "MESH" and ob.data.vertices.items():
                ob.select_set(True)  # objects for merging must be selected
                join += 1
                bpy.context.view_layer.objects.active = ob
                single = ob
                if hasattr(ob.data, "transform"):  # glb files
                    ob.data.transform(mb)
            ob.matrix_basis.identity()

        if join > 0:
            bpy.ops.object.join()  # join them together
            objs = list(bpy.context.view_layer.objects.selected)

        for obj in objs:
            obj.users_collection[0].objects.unlink(obj)

        if join == 1:
            objs = [single]  # if there was only a single object for merging

        for ob in objs:
            if ob.type == "MESH":
                obj = ob
                break

        return obj

    @staticmethod
    def build_collection(profile, mode, display_beams, add_target):
        # Create model collection
        collection = bpy.data.collections.new(ProfileGDTF.get_name(profile, mode, display_beams, add_target))
        objs = {}
        # Get root geometry reference from the selected DMX Mode
        dmx_mode = pygdtf.utils.get_dmx_mode_by_name(profile, mode)

        # Handle if dmx mode doesn't exist (maybe this is MVR import and GDTF files were replaced)
        # use mode[0] as default
        if dmx_mode is None:
            dmx_mode = profile.dmx_modes[0]
            mode = dmx_mode.name

        root_geometry = pygdtf.utils.get_geometry_by_name(profile, dmx_mode.geometry)
        has_gobos = False

        dmx_channels = pygdtf.utils.get_dmx_channels(profile, mode)
        virtual_channels = pygdtf.utils.get_virtual_channels(profile, mode)
        # Merge all DMX breaks together
        dmx_channels_flattened = [channel for break_channels in dmx_channels for channel in break_channels]
        # dmx_channels_flattened contain list of channel with id, geometry

        for ch in dmx_channels_flattened:
            if "Gobo" in ch["id"]:
                has_gobos = True

        def load_geometries(geometry):
            """Load 3d models, primitives and shapes"""
            DMX_Log.log.info(f"loading geometry {geometry.name}")

            if isinstance(geometry, pygdtf.GeometryReference):
                reference = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
                geometry.model = reference.model

                if hasattr(reference, "geometries"):
                    for sub_geometry in reference.geometries:
                        setattr(sub_geometry, "reference_root", str(geometry.name))
                        load_geometries(sub_geometry)

            if geometry.model is None:
                # Empty geometries are allowed as of GDTF 1.2
                # If the size is 0, Blender will discard it, set it to something tiny
                model = pygdtf.Model(name=f"{geometry}", length=0.0001, width=0.0001, height=0.0001, primitive_type="Cube")
                geometry.model = ""
            else:
                # Deepcopy the model because GeometryReference will modify the name
                # Perhaps this could be done conditionally
                # Also, we could maybe make a copy of the beam instance, if Blender supports it...
                model = copy.deepcopy(pygdtf.utils.get_model_by_name(profile, geometry.model))

            if isinstance(geometry, pygdtf.GeometryReference):
                model.name = f"{geometry}"

            obj = None
            primitive = str(model.primitive_type)
            # Normalize 1.1 PrimitiveTypes
            # (From GDTF v1.1 on, the 1_1 was added to the end of primitive names, we just ignore them and use the same primitives)
            if primitive[-3:] == "1_1":
                primitive = primitive[:-3]
                model.primitive_type = pygdtf.PrimitiveType(primitive)

            # 'Undefined' of 'File': load from file
            # Prefer File first, as some GDTFs have both File and PrimitiveType
            if (str(model.primitive_type) == "Undefined") or (model.file is not None and model.file.name != "" and (str(model.primitive_type) != "Pigtail")):
                try:
                    obj = ProfileGDTF.load_model(profile, model)
                except Exception as e:
                    DMX_Log.log.error(f"Error importing 3D model: {e}")
                    DMX_Log.log.exception(e)
                    model.primitive_type = "Cube"
                    obj = ProfileGDTF.load_blender_primitive(model)
            # BlenderDMX primitives
            elif str(model.primitive_type) in ["Base", "Conventional", "Head", "Yoke"]:
                obj = ProfileGDTF.load_gdtf_primitive(model)
            # Blender primitives
            else:
                obj = ProfileGDTF.load_blender_primitive(model)

            # If object was created
            if obj is not None:
                if sanitize_obj_name(geometry) == sanitize_obj_name(root_geometry):
                    obj["geometry_root"] = True
                    obj.hide_select = False
                else:
                    obj.hide_select = True
                obj.name = sanitize_obj_name(geometry)
                obj["geometry_type"] = get_geometry_type_as_string(geometry)
                obj["original_name"] = geometry.name
                if isinstance(geometry, pygdtf.GeometryReference):
                    obj["referenced_geometry"] = str(geometry.geometry)
                if str(model.primitive_type) == "Pigtail":
                    # This is a bit ugly because of PrimitiveType (in model) and not Geometry type (in geometry)
                    obj["geometry_type"] = "pigtail"
                objs[sanitize_obj_name(geometry)] = obj

                # Apply transforms to ensure that models are correctly rendered
                # even if their transformations have not been applied prior to saving
                # without this, MVR fixtures are not loading correctly

                mb = obj.matrix_basis
                if hasattr(obj.data, "transform"):
                    obj.data.transform(mb)
                for c in obj.children:
                    c.matrix_local = mb @ c.matrix_local
                obj.matrix_basis.identity()

            if hasattr(geometry, "geometries"):
                for sub_geometry in geometry.geometries:
                    load_geometries(sub_geometry)

        def get_geometry_type_as_string(geometry):
            # From these, we end up using "beam" and "pigtail".
            # The Pigtail is a special primitive type and we don't have access to
            # get to know this here
            # Even axis is not needed, as we rotate the geometry based on attributes during controlling

            if isinstance(geometry, pygdtf.GeometryMediaServerCamera):
                return "camera"
            if isinstance(geometry, pygdtf.GeometryBeam):
                return "beam"
            if isinstance(geometry, pygdtf.GeometryLaser):
                return "laser"
            if isinstance(geometry, pygdtf.GeometryAxis):
                return "axis"
            if isinstance(geometry, pygdtf.GeometryReference):
                geometry = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
                return get_geometry_type_as_string(geometry)
            return "normal"

        def create_camera(geometry):
            if not sanitize_obj_name(geometry) in objs:
                return
            obj_child = objs[sanitize_obj_name(geometry)]
            camera_data = bpy.data.cameras.new(name=f"{obj_child.name}")
            camera_object = bpy.data.objects.new("MediaCamera", camera_data)
            camera_object.hide_select = True
            camera_object.parent = obj_child
            camera_object.matrix_parent_inverse = obj_child.matrix_world.inverted()
            camera_object.rotation_euler[0] += math.radians(90)  # The media server camera-view points into the positive Y-direction (and Z-up).
            collection.objects.link(camera_object)

        def create_beam(geometry):
            if sanitize_obj_name(geometry) not in objs:
                return
            obj_child = objs[sanitize_obj_name(geometry)]
            if "beam" not in obj_child.name.lower():
                obj_child.name = f"Beam {obj_child.name}"

            if not display_beams:  # Don't even create beam objects to save resources
                return
            if any(geometry.beam_type.value == x for x in ["None", "Glow"]):
                return

            obj_child.visible_shadow = False
            light_data = bpy.data.lights.new(name=f"Spot {obj_child.name}", type="SPOT")
            light_data["flux"] = geometry.luminous_flux
            light_data["shutter_value"] = 0  # Here we will store values required for strobing
            light_data["shutter_dimmer_value"] = 0
            light_data["shutter_counter"] = 0
            light_data.energy = light_data["flux"]  # set by default to full brightness for devices without dimmer
            light_data.use_custom_distance = True
            light_data.cutoff_distance = 23

            light_data.spot_blend = calculate_spot_blend(geometry)
            light_data.spot_size = math.radians(geometry.beam_angle)
            light_data.shadow_soft_size = geometry.beam_radius
            light_data["beam_radius"] = geometry.beam_radius  # save original beam size
            light_data["beam_radius_pin_sized_for_gobos"] = True
            # This allows the user to set this if wanted to prevent beam rendering differences
            light_data.shadow_buffer_clip_start = 0.0001
            light_object = bpy.data.objects.new(name="Spot", object_data=light_data)
            light_object.hide_select = True
            light_object.parent = obj_child
            obj_child.matrix_parent_inverse = light_object.matrix_world.inverted()
            collection.objects.link(light_object)

            gobo_radius = 2.2 * 0.01 * math.tan(math.radians(geometry.beam_angle / 2))
            goboGeometry = SimpleNamespace(name=f"gobo {geometry}", length=gobo_radius, width=gobo_radius, height=0, primitive_type="Plane", beam_radius=geometry.beam_radius)
            if has_gobos:
                create_gobo(geometry, goboGeometry)

        def create_laser(geometry):
            if sanitize_obj_name(geometry) not in objs:
                return
            obj_child = objs[sanitize_obj_name(geometry)]
            if "laser" not in obj_child.name.lower():
                obj_child.name = f"Laser {obj_child.name}"
            obj_child.visible_shadow = False
            obj_child.rotation_mode = "XYZ"
            obj_child["beam_diameter"] = geometry.beam_diameter
            obj_child["rot_x"] = obj_child.rotation_euler[0]
            obj_child["rot_y"] = obj_child.rotation_euler[1]
            obj_child["rot_z"] = obj_child.rotation_euler[2]

        def create_gobo(geometry, goboGeometry):
            obj = ProfileGDTF.load_blender_primitive(goboGeometry)
            obj["geometry_type"] = "gobo"
            obj["beam_radius"] = goboGeometry.beam_radius
            obj.dimensions = (goboGeometry.length, goboGeometry.width, 0)
            obj.name = goboGeometry.name
            objs[sanitize_obj_name(goboGeometry)] = obj
            obj.location[2] += -0.01
            constraint_child_to_parent(geometry, goboGeometry)

        def calculate_spot_blend(geometry):
            """Return spot_blend value based on beam_type, maybe in the future
            we can calculate different value based on beam/field angle...?"""

            beam_type = geometry.beam_type.value
            if any(beam_type == x for x in ["Wash", "Fresnel", "PC"]):
                return 1.0
            return 0.0

        def add_child_position(geometry):
            """Add a child position"""

            # if (not sanitize_obj_name(geometry) in objs): return
            obj_child = objs[sanitize_obj_name(geometry)]
            position = Matrix(geometry.position.matrix).to_translation()

            obj_child.location[0] += position[0]
            obj_child.location[1] += position[1]
            obj_child.location[2] += position[2]

            obj_child.rotation_mode = "XYZ"
            obj_child.rotation_euler = mathutils.Matrix(geometry.position.matrix).to_euler("XYZ")
            # this makes applying rotations correct
            obj_child.rotation_euler[0] *= -1
            obj_child.rotation_euler[1] *= -1
            obj_child.rotation_euler[2] *= -1

            scale = mathutils.Matrix(geometry.position.matrix).to_scale()
            obj_child.scale[0] *= scale[0]
            obj_child.scale[1] *= scale[1]
            obj_child.scale[2] *= scale[2]

        def constraint_child_to_parent(parent_geometry, child_geometry):
            if not sanitize_obj_name(parent_geometry) in objs:
                return
            obj_parent = objs[sanitize_obj_name(parent_geometry)]
            if not sanitize_obj_name(child_geometry) in objs:
                return
            obj_child = objs[sanitize_obj_name(child_geometry)]
            obj_child.parent = obj_parent
            obj_child.matrix_parent_inverse = obj_parent.matrix_world.inverted()

        def update_geometry(geometry):
            """Recursively update objects position, rotation and scale
            and define parent/child constraints. References are new
            sub-trees that must be processed and their root marked."""

            if not isinstance(geometry, pygdtf.GeometryReference):
                # geometry reference will have different geometry
                add_child_position(geometry)

            if isinstance(geometry, pygdtf.GeometryBeam):
                create_beam(geometry)
            if isinstance(geometry, pygdtf.GeometryLaser):
                create_laser(geometry)
            elif isinstance(geometry, (pygdtf.GeometryMediaServerCamera)):
                create_camera(geometry)

            elif isinstance(geometry, pygdtf.GeometryReference):
                reference = copy.deepcopy(pygdtf.utils.get_geometry_by_name(profile, geometry.geometry))
                reference.name = sanitize_obj_name(geometry)

                # apply position of the reference
                add_child_position(reference)

                # apply position of the referring geometry
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
                            constraint_child_to_parent(reference, child_geometry)  # parent, child
                            update_geometry(child_geometry)
                return

            if hasattr(geometry, "geometries"):
                if len(geometry.geometries) > 0:
                    for child_geometry in geometry.geometries:
                        constraint_child_to_parent(geometry, child_geometry)  # parent, child
                        update_geometry(child_geometry)

        # Load 3d objects from the GDTF profile
        # The whole procedure is still quite simplified
        # We could use more hierarchical approach inside Blender
        # To represent the geometries in a kinematic chain rather then flat structure
        # Also, we mostly omit links between geometry and channel function's geometry linking
        # For places, where for example multiple yokes would exist...
        load_geometries(root_geometry)
        update_geometry(root_geometry)

        # Add target for manipulating fixture
        if add_target:
            target = bpy.data.objects.new(name="Target", object_data=None)
            collection.objects.link(target)
            target.empty_display_size = 0.5
            target.empty_display_type = "PLAIN_AXES"
            target.location = (0, 0, -2)

        def get_root():
            for obj in objs.values():
                if obj.get("geometry_root", False):
                    return obj

        def get_axis(attribute):
            for obj in objs.values():
                for channel in dmx_channels_flattened:
                    if attribute == channel["id"] and channel["geometry"] == obj.get("original_name", "None"):
                        return obj
                for channel in virtual_channels:
                    if attribute == channel["id"] and channel["geometry"] == obj.get("original_name", "None"):
                        return obj

        # This could be moved to the processing up higher,but for now, it's easier here
        head = get_axis("Tilt")
        if head:
            head["mobile_type"] = "head"
        yoke = get_axis("Pan")
        if yoke:
            yoke["mobile_type"] = "yoke"
        base = get_root()

        # If the root has a child with Pan, create Z rotation constraint
        if add_target:
            if yoke is not None:
                for name, obj in objs.items():
                    if yoke.name == obj.name:
                        if add_target:
                            constraint = obj.constraints.new("LOCKED_TRACK")
                            constraint.target = target
                            constraint.lock_axis = "LOCK_Z"
                        break

        # Track head to the target
        if add_target:
            if head is not None:
                constraint = head.constraints.new("TRACK_TO")
                constraint.target = target
            else:
                # make sure simple par fixtures can be controlled via Target
                constraint = base.constraints.new("TRACK_TO")
                constraint.target = target

        # 2D thumbnail planning symbol
        obj = ProfileGDTF.load_2d(profile)
        if obj is not None:
            # should probably always show it "on top"
            obj["2d_symbol"] = "all"
            objs["2d_symbol"] = obj
            obj.show_in_front = True
            obj.active_material.grease_pencil.show_stroke = True
            obj.data.pixel_factor = 2

            # svg.data.layers[...].frames[0].strokes[0]
            # add constraints
            constraint_copyLocation = obj.constraints.new(type="COPY_LOCATION")
            constraint_copyRotation = obj.constraints.new(type="COPY_ROTATION")
            constraint_copyLocation.target = base
            constraint_copyRotation.target = base
            constraint_copyRotation.use_z = True
            constraint_copyRotation.use_x = False
            constraint_copyRotation.use_y = False

        # Link objects to collection
        for name, obj in objs.items():
            collection.objects.link(obj)

        return collection

    @staticmethod
    def get_name(profile, dmx_mode, display_beams, add_target):
        revision = profile.revisions[-1].text if len(profile.revisions) else ""
        name = f"{profile.manufacturer}, {profile.name}, {dmx_mode}, {revision}, {'with_beams' if display_beams else 'without_beams'}, {'with_target' if add_target else 'without_target'}"
        # base64 encode the name as collections seems to have lenght limit
        # which causes collections not to be cached, thus slowing imports down
        name = hashlib.shake_256(name.encode()).hexdigest(5)
        return name
