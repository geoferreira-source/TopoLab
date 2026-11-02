from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from ..resources import icon_path
from .alg_platform import PlatformAlgorithm
from .alg_profiles import CrossSectionsAlgorithm, ProfileAlgorithm
from .alg_quality import CheckPointsAlgorithm
from .alg_raster import RasterToPointsAlgorithm
from .alg_thematic import (
    CutFillMapAlgorithm, ElevationBandsAlgorithm, FloodMapAlgorithm, SlopeMapAlgorithm,
)
from .alg_tin_contours import TinContoursAlgorithm
from .alg_volumes import VolumeBetweenAlgorithm, VolumeDatumAlgorithm


class TopoLabProvider(QgsProcessingProvider):
    def id(self):
        return "topolab"

    def name(self):
        return "TopoLab"

    def icon(self):
        return QIcon(icon_path())

    def loadAlgorithms(self):
        self.addAlgorithm(RasterToPointsAlgorithm())
        self.addAlgorithm(CheckPointsAlgorithm())
        self.addAlgorithm(TinContoursAlgorithm())
        self.addAlgorithm(VolumeDatumAlgorithm())
        self.addAlgorithm(VolumeBetweenAlgorithm())
        self.addAlgorithm(PlatformAlgorithm())
        self.addAlgorithm(ProfileAlgorithm())
        self.addAlgorithm(CrossSectionsAlgorithm())
        for alg in (SlopeMapAlgorithm, ElevationBandsAlgorithm, FloodMapAlgorithm,
                    CutFillMapAlgorithm):
            self.addAlgorithm(alg())
        # Próximas fases: poligonais, memorial descritivo...
