"""Compatibilidade entre QGIS 3 (Qt5/PyQt5) e QGIS 4 (Qt6/PyQt6).

No PyQt6 os enums só existem na forma qualificada (``Qt.WindowType.Window``, não
``Qt.Window``) e o QGIS moveu vários enums para o namespace ``Qgis`` (por exemplo
``QgsProcessing.TypeVectorPoint`` -> ``Qgis.ProcessingSourceType.VectorPoint``).
Os enums do Qt são escritos direto no código já na forma qualificada, que funciona
nas duas versões. Os do QGIS ficam aqui, resolvidos uma única vez: tenta-se o nome
novo e, se não existir (QGIS 3 antigo), o nome antigo.
"""
from qgis.core import (
    Qgis, QgsFeatureSink, QgsMapLayerProxyModel, QgsProcessing,
    QgsProcessingParameterDefinition, QgsProcessingParameterField,
    QgsProcessingParameterNumber, QgsWkbTypes,
)

_NS = {
    "Qgis": Qgis, "QgsFeatureSink": QgsFeatureSink, "QgsMapLayerProxyModel": QgsMapLayerProxyModel,
    "QgsProcessing": QgsProcessing, "QgsProcessingParameterDefinition": QgsProcessingParameterDefinition,
    "QgsProcessingParameterField": QgsProcessingParameterField,
    "QgsProcessingParameterNumber": QgsProcessingParameterNumber, "QgsWkbTypes": QgsWkbTypes,
}


def resolve(*paths):
    """Primeiro nome pontilhado (ex.: 'Qgis.WkbType.Point') que existir nesta versão do QGIS."""
    for path in paths:
        head, *rest = path.split(".")
        obj = _NS.get(head)
        try:
            for name in rest:
                obj = getattr(obj, name)
        except AttributeError:
            continue
        if obj is not None:
            return obj
    raise AttributeError("TopoLab: nenhum destes nomes existe nesta versão do QGIS: "
                         + ", ".join(paths))


# Tipos de camada aceitos pelos parâmetros do Processing
SOURCE_POINT = resolve("Qgis.ProcessingSourceType.VectorPoint", "QgsProcessing.TypeVectorPoint")
SOURCE_LINE = resolve("Qgis.ProcessingSourceType.VectorLine", "QgsProcessing.TypeVectorLine")
SOURCE_POLYGON = resolve("Qgis.ProcessingSourceType.VectorPolygon", "QgsProcessing.TypeVectorPolygon")

# Parâmetros numéricos e de campo
NUM_DOUBLE = resolve("Qgis.ProcessingNumberParameterType.Double",
                     "QgsProcessingParameterNumber.Type.Double", "QgsProcessingParameterNumber.Double")
NUM_INTEGER = resolve("Qgis.ProcessingNumberParameterType.Integer",
                      "QgsProcessingParameterNumber.Type.Integer", "QgsProcessingParameterNumber.Integer")
FIELD_NUMERIC = resolve("Qgis.ProcessingFieldParameterDataType.Numeric",
                        "QgsProcessingParameterField.DataType.Numeric",
                        "QgsProcessingParameterField.Numeric")
FIELD_ANY = resolve("Qgis.ProcessingFieldParameterDataType.Any",
                    "QgsProcessingParameterField.DataType.Any", "QgsProcessingParameterField.Any")
FLAG_ADVANCED = resolve("Qgis.ProcessingParameterFlag.Advanced",
                        "QgsProcessingParameterDefinition.Flag.FlagAdvanced",
                        "QgsProcessingParameterDefinition.FlagAdvanced")

# Gravação de feições
FAST_INSERT = resolve("QgsFeatureSink.Flag.FastInsert", "QgsFeatureSink.FastInsert")

# Tipos de geometria (WKB) e famílias de geometria
WKB_POINT = resolve("Qgis.WkbType.Point", "QgsWkbTypes.Type.Point", "QgsWkbTypes.Point")
WKB_POINTZ = resolve("Qgis.WkbType.PointZ", "QgsWkbTypes.Type.PointZ", "QgsWkbTypes.PointZ")
WKB_LINESTRING = resolve("Qgis.WkbType.LineString", "QgsWkbTypes.Type.LineString",
                         "QgsWkbTypes.LineString")
