# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
## [Unreleased]
-->

## [0.1.3] - 2024-09-19
### Added
* Support for yowasp when yosys is unavailable.
### Changed
* Dropped support for Python 3.8


## [0.1.2] - 2024-09-19
### Changed
* Use `debugger.force_fpga_online()` instead of `programmer.unconfigure()` to take FPGA offline.
* Remove unused/out-of-date imports from PIPE PHY example.


## [0.1.1] - 2024-07-05
### Added
- New `LUNAApolloPlatform` property: `apollo_gateware_phy`
- Support for `ClearFeature(ENDPOINT_HALT)`
### Changed
- Remove Cynthion VID/PIDs from udev rules


## [0.1.0] - 2024-06-12
### Added
- Initial release

[Unreleased]: https://github.com/greatscottgadgets/luna/compare/0.1.3...HEAD
[0.1.3]: https://github.com/greatscottgadgets/luna/compare/0.1.2...0.1.3
[0.1.2]: https://github.com/greatscottgadgets/luna/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/greatscottgadgets/luna/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/greatscottgadgets/luna/releases/tag/0.1.0
