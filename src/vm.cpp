#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

enum class Op {
    load_x, load_y, constant, add, subtract, multiply,
    add_constant, multiply_constant, subtract_constant,
    add_x, add_y, multiply_x, multiply_y,
    multiply_then_add, add_then_multiply
};

struct Instruction {
    Op op;
    std::uint64_t value = 0;
};

struct Fusion {
    Op first;
    Op second;
    Op replacement;
    const char* name;
};

constexpr Fusion fusions[] = {
    {Op::constant, Op::add, Op::add_constant, "constant+add"},
    {Op::constant, Op::multiply, Op::multiply_constant, "constant+multiply"},
    {Op::constant, Op::subtract, Op::subtract_constant, "constant+subtract"},
    {Op::load_x, Op::add, Op::add_x, "load_x+add"},
    {Op::load_y, Op::add, Op::add_y, "load_y+add"},
    {Op::load_x, Op::multiply, Op::multiply_x, "load_x+multiply"},
    {Op::load_y, Op::multiply, Op::multiply_y, "load_y+multiply"},
    {Op::multiply, Op::add, Op::multiply_then_add, "multiply+add"},
    {Op::add, Op::multiply, Op::add_then_multiply, "add+multiply"},
};
constexpr unsigned fusion_count = sizeof(fusions) / sizeof(fusions[0]);

std::uint64_t parse_number(const std::string& text) {
    std::uint64_t result = 0;
    const auto* begin = text.data();
    const auto* end = begin + text.size();
    const auto parsed = std::from_chars(begin, end, result);
    if (parsed.ec != std::errc{} || parsed.ptr != end) {
        throw std::runtime_error("invalid token: " + text);
    }
    return result;
}

std::vector<Instruction> compile(const std::string& source) {
    std::istringstream input(source);
    std::vector<Instruction> code;
    std::string token;
    int depth = 0;
    while (input >> token) {
        if (token == "x") {
            code.push_back({Op::load_x});
            ++depth;
        } else if (token == "y") {
            code.push_back({Op::load_y});
            ++depth;
        } else if (token == "+" || token == "-" || token == "*") {
            if (depth < 2) {
                throw std::runtime_error("operator requires two values");
            }
            code.push_back({token == "+" ? Op::add : token == "-" ? Op::subtract : Op::multiply});
            --depth;
        } else {
            code.push_back({Op::constant, parse_number(token)});
            ++depth;
        }
        if (depth > 64) {
            throw std::runtime_error("expression exceeds maximum stack depth");
        }
    }
    if (depth != 1) {
        throw std::runtime_error("expression must leave exactly one value");
    }
    return code;
}

std::vector<Instruction> fuse(const std::vector<Instruction>& code, unsigned mask) {
    std::vector<Instruction> result;
    for (std::size_t i = 0; i < code.size();) {
        bool matched = false;
        if (i + 1 < code.size()) {
            for (unsigned j = 0; j < fusion_count; ++j) {
                const Fusion& rule = fusions[j];
                if ((mask & (1u << j)) && code[i].op == rule.first && code[i + 1].op == rule.second) {
                    result.push_back({rule.replacement, code[i].value});
                    i += 2;
                    matched = true;
                    break;
                }
            }
        }
        if (!matched) {
            result.push_back(code[i]);
            ++i;
        }
    }
    return result;
}

std::uint64_t execute(const std::vector<Instruction>& code, std::uint64_t x, std::uint64_t y) {
    std::uint64_t stack[64];
    unsigned top = 0;
    for (const auto& instruction : code) {
        switch (instruction.op) {
            case Op::load_x: stack[top++] = x; break;
            case Op::load_y: stack[top++] = y; break;
            case Op::constant: stack[top++] = instruction.value; break;
            case Op::add: {
                const auto right = stack[--top];
                stack[top - 1] += right;
                break;
            }
            case Op::subtract: {
                const auto right = stack[--top];
                stack[top - 1] -= right;
                break;
            }
            case Op::multiply: {
                const auto right = stack[--top];
                stack[top - 1] *= right;
                break;
            }
            case Op::add_constant: stack[top - 1] += instruction.value; break;
            case Op::subtract_constant: stack[top - 1] -= instruction.value; break;
            case Op::multiply_constant: stack[top - 1] *= instruction.value; break;
            case Op::add_x: stack[top - 1] += x; break;
            case Op::add_y: stack[top - 1] += y; break;
            case Op::multiply_x: stack[top - 1] *= x; break;
            case Op::multiply_y: stack[top - 1] *= y; break;
            case Op::multiply_then_add: {
                const auto right = stack[--top];
                const auto left = stack[--top];
                stack[top - 1] += left * right;
                break;
            }
            case Op::add_then_multiply: {
                const auto right = stack[--top];
                const auto left = stack[--top];
                stack[top - 1] *= left + right;
                break;
            }
        }
    }
    return stack[0];
}

