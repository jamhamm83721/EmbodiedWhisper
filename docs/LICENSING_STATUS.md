# Licensing

The root MIT license applies to the project-specific hardware design, firmware and
host SDK files in this repository. The copyright line uses the repository account.

External dependencies are installed separately and retain their own licenses. This
includes ESP-IDF, the `esp32-camera` driver and Python runtime dependencies. Their
copyright notices are not removed or relicensed by this repository.

The CAD project contains component-library definitions, part numbers and tool/vendor
references required to inspect and edit the design. These are technical references,
not a statement of author affiliation. Embedded library assets retain any applicable
third-party terms. The project license does not grant rights over third-party
trademarks, datasheets or component-library services.

The ring entry point integrates its button and BLE modules. The supplied glasses
entry point is retained with an unused personal debug include removed. Build
outputs, editor settings and vendored camera-driver sources are not distributed. The camera driver is obtained from its upstream dependency.
