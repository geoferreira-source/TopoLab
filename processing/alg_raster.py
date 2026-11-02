from qgis.core import (
    QgsFeature, QgsField, QgsFields, QgsGeometry, QgsPoint, QgsProcessingAlgorithm,
    QgsProcessingException, QgsProcessingParameterFeatureSink, QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
)

from ..adapters.raster_adapter import raster_points
from ..compat import FAST_INSERT, NUM_INTEGER, SOURCE_POINT, TYPE_DOUBLE, WKB_POINTZ


class RasterToPointsAlgorithm(QgsProcessingAlgorithm):
    INPUT, BAND, STEP, OUTPUT = "INPUT", "BAND", "STEP", "OUTPUT"

    def name(self):
        return "raster_to_points"

    def displayName(self):
        return "MDE (raster) em pontos cotados"

    def group(self):
        return "Superfície"

    def groupId(self):
        return "surface"

    def createInstance(self):
        return RasterToPointsAlgorithm()

    def shortHelpString(self):
        return ("Converte um MDE em raster (GeoTIFF etc.) em pontos cotados no centro das "
                "células, para usar nas demais ferramentas do TopoLab (TIN, curvas, volumes, "
                "perfis e seções). O passo pega 1 célula a cada N, o que controla o tamanho "
                "do TIN. Células sem dado (nodata) são ignoradas.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT, "MDE (raster)"))
        self.addParameter(QgsProcessingParameterNumber(
            self.BAND, "Banda", NUM_INTEGER, defaultValue=1, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.STEP, "Passo (1 célula a cada N)", NUM_INTEGER,
            defaultValue=1, minValue=1))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Pontos cotados", SOURCE_POINT))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if layer is None:
            raise QgsProcessingException(self.invalidRasterError(parameters, self.INPUT))
        band = self.parameterAsInt(parameters, self.BAND, context)
        step = self.parameterAsInt(parameters, self.STEP, context)
        if layer.crs().isGeographic():
            feedback.pushWarning("O MDE está em CRS geográfico (graus). Reprojete para UTM "
                                 "antes de calcular distâncias, áreas e volumes.")
        pts = raster_points(layer, band, step)
        feedback.pushInfo(f"{len(pts)} pontos a partir de {layer.width()}x{layer.height()} células.")

        fields = QgsFields()
        fields.append(QgsField("COTA", TYPE_DOUBLE))
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                          WKB_POINTZ, layer.crs())
        total = len(pts)
        for i, (x, y, z) in enumerate(pts):
            if i % 5000 == 0:
                if feedback.isCanceled():
                    break
                feedback.setProgress(100 * i / total)
            f = QgsFeature(fields)
            f.setGeometry(QgsGeometry(QgsPoint(float(x), float(y), float(z))))
            f.setAttributes([float(z)])
            sink.addFeature(f, FAST_INSERT)
        return {self.OUTPUT: dest}
