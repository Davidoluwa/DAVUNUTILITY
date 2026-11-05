CXX ?= g++
CXXFLAGS ?= -O3 -march=native -std=c++17 -pthread -Wall -Wno-unused-function
SRC = src/gguf.cpp src/quants.cpp src/tokenizer.cpp src/model.cpp
HDR = $(wildcard src/*.h)

all: build/run build/inspect build/test_quants build/tokenize build/membw build/diskbw

build/%: tools/%.cpp $(SRC) $(HDR) | build
	$(CXX) $(CXXFLAGS) $< $(SRC) -o $@

build/membw: bench/membw.c | build
	$(CC) -O3 -march=native -pthread $< -o $@

build/diskbw: bench/diskbw.c | build
	$(CC) -O2 -pthread $< -o $@

build:
	mkdir -p build

clean:
	rm -rf build

.PHONY: all clean
