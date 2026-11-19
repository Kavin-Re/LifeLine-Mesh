# Contributing to LifeLine-Mesh

Thanks for your interest. LifeLine-Mesh is an offline emergency-message protocol with a C reference (no dynamic allocation) and a Python model; see `docs/PROTOCOL.md`.

## Getting started

C: a C99 compiler (gcc or clang) and make. Python: 3 with the standard library for the tests below.

## Testing

```
make -C c test                                     # unit tests and shared vectors
make -C c san                                      # ASan/UBSan tests and fuzzing
make -C c nomalloc                                 # checks no allocator symbols in the library
python3 -m unittest discover -s python/tests -v    # Python codec, core and simulator tests
```

The C reference builds with `-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Werror`; keep it warning-free.

## Pull requests

- Open an issue first for larger changes.
- Keep PRs focused and fill in the pull request template.
- Follow `.editorconfig` and match the style of surrounding code.
- Do not introduce dynamic allocation in the C reference.

## Conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
