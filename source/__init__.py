# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later


import bpy
from bpy_extras.io_utils import (
    ImportHelper,
    orientation_helper,
    axis_conversion,
)
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
    CollectionProperty,
)

bl_info = {
    "name": "Import My Virtual Rig (.mvr)",
    "author": "Sebastian Sille",
    "version": (1, 1, 0),
    "blender": (4, 0, 0),
    "location": "File > Import",
    "description": "Import My Virtual Rig files",
    "warning": "",
    "filepath_url": "",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "import_mvr" in locals():
        importlib.reload(import_max)


@orientation_helper(axis_forward='Y', axis_up='Z')
class Import_mvr(bpy.types.Operator, ImportHelper):
    """Import My Virtual Rig"""
    bl_idname = "import_scene.mvr"
    bl_label = "Import MVR (.mvr)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".mvr"
    filter_glob: StringProperty(default="*.mvr", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    scale_objects: FloatProperty(
        name="Scale",
        description="Scale factor for all objects",
        min=0.0, max=10000.0,
        soft_min=0.0, soft_max=10000.0,
        default=1.0,
    )
    use_image_search: BoolProperty(
        name="Image Search",
        description="Search subdirectories for any associated images "
        "(Warning, may be slow)",
        default=True,
    )
    object_filter: EnumProperty(
        name="Object Filter", options={'ENUM_FLAG'},
        items=(('MATERIAL', "Material".rjust(12), "", 'MATERIAL_DATA', 0x1),
               ('LIGHT', "Light".rjust(11), "", 'LIGHT_DATA', 0x2),
               ('EMPTY', "Empty".rjust(11), "", 'EMPTY_AXIS', 0x4),
               ),
        description="Object types to import",
        default={'MATERIAL', 'LIGHT', 'EMPTY'},
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_target: BoolProperty(
        name="Target",
        description="Use constraint for targets",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        import_include(layout, self)
        import_transform(layout, self)

    def execute(self, context):
        from . import import_mvr
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob"))
        global_matrix = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up,).to_4x4()
        keywords["global_matrix"] = global_matrix

        return import_mvr.load(self, context, **keywords)


def import_include(layout, operator):
    header, body = layout.panel("MVR_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_image_search")
        layrow.label(text="", icon='OUTLINER_OB_IMAGE' if operator.use_image_search else 'IMAGE_DATA')
        layout.column().prop(operator, "object_filter")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_collection")
        layrow.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')


def import_transform(layout, operator):
    header, body = layout.panel("MVR_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        layout.prop(operator, "scale_objects")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_target")
        layrow.label(text="", icon='LIGHT_SPOT' if operator.use_target else 'LIGHT_HEMI')
        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")


class IO_FH_mvr(bpy.types.FileHandler):
    bl_idname = "IO_FH_mvr"
    bl_label = "MVR"
    bl_import_operator = "import_scene.mvr"
    #bl_export_operator = "export_scene.mvr"
    bl_file_extensions = ".mvr"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func(self, context):
    self.layout.operator(Import_mvr.bl_idname, text="My Virtual Rig (.mvr)")


def register():
    bpy.utils.register_class(Import_mvr)
    bpy.utils.register_class(IO_FH_mvr)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    bpy.utils.unregister_class(IO_FH_mvr)
    bpy.utils.unregister_class(Import_mvr)


if __name__ == "__main__":
    register()
