# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
## [Unreleased]
-->

## [0.2.2] - 2025-08-01
### Added
* Support for non-contiguous descriptor indices without requiring `avoid_blockram`.
* `StreamSerializer` can now send descriptors with more than 64 bytes of content.  (tx povauboin!)

### Changed
* Deprecate `blacklist` in favor of `skiplist` in `StandardRequestHandler` method: `add_standard_request_handlers()`.

### Fixed
* `handle_write_register_write_request` is no longer limited to a 7 bit value.



## [0.2.1] - 2025-06-10
### Added
* Add support for streaming USB 2.0 Isochronous Endpoints.

## [0.2.0] - 2025-02-25
### Added
* Support for Amaranth 0.5.x
### Changed
* Use `amaranth.lib.memory.Memory` instead of `amaranth.hdl.Memory`.
### Removed
* The `synchronize` helper function. Use `amaranth.lib.cdc.FFSynchronizer` instead.
* Old examples and components that used the `debug_spi` interface.
### Security
* Bump jinja2 from 3.1.4 to 3.1.5


## [0.1.3] - 2024-12-18
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

[Unreleased]: https://github.com/greatscottgadgets/luna/compare/0.2.2...HEAD
[0.2.2]: https://github.com/greatscottgadgets/luna/compare/0.2.1...0.2.2
[0.2.1]: https://github.com/greatscottgadgets/luna/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/greatscottgadgets/luna/compare/0.1.3...0.2.0
[0.1.3]: https://github.com/greatscottgadgets/luna/compare/0.1.2...0.1.3
[0.1.2]: https://github.com/greatscottgadgets/luna/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/greatscottgadgets/luna/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/greatscottgadgets/luna/releases/tag/0.1.0
