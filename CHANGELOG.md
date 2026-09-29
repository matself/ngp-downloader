# Changelog

All notable changes to NGP Downloader (Lantmäteriet) are documented in this file.

## [Unreleased]

## [1.0.1]
- Renamed to "Geodata: NGP (Lantmäteriet)" with a new icon, part of a
  shared naming/icon scheme across the four Lantmäteriet plugins

## [1.0.0]
- First stable release, published to the official QGIS plugin repository
- Dropped the "not in the official plugin repository" install instructions from the README
- No longer marked experimental

## [0.4.5]
- Added a user guide, linked from the README ([docs/anvandning.md](docs/anvandning.md))

## [0.4.4]
- Show the "not affiliated with Lantmäteriet" independence note in the panel UI

## [0.4.3]
- Renamed plugin to **NGP Downloader (Lantmäteriet)** and clarified in the description that it is an independent plugin, not made by Lantmäteriet
- Release zip is now named `<package>.<version>.zip`

## [0.4.2]
- NGP download progress is now shown as an object count instead of a generic progress bar

## [0.4.1]
- README: documented where to get NGP credentials

## [0.4.0]
- Added RAÄ lämningsregister (Riksantikvarieämbetets ancient monument register) as a download source, with Fornsök-style defaults

## [0.3.1]
- Added styles for Strandskydd and Kulturhistorisk lämning

## [0.3.0]
- Detaljplan styles per BFS 2020:6, symbol rasters, merged properties
- Detaljplan: catalog notation, split per type, merged combinations, styles

## [0.2.0]
- Drop geometry-less noise, show municipality names
- Added resource download ("resurshämtning")

## [0.1.1]
- Added plugin icon

## [0.1.0]
- Split mixed geometries into layers, clarify 404s, mark datasets verified
- Renamed plugin to "NGP nedladdning" and added build script
- Initial QGIS plugin skeleton for NGP downloads

[Unreleased]: https://github.com/matself/ngp-downloader/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/matself/ngp-downloader/compare/v0.4.5...v1.0.0
[0.4.5]: https://github.com/matself/ngp-downloader/compare/v0.4.4...v0.4.5
[0.4.4]: https://github.com/matself/ngp-downloader/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/matself/ngp-downloader/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/matself/ngp-downloader/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/matself/ngp-downloader/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/matself/ngp-downloader/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/matself/ngp-downloader/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/matself/ngp-downloader/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/matself/ngp-downloader/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/matself/ngp-downloader/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/matself/ngp-downloader/releases/tag/v0.1.0
