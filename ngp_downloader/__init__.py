def classFactory(iface):
    from .plugin import NgpDownloaderPlugin

    return NgpDownloaderPlugin(iface)
