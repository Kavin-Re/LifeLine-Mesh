## Summary

What does this change and why?

## Checklist

- [ ] `make -C c test` passes (and `make -C c san nomalloc` for C changes)
- [ ] `python3 -m unittest discover -s python/tests` passes
- [ ] Python and C stay in agreement (shared vectors regenerated if the wire format changed)
- [ ] `docs/PROTOCOL.md` updated if behaviour changed
- [ ] Documentation updated where behaviour changed
- [ ] No secrets, keys or personal data committed

## Test notes

How was this verified? Paste commands and results, or write "not run".