WKB_POLYGON = resolve("Qgis.WkbType.Polygon", "QgsWkbTypes.Type.Polygon", "QgsWkbTypes.Polygon")
WKB_MULTIPOLYGON = resolve("Qgis.WkbType.MultiPolygon", "QgsWkbTypes.Type.MultiPolygon",
                           "QgsWkbTypes.MultiPolygon")
WKB_LINESTRINGZ = resolve("Qgis.WkbType.LineStringZ", "QgsWkbTypes.Type.LineStringZ",
                          "QgsWkbTypes.LineStringZ")
GEOM_POINT = resolve("Qgis.GeometryType.Point", "QgsWkbTypes.GeometryType.PointGeometry",
                     "QgsWkbTypes.PointGeometry")
GEOM_LINE = resolve("Qgis.GeometryType.Line", "QgsWkbTypes.GeometryType.LineGeometry",
                    "QgsWkbTypes.LineGeometry")
GEOM_POLYGON = resolve("Qgis.GeometryType.Polygon", "QgsWkbTypes.GeometryType.PolygonGeometry",
                       "QgsWkbTypes.PolygonGeometry")

# Filtros dos combos de camadas
LAYER_POINT = resolve("Qgis.LayerFilter.PointLayer", "QgsMapLayerProxyModel.Filter.PointLayer",
                      "QgsMapLayerProxyModel.PointLayer")
LAYER_LINE = resolve("Qgis.LayerFilter.LineLayer", "QgsMapLayerProxyModel.Filter.LineLayer",
                     "QgsMapLayerProxyModel.LineLayer")
LAYER_POLYGON = resolve("Qgis.LayerFilter.PolygonLayer", "QgsMapLayerProxyModel.Filter.PolygonLayer",
                        "QgsMapLayerProxyModel.PolygonLayer")
LAYER_RASTER = resolve("Qgis.LayerFilter.RasterLayer", "QgsMapLayerProxyModel.Filter.RasterLayer",
                       "QgsMapLayerProxyModel.RasterLayer")

# Tipos dos campos (QgsField). Desde o QGIS 3.38 o tipo é um QMetaType.Type; no Qt6 o
# QVariant.Type nem existe mais no Python. Antes do 3.38, só QVariant.Type é aceito.
if Qgis.QGIS_VERSION_INT >= 33800:
    from qgis.PyQt.QtCore import QMetaType
    TYPE_DOUBLE, TYPE_INT, TYPE_STRING = (QMetaType.Type.Double, QMetaType.Type.Int,
                                          QMetaType.Type.QString)
else:
    from qgis.PyQt.QtCore import QVariant
    TYPE_DOUBLE, TYPE_INT, TYPE_STRING = QVariant.Double, QVariant.Int, QVariant.String

# QAction mudou de QtWidgets (Qt5) para QtGui (Qt6)
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction


__all__ = [
    "resolve", "is_null", "QAction",
    "SOURCE_POINT", "SOURCE_LINE", "SOURCE_POLYGON", "NUM_DOUBLE", "NUM_INTEGER",
    "FIELD_NUMERIC", "FIELD_ANY", "FLAG_ADVANCED", "FAST_INSERT",
    "WKB_POINT", "WKB_POINTZ", "WKB_LINESTRING", "WKB_LINESTRINGZ", "WKB_POLYGON",
    "WKB_MULTIPOLYGON",
    "GEOM_POINT", "GEOM_LINE", "GEOM_POLYGON",
    "LAYER_POINT", "LAYER_LINE", "LAYER_POLYGON", "LAYER_RASTER",
    "TYPE_DOUBLE", "TYPE_INT", "TYPE_STRING",
]


def is_null(value):
    """Valor de atributo vazio: None, NULL do QGIS (QVariant nulo no Qt5) ou texto vazio."""
    return value is None or str(value) in ("NULL", "")
