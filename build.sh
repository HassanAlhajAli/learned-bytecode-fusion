#!/usr/bin/env bash
set -euo pipefail
mkdir -p build
c++ -O2 -std=c++17 -Wall -Wextra -pedantic src/vm.cpp -o build/fusion_vm
