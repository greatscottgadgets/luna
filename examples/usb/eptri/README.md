# Tri-Endpoint (eptri) Example

You'll need to build both firmware and the SoC gateware in order to use this example.

The easiest way to do both at once is to

```sh

# Build and program:
$ make program

# Or just build:
$ make soc.bit
```

### Firmware

The included firmware is heavily intended as a quick example, and doesn't go as far as a full USB stack
should. Accordingly, it e.g. may fail the first (non-compliant) enumeration attempt on Linux.
