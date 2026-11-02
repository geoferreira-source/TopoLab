def classFactory(iface):
    """Ponto de entrada chamado pelo QGIS."""
    from .plugin import TopoLabPlugin
    return TopoLabPlugin(iface)
