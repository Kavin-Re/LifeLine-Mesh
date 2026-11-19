# LifeLine-Mesh C reference. Host build: gcc/clang, C99, no dynamic allocation.
CC      ?= gcc
CSTD    := -std=c99 -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Werror
OPT     ?= -O2 -g
SRC     := $(wildcard src/*.c)
INC     := -Iinclude
BUILD   := build
SAN     := -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer
ITERS   ?= 2000000

all: $(BUILD)/test_main $(BUILD)/fuzz_main

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/test_main: $(SRC) tests/test_main.c | $(BUILD)
	$(CC) $(CSTD) $(OPT) $(INC) $^ -o $@
$(BUILD)/fuzz_main: $(SRC) fuzz/fuzz_main.c | $(BUILD)
	$(CC) $(CSTD) $(OPT) $(INC) $^ -o $@
$(BUILD)/test_san: $(SRC) tests/test_main.c | $(BUILD)
	$(CC) $(CSTD) -O1 -g $(SAN) $(INC) $^ -o $@
$(BUILD)/fuzz_san: $(SRC) fuzz/fuzz_main.c | $(BUILD)
	$(CC) $(CSTD) -O1 -g $(SAN) $(INC) $^ -o $@

test: $(BUILD)/test_main
	$(BUILD)/test_main tests
fuzz: $(BUILD)/fuzz_main
	$(BUILD)/fuzz_main $(ITERS) 1
san: $(BUILD)/test_san $(BUILD)/fuzz_san
	$(BUILD)/test_san tests
	$(BUILD)/fuzz_san $(ITERS) 1
	$(BUILD)/fuzz_san $(ITERS) 2
# the library objects must not reference any allocator
nomalloc: $(SRC) | $(BUILD)
	@for f in $(SRC); do $(CC) $(CSTD) -O2 $(INC) -c $$f -o $(BUILD)/chk.o && ! nm -u $(BUILD)/chk.o | grep -E ' (malloc|calloc|realloc|free)$$' ; done && echo "nomalloc: OK (no allocator symbols in src/*.o)"
clean:
	rm -rf $(BUILD)
.PHONY: all test fuzz san nomalloc clean