std::uint64_t next_random(std::uint64_t& state) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    return state;
}

void check_correctness(const std::vector<Instruction>& original,
                       const std::vector<Instruction>& optimized) {
    std::uint64_t state = 0x1a2b3c4d5e6f7081ULL;
    for (unsigned i = 0; i < 1024; ++i) {
        const auto x = next_random(state);
        const auto y = next_random(state);
        if (execute(original, x, y) != execute(optimized, x, y)) {
            throw std::runtime_error("fused program changed the result");
        }
    }
}

void self_test() {
    struct Example {
        const char* source;
        std::uint64_t x;
        std::uint64_t y;
        std::uint64_t expected;
    };
    constexpr Example examples[] = {
        {"x 3 * y +", 2, 5, 11},
        {"x y - 2 *", 9, 4, 10},
        {"x y * 7 +", 3, 4, 19},
        {"5 x -", 2, 0, 3},
        {"3 4 + x *", 2, 0, 14},
    };
    for (const auto& example : examples) {
        const auto original = compile(example.source);
        if (execute(original, example.x, example.y) != example.expected) {
            throw std::runtime_error("interpreter disagrees with a known result");
        }
        for (unsigned mask = 0; mask < (1u << fusion_count); ++mask) {
            const auto optimized = fuse(original, mask);
            if (execute(optimized, example.x, example.y) != example.expected) {
                throw std::runtime_error("fusion disagrees with a known result");
            }
            check_correctness(original, optimized);
        }
    }
}

struct Result {
    double median_ns;
    std::uint64_t checksum;
};

Result benchmark(const std::vector<Instruction>& code, std::size_t count, unsigned repetitions) {
    std::vector<std::uint64_t> xs(count), ys(count);
    std::uint64_t state = 0x52a7b8c9d0123456ULL;
    for (std::size_t i = 0; i < count; ++i) {
        xs[i] = next_random(state) & 255;
        ys[i] = next_random(state) & 255;
    }
    std::vector<double> timings;
    std::uint64_t expected_checksum = 0;
    for (unsigned repetition = 0; repetition <= repetitions; ++repetition) {
        std::uint64_t checksum = 0;
        const auto start = std::chrono::steady_clock::now();
        for (std::size_t i = 0; i < count; ++i) {
            checksum += execute(code, xs[i], ys[i]) ^ static_cast<std::uint64_t>(i);
        }
        const auto end = std::chrono::steady_clock::now();
        if (repetition == 0) {
            expected_checksum = checksum;
        } else {
            if (checksum != expected_checksum) {
                throw std::runtime_error("benchmark checksum changed between repetitions");
            }
            timings.push_back(std::chrono::duration<double, std::nano>(end - start).count() /
                              static_cast<double>(count));
        }
    }
    std::sort(timings.begin(), timings.end());
    return {timings[timings.size() / 2], expected_checksum};
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--self-test") {
            self_test();
            std::cout << "self-test passed: known answers and all 512 fusion masks\n";
            return 0;
        }
        std::string expression;
        unsigned mask = 0;
        std::size_t count = 100000;
        unsigned repetitions = 3;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (i + 1 >= argc) {
                throw std::runtime_error("missing value for " + option);
            }
            const std::string value = argv[++i];
            if (option == "--expr") expression = value;
            else if (option == "--mask") mask = static_cast<unsigned>(parse_number(value));
            else if (option == "--count") count = static_cast<std::size_t>(parse_number(value));
            else if (option == "--repetitions") repetitions = static_cast<unsigned>(parse_number(value));
            else throw std::runtime_error("unknown option: " + option);
        }
        if (expression.empty() || count == 0 || repetitions == 0 || repetitions > 100 ||
            mask >= (1u << fusion_count)) {
            throw std::runtime_error("invalid expression, mask, count, or repetitions");
        }
        const auto original = compile(expression);
        const auto optimized = fuse(original, mask);
        check_correctness(original, optimized);
        const auto result = benchmark(optimized, count, repetitions);
        std::cout << "{\"median_ns_per_item\":" << result.median_ns
                  << ",\"checksum\":" << result.checksum
                  << ",\"original_instructions\":" << original.size()
                  << ",\"optimized_instructions\":" << optimized.size()
                  << ",\"mask\":" << mask << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
